using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Experimental.Rendering;
using UnityEngine.Rendering;

namespace SaberMapperBridge
{
    /// <summary>PNG frame capture at requested song times. Frames are grabbed at end of frame (after every camera and
    /// image effect, so Vivify post-processing on the player camera is included), read back asynchronously from the
    /// GPU and encoded on worker threads so gameplay keeps its frame rate.
    ///
    /// Requests due in a frame are taken in LateUpdate, when the song time is final. Nobody cuts notes during a capture,
    /// so uncut notes fly through the camera and fill the frame; the flash probe measures the scene the player sees,
    /// not notes hitting the lens. Notes, bombs, chains and arcs are therefore hidden through one continuous window:
    /// the whole job with hide_notes, or from the first probe frame until the probe ends with probe.hide_notes. Every
    /// frame of the window turns rendering off for the renderers under active notes (including ones spawned that
    /// frame) at the first camera cull; nothing is turned back on inside the window, so the live game never blinks
    /// notes on and off. Exactly the renderers the window turned off are turned back on once, when it closes: the probe
    /// ends, the job finishes, fails or is cancelled, or the level stops. Every frame grabbed inside the window,
    /// probe or regular, reports notes_hidden. Walls, sabers and the scene stay visible.</summary>
    internal class CaptureController
    {
        private const int MaxPendingWrites = 48;
        private readonly GameController _game;
        private readonly object _lock = new object();
        private Job _job;
        private int _jobCounter;
        private Camera _wideCamera;

        // Requests taken in LateUpdate and grabbed at the end of the same frame (main thread only).
        private List<FrameRequest> _scheduled;
        private float _scheduledTime;
        // Continuous notes-hidden window: open while _hideActive, closed (renderers restored) exactly once.
        private bool _hideActive;
        private int _hiddenFrame = -1;
        private readonly List<Renderer> _hidden = new List<Renderer>();

        private class FrameRequest { public float Time; public string Name; public string Reason; }

        private class Probe { public float Start, End, Fps; public int NextIndex; public bool Finished, HideNotes; }

        private class Job
        {
            public int Id;
            public string Status = "running", OutDir, Camera, Error;
            public bool HideNotes;
            public int NotesHiddenFrames;
            public int? Width, Height;
            public List<FrameRequest> Frames = new List<FrameRequest>();
            public int Next, Pending, Dropped, Written, Captured;
            public Probe Probe;
            public readonly List<JObject> Results = new List<JObject>();
            public DateTime StartedAt = DateTime.UtcNow;
            public bool AllScheduled => Next >= Frames.Count && (Probe == null || Probe.Finished);
        }

        public CaptureController(GameController game)
        {
            _game = game;
            Camera.onPreCull += OnPreCull;
        }

        public JToken Start(JObject input)
        {
            lock (_lock)
                if (_job != null && _job.Status == "running")
                    throw new BridgeException("capture_busy", $"Capture job {_job.Id} is still running; POST /capture/cancel first", 409);
            var outDir = BridgeServer.OptString(input, "out_dir");
            if (string.IsNullOrEmpty(outDir) || !Path.IsPathRooted(outDir))
                throw new BridgeException("bad_request", "capture needs an absolute out_dir");
            var camera = BridgeServer.OptString(input, "camera", "player");
            if (camera != "player" && camera != "wide")
                throw new BridgeException("bad_request", "camera must be player or wide");
            var job = new Job { Id = ++_jobCounter, OutDir = outDir, Camera = camera, HideNotes = BridgeServer.OptBool(input, "hide_notes", false) };
            var width = BridgeServer.OptInt(input, "width", 0);
            var height = BridgeServer.OptInt(input, "height", 0);
            if (width < 0 || height < 0 || width > 8192 || height > 8192) throw new BridgeException("bad_request", "width/height must be within 1..8192");
            job.Width = width > 0 ? (int?)width : null;
            job.Height = height > 0 ? (int?)height : null;
            if (input["frames"] is JArray frames)
            {
                foreach (var token in frames)
                {
                    if (!(token is JObject f)) throw new BridgeException("bad_request", "frames must be objects {time, name}");
                    var time = BridgeServer.OptNullableFloat(f, "time") ?? throw new BridgeException("bad_request", "every frame needs a time");
                    var name = SafeName(BridgeServer.OptString(f, "name", $"t{time:0000.000}.png"));
                    job.Frames.Add(new FrameRequest { Time = time, Name = name, Reason = BridgeServer.OptString(f, "reason") });
                }
                job.Frames = job.Frames.OrderBy(f => f.Time).ToList();
            }
            if (input["probe"] is JObject probe)
            {
                var start = BridgeServer.OptNullableFloat(probe, "start") ?? throw new BridgeException("bad_request", "probe needs start");
                var end = BridgeServer.OptNullableFloat(probe, "end") ?? throw new BridgeException("bad_request", "probe needs end");
                var fps = BridgeServer.OptFloat(probe, "fps", 30f);
                if (end <= start || fps <= 0 || fps > 120) throw new BridgeException("bad_request", "probe needs end > start and 0 < fps <= 120");
                job.Probe = new Probe { Start = start, End = end, Fps = fps, HideNotes = job.HideNotes || BridgeServer.OptBool(probe, "hide_notes", false) };
            }
            if (job.Frames.Count == 0 && job.Probe == null) throw new BridgeException("bad_request", "capture needs frames [{time, name}] or probe {start, end, fps}");
            try { Directory.CreateDirectory(outDir); }
            catch (Exception e) { throw new BridgeException("bad_request", $"Cannot create out_dir: {e.Message}"); }
            lock (_lock) _job = job;
            Plugin.Log.Info($"capture job {job.Id}: {job.Frames.Count} frames{(job.Probe != null ? $", probe {job.Probe.Start}-{job.Probe.End}@{job.Probe.Fps}{(job.Probe.HideNotes ? " notes hidden" : "")}" : "")}, camera {camera}{(job.HideNotes ? ", notes hidden" : "")}, out {outDir}");
            return Status(false);
        }

        private static string SafeName(string name)
        {
            if (string.IsNullOrEmpty(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name.Contains("..") || name.Contains("/") || name.Contains("\\"))
                throw new BridgeException("bad_request", $"Invalid frame file name {name}");
            return name.EndsWith(".png", StringComparison.OrdinalIgnoreCase) ? name : name + ".png";
        }

        public JToken Cancel()
        {
            lock (_lock)
            {
                if (_job == null || _job.Status != "running") return new JObject { ["cancelled"] = false };
                _job.Status = "cancelled";
            }
            CloseHideWindow(); // Cancel runs on the main thread (GameController.Invoke)
            return Status(true);
        }

        /// <summary>Main thread only (GameController's LateUpdate and end-of-frame handlers).</summary>
        public void Fail(Exception e)
        {
            lock (_lock)
                if (_job != null && _job.Status == "running") { _job.Status = "failed"; _job.Error = e.Message; }
            try { CloseHideWindow(); }
            catch (Exception restore) { Plugin.Log.Error($"restoring notes failed: {restore}"); }
        }

        public JObject Status(bool withFrames)
        {
            lock (_lock)
            {
                if (_job == null) return null;
                var o = new JObject
                {
                    ["job_id"] = _job.Id, ["status"] = _job.Status, ["out_dir"] = _job.OutDir, ["camera"] = _job.Camera,
                    ["requested"] = _job.Frames.Count, ["next"] = _job.Next, ["captured"] = _job.Captured, ["written"] = _job.Written,
                    ["pending"] = _job.Pending, ["dropped"] = _job.Dropped, ["error"] = _job.Error,
                    ["hide_notes"] = _job.HideNotes, ["notes_hidden_frames"] = _job.NotesHiddenFrames,
                    ["notes_hidden_now"] = _hideActive,
                    ["probe"] = _job.Probe == null ? null : new JObject
                    {
                        ["start"] = _job.Probe.Start, ["end"] = _job.Probe.End, ["fps"] = _job.Probe.Fps, ["finished"] = _job.Probe.Finished,
                        ["hide_notes"] = _job.Probe.HideNotes,
                    },
                    ["started_at"] = _job.StartedAt.ToString("o"),
                };
                if (withFrames) o["frames"] = new JArray(_job.Results.Select(r => r.DeepClone()).ToArray());
                return o;
            }
        }

        /// <summary>LateUpdate: takes the requests due at this frame's song time and opens or closes the notes-hidden
        /// window. The window is open while the job runs in a level and either the job hides notes or the probe hides
        /// notes, has taken its first frame and has not ended; pausing keeps it open, leaving the level closes it.</summary>
        public void Schedule(bool inLevel, bool playing, float songTime)
        {
            _scheduled = null;
            Job job;
            lock (_lock) job = _job;
            bool running = job != null && job.Status == "running";
            var due = new List<FrameRequest>();
            if (running && playing)
            {
                var probe = job.Probe;
                if (probe != null && !probe.Finished && songTime >= probe.Start)
                {
                    if (songTime > probe.End + 0.5f / probe.Fps) probe.Finished = true;
                    else
                    {
                        int index = Mathf.FloorToInt((songTime - probe.Start) * probe.Fps + 1e-4f);
                        if (index >= probe.NextIndex)
                        {
                            due.Add(new FrameRequest { Time = probe.Start + index / probe.Fps, Name = $"probe-{index:D5}.png", Reason = "probe" });
                            probe.NextIndex = index + 1;
                        }
                    }
                }
                while (job.Next < job.Frames.Count && job.Frames[job.Next].Time <= songTime) due.Add(job.Frames[job.Next++]);
            }
            bool hide = running && inLevel && (job.HideNotes
                || (job.Probe != null && job.Probe.HideNotes && job.Probe.NextIndex > 0 && !job.Probe.Finished));
            if (hide) _hideActive = true;
            else CloseHideWindow();
            if (due.Count == 0) return;
            _scheduled = due;
            _scheduledTime = songTime;
        }

        /// <summary>Turns back on exactly the renderers the window turned off, once. Safe to call when it is closed.</summary>
        private void CloseHideWindow()
        {
            _hideActive = false;
            if (_hidden.Count == 0) return;
            int restored = _hidden.Count;
            RestoreNotes();
            Plugin.Log.Info($"capture notes visible again ({restored} renderers)");
        }

        /// <summary>First camera cull of each frame while the window is open. It runs after every LateUpdate, so notes
        /// spawned or moved this frame are covered; renderers already turned off stay off (nothing toggles). Vivify note
        /// prefabs are parented under the note object, so its children cover them.</summary>
        private void OnPreCull(Camera camera)
        {
            int frame = Time.frameCount;
            if (!_hideActive || _hiddenFrame == frame) return;
            _hiddenFrame = frame;
            try
            {
                foreach (var note in UnityEngine.Object.FindObjectsOfType<NoteController>()) HideUnder(note);
                foreach (var slider in UnityEngine.Object.FindObjectsOfType<SliderController>()) HideUnder(slider);
            }
            catch (Exception e) { Plugin.Log.Error($"hiding notes failed: {e}"); }
        }

        private void HideUnder(Component root)
        {
            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
                if (renderer != null && !renderer.forceRenderingOff)
                {
                    renderer.forceRenderingOff = true;
                    _hidden.Add(renderer);
                }
        }

        private void RestoreNotes()
        {
            foreach (var renderer in _hidden)
                if (renderer != null) renderer.forceRenderingOff = false;
            _hidden.Clear();
        }

        public void OnEndOfFrame()
        {
            var due = _scheduled;
            float songTime = _scheduledTime;
            bool notesHidden = _hiddenFrame == Time.frameCount;
            int hiddenRenderers = _hidden.Count;
            _scheduled = null;
            Job job;
            lock (_lock) job = _job;
            try
            {
                if (job != null && job.Status == "running" && due != null) Grab(job, due, songTime, notesHidden, hiddenRenderers);
            }
            finally
            {
                bool running;
                lock (_lock) running = job != null && job.Status == "running";
                if (!running) CloseHideWindow();
            }
            if (job == null) return;
            bool finished = false;
            lock (_lock)
                if (job.Status == "running" && job.AllScheduled && job.Pending == 0)
                {
                    job.Status = "done";
                    finished = true;
                    Plugin.Log.Info($"capture job {job.Id} done: {job.Written} written, {job.Dropped} dropped, {job.NotesHiddenFrames} with notes hidden");
                }
            if (finished) CloseHideWindow();
        }

        private void Grab(Job job, List<FrameRequest> due, float songTime, bool notesHidden, int hiddenRenderers)
        {
            int frame = Time.frameCount;
            var results = due.Select(r => new JObject
            {
                ["name"] = r.Name, ["file"] = Path.Combine(job.OutDir, r.Name), ["requested_time"] = r.Time, ["song_time"] = Math.Round(songTime, 4),
                ["frame"] = frame, ["reason"] = r.Reason, ["written"] = false, ["notes_hidden"] = notesHidden,
                ["hidden_renderers"] = notesHidden ? (JToken)hiddenRenderers : null,
            }).ToList();
            lock (_lock)
            {
                job.Results.AddRange(results);
                job.Captured += due.Count;
                if (notesHidden) job.NotesHiddenFrames += due.Count;
                if (job.Pending >= MaxPendingWrites)
                {
                    job.Dropped += due.Count;
                    foreach (var r in results) r["error"] = "dropped: too many frames waiting to be written";
                    return;
                }
                job.Pending++;
            }
            int srcW = Screen.width, srcH = Screen.height;
            int outW = job.Width ?? (job.Height.HasValue ? Mathf.RoundToInt(srcW * (job.Height.Value / (float)srcH)) : srcW);
            int outH = job.Height ?? (job.Width.HasValue ? Mathf.RoundToInt(srcH * (job.Width.Value / (float)srcW)) : srcH);
            bool flip;
            RenderTexture source = RenderTexture.GetTemporary(srcW, srcH, job.Camera == "player" ? 0 : 24, RenderTextureFormat.ARGB32);
            if (job.Camera == "player")
            {
                ScreenCapture.CaptureScreenshotIntoRenderTexture(source);
                flip = SystemInfo.graphicsUVStartsAtTop;
            }
            else
            {
                RenderWide(source);
                flip = false;
            }
            RenderTexture readback = source;
            if (outW != srcW || outH != srcH)
            {
                readback = RenderTexture.GetTemporary(outW, outH, 0, RenderTextureFormat.ARGB32);
                Graphics.Blit(source, readback);
                RenderTexture.ReleaseTemporary(source);
            }
            AsyncGPUReadback.Request(readback, 0, TextureFormat.RGBA32, request =>
            {
                RenderTexture.ReleaseTemporary(readback);
                if (request.hasError) { Finish(job, results, "GPU readback failed"); return; }
                var rgba = request.GetData<byte>().ToArray();
                ThreadPool.QueueUserWorkItem(_ => Encode(job, results, rgba, outW, outH, flip));
            });
        }

        private void RenderWide(RenderTexture target)
        {
            var main = Camera.main;
            if (main == null) throw new InvalidOperationException("No main camera to render");
            if (_wideCamera == null)
            {
                var go = new GameObject("SaberMapperBridge.WideCamera");
                UnityEngine.Object.DontDestroyOnLoad(go);
                _wideCamera = go.AddComponent<Camera>();
                _wideCamera.enabled = false;
            }
            _wideCamera.CopyFrom(main);
            _wideCamera.stereoTargetEye = StereoTargetEyeMask.None;
            _wideCamera.fieldOfView = 70f;
            _wideCamera.transform.position = new Vector3(0f, 4.5f, -8f);
            _wideCamera.transform.LookAt(new Vector3(0f, 1.2f, 14f));
            _wideCamera.targetTexture = target;
            try { _wideCamera.Render(); }
            finally { _wideCamera.targetTexture = null; }
        }

        private void Encode(Job job, List<JObject> results, byte[] rgba, int width, int height, bool flip)
        {
            try
            {
                var rgb = new byte[width * height * 3];
                for (int y = 0; y < height; y++)
                {
                    int srcRow = (flip ? height - 1 - y : y) * width * 4, dstRow = y * width * 3;
                    for (int x = 0; x < width; x++)
                    {
                        rgb[dstRow + x * 3] = rgba[srcRow + x * 4];
                        rgb[dstRow + x * 3 + 1] = rgba[srcRow + x * 4 + 1];
                        rgb[dstRow + x * 3 + 2] = rgba[srcRow + x * 4 + 2];
                    }
                }
                // Readbacks of camera render textures arrive top row first; CaptureScreenshotIntoRenderTexture leaves the
                // screen upside down where graphicsUVStartsAtTop (D3D11), which the flip above undoes.
                var png = ImageConversion.EncodeArrayToPNG(rgb, GraphicsFormat.R8G8B8_UNorm, (uint)width, (uint)height);
                foreach (var r in results) File.WriteAllBytes((string)r["file"], png);
                Finish(job, results, null);
            }
            catch (Exception e) { Finish(job, results, e.Message); }
        }

        private void Finish(Job job, List<JObject> results, string error)
        {
            lock (_lock)
            {
                job.Pending--;
                foreach (var r in results)
                {
                    if (error == null) { r["written"] = true; job.Written++; }
                    else r["error"] = error;
                }
                if (error != null && job.Error == null) job.Error = error;
            }
        }
    }
}
