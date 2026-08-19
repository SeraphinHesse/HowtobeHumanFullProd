"""SD-6: UI sound triggers, the per-button override, and the volume sliders.

Everything here is pure rect math + dict plumbing: the seam
(``game/ui/sound.py``) takes a host-injected SINK, so a fake sink records what
WOULD have been played and no audio device is ever opened. The data cases use
a private ``data/`` copy (``DataDirCase``) — never the live tree.
"""
import json
import unittest
from pathlib import Path

from engine import data_io
from game.core import audio_settings, load_balance
from game.core.phases import GameState
from game.ui import Shell, sound, widgets
from game.ui.settings import SessionSettings, SettingsScreen
from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.temp_data import DataDirCase

REPO = Path(__file__).resolve().parents[2]
VW, VH = 640, 360

CLICK_SLOT = {"clips": [{"file": "ui/click.ogg", "volume": 1.0,
                         "start": 0.0, "end": 0.0}],
              "loop": False, "pick": "random"}
LOVE_SLOT = {"clips": [{"file": "ui/refused.ogg", "volume": 1.0,
                        "start": 0.0, "end": 0.0}],
             "loop": False, "pick": "random"}


class SoundSeamTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        sound.reset()
        self.addCleanup(sound.reset)
        sound.configure({"button_click": CLICK_SLOT,
                         "not_enough_love": LOVE_SLOT})
        sound.set_sink(lambda slot, bus: self.calls.append((slot, bus)))

    def test_click_plays_the_global_slot(self):
        btn = widgets.Button((10, 10, 40, 20), "GO")
        self.assertTrue(widgets.click(btn, 20, 15))
        self.assertEqual(self.calls, [(CLICK_SLOT, "sfx")])
        # A click that misses is silent.
        self.assertFalse(widgets.click(btn, 200, 200))
        self.assertEqual(len(self.calls), 1)

    def test_per_widget_override_wins(self):
        btn = widgets.Button((10, 10, 40, 20), "GO")
        btn.sound = "imported/x.ogg"       # what ScreenSkinning.apply setattrs
        self.assertTrue(widgets.click(btn, 20, 15))
        (slot, bus), = self.calls
        self.assertEqual(bus, "sfx")
        self.assertEqual([c["file"] for c in slot["clips"]], ["imported/x.ogg"])
        self.assertNotEqual(slot, CLICK_SLOT)

    def test_not_enough_love_slot(self):
        sound.play_not_enough_love()
        self.assertEqual(self.calls, [(LOVE_SLOT, "sfx")])


class SilentByDefaultTest(unittest.TestCase):
    """No sink installed (the module default) and no slot table: every entry
    point is a no-op and nothing raises — that is what keeps smoke.py and the
    headless suite quiet."""

    def setUp(self):
        sound.reset()
        self.addCleanup(sound.reset)

    def test_no_sink_and_missing_slot_are_silent(self):
        btn = widgets.Button((0, 0, 10, 10), "X")
        self.assertTrue(widgets.click(btn, 5, 5))     # still consumes the click
        self.assertFalse(sound.play_slot("button_click"))
        self.assertFalse(sound.play_not_enough_love())
        sound.set_sink(lambda slot, bus: self.fail("empty slot reached the sink"))
        sound.configure({"button_click": {"clips": [], "loop": False,
                                          "pick": "random"}})
        self.assertFalse(sound.play_click(btn))


class VolumeSliderTest(unittest.TestCase):
    def _screen(self):
        screen = SettingsScreen(VW, VH, SessionSettings())
        return screen, screen._volume_bars["master_volume"].rect

    def test_click_sets_value_and_returns_the_action(self):
        screen, (sx, sy, sw, sh) = self._screen()
        self.assertEqual(screen.hit(sx, sy + sh // 2), "set_volume")
        self.assertEqual(screen.settings.master_volume, 0.0)
        self.assertEqual(screen.hit(sx + sw // 2, sy + sh // 2), "set_volume")
        self.assertAlmostEqual(screen.settings.master_volume, 0.5, places=1)

    def test_shell_passes_set_volume_through_as_an_intent(self):
        shell = Shell(VW, VH, load_balance(FIXTURE_DATA, "ui"),
                      start_state=GameState.SETTINGS)
        bar = shell.settings_screen._volume_bars["sfx_volume"].rect
        sx, sy, sw, sh = bar
        self.assertEqual(shell.handle_click(sx, sy + sh // 2), "set_volume")
        self.assertEqual(shell.settings.sfx_volume, 0.0)


class AudioSettingsFileTest(DataDirCase):
    def test_round_trip_and_validation(self):
        path = Path(self.data_dir).parent / "settings" / "audio.json"
        self.assertEqual(audio_settings.load(path, self.data_dir),
                         audio_settings.defaults())
        doc = {"master": 0.25, "music": 0.5, "sfx": 1.0}
        audio_settings.save(doc, path, self.data_dir)
        self.assertEqual(audio_settings.load(path, self.data_dir), doc)
        with self.assertRaises(Exception):
            audio_settings.save({"master": 1.5, "music": 0.5, "sfx": 1.0},
                                path, self.data_dir)


class ScreenSoundOverrideTest(DataDirCase):
    def _schema(self):
        return Path(self.data_dir) / "schemas" / "ui_screen.schema.json"

    def test_every_shipped_screen_still_validates(self):
        for doc in sorted((Path(self.data_dir) / "ui" / "screens").glob("*.json")):
            data_io.load_validated(doc, self._schema())

    def test_sound_key_accepts_a_string_and_rejects_a_number(self):
        out = Path(self.data_dir) / "ui" / "screens" / "settings.json"
        doc = json.loads(out.read_text(encoding="utf-8"))
        doc["widgets"]["btn_back"]["sound"] = "a.ogg"
        data_io.write_validated(doc, out, self._schema())
        doc["widgets"]["btn_back"]["sound"] = 5
        with self.assertRaises(Exception):
            data_io.write_validated(doc, out, self._schema())


if __name__ == "__main__":
    unittest.main()


class SinkReachesRealDispatcherTest(unittest.TestCase):
    """The seam contract END TO END, through the REAL ``GameSounds``.

    Every other case above installs a fake sink, so nothing exercised the one
    call `game/main.py`'s ``_ui_sound_sink`` actually makes:
    ``gp["sfx"].play_slot(slot, bus)``. ``GameSounds`` had no ``play_slot`` at
    all, and because ``gp["sfx"]`` is seeded at boot and never None, the
    sink's ``engine_audio`` fallback never ran — so a click, or a refused
    purchase, raised ``AttributeError`` the moment the slot had a clip in it.
    Empty slots never reached the sink, which is why the crash only appeared
    once sounds were imported.
    """

    def setUp(self):
        sound.reset()
        self.addCleanup(sound.reset)
        sound.configure({"button_click": CLICK_SLOT,
                         "not_enough_love": LOVE_SLOT})
        self.played = []

        class RecordingAudio:
            @staticmethod
            def play_slot(default_slot, override_slot=None, *, bus="sfx",
                          key=None, rng=None, loop=None):
                self.played.append((default_slot, override_slot, bus, key))
                return True

        from game.sounds import GameSounds
        self.sfx = GameSounds({}, {}, audio=RecordingAudio())
        sound.set_sink(self.sfx.play_slot)

    def test_click_reaches_the_dispatcher(self):
        btn = widgets.Button((10, 10, 40, 20), "GO")
        self.assertTrue(widgets.click(btn, 20, 15))
        self.assertEqual(len(self.played), 1)
        slot, override, bus, key = self.played[0]
        self.assertEqual(slot, CLICK_SLOT)
        self.assertIsNone(override)
        self.assertEqual(bus, "sfx")
        self.assertIn("ui/click.ogg", key)   # bucketed, not None

    def test_not_enough_love_reaches_the_dispatcher(self):
        self.assertTrue(sound.play_not_enough_love())
        self.assertEqual([c[0] for c in self.played], [LOVE_SLOT])

    def test_per_button_override_reaches_the_dispatcher(self):
        btn = widgets.Button((10, 10, 40, 20), "GO")
        btn.sound = "ui/special.ogg"
        self.assertTrue(widgets.click(btn, 20, 15))
        self.assertEqual(self.played[0][0]["clips"][0]["file"], "ui/special.ogg")

    def test_two_distinct_slots_get_distinct_cooldown_buckets(self):
        sound.play_slot("button_click")
        sound.play_not_enough_love()
        self.assertNotEqual(self.played[0][3], self.played[1][3])

    def test_a_clipless_slot_is_a_silent_false_not_a_raise(self):
        self.assertFalse(self.sfx.play_slot({"clips": []}, "sfx"))
        self.assertFalse(self.sfx.play_slot(None, "sfx"))
        self.assertEqual(self.played, [])
