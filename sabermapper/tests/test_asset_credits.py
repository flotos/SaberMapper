"""Credits for fetched and generated media: grouping per source work, attribution text, and the command."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from sabermapper.asset_credits import credits_for_spec
from sabermapper.__main__ import main


def fetched(aid, source, asset, name, authors, model=None, kind="mesh"):
    record = {"source": source, "asset": asset, "name": name, "url": f"https://example.org/{asset}",
              "files": [f"https://example.org/{asset}.zip"], "authors": authors, "retrieved_at": "2026-09-23T00:00:00Z"}
    if model:
        record["model"] = model
    body = {"mesh": {"file": f"models/{aid}.obj"}} if kind == "mesh" else {"source": f"textures/{aid}.jpg"}
    return {"id": aid, "kind": kind, "tier": 3, **body,
            "provenance": {"fetched": record, "license": "CC0-1.0", "output_sha256": "0" * 64,
                           "postprocess": [{"op": "normalise", "origin": "base", "height_m": 7}]}}


SPEC = {"format": "sabermapper-assets/1", "project": "demo", "assets": [
    fetched("pine", "kenney", "nature-kit", "Nature Kit", ["Kenney"], model="tree_pineTallA"),
    fetched("cliff", "kenney", "nature-kit", "Nature Kit", ["Kenney"], model="cliff_block_rock"),
    fetched("rock", "polyhaven", "rock_moss_set_01", "Rock Moss Set 01", ["Kless Gyzen"]),
    fetched("sky", "polyhaven", "kloppenheim_06_puresky", "Kloppenheim 06 (Pure Sky)", ["Greg Zaal"], kind="texture"),
    {"id": "clouds", "kind": "texture", "tier": 3, "source": "textures/clouds.png",
     "provenance": {"generator": {"kind": "skybox", "model": "FLUX.1-schnell", "model_version": "1", "backend": "local",
                                  "prompt": "clouds", "seed": 7},
                    "license": "Apache-2.0", "created_at": "2026-09-23T00:00:00Z", "output_sha256": "0" * 64}},
    {"id": "grade", "kind": "post_process", "tier": 1, "shader": {"library": "sm_color_grade"}},
    {"id": "own", "kind": "material", "tier": 2, "shader": {"source": "shaders/x.shader"},
     "provenance": {"author": "agent", "description": "per-map shader"}},
]}


class CreditsTests(unittest.TestCase):
    def test_works_are_grouped_and_own_assets_left_out(self):
        credits = credits_for_spec(SPEC)
        titles = [w["title"] for w in credits["third_party"]]
        self.assertEqual(["Nature Kit", "Rock Moss Set 01", "Kloppenheim 06 (Pure Sky)"], titles)
        kenney = credits["third_party"][0]
        self.assertEqual(["pine", "cliff"], [u["asset_id"] for u in kenney["used_as"]])
        self.assertEqual(["tree_pineTallA", "cliff_block_rock"], [u["model"] for u in kenney["used_as"]])
        self.assertEqual(("Kenney", "https://kenney.nl"), (kenney["source_name"], kenney["source_url"]))
        self.assertEqual("https://creativecommons.org/publicdomain/zero/1.0/", kenney["license_url"])
        self.assertEqual([{"op": "normalise", "origin": "base", "height_m": 7}], kenney["used_as"][0]["modifications"])
        self.assertEqual(["clouds"], [g["asset_id"] for g in credits["generated_media"]])
        self.assertEqual(["Apache-2.0", "CC0-1.0"], credits["licenses"])
        listed = json.dumps(credits)
        self.assertNotIn('"grade"', listed)
        self.assertNotIn('"own"', listed)

    def test_attribution_text_names_every_work_author_and_source(self):
        text = credits_for_spec(SPEC)["attribution_text"]
        self.assertIn('"Nature Kit" (cliff_block_rock, tree_pineTallA), Kenney, https://example.org/nature-kit (CC0)', text)
        self.assertIn('"Rock Moss Set 01" by Kless Gyzen, Poly Haven', text)
        self.assertIn("Generated media made with FLUX.1-schnell 1.", text)
        own_only = credits_for_spec({"project": "demo", "assets": [SPEC["assets"][5]]})
        self.assertEqual("All visual assets were made for this map with SaberMapper.", own_only["attribution_text"])

    def test_cli_prints_and_writes_credits(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = Path(tmp) / "assets.json"
            spec.write_text(json.dumps(SPEC), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["assets", "credits", "--spec", str(spec), "--write"])
            self.assertEqual(0, code)
            printed = json.loads(out.getvalue())
            self.assertEqual(3, len(printed["third_party"]))
            self.assertTrue((Path(tmp) / "credits.json").is_file())
            self.assertIn("spec_sha256", printed)


if __name__ == "__main__":
    unittest.main()
