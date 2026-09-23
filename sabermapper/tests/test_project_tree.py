"""Projects carry an album so the studio can group them as artist / album / song."""

from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from sabermapper.__main__ import main
from sabermapper.audio import generate_demo_audio
from sabermapper.projects import ProjectStore, source_album


class ProjectAlbumTests(unittest.TestCase):
    def test_album_tag_wins_over_folder_layout(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "Artist" / "Folder Album" / "Song.flac"
            source.parent.mkdir(parents=True)
            with sf.SoundFile(source, "w", 44100, 1, format="FLAC") as handle:
                handle.album = "Tagged Album"
                handle.write(np.zeros(4410))
            self.assertEqual(source_album(source, "Artist"), "Tagged Album")

    def test_folder_layout_is_used_only_under_the_artist_folder(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "La P'tite Fumée" / "The Spell" / "song.ogg"
            source.parent.mkdir(parents=True)
            generate_demo_audio(source, seconds=8.0)
            self.assertEqual(source_album(source, "la p'tite fumée"), "The Spell")
            self.assertIsNone(source_album(source, "Someone Else"))
            self.assertIsNone(source_album(Path(root) / "missing.ogg", "Artist"))
            self.assertIsNone(source_album(None, "Artist"))

    def test_import_records_album_and_set_album_overrides_it(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "Artist" / "Debut" / "song.ogg"
            source.parent.mkdir(parents=True)
            generate_demo_audio(source, seconds=8.0)
            workspace = Path(root) / "workspace"
            store = ProjectStore(workspace)
            project = store.create(source, title="Song", artist="Artist")["project"]
            self.assertEqual(project["album"], "Debut")
            self.assertEqual(store.list()[0]["album"], "Debut")
            self.assertEqual(store.set_album(project["id"], " Remaster ")["album"], "Remaster")
            self.assertEqual(store.list()[0]["album"], "Remaster")
            self.assertEqual(main(["project", "set-album", project["id"], "--workspace", str(workspace),
                                   "--album", ""]), 0)
            self.assertEqual(store.list()[0]["album"], "Debut")
            explicit = store.create(source, title="Song", artist="Artist", album="Live",
                                    allow_duplicate=True)["project"]
            self.assertEqual(explicit["album"], "Live")

    def test_projects_without_album_metadata_derive_it_when_listed(self):
        with tempfile.TemporaryDirectory() as root:
            store = ProjectStore(Path(root) / "workspace")
            demo = store.create(demo=True)["project"]
            self.assertIsNone(store.list()[0]["album"])
            self.assertIsNone(demo["album"])


if __name__ == "__main__":
    unittest.main()
