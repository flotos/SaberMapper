import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from sabermapper.__main__ import main
from sabermapper.projects import ProjectStore
from sabermapper.workspace_clone import CloneError, clone, main_workspace, publish, status


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


if __name__ == "__main__":
    unittest.main()
