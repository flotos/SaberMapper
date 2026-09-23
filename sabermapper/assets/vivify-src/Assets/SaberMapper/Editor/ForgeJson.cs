// Minimal JSON reader/writer for the SaberMapper forge (JsonUtility cannot read dictionaries).
// Objects become Dictionary<string, object>, arrays List<object>, numbers double.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace SaberMapper
{
    public static class ForgeJson
    {
        public static object Parse(string text)
        {
            int i = 0;
            object value = ReadValue(text, ref i);
            SkipWhite(text, ref i);
            if (i != text.Length) throw new FormatException("Trailing characters in JSON at offset " + i);
            return value;
        }

        static void SkipWhite(string s, ref int i)
        {
            while (i < s.Length && char.IsWhiteSpace(s[i])) i++;
        }

        static object ReadValue(string s, ref int i)
        {
            SkipWhite(s, ref i);
            if (i >= s.Length) throw new FormatException("Unexpected end of JSON");
            char c = s[i];
            if (c == '{') return ReadObject(s, ref i);
            if (c == '[') return ReadArray(s, ref i);
            if (c == '"') return ReadString(s, ref i);
            if (c == 't' && string.CompareOrdinal(s, i, "true", 0, 4) == 0) { i += 4; return true; }
            if (c == 'f' && string.CompareOrdinal(s, i, "false", 0, 5) == 0) { i += 5; return false; }
            if (c == 'n' && string.CompareOrdinal(s, i, "null", 0, 4) == 0) { i += 4; return null; }
            return ReadNumber(s, ref i);
        }

        static Dictionary<string, object> ReadObject(string s, ref int i)
        {
            var result = new Dictionary<string, object>();
            i++;
            SkipWhite(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return result; }
            while (true)
            {
                SkipWhite(s, ref i);
                string key = ReadString(s, ref i);
                SkipWhite(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("Expected ':' at offset " + i);
                i++;
                result[key] = ReadValue(s, ref i);
                SkipWhite(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { i++; return result; }
                throw new FormatException("Expected ',' or '}' at offset " + i);
            }
        }

        static List<object> ReadArray(string s, ref int i)
        {
            var result = new List<object>();
            i++;
            SkipWhite(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return result; }
            while (true)
            {
                result.Add(ReadValue(s, ref i));
                SkipWhite(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == ']') { i++; return result; }
                throw new FormatException("Expected ',' or ']' at offset " + i);
            }
        }

        static string ReadString(string s, ref int i)
        {
            if (s[i] != '"') throw new FormatException("Expected string at offset " + i);
            i++;
            var sb = new StringBuilder();
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                char e = s[i++];
                switch (e)
                {
                    case 'n': sb.Append('\n'); break;
                    case 't': sb.Append('\t'); break;
                    case 'r': sb.Append('\r'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'u':
                        sb.Append((char)Convert.ToInt32(s.Substring(i, 4), 16));
                        i += 4;
                        break;
                    default: sb.Append(e); break;
                }
            }
            throw new FormatException("Unterminated string");
        }

        static double ReadNumber(string s, ref int i)
        {
            int start = i;
            while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
            if (start == i) throw new FormatException("Unexpected character '" + s[i] + "' at offset " + i);
            return double.Parse(s.Substring(start, i - start), NumberStyles.Float, CultureInfo.InvariantCulture);
        }

        public static string Write(object value, bool indent = true)
        {
            var sb = new StringBuilder();
            WriteValue(sb, value, indent, 0);
            return sb.ToString();
        }

        static void NewLine(StringBuilder sb, bool indent, int depth)
        {
            if (!indent) return;
            sb.Append('\n');
            sb.Append(' ', depth * 2);
        }

        static void WriteValue(StringBuilder sb, object value, bool indent, int depth)
        {
            if (value == null) { sb.Append("null"); return; }
            if (value is string) { WriteString(sb, (string)value); return; }
            if (value is bool) { sb.Append((bool)value ? "true" : "false"); return; }
            if (value is float)
            {
                float f = (float)value;
                if (float.IsNaN(f) || float.IsInfinity(f)) f = 0;
                sb.Append(f.ToString("R", CultureInfo.InvariantCulture));
                return;
            }
            if (value is double)
            {
                double d = Convert.ToDouble(value, CultureInfo.InvariantCulture);
                if (double.IsNaN(d) || double.IsInfinity(d)) d = 0;
                sb.Append(d.ToString("R", CultureInfo.InvariantCulture));
                return;
            }
            if (value is int || value is long || value is uint || value is short || value is ulong)
            {
                sb.Append(Convert.ToString(value, CultureInfo.InvariantCulture));
                return;
            }
            var dict = value as IDictionary;
            if (dict != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (DictionaryEntry entry in dict)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    NewLine(sb, indent, depth + 1);
                    WriteString(sb, Convert.ToString(entry.Key, CultureInfo.InvariantCulture));
                    sb.Append(indent ? ": " : ":");
                    WriteValue(sb, entry.Value, indent, depth + 1);
                }
                if (!first) NewLine(sb, indent, depth);
                sb.Append('}');
                return;
            }
            var list = value as IEnumerable;
            if (list != null)
            {
                sb.Append('[');
                bool first = true;
                foreach (object item in list)
                {
                    if (!first) sb.Append(indent ? ", " : ",");
                    first = false;
                    WriteValue(sb, item, indent, depth + 1);
                }
                sb.Append(']');
                return;
            }
            WriteString(sb, value.ToString());
        }

        static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }

    /// <summary>Typed access to a JSON object from assets.json (generator params, particle modules).</summary>
    public class ForgeParams
    {
        public readonly Dictionary<string, object> Raw;

        public ForgeParams(object raw)
        {
            Raw = raw as Dictionary<string, object> ?? new Dictionary<string, object>();
        }

        public bool Has(string key) { return Raw.ContainsKey(key) && Raw[key] != null; }

        public float Float(string key, float fallback)
        {
            object v;
            if (!Raw.TryGetValue(key, out v) || v == null) return fallback;
            return Convert.ToSingle(v, CultureInfo.InvariantCulture);
        }

        public int Int(string key, int fallback) { return (int)Math.Round(Float(key, fallback)); }

        public bool Bool(string key, bool fallback)
        {
            object v;
            if (!Raw.TryGetValue(key, out v) || v == null) return fallback;
            return v is bool ? (bool)v : Convert.ToDouble(v, CultureInfo.InvariantCulture) != 0;
        }

        public string String(string key, string fallback)
        {
            object v;
            return Raw.TryGetValue(key, out v) && v != null ? Convert.ToString(v, CultureInfo.InvariantCulture) : fallback;
        }

        public float[] Floats(string key, float[] fallback)
        {
            object v;
            var list = Raw.TryGetValue(key, out v) ? v as List<object> : null;
            if (list == null)
            {
                if (v is double) return new[] { Convert.ToSingle(v, CultureInfo.InvariantCulture) };
                return fallback;
            }
            var result = new float[list.Count];
            for (int i = 0; i < list.Count; i++) result[i] = Convert.ToSingle(list[i], CultureInfo.InvariantCulture);
            return result;
        }

        public UnityEngine.Vector3 Vec3(string key, UnityEngine.Vector3 fallback)
        {
            float[] f = Floats(key, null);
            if (f == null) return fallback;
            if (f.Length == 1) return new UnityEngine.Vector3(f[0], f[0], f[0]);
            return new UnityEngine.Vector3(f[0], f.Length > 1 ? f[1] : 0, f.Length > 2 ? f[2] : 0);
        }

        public UnityEngine.Color Color(string key, UnityEngine.Color fallback)
        {
            float[] f = Floats(key, null);
            if (f == null || f.Length < 3) return fallback;
            return new UnityEngine.Color(f[0], f[1], f[2], f.Length > 3 ? f[3] : 1f);
        }

        public ForgeParams Child(string key)
        {
            object v;
            return new ForgeParams(Raw.TryGetValue(key, out v) ? v : null);
        }

        public List<object> List(string key)
        {
            object v;
            return (Raw.TryGetValue(key, out v) ? v as List<object> : null) ?? new List<object>();
        }
    }
}
