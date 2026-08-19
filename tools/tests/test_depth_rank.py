"""VfxAuthoringPLAN VA-3: the depth-key rank, WorldRect/WorldLines, and
VfxSystem.submit_world.

The claim VA-3 has to earn is that it changes NOTHING until something opts in:
`depth_key` grew a fourth element, and every shipping caller passes its
default. `TestRankIsANoOpAtZero` is that argument, made against the pre-VA-3
3-tuple written out explicitly rather than against the function under test —
the tautology shape that let the ESV-6 anchor bug ship green.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random

from engine.coords import Camera, CoordinateSystem, Geometry
from engine.core import Transform
from engine.render import (
    LAYERS, HudLines, HudRect, HudSprite, HudText, OverlayLines, OverlayPolys,
    RenderItem, Renderer,
)
from engine import tilemap
from engine.vfx import BurstParams, SlashParams, VfxSystem

_HUD_TYPES = (HudRect, HudText, HudSprite, HudLines)


def make_cs(zoom=1.0):
    geo = Geometry(tile_w=64, tile_h=32, map_cols=20, map_rows=20,
                   zoom_levels=(0.5, 1.0, 2.0))
    return CoordinateSystem(geo, Camera(zoom=zoom))


class FakeAssets:
    #: {slot_key: {anchor_name: (x, y)}} — empty means "no sheet authors an
    #: anchor", the state every pre-depth_pivot test runs in.
    def __init__(self, anchors=None):
        self.anchors = dict(anchors or {})

    def frame(self, slot_key, animation="idle", anim_time_ms=0,
              extra_hidden=None, column=None):
        from engine.assets.types import Frame
        return Frame(surface=f"SURF:{slot_key}", frame_w=64, frame_h=32,
                     offset_x=0, offset_y=0, slice=None)

    def frame_size(self, slot_key):
        return (64, 32)

    def offset(self, slot_key):
        return (0, 0)

    def anchor(self, slot_key, name):
        return self.anchors.get(slot_key, {}).get(name)


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


# ===========================================================================
# depth_key
# ===========================================================================
class TestRankIsANoOpAtZero(unittest.TestCase):
    """A 4-tuple whose last element is constant sorts exactly as the 3-tuple
    did. Asserted against the OLD FORMULA WRITTEN OUT, never against
    depth_key itself."""

    @staticmethod
    def _pre_va3_key(wx, wy, layer_index=0):
        return (layer_index, wx + wy, wy)

    def test_a_representative_queue_sorts_identically(self):
        cs = make_cs()
        rng = random.Random(11)
        items = [(rng.uniform(0, 19), rng.uniform(0, 19), rng.randrange(5))
                 for _ in range(400)]
        self.assertEqual(
            sorted(items, key=lambda i: cs.depth_key(i[0], i[1], i[2])),
            sorted(items, key=lambda i: self._pre_va3_key(i[0], i[1], i[2])))

    def test_ties_still_fall_through_to_submission_order(self):
        """Two items at the same tile and the same rank must compare EQUAL,
        so Python's stable sort keeps submission order — the mechanism
        fix/depth-sorted-world-fills relies on."""
        cs = make_cs()
        self.assertEqual(cs.depth_key(3.0, 4.0, 2), cs.depth_key(3.0, 4.0, 2))


class TestRankBreaksAnExactTie(unittest.TestCase):
    def test_higher_rank_sorts_later(self):
        cs = make_cs()
        self.assertLess(cs.depth_key(3, 4, 2, -1), cs.depth_key(3, 4, 2, 0))
        self.assertLess(cs.depth_key(3, 4, 2, 0), cs.depth_key(3, 4, 2, +1))

    def test_iso_depth_still_beats_rank(self):
        """The whole reason rank is LAST: an effect on a near tile keeps
        drawing over a building on a far tile, whatever its rank says."""
        cs = make_cs()
        far_in_front = cs.depth_key(1, 1, 2, +1)
        near_behind = cs.depth_key(9, 9, 2, -1)
        self.assertLess(far_in_front, near_behind)

    def test_layer_still_beats_everything(self):
        """The ground cache depends on layer being primary — a rank must
        never lift an item out of its layer."""
        cs = make_cs()
        self.assertLess(cs.depth_key(19, 19, 0, +999),
                        cs.depth_key(0, 0, 1, -999))


# ===========================================================================
# WorldRect / WorldLines
# ===========================================================================
class TestWorldPixelPrimitives(unittest.TestCase):
    def _renderer(self):
        backend = RecordingBackend()
        return Renderer(make_cs(), FakeAssets(), backend=backend), backend

    def test_a_world_rect_resolves_to_a_screen_space_quad(self):
        r, backend = self._renderer()
        r.submit_world_rect((3.0, 4.0), (100, 50, 2, 3), (10, 20, 30))
        r.flush(target=None)
        call = backend.calls[-1]
        self.assertIsInstance(call, OverlayPolys)
        self.assertEqual(call.color, (10, 20, 30))
        self.assertEqual(call.points,
                         ((100, 50), (102, 50), (102, 53), (100, 53)))

    def test_the_rect_is_independent_of_zoom_and_of_the_depth_anchor(self):
        """The reason this exists rather than a WorldFill: a WorldFill's
        polygon is world-space and grows with zoom, which is wrong for a
        particle. world_pos moves where it SORTS, never where it draws."""
        seen = []
        for zoom in (0.5, 1.0, 2.0):
            for anchor in ((0.0, 0.0), (9.0, 9.0)):
                backend = RecordingBackend()
                r = Renderer(make_cs(zoom), FakeAssets(), backend=backend)
                r.submit_world_rect(anchor, (100, 50, 4, 6), (1, 2, 3))
                r.flush(target=None)
                seen.append(backend.calls[-1].points)
        self.assertEqual(len(set(seen)), 1, seen)

    def test_a_world_lines_resolves_to_its_screen_points(self):
        r, backend = self._renderer()
        r.submit_world_lines((2.0, 2.0), ((10, 10), (20, 20)), (9, 9, 9),
                             width=2)
        r.flush(target=None)
        call = backend.calls[-1]
        self.assertIsInstance(call, OverlayLines)
        self.assertEqual(call.points, ((10, 10), (20, 20)))
        self.assertEqual(call.width, 2)

    def test_neither_emits_a_HUD_primitive(self):
        """Load-bearing: backend_gpu raises NotImplementedError on every HUD
        primitive by design (D7), so a HudRect in the depth-sorted world list
        would crash the GPU host. This is why both resolve to overlay
        primitives."""
        r, backend = self._renderer()
        r.submit_world_rect((1.0, 1.0), (0, 0, 2, 2), (1, 2, 3))
        r.submit_world_lines((1.0, 1.0), ((0, 0), (1, 1)), (1, 2, 3))
        r.flush(target=None)
        for call in backend.calls:
            self.assertNotIsInstance(call, _HUD_TYPES)

    def test_rank_decides_a_same_tile_tie_against_a_sprite(self):
        r, backend = self._renderer()
        r.submit(RenderItem("bld", (3.0, 4.0)))            # rank 0
        r.submit_world_rect((3.0, 4.0), (0, 0, 2, 2), (1, 2, 3), rank=-1)
        r.flush(target=None)
        # The behind-ranked fill sorts FIRST despite being submitted second.
        self.assertIsInstance(backend.calls[0], OverlayPolys)

        backend.calls.clear()
        r.submit(RenderItem("bld", (3.0, 4.0)))
        r.submit_world_rect((3.0, 4.0), (0, 0, 2, 2), (1, 2, 3), rank=+1)
        r.flush(target=None)
        self.assertIsInstance(backend.calls[-1], OverlayPolys)

    def test_an_unknown_layer_is_refused(self):
        r, _ = self._renderer()
        with self.assertRaises(ValueError):
            r.submit_world_rect((0, 0), (0, 0, 1, 1), (1, 2, 3), layer="nope")
        with self.assertRaises(ValueError):
            r.submit_world_lines((0, 0), ((0, 0), (1, 1)), (1, 2, 3),
                                 layer="nope")

    def test_world_lines_needs_two_points(self):
        r, _ = self._renderer()
        with self.assertRaises(ValueError):
            r.submit_world_lines((0, 0), ((0, 0),), (1, 2, 3))


# ===========================================================================
# Transform.rank
# ===========================================================================
class TestTransformRank(unittest.TestCase):
    def test_it_defaults_to_zero_and_is_omitted_from_to_dict(self):
        """The manifest row_start/slice convention — an object that never
        opts in serializes byte-identically to before VA-3."""
        self.assertEqual(Transform(1.0, 2.0).to_dict(),
                         {"wx": 1.0, "wy": 2.0, "layer": "entities"})

    def test_a_non_zero_rank_round_trips(self):
        t = Transform(1.0, 2.0, rank=-1)
        self.assertEqual(t.to_dict()["rank"], -1)
        self.assertEqual(Transform.from_dict(t.to_dict()).rank, -1)

    def test_a_pre_va3_dict_still_loads(self):
        self.assertEqual(
            Transform.from_dict({"wx": 1.0, "wy": 2.0, "layer": "deco"}).rank,
            0)

    def test_a_sprite_carries_its_transforms_rank(self):
        from engine.core import SpriteAnimator
        anim = SpriteAnimator(slot_key="x")
        items = list(anim.render_items(Transform(1.0, 2.0, rank=-1)))
        self.assertEqual(items[0].rank, -1)


# ===========================================================================
# VfxSystem.submit_world
# ===========================================================================
_BURST = BurstParams(life=1.0, count=3, gravity=0.0,
                     ramp=((255, 0, 0), (0, 255, 0), (0, 0, 255)),
                     vx_min=-1.0, vx_max=1.0, vy_min=-1.0, vy_max=1.0,
                     size_w=2, size_h=3)
_SLASH = SlashParams(life=1.0, colors=((255, 255, 255),) * 3, lines_min=2,
                     lines_max=2, ox_min=-4.0, ox_max=4.0, oy_min=-4.0,
                     oy_max=4.0, size=6, size_large=12)


class _Params:
    slash = _SLASH


class _Capture:
    """Records both submit surfaces so the two passes can be compared."""

    def __init__(self):
        self.hud = []
        self.world_rects = []
        self.world_lines = []

    def submit_hud(self, item):
        self.hud.append(item)

    def submit_world_rect(self, world_pos, rect, color, layer="entities",
                          rank=0):
        self.world_rects.append((world_pos, rect, color, layer, rank))

    def submit_world_lines(self, world_pos, points, color, width=1,
                           closed=False, layer="entities", rank=0):
        self.world_lines.append((world_pos, points, color, layer, rank))


class TestSubmitWorldMatchesSubmitHud(unittest.TestCase):
    """The switch must not MOVE anything on screen — only change which pass
    it draws in. Same anchor, same zoom-scaled offsets, same quantization."""

    def _system(self):
        sys_ = VfxSystem(_Params(), rng=random.Random(5))
        sys_.emit_burst(_BURST, 3.0, 4.0)
        sys_.emit_slash(2.0, 2.0)
        return sys_

    def test_particle_geometry_is_identical_to_the_hud_pass(self):
        cs = make_cs()
        sys_ = self._system()
        hud_cap, world_cap = _Capture(), _Capture()
        sys_.submit_hud(hud_cap, cs)
        sys_.submit_world(world_cap, cs)

        hud_rects = [i for i in hud_cap.hud if isinstance(i, HudRect)]
        self.assertEqual(len(hud_rects), len(world_cap.world_rects))
        self.assertTrue(hud_rects, "the fixture must actually emit particles")
        for hud_item, (_wpos, rect, color, _layer, _rank) in zip(
                hud_rects, world_cap.world_rects):
            self.assertEqual(hud_item.rect, rect)
            self.assertEqual(hud_item.color, color)

    def test_slash_geometry_is_identical_to_the_hud_pass(self):
        cs = make_cs()
        sys_ = self._system()
        hud_cap, world_cap = _Capture(), _Capture()
        sys_.submit_hud(hud_cap, cs)
        sys_.submit_world(world_cap, cs)

        hud_lines = [i for i in hud_cap.hud if isinstance(i, HudLines)]
        self.assertEqual(len(hud_lines), len(world_cap.world_lines))
        self.assertTrue(hud_lines, "the fixture must actually emit a slash")
        for hud_item, (_wpos, points, color, _layer, _rank) in zip(
                hud_lines, world_cap.world_lines):
            self.assertEqual(hud_item.points, points)
            self.assertEqual(hud_item.color, color)

    def test_it_defaults_to_drawing_behind(self):
        """+1 in the depth queue and the HUD pass both put the effect on
        top, and the HUD pass is cheaper — so BEHIND is the only reason to
        call this, and the default says so."""
        sys_ = self._system()
        cap = _Capture()
        sys_.submit_world(cap, make_cs())
        self.assertTrue(cap.world_rects)
        for entry in cap.world_rects + cap.world_lines:
            self.assertEqual(entry[-1], -1)

    def test_the_rank_and_layer_are_passed_through(self):
        sys_ = self._system()
        cap = _Capture()
        sys_.submit_world(cap, make_cs(), rank=+1, layer="deco")
        self.assertTrue(cap.world_rects and cap.world_lines)
        for entry in cap.world_rects + cap.world_lines:
            self.assertEqual(entry[-1], +1)
            self.assertEqual(entry[-2], "deco")

    def test_submit_hud_still_emits_hud_primitives(self):
        """submit_world is an ALTERNATIVE, not a replacement — the always-on-
        top pass stays the default and must be untouched."""
        sys_ = self._system()
        cap = _Capture()
        sys_.submit_hud(cap, make_cs())
        self.assertTrue(cap.hud)
        self.assertEqual(cap.world_rects, [])
        self.assertEqual(cap.world_lines, [])



# ===========================================================================
# depth_pivot — feet-based Y-sorting (sort only, opt-in per sheet)
# ===========================================================================
class TestDepthPivot(unittest.TestCase):
    """A `depth_pivot` anchor moves where a sprite SORTS and nothing else."""

    def _order(self, assets, items):
        backend = RecordingBackend()
        r = Renderer(make_cs(), assets, backend=backend)
        for item in items:
            r.submit(item)
        r.flush(target=None)
        return [c.surface for c in backend.calls]

    def test_unauthored_sheets_sort_exactly_as_before(self):
        """The no-op proof: with no anchor authored anywhere, order is the
        old world_pos order, written out rather than taken from the renderer."""
        near = RenderItem("near", (5.0, 5.0))
        far = RenderItem("far", (2.0, 2.0))
        self.assertEqual(self._order(FakeAssets(), [near, far]),
                         ["SURF:far", "SURF:near"])

    def test_a_lower_pivot_draws_in_front_of_a_same_tile_sprite(self):
        """Both on the SAME tile, so world_pos alone ties and submission
        order would win. The pivot at the feet (+y is DOWN the frame) breaks
        the tie the way the art reads."""
        assets = FakeAssets({"feet": {"depth_pivot": (0, 24)}})
        # `feet` submitted FIRST: without the pivot the stable sort would
        # leave it behind `head`, so this can only pass via the pivot.
        order = self._order(assets, [RenderItem("feet", (4.0, 4.0)),
                                     RenderItem("head", (4.0, 4.0))])
        self.assertEqual(order, ["SURF:head", "SURF:feet"])

    def test_the_pivot_sorts_against_a_building_in_the_same_queue(self):
        """One shared queue: a pivoted enemy sorts against non-enemy sprites
        too, not only against other pivoted ones."""
        assets = FakeAssets({"enemy": {"depth_pivot": (0, 24)}})
        building = RenderItem("building", (4.4, 4.4))
        enemy = RenderItem("enemy", (4.0, 4.0))
        # Unpivoted, the enemy sits behind the building (4.0+4.0 < 4.4+4.4);
        # the pivot at its feet pushes it in front.
        self.assertEqual(self._order(FakeAssets(), [enemy, building]),
                         ["SURF:enemy", "SURF:building"])
        self.assertEqual(self._order(assets, [enemy, building]),
                         ["SURF:building", "SURF:enemy"])

    def test_the_pivot_never_moves_the_blit(self):
        """Sort only: the DrawCall dest/size for a pivoted sprite is
        byte-identical to the same sprite with no anchor authored."""
        item = RenderItem("e", (3.0, 7.0))
        plain = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=plain)
        r.submit(item)
        r.flush(target=None)
        pivoted = RecordingBackend()
        r2 = Renderer(make_cs(), FakeAssets({"e": {"depth_pivot": (7, 24)}}),
                      backend=pivoted)
        r2.submit(item)
        r2.flush(target=None)
        self.assertEqual([(c.dest, c.size) for c in plain.calls],
                         [(c.dest, c.size) for c in pivoted.calls])

    def test_a_non_entities_layer_ignores_the_pivot(self):
        """Layer stays primary and only `entities` is depth-contested — a
        deco sprite that happens to author the anchor sorts at its tile."""
        assets = FakeAssets({"a": {"depth_pivot": (0, 240)}})
        order = self._order(assets, [RenderItem("a", (2.0, 2.0), layer="deco"),
                                     RenderItem("b", (5.0, 5.0), layer="deco")])
        self.assertEqual(order, ["SURF:a", "SURF:b"])

    def test_deco_y_sorts_against_an_enemy_instead_of_covering_it(self):
        """fix/y-sorted-deco — THE reported bug, pinned end to end.

        An enemy standing a full tile IN FRONT of a tree used to draw behind
        it: the tree rode the `deco` layer, and layer beats iso depth, so the
        occlusion was unconditional. Both now ride `entities`, so the near
        one wins and the far one loses — the same queue, both ways round."""
        assets = FakeAssets()
        tree = RenderItem("tree", (4.0, 4.0),
                          layer=tilemap.DECO_LAYER, rank=tilemap.DECO_RANK)
        in_front = RenderItem("enemy", (5.0, 5.0))
        behind = RenderItem("enemy", (3.0, 3.0))
        self.assertEqual(self._order(assets, [in_front, tree]),
                         ["SURF:tree", "SURF:enemy"])
        self.assertEqual(self._order(assets, [behind, tree]),
                         ["SURF:enemy", "SURF:tree"])

    def test_deco_loses_an_exact_same_tile_tie_to_the_unit_on_it(self):
        """`DECO_RANK` is the last word on an exact depth tie: a unit standing
        ON a deco tile draws in FRONT of it, whichever order the two emitters
        happened to submit in."""
        assets = FakeAssets()
        tree = RenderItem("tree", (4.0, 4.0),
                          layer=tilemap.DECO_LAYER, rank=tilemap.DECO_RANK)
        unit = RenderItem("enemy", (4.0, 4.0))
        self.assertEqual(self._order(assets, [tree, unit]),
                         ["SURF:tree", "SURF:enemy"])
        self.assertEqual(self._order(assets, [unit, tree]),   # submission order
                         ["SURF:tree", "SURF:enemy"])         # must not matter

    def test_the_order_does_not_depend_on_zoom(self):
        """`sprite_anchor_screen` multiplies zoom in and `screen_to_world`
        divides it back out, so a pivoted queue sorts the same at every
        zoom level."""
        assets = FakeAssets({"feet": {"depth_pivot": (0, 24)}})
        items = [RenderItem("feet", (4.0, 4.0)), RenderItem("head", (4.0, 4.0))]
        orders = []
        for zoom in (0.5, 1.0, 2.0):
            backend = RecordingBackend()
            r = Renderer(make_cs(zoom), assets, backend=backend)
            for item in items:
                r.submit(item)
            r.flush(target=None)
            orders.append([c.surface for c in backend.calls])
        self.assertEqual(orders[0], orders[1])
        self.assertEqual(orders[1], orders[2])


if __name__ == "__main__":
    unittest.main()
