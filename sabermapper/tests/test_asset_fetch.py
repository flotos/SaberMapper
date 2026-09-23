"""Fetched media: model files (glTF/GLB/OBJ in, normalised OBJ out), forge lint and staging of model files, and the
`assets fetch` search/info/get flow against fixture responses (no network)."""
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

from sabermapper import asset_fetch, forge, mesh_files


def make_glb(positions, indices, color=(1, 1, 1, 1), translation=(0, 0, 0), name="thing") -> bytes:
    """A one-node, one-primitive GLB with a material base colour."""
    pos = np.asarray(positions, dtype="<f4").tobytes()
    idx = np.asarray(indices, dtype="<u2").tobytes()
    pad = (4 - len(idx) % 4) % 4
    binary = pos + idx + b"\x00" * pad
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [{"name": name, "mesh": 0, "translation": list(translation)}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
           "materials": [{"pbrMetallicRoughness": {"baseColorFactor": list(color)}}],
           "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                           {"buffer": 0, "byteOffset": len(pos), "byteLength": len(idx)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(positions), "type": "VEC3"},
                         {"bufferView": 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"}]}
    text = json.dumps(doc).encode()
    text += b" " * ((4 - len(text) % 4) % 4)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def grid_mesh(n=30):
    """An n x n bumpy height field: 2 n^2 triangles."""
    xs, zs = np.meshgrid(np.linspace(0, 1, n + 1), np.linspace(0, 1, n + 1))
    ys = 0.1 * np.sin(xs * 9) * np.cos(zs * 7)
    positions = np.c_[xs.ravel(), ys.ravel(), zs.ravel()]
    tris = []
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            tris += [[a, a + n + 1, a + 1], [a + 1, a + n + 1, a + n + 2]]
    return {"positions": positions, "uvs": None, "colors": np.tile([0.5, 0.2, 0.1, 1.0], (len(positions), 1)),
            "triangles": np.array(tris), "parts": ["grid"]}


TRIANGLE = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]


class MeshFileTests(unittest.TestCase):
    def test_glb_merges_nodes_with_transforms_and_material_colour(self):
        doc, embedded = mesh_files.parse_glb(make_glb(TRIANGLE, [0, 1, 2], color=(0.5, 0.25, 1, 1), translation=(0, 2, 0)))
        mesh, warnings = mesh_files.load_gltf(doc, mesh_files.gltf_buffers(doc, embedded, None))
        self.assertEqual([], warnings)
        self.assertEqual(1, mesh_files.triangle_count(mesh))
        self.assertEqual([0, 2, 0], mesh["positions"][0].tolist())
        np.testing.assert_allclose(mesh["colors"][0], [0.5, 0.25, 1, 1])
        with self.assertRaises(mesh_files.MeshFileError) as caught:
            mesh_files.load_gltf(doc, mesh_files.gltf_buffers(doc, embedded, None), ["missing"])
        self.assertEqual("model_node_unknown", caught.exception.code)

    def test_srgb_authored_factors_become_linear(self):
        doc, embedded = mesh_files.parse_glb(make_glb(TRIANGLE, [0, 1, 2], color=(0.5, 0.5, 0.5, 1)))
        mesh, _ = mesh_files.load_gltf(doc, mesh_files.gltf_buffers(doc, embedded, None), srgb_factors=True)
        self.assertAlmostEqual(0.2140, mesh["colors"][0][0], places=3)

    def test_compressed_gltf_is_refused_with_a_fix(self):
        doc = {"extensionsRequired": ["KHR_draco_mesh_compression"]}
        with self.assertRaises(mesh_files.MeshFileError) as caught:
            mesh_files.load_gltf(doc, {})
        self.assertEqual("gltf_compressed", caught.exception.code)

    def test_obj_round_trip_keeps_colours_and_fans_polygons(self):
        with tempfile.TemporaryDirectory() as tmp:
            quad = "v 0 0 0 1 0 0\nv 1 0 0 1 0 0\nv 1 1 0 1 0 0\nv 0 1 0 1 0 0\nf 1 2 3 4\n"
            mesh = mesh_files.read_obj(quad)
            self.assertEqual(2, mesh_files.triangle_count(mesh))
            path = Path(tmp) / "quad.obj"
            mesh_files.write_obj(mesh, path, ["test"])
            self.assertEqual(2, mesh_files.obj_triangle_count(path))
            back = mesh_files.load_model_file(path)
            np.testing.assert_allclose(back["colors"][:, :3], [[1, 0, 0]] * 4)

    def test_mtl_diffuse_colours_are_srgb(self):
        mesh = mesh_files.read_obj("usemtl leaf\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", {"leaf": [0.5, 0.5, 0.5]})
        self.assertAlmostEqual(0.2140, mesh["colors"][0][0], places=3)

    def test_decimate_meets_the_budget_and_records_the_step(self):
        mesh = grid_mesh(30)
        smaller, step = mesh_files.decimate(mesh, 400)
        self.assertLessEqual(mesh_files.triangle_count(smaller), 400)
        self.assertGreater(mesh_files.triangle_count(smaller), 100)
        self.assertEqual({"op", "method", "grid_cells", "triangles_before", "triangles_after"}, set(step))
        self.assertEqual((len(smaller["positions"]), 4), smaller["colors"].shape)
        same, none = mesh_files.decimate(mesh, 10_000)
        self.assertIs(mesh, same)
        self.assertIsNone(none)

    def test_normalise_puts_the_base_at_the_origin_and_scales_height(self):
        mesh = {"positions": np.array([[1.0, 2, 3], [3, 6, 5], [1, 2, 5]]), "triangles": np.array([[0, 1, 2]])}
        out = mesh_files.normalise(mesh, origin="base", height=2.0)
        # 2 m wide and 4 m tall, scaled uniformly to 2 m tall: half as wide.
        self.assertEqual({"min": [-0.5, 0.0, -0.5], "max": [0.5, 2.0, 0.5], "size": [1.0, 2.0, 1.0]},
                         mesh_files.bounds(out))

    def test_unity_data_mirrors_x_and_reverses_winding(self):
        data = mesh_files.unity_mesh_data({"positions": np.array(TRIANGLE, dtype=float), "triangles": np.array([[0, 1, 2]]),
                                           "uvs": None, "colors": None})
        self.assertEqual([-0.0, 0.0, 0.0, -1.0, 0.0, 0.0, -0.0, 1.0, 0.0], data["vertices"])
        self.assertEqual([0, 2, 1], data["triangles"])


class ForgeModelFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "models").mkdir()
        mesh_files.write_obj(grid_mesh(4), self.root / "models" / "rock.obj")
        self.sha = forge.hashlib.sha256((self.root / "models" / "rock.obj").read_bytes()).hexdigest()

    def tearDown(self):
        self._tmp.cleanup()

    def spec(self, **mesh_asset):
        asset = {"id": "rock", "kind": "mesh", "tier": 3, "path": "assets/sabermapper/demo/meshes/rock.asset",
                 "mesh": {"file": "models/rock.obj"},
                 "provenance": {"fetched": {"source": "polyhaven", "asset": "rock", "url": "https://polyhaven.com/a/rock",
                                            "authors": ["Someone"], "retrieved_at": "2026-09-23T00:00:00Z"},
                                "license": "CC0-1.0", "output_sha256": self.sha}}
        asset.update(mesh_asset)
        material = {"id": "stone", "kind": "material", "tier": 1, "path": "assets/sabermapper/demo/materials/stone.mat",
                    "shader": {"library": "sm_unlit_emissive"}}
        prefab = {"id": "pile", "kind": "prefab", "tier": 1, "path": "assets/sabermapper/demo/prefabs/pile.prefab",
                  "children": [{"name": "a", "mesh": {"asset": "rock"}, "material": "stone"}]}
        return {"format": "sabermapper-assets/1", "project": "demo", "assets": [asset, material, prefab]}

    def rules(self, spec):
        diags, summary = forge.validate_spec(spec, self.root)
        return {d["rule"] for d in diags if d["severity"] == "error"}, summary

    def test_fetched_model_lints_and_counts_triangles_in_prefabs(self):
        rules, summary = self.rules(self.spec())
        self.assertEqual(set(), rules)
        self.assertEqual(32, summary["triangles"])

    def test_model_file_problems_are_reported(self):
        self.assertIn("mesh_file_missing", self.rules(self.spec(mesh={"file": "models/none.obj"}))[0])
        self.assertIn("mesh_file_format", self.rules(self.spec(mesh={"file": "models/rock.glb"}))[0])
        self.assertIn("tier_mismatch", self.rules(self.spec(tier=1))[0])
        budget = self.spec()
        budget["budgets"] = {"max_triangles_per_mesh": 10}
        self.assertIn("mesh_budget_exceeded", self.rules(budget)[0])
        inline = self.spec()
        inline["assets"][2]["children"][0]["mesh"] = {"file": "models/rock.obj"}
        self.assertIn("mesh_file_inline", self.rules(inline)[0])

    def test_fetched_provenance_is_checked_against_the_file(self):
        missing = self.spec()
        del missing["assets"][0]["provenance"]["fetched"]["authors"]
        self.assertIn("provenance_incomplete", self.rules(missing)[0])
        (self.root / "models" / "rock.obj").write_text("# edited\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        self.assertIn("provenance_hash_mismatch", self.rules(self.spec())[0])

    def test_staging_writes_unity_space_mesh_data(self):
        project = self.root / "unity"
        staged, source_map = forge.stage(self.spec(), self.root, project, forge.load_library(), "windows2021")
        entry = next(a for a in staged["assets"] if a["id"] == "rock")
        rel = entry["mesh"]["data_unity_path"]
        data = json.loads((project / rel).read_text(encoding="utf-8"))
        self.assertEqual(32 * 3, len(data["triangles"]))
        self.assertEqual(len(data["vertices"]) // 3 * 4, len(data["colors"]))
        self.assertIn(rel.lower(), source_map["files"])


def fixture_http(routes):
    def get(url, max_bytes):
        asset_fetch._check_url(url)
        for prefix, body in routes.items():
            if url.startswith(prefix):
                return body() if callable(body) else body
        raise asset_fetch.FetchError("fetch_network", f"no fixture for {url}")
    return get


def jpeg(size) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (40, 80, 160)).save(out, format="JPEG")
    return out.getvalue()


class FetchFlowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        (self.project / "assets").mkdir(parents=True)
        pos = np.asarray(TRIANGLE, dtype="<f4").tobytes() + np.asarray([0, 1, 2], dtype="<u2").tobytes() + b"\x00\x00"
        gltf = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}],
                "nodes": [{"name": "rock_a", "mesh": 0}, {"name": "rock_b", "mesh": 0, "translation": [3, 0, 0]}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
                "buffers": [{"uri": "rock.bin", "byteLength": len(pos)}],
                "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 36}, {"buffer": 0, "byteOffset": 36, "byteLength": 6}],
                "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
                              {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}]}
        pack = io.BytesIO()
        with zipfile.ZipFile(pack, "w") as z:
            z.writestr("License.txt", "License: (Creative Commons Zero, CC0)")
            z.writestr("Models/GLTF format/statue.glb", make_glb(TRIANGLE, [0, 1, 2], color=(0.5, 0.5, 0.5, 1)))
            z.writestr("Previews/statue.png", b"png")
            z.writestr("Models/GLTF format/tree_pineTallA.glb", make_glb(TRIANGLE, [0, 1, 2]))
        sky = io.BytesIO()
        with zipfile.ZipFile(sky, "w") as z:
            z.writestr("Dusk_2K_TONEMAPPED.jpg", jpeg((256, 128)))
        self.routes = {
            "https://api.polyhaven.com/assets?t=models": json.dumps({"rock_set": {
                "name": "Rock Set", "tags": ["rock"], "categories": ["nature"], "authors": {"Ann": "All"},
                "polycount": 3, "dimensions": [2000, 1000, 500]}}).encode(),
            "https://api.polyhaven.com/info/rock_set": json.dumps({"name": "Rock Set", "type": 2, "authors": {"Ann": "All"}}).encode(),
            "https://api.polyhaven.com/files/rock_set": json.dumps({"gltf": {"1k": {"gltf": {
                "url": "https://dl.polyhaven.org/rock_set_1k.gltf",
                "include": {"rock.bin": {"url": "https://dl.polyhaven.org/rock.bin"}}}}}}).encode(),
            "https://dl.polyhaven.org/rock_set_1k.gltf": json.dumps(gltf).encode(),
            "https://dl.polyhaven.org/rock.bin": pos,
            "https://cdn.polyhaven.com/": b"png",
            "https://kenney.nl/assets/statues": b"<a href='https://kenney.nl/media/pages/assets/statues/1/kenney_statues.zip'>",
            "https://kenney.nl/media/pages/assets/statues/1/kenney_statues.zip": pack.getvalue(),
            "https://kenney.nl/feed": b"<rss><channel></channel></rss>",
            "https://ambientcg.com/get?file=Dusk_2K.zip": sky.getvalue(),
        }
        self.patches = [patch.object(asset_fetch, "HTTP", fixture_http(self.routes)),
                        patch.dict(os.environ, {"SABERMAPPER_FETCH_CACHE": str(self.root / "cache")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()

    def test_allowlist_refuses_other_hosts(self):
        with self.assertRaises(asset_fetch.FetchError) as caught:
            asset_fetch._check_url("https://example.com/model.glb")
        self.assertEqual("fetch_host_not_allowed", caught.exception.code)
        with self.assertRaises(asset_fetch.FetchError):
            asset_fetch._check_url("http://dl.polyhaven.org/plain-http.glb")

    def test_search_marks_budget_and_suggests_the_next_step(self):
        result = asset_fetch.search("rock", sources=["polyhaven"])
        self.assertEqual("polyhaven:rock_set", result["results"][0]["ref"])
        self.assertTrue(result["results"][0]["fits_budget"])
        self.assertEqual([2.0, 1.0, 0.5], result["results"][0]["dimensions_m"])
        self.assertIn("assets fetch info", result["next"])

    def test_polyhaven_model_becomes_a_linted_tier3_mesh(self):
        info = asset_fetch.info("polyhaven:rock_set")
        self.assertEqual(["rock_a", "rock_b"], sorted(n["node"] for n in info["nodes"]))
        result = asset_fetch.get("polyhaven:rock_set", self.project, "demo", nodes=["rock_b"], height=2.0, add=True)
        entry = result["assets"][0]
        self.assertEqual(("mesh", 3, "models/rock_b.obj"), (entry["kind"], entry["tier"], entry["mesh"]["file"]))
        self.assertEqual(["Ann"], entry["provenance"]["fetched"]["authors"])
        self.assertEqual("Rock Set", entry["provenance"]["fetched"]["name"])
        self.assertEqual(2.0, result["summary"]["bounds_m"]["size"][1])
        spec = json.loads((self.project / "assets" / "assets.json").read_text(encoding="utf-8"))
        diags, _ = forge.validate_spec(spec, self.project / "assets")
        self.assertEqual([], [d for d in diags if d["severity"] == "error"])
        with self.assertRaises(asset_fetch.FetchError) as caught:
            asset_fetch.get("polyhaven:rock_set", self.project, "demo", nodes=["rock_b"], add=True)
        self.assertEqual("fetch_exists", caught.exception.code)

    def test_kenney_pack_needs_a_model_and_converts_srgb_colours(self):
        with self.assertRaises(asset_fetch.FetchError) as caught:
            asset_fetch.get("kenney:statues", self.project, "demo")
        self.assertEqual("fetch_model_required", caught.exception.code)
        info = asset_fetch.info("kenney:statues")
        self.assertEqual(("statue", "CC0-1.0"), (info["models"][0]["model"], info["license"]))
        self.assertTrue(info["models"][0]["preview"])
        result = asset_fetch.get("kenney:statues", self.project, "demo", model="statue")
        self.assertIn("face the player", result["next"])
        self.assertEqual("statue", result["assets"][0]["provenance"]["fetched"]["model"])
        mesh = mesh_files.load_model_file(self.project / "assets" / "models" / "statue.obj")
        self.assertAlmostEqual(0.214, mesh["colors"][0][0], places=3)

    def test_cached_kenney_packs_are_searched_by_model_name(self):
        self.assertFalse([r for r in asset_fetch.search("statue", sources=["kenney"])["results"] if r.get("model")])
        with patch.dict(asset_fetch.KENNEY_3D, {"statues": "sculpture"}):
            asset_fetch.info("kenney:statues")
            found = asset_fetch.search("statue", sources=["kenney"])["results"]
        self.assertEqual(("kenney:statues", "statue"), (found[0]["ref"], found[0]["model"]))
        self.assertIn("--model statue", found[0]["next"])
        with patch.dict(asset_fetch.KENNEY_3D, {"statues": "sculpture"}):
            pines = asset_fetch.search("pine", sources=["kenney"])["results"]
        self.assertEqual("tree_pineTallA", pines[0]["model"])

    def test_ambientcg_sky_is_resized_into_a_texture_asset(self):
        result = asset_fetch.get("ambientcg:Dusk", self.project, "demo", kind="sky", max_size=128, add=True)
        entry = result["assets"][0]
        self.assertEqual(("texture", "textures/dusk.jpg", "clamp"), (entry["kind"], entry["source"], entry["texture"]["wrap"]))
        with Image.open(self.project / "assets" / "textures" / "dusk.jpg") as image:
            self.assertEqual((128, 64), image.size)
        self.assertEqual("resize", entry["provenance"]["postprocess"][0]["op"])
        self.assertIn("sm_sky_panorama", result["next"])

    def test_bad_refs_are_explained(self):
        with self.assertRaises(asset_fetch.FetchError) as caught:
            asset_fetch.parse_ref("sketchfab:abc")
        self.assertEqual("fetch_ref_invalid", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
