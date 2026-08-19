"""SD-3: editor/sound_import.py — the pure half (no Qt).

Pins only the contract the brief names: import-copy + rejection, the CROSS-DOMAIN
refcount, the "count unknown, never zero" degrade, and the transcode skip when
the optional `soundfile` dependency is absent.
"""
import unittest

from editor import sound_import
from tools.tests.temp_data import DataDirCase


class TestImportClip(DataDirCase):
    def _src(self, name):
        path = self.data_dir / name
        path.write_bytes(b"\0" * 16)
        return path

    def test_copies_into_imported_and_returns_ref(self):
        ref = sound_import.import_clip(self.data_dir, self._src("shot.ogg"))
        self.assertEqual(ref, "imported/shot.ogg")
        self.assertTrue((self.data_dir / "audio" / "imported" / "shot.ogg").exists())

    def test_rejects_non_audio_extension(self):
        with self.assertRaises(ValueError):
            sound_import.import_clip(self.data_dir, self._src("shot.png"))

    def test_colliding_name_is_minted_not_overwritten(self):
        first = sound_import.import_clip(self.data_dir, self._src("shot.ogg"))
        second = sound_import.import_clip(self.data_dir, self._src("shot.ogg"))
        self.assertEqual(first, "imported/shot.ogg")
        self.assertEqual(second, "imported/shot_2.ogg")

    def test_transcode_skipped_cleanly_when_soundfile_absent(self):
        # Whether soundfile is installed or not, asking for a transcode must
        # produce a real file and a ref — never an exception.
        ref = sound_import.import_clip(
            self.data_dir, self._src("song.wav"), transcode=True)
        self.assertTrue(ref.startswith("imported/song."))
        if not sound_import.transcode_available():
            self.assertEqual(ref, "imported/song.wav")


class TestRefcount(unittest.TestCase):
    """Pure functions over hand-built docs — they never read data/."""

    REF = "imported/boom.ogg"

    def _doc(self, ref):
        return {"Group": {"slot": {"clips": [
            {"file": ref, "volume": 1.0, "start": 0.0, "end": 0.0}],
            "loop": False, "pick": "random"}}}

    def test_counts_across_domains(self):
        docs = {"buildings": self._doc("imported/other.ogg"),
                "enemies": self._doc(self.REF)}
        users, unknown = sound_import.clip_users(docs, self.REF)
        self.assertEqual(users, ("enemies",))
        self.assertEqual(unknown, ())
        self.assertEqual(
            sound_import.unreferenced_clips(docs, [self.REF]), ())
        self.assertEqual(
            sound_import.unreferenced_clips(docs, ["imported/nobody.ogg"]),
            ("imported/nobody.ogg",))

    def test_unreadable_domain_is_unknown_never_unreferenced(self):
        docs = {"buildings": self._doc("imported/other.ogg"), "enemies": None}
        users, unknown = sound_import.clip_users(docs, self.REF)
        self.assertEqual(users, ())
        self.assertEqual(unknown, ("enemies",))
        # Nothing may be reported free-to-delete while a domain is unknown.
        self.assertEqual(sound_import.unreferenced_clips(docs, [self.REF]), ())


class TestUsageDocs(DataDirCase):
    def test_staged_domain_uses_the_live_doc_not_disk(self):
        marker = {"__staged__": True}
        docs = sound_import.usage_docs(self.data_dir, "buildings", marker)
        self.assertIs(docs["buildings"], marker)
        # Derived domain list, not a hardcoded five.
        from editor import domains as domains_mod
        self.assertEqual(set(docs), set(domains_mod.domains(self.data_dir)))


if __name__ == "__main__":
    unittest.main()
