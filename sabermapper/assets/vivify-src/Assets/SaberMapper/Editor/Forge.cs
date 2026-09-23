// SaberMapper asset forge: builds a Vivify asset bundle from a staged assets.json in Unity batchmode.
//
//   Unity.exe -batchmode -nographics -quit -projectPath <this project> -buildTarget Win64
//     -executeMethod SaberMapper.Forge.Build -forgeSpec <staged spec.json> -forgeOut <dir>
//     -forgeTarget windows2021 -logFile <log>
//
// `sabermapper assets build` stages the spec (paths resolved, shaders, textures and generator code copied
// into Assets/SaberMapper/) and parses the outputs: <forgeOut>/<bundle file>, bundleinfo.json in
// VivifyTemplate's format, and build-report.json. Every failure is reported as structured JSON.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace SaberMapper
{
    public class ForgeException : Exception
    {
        public readonly string Code, Asset, Fix;

        public ForgeException(string code, string message, string asset = null, string fix = null) : base(message)
        {
            Code = code;
            Asset = asset;
            Fix = fix;
        }
    }

    public static class Forge
    {
        const string Tag = "[SaberMapperForge] ";
        static readonly List<object> Errors = new List<object>();
        static readonly List<object> Warnings = new List<object>();

        static string Arg(string[] args, string name)
        {
            int i = Array.IndexOf(args, name);
            return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
        }

        static Dictionary<string, object> Issue(string code, string message, string asset, string file, int line, string fix)
        {
            var issue = new Dictionary<string, object> { { "code", code }, { "message", message } };
            if (asset != null) issue["asset"] = asset;
            if (file != null) issue["file"] = file;
            if (line > 0) issue["line"] = line;
            if (fix != null) issue["fix"] = fix;
            return issue;
        }

        static void Error(string code, string message, string asset = null, string file = null, int line = 0, string fix = null)
        {
            var issue = Issue(code, message, asset, file, line, fix);
            Errors.Add(issue);
            Debug.Log(Tag + ForgeJson.Write(issue, false));
        }

        static void Warn(string code, string message, string asset = null, string fix = null)
        {
            Warnings.Add(Issue(code, message, asset, null, 0, fix));
        }

        static void OnLog(string condition, string stack, LogType type)
        {
            if ((type == LogType.Error || type == LogType.Warning) && condition.StartsWith("Shader error in", StringComparison.Ordinal))
                Error("shader_compile_error", condition.Trim(), fix: "Fix the shader source at the reported line and rebuild");
        }

        /// <summary>Batchmode entry point.</summary>
        public static void Build()
        {
            string[] args = Environment.GetCommandLineArgs();
            string specPath = Arg(args, "-forgeSpec");
            string outDir = Arg(args, "-forgeOut");
            var report = new Dictionary<string, object>
            {
                { "format", "sabermapper-forge-report/1" },
                { "unity_version", Application.unityVersion },
                { "started_at", DateTime.UtcNow.ToString("o") }
            };
            int exitCode = 1;
            Errors.Clear();
            Warnings.Clear();
            Application.logMessageReceived += OnLog;
            try
            {
                if (string.IsNullOrEmpty(specPath) || string.IsNullOrEmpty(outDir))
                    throw new ForgeException("forge_arguments", "Pass -forgeSpec <spec.json> and -forgeOut <dir>");
                Directory.CreateDirectory(outDir);
                var spec = ForgeJson.Parse(File.ReadAllText(specPath)) as Dictionary<string, object>;
                if (spec == null) throw new ForgeException("forge_spec", "The staged spec is not a JSON object");
                string target = Arg(args, "-forgeTarget") ?? new ForgeParams(spec).String("target", "windows2021");
                report["target"] = target;
                Run(spec, target, outDir, report);
                exitCode = Errors.Count == 0 ? 0 : 1;
            }
            catch (ForgeException e)
            {
                Error(e.Code, e.Message, e.Asset, fix: e.Fix);
            }
            catch (Exception e)
            {
                Error("forge_exception", e.ToString(), fix: "Report this build log; the forge hit an unexpected editor exception");
            }
            finally
            {
                Application.logMessageReceived -= OnLog;
                if (Errors.Count > 0) exitCode = 1;
                report["ok"] = exitCode == 0;
                report["errors"] = Errors;
                report["warnings"] = Warnings;
                report["finished_at"] = DateTime.UtcNow.ToString("o");
                if (!string.IsNullOrEmpty(outDir))
                {
                    Directory.CreateDirectory(outDir);
                    File.WriteAllText(Path.Combine(outDir, "build-report.json"), ForgeJson.Write(report));
                }
                Debug.Log(Tag + "finished ok=" + (exitCode == 0));
            }
            EditorApplication.Exit(exitCode);
        }

        static void Run(Dictionary<string, object> specRaw, string target, string outDir, Dictionary<string, object> report)
        {
            var spec = new ForgeParams(specRaw);
            int major = int.Parse(Application.unityVersion.Split('.')[0]);
            if (target == "windows2021" && major <= 2019)
                throw new ForgeException("editor_target_mismatch",
                    "windows2021 bundles need Unity 2021.3 keyword serialization; this editor is " + Application.unityVersion,
                    fix: "Install Unity 2021.3.16f1 (or pass --target windows2019 for game 1.29.1 only)");
            if (target == "windows2019" && major != 2019)
                throw new ForgeException("editor_target_mismatch", "windows2019 bundles need Unity 2019.4.28f1; this editor is " + Application.unityVersion,
                    fix: "Use --target windows2021 for game 1.30+");
            if (target != "windows2021" && target != "windows2019")
                throw new ForgeException("target_unsupported", "Unsupported forge target '" + target + "'", fix: "Use windows2021");

            ConfigurePlayer(target, spec.Bool("allow_no_xr", false), report);
            AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

            var budgets = spec.Child("budgets");
            var assets = spec.List("assets");
            var created = new List<string>();
            var shaders = new Dictionary<string, Shader>();
            var materials = new Dictionary<string, Material>();
            var meshes = new Dictionary<string, Mesh>();
            var textures = new Dictionary<string, Texture>();
            var assetReports = new List<object>();
            int totalTriangles = 0, totalRenderers = 0, totalParticles = 0;

            foreach (object rawAsset in assets)
            {
                var a = new ForgeParams(rawAsset);
                string id = a.String("id", "?"), kind = a.String("kind", ""), path = a.String("unity_path", "");
                var entry = new Dictionary<string, object> { { "id", id }, { "kind", kind }, { "path", path.ToLowerInvariant() } };
                try
                {
                    EnsureFolder(Path.GetDirectoryName(path).Replace('\\', '/'));
                    switch (kind)
                    {
                        case "texture":
                            textures[id] = ImportTexture(path, a.Child("texture"), id);
                            break;
                        case "mesh":
                        {
                            Mesh mesh = GenerateMesh(a.Child("mesh"), id);
                            int tris = ForgeMeshes.TriangleCount(mesh);
                            entry["triangles"] = tris;
                            int limit = a.Child("mesh").Int("max_triangles", budgets.Int("max_triangles_per_mesh", 20000));
                            limit = Math.Min(limit, budgets.Int("max_triangles_per_mesh", 20000));
                            if (tris > limit)
                                Error("mesh_budget_exceeded", "Mesh has " + tris + " triangles; the limit is " + limit, id,
                                      fix: "Lower the generator's segment counts or raise budgets.max_triangles_per_mesh deliberately");
                            DeleteIfExists(path);
                            AssetDatabase.CreateAsset(mesh, path);
                            meshes[id] = mesh;
                            break;
                        }
                        case "material":
                        case "post_process":
                        case "skybox":
                            materials[id] = CreateMaterial(a, path, id, shaders, textures);
                            break;
                        case "prefab":
                        case "particles":
                        {
                            int renderers, particles, triangles;
                            CreatePrefab(a, path, id, materials, meshes, out renderers, out particles, out triangles);
                            entry["renderers"] = renderers;
                            entry["max_particles"] = particles;
                            entry["triangles"] = triangles;
                            totalRenderers += renderers;
                            totalParticles += particles;
                            totalTriangles += triangles;
                            break;
                        }
                        default:
                            throw new ForgeException("asset_kind_unknown", "Unknown asset kind '" + kind + "'", id);
                    }
                    created.Add(path);
                }
                catch (ForgeException e)
                {
                    Error(e.Code, e.Message, e.Asset ?? id, fix: e.Fix);
                }
                catch (Exception e)
                {
                    Exception inner = e is TargetInvocationException && e.InnerException != null ? e.InnerException : e;
                    Error("asset_failed", inner.GetType().Name + ": " + inner.Message, id,
                          fix: "Check this asset's parameters (and generator code for tier-2 meshes)");
                }
                assetReports.Add(entry);
            }
            foreach (var pair in shaders) created.Add(AssetDatabase.GetAssetPath(pair.Value));
            AssetDatabase.SaveAssets();

            CheckBudget("max_total_triangles", totalTriangles, budgets.Int("max_total_triangles", 150000), "triangles across all prefabs");
            CheckBudget("max_renderers", totalRenderers, budgets.Int("max_renderers", 64), "renderers (draw calls) across all prefabs");
            CheckBudget("max_particles", totalParticles, budgets.Int("max_particles", 4000), "max particles across all particle systems");
            report["assets"] = assetReports;
            report["totals"] = new Dictionary<string, object> { { "triangles", totalTriangles }, { "renderers", totalRenderers }, { "max_particles", totalParticles } };
            if (Errors.Count > 0) return;

            string bundleName = spec.String("bundle_name", "sabermapper").ToLowerInvariant();
            var bundlePaths = created.Where(p => !string.IsNullOrEmpty(p)).Distinct().ToArray();
            foreach (string assetPath in bundlePaths)
            {
                AssetImporter importer = AssetImporter.GetAtPath(assetPath);
                if (importer != null) importer.assetBundleName = bundleName;
            }
            BuildBundle(spec, target, bundleName, bundlePaths, outDir, materials, report);
        }

        static void CheckBudget(string key, int value, int limit, string what)
        {
            if (value > limit)
                Error("budget_exceeded", "Spec uses " + value + " " + what + "; budgets." + key + " is " + limit,
                      fix: "Simplify the assets or raise budgets." + key + " deliberately");
        }

        static void ConfigurePlayer(string target, bool allowNoXR, Dictionary<string, object> report)
        {
            if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.StandaloneWindows64)
                EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone, BuildTarget.StandaloneWindows64);
            PlayerSettings.colorSpace = ColorSpace.Linear;
            var xr = new Dictionary<string, object>();
            if (target == "windows2019")
            {
                // Legacy built-in VR (removed after 2019): set through reflection so this file compiles everywhere.
                PropertyInfo vr = typeof(PlayerSettings).GetProperty("virtualRealitySupported", BindingFlags.Public | BindingFlags.Static);
                if (vr != null) vr.SetValue(null, true, null);
                PlayerSettings.stereoRenderingPath = StereoRenderingPath.SinglePass;
                xr["stereo_rendering"] = "SinglePass";
            }
            else
            {
                PlayerSettings.stereoRenderingPath = StereoRenderingPath.Instancing;
                xr["stereo_rendering"] = "SinglePassInstanced";
                string problem = SaberMapper.XR.ForgeXR.EnsureStandaloneOpenXR();
                xr["loader"] = problem == null ? SaberMapper.XR.ForgeXR.OpenXRLoader : null;
                if (problem != null)
                {
                    if (allowNoXR)
                        Warn("xr_not_configured", problem + "; shaders may render in the left eye only", fix: "Let Unity resolve Packages/manifest.json");
                    else
                        throw new ForgeException("xr_not_configured", problem + ". Without an XR loader Unity may strip the single-pass-instanced shader variants",
                            fix: "Let Unity resolve com.unity.xr.management and com.unity.xr.openxr from Packages/manifest.json (network on first run), or pass --allow-no-xr");
                }
            }
            report["xr"] = xr;
            AssetDatabase.SaveAssets();
        }

        static void EnsureFolder(string folder)
        {
            if (string.IsNullOrEmpty(folder) || AssetDatabase.IsValidFolder(folder)) return;
            string parent = Path.GetDirectoryName(folder).Replace('\\', '/');
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, Path.GetFileName(folder));
        }

        static void DeleteIfExists(string path)
        {
            if (AssetDatabase.LoadMainAssetAtPath(path) != null) AssetDatabase.DeleteAsset(path);
        }

        static Texture ImportTexture(string path, ForgeParams t, string id)
        {
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport);
            var importer = AssetImporter.GetAtPath(path) as TextureImporter;
            if (importer == null) throw new ForgeException("texture_missing", "No texture was staged at " + path, id, "Check the asset's source file");
            importer.sRGBTexture = t.Bool("srgb", true);
            importer.mipmapEnabled = t.Bool("mipmaps", true);
            importer.wrapMode = t.String("wrap", "repeat") == "clamp" ? TextureWrapMode.Clamp : TextureWrapMode.Repeat;
            importer.maxTextureSize = t.Int("max_size", 2048);
            importer.alphaIsTransparency = t.Bool("alpha_is_transparency", false);
            if (t.String("shape", "2d") == "cube")
            {
                importer.textureShape = TextureImporterShape.TextureCube;
                importer.generateCubemap = TextureImporterGenerateCubemap.Cylindrical;
            }
            importer.SaveAndReimport();
            var texture = AssetDatabase.LoadAssetAtPath<Texture>(path);
            if (texture == null) throw new ForgeException("texture_import_failed", "Unity could not import " + path, id);
            return texture;
        }

        static Mesh GenerateMesh(ForgeParams m, string id)
        {
            string className = m.String("class", null);
            string data = m.String("data_unity_path", null);
            ForgeParams p = m.Child("params");
            Mesh mesh;
            if (data != null)
            {
                mesh = ForgeMeshes.FromData(data, id);
            }
            else if (className == null)
            {
                mesh = ForgeMeshes.Generate(m.String("generator", "quad"), p);
            }
            else
            {
                Type type = null;
                foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
                {
                    type = asm.GetType(className);
                    if (type != null) break;
                }
                if (type == null)
                    throw new ForgeException("generator_class_missing", "Generator class " + className + " was not compiled", id,
                        "Check the class name and namespace in the generator source (see the C# errors in the log)");
                MethodInfo method = type.GetMethod("Generate", BindingFlags.Public | BindingFlags.Static, null, new[] { typeof(ForgeParams) }, null);
                if (method == null || method.ReturnType != typeof(Mesh))
                    throw new ForgeException("generator_signature", className + " needs `public static Mesh Generate(SaberMapper.ForgeParams p)`", id);
                mesh = (Mesh)method.Invoke(null, new object[] { p });
                if (mesh == null) throw new ForgeException("generator_null", className + ".Generate returned null", id);
            }
            mesh.name = id;
            return mesh;
        }

        static Material CreateMaterial(ForgeParams a, string path, string id, Dictionary<string, Shader> shaders, Dictionary<string, Texture> textures)
        {
            string shaderPath = a.String("shader_unity_path", null);
            if (shaderPath == null) throw new ForgeException("shader_missing", "Material has no staged shader", id);
            Shader shader;
            if (!shaders.TryGetValue(shaderPath, out shader))
            {
                AssetDatabase.ImportAsset(shaderPath, ImportAssetOptions.ForceSynchronousImport);
                shader = AssetDatabase.LoadAssetAtPath<Shader>(shaderPath);
                if (shader == null) throw new ForgeException("shader_import_failed", "Unity could not import " + shaderPath, id);
                shaders[shaderPath] = shader;
                ReportShaderMessages(shader, shaderPath, id);
            }
            var material = new Material(shader) { name = Path.GetFileNameWithoutExtension(path) };
            var props = a.Child("properties");
            var types = new Dictionary<string, ShaderPropertyType>();
            for (int i = 0; i < shader.GetPropertyCount(); i++) types[shader.GetPropertyName(i)] = shader.GetPropertyType(i);
            foreach (var pair in props.Raw)
            {
                ShaderPropertyType type;
                if (!types.TryGetValue(pair.Key, out type))
                {
                    Error("property_unknown", "Shader " + shader.name + " has no property " + pair.Key, id, fix: "Use a property from the shader's Properties block");
                    continue;
                }
                switch (type)
                {
                    case ShaderPropertyType.Color:
                        material.SetColor(pair.Key, props.Color(pair.Key, Color.white));
                        break;
                    case ShaderPropertyType.Vector:
                    {
                        float[] f = props.Floats(pair.Key, new float[4]);
                        material.SetVector(pair.Key, new Vector4(f.Length > 0 ? f[0] : 0, f.Length > 1 ? f[1] : 0, f.Length > 2 ? f[2] : 0, f.Length > 3 ? f[3] : 0));
                        break;
                    }
                    case ShaderPropertyType.Texture:
                    {
                        string texId = props.Child(pair.Key).String("texture", null);
                        Texture tex;
                        if (texId == null || !textures.TryGetValue(texId, out tex))
                            Error("texture_reference", "Property " + pair.Key + " references unknown texture asset '" + texId + "'", id);
                        else
                            material.SetTexture(pair.Key, tex);
                        break;
                    }
                    default:
                        material.SetFloat(pair.Key, props.Float(pair.Key, 0));
                        break;
                }
            }
            if (a.Has("render_queue")) material.renderQueue = a.Int("render_queue", -1);
            material.enableInstancing = true;
            DeleteIfExists(path);
            AssetDatabase.CreateAsset(material, path);
            return material;
        }

        static void ReportShaderMessages(Shader shader, string shaderPath, string id)
        {
#if UNITY_2020_1_OR_NEWER
            if (!ShaderUtil.ShaderHasError(shader)) return;
            foreach (ShaderMessage message in ShaderUtil.GetShaderMessages(shader))
            {
                if (message.severity != UnityEditor.Rendering.ShaderCompilerMessageSeverity.Error) continue;
                Error("shader_compile_error", message.message + (string.IsNullOrEmpty(message.messageDetails) ? "" : " — " + message.messageDetails),
                      id, string.IsNullOrEmpty(message.file) ? shaderPath : message.file, message.line,
                      "Fix the shader source at the reported line and rebuild");
            }
#endif
        }

        static void CreatePrefab(ForgeParams a, string path, string id, Dictionary<string, Material> materials, Dictionary<string, Mesh> meshes,
                                 out int renderers, out int particles, out int triangles)
        {
            renderers = particles = triangles = 0;
            var root = new GameObject(Path.GetFileNameWithoutExtension(path));
            try
            {
                if (a.String("kind", "") == "particles")
                {
                    particles += ForgeParticles.Configure(root, a.Child("particles"), ResolveMaterial(a.String("material", null), materials, id),
                                                          ResolveMesh(a.Child("particles").Child("renderer").String("mesh", null), meshes, id, true));
                    renderers++;
                }
                foreach (object rawChild in a.List("children"))
                {
                    var c = new ForgeParams(rawChild);
                    var go = new GameObject(c.String("name", "child"));
                    go.transform.SetParent(root.transform, false);
                    go.transform.localPosition = c.Vec3("position", Vector3.zero);
                    go.transform.localEulerAngles = c.Vec3("rotation", Vector3.zero);
                    go.transform.localScale = c.Vec3("scale", Vector3.one);
                    Material material = ResolveMaterial(c.String("material", null), materials, id);
                    if (c.Has("particles"))
                    {
                        particles += ForgeParticles.Configure(go, c.Child("particles"), material,
                                                              ResolveMesh(c.Child("particles").Child("renderer").String("mesh", null), meshes, id, true));
                        renderers++;
                    }
                    else
                    {
                        Mesh mesh = ResolveMesh(c.Child("mesh").String("asset", null), meshes, id, false);
                        go.AddComponent<MeshFilter>().sharedMesh = mesh;
                        var mr = go.AddComponent<MeshRenderer>();
                        mr.sharedMaterial = material;
                        mr.shadowCastingMode = ShadowCastingMode.Off;
                        mr.receiveShadows = false;
                        renderers++;
                        triangles += ForgeMeshes.TriangleCount(mesh);
                    }
                }
                DeleteIfExists(path);
                bool success;
                PrefabUtility.SaveAsPrefabAsset(root, path, out success);
                if (!success) throw new ForgeException("prefab_save_failed", "Unity could not save " + path, id);
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }

        static Material ResolveMaterial(string materialId, Dictionary<string, Material> materials, string owner)
        {
            Material material;
            if (materialId == null || !materials.TryGetValue(materialId, out material))
                throw new ForgeException("material_reference", "Unknown or failed material asset '" + materialId + "'", owner,
                    "Reference the id of a material asset declared earlier in assets.json");
            return material;
        }

        static Mesh ResolveMesh(string meshId, Dictionary<string, Mesh> meshes, string owner, bool optional)
        {
            if (meshId == null && optional) return null;
            Mesh mesh;
            if (meshId == null || !meshes.TryGetValue(meshId, out mesh))
                throw new ForgeException("mesh_reference", "Unknown or failed mesh asset '" + meshId + "'", owner,
                    "Reference a mesh asset id (inline meshes are normalized by `sabermapper assets build`)");
            return mesh;
        }

        static void BuildBundle(ForgeParams spec, string target, string bundleName, string[] assetPaths, string outDir,
                                Dictionary<string, Material> materials, Dictionary<string, object> report)
        {
            string compression = spec.String("compression", "lz4");
            BuildAssetBundleOptions options = BuildAssetBundleOptions.ForceRebuildAssetBundle | BuildAssetBundleOptions.StrictMode;
            if (compression == "lz4") options |= BuildAssetBundleOptions.ChunkBasedCompression;
            else if (compression == "none") options |= BuildAssetBundleOptions.UncompressedAssetBundle;
            string temp = Path.Combine(Path.GetTempPath(), "sabermapper-forge", bundleName + "-" + target);
            if (Directory.Exists(temp)) Directory.Delete(temp, true);
            Directory.CreateDirectory(temp);
            var builds = new[] { new AssetBundleBuild { assetBundleName = bundleName, assetNames = assetPaths } };
            AssetBundleManifest manifest = BuildPipeline.BuildAssetBundles(temp, builds, options, BuildTarget.StandaloneWindows64);
            if (manifest == null)
                throw new ForgeException("bundle_build_failed", "BuildPipeline.BuildAssetBundles returned no manifest",
                    fix: "Read the errors above in this report and the Unity log");
            if (Errors.Count > 0) return;
            string built = Path.Combine(temp, bundleName);
            uint crc;
            if (!BuildPipeline.GetCRCForAssetBundle(built, out crc))
                throw new ForgeException("crc_unavailable", "Unity returned no CRC for " + built);
            string fileName = spec.String("bundle_file", "bundleWindows2021.vivify");
            string output = Path.Combine(outDir, fileName);
            File.Copy(built, output, true);
            if (File.Exists(built + ".manifest")) File.Copy(built + ".manifest", output + ".manifest", true);

            string crcKey = spec.String("crc_key", "_windows2021");
            report["bundle_name"] = bundleName;
            report["bundle_file"] = fileName;
            report["crc"] = crc;
            report["crc_key"] = crcKey;
            report["compression"] = compression;
            report["bundle_assets"] = manifest.GetAllAssetBundles().Length > 0
                ? AssetDatabase.GetAssetPathsFromAssetBundle(bundleName).Select(p => (object)p.ToLowerInvariant()).ToList()
                : new List<object>();
            WriteBundleInfo(assetPaths, output, crcKey, crc, compression != "none", outDir);
        }

        static void WriteBundleInfo(string[] assetPaths, string bundleOutput, string crcKey, uint crc, bool compressed, string outDir)
        {
            // Same shape as VivifyTemplate's BundleInfoProcessor (MIT, Swifter1243): materials with typed
            // property values, prefabs by file name, bundleFiles, bundleCRCs and isCompressed.
            var materialInfo = new Dictionary<string, object>();
            var prefabInfo = new Dictionary<string, object>();
            foreach (string assetPath in assetPaths)
            {
                string lower = assetPath.ToLowerInvariant();
                string stem = Path.GetFileNameWithoutExtension(lower);
                if (lower.EndsWith(".mat"))
                {
                    var material = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
                    if (material == null) continue;
                    var props = new Dictionary<string, object>();
                    Shader shader = material.shader;
                    for (int i = 0; i < shader.GetPropertyCount(); i++)
                    {
                        string name = shader.GetPropertyName(i);
                        object value;
                        string type;
                        switch (shader.GetPropertyType(i))
                        {
                            case ShaderPropertyType.Color:
                            {
                                Color c = material.GetColor(name);
                                value = new List<object> { c.r, c.g, c.b, c.a };
                                type = "Color";
                                break;
                            }
                            case ShaderPropertyType.Vector:
                            {
                                Vector4 v = material.GetVector(name);
                                value = new List<object> { v.x, v.y, v.z, v.w };
                                type = "Vector";
                                break;
                            }
                            case ShaderPropertyType.Texture:
                                value = "";
                                type = "Texture";
                                break;
                            default:
                                value = material.GetFloat(name);
                                type = "Float";
                                break;
                        }
                        props[name] = new Dictionary<string, object> { { "value", value }, { "type", new Dictionary<string, object> { { type, null } } } };
                    }
                    materialInfo[Unique(materialInfo, stem)] = new Dictionary<string, object> { { "path", lower }, { "properties", props } };
                }
                else if (lower.EndsWith(".prefab"))
                {
                    prefabInfo[Unique(prefabInfo, stem)] = lower;
                }
            }
            var info = new Dictionary<string, object>
            {
                { "materials", materialInfo },
                { "prefabs", prefabInfo },
                { "bundleFiles", new List<object> { bundleOutput.Replace('\\', '/') } },
                { "bundleCRCs", new Dictionary<string, object> { { crcKey, crc } } },
                { "isCompressed", compressed }
            };
            File.WriteAllText(Path.Combine(outDir, "bundleinfo.json"), ForgeJson.Write(info));
        }

        static string Unique(Dictionary<string, object> taken, string key)
        {
            string candidate = key;
            int n = 0;
            while (taken.ContainsKey(candidate)) candidate = key + " (" + (++n) + ")";
            return candidate;
        }
    }
}
