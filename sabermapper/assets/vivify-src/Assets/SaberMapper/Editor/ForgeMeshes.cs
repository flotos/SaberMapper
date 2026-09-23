// Built-in procedural mesh generators for the SaberMapper forge (tier 1).
// Triangle counts must match the formulas in sabermapper/assets/library/library.json ("meshes").
// Agent-written generators (tier 2) follow the same contract:
//   public static class MyMesh { public static Mesh Generate(SaberMapper.ForgeParams p) { ... } }
using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace SaberMapper
{
    public static class ForgeMeshes
    {
        public static readonly string[] Names = { "quad", "plane", "cube", "uv_sphere", "ring", "torus", "tube", "cone", "shard" };

        public static Mesh Generate(string generator, ForgeParams p)
        {
            switch (generator)
            {
                case "quad": return Quad(p.Float("width", 1), p.Float("height", 1));
                case "plane": return Plane(p.Float("width", 10), p.Float("depth", 10), Math.Max(1, p.Int("segments_x", 1)), Math.Max(1, p.Int("segments_z", 1)));
                case "cube": return Cube(p.Vec3("size", Vector3.one));
                case "uv_sphere": return Sphere(p.Float("radius", 0.5f), Math.Max(3, p.Int("segments", 24)), Math.Max(2, p.Int("rings", 16)));
                case "ring": return Ring(p.Float("inner_radius", 0.8f), p.Float("outer_radius", 1f), Math.Max(3, p.Int("segments", 64)));
                case "torus": return Torus(p.Float("radius", 1f), p.Float("thickness", 0.05f), Math.Max(3, p.Int("segments", 64)), Math.Max(3, p.Int("sides", 8)));
                case "tube": return Tube(p.Float("radius", 2f), p.Float("length", 4f), Math.Max(3, p.Int("segments", 32)), Math.Max(1, p.Int("length_segments", 1)), p.Bool("inside", true));
                case "cone": return Cone(p.Float("radius", 0.5f), p.Float("height", 1f), Math.Max(3, p.Int("segments", 24)));
                case "shard": return Shard(p.Float("length", 1f), p.Float("width", 0.25f), Math.Max(3, p.Int("sides", 5)), p.Int("seed", 1));
                default: throw new ArgumentException("Unknown mesh generator '" + generator + "'; built-ins: " + string.Join(", ", Names));
            }
        }

        public static Mesh Build(string name, List<Vector3> v, List<Vector2> uv, List<int> t, bool recalcNormals = true)
        {
            var mesh = new Mesh { name = name };
            if (v.Count > 65535) mesh.indexFormat = IndexFormat.UInt32;
            mesh.SetVertices(v);
            if (uv != null) mesh.SetUVs(0, uv);
            mesh.SetTriangles(t, 0);
            if (recalcNormals) mesh.RecalculateNormals();
            mesh.RecalculateBounds();
            return mesh;
        }

        /// <summary>A mesh from model data staged by `sabermapper assets build` (a fetched or exported OBJ, already in
        /// Unity space): flat vertices, triangles and optional uvs and linear RGBA vertex colours.</summary>
        public static Mesh FromData(string projectRelativePath, string name)
        {
            string full = System.IO.Path.GetFullPath(System.IO.Path.Combine(Application.dataPath, "..", projectRelativePath));
            var data = new ForgeParams(ForgeJson.Parse(System.IO.File.ReadAllText(full)));
            float[] p = data.Floats("vertices", new float[0]);
            float[] t = data.Floats("triangles", new float[0]);
            float[] uv = data.Floats("uvs", null);
            float[] c = data.Floats("colors", null);
            int count = p.Length / 3;
            var v = new List<Vector3>(count);
            for (int i = 0; i < count; i++) v.Add(new Vector3(p[3 * i], p[3 * i + 1], p[3 * i + 2]));
            List<Vector2> uvs = null;
            if (uv != null && uv.Length == count * 2)
            {
                uvs = new List<Vector2>(count);
                for (int i = 0; i < count; i++) uvs.Add(new Vector2(uv[2 * i], uv[2 * i + 1]));
            }
            var tris = new List<int>(t.Length);
            foreach (float index in t) tris.Add((int)index);
            Mesh mesh = Build(name, v, uvs, tris);
            if (c != null && c.Length == count * 4)
            {
                var colors = new List<Color>(count);
                for (int i = 0; i < count; i++) colors.Add(new Color(c[4 * i], c[4 * i + 1], c[4 * i + 2], c[4 * i + 3]));
                mesh.SetColors(colors);
            }
            return mesh;
        }

        public static int TriangleCount(Mesh mesh)
        {
            long total = 0;
            for (int s = 0; s < mesh.subMeshCount; s++) total += mesh.GetIndexCount(s) / 3;
            return (int)total;
        }

        static Mesh Quad(float w, float h)
        {
            var v = new List<Vector3> { new Vector3(-w / 2, -h / 2, 0), new Vector3(w / 2, -h / 2, 0), new Vector3(-w / 2, h / 2, 0), new Vector3(w / 2, h / 2, 0) };
            var uv = new List<Vector2> { new Vector2(0, 0), new Vector2(1, 0), new Vector2(0, 1), new Vector2(1, 1) };
            return Build("quad", v, uv, new List<int> { 0, 2, 1, 2, 3, 1 });
        }

        static Mesh Plane(float w, float d, int sx, int sz)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int z = 0; z <= sz; z++)
                for (int x = 0; x <= sx; x++)
                {
                    v.Add(new Vector3((x / (float)sx - 0.5f) * w, 0, (z / (float)sz - 0.5f) * d));
                    uv.Add(new Vector2(x / (float)sx, z / (float)sz));
                }
            for (int z = 0; z < sz; z++)
                for (int x = 0; x < sx; x++)
                {
                    int a = z * (sx + 1) + x, b = a + 1, c = a + sx + 1, e = c + 1;
                    t.AddRange(new[] { a, c, b, b, c, e });
                }
            return Build("plane", v, uv, t);
        }

        static Mesh Cube(Vector3 size)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            Vector3[] normals = { Vector3.forward, Vector3.back, Vector3.up, Vector3.down, Vector3.right, Vector3.left };
            foreach (Vector3 n in normals)
            {
                Vector3 u = Mathf.Abs(n.y) > 0.5f ? Vector3.right : Vector3.up;
                Vector3 side = Vector3.Cross(n, u);
                int start = v.Count;
                Vector3 c = Vector3.Scale(n, size) * 0.5f;
                Vector3 su = Vector3.Scale(u, size) * 0.5f, ss = Vector3.Scale(side, size) * 0.5f;
                v.Add(c - su - ss); v.Add(c - su + ss); v.Add(c + su - ss); v.Add(c + su + ss);
                uv.Add(new Vector2(0, 0)); uv.Add(new Vector2(1, 0)); uv.Add(new Vector2(0, 1)); uv.Add(new Vector2(1, 1));
                t.AddRange(new[] { start, start + 2, start + 1, start + 2, start + 3, start + 1 });
            }
            return Build("cube", v, uv, t);
        }

        static Mesh Sphere(float r, int seg, int rings)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int y = 0; y <= rings; y++)
            {
                float lat = Mathf.PI * y / rings;
                for (int x = 0; x <= seg; x++)
                {
                    float lon = 2 * Mathf.PI * x / seg;
                    v.Add(new Vector3(Mathf.Sin(lat) * Mathf.Cos(lon), Mathf.Cos(lat), Mathf.Sin(lat) * Mathf.Sin(lon)) * r);
                    uv.Add(new Vector2(x / (float)seg, 1 - y / (float)rings));
                }
            }
            for (int y = 0; y < rings; y++)
                for (int x = 0; x < seg; x++)
                {
                    int a = y * (seg + 1) + x, b = a + 1, c = a + seg + 1, e = c + 1;
                    t.AddRange(new[] { a, b, c, b, e, c });
                }
            return Build("uv_sphere", v, uv, t);
        }

        static Mesh Ring(float inner, float outer, int seg)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int i = 0; i <= seg; i++)
            {
                float a = 2 * Mathf.PI * i / seg;
                var dir = new Vector3(Mathf.Cos(a), Mathf.Sin(a), 0);
                v.Add(dir * inner); v.Add(dir * outer);
                uv.Add(new Vector2(i / (float)seg, 0)); uv.Add(new Vector2(i / (float)seg, 1));
            }
            for (int i = 0; i < seg; i++)
            {
                int a = i * 2;
                t.AddRange(new[] { a, a + 2, a + 1, a + 1, a + 2, a + 3 });
            }
            return Build("ring", v, uv, t);
        }

        static Mesh Torus(float radius, float thickness, int seg, int sides)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int i = 0; i <= seg; i++)
            {
                float a = 2 * Mathf.PI * i / seg;
                var center = new Vector3(Mathf.Cos(a), Mathf.Sin(a), 0) * radius;
                var outward = center.normalized;
                for (int j = 0; j <= sides; j++)
                {
                    float b = 2 * Mathf.PI * j / sides;
                    v.Add(center + (outward * Mathf.Cos(b) + Vector3.forward * Mathf.Sin(b)) * thickness);
                    uv.Add(new Vector2(i / (float)seg, j / (float)sides));
                }
            }
            for (int i = 0; i < seg; i++)
                for (int j = 0; j < sides; j++)
                {
                    int a = i * (sides + 1) + j, b = a + 1, c = a + sides + 1, e = c + 1;
                    t.AddRange(new[] { a, c, b, b, c, e });
                }
            return Build("torus", v, uv, t);
        }

        static Mesh Tube(float radius, float length, int seg, int lseg, bool inside)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int z = 0; z <= lseg; z++)
                for (int i = 0; i <= seg; i++)
                {
                    float a = 2 * Mathf.PI * i / seg;
                    v.Add(new Vector3(Mathf.Cos(a) * radius, Mathf.Sin(a) * radius, length * z / lseg));
                    uv.Add(new Vector2(i / (float)seg, z / (float)lseg));
                }
            for (int z = 0; z < lseg; z++)
                for (int i = 0; i < seg; i++)
                {
                    int a = z * (seg + 1) + i, b = a + 1, c = a + seg + 1, e = c + 1;
                    if (inside) t.AddRange(new[] { a, c, b, b, c, e });
                    else t.AddRange(new[] { a, b, c, b, e, c });
                }
            return Build("tube", v, uv, t);
        }

        static Mesh Cone(float radius, float height, int seg)
        {
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            for (int i = 0; i < seg; i++)
            {
                float a0 = 2 * Mathf.PI * i / seg, a1 = 2 * Mathf.PI * (i + 1) / seg;
                var p0 = new Vector3(Mathf.Cos(a0) * radius, 0, Mathf.Sin(a0) * radius);
                var p1 = new Vector3(Mathf.Cos(a1) * radius, 0, Mathf.Sin(a1) * radius);
                int s = v.Count;
                v.Add(p0); v.Add(new Vector3(0, height, 0)); v.Add(p1);
                uv.Add(new Vector2(i / (float)seg, 0)); uv.Add(new Vector2((i + 0.5f) / seg, 1)); uv.Add(new Vector2((i + 1) / (float)seg, 0));
                t.AddRange(new[] { s, s + 1, s + 2 });
                s = v.Count;
                v.Add(p0); v.Add(p1); v.Add(Vector3.zero);
                uv.Add(new Vector2(0, 0)); uv.Add(new Vector2(1, 0)); uv.Add(new Vector2(0.5f, 0.5f));
                t.AddRange(new[] { s, s + 1, s + 2 });
            }
            return Build("cone", v, uv, t);
        }

        static Mesh Shard(float length, float width, int sides, int seed)
        {
            var rng = new System.Random(seed);
            var v = new List<Vector3>();
            var uv = new List<Vector2>();
            var t = new List<int>();
            var ring = new Vector3[sides];
            for (int i = 0; i < sides; i++)
            {
                float a = 2 * Mathf.PI * (i + (float)rng.NextDouble() * 0.4f) / sides;
                float r = width * (0.6f + 0.4f * (float)rng.NextDouble());
                ring[i] = new Vector3(Mathf.Cos(a) * r, length * (0.35f + 0.1f * (float)rng.NextDouble()), Mathf.Sin(a) * r);
            }
            var top = new Vector3(0, length, 0);
            for (int i = 0; i < sides; i++)
            {
                Vector3 a = ring[i], b = ring[(i + 1) % sides];
                int s = v.Count;
                v.Add(a); v.Add(top); v.Add(b);
                v.Add(b); v.Add(Vector3.zero); v.Add(a);
                for (int k = 0; k < 6; k++) uv.Add(new Vector2(k % 3 * 0.5f, k < 3 ? 1 : 0));
                t.AddRange(new[] { s, s + 1, s + 2, s + 3, s + 4, s + 5 });
            }
            return Build("shard", v, uv, t);
        }
    }
}
