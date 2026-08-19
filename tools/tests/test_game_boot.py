"""E-37: a corrupt or missing asset manifest must never crash game boot —
the game logs and falls back to grey-X placeholders. Phase 6 adds the
OPPOSITE contract for MAP data (D-2/D-21): the game loads the active map
and fails LOUD on invalid map structure — tolerance is for art only.
Headless via SDL dummy drivers; runs against a tempfile copy of data/
(repo data never touched).
"""
import contextlib
import copy
import io
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import jsonschema  # noqa: E402
import pygame  # noqa: E402

from engine import data_io, tilemap  # noqa: E402
from engine.render import fonts as _fonts  # noqa: E402
from game import main as game_main_module  # noqa: E402
from game.main import main as game_main  # noqa: E402
from game.ui import strings as _strings  # noqa: E402
from game.ui import widgets as _widgets  # noqa: E402
from tools.tests.temp_data import DataDirCase  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def _restore_font_state_after(case):
    """Undo the theme globals that BOOTING THE GAME installs.

    `test_theme_data.py`'s module docstring states the house rule: every test
    that calls `configure_fonts`/`configure_palette` must `addCleanup`-restore
    the unconfigured state, because those mutate module globals and "a leaked
    configure poisons every later parity test in the same process". Booting
    the game calls all three (`game/main.py` — fonts WITH the real
    `active_font.json` TTF, palette, strings), and this module never restored
    them, so it was the one place the rule was broken.

    The damage was invisible and order-dependent: under `--dist loadfile` a
    worker that ran this file first left the real Pixel Emulator face
    installed, and every later text measurement in that worker used it instead
    of the `SysFont("monospace")` fallback every UI parity/pin test is written
    against. `test_ui_min_targets.TestStaticLabelFit` then reported twelve
    static buttons overhanging (e.g. "RETURN TO MENU" needing 154px in a 120px
    box) — real numbers for the shipped font, but produced by a test that had
    no idea which font it was measuring, and only when the shuffle happened to
    put the two files in one worker. It is exactly the flake that makes a
    suite untrustworthy: green alone, red in CI, blamed on the last person to
    touch anything.

    Those twelve overhangs were a genuine finding about the real font, not an
    artifact, and they are FIXED: the copy was cut to fit and three buttons
    dropped a preset. `test_ui_min_targets.py` now installs the shipped face
    in `setUpModule` and asserts against it, so that measurement is deliberate
    and owned there — which is where it belongs. This cleanup exists so the
    two modules cannot interfere either way.
    """
    font_family = (_fonts._FONT_PATH, _fonts._FONT_BYTES)
    font_specs = dict(_fonts._FONT_SPECS)
    palette = {name: getattr(_widgets, name)
               for name in dir(_widgets) if name.startswith("C_")}
    # ALL THREE, not two. `main()` calls configure_fonts + configure_palette +
    # configure_strings, and the first version of this helper restored only the
    # first two. The strings leak then behaved exactly like the font one and
    # was just as invisible locally: `configure_strings` replaces `_STRINGS`
    # IN PLACE from live `data/ui/strings.json`, so any later test in the same
    # worker sees LIVE copy where it expected the module's unconfigured
    # fallback. `test_strings_data.TestFallbackEqualsStock` — whose whole job
    # is to catch dual-store drift between the Python literal and the JSON —
    # passed on Windows (where the shuffle happened to separate them) and
    # failed on CI's `core` shard, reporting a drift that did not exist.
    strings_snapshot = dict(_strings._STRINGS)
    # A FOURTH, exactly as this class's docstring predicted one would be:
    # VfxAuthoringPLAN VA-5's `configure_highlights` moved five tile-highlight
    # colours out of the C_* block (three of them palette keys) into
    # `data/balancing/vfx.json`, and rebinds two module dicts IN PLACE from
    # the live file at boot — the same shape as `_STRINGS`, so the same leak.
    # `test_highlight_data.TestFallbackEqualsData` is the drift test it would
    # otherwise have made lie.
    highlights_snapshot = copy.deepcopy(_widgets._HIGHLIGHTS)
    highlight_triggers_snapshot = dict(_widgets._HIGHLIGHT_TRIGGERS)
    # The tile-buying tutorial topic's pulse/glow overlay: a THIRD dict
    # `configure_highlights` rebinds in place from the same live file —
    # the exact same leak shape, one call site later.
    tutorial_pulse_snapshot = dict(_widgets._TUTORIAL_PULSE)

    def restore():
        _fonts._FONT_PATH, _fonts._FONT_BYTES = font_family
        # `_FONT_SPECS` is replaced IN PLACE by configure_fonts, so restore it
        # the same way rather than rebinding the name.
        _fonts._FONT_SPECS.clear()
        _fonts._FONT_SPECS.update(font_specs)
        _fonts._cache.clear()   # built from the OLD size/face — must not survive
        for name, value in palette.items():
            setattr(_widgets, name, value)
        _strings._STRINGS.clear()
        _strings._STRINGS.update(strings_snapshot)
        # Both are replaced IN PLACE by configure_highlights, so restore them
        # the same way rather than rebinding the names.
        _widgets._HIGHLIGHTS.clear()
        _widgets._HIGHLIGHTS.update(highlights_snapshot)
        _widgets._HIGHLIGHT_TRIGGERS.clear()
        _widgets._HIGHLIGHT_TRIGGERS.update(highlight_triggers_snapshot)
        _widgets._TUTORIAL_PULSE.clear()
        _widgets._TUTORIAL_PULSE.update(tutorial_pulse_snapshot)

    case.addCleanup(restore)


class TestTheRestoreCoversEveryThemeGlobal(unittest.TestCase):
    """A new `configure_*` must not be able to leak the way the last three did.

    This exact bug has now been found THREE times — fonts, palette, strings —
    always the same shape: `game/main.py` configures a module global at boot,
    this file boots the game, nothing restores it, and a later test in the same
    xdist worker silently measures the live value. Each one was invisible on
    the machine it was written on and only surfaced as a "flake" elsewhere.

    So the helper's coverage is asserted rather than trusted: the set of
    `configure_*` entry points the host calls is pinned, and adding a fourth
    without teaching `_restore_font_state_after` about it fails HERE, with a
    message saying what to do — instead of as someone else's flaky test three
    weeks later.
    """

    def test_no_unrestored_configure_entry_point_exists(self):
        import re
        host = (REPO / "game" / "main.py").read_text(encoding="utf-8")
        called = set(re.findall(r"\b(configure_\w+)\s*\(", host))
        covered = {"configure_fonts",     # _FONT_PATH/_FONT_BYTES/_FONT_SPECS/_cache
                   "configure_palette",   # widgets.C_*
                   "configure_strings",   # strings._STRINGS
                   "configure_highlights"}  # widgets._HIGHLIGHTS/_TRIGGERS
        self.assertEqual(
            called, covered,
            "game/main.py configures a module global this file's "
            "`_restore_font_state_after` does not restore (or no longer needs "
            "to). Booting the game leaks it into every later test in the same "
            "xdist worker — the fonts/palette/strings bug, a fourth time. "
            "Teach the helper to snapshot and restore it, then update this set.")


class TempDataBoot(DataDirCase):
    """DataDirCase gives the tempdir data/ copy — this class had duplicated
    that copytree by hand."""

    def setUp(self):
        super().setUp()
        self.manifest_path = self.data_dir / "sprites" / "asset_manifest.json"
        _restore_font_state_after(self)


class TestFineScrollIsNotDiscarded(unittest.TestCase):
    """LIVE BUG: the wheel arms were guarded on ``and event.y``.

    ``event.y`` is an INTEGER. A precision touchpad, a free-spin wheel and
    macOS inertial scrolling all report the gesture in ``precise_y`` and leave
    ``y`` at **0**, so every such event was discarded before any handler ran
    and nothing scrolled or zoomed at all — while the same code worked
    perfectly on a notched mouse. That asymmetry is why the construct card
    list measured green at every layer (model, host routing, draw) and was
    still unusable for the person reporting it."""

    def _wheel(self, y, precise_y):
        return pygame.event.Event(
            pygame.MOUSEWHEEL,
            {"y": y, "x": 0, "precise_y": precise_y, "precise_x": 0.0,
             "flipped": False, "touch": precise_y != y})

    def test_fractions_accumulate_into_whole_ticks(self):
        w = game_main_module._WheelTicks()
        got = [w.of(self._wheel(0, -0.34)) for _ in range(6)]
        self.assertEqual([t for t in got if t], [-1, -1],
                         "six 0.34 nudges are two whole ticks, not zero")

    def test_a_notched_wheel_is_one_tick_each(self):
        w = game_main_module._WheelTicks()
        self.assertEqual(w.of(self._wheel(1, 1.0)), 1)
        self.assertEqual(w.of(self._wheel(-1, -1.0)), -1)

    def test_a_backend_that_leaves_precise_y_empty_falls_back_to_y(self):
        w = game_main_module._WheelTicks()
        self.assertEqual(w.of(self._wheel(1, 0.0)), 1)

    def test_a_reversal_drops_the_residue(self):
        w = game_main_module._WheelTicks()
        w.of(self._wheel(0, 0.9))              # nearly a tick, held
        self.assertEqual(w.of(self._wheel(0, -0.9)), 0,
                         "the up-residue must not delay the first down tick")
        self.assertEqual(w.of(self._wheel(0, -0.2)), -1)


class TestHoverReadsTheSameCursorAsClicks(TempDataBoot):
    """LIVE BUG, the mirror of
    ``test_map_event_does_not_rescale_an_already_logical_mouse_pos`` above.

    Clicks have always used ``event.pos``; hover used to read
    ``presenter.mouse_pos()`` — a DIFFERENT source, and the only one either
    presenter remaps. When the two disagree, every hover/pressed skin row
    fires for whatever widget sits under the *other* coordinate: buttons that
    still click correctly never light up, widgets near the top-left light up
    with the cursor nowhere near them, and the cursor-anchored lightning
    progress bar draws at the wrong place. One source now, so they cannot.

    The stub below makes them disagree on purpose: ``get_pos()`` answers a
    point over the RANGE pill while the mouse EVENT reports one over End
    Turn. The event must win.
    """

    def test_the_event_position_wins_over_get_pos(self):
        end_turn_pt = (600, 300)     # inside btn_end_turn's authored rect
        elsewhere = (10, 112)        # inside the RANGE overlay pill's rect
        seen = {}
        real_submit = _widgets.Button.submit

        def record(button, renderer, **kwargs):
            if button.skin:
                seen.setdefault(button.skin, set()).add(button._state())
            return real_submit(button, renderer, **kwargs)

        real_get = pygame.event.get

        def with_motion(*args, **kwargs):
            events = list(real_get(*args, **kwargs))
            events.append(pygame.event.Event(
                pygame.MOUSEMOTION,
                {"pos": end_turn_pt, "rel": (0, 0), "buttons": (0, 0, 0),
                 "touch": False}))
            return events

        with unittest.mock.patch.object(_widgets.Button, "submit", record),                 unittest.mock.patch.object(pygame.event, "get", with_motion),                 unittest.mock.patch.object(pygame.mouse, "get_pos",
                                           lambda: elsewhere):
            game_main(max_frames=6, data_dir=self.data_dir, autostart=True)

        self.assertIn("hover", seen.get("ui_button_end_turn", set()),
                      "the button under the EVENT position must hover")
        self.assertNotIn("hover", seen.get("ui_panel_stone", set()),
                         "no widget under the stale get_pos() may hover")


class TestCorruptManifestBoot(TempDataBoot):
    def test_corrupt_manifest_boots_and_logs(self):
        self.manifest_path.write_text("{this is not json", encoding="utf-8")
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            frames = game_main(max_frames=2, data_dir=self.data_dir,
                               autostart=True)
        self.assertEqual(frames, 2)

    def test_missing_manifest_boots_clean(self):
        self.manifest_path.unlink()
        self.assertEqual(
            game_main(max_frames=2, data_dir=self.data_dir, autostart=True), 2)

    def test_default_data_dir_still_boots(self):
        # default shell path: real data has the cutscene -> boots in CUTSCENE.
        self.assertEqual(game_main(max_frames=1), 1)

    def test_shell_boots_to_menu_without_cutscene(self):
        # 9H: remove the video -> VideoSource disables -> boot lands on
        # MAIN_MENU and renders the null-world menu path headlessly.
        (self.data_dir / "video" / "cutscene.mp4").unlink()
        self.assertEqual(game_main(max_frames=2, data_dir=self.data_dir), 2)


class TestActiveMapBoot(TempDataBoot):
    """Phase 6 (D-20/D-21): the game renders the ACTIVE map's painted grid."""

    def test_boots_on_a_freshly_painted_map(self):
        doc = tilemap.new_doc("painted", "Painted", 10, 8,
                              tilemap.map_schema_path(self.data_dir))
        doc.terrain[2][3] = "s"
        doc.deco.append({"col": 5, "row": 5, "slot": "deco_tree"})
        tilemap.save_map(doc, tilemap.map_path(self.data_dir, "painted"),
                         tilemap.map_schema_path(self.data_dir))
        data_io.write_validated(
            {"active": "painted"},
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))
        self.assertEqual(
            game_main(max_frames=2, data_dir=self.data_dir, autostart=True), 2)

    def test_missing_active_pointer_fails_loud(self):
        tilemap.active_map_path(self.data_dir).unlink()
        with self.assertRaises(FileNotFoundError):
            game_main(max_frames=1, data_dir=self.data_dir)

    def _active_map_path(self):
        active = data_io.load_json(
            tilemap.active_map_path(self.data_dir))["active"]
        return tilemap.map_path(self.data_dir, active)

    def test_schema_invalid_map_fails_loud(self):
        path = self._active_map_path()
        doc = data_io.load_json(path)
        del doc["base"]
        path.write_text(data_io.dumps_deterministic(doc), encoding="utf-8")
        with self.assertRaises(jsonschema.ValidationError):
            game_main(max_frames=1, data_dir=self.data_dir)

    def test_dims_inconsistent_map_fails_loud(self):
        path = self._active_map_path()
        doc = data_io.load_json(path)
        doc["terrain"] = doc["terrain"][:-1]   # schema-valid, dims broken
        path.write_text(data_io.dumps_deterministic(doc), encoding="utf-8")
        with self.assertRaises(ValueError):
            game_main(max_frames=1, data_dir=self.data_dir)


class TestRenderBackendSelection(TempDataBoot):
    """G4: the host's GPU path, its D8 fallback, and the one bug that is
    otherwise invisible (a frozen HUD). Headless under the dummy video driver,
    which CAN host an SDL Renderer."""

    def _boot(self, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            frames = game_main(max_frames=5, data_dir=self.data_dir,
                               autostart=True, **kw)
        return frames, buf.getvalue()

    def test_gpu_boot_runs_and_names_the_backend(self):
        frames, out = self._boot(backend="gpu")
        self.assertEqual(frames, 5)
        self.assertIn("render backend: GPU (SDL2 texture", out)
        self.assertIn("ground cache: GroundCacheGpu", out)

    def test_headless_default_stays_on_the_surface_path(self):
        # `max_frames is not None` forces Surface — the single condition that
        # keeps tools/smoke.py on today's stack with no flag of its own.
        frames, out = self._boot()
        self.assertEqual(frames, 5)
        self.assertIn("render backend: Surface (CPU blitter)", out)
        self.assertNotIn("GPU", out)

    def test_gpu_failure_falls_back_to_surface_and_says_why(self):
        from pygame._sdl2 import video as sdl2

        def boom(*args, **kwargs):
            raise RuntimeError("no fast renderer available")

        with unittest.mock.patch.object(sdl2, "Renderer", boom):
            frames, out = self._boot(backend="gpu")
        self.assertEqual(frames, 5)
        self.assertIn("render backend: Surface (CPU blitter) — GPU requested "
                      "but unavailable: RuntimeError: no fast renderer "
                      "available", out)

    def test_hud_texture_is_updated_once_per_frame_not_once_ever(self):
        """The §1.3 pin: backend_gpu's texture cache snapshots a source
        surface at first upload, so a HUD that rode it would freeze at frame 1
        with no exception, no log line and no other failing test. The host
        therefore owns a streaming Texture it updates EVERY frame — assert the
        count, not merely that it happened."""
        updates = []
        original = game_main_module._GpuPresenter._new_streaming_texture

        class _SpyTexture:
            def __init__(self, tex):
                self._tex = tex

            def update(self, *args, **kwargs):
                updates.append(1)
                return self._tex.update(*args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._tex, name)

        def spied(presenter):
            return _SpyTexture(original(presenter))

        with unittest.mock.patch.object(
                game_main_module._GpuPresenter, "_new_streaming_texture",
                spied):
            frames, out = self._boot(backend="gpu")
        self.assertEqual(frames, 5)
        self.assertIn("render backend: GPU", out)
        self.assertEqual(len(updates), 5, "the HUD composite must upload once "
                                          "per frame, or the HUD freezes")

    # -- cursor space: which source is scaled is MEASURED, not assumed ----
    #
    # This pair of tests used to be one test pinning a hard-coded answer, and
    # it has been wrong in each direction in turn. `event.pos` and
    # `pygame.mouse.get_pos()` both report the cursor, and on the GPU path one
    # of them is in window pixels while the other is already renderer-logical
    # — but WHICH one differs between pygame/SDL builds:
    #
    #   * 1280x720 window at logical 640x360: events arrived logical and
    #     get_pos() was window pixels. A `map_event` that mapped anyway put
    #     every click at a third of its position, so no menu button fired
    #     while hover (the other source) stayed correct.
    #   * 1920x1080 window at logical 640x360, direct3d: the reverse. MEASURED
    #     live — `event.pos == (1652, 536)` for the cursor `get_pos()` reports
    #     as (549, 177). `mouse_pos()` divided that correct value again and
    #     handed hover (183, 59), which lit widgets near the top-left, drew
    #     the lightning cooldown bar in the wrong place, and made the
    #     construct card list refuse the wheel — `wants_scroll` was asked
    #     about a point three times too far up and left to be on the panel.
    #
    # `_calibrate` compares the two readings of the SAME cursor and derives
    # the answer. Both directions are pinned here; neither is the default.

    def _presenter(self, window_size=(1920, 1080)):
        p = game_main_module._GpuPresenter.__new__(
            game_main_module._GpuPresenter)

        class _StubRenderer:
            def coordinates_from_window(self, point):
                return point[0] / 3.0, point[1] / 3.0

        p._renderer = _StubRenderer()
        p._window = unittest.mock.Mock(size=window_size)
        p._view_w, p._view_h = 640, 360
        p._map_events = None
        p._map_get_pos = False
        return p

    def test_events_in_window_pixels_are_mapped_and_get_pos_is_not(self):
        """The live case: `event.pos` is window pixels, `get_pos()` logical."""
        p = self._presenter()
        motion = pygame.event.Event(
            pygame.MOUSEMOTION,
            {"pos": (1647, 531), "rel": (300, 150), "buttons": (0, 0, 0),
             "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (549, 177)):
            mapped = p.map_event(motion)
            self.assertEqual(mapped.pos, (549, 177))
            self.assertEqual(mapped.rel, (100, 50),
                             "rel rides the same scale, or panning is 3x fast")
            self.assertEqual(p.mouse_pos(), (549, 177),
                             "get_pos() is already logical — do not divide it")

    def test_get_pos_in_window_pixels_is_mapped_and_events_are_not(self):
        """The other build: events arrive logical, `get_pos()` does not."""
        p = self._presenter()
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (320, 163), "button": 1, "clicks": 1, "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (960, 489)):
            mapped = p.map_event(down)
            self.assertEqual(mapped.pos, (320, 163))
            self.assertEqual(mapped.button, 1)
            self.assertEqual(p.mouse_pos(), (320, 163))

    def test_an_unscaled_window_maps_neither(self):
        p = self._presenter(window_size=(640, 360))
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (320, 163), "button": 1, "clicks": 1, "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (320, 163)):
            self.assertEqual(p.map_event(down).pos, (320, 163))
            self.assertEqual(p.mouse_pos(), (320, 163))

    def test_two_sources_that_already_agree_map_neither(self):
        p = self._presenter()
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (549, 177), "button": 1, "clicks": 1, "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (549, 177)):
            self.assertEqual(p.map_event(down).pos, (549, 177))
            self.assertEqual(p.mouse_pos(), (549, 177))
        self.assertFalse(p._map_events)
        self.assertFalse(p._map_get_pos)

    def test_a_sample_taken_mid_flick_defers_instead_of_guessing(self):
        """The two reads are a frame apart. If neither relation holds the
        cursor moved between them — freezing a verdict from that sample is how
        a coordinate bug becomes intermittent."""
        p = self._presenter()
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (1647, 531), "button": 1, "clicks": 1, "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (77, 301)):
            p.map_event(down)
        self.assertIsNone(p._map_events)
        # a clean sample right after still decides
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (549, 177)):
            self.assertEqual(p.map_event(down).pos, (549, 177))
        self.assertTrue(p._map_events)

    def test_a_cursor_at_the_origin_does_not_decide_anything(self):
        """Every space agrees at (0, 0) — calibrating there would coin-flip."""
        p = self._presenter()
        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (1, 2), "button": 1, "clicks": 1, "touch": False})
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (0, 0)):
            p.map_event(down)
        self.assertIsNone(p._map_events, "still undecided, try the next event")

    def test_the_wheel_is_left_alone(self):
        """MOUSEWHEEL carries no `pos` — mapping it would raise."""
        p = self._presenter()
        wheel = pygame.event.Event(
            pygame.MOUSEWHEEL,
            {"y": -1, "x": 0, "precise_y": -1.0, "precise_x": 0.0,
             "flipped": False, "touch": False})
        self.assertIs(p.map_event(wheel), wheel)


class TestDpiAwareness(unittest.TestCase):
    """The frame is a fixed 640x360 buffer upscaled whole to the monitor, so a
    DPI-unaware process gets its window bilinear-stretched by the Windows
    compositor AFTER SDL is done — blur nothing inside the frame can undo, plus
    a non-integer scale factor that deforms glyph stems. See
    `_enable_dpi_awareness`."""

    _HINT = "SDL_WINDOWS_DPI_AWARENESS"

    def setUp(self):
        self._saved = os.environ.get(self._HINT)
        os.environ.pop(self._HINT, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(self._HINT, None)
        else:
            os.environ[self._HINT] = self._saved

    def test_sets_per_monitor_awareness(self):
        game_main_module._enable_dpi_awareness()
        self.assertEqual(os.environ[self._HINT], "permonitorv2")

    def test_env_override_wins(self):
        """setdefault, not assignment — a launcher may pin a different mode."""
        os.environ[self._HINT] = "system"
        game_main_module._enable_dpi_awareness()
        self.assertEqual(os.environ[self._HINT], "system")


if __name__ == "__main__":
    unittest.main()
