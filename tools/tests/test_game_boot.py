"""E-37: a corrupt or missing asset manifest must never crash game boot —
the game logs and falls back to grey-X placeholders. Phase 6 adds the
OPPOSITE contract for MAP data (D-2/D-21): the game loads the active map
and fails LOUD on invalid map structure — tolerance is for art only.
Headless via SDL dummy drivers; runs against a tempfile copy of data/
(repo data never touched).
"""
import contextlib
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
                   "configure_strings"}   # strings._STRINGS
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

    def test_map_event_does_not_rescale_an_already_logical_mouse_pos(self):
        """LIVE BUG (G4 follow-up): every main-menu button was dead on
        --backend=gpu while its hover animation still worked.

        pygame-ce ALREADY delivers mouse events in renderer-logical
        coordinates once ``renderer.logical_size`` is set (MEASURED, pygame-ce
        2.5.7 / SDL 2.32.10: a 1280x720 window at logical 640x360 reports
        ``pos == (320, 180)`` for a click at physical (640, 360), and
        ``rel == (100, 50)`` for a physical (+200, +100) move). ``map_event``
        mapped them a SECOND time, so at the shipped fullscreen default every
        click landed at a third of its true position. ``mouse_pos()`` reads
        ``pygame.mouse.get_pos()``, which is NOT scaled, so hover stayed
        correct and nothing else looked wrong.

        The stub renderer below rescales, so a reintroduced mapping shows up
        as a wrong coordinate rather than an AttributeError."""
        class _StubRenderer:
            def coordinates_from_window(self, point):
                return point[0] / 3.0, point[1] / 3.0

        presenter = game_main_module._GpuPresenter.__new__(
            game_main_module._GpuPresenter)
        presenter._renderer = _StubRenderer()

        down = pygame.event.Event(
            pygame.MOUSEBUTTONDOWN,
            {"pos": (320, 163), "button": 1, "clicks": 1, "touch": False})
        mapped = game_main_module._GpuPresenter.map_event(presenter, down)
        self.assertEqual(mapped.pos, (320, 163))
        self.assertEqual(mapped.button, 1)

        motion = pygame.event.Event(
            pygame.MOUSEMOTION,
            {"pos": (250, 200), "rel": (100, 50), "buttons": (0, 0, 0),
             "touch": False})
        mapped = game_main_module._GpuPresenter.map_event(presenter, motion)
        self.assertEqual(mapped.pos, (250, 200))
        self.assertEqual(mapped.rel, (100, 50))

        # The other half of the asymmetry: get_pos() IS window pixels, so
        # mouse_pos() must keep remapping it.
        with unittest.mock.patch.object(pygame.mouse, "get_pos",
                                        lambda: (960, 489)):
            self.assertEqual(presenter.mouse_pos(), (320, 163))


if __name__ == "__main__":
    unittest.main()
