using System;
using System.IO;
using IPA;
using IPA.Utilities;
using Newtonsoft.Json.Linq;
using UnityEngine;
using IPALogger = IPA.Logging.Logger;

namespace SaberMapperBridge
{
    [Plugin(RuntimeOptions.SingleStartInit)]
    public class Plugin
    {
        public const string Version = "0.3.0";
        internal static IPALogger Log;
        internal static BridgeConfig Config;
        internal static BridgeServer Server;

        [Init]
        public void Init(IPALogger logger) { Log = logger; }

        [OnStart]
        public void OnStart()
        {
            Config = BridgeConfig.Load();
            var go = new GameObject("SaberMapperBridge");
            UnityEngine.Object.DontDestroyOnLoad(go);
            var controller = go.AddComponent<GameController>();
            Server = new BridgeServer(controller, Config.Port);
            try
            {
                Server.Start();
                BridgeConfig.WriteBridgeFile(Config.Port);
                Log.Info($"listening on http://127.0.0.1:{Config.Port}/ (bridge {Version}, game {UnityGame.GameVersion})");
            }
            catch (Exception e) { Log.Error($"could not start the HTTP server on 127.0.0.1:{Config.Port}: {e.Message}"); }
        }

        [OnExit]
        public void OnExit()
        {
            Server?.Stop();
            BridgeConfig.RemoveBridgeFile();
        }
    }

    internal class BridgeConfig
    {
        public int Port = 28765;
        public bool RunInBackground = true;

        public static string ConfigPath => Path.Combine(UnityGame.UserDataPath, "SaberMapperBridge.json");

        public static string StateDir
        {
            get
            {
                var overrideDir = Environment.GetEnvironmentVariable("SABERMAPPER_LEASE_DIR");
                if (!string.IsNullOrEmpty(overrideDir)) return overrideDir;
                return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SaberMapper");
            }
        }

        // Read-only: the bridge never creates or rewrites the user's UserData config.
        public static BridgeConfig Load()
        {
            var config = new BridgeConfig();
            try
            {
                if (File.Exists(ConfigPath))
                {
                    var obj = JObject.Parse(File.ReadAllText(ConfigPath));
                    config.Port = (int?)obj["port"] ?? config.Port;
                    config.RunInBackground = (bool?)obj["run_in_background"] ?? config.RunInBackground;
                }
            }
            catch (Exception e) { Plugin.Log.Warn($"ignoring unreadable {ConfigPath}: {e.Message}"); }
            var envPort = Environment.GetEnvironmentVariable("SABERMAPPER_BRIDGE_PORT");
            if (int.TryParse(envPort, out var p) && p > 0) config.Port = p;
            return config;
        }

        public static void WriteBridgeFile(int port)
        {
            try
            {
                Directory.CreateDirectory(StateDir);
                var obj = new JObject
                {
                    ["port"] = port,
                    ["pid"] = System.Diagnostics.Process.GetCurrentProcess().Id,
                    ["bridge_version"] = Version,
                    ["game_version"] = UnityGame.GameVersion.ToString(),
                    ["started_at"] = DateTime.UtcNow.ToString("o"),
                };
                var path = Path.Combine(StateDir, "bridge.json");
                var tmp = path + ".tmp";
                File.WriteAllText(tmp, obj.ToString());
                if (File.Exists(path)) File.Delete(path);
                File.Move(tmp, path);
            }
            catch (Exception e) { Plugin.Log.Warn($"could not write bridge.json: {e.Message}"); }
        }

        public static void RemoveBridgeFile()
        {
            try
            {
                var path = Path.Combine(StateDir, "bridge.json");
                if (!File.Exists(path)) return;
                var obj = JObject.Parse(File.ReadAllText(path));
                if ((int?)obj["pid"] == System.Diagnostics.Process.GetCurrentProcess().Id) File.Delete(path);
            }
            catch (Exception) { }
        }

        private const string Version = Plugin.Version;
    }
}
