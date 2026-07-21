"""fix-anchor-offset-and-bullet-sprites Fix 2: swappable bullet sprites.

``FloaterManager.submit_projectiles`` draws every in-flight shot as a coloured
``HudRect`` dot UNLESS its slot (``vfx_projectile`` for every defender's
stone, ``vfx_shell`` for a mortar's shell) has imported art, in which case it
draws a ``HudSprite`` instead — colour/size/lift come from
``data/balancing/vfx.json procedural.projectile`` (``engine.vfx.
ProjectileParams``), never a module constant any more.

Headless/pure: a fake scene + a recording renderer, the ``test_enemy_hp_bars.
py`` pattern. Never touches live ``data/`` — the pinned ``FIXTURE_DATA``
snapshot only, never written.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import GameObject, Transform
from engine.render import HudRect, HudSprite
from game.core import load_balance
from game.ui.effects import FloaterManager

CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")
PROJ = VFX_BAL["procedural"]["projectile"]   # today's shipped defaults


def _shipped_defaults_are_unchanged():
    """Guards the whole module against a designer having retuned the fixture
    since this was written — the exact-value assertions below need the
    values pinned in the schema-writing skill call."""
    return (
        tuple(PROJ["stone_color"]) == (185, 180, 170)
        and tuple(PROJ["shell_color"]) == (70, 60, 55)
        and PROJ["stone_size"] == 3
        and PROJ["shell_size"] == 5
        and PROJ["lift_frac"] == 0.6
    )


class RecordingRenderer:
    """``submit_projectiles`` emits only through ``submit_hud``."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


class FakeScene:
    def __init__(self, objects):
        self._objects = list(objects)

    def by_tag(self, tag):
        return [o for o in self._objects if tag in o.tags]


def make_shot(name, wx, wy):
    return GameObject(name=name, tags=("projectile",),
                      transform=Transform(wx=wx, wy=wy))


def make_store_with_art(*slot_keys, frame_w=64, frame_h=64):
    """An AssetStore where every slot in `slot_keys` has one imported `idle`
    frame — `animation_total_ms` returns a real number for exactly these
    slots, same E-37 signal `engine.vfx.spawn_play_once` reads."""
    entries = {}
    for slot in slot_keys:
        raw = {
            "sheet": "imported/x.png", "frame_w": frame_w, "frame_h": frame_h,
            "offset_x": 0, "offset_y": 0,
            "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                      "loop_start": 0, "loop_end": 0, "loop_count": 1}],
        }
        entries[slot] = entry_from_dict(slot, raw)
    frame_sizes = {slot: (frame_w, frame_h) for slot in slot_keys}
    return AssetStore(manifest=Manifest(entries), sprites_dir=None,
                      frame_sizes=frame_sizes)


class TestProjectileFallbackDot(unittest.TestCase):
    """Test 6 (brief §4): with no art, `submit_projectiles` emits exactly
    today's `HudRect` stream (colour, size, lift, border_radius) built from
    the shipped JSON defaults, and the `max(2, ...)` floor still applies at
    low zoom."""

    def setUp(self):
        self.assertTrue(_shipped_defaults_are_unchanged(),
                        "vfx.json procedural.projectile defaults drifted — "
                        "update this test's expectations deliberately")

    def _fm(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        self.assertIsNone(fm.assets)   # bare-constructed: no art anywhere
        return fm

    def test_stone_dot_matches_shipped_defaults(self):
        fm = self._fm()
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        scene = FakeScene([make_shot("projectile", 3.0, 2.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        self.assertEqual(len(renderer.items), 1)
        item = renderer.items[0]
        self.assertIsInstance(item, HudRect)
        self.assertEqual(item.color, (185, 180, 170))
        size = item.rect[2]
        self.assertEqual(size, 3)          # stone_size=3 * zoom=1.0
        self.assertEqual(item.border_radius, size // 2)

        cx, cy = cs.world_to_screen(3.0, 2.0)
        lift = int(cs.geometry.tile_h * 1.0 * 0.6)
        self.assertEqual(item.rect[0], int(cx - size / 2))
        self.assertEqual(item.rect[1], int(cy - lift - size / 2))

    def test_shell_dot_matches_shipped_defaults(self):
        fm = self._fm()
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        scene = FakeScene([make_shot("shell", 5.0, 5.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        item = renderer.items[0]
        self.assertIsInstance(item, HudRect)
        self.assertEqual(item.color, (70, 60, 55))
        self.assertEqual(item.rect[2], 5)   # shell_size=5 * zoom=1.0

    def test_low_zoom_floor_still_applies(self):
        """`max(2, int(size * zoom))` — the degeneracy guard stays inline,
        not a schema tunable, and still floors a near-zero zoom to 2px."""
        fm = self._fm()
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 0.01
        scene = FakeScene([make_shot("projectile", 3.0, 2.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)
        self.assertEqual(renderer.items[0].rect[2], 2)


class TestProjectileSprite(unittest.TestCase):
    """Test 7 (brief §4): with a fixture sheet on `vfx_projectile`, a stone
    emits a `HudSprite`; a shell with art on `vfx_shell` emits its own; a
    shell with art only on `vfx_projectile` still falls back to its dot —
    the two slots are independent."""

    def test_stone_with_art_emits_hud_sprite(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_projectile")
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        scene = FakeScene([make_shot("projectile", 3.0, 2.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        self.assertEqual(len(renderer.items), 1)
        item = renderer.items[0]
        self.assertIsInstance(item, HudSprite)
        self.assertEqual(item.slot_key, "vfx_projectile")

    def test_shell_with_art_on_its_own_slot_emits_hud_sprite(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_shell")
        cs = load_coordinate_system(FIXTURE_DATA)
        scene = FakeScene([make_shot("shell", 5.0, 5.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        item = renderer.items[0]
        self.assertIsInstance(item, HudSprite)
        self.assertEqual(item.slot_key, "vfx_shell")

    def test_shell_falls_back_when_only_stone_slot_has_art(self):
        """The two slots are independent — art on `vfx_projectile` must not
        leak into `vfx_shell`'s decision."""
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_projectile")   # NOT vfx_shell
        cs = load_coordinate_system(FIXTURE_DATA)
        scene = FakeScene([make_shot("shell", 5.0, 5.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        item = renderer.items[0]
        self.assertIsInstance(item, HudRect)   # still the dot

    def test_stone_falls_back_when_only_shell_slot_has_art(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_shell")   # NOT vfx_projectile
        cs = load_coordinate_system(FIXTURE_DATA)
        scene = FakeScene([make_shot("projectile", 3.0, 2.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)

        item = renderer.items[0]
        self.assertIsInstance(item, HudRect)   # still the dot


class TestAssetsNoneDegrades(unittest.TestCase):
    """Test 8 (brief §4): a bare `FloaterManager` (assets=None, every test's
    default construction) emits dots and never raises."""

    def test_bare_construction_emits_dots_never_raises(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        self.assertIsNone(fm.assets)
        cs = load_coordinate_system(FIXTURE_DATA)
        scene = FakeScene([make_shot("projectile", 1.0, 1.0),
                           make_shot("shell", 2.0, 2.0)])
        renderer = RecordingRenderer()
        fm.submit_projectiles(renderer, cs, scene)   # must not raise
        self.assertEqual(len(renderer.items), 2)
        for item in renderer.items:
            self.assertIsInstance(item, HudRect)


if __name__ == "__main__":
    unittest.main()
