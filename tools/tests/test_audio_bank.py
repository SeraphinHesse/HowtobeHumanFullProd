"""SD-2: engine.audio.bank is PURE — resolve/pick/volume math, no pygame."""
import random
import subprocess
import sys
import unittest
from pathlib import Path

from engine.audio import bank

REPO = Path(__file__).resolve().parents[2]


class TestResolve(unittest.TestCase):
    def test_non_empty_override_wins(self):
        default = {"clips": [{"file": "a.wav", "volume": 1.0, "start": 0.0, "end": 0.0}]}
        override = {"clips": [{"file": "b.wav", "volume": 1.0, "start": 0.0, "end": 0.0}]}
        self.assertEqual(bank.resolve(default, override), override)

    def test_empty_override_falls_through_to_default(self):
        default = {"clips": [{"file": "a.wav", "volume": 1.0, "start": 0.0, "end": 0.0}]}
        override = {"clips": []}
        self.assertEqual(bank.resolve(default, override), default)

    def test_both_empty_is_none(self):
        self.assertIsNone(bank.resolve({"clips": []}, {"clips": []}))
        self.assertIsNone(bank.resolve(None, None))


class TestPickClip(unittest.TestCase):
    def test_seeded_random_pick_is_deterministic(self):
        slot = {
            "clips": [
                {"file": "a.wav", "volume": 1.0, "start": 0.0, "end": 0.0},
                {"file": "b.wav", "volume": 1.0, "start": 0.0, "end": 0.0},
            ],
            "pick": "random",
        }
        rng1 = random.Random(1234)
        rng2 = random.Random(1234)
        self.assertEqual(bank.pick_clip(slot, rng1), bank.pick_clip(slot, rng2))

    def test_sequential_cycles_by_counter(self):
        slot = {
            "clips": [
                {"file": "a.wav", "volume": 1.0, "start": 0.0, "end": 0.0},
                {"file": "b.wav", "volume": 1.0, "start": 0.0, "end": 0.0},
            ],
            "pick": "sequential",
        }
        self.assertEqual(bank.pick_clip(slot, counter=0)["file"], "a.wav")
        self.assertEqual(bank.pick_clip(slot, counter=1)["file"], "b.wav")
        self.assertEqual(bank.pick_clip(slot, counter=2)["file"], "a.wav")


class TestEffectiveVolume(unittest.TestCase):
    def test_multiplies_master_bus_clip(self):
        clip = {"file": "a.wav", "volume": 0.8, "start": 0.0, "end": 0.0}
        self.assertAlmostEqual(bank.effective_volume(clip, bus_volume=0.5, master=0.5), 0.2)

    def test_clamps_above_one(self):
        clip = {"file": "a.wav", "volume": 2.0, "start": 0.0, "end": 0.0}
        self.assertEqual(bank.effective_volume(clip, bus_volume=2.0, master=2.0), 1.0)


class TestPurity(unittest.TestCase):
    """Hard rule: engine.audio.bank imports no pygame — headless-testable."""

    def test_engine_audio_bank_does_not_import_pygame(self):
        code = (
            "import sys; "
            "import engine.audio.bank; "
            "assert 'pygame' not in sys.modules, 'pygame leaked into engine.audio.bank'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_module_getattr_resolves_submodules_without_regressing_purity(self):
        """PEP 562 fix: `engine.audio.sfx` / `.music` must resolve as
        attributes even with NO prior facade call (the SD-7 MusicDirector
        default-argument case, `music=audio.music` evaluated at `def`
        time) — and `import engine.audio.bank` alone must still never pull
        pygame in, i.e. `__getattr__` must not be triggered by that path."""
        code = (
            "import sys; "
            "import engine.audio as audio; "
            "assert audio.music is not None; "
            "assert audio.sfx is not None; "
            "assert 'pygame' in sys.modules, "
            "'expected pygame to load via the sfx/music attribute resolution'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        # Second, separate process: `import engine.audio.bank` alone (no
        # attribute lookup on .sfx/.music) must stay pygame-free.
        code2 = (
            "import sys; "
            "import engine.audio.bank; "
            "assert 'pygame' not in sys.modules, "
            "'pygame leaked into engine.audio.bank via bare submodule import'"
        )
        result2 = subprocess.run(
            [sys.executable, "-c", code2], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result2.returncode, 0, msg=result2.stderr)


if __name__ == "__main__":
    unittest.main()
