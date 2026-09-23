import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.projects import ProjectStore
from sabermapper.storage import read_json
from sabermapper.workspace_clone import CloneError, clone, main_workspace, merge_metadata, publish, status


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class WorkspaceCloneTests(unittest.TestCase):
    """A worktree maps against its own clone and publishes only the files it changed."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.real, self.local = base / "main" / "workspace", base / "worktree" / "workspace"
        for project in ("aaa", "bbb"):
            root = self.real / "projects" / project
            write(root / "project.json", json.dumps({"id": project}))
            write(root / "arrangement.json", '{"revision": 1}')
            write(root / "history" / "r1.json", '{"revision": 1}')
            write(root / "song.ogg", "audio bytes")
            write(root / "musical" / "run1" / "drums.wav", "stem bytes")
            write(root / "musical" / "run1" / "report.json", "{}")
            write(root / "exports" / "map-1.zip", "zip")
        write(self.real / "corpus" / "tier-reference.json", "{}")
        write(self.real / "corpus" / "manifest.sqlite", "db")
        write(self.real / "corpus" / "archives" / ("a" * 64 + ".zip"), "archive")
        write(self.real / "player-profile.json", "{}")
        write(self.real / "tidal" / "auth.json", "secret")
        write(self.real / ".project.lock", "\0")

    def tearDown(self):
        self.temp.cleanup()

    def test_clone_links_write_once_files_and_copies_the_rest(self):
        result = clone(self.local, self.real)
        self.assertEqual(result["projects"], ["projects/aaa", "projects/bbb"])
        project = self.local / "projects" / "aaa"
        self.assertTrue(os.path.samefile(project / "song.ogg", self.real / "projects/aaa/song.ogg"))
        self.assertTrue(os.path.samefile(project / "musical/run1/drums.wav", self.real / "projects/aaa/musical/run1/drums.wav"))
        archive = "corpus/archives/" + "a" * 64 + ".zip"
        self.assertTrue(os.path.samefile(self.local / archive, self.real / archive))
        for copied in ("projects/aaa/arrangement.json", "projects/aaa/musical/run1/report.json", "corpus/manifest.sqlite"):
            self.assertFalse(os.path.samefile(self.local / copied, self.real / copied), copied)
        self.assertFalse((project / "exports").exists())
        self.assertFalse((self.local / "tidal").exists())
        self.assertFalse((self.local / ".project.lock").exists())
        # A store on the clone finds the projects without touching the real workspace's lock.
        self.assertEqual(ProjectStore(self.local).directory("aaa"), project.resolve())

    def test_clone_refuses_the_real_workspace_and_a_second_clone(self):
        with self.assertRaises(CloneError) as caught:
            clone(self.real, self.real)
        self.assertEqual(caught.exception.code, "clone_is_source")
        clone(self.local, self.real)
        with self.assertRaises(CloneError) as caught:
            clone(self.local, self.real)
        self.assertEqual(caught.exception.code, "clone_exists")

    def test_publish_copies_only_changed_files(self):
        clone(self.local, self.real)
        untouched = self.real / "projects/bbb/arrangement.json"
        before = untouched.stat().st_mtime_ns
        write(self.local / "projects/aaa/arrangement.json", '{"revision": 2, "notes": []}')
        write(self.local / "projects/aaa/history/r2.json", '{"revision": 2, "notes": []}')
        write(self.local / "projects/aaa/musical/run2/drums.wav", "new stem")
        (self.local / "projects/aaa/history/r1.json").unlink()
        self.assertEqual(status(self.local)["publishable"], ["projects/aaa"])

        preview = publish(self.local, dry_run=True)
        self.assertEqual(preview["published"], [{"unit": "projects/aaa", "files": 4}])
        self.assertEqual((self.real / "projects/aaa/arrangement.json").read_text(), '{"revision": 1}')

        result = publish(self.local)
        self.assertEqual(result["applied"], {"added": 2, "updated": 1, "deleted": 1})
        self.assertEqual((self.real / "projects/aaa/arrangement.json").read_text(), '{"revision": 2, "notes": []}')
        self.assertTrue((self.real / "projects/aaa/musical/run2/drums.wav").exists())
        self.assertFalse((self.real / "projects/aaa/history/r1.json").exists())
        self.assertEqual(untouched.stat().st_mtime_ns, before)
        self.assertTrue((self.real / "projects/aaa/exports/map-1.zip").exists())
        # Publishing again finds nothing left to copy.
        self.assertEqual(publish(self.local)["published"], [])
        self.assertEqual(status(self.local)["publishable"], [])

    def test_a_file_changed_on_both_sides_holds_its_project_back(self):
        clone(self.local, self.real)
        write(self.local / "projects/aaa/arrangement.json", '{"revision": "local"}')
        write(self.local / "projects/aaa/history/local.json", "{}")
        write(self.real / "projects/aaa/arrangement.json", '{"revision": "studio save"}')
        write(self.local / "projects/bbb/arrangement.json", '{"revision": "bbb local"}')
        report = status(self.local)
        self.assertEqual(report["conflicted"], ["projects/aaa"])
        self.assertEqual(report["publishable"], ["projects/bbb"])

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["workspace", "publish", "--workspace", str(self.local)])
        result = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual([h["unit"] for h in result["held_back"]], ["projects/aaa"])
        self.assertIn("project save aaa", result["held_back"][0]["fix"])
        # The held-back project is untouched, including its new files; the other project is published.
        self.assertEqual((self.real / "projects/aaa/arrangement.json").read_text(), '{"revision": "studio save"}')
        self.assertFalse((self.real / "projects/aaa/history/local.json").exists())
        self.assertEqual((self.real / "projects/bbb/arrangement.json").read_text(), '{"revision": "bbb local"}')

    def test_real_workspace_changes_to_other_files_do_not_block(self):
        clone(self.local, self.real)
        write(self.real / "projects/aaa/project.json", '{"id": "aaa", "album": "set in the studio"}')
        write(self.local / "projects/aaa/arrangement.json", '{"revision": "local edit"}')
        row = next(u for u in status(self.local)["units"] if u["unit"] == "projects/aaa")
        self.assertTrue(row["real_workspace_changed"])
        self.assertEqual(row["conflicts"], [])
        publish(self.local, units=["aaa"])
        self.assertEqual((self.real / "projects/aaa/project.json").read_text(), '{"id": "aaa", "album": "set in the studio"}')
        self.assertEqual((self.real / "projects/aaa/arrangement.json").read_text(), '{"revision": "local edit"}')

    def test_publish_names_units_without_changes(self):
        clone(self.local, self.real)
        with self.assertRaises(CloneError) as caught:
            publish(self.local, units=["bbb"])
        self.assertEqual(caught.exception.code, "unit_unchanged")

    def test_replace_keeps_unpublished_changes_unless_discarded(self):
        clone(self.local, self.real)
        write(self.local / "projects/aaa/arrangement.json", '{"revision": "unpublished"}')
        with self.assertRaises(CloneError) as caught:
            clone(self.local, self.real, replace=True)
        self.assertEqual(caught.exception.code, "unpublished_changes")
        clone(self.local, self.real, replace=True, discard_local=True)
        self.assertEqual((self.local / "projects/aaa/arrangement.json").read_text(), '{"revision": 1}')

    def test_skip_corpus_keeps_the_files_project_commands_read(self):
        clone(self.local, self.real, corpus=False)
        self.assertTrue((self.local / "corpus/tier-reference.json").exists())
        self.assertFalse((self.local / "corpus/manifest.sqlite").exists())

    def test_an_empty_workspace_points_to_workspace_clone(self):
        with self.assertRaises(FileNotFoundError) as caught:
            ProjectStore(self.local).directory("aaa")
        self.assertIn("workspace clone", str(caught.exception))

    def test_the_real_workspace_is_in_the_main_checkout(self):
        found = main_workspace()
        self.assertEqual(found.parts[-2:], ("sabermapper", "workspace"))
        self.assertTrue((found.parent.parent / ".git").exists())


def placed_lists(arrangement):
    return {(s["id"], n["id"]): n.get("placed") for s in arrangement["sections"] for n in s["notes"]}


class ClonedArrangementReachesTheRealWorkspaceTests(unittest.TestCase):
    """Reapplying a clone's arrangement never pins a value the clone's placer chose."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.real, self.local = base / "main" / "workspace", base / "worktree" / "workspace"
        self.real_store = ProjectStore(self.real)
        created = self.real_store.create(demo=True)
        self.project = created["project"]["id"]
        draft = created["arrangement"]
        for section in draft["sections"]:
            for note in section["notes"]:
                for field in ("x", "y", "color", "direction"):
                    note.pop(field, None)
        self.start = self.real_store.save(self.project, draft, created["revision"])
        clone(self.local, self.real)
        self.unit = f"projects/{self.project}"
        self.clone_file = self.local / self.unit / "arrangement.json"

    def replace_in_clone(self):
        """A clone save that inserts a note, so the placer re-chooses its neighbours' cuts."""
        store = ProjectStore(self.local)
        current = store.get(self.project)
        edited = json.loads(json.dumps(current["arrangement"]))
        section = next(s for s in edited["sections"] if len(s["notes"]) > 4)
        section["notes"].insert(2, {"id": "inserted", "beat": section["notes"][1]["beat"] + 0.5})
        saved = store.save(self.project, edited, current["revision"])["arrangement"]
        before = {(s["id"], n["id"]): n for s in self.start["arrangement"]["sections"] for n in s["notes"]}
        rechosen = [key for s in saved["sections"] for n in s["notes"] for key in [(s["id"], n["id"])]
                    if key in before and any(n[f] != before[key][f] for f in n["placed"])]
        self.assertTrue(rechosen, "the clone's placer re-chose placed values")
        return saved

    def test_publish_merges_project_json_and_keeps_placed_lists(self):
        saved = self.replace_in_clone()
        self.real_store.set_album(self.project, "Set in the studio")  # project.json only
        row = next(u for u in status(self.local)["units"] if u["unit"] == self.unit)
        self.assertEqual((row["conflicts"], row["merged"]), ([], [self.unit + "/project.json"]))

        result = publish(self.local)
        self.assertEqual(result["held_back"], [])
        self.assertEqual(result["applied"]["merged"], 1)
        real = self.real_store.get(self.project)
        self.assertEqual(real["revision"], ProjectStore(self.local).get(self.project)["revision"])
        self.assertEqual(placed_lists(real["arrangement"]), placed_lists(saved))
        self.assertTrue(all(p == ["x", "y", "color", "direction"] for p in placed_lists(real["arrangement"]).values()))
        meta = real["project"]
        self.assertEqual(meta["album"], "Set in the studio")
        self.assertFalse(meta["playtested"])
        self.assertEqual(status(self.local)["publishable"], [])
        self.assertEqual(read_json(self.local / self.unit / "project.json"), meta)

    def test_a_held_back_arrangement_reapplies_with_its_placed_lists(self):
        saved = self.replace_in_clone()
        studio = self.real_store.get(self.project)
        edited = json.loads(json.dumps(studio["arrangement"]))
        edited["sections"][0]["intent"] = "renamed in the studio"
        self.real_store.save(self.project, edited, studio["revision"])

        held = publish(self.local)["held_back"]
        self.assertEqual([h["unit"] for h in held], [self.unit])
        self.assertIn(f"--arrangement {self.clone_file} --base {self.clone_file}", held[0]["fix"])

        revision = self.real_store.get(self.project)["revision"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["project", "save", self.project, "--workspace", str(self.real), "--revision", revision,
                         "--arrangement", str(self.clone_file), "--base", str(self.clone_file)])
        self.assertEqual(code, 0, output.getvalue())
        real = self.real_store.get(self.project)["arrangement"]
        self.assertEqual(placed_lists(real), placed_lists(saved))
        self.assertEqual(real["sections"], saved["sections"])

    def test_restoring_a_revision_keeps_its_placed_lists(self):
        saved = self.replace_in_clone()
        store = ProjectStore(self.local)
        restored = store.restore(self.project, self.start["revision"], store.get(self.project)["revision"])
        self.assertEqual(placed_lists(restored["arrangement"]), placed_lists(self.start["arrangement"]))
        self.assertNotEqual(placed_lists(restored["arrangement"]), placed_lists(saved))

    def test_a_base_names_a_file_or_a_revision_in_history(self):
        with self.assertRaises(FileNotFoundError) as caught:
            self.real_store.base_arrangement(self.project, "f" * 64)
        self.assertIn("--base", str(caught.exception))
        self.assertEqual(self.real_store.base_arrangement(self.project, self.start["revision"]),
                         self.start["arrangement"])

    def test_merged_metadata_keeps_real_review_claims_only_for_unchanged_arrangements(self):
        local = {"title": "Clone title", "updated_at": "2026-09-23T10:00:00+00:00", "playtested": False,
                 "timing_reviewed": True, "album": "old"}
        real = {"title": "Old title", "updated_at": "2026-09-23T11:00:00+00:00", "playtested": True,
                "timing_reviewed": True, "album": "studio", "game_build": "1.40", "review_revision": "r0"}
        kept = merge_metadata(local, real, arrangements_published=False)
        self.assertEqual((kept["title"], kept["updated_at"], kept["album"], kept["game_build"], kept["playtested"]),
                         ("Clone title", real["updated_at"], "studio", "1.40", True))
        replaced = merge_metadata(local, real, arrangements_published=True)
        self.assertEqual((replaced["playtested"], replaced["timing_reviewed"]), (False, True))


if __name__ == "__main__":
    unittest.main()
