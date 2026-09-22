"""Independent state, concurrency, and review-boundary regression scenarios."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import multiprocessing
from pathlib import Path
import tempfile
import unittest

from sabermapper.projects import ConflictError, ProjectStore


def _process_save(root, project_id, arrangement, revision, label, gate, output):
    gate.wait(10)
    changed = deepcopy(arrangement)
    changed["sections"][0]["intent"] = label
    try:
        result = ProjectStore(root).save(project_id, changed, revision)
        output.put(("saved", result["revision"]))
    except ConflictError:
        output.put(("conflict", label))
    except Exception as exc:
        output.put(("error", f"{type(exc).__name__}: {exc}"))


class StudioRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.first = ProjectStore(self.temp.name)
        self.second = ProjectStore(self.temp.name)
        self.project = self.first.create(demo=True)
        self.pid = self.project["project"]["id"]

    def test_reads_are_stable_and_two_store_stale_write_rejected(self):
        path = self.first.directory(self.pid) / "arrangement.json"
        before = path.read_bytes()
        first_view = self.first.get(self.pid)
        second_view = self.second.get(self.pid)
        self.assertEqual(first_view["revision"], second_view["revision"])
        self.assertEqual(path.read_bytes(), before)
        edited = deepcopy(first_view["arrangement"])
        edited["sections"][0]["intent"] = "First store edit"
        saved = self.first.save(self.pid, edited, first_view["revision"])
        late = deepcopy(second_view["arrangement"])
        late["sections"][0]["intent"] = "Stale second store edit"
        with self.assertRaises(ConflictError):
            self.second.save(self.pid, late, second_view["revision"])
        self.assertEqual(self.second.get(self.pid)["revision"], saved["revision"])

    def test_simultaneous_stores_only_commit_one_revision(self):
        revision = self.project["revision"]

        def save_variant(label):
            arrangement = deepcopy(self.project["arrangement"])
            arrangement["sections"][0]["intent"] = label
            store = ProjectStore(self.temp.name)
            try:
                return ("saved", store.save(self.pid, arrangement, revision)["revision"])
            except ConflictError:
                return ("conflict", label)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(save_variant, ("Parallel A", "Parallel B")))
        self.assertEqual(sorted(row[0] for row in results), ["conflict", "saved"])
        current = self.first.get(self.pid)
        self.assertEqual(current["revision"], next(row[1] for row in results if row[0] == "saved"))
        self.assertIn(current["arrangement"]["sections"][0]["intent"], {"Parallel A", "Parallel B"})

    def test_cross_process_writes_preserve_one_winner(self):
        context = multiprocessing.get_context("spawn")
        gate, output = context.Event(), context.Queue()
        args = (self.temp.name, self.pid, self.project["arrangement"], self.project["revision"])
        workers = [context.Process(target=_process_save, args=(*args, label, gate, output))
                   for label in ("Process A", "Process B")]
        for worker in workers:
            worker.start()
        gate.set()
        results = [output.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(timeout=20)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sorted(item[0] for item in results), ["conflict", "saved"])
        self.assertEqual(self.first.get(self.pid)["revision"], next(item[1] for item in results if item[0] == "saved"))

    def test_locked_global_settings_and_feedback_request_integrity(self):
        base = self.first.get(self.pid)
        locked = self.first.set_lock(self.pid, base["arrangement"]["sections"][0]["id"], True, base["revision"])
        for field in ("bpm", "audio_offset_seconds"):
            changed = deepcopy(locked["arrangement"])
            changed["song"][field] += 1
            with self.assertRaises(ConflictError):
                self.first.save(self.pid, changed, locked["revision"])
        changed = deepcopy(locked["arrangement"])
        changed["difficulty"]["njs"] += 1
        with self.assertRaises(ConflictError):
            self.first.save(self.pid, changed, locked["revision"])
        changed = deepcopy(locked["arrangement"])
        changed["sections"][1]["intent"] = "Editable elsewhere"
        with self.assertRaises(ValueError):
            self.first.save(self.pid, changed, locked["revision"], request_id="bad")
        with self.assertRaises(ValueError):
            self.first.save(self.pid, changed, locked["revision"], request_id="0123456789ab")
        self.assertEqual(self.first.get(self.pid)["revision"], locked["revision"])
        feedback = self.first.add_feedback(self.pid, {"revision": locked["revision"],
                             "start_beat": 20, "end_beat": 21, "text": "Revise the later section"})
        saved = self.first.save(self.pid, changed, locked["revision"], request_id=feedback["id"])
        self.assertEqual(next(x for x in saved["feedback"] if x["id"] == feedback["id"])["status"], "addressed")
        self.assertEqual(next(x for x in saved["feedback"] if x["id"] == feedback["id"])["resulting_revision"], saved["revision"])
        another = deepcopy(saved["arrangement"])
        another["sections"][1]["intent"] = "Second revision"
        with self.assertRaises(ConflictError):
            self.first.save(self.pid, another, saved["revision"], request_id=feedback["id"])

    def test_review_claims_require_evidence_and_preserve_audio_hash(self):
        revision = self.project["revision"]
        with self.assertRaises(ValueError):
            self.first.review(self.pid, {"revision": revision, "playtested": True})
        with self.assertRaises(ValueError):
            self.first.review(self.pid, {"revision": revision, "ratings": {"fun": 6}})
        with self.assertRaises(ValueError):
            self.first.review(self.pid, {"revision": revision, "minutes_spent": -1})
        with self.assertRaises(ValueError):
            self.first.review(self.pid, {"revision": revision, "decision": "go"})
        before = self.first.get(self.pid)
        self.assertFalse(before["project"]["playtested"])
        result = self.first.review(self.pid, {"revision": revision, "playtested": True,
                    "game_build": "local test build", "notes": "Readability checked in game",
                    "ratings": {"fun": 4}, "minutes_spent": 12, "decision": "revise"})
        self.assertTrue(result["project"]["playtested"])
        self.assertEqual(result["reviews"][-1]["origin"], "user-entered")
        self.assertEqual(len(result["reviews"][-1]["audio_sha256"]), 64)
        self.assertEqual(Path(self.first.directory(self.pid), "song.ogg").read_bytes()[:4], b"OggS")


if __name__ == "__main__":
    unittest.main()
