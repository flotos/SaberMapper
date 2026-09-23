using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace SaberMapperBridge
{
    /// <summary>Error with a stable machine-readable code, returned as {"error":{"code","message","details"}}.</summary>
    internal class BridgeException : Exception
    {
        public readonly string Code;
        public readonly int Status;
        public readonly JObject Details;

        public BridgeException(string code, string message, int status = 400, JObject details = null) : base(message)
        {
            Code = code; Status = status; Details = details ?? new JObject();
        }
    }

    /// <summary>127.0.0.1-only HTTP JSON server. Request threads never touch Unity objects; they hand work to
    /// <see cref="GameController"/>, which runs it on the Unity main thread.</summary>
    internal class BridgeServer
    {
        private readonly GameController _game;
        private readonly int _port;
        private HttpListener _listener;
        private Thread _thread;
        private volatile bool _running;

        public BridgeServer(GameController game, int port) { _game = game; _port = port; }

        public void Start()
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://127.0.0.1:{_port}/");
            _listener.Start();
            _running = true;
            _thread = new Thread(Loop) { IsBackground = true, Name = "SaberMapperBridge.Http" };
            _thread.Start();
        }

        public void Stop()
        {
            _running = false;
            try { _listener?.Stop(); _listener?.Close(); } catch (Exception) { }
        }

        private void Loop()
        {
            while (_running)
            {
                HttpListenerContext context;
                try { context = _listener.GetContext(); }
                catch (Exception) { if (!_running) return; continue; }
                ThreadPool.QueueUserWorkItem(_ => Handle(context));
            }
        }

        private void Handle(HttpListenerContext context)
        {
            var request = context.Request;
            int status = 200;
            JToken body;
            try
            {
                if (!IPAddress.IsLoopback(request.RemoteEndPoint.Address))
                    throw new BridgeException("forbidden", "Only loopback clients are accepted", 403);
                var path = request.Url.AbsolutePath.TrimEnd('/');
                if (path == "") path = "/";
                var method = request.HttpMethod.ToUpperInvariant();
                if (!(method == "GET" && path == "/health")) Lease.Check(request.Headers["X-SaberMapper-Lease"]);
                JObject input = ReadBody(request);
                foreach (string key in request.QueryString.Keys)
                    if (key != null && input[key] == null) input[key] = request.QueryString[key];
                body = Route(method, path, input);
            }
            catch (BridgeException e)
            {
                status = e.Status;
                body = ErrorBody(e.Code, e.Message, e.Details);
            }
            catch (Exception e)
            {
                status = 500;
                body = ErrorBody("bridge_internal", e.GetType().Name + ": " + e.Message, new JObject { ["trace"] = e.StackTrace });
                Plugin.Log.Error($"request {request.HttpMethod} {request.Url.AbsolutePath} failed: {e}");
            }
            try
            {
                var bytes = Encoding.UTF8.GetBytes(body.ToString(Formatting.None));
                context.Response.StatusCode = status;
                context.Response.ContentType = "application/json; charset=utf-8";
                context.Response.ContentLength64 = bytes.Length;
                context.Response.OutputStream.Write(bytes, 0, bytes.Length);
                context.Response.OutputStream.Close();
            }
            catch (Exception) { }
        }

        internal static JObject ErrorBody(string code, string message, JObject details) =>
            new JObject { ["error"] = new JObject { ["code"] = code, ["message"] = message, ["details"] = details ?? new JObject() } };

        private static JObject ReadBody(HttpListenerRequest request)
        {
            if (!request.HasEntityBody) return new JObject();
            string text;
            using (var reader = new StreamReader(request.InputStream, Encoding.UTF8)) text = reader.ReadToEnd();
            if (string.IsNullOrWhiteSpace(text)) return new JObject();
            JToken token;
            try { token = JToken.Parse(text); }
            catch (JsonException e) { throw new BridgeException("bad_request", "Request body is not valid JSON: " + e.Message); }
            if (token is JObject obj) return obj;
            throw new BridgeException("bad_request", "Request body must be a JSON object");
        }

        private static readonly string[] Endpoints =
        {
            "GET /health", "GET /state", "POST /refresh", "POST /load", "POST /pause", "POST /resume", "POST /restart",
            "POST /seek", "POST /menu", "POST /capture", "GET /capture", "POST /capture/cancel",
        };

        private JToken Route(string method, string path, JObject input)
        {
            switch (method + " " + path)
            {
                case "GET /health": return _game.Health();
                case "GET /state": return _game.WaitState(OptInt(input, "wait_ms", 0), OptLong(input, "since", -1));
                case "POST /refresh": return _game.Refresh(OptBool(input, "full", false), OptInt(input, "wait_ms", 0));
                case "POST /load": return _game.Invoke(() => _game.Load(input));
                case "POST /pause": return _game.Invoke(() => _game.Pause());
                case "POST /resume": return _game.Invoke(() => _game.Resume());
                case "POST /restart": return _game.Invoke(() => _game.Restart(OptNullableFloat(input, "start_time"), "restart"));
                case "POST /seek":
                    var time = OptNullableFloat(input, "time");
                    if (time == null) throw new BridgeException("bad_request", "seek needs {\"time\": seconds}");
                    return _game.Invoke(() => _game.Restart(time, "seek"));
                case "POST /menu": return _game.Invoke(() => _game.Menu());
                case "POST /capture": return _game.Invoke(() => _game.Capture.Start(input));
                case "GET /capture": return _game.Invoke(() => _game.Capture.Status(true));
                case "POST /capture/cancel": return _game.Invoke(() => _game.Capture.Cancel());
            }
            throw new BridgeException("not_found", $"Unknown endpoint {method} {path}", 404,
                new JObject { ["endpoints"] = new JArray(Endpoints) });
        }

        private static double? Number(JObject o, string key)
        {
            var t = o[key];
            if (t == null || t.Type == JTokenType.Null) return null;
            if (t.Type == JTokenType.Integer || t.Type == JTokenType.Float) return (double)t;
            if (double.TryParse(t.ToString(), System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var d)) return d;
            throw new BridgeException("bad_request", $"'{key}' must be a number", 400, new JObject { ["value"] = t.ToString() });
        }

        internal static int OptInt(JObject o, string key, int fallback) => (int?)Number(o, key) ?? fallback;
        internal static long OptLong(JObject o, string key, long fallback) => (long?)Number(o, key) ?? fallback;
        internal static float? OptNullableFloat(JObject o, string key) => (float?)Number(o, key);
        internal static float OptFloat(JObject o, string key, float fallback) => (float?)Number(o, key) ?? fallback;

        internal static bool OptBool(JObject o, string key, bool fallback)
        {
            var t = o[key];
            if (t == null || t.Type == JTokenType.Null) return fallback;
            if (t.Type == JTokenType.Boolean) return (bool)t;
            var s = t.ToString().ToLowerInvariant();
            return s == "1" || s == "true" || s == "yes";
        }

        internal static string OptString(JObject o, string key, string fallback = null)
        {
            var t = o[key];
            return t == null || t.Type == JTokenType.Null ? fallback : t.ToString();
        }
    }

    /// <summary>Machine-wide SaberMapper game lease: the token in game-lease.json is the only credential.</summary>
    internal static class Lease
    {
        public static string LeasePath => Path.Combine(BridgeConfig.StateDir, "game-lease.json");

        public static void Check(string header)
        {
            string token = ReadToken();
            if (token == null)
                throw new BridgeException("lease_not_held",
                    "No SaberMapper game lease is held; acquire one with `sabermapper game lease --acquire`", 403,
                    new JObject { ["lease_file"] = LeasePath });
            if (string.IsNullOrEmpty(header) || !FixedTimeEquals(header, token))
                throw new BridgeException("lease_invalid",
                    "The X-SaberMapper-Lease header does not match the current lease token (the lease changed hands or was not sent)", 403,
                    new JObject { ["lease_file"] = LeasePath });
        }

        private static string ReadToken()
        {
            for (int attempt = 0; attempt < 3; attempt++)
            {
                try
                {
                    if (!File.Exists(LeasePath)) return null;
                    string text;
                    using (var stream = new FileStream(LeasePath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                    using (var reader = new StreamReader(stream, Encoding.UTF8)) text = reader.ReadToEnd();
                    var token = (string)JObject.Parse(text)["token"];
                    return string.IsNullOrEmpty(token) ? null : token;
                }
                catch (FileNotFoundException) { return null; }
                catch (DirectoryNotFoundException) { return null; }
                catch (Exception) { Thread.Sleep(50); }
            }
            return null;
        }

        private static bool FixedTimeEquals(string a, string b)
        {
            if (a.Length != b.Length) return false;
            int diff = 0;
            for (int i = 0; i < a.Length; i++) diff |= a[i] ^ b[i];
            return diff == 0;
        }
    }
}
