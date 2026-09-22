from copy import deepcopy
import unittest

from sabermapper.revisions import apply_section_revision, arrangement_revision


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "schema_version": "0.1",
            "song": {"title": "Test", "artist": "Fixture", "bpm": 120,
                     "audio_offset_seconds": 0},
            "difficulty": {"name": "Expert", "rank": 7, "njs": 16,
                           "spawn_offset_beats": 0},
            "motifs": {},
            "sections": [
                {"id": "a", "start_beat": 0, "length_beats": 4,
                 "intent": "Opening", "locked": False, "resolved": True,
                 "patterns": [], "notes": [
                     {"id": "one", "beat": 0, "x": 1, "y": 1,
                      "color": 0, "direction": 1}]},
                {"id": "b", "start_beat": 4, "length_beats": 4,
                 "intent": "Keep", "locked": True, "resolved": True,
                 "patterns": [], "notes": []},
            ],
        }

    def apply(self, replacement, **kwargs):
        return apply_section_revision(
            self.source, expected_revision=kwargs.get(
                "revision", arrangement_revision(self.source)),
            section_id=kwargs.get("section_id", "a"), replacement=replacement)

    def test_scoped_copy_and_preserved_lock(self):
        before = deepcopy(self.source)
        replacement = deepcopy(self.source["sections"][0])
        replacement["notes"][0]["x"] = 2
        result = self.apply(replacement)
        self.assertEqual(self.source, before)
        self.assertEqual(result["sections"][1], before["sections"][1])
        self.assertNotEqual(arrangement_revision(result), arrangement_revision(before))
        replacement["notes"].clear()
        self.assertEqual(len(result["sections"][0]["notes"]), 1)

    def test_stale_locked_and_invalid_changes_rejected(self):
        replacement = deepcopy(self.source["sections"][0])
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.apply(replacement, revision="old")
        locked = deepcopy(self.source["sections"][1])
        locked["locked"] = False
        with self.assertRaisesRegex(ValueError, "locked"):
            self.apply(locked, section_id="b")
        replacement["notes"][0]["x"] = 9
        with self.assertRaisesRegex(ValueError, "Invalid"):
            self.apply(replacement)

    def test_revision_ignores_json_key_order(self):
        self.assertEqual(arrangement_revision(self.source),
                         arrangement_revision(dict(reversed(list(self.source.items())))))


if __name__ == "__main__":
    unittest.main()
