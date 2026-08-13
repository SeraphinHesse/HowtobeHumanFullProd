"""Digger underground telegraph (``FloaterManager.submit_digger_telegraphs``).

Two placeholder arrows over a burrowed Digger's CURRENT dig -- the only
visible trace of it while its sprite is hidden (``BurrowAgent.state ==
BURROW_SUBMERGED``): a marker hovering over the entry tile
(``start_wx``/``start_wy``) and a second arrow pointing at the segment's
destination (``dest_col``/``dest_row``). The ``submit_projectiles``/
``submit_buff_arrows`` swappable-art pattern: a ``HudSprite`` once an artist
imports art on ``vfx_digger_marker``/``vfx_digger_direction``, two small
``HudLines`` triangles otherwise. Both draw ONLY while submerged and alive,
alongside (never instead of) the existing dirt-pile decal.

Headless/pure: a real ``Digger`` built directly (no Scene/TileMap sim -- its
``BurrowAgent`` fields are set by hand to the scenario under test, the
``test_enemy_hp_bars.py`` ``make_enemy`` pattern), a recording renderer.
Never touches live ``data/`` -- the pinned ``FIXTURE_DATA`` snapshot only,
never written.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import Health
from engine.render import HudLines, HudSprite
from game.core import load_balance
from game.enemies.components import BURROW_SUBMERGED, BURROW_WALKING, BurrowAgent
from game.enemies.enemy import Digger
from game.ui.effects import (
    DIGGER_DIRECTION_SLOT, DIGGER_MARKER_SLOT, FloaterManager,
)

ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")


class _StubTileMap:
    """Enemies cache a tilemap ref; nothing here paths, so it stays inert."""
    balance = {}


class RecordingRenderer:
    def __init__(self, assets=None):
        self.items = []
        self.assets = assets

    def submit_hud(self, item):
        self.items.append(item)


class FakeScene:
    """``submit_digger_telegraphs`` only ever asks for ``by_tag("enemy")``."""

    def __init__(self, enemies):
        self._enemies = enemies

    def by_tag(self, tag):
        return [e for e in self._enemies if tag in e.tags]


def make_store_with_art(*slot_keys, frame_w=64, frame_h=64):
    """An AssetStore where every slot in ``slot_keys`` has one imported
    ``idle`` frame -- the same E-37 signal ``engine.vfx.spawn_play_once``
    reads (``test_projectile_sprites.py``'s helper)."""
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


def make_digger(col, row):
    return Digger(col, row, ENEMIES_BAL, _StubTileMap())


def make_submerged_digger(start=(5.0, 5.0), dest=(8, 5)):
    """A Digger whose ``BurrowAgent`` is hand-set to a submerged dig segment
    -- no Scene/TileMap simulation needed, exactly the scenario this pass
    reads."""
    dig = make_digger(int(start[0]), int(start[1]))
    burrow = dig.get_component(BurrowAgent)
    burrow.state = BURROW_SUBMERGED
    burrow.start_wx, burrow.start_wy = start
    burrow.dest_col, burrow.dest_row = dest
    return dig, burrow


def make_cs():
    cs = load_coordinate_system(FIXTURE_DATA)
    cs.camera.zoom = 1
    cs.camera.pan_x = cs.camera.pan_y = 0
    return cs


class TestOnlyDrawnWhileSubmergedAndAlive(unittest.TestCase):
    def _fm(self):
        return FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)

    def test_walking_digger_draws_nothing(self):
        dig = make_digger(5, 5)
        self.assertEqual(dig.get_component(BurrowAgent).state, BURROW_WALKING)
        renderer = RecordingRenderer()
        self._fm().submit_digger_telegraphs(
            renderer, make_cs(), FakeScene([dig]))
        self.assertEqual(renderer.items, [])

    def test_dead_digger_draws_nothing_even_if_submerged(self):
        dig, _burrow = make_submerged_digger()
        dig.get_component(Health).hp = 0
        self.assertFalse(dig.alive)
        renderer = RecordingRenderer()
        self._fm().submit_digger_telegraphs(
            renderer, make_cs(), FakeScene([dig]))
        self.assertEqual(renderer.items, [])

    def test_a_non_digger_enemy_is_ignored(self):
        """No ``BurrowAgent`` at all -- must not raise, must draw nothing."""
        from game.enemies.enemy import Enemy
        e = Enemy(5, 5, ENEMIES_BAL, _StubTileMap())
        self.assertIsNone(e.get_component(BurrowAgent))
        renderer = RecordingRenderer()
        self._fm().submit_digger_telegraphs(
            renderer, make_cs(), FakeScene([e]))
        self.assertEqual(renderer.items, [])


class TestFallbackTriangles(unittest.TestCase):
    """No imported art (every test's default ``assets=None``, like
    ``TestAssetsNoneDegrades`` in ``test_projectile_sprites.py``): two
    ``HudLines`` triangles, never a raise."""

    def test_no_art_draws_two_triangles(self):
        dig, _burrow = make_submerged_digger()
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        self.assertIsNone(fm.assets)
        renderer = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer, make_cs(), FakeScene([dig]))

        self.assertEqual(len(renderer.items), 2)
        for item in renderer.items:
            self.assertIsInstance(item, HudLines)
            self.assertEqual(len(item.points), 3)

    def test_marker_hovers_exactly_over_the_entry_tile(self):
        """The marker's apex sits directly under the entry tile's screen
        point (hand-computed from the same ``cs.world_to_screen`` the
        implementation uses) -- and moves when the entry tile does, never
        the destination."""
        dig, _burrow = make_submerged_digger(start=(5.0, 5.0), dest=(20, 5))
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        cs = make_cs()
        renderer = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer, cs, FakeScene([dig]))

        marker = renderer.items[0]
        cx, cy = cs.world_to_screen(5.5, 5.5)
        apex = marker.points[1]
        self.assertEqual(apex[0], int(cx))

        # A second Digger, same destination, a DIFFERENT entry tile -- the
        # marker follows the entry tile, not the (identical) destination.
        dig2, _b2 = make_submerged_digger(start=(9.0, 5.0), dest=(20, 5))
        renderer2 = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer2, cs, FakeScene([dig2]))
        cx2, _cy2 = cs.world_to_screen(9.5, 5.5)
        self.assertNotEqual(renderer2.items[0].points[1][0], apex[0])
        self.assertEqual(renderer2.items[0].points[1][0], int(cx2))

    def test_direction_arrow_rotates_toward_the_destination(self):
        """Two segments from the SAME entry tile toward opposite
        destinations must not draw the same (unrotated) chevron -- proof the
        fallback actually points somewhere, not a fixed shape."""
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        cs = make_cs()

        dig_a, _ba = make_submerged_digger(start=(10.0, 10.0), dest=(30, 10))
        renderer_a = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer_a, cs, FakeScene([dig_a]))

        dig_b, _bb = make_submerged_digger(start=(10.0, 10.0), dest=(10, 30))
        renderer_b = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer_b, cs, FakeScene([dig_b]))

        direction_a = renderer_a.items[1]
        direction_b = renderer_b.items[1]
        self.assertNotEqual(direction_a.points, direction_b.points)
        # The marker (over the shared entry tile) is unaffected by direction.
        self.assertEqual(renderer_a.items[0].points, renderer_b.items[0].points)

    def test_degenerate_same_tile_destination_never_raises(self):
        """``dest_col``/``dest_row`` equal to the entry tile (a zero-length
        segment) is a real, if unusual, state -- must degrade, never divide
        by zero."""
        dig, burrow = make_submerged_digger(start=(5.0, 5.0), dest=(5, 5))
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        renderer = RecordingRenderer()
        fm.submit_digger_telegraphs(renderer, make_cs(), FakeScene([dig]))
        self.assertEqual(len(renderer.items), 2)


class TestSwappableArt(unittest.TestCase):
    """With imported art on one or both slots: a ``HudSprite`` instead of
    the matching triangle, independently per slot (the ``vfx_projectile``/
    ``vfx_shell`` independence ``test_projectile_sprites.py`` pins)."""

    def test_both_slots_with_art_emit_two_hud_sprites(self):
        dig, _burrow = make_submerged_digger()
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        assets = make_store_with_art(DIGGER_MARKER_SLOT, DIGGER_DIRECTION_SLOT)
        renderer = RecordingRenderer(assets=assets)
        fm.submit_digger_telegraphs(renderer, make_cs(), FakeScene([dig]))

        self.assertEqual(len(renderer.items), 2)
        marker, direction = renderer.items
        self.assertIsInstance(marker, HudSprite)
        self.assertEqual(marker.slot_key, DIGGER_MARKER_SLOT)
        self.assertIsInstance(direction, HudSprite)
        self.assertEqual(direction.slot_key, DIGGER_DIRECTION_SLOT)

    def test_marker_art_alone_leaves_direction_on_the_fallback(self):
        dig, _burrow = make_submerged_digger()
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        assets = make_store_with_art(DIGGER_MARKER_SLOT)   # NOT direction
        renderer = RecordingRenderer(assets=assets)
        fm.submit_digger_telegraphs(renderer, make_cs(), FakeScene([dig]))

        marker, direction = renderer.items
        self.assertIsInstance(marker, HudSprite)
        self.assertIsInstance(direction, HudLines)

    def test_direction_art_alone_leaves_marker_on_the_fallback(self):
        dig, _burrow = make_submerged_digger()
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        assets = make_store_with_art(DIGGER_DIRECTION_SLOT)   # NOT marker
        renderer = RecordingRenderer(assets=assets)
        fm.submit_digger_telegraphs(renderer, make_cs(), FakeScene([dig]))

        marker, direction = renderer.items
        self.assertIsInstance(marker, HudLines)
        self.assertIsInstance(direction, HudSprite)


if __name__ == "__main__":
    unittest.main()
