"""Asset forge: library integrity, shader lint, spec validation, Unity location and the batchmode driver (stubbed)."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from sabermapper import forge
from sabermapper.__main__ import main

# Stands in for Unity.exe: reads the forge arguments, records them, and writes a log plus outputs per FORGE_STUB_MODE.
UNITY_STUB = textwrap.dedent(r'''
    import json, os, sys
    args = sys.argv[1:]
    arg = lambda name: args[args.index(name) + 1]
    mode = os.environ.get("FORGE_STUB_MODE", "ok")
    out, log = arg("-forgeOut"), arg("-logFile")
    with open(os.environ["FORGE_STUB_ARGV"], "w") as f:
        json.dump(args, f)
    spec = json.load(open(arg("-forgeSpec"), encoding="utf-8"))
    os.makedirs(out, exist_ok=True)
    lines = ["Initialize engine version: 2021.3.45f1 (0da89fac8e79)"]
    def report(ok, **extra):
        with open(os.path.join(out, "build-report.json"), "w") as f:
            json.dump({"format": "sabermapper-forge-report/1", "ok": ok, "errors": [], "warnings": [], **extra}, f)
    if mode == "license":
        lines.append("No valid Unity Editor license found. Please activate your license.")
        open(log, "w").write("\n".join(lines)); sys.exit(1)
    if mode == "headless_license":
        lines += ["Entitlement-based licensing initiated", "[Licensing::Module] Error: Access token is unavailable",
                  "BatchMode: Unity has not been activated with a valid License. Could be a new activation or renewal..."]
        open(log, "w").write("\n".join(lines)); sys.exit(1)
    if mode == "cs_error":
        lines += [f"Assets/SaberMapper/Staging/Editor/{spec['project']}_Ribbon.cs(12,9): error CS1002: ; expected",
                  "Scripts have compiler errors.",
                  "executeMethod method SaberMapper.Forge.Build could not be found."]
        open(log, "w").write("\n".join(lines)); sys.exit(1)
    if mode == "shader_error":
        lines.append("Shader error in 'SaberMapper/Post/Vignette': undeclared identifier 'foo' at line 58 (on d3d11)")
        report(False, errors=[{"code": "shader_compile_error", "message": "undeclared identifier 'foo'"}])
        open(log, "w").write("\n".join(lines)); sys.exit(1)
    crc = 1234567890
    bundle = os.path.join(out, spec["bundle_file"])
    with open(bundle, "wb") as f:
        f.write(b"UnityFS\x00\x00\x00\x00\x065.x.x\x002021.3.45f1\x00" + b"\x00" * 64)
    with open(bundle + ".manifest", "w") as f:
        f.write("ManifestFileVersion: 0\nCRC: %d\n" % (crc + 1 if mode == "crc_mismatch" else crc))
    mats = {a["unity_path"].lower().rsplit("/", 1)[-1][:-4]: {"path": a["unity_path"].lower(), "properties": {
        "_Strength": {"value": 0.4, "type": {"Float": None}}}} for a in spec["assets"] if a["unity_path"].endswith(".mat")}
    prefabs = {a["unity_path"].lower().rsplit("/", 1)[-1][:-7]: a["unity_path"].lower()
               for a in spec["assets"] if a["unity_path"].endswith(".prefab")}
    with open(os.path.join(out, "bundleinfo.json"), "w") as f:
        json.dump({"materials": mats, "prefabs": prefabs, "bundleFiles": [bundle], "bundleCRCs": {spec["crc_key"]: crc},
                   "isCompressed": True}, f)
    report(True, crc=crc, crc_key=spec["crc_key"], bundle_file=spec["bundle_file"], warnings=[{"code": "stub"}])
    lines.append("[SaberMapperForge] finished ok=True")
    open(log, "w").write("\n".join(lines))
''')

RIBBON_CS = textwrap.dedent('''
    using UnityEngine;
    namespace SaberMapper.Generated
    {
        public static class RibbonMesh
        {
            public static Mesh Generate(SaberMapper.ForgeParams p)
            {
                return ForgeMeshes.Generate("quad", p);
            }
        }
    }
''')

GOOD_SHADER = forge.library_shader_path(forge.load_library(), "sm_vignette").read_text(encoding="utf-8")


def run_cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, json.loads(out.getvalue())


class ForgeTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hub = self.root / "hub"
        self.hub.mkdir()
        env = {"SABERMAPPER_FORGE_CONFIG": str(self.root / "forge.json"), "SABERMAPPER_UNITY_HUB_ROOTS": str(self.hub),
               "FORGE_STUB_ARGV": str(self.root / "argv.json"), "LOCALAPPDATA": str(self.root / "local")}
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("SABERMAPPER_UNITY", None)
        os.environ.pop("FORGE_STUB_MODE", None)
        self.workspace = self.root / "workspace"
        self.project = self.workspace / "projects" / "Demo-Song"
        self.project.mkdir(parents=True)
        (self.project / "project.json").write_text("{}", encoding="utf-8")
        self.stub = self.root / "unity_stub.py"
        self.stub.write_text(UNITY_STUB, encoding="utf-8")
        self.library = forge.load_library()

    def spec_file(self, spec=None, directory=None):
        directory = directory or self.project / "assets"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "assets.json"
        path.write_text(json.dumps(spec or forge.starter_spec("demo-song"), indent=2), encoding="utf-8")
        return path

    def rules(self, spec, base=None):
        diags, summary = forge.validate_spec(spec, base or self.root, self.library)
        return {d["rule"] for d in diags if d["severity"] == "error"}, {d["rule"] for d in diags if d["severity"] == "warning"}, summary


class LibraryTests(ForgeTestCase):
    def test_every_library_shader_is_lint_clean_and_matches_library_json(self):
        for sid, entry in self.library["shaders"].items():
            text = forge.library_shader_path(self.library, sid).read_text(encoding="utf-8")
            self.assertEqual([], forge.lint_shader(text, kind=entry["kinds"][0], file=sid), sid)
            parsed = forge.parse_shader(text)
            self.assertEqual(entry["shader_name"], parsed["name"], sid)
            declared = set(parsed["properties"]) - ({"_MainTex"} if entry["kinds"] == ["post_process"] else set())
            self.assertEqual(set(entry["properties"]), declared, sid)
            for name, prop in entry["properties"].items():
                shader_prop = parsed["properties"][name]
                self.assertEqual(prop["type"], shader_prop["type"], f"{sid}.{name}")
                self.assertEqual(prop["default"], shader_prop["default"], f"{sid}.{name}")
                if prop.get("safe"):
                    low, high = shader_prop["range"]
                    self.assertTrue(low <= prop["safe"][0] <= prop["safe"][1] <= high, f"{sid}.{name}")
                self.assertTrue(prop["meaning"].strip())
            self.assertTrue(entry["intent"].strip() and entry["description"].strip())

    def test_library_md_is_generated_from_library_json(self):
        raw = json.loads((forge.LIBRARY_DIR / "library.json").read_text(encoding="utf-8"))
        self.assertEqual(forge.render_library_md(raw), (forge.LIBRARY_DIR / "library.md").read_text(encoding="utf-8"))

    def test_mesh_generators_match_the_csharp_builder(self):
        source = (forge.TEMPLATE_DIR / "Assets/SaberMapper/Editor/ForgeMeshes.cs").read_text(encoding="utf-8")
        names = re.search(r"Names\s*=\s*\{([^}]*)\}", source).group(1)
        self.assertEqual(set(self.library["meshes"]), set(re.findall(r'"(\w+)"', names)))
        for name in self.library["meshes"]:
            self.assertIn(f'case "{name}":', source)
            self.assertGreater(forge.mesh_triangles(name, {}, self.library), 0)
        self.assertEqual(2 * 64 * 8, forge.mesh_triangles("torus", {}, self.library))
        self.assertEqual(2 * 3 * 3, forge.mesh_triangles("torus", {"segments": 1, "sides": 2}, self.library))

    def test_template_is_text_only_and_pins_the_researched_editor(self):
        for path in forge.TEMPLATE_DIR.rglob("*"):
            if path.is_file():
                self.assertNotIn(path.suffix.lower(), {".dll", ".exe", ".asset", ".unity", ".vivify", ".meta"}, path)
                path.read_text(encoding="utf-8")
        version = (forge.TEMPLATE_DIR / "ProjectSettings/ProjectVersion.txt").read_text(encoding="utf-8")
        self.assertIn(f"m_EditorVersion: {forge.TARGETS[forge.DEFAULT_TARGET]['unity_version']}", version)
        manifest = json.loads((forge.TEMPLATE_DIR / "Packages/manifest.json").read_text(encoding="utf-8"))
        self.assertIn("com.unity.xr.management", manifest["dependencies"])
        self.assertIn("com.unity.xr.openxr", manifest["dependencies"])
        builder = (forge.TEMPLATE_DIR / "Assets/SaberMapper/Editor/Forge.cs").read_text(encoding="utf-8")
        self.assertIn("namespace SaberMapper", builder)
        self.assertIn("public static void Build()", builder)
        for key in ("materials", "prefabs", "bundleFiles", "bundleCRCs", "isCompressed"):
            self.assertIn(f'"{key}"', builder)
        self.assertEqual("bundleWindows2021.vivify", forge.TARGETS["windows2021"]["bundle_file"])
        self.assertEqual("_windows2021", forge.TARGETS["windows2021"]["crc_key"])


class ShaderLintTests(ForgeTestCase):
    def rules_for(self, text, kind="post_process"):
        return {d["rule"]: d for d in forge.lint_shader(text, kind=kind, file="x.shader")}

    def test_missing_stereo_macros_are_errors_with_lines(self):
        broken = GOOD_SHADER.replace("                UNITY_VERTEX_OUTPUT_STEREO\n", "")
        found = self.rules_for(broken)
        self.assertIn("stereo_output", found)
        self.assertEqual("error", found["stereo_output"]["severity"])
        line = broken.splitlines()[found["stereo_output"]["line"] - 1]
        self.assertIn("struct v2f", line)
        for macro, rule in (("UNITY_VERTEX_INPUT_INSTANCE_ID\n", "stereo_input_instance_id"),
                            ("UNITY_SETUP_INSTANCE_ID(v);", "stereo_setup_instance"),
                            ("UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(o);", "stereo_init_output"),
                            ("UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(i);", "stereo_eye_index")):
            self.assertIn(rule, self.rules_for(GOOD_SHADER.replace(macro, "")), rule)

    def test_blit_must_sample_the_screen_texture_array(self):
        broken = GOOD_SHADER.replace("UNITY_DECLARE_SCREENSPACE_TEXTURE(_MainTex);", "sampler2D _MainTex;").replace(
            "UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv)", "tex2D(_MainTex, uv)")
        found = self.rules_for(broken)
        self.assertIn("screenspace_declare", found)
        self.assertIn("screenspace_sample", found)
        self.assertIn("sampler2D _MainTex", broken.splitlines()[found["screenspace_declare"]["line"] - 1])
        self.assertNotIn("screenspace_declare", self.rules_for(broken, kind="material"))

    def test_cost_heuristic_counts_loops_and_function_calls(self):
        loop = GOOD_SHADER.replace(
            "float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv);",
            "float4 src = 0; for (int k = 0; k < 40; k++) { src += UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv); }")
        cost = forge.shader_cost(loop)
        self.assertEqual(40, cost["texture_samples"])
        self.assertIn("cost_texture_samples", self.rules_for(loop))
        unbounded = GOOD_SHADER.replace("float4 src = UNITY_SAMPLE_SCREENSPACE_TEXTURE(_MainTex, uv);",
                                        "float4 src = 0; for (int k = 0; k < _Strength; k++) { src += 1; }")
        self.assertEqual("warning", self.rules_for(unbounded)["unbounded_loop"]["severity"])
        glow = forge.library_shader_path(self.library, "sm_glow").read_text(encoding="utf-8")
        self.assertEqual(13, forge.shader_cost(glow)["texture_samples"])


class SpecValidationTests(ForgeTestCase):
    def test_starter_spec_is_valid_and_counts_budgets(self):
        errors, warnings, summary = self.rules(forge.starter_spec("demo-song"))
        self.assertEqual(set(), errors)
        self.assertEqual(2 * 64 * 8, summary["triangles"])
        self.assertEqual(2, summary["renderers"])
        self.assertEqual(300, summary["max_particles"])

    def test_path_id_property_and_reference_rules(self):
        spec = forge.starter_spec("demo-song")
        spec["assets"][0]["path"] = "assets/sabermapper/demo-song/post/Grade.mat"
        spec["assets"][1]["id"] = "grade"
        spec["assets"][2]["properties"] = {"_Nope": 1, "_HorizonWidth": 5}
        spec["assets"][3]["properties"]["_Intensity"] = 6
        spec["assets"][5]["children"][0]["material"] = "sky"
        errors, warnings, _ = self.rules(spec)
        for rule in ("path_not_lowercase", "asset_id_duplicate", "property_unknown", "property_out_of_range",
                     "material_reference"):
            self.assertIn(rule, errors)
        self.assertIn("property_outside_safe_range", warnings)

    def test_budgets_tiers_and_targets(self):
        spec = forge.starter_spec("demo-song")
        spec["assets"][5]["children"][0]["mesh"]["params"].update({"segments": 2000, "sides": 64})
        spec["assets"].append({"id": "gen", "kind": "mesh", "tier": 2, "path": "assets/sabermapper/demo-song/meshes/gen.asset",
                               "mesh": {"source": "Ribbon.cs", "class": "SaberMapper.Generated.RibbonMesh"},
                               "provenance": {"author": "agent", "description": "ribbon"}})
        spec["assets"].append({"id": "tex", "kind": "texture", "tier": 3, "path": "assets/sabermapper/demo-song/textures/t.png",
                               "source": "missing.png"})
        spec["target"] = "android2021"
        (self.root / "Ribbon.cs").write_text(RIBBON_CS, encoding="utf-8")
        errors, _, _ = self.rules(spec)
        for rule in ("mesh_budget_exceeded", "mesh_budget_undeclared", "provenance_missing", "texture_source_missing",
                     "target_unsupported"):
            self.assertIn(rule, errors)

    def test_tier3_provenance_hash_is_checked(self):
        from PIL import Image
        Image.new("RGB", (64, 64), (10, 20, 30)).save(self.root / "sky.png")
        spec = forge.starter_spec("demo-song")
        prov = {"generator": {"kind": "skybox", "model": "m", "model_version": "1", "backend": "local", "prompt": "dusk",
                              "seed": 3}, "created_at": "2026-09-23T00:00:00Z", "license": "local", "output_sha256": "0" * 64}
        spec["assets"].append({"id": "tex", "kind": "texture", "tier": 3, "source": "sky.png", "provenance": prov,
                               "path": "assets/sabermapper/demo-song/textures/sky.png"})
        self.assertIn("provenance_hash_mismatch", self.rules(spec)[0])
        import hashlib
        prov["output_sha256"] = hashlib.sha256((self.root / "sky.png").read_bytes()).hexdigest()
        self.assertEqual(set(), self.rules(spec)[0])

    def test_custom_shader_is_linted_in_place(self):
        (self.root / "fx.shader").write_text(GOOD_SHADER.replace("UNITY_SETUP_INSTANCE_ID(v);", ""), encoding="utf-8")
        spec = forge.starter_spec("demo-song")
        spec["assets"][0].update({"tier": 2, "shader": {"source": "fx.shader"}, "properties": {"_Strength": 0.2},
                                  "provenance": {"author": "agent", "description": "custom vignette"}})
        diags, _ = forge.validate_spec(spec, self.root, self.library)
        hit = next(d for d in diags if d["rule"] == "stereo_setup_instance")
        self.assertEqual(str(self.root / "fx.shader"), hit["file"])
        self.assertEqual("grade", hit["asset"])


class UnityLocationTests(ForgeTestCase):
    def fake_editor(self, version):
        exe = self.hub / version / "Editor" / "Unity.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        return exe

    def test_missing_unity_names_the_required_version(self):
        with self.assertRaises(forge.ForgeError) as caught:
            forge.locate_unity()
        error = caught.exception.as_dict()["error"]
        self.assertEqual("unity_missing", error["code"])
        self.assertEqual("2021.3.45f1", error["required_version"])
        self.assertIn("Install Unity 2021.3.45f1 with Unity Hub", error["fix"])
        self.assertIn("activate a Personal license once, then rerun", error["fix"])

    def test_hub_install_exact_and_same_stream_fallback(self):
        patch_exe = self.fake_editor("2021.3.45f2")
        found = forge.locate_unity()
        self.assertEqual(str(patch_exe), found["path"])
        self.assertEqual("unity_version_mismatch", found["warnings"][0]["code"])
        exact = self.fake_editor("2021.3.45f1")
        self.assertEqual({"path": str(exact), "version": "2021.3.45f1", "source": "hub", "warnings": []}, forge.locate_unity())

    def test_env_and_config_override(self):
        exe = self.fake_editor("2021.3.45f1")
        os.environ["SABERMAPPER_UNITY"] = str(self.root / "nope.exe")
        with self.assertRaises(forge.ForgeError):
            forge.locate_unity()
        os.environ.pop("SABERMAPPER_UNITY")
        forge.save_config({"unity_path": str(exe)})
        self.assertEqual("config", forge.locate_unity()["source"])

    def test_cli_build_without_unity_returns_structured_error(self):
        self.spec_file()
        code, payload = run_cli("assets", "build", "Demo-Song", "--workspace", str(self.workspace))
        self.assertEqual(1, code)
        self.assertEqual("unity_missing", payload["error"]["code"])
        self.assertTrue(payload["error"]["fix"].startswith("Install Unity 2021.3.45f1 with Unity Hub"))


class BuildDriverTests(ForgeTestCase):
    def build_cli(self, *extra):
        return run_cli("assets", "build", "Demo-Song", "--workspace", str(self.workspace), "--unity", str(self.stub),
                       "--unity-project", str(self.root / "unity"), *extra)

    def test_successful_build_copies_the_layout_the_show_compiler_reads(self):
        self.spec_file()
        code, result = self.build_cli()
        self.assertEqual(0, code, result)
        assets = self.project / "assets"
        bundle = assets / "bundleWindows2021.vivify"
        self.assertTrue(bundle.is_file())
        info = json.loads((assets / "bundleinfo.json").read_text(encoding="utf-8"))
        self.assertEqual({"_windows2021": 1234567890}, info["bundleCRCs"])
        self.assertEqual([bundle.resolve().as_posix()], info["bundleFiles"])
        self.assertIn("assets/sabermapper/demo-song/prefabs/ring.prefab", info["prefabs"].values())
        self.assertEqual(1234567890, result["crc"])
        self.assertEqual("_windows2021", result["crc_key"])
        # The show compiler's reader accepts the forge output as is.
        from sabermapper.vivify import read_bundle
        bundle_set = read_bundle(assets)
        self.assertEqual(["_windows2021"], bundle_set["shipped"])
        self.assertEqual({"_windows2021": 1234567890}, bundle_set["crcs"])
        self.assertIn("assets/sabermapper/demo-song/prefabs/ring.prefab", bundle_set["prefabs"])
        self.assertTrue(all(m["properties"]["_Strength"]["type"] == "Float" for m in bundle_set["materials"].values()))
        self.assertEqual([str(bundle)], result["bundle_paths"])
        self.assertTrue((assets / "build-report.json").is_file() and (assets / "build.log").is_file())
        self.assertTrue((assets / "builds" / result["build_id"] / "build-report.json").is_file())
        credits = json.loads((assets / "credits.json").read_text(encoding="utf-8"))
        self.assertEqual("sabermapper-credits/1", credits["format"])
        self.assertEqual(credits["attribution_text"], result["credits"]["attribution_text"])
        self.assertTrue((assets / "builds" / result["build_id"] / "credits.json").is_file())
        argv = json.loads((self.root / "argv.json").read_text())
        for flag in ("-batchmode", "-quit", "-nographics", "-projectPath"):
            self.assertIn(flag, argv)
        self.assertEqual("SaberMapper.Forge.Build", argv[argv.index("-executeMethod") + 1])
        self.assertEqual("windows2021", argv[argv.index("-forgeTarget") + 1])
        staged = json.loads(Path(argv[argv.index("-forgeSpec") + 1]).read_text(encoding="utf-8"))
        ids = [a["id"] for a in staged["assets"]]
        self.assertLess(ids.index("ring__ring"), ids.index("ring"))
        ring = next(a for a in staged["assets"] if a["id"] == "ring")
        self.assertEqual({"asset": "ring__ring"}, ring["children"][0]["mesh"])
        grade = next(a for a in staged["assets"] if a["id"] == "grade")
        self.assertEqual("Assets/SaberMapper/demo-song/post/grade.mat", grade["unity_path"])
        self.assertTrue((self.root / "unity" / grade["shader_unity_path"]).is_file())
        self.assertTrue((self.root / "unity" / "Assets/SaberMapper/Editor/Forge.cs").is_file())
        self.assertIn("2021.3.45f1", (self.root / "unity/ProjectSettings/ProjectVersion.txt").read_text())

    def test_csharp_errors_map_back_to_the_agent_generator(self):
        spec = forge.starter_spec("demo-song")
        spec["assets"].append({"id": "ribbon", "kind": "mesh", "tier": 2, "path": "assets/sabermapper/demo-song/meshes/ribbon.asset",
                               "mesh": {"source": "generators/Ribbon.cs", "class": "SaberMapper.Generated.RibbonMesh",
                                        "max_triangles": 100},
                               "provenance": {"author": "agent", "description": "ribbon strip"}})
        path = self.spec_file(spec)
        (path.parent / "generators").mkdir()
        (path.parent / "generators" / "Ribbon.cs").write_text(RIBBON_CS, encoding="utf-8")
        os.environ["FORGE_STUB_MODE"] = "cs_error"
        code, result = self.build_cli()
        self.assertEqual(1, code)
        self.assertEqual("unity_build_failed", result["error"]["code"])
        cs = next(e for e in result["error"]["errors"] if e["source"] == "csharp")
        self.assertEqual(str((path.parent / "generators" / "Ribbon.cs").resolve()), cs["file"])
        self.assertEqual((12, "CS1002"), (cs["line"], cs["code"]))
        self.assertIn("forge_method_missing", {e["code"] for e in result["error"]["errors"]})
        self.assertTrue(Path(result["error"]["log"]).is_file())
        self.assertFalse((self.project / "assets" / "bundleWindows2021.vivify").exists())

    def test_shader_license_and_crc_failures(self):
        self.spec_file()
        os.environ["FORGE_STUB_MODE"] = "shader_error"
        code, result = self.build_cli()
        shader = next(e for e in result["error"]["errors"] if e["source"] == "shader")
        self.assertEqual(str(forge.library_shader_path(self.library, "sm_vignette")), shader["file"])
        self.assertEqual(58, shader["line"])
        os.environ["FORGE_STUB_MODE"] = "license"
        code, result = self.build_cli()
        self.assertIn("unity_license_missing", {e["code"] for e in result["error"]["errors"]})
        # 2021.3.16f1 with a valid Hub Personal seat: name the editor that works headless, not "add a license".
        os.environ["FORGE_STUB_MODE"] = "headless_license"
        code, result = self.build_cli()
        codes = {e["code"] for e in result["error"]["errors"]}
        self.assertEqual({"unity_headless_license_unsupported"}, codes)
        self.assertIn("assets config --unity-version 2021.3.45f1", result["error"]["errors"][0]["fix"])
        os.environ["FORGE_STUB_MODE"] = "crc_mismatch"
        code, result = self.build_cli()
        self.assertEqual("crc_mismatch", result["error"]["code"])
        self.assertFalse((self.project / "assets" / "bundleinfo.json").exists())

    def test_lint_errors_block_the_build_before_unity(self):
        spec = forge.starter_spec("demo-song")
        spec["assets"][0]["path"] = "assets/sabermapper/demo-song/post/UPPER.mat"
        self.spec_file(spec)
        code, result = self.build_cli()
        self.assertEqual("lint_failed", result["error"]["code"])
        hit = next(d for d in result["error"]["diagnostics"] if d["rule"] == "path_not_lowercase")
        spec_lines = (self.project / "assets/assets.json").read_text(encoding="utf-8").splitlines()
        self.assertIn('"id": "grade"', spec_lines[hit["line"] - 1])
        self.assertFalse((self.root / "argv.json").exists())

    def test_spec_mode_and_project_mismatch(self):
        spec_path = self.spec_file(forge.starter_spec("other-song"))
        code, result = run_cli("assets", "lint", "Demo-Song", "--workspace", str(self.workspace))
        self.assertEqual(1, code)
        self.assertEqual("project_mismatch", result["diagnostics"][0]["rule"])
        out = self.root / "out"
        code, result = run_cli("assets", "build", "--spec", str(spec_path), "--out", str(out), "--unity", str(self.stub),
                               "--unity-project", str(self.root / "unity"))
        self.assertEqual(0, code, result)
        self.assertTrue((out / "bundleWindows2021.vivify").is_file())

    def test_log_parser_formats(self):
        log = "\n".join([
            "Assets/SaberMapper/Editor/Forge.cs(40,13): error CS0103: The name 'foo' does not exist in the current context",
            "Shader error in 'SaberMapper/Sky/Nebula': syntax error: unexpected token '}' at Assets/SaberMapper/x/inc.cginc(7) (on d3d11)",
            "Shader warning in 'SaberMapper/Sky/Nebula': implicit truncation at line 12 (on d3d11)",
            '[SaberMapperForge] {"code": "mesh_budget_exceeded", "message": "too many", "asset": "ring"}',
            "It looks like another Unity instance is running with this project open."])
        issues = forge.parse_unity_log(log, {"files": {"assets/sabermapper/x/inc.cginc": "C:/src/inc.cginc"}, "shaders": {}})
        by_code = {i["code"]: i for i in issues}
        self.assertTrue(by_code["CS0103"]["file"].endswith("Forge.cs"))
        self.assertEqual(40, by_code["CS0103"]["line"])
        errors = [i for i in issues if i["code"] == "shader_compile_error" and i["severity"] == "error"]
        self.assertEqual(("C:/src/inc.cginc", 7, "d3d11"), (errors[0]["file"], errors[0]["line"], errors[0]["api"]))
        self.assertEqual("ring", by_code["mesh_budget_exceeded"]["asset"])
        self.assertIn("unity_project_locked", by_code)


class InitPromoteGenerateTests(ForgeTestCase):
    def test_init_writes_a_clean_starter_and_refuses_to_overwrite(self):
        code, result = run_cli("assets", "init", "Demo-Song", "--workspace", str(self.workspace))
        self.assertEqual(0, code)
        self.assertTrue(result["ok"])
        self.assertEqual("demo-song", json.loads((self.project / "assets/assets.json").read_text())["project"])
        code, result = run_cli("assets", "init", "Demo-Song", "--workspace", str(self.workspace))
        self.assertEqual("spec_exists", result["error"]["code"])
        code, result = run_cli("assets", "lint", "Demo-Song", "--workspace", str(self.workspace))
        self.assertEqual(0, code)

    def test_promote_requires_a_complete_library_entry(self):
        library = self.root / "library"
        shutil.copytree(forge.LIBRARY_DIR, library)
        spec = forge.starter_spec("demo-song")
        spec["assets"][0].update({"tier": 2, "shader": {"source": "shaders/fx.shader"}, "properties": {},
                                  "provenance": {"author": "agent", "description": "soft vignette"}})
        path = self.spec_file(spec)
        (path.parent / "shaders").mkdir()
        (path.parent / "shaders" / "fx.shader").write_text(GOOD_SHADER.replace("SaberMapper/Post/Vignette", "SaberMapper/Post/Fx"),
                                                          encoding="utf-8")
        argv = ("assets", "promote", "Demo-Song", "grade", "--workspace", str(self.workspace), "--library", str(library))
        code, result = run_cli(*argv)
        self.assertEqual("library_entry_incomplete", result["error"]["code"])
        self.assertIn("intent", result["error"]["missing"])
        self.assertIn("properties._Strength.safe", result["error"]["missing"])
        stub = result["error"]["stub"]
        self.assertEqual({"_Strength", "_Radius", "_Softness", "_Color"}, set(stub["properties"]))
        stub.update({"intent": "Soft focus", "description": "Edges fade to a colour"})
        for name, entry in stub["properties"].items():
            entry["meaning"] = f"meaning of {name}"
        spec["assets"][0]["library"] = stub
        path.write_text(json.dumps(spec), encoding="utf-8")
        code, result = run_cli(*argv)
        self.assertEqual(0, code, result)
        self.assertEqual("sm_grade", result["promoted"])
        promoted = forge.load_library(library)
        self.assertIn("sm_grade", promoted["shaders"])
        self.assertIn("sm_grade", (library / "library.md").read_text(encoding="utf-8"))
        self.assertTrue((library / "shaders" / "sm_grade.shader").is_file())
        code, result = run_cli(*argv)
        self.assertEqual("library_id_taken", result["error"]["code"])

    def test_generate_reports_generator_unavailable_with_provenance_template(self):
        code, result = run_cli("assets", "generate", "Demo-Song", "--workspace", str(self.workspace), "--kind", "skybox",
                               "--prompt", "violet dusk over a glass sea", "--seed", "7")
        self.assertEqual(1, code)
        self.assertEqual("generator_unavailable", result["error"]["code"])
        self.assertEqual(7, result["error"]["provenance_template"]["generator"]["seed"])
        self.assertEqual("local", result["error"]["backend"])


if __name__ == "__main__":
    unittest.main()
