"""Importing the same source audio twice must not silently create a second project."""

from pathlib import Path
import tempfile
import unittest

from sabermapper.audio import generate_demo_audio
from sabermapper.projects import DuplicateProjectError, ProjectStore, repair_mojibake


class ImportDedupeTests(unittest.TestCase):
    def test_second_import_of_same_audio_is_refused_unless_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source.ogg"
            generate_demo_audio(source, seconds=8.0)
            store = ProjectStore(Path(root) / "workspace")
            first = store.create(source, title="Song", artist="Artist")["project"]
            with self.assertRaises(DuplicateProjectError) as raised:
                store.create(source, title="Song", artist="Artist")
            self.assertEqual(raised.exception.project_id, first["id"])
            self.assertIn(first["id"], str(raised.exception))
            self.assertEqual(len(store.list()), 1)
            second = store.create(source, title="Song", artist="Artist", allow_duplicate=True)["project"]
            self.assertNotEqual(second["id"], first["id"])
            self.assertEqual(len(store.list()), 2)

    def test_mojibake_metadata_is_repaired(self):
        self.assertEqual(repair_mojibake("La P'tite FumÃ©e"), "La P'tite Fumée")
        self.assertEqual(repair_mojibake("La P'tite Fumée"), "La P'tite Fumée")
        self.assertEqual(repair_mojibake("Beyoncé â€™Halo"), "Beyoncé â€™Halo")  # mixed: left unchanged
        self.assertEqual(repair_mojibake("Itâ€™s"), "It’s")


if __name__ == "__main__":
    unittest.main()
