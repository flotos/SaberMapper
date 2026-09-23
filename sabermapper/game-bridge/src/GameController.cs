using System;
using System.Collections;
using System.Collections.Concurrent;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using IPA.Utilities;
using Newtonsoft.Json.Linq;
using UnityEngine;

namespace SaberMapperBridge
{
    /// <summary>Unity-side controller: runs queued commands on the main thread, publishes a state snapshot every
    /// frame for the HTTP threads, starts levels through MenuTransitionsHelper with practice start time/speed and
    /// drives pause, restart-at-time and return-to-menu through the game's own controllers.</summary>
    internal class GameController : MonoBehaviour
    {
        private const BindingFlags Any = BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

        public CaptureController Capture;
        private readonly ConcurrentQueue<Action> _queue = new ConcurrentQueue<Action>();
        private int _mainThreadId;
        private string _gameVersion, _unityVersion;
        private int _pid;

        // Snapshot shared with HTTP threads.
        private readonly object _stateLock = new object();
        private JObject _snapshot = new JObject { ["scene"] = "loading" };
        private long _version;
        private string _snapshotKey = "";

        // Game references (main thread only).
        private GameScenesManager _scenes;
        private MenuTransitionsHelper _menu;
        private AudioTimeSyncController _audio;
        private int _audioSearchCountdown;
        private bool _markerOpen, _levelSeen;
        private string _currentLevelPath, _currentLevelId;
        private float _fps;

        // Level control state.
        private PendingLoad _pending;
        private bool _returningToMenu;
        private PendingLoad _lastLoad;
        private string _lastEndState;
        private bool _showResults;
        private string _lastError;
        private int _songsLoadedEvents;
        private volatile bool _songsLoading;

        private class PendingLoad
        {
            public BeatmapLevel Level;
            public string LevelPath;
            public BeatmapCharacteristicSO Characteristic;
            public BeatmapDifficulty Difficulty;
            public float StartTime, Speed;
            public bool NoFail, Hud;
            public JObject Describe() => new JObject
            {
                ["level_id"] = Level.levelID, ["level_path"] = LevelPath, ["characteristic"] = Characteristic.serializedName,
                ["difficulty"] = Difficulty.ToString(), ["start_time"] = StartTime, ["speed"] = Speed,
                ["modifiers"] = NoFail ? "no_fail" : "player", ["hud"] = Hud,
            };
        }

        private void Awake()
        {
            _mainThreadId = Thread.CurrentThread.ManagedThreadId;
            _gameVersion = UnityGame.GameVersion.ToString();
            _unityVersion = Application.unityVersion;
            _pid = System.Diagnostics.Process.GetCurrentProcess().Id;
            Capture = new CaptureController(this);
            if (Plugin.Config.RunInBackground) Application.runInBackground = true;
            SongCore.Loader.SongsLoadedEvent += (loader, levels) => Interlocked.Increment(ref _songsLoadedEvents);
            StartCoroutine(EndOfFrameLoop());
        }

        // ---------------------------------------------------------------- threading

        public JToken Invoke(Func<JToken> work, int timeoutMs = 15000)
        {
            if (Thread.CurrentThread.ManagedThreadId == _mainThreadId) return work();
            JToken result = null;
            Exception error = null;
            using (var done = new ManualResetEventSlim(false))
            {
                _queue.Enqueue(() =>
                {
                    try { result = work(); }
                    catch (Exception e) { error = e; }
                    finally { done.Set(); }
                });
                if (!done.Wait(timeoutMs))
                    throw new BridgeException("timeout", $"The game main thread did not answer within {timeoutMs} ms (loading or frozen)", 504);
            }
            if (error is BridgeException) throw error;
            if (error != null) throw new BridgeException("bridge_internal", error.GetType().Name + ": " + error.Message, 500,
                new JObject { ["trace"] = error.StackTrace });
            return result;
        }

        private void Update()
        {
            while (_queue.TryDequeue(out var action)) action();
            float dt = Time.unscaledDeltaTime;
            if (dt > 0) _fps = _fps <= 0 ? 1f / dt : Mathf.Lerp(_fps, 1f / dt, 0.1f);
            try
            {
                RefreshReferences();
                TrackLevel();
                TryStartPending();
            }
            catch (Exception e)
            {
                _lastError = e.Message;
                Plugin.Log.Error($"update failed: {e}");
                if (_pending != null) { _pending = null; _returningToMenu = false; }
            }
            PublishSnapshot();
        }

        private IEnumerator EndOfFrameLoop()
        {
            var wait = new WaitForEndOfFrame();
            while (true)
            {
                yield return wait;
                try { Capture.OnEndOfFrame(); }
                catch (Exception e) { Capture.Fail(e); Plugin.Log.Error($"capture failed: {e}"); }
            }
        }

        /// <summary>Takes this frame's capture requests once every Update has set the song time, and opens or closes the
        /// capture's notes-hidden window (closed as soon as no level is playing). Notes are hidden at the first camera
        /// cull, after every LateUpdate.</summary>
        private void LateUpdate()
        {
            bool inLevel = InLevel && !InTransition;
            try { Capture.Schedule(inLevel, inLevel && _audio.state == AudioTimeSyncController.State.Playing, inLevel ? _audio.songTime : -1f); }
            catch (Exception e) { Capture.Fail(e); Plugin.Log.Error($"capture failed: {e}"); }
        }

        // ---------------------------------------------------------------- state

        internal bool InLevel => _audio != null && _audio.isActiveAndEnabled;
        internal float SongTime => InLevel ? _audio.songTime : -1f;
        internal float SongLength => InLevel ? _audio.songLength : -1f;

        private bool InTransition => _scenes != null && _scenes.isInTransition;

        private string Scene
        {
            get
            {
                if (InTransition || _returningToMenu || (_pending != null)) return "loading";
                if (InLevel) return "game";
                return _showResults ? "results" : "menu";
            }
        }

        /// <summary>A scene instance of T (FindObjectsOfTypeAll also returns prefabs and assets with null injections).</summary>
        private static T Live<T>(Func<T, bool> ready = null) where T : Component =>
            Resources.FindObjectsOfTypeAll<T>().FirstOrDefault(c => c != null && c.gameObject.scene.IsValid() && (ready == null || ready(c)));

        private static bool Injected(MenuTransitionsHelper helper) =>
            typeof(MenuTransitionsHelper).GetField("_gameScenesManager", Any)?.GetValue(helper) != null
            && typeof(MenuTransitionsHelper).GetField("_standardLevelScenesTransitionSetupData", Any)?.GetValue(helper) != null;

        private void RefreshReferences()
        {
            if (_scenes == null) _scenes = Live<GameScenesManager>();
            if (_menu == null) _menu = Live<MenuTransitionsHelper>(Injected);
            _songsLoading = SongCore.Loader.AreSongsLoading;
            if (_audio != null && !_audio.isActiveAndEnabled) _audio = null;
            if (_audio == null && --_audioSearchCountdown <= 0)
            {
                _audioSearchCountdown = 10;
                _audio = FindObjectOfType<AudioTimeSyncController>();
            }
        }

        private void TrackLevel()
        {
            if (_returningToMenu && _pending == null && !InLevel && !InTransition) _returningToMenu = false;
            if (InLevel)
            {
                if (!_levelSeen && _audio.state == AudioTimeSyncController.State.Playing)
                {
                    _levelSeen = true;
                    _showResults = false;
                    var setup = CurrentSetup();
                    _currentLevelId = setup?.beatmapLevel?.levelID;
                    _currentLevelPath = LevelPathFor(_currentLevelId);
                    if (!_markerOpen) OpenMarker(_currentLevelPath ?? _currentLevelId); // started outside the bridge
                }
            }
            else if (_markerOpen && _levelSeen && !InTransition)
            {
                _markerOpen = _levelSeen = false;
                Plugin.Log.Info("level_end");
            }
        }

        /// <summary>`level_start` is logged before the beatmap is deserialized (load or restart), so Heck/Vivify
        /// parse errors fall inside the level's log scope for `sabermapper game logs --level`.</summary>
        private void OpenMarker(string level)
        {
            if (_markerOpen) Plugin.Log.Info("level_end");
            Plugin.Log.Info($"level_start {level}");
            _markerOpen = true;
            _levelSeen = false;
        }

        private StandardLevelScenesTransitionSetupDataSO CurrentSetup()
        {
            if (_menu == null) return null;
            return (StandardLevelScenesTransitionSetupDataSO)typeof(MenuTransitionsHelper)
                .GetField("_standardLevelScenesTransitionSetupData", Any)?.GetValue(_menu);
        }

        private JObject LevelInfo()
        {
            if (!InLevel) return null;
            var setup = CurrentSetup();
            if (setup == null) return null;
            var key = setup.beatmapKey;
            return new JObject
            {
                ["level_id"] = key.levelId,
                ["level_path"] = _currentLevelPath ?? LevelPathFor(key.levelId),
                ["characteristic"] = key.beatmapCharacteristic != null ? key.beatmapCharacteristic.serializedName : null,
                ["difficulty"] = key.difficulty.ToString(),
                ["song_name"] = setup.beatmapLevel?.songName,
                ["practice_start_time"] = setup.practiceSettings != null ? (JToken)setup.practiceSettings.startSongTime : null,
            };
        }

        private void PublishSnapshot()
        {
            bool inLevel = InLevel;
            var capture = Capture.Status(false);
            var scene = Scene;
            var level = LevelInfo();
            bool paused = inLevel && _audio.state == AudioTimeSyncController.State.Paused;
            var snap = new JObject
            {
                ["scene"] = scene,
                ["level"] = level,
                ["song_time"] = inLevel ? (JToken)Math.Round(_audio.songTime, 4) : null,
                ["song_length"] = inLevel ? (JToken)Math.Round(_audio.songLength, 3) : null,
                ["paused"] = paused,
                ["speed"] = inLevel ? (JToken)Math.Round(_audio.timeScale, 4) : null,
                ["fps"] = Math.Round(_fps, 1),
                ["capture"] = capture,
                ["autoplay"] = false,
                ["songs_loading"] = _songsLoading,
                ["songs_ready"] = SongCore.Loader.Instance != null && SongCore.Loader.AreSongsLoaded && !_songsLoading && _menu != null,
                ["songs_loaded_events"] = _songsLoadedEvents,
                ["pending_load"] = _pending?.Describe(),
                ["last_load"] = _lastLoad?.Describe(),
                ["last_end_state"] = _lastEndState,
                ["last_error"] = _lastError,
                ["realtime"] = Math.Round(Time.realtimeSinceStartup, 3),
            };
            var key = string.Join("|", scene, level?["level_id"], paused, _songsLoading, _songsLoadedEvents,
                capture?["status"], capture?["captured"], capture?["written"], _lastEndState, _lastError, _pending != null);
            lock (_stateLock)
            {
                if (key != _snapshotKey) { _snapshotKey = key; _version++; Monitor.PulseAll(_stateLock); }
                snap["version"] = _version;
                _snapshot = snap;
            }
        }

        public JToken Health()
        {
            JObject snap;
            lock (_stateLock) snap = _snapshot;
            return new JObject
            {
                ["bridge_version"] = Plugin.Version, ["game_version"] = _gameVersion, ["unity_version"] = _unityVersion,
                ["scene"] = snap["scene"], ["pid"] = _pid, ["port"] = Plugin.Config.Port,
            };
        }

        public JToken WaitState(int waitMs, long since)
        {
            lock (_stateLock)
            {
                if (waitMs > 0)
                {
                    long target = since >= 0 ? since : _version;
                    var deadline = DateTime.UtcNow.AddMilliseconds(Math.Min(waitMs, 60000));
                    while (_version == target)
                    {
                        var remaining = (int)(deadline - DateTime.UtcNow).TotalMilliseconds;
                        if (remaining <= 0) break;
                        Monitor.Wait(_stateLock, remaining);
                    }
                }
                return _snapshot.DeepClone();
            }
        }

        // ---------------------------------------------------------------- songs

        public JToken Refresh(bool full, int waitMs)
        {
            int before = _songsLoadedEvents;
            Invoke(() =>
            {
                if (InLevel || InTransition || _pending != null)
                    throw new BridgeException("not_in_menu", "SongCore reloads songs only in the menu; POST /menu first", 409,
                        new JObject { ["scene"] = Scene });
                if (SongCore.Loader.Instance == null)
                    throw new BridgeException("songs_not_ready", "SongCore has not initialized yet (the menu is still loading); retry shortly", 409);
                SongCore.Loader.Instance.RefreshSongs(full);
                _songsLoading = true;
                return null;
            });
            bool done = false;
            var deadline = DateTime.UtcNow.AddMilliseconds(Math.Min(Math.Max(waitMs, 0), 300000));
            while (waitMs > 0 && DateTime.UtcNow < deadline)
            {
                if (_songsLoadedEvents > before) { done = true; break; }
                Thread.Sleep(50);
            }
            return Invoke(() => new JObject
            {
                ["refreshing"] = !done && SongCore.Loader.AreSongsLoading,
                ["completed"] = done,
                ["full"] = full,
                ["custom_levels"] = SongCore.Loader.CustomLevels.Count,
                ["wip_levels"] = SongCore.Loader.CustomWIPLevels.Count,
                ["songs_loaded_events"] = _songsLoadedEvents,
            });
        }

        private static string NormalizePath(string path)
        {
            try { path = Path.GetFullPath(path); } catch (Exception) { }
            return path.Replace('/', '\\').TrimEnd('\\').ToLowerInvariant();
        }

        private static string LevelPathFor(string levelId)
        {
            if (string.IsNullOrEmpty(levelId)) return null;
            foreach (var dict in new[] { SongCore.Loader.CustomWIPLevels, SongCore.Loader.CustomLevels })
                foreach (var pair in dict)
                    if (pair.Value != null && pair.Value.levelID == levelId) return pair.Key;
            return null;
        }

        private BeatmapLevel FindLevel(string levelPath, string levelId, out string resolvedPath)
        {
            resolvedPath = null;
            if (!string.IsNullOrEmpty(levelPath))
            {
                var wanted = NormalizePath(levelPath);
                foreach (var dict in new[] { SongCore.Loader.CustomWIPLevels, SongCore.Loader.CustomLevels })
                    foreach (var pair in dict)
                        if (NormalizePath(pair.Key) == wanted) { resolvedPath = pair.Key; return pair.Value; }
                throw new BridgeException("level_not_found", $"No loaded custom or WIP level at {levelPath}", 404, new JObject
                {
                    ["level_path"] = levelPath, ["fix"] = "Install the map, then POST /refresh (full=true after replacing files) and retry",
                    ["wip_levels"] = new JArray(SongCore.Loader.CustomWIPLevels.Keys.Take(50).ToArray()),
                });
            }
            if (!string.IsNullOrEmpty(levelId))
            {
                var level = SongCore.Loader.GetLevelById(levelId) ?? SongCore.Loader.BeatmapLevelsModelSO?.GetBeatmapLevel(levelId);
                if (level == null) throw new BridgeException("level_not_found", $"No level with id {levelId}", 404, new JObject { ["level_id"] = levelId });
                resolvedPath = LevelPathFor(level.levelID);
                return level;
            }
            throw new BridgeException("bad_request", "load needs level_path or level_id");
        }

        // ---------------------------------------------------------------- level control

        public JToken Load(JObject input)
        {
            if (SongCore.Loader.Instance == null || SongCore.Loader.AreSongsLoading || !SongCore.Loader.AreSongsLoaded)
                throw new BridgeException("songs_loading", "SongCore is still loading songs; wait for POST /refresh to complete", 409);
            var level = FindLevel(BridgeServer.OptString(input, "level_path"), BridgeServer.OptString(input, "level_id"), out var path);
            var characteristicName = BridgeServer.OptString(input, "characteristic", "Standard");
            var characteristic = SongCore.Loader.beatmapCharacteristicCollection.GetBeatmapCharacteristicBySerializedName(characteristicName);
            var available = level.GetCharacteristics().Select(c => c.serializedName).ToArray();
            if (characteristic == null || !available.Contains(characteristic.serializedName))
                throw new BridgeException("characteristic_not_found", $"Level has no {characteristicName} characteristic", 404,
                    new JObject { ["available"] = new JArray(available) });
            var difficulties = level.GetDifficulties(characteristic).ToArray();
            var difficultyName = BridgeServer.OptString(input, "difficulty");
            BeatmapDifficulty difficulty;
            if (string.IsNullOrEmpty(difficultyName)) difficulty = difficulties.Max();
            else if (!BeatmapDifficultySerializedMethods.BeatmapDifficultyFromSerializedName(difficultyName, out difficulty) || !difficulties.Contains(difficulty))
                throw new BridgeException("difficulty_not_found", $"Level has no {characteristicName} {difficultyName} difficulty", 404,
                    new JObject { ["available"] = new JArray(difficulties.Select(d => d.ToString()).ToArray()) });
            var speed = BridgeServer.OptFloat(input, "speed", 1f);
            if (speed < 0.1f || speed > 3f) throw new BridgeException("bad_request", "speed must be within 0.1..3.0");
            var start = Mathf.Max(0f, BridgeServer.OptFloat(input, "start_time", 0f));
            if (level.songDuration > 1f && start >= level.songDuration)
                throw new BridgeException("bad_request", $"start_time {start} is past the song end ({level.songDuration:0.###} s)");
            CheckRequirements(level, characteristic, difficulty, path);
            _pending = new PendingLoad
            {
                Level = level, LevelPath = path, Characteristic = characteristic, Difficulty = difficulty, StartTime = start, Speed = speed,
                NoFail = BridgeServer.OptString(input, "modifiers", "no_fail") != "player",
                Hud = BridgeServer.OptBool(input, "hud", true),
            };
            _lastError = null;
            bool leaving = InLevel;
            if (leaving) ReturnToMenu();
            return new JObject { ["accepted"] = true, ["returning_to_menu"] = leaving, ["load"] = _pending.Describe() };
        }

        private static void CheckRequirements(BeatmapLevel level, BeatmapCharacteristicSO characteristic, BeatmapDifficulty difficulty, string path)
        {
            SongCore.Data.SongData.DifficultyData data = null;
            try { data = SongCore.Collections.GetCustomLevelSongDifficultyData(new BeatmapKey(level.levelID, characteristic, difficulty)); }
            catch (Exception) { }
            var requirements = data?.additionalDifficultyData?._requirements ?? new string[0];
            var capabilities = SongCore.Collections.capabilities;
            var missing = requirements.Where(r => !capabilities.Contains(r)).ToArray();
            if (missing.Length == 0) return;
            foreach (var m in missing) Plugin.Log.Error($"missing requirement {m} for {path ?? level.levelID}");
            throw new BridgeException("missing_requirement", "The map needs mods that are not installed or enabled: " + string.Join(", ", missing), 409,
                new JObject { ["missing"] = new JArray(missing), ["installed_capabilities"] = new JArray(capabilities.ToArray()) });
        }

        private void TryStartPending()
        {
            if (_pending == null || InTransition || SongCore.Loader.AreSongsLoading) return;
            if (InLevel) { if (!_returningToMenu) ReturnToMenu(); return; }
            if (_menu == null) return;
            _returningToMenu = false;
            var p = _pending;
            _pending = null;
            var playerData = Live<PlayerDataModel>()?.playerData ?? throw new BridgeException("menu_not_ready", "No PlayerDataModel in the menu");
            var flow = Live<SoloFreePlayFlowCoordinator>();
            var environments = flow != null
                ? (EnvironmentsListModel)typeof(SinglePlayerLevelSelectionFlowCoordinator).GetField("_environmentsListModel", Any).GetValue(flow)
                : null;
            if (environments == null) throw new BridgeException("menu_not_ready", "Could not find the EnvironmentsListModel in the menu");
            var key = new BeatmapKey(p.Level.levelID, p.Characteristic, p.Difficulty);
            var modifiers = p.NoFail ? new GameplayModifiers().CopyWith(noFailOn0Energy: true) : playerData.gameplayModifiers;
            var playerSettings = p.Hud ? playerData.playerSpecificSettings : playerData.playerSpecificSettings.CopyWith(noTextsAndHuds: true);
            var practice = new PracticeSettings(p.StartTime, p.Speed);
            _lastLoad = p;
            _lastEndState = null;
            _showResults = false;
            Plugin.Log.Info($"load {p.LevelPath ?? p.Level.levelID} {p.Characteristic.serializedName}/{p.Difficulty} at {p.StartTime:0.###}s x{p.Speed:0.###}");
            var colors = playerData.colorSchemesSettings;
            _currentLevelPath = p.LevelPath;
            _currentLevelId = p.Level.levelID;
            OpenMarker(p.LevelPath ?? p.Level.levelID);
            _menu.StartStandardLevel("Solo", in key, p.Level, playerData.overrideEnvironmentSettings, colors.GetOverrideColorScheme(),
                colors.ShouldOverrideLightshowColors(), p.Level.GetColorScheme(p.Characteristic, p.Difficulty), modifiers, playerSettings,
                practice, environments, "Menu", false, false, null, null, OnLevelFinished, OnLevelRestarted, null);
        }

        private void OnLevelFinished(StandardLevelScenesTransitionSetupDataSO setup, LevelCompletionResults results)
        {
            _lastEndState = results.levelEndStateType.ToString().ToLowerInvariant();
            _showResults = results.levelEndStateType != LevelCompletionResults.LevelEndStateType.Incomplete && _pending == null;
        }

        private void OnLevelRestarted(StandardLevelScenesTransitionSetupDataSO setup, LevelCompletionResults results)
        {
            OpenMarker(_currentLevelPath ?? setup?.beatmapLevel?.levelID);
        }

        private void ReturnToMenu()
        {
            _returningToMenu = true;
            var controller = FindObjectOfType<StandardLevelReturnToMenuController>();
            if (controller != null) controller.ReturnToMenu();
            else _menu?.StopStandardLevel();
        }

        private void RequireLevel(string action)
        {
            if (!InLevel || InTransition)
                throw new BridgeException("not_in_level", $"Cannot {action}: no level is playing", 409, new JObject { ["scene"] = Scene });
        }

        public JToken Pause()
        {
            RequireLevel("pause");
            var controller = FindObjectOfType<PauseController>();
            if (controller == null) throw new BridgeException("not_in_level", "No PauseController in the current scene", 409);
            bool already = _audio.state == AudioTimeSyncController.State.Paused;
            if (!already) controller.Pause();
            return new JObject { ["paused"] = true, ["already"] = already, ["song_time"] = _audio.songTime };
        }

        public JToken Resume()
        {
            RequireLevel("resume");
            var controller = FindObjectOfType<PauseController>();
            if (controller == null) throw new BridgeException("not_in_level", "No PauseController in the current scene", 409);
            bool playing = _audio.state == AudioTimeSyncController.State.Playing;
            if (!playing) typeof(PauseController).GetMethod("HandlePauseMenuManagerDidPressContinueButton", Any).Invoke(controller, null);
            return new JObject { ["resuming"] = !playing, ["already"] = playing, ["song_time"] = _audio.songTime };
        }

        /// <summary>Restart the current level, optionally at a new song time. Beat Saber has no exact in-level seek that
        /// keeps notes, walls and Heck/Vivify event state consistent, so seek is a practice-mode restart at that time.</summary>
        public JToken Restart(float? time, string action)
        {
            if (!InLevel || InTransition)
            {
                if (_lastLoad == null || _pending != null)
                    throw new BridgeException("not_in_level", $"Cannot {action}: no level is playing and none was loaded by the bridge", 409, new JObject { ["scene"] = Scene });
                var again = _lastLoad;
                if (time.HasValue) again.StartTime = Mathf.Max(0f, time.Value);
                _pending = again;
                return new JObject { ["restarting"] = true, ["via"] = "load", ["start_time"] = again.StartTime };
            }
            var setup = CurrentSetup();
            var practice = setup.practiceSettings;
            if (time.HasValue)
            {
                var t = Mathf.Max(0f, time.Value);
                if (_audio.songLength > 1f && t >= _audio.songLength)
                    throw new BridgeException("bad_request", $"time {t} is past the song end ({_audio.songLength:0.###} s)");
                if (practice == null)
                {
                    practice = new PracticeSettings(t, 1f);
                    typeof(StandardLevelScenesTransitionSetupDataSO).GetField("<practiceSettings>k__BackingField", Any).SetValue(setup, practice);
                    var core = (GameplayCoreSceneSetupData)typeof(LevelScenesTransitionSetupDataSO)
                        .GetField("<gameplayCoreSceneSetupData>k__BackingField", Any)?.GetValue(setup);
                    if (core != null) typeof(GameplayCoreSceneSetupData).GetField("practiceSettings", Any).SetValue(core, practice);
                }
                else practice.startSongTime = t;
                if (_lastLoad != null) _lastLoad.StartTime = t;
            }
            var restart = FindObjectOfType<StandardLevelRestartController>();
            if (restart == null) throw new BridgeException("not_in_level", "No StandardLevelRestartController in the current scene", 409);
            restart.RestartLevel();
            return new JObject { ["restarting"] = true, ["via"] = "restart", ["start_time"] = practice?.startSongTime ?? 0f };
        }

        public JToken Menu()
        {
            _pending = null;
            if (!InLevel) { _returningToMenu = false; return new JObject { ["menu"] = true, ["already"] = true }; }
            ReturnToMenu();
            return new JObject { ["menu"] = true, ["already"] = false };
        }
    }
}
