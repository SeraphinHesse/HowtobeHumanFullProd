"""Phase 1 acceptance tests for engine/render (E-20..E-26).

Ordering/anchoring is tested pure (fake assets + recording backend);
the end-to-end test renders headlessly via SDL dummy drivers.
"""
import os
import subprocess
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pathlib

from engine.assets.types import Frame
from engine.coords import Camera, CoordinateSystem, Geometry
from engine.render import (
    LAYERS, HudSprite, OverlayLines, RenderItem, Renderer, block_center_offset,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


def make_cs(**camera):
    geo = Geometry(
        tile_w=64, tile_h=32, map_cols=20, map_rows=20, zoom_levels=(0.5, 1.0, 2.0)
    )
    # Pin the test camera to zoom 1 explicitly rather than relying on
    # Camera's dataclass default (now 2.0, the new game/editor default) —
    # these tests assert render math at a known zoom.
    camera.setdefault("zoom", 1.0)
    return CoordinateSystem(geo, Camera(**camera))


class FakeAssets:
    """Resolves every slot to a token 'surface' so tests stay pygame-free."""

    def __init__(self, sizes=None, default=(64, 32), offsets=None, slices=None):
        self.sizes = sizes or {}
        self.default = default
        self.offsets = offsets or {}
        self.slices = slices or {}

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None):
        w, h = self.sizes.get(slot_key, self.default)
        offset_x, offset_y = self.offsets.get(slot_key, (0, 0))
        return Frame(surface=f"SURF:{slot_key}", frame_w=w, frame_h=h,
                     offset_x=offset_x, offset_y=offset_y,
                     slice=self.slices.get(slot_key))


def old_anchor_dest(px, py, frame_w, frame_h, zoom=1.0, tile_h=32):
    """The pre-ER-1 two-branch anchor, kept verbatim as the pixel-pin oracle:
    a frame taller than the tile anchored one extra tile-height lower."""
    w, h = frame_w * zoom, frame_h * zoom
    anchor = tile_h * (2 if frame_h > tile_h else 1)
    return (px - w / 2, py + anchor * zoom - h)


def only_call(renderer, backend, item):
    renderer.submit(item)
    renderer.flush(target=None)
    return backend.calls[-1]


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


class TestLayerAndDepthOrder(unittest.TestCase):
    """E-26 layer order ground→entities→deco→overlay; E-21/E-4 iso sort within."""

    def test_named_layer_order(self):
        self.assertEqual(
            LAYERS, ("ground", "terrain", "entities", "deco", "overlay"))

    def test_draw_order(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit(RenderItem("ovl", (0, 0), layer="overlay"))
        r.submit(RenderItem("deco", (0, 0), layer="deco"))
        r.submit(RenderItem("ent_far", (3, 3), layer="entities"))
        r.submit(RenderItem("ent_near", (2, 2), layer="entities"))
        r.submit(RenderItem("tile", (5, 5), layer="ground"))
        count = r.flush(target=None)
        self.assertEqual(count, 5)
        drawn = [c.surface for c in backend.calls]
        self.assertEqual(
            drawn, ["SURF:tile", "SURF:ent_near", "SURF:ent_far", "SURF:deco", "SURF:ovl"]
        )

    def test_flush_clears_queue(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        r.flush(target=None)
        self.assertEqual(r.flush(target=None), 0)
        self.assertEqual(len(backend.calls), 1)

    def test_unknown_layer_rejected(self):
        r = Renderer(make_cs(), FakeAssets(), backend=RecordingBackend())
        with self.assertRaises(ValueError):
            r.submit(RenderItem("tile", (0, 0), layer="hud"))


class TestAnchoring(unittest.TestCase):
    """Blit anchor: bottom edge on the tile-diamond bottom, centred horizontally."""

    def test_ground_tile_anchor(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        r.flush(target=None)
        call = backend.calls[0]
        self.assertEqual(call.dest, (-32.0, 0.0))
        self.assertEqual(call.size, (64.0, 32.0))

    def test_tall_entity_anchor(self):
        backend = RecordingBackend()
        r = Renderer(
            make_cs(), FakeAssets(sizes={"ent": (64, 96)}), backend=backend
        )
        r.submit(RenderItem("ent", (1, 1), layer="entities"))
        r.flush(target=None)
        call = backend.calls[0]
        # world (1,1) → screen (0, 32); a frame taller than the tile anchors one
        # extra tile-height lower (bottom at 32 + 2·32 = 96), so the centred
        # figure sits ON the tile — the prototype building-sheet convention.
        self.assertEqual(call.dest, (-32.0, 0.0))
        self.assertEqual(call.size, (64.0, 96.0))

    def test_zoom_scales_dest_and_size(self):
        backend = RecordingBackend()
        cs = make_cs()
        cs.set_zoom(2.0)
        r = Renderer(cs, FakeAssets(), backend=backend)
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        r.flush(target=None)
        call = backend.calls[0]
        self.assertEqual(call.dest, (-64.0, 0.0))
        self.assertEqual(call.size, (128.0, 64.0))

    def test_anchor_is_continuous_across_the_old_32px_cliff(self):
        """ER-1 D3: the frame's centre sits on the tile diamond's centre, so
        dest_y falls smoothly with frame_h. The old two-branch rule jumped a
        whole tile_h (32px) between frame_h 32 and 33."""
        backend = RecordingBackend()
        r = Renderer(
            make_cs(),
            FakeAssets(sizes={f"h{h}": (64, h) for h in range(1, 129)}),
            backend=backend,
        )
        for h in range(1, 129):
            r.submit(RenderItem(f"h{h}", (0, 0), layer="entities"))
        r.flush(target=None)
        ys = [c.dest[1] for c in backend.calls]
        self.assertEqual(len(ys), 128)
        for previous, current in zip(ys, ys[1:]):
            self.assertLessEqual(current, previous)          # monotone
            self.assertLessEqual(previous - current, 1.0)    # no cliff

    def test_non_enemy_world_frames_are_pixel_identical_to_the_old_rule(self):
        """The D3 safety proof: at fit_tiles=0/scale=1 every frame size that
        actually ships for a tile / building / deco / core sheet (32 or 96
        tall) lands byte-identically on the old two-branch formula."""
        sizes = {"tile": (64, 32), "building": (64, 96),
                 "wide_building": (68, 96), "boss_sheet": (124, 96)}
        for zoom in (1.0, 2.0):
            for slot, (fw, fh) in sizes.items():
                backend = RecordingBackend()
                cs = make_cs()
                cs.set_zoom(zoom)
                r = Renderer(cs, FakeAssets(sizes=sizes), backend=backend)
                call = only_call(r, backend, RenderItem(slot, (2, 3)))
                px, py = cs.world_to_screen(2, 3)
                with self.subTest(slot=slot, zoom=zoom):
                    self.assertEqual(
                        call.dest, old_anchor_dest(px, py, fw, fh, zoom))
                    self.assertEqual(call.size, (fw * zoom, fh * zoom))


class TestFootprintFit(unittest.TestCase):
    """ER-1 D2: an item with fit_tiles > 0 is DOWNSCALED to span at most
    fit_tiles tiles horizontally; `scale` multiplies on top. Never upscaled."""

    def render(self, sizes, item, **kwargs):
        backend = RecordingBackend()
        cs = make_cs()
        r = Renderer(cs, FakeAssets(sizes=sizes, **kwargs), backend=backend)
        return only_call(r, backend, item)

    def test_oversized_boss_sheet_shrinks_to_one_tile_wide(self):
        # The bug ER-1 exists to fix: a 124x96 boss sheet overflowed its tile.
        call = self.render({"boss": (124, 96)},
                           RenderItem("boss", (0, 0), fit_tiles=1.0))
        self.assertAlmostEqual(call.size[0], 64.0)
        self.assertAlmostEqual(call.size[1], 96.0 * (64.0 / 124.0))

    def test_two_tile_footprint_fits_a_128_sheet_exactly(self):
        call = self.render({"form": (128, 128)},
                           RenderItem("form", (0, 0), fit_tiles=2.0))
        self.assertEqual(call.size, (128.0, 128.0))

    def test_small_frame_is_never_upscaled(self):
        call = self.render({"tiny": (16, 16)},
                           RenderItem("tiny", (0, 0), fit_tiles=1.0))
        self.assertEqual(call.size, (16.0, 16.0))

    def test_scale_is_the_knob_for_low_res_art(self):
        call = self.render({"tiny": (16, 16)},
                           RenderItem("tiny", (0, 0), fit_tiles=1.0, scale=2.0))
        self.assertEqual(call.size, (32.0, 32.0))

    def test_scale_applies_without_a_fit(self):
        call = self.render({"ent": (64, 96)},
                           RenderItem("ent", (0, 0), scale=0.5))
        self.assertEqual(call.size, (32.0, 48.0))

    def test_fit_keeps_the_frame_centred_on_the_tile(self):
        call = self.render({"boss": (124, 96)},
                           RenderItem("boss", (0, 0), fit_tiles=1.0))
        w, h = call.size
        self.assertAlmostEqual(call.dest[0], -w / 2)      # centred on (0,0)
        self.assertAlmostEqual(call.dest[1], 16.0 - h / 2)  # on the tile centre

    def test_a_two_tile_unit_draws_on_its_block_centre_not_its_anchor(self):
        # ER-5: a footprint-N unit is ADDRESSED by its anchor (the block's min
        # corner) but must DRAW on the block's centre — (N-1)/2 tiles along both
        # axes. In iso that cancels horizontally and drops it (N-1)*tile_h/2.
        anchor = self.render({"form": (128, 128)},
                             RenderItem("form", (0, 0), fit_tiles=1.0))
        block = self.render({"form": (128, 128)},
                            RenderItem("form", (0, 0), fit_tiles=2.0))
        self.assertAlmostEqual(block.dest[0] + block.size[0] / 2,
                               anchor.dest[0] + anchor.size[0] / 2)  # no x shift
        centre_of = lambda c: c.dest[1] + c.size[1] / 2
        self.assertAlmostEqual(centre_of(block) - centre_of(anchor), 16.0)

    def test_a_three_tile_unit_drops_a_full_tile_height(self):
        two = self.render({"big": (64, 64)},
                          RenderItem("big", (0, 0), fit_tiles=2.0))
        three = self.render({"big": (64, 64)},
                            RenderItem("big", (0, 0), fit_tiles=3.0))
        centre_of = lambda c: c.dest[1] + c.size[1] / 2
        self.assertAlmostEqual(centre_of(three) - centre_of(two), 16.0)
        self.assertAlmostEqual(three.dest[0] + three.size[0] / 2,
                               two.dest[0] + two.size[0] / 2)

    def test_one_tile_and_no_fit_do_not_move(self):
        # The whole safety argument for the block-centre shift: it is a provable
        # no-op at fit_tiles 1, and gated off entirely at 0 — so buildings, tiles,
        # deco and every 1-tile enemy are untouched.
        self.assertEqual(block_center_offset(0.0), 0.0)
        self.assertEqual(block_center_offset(1.0), 0.0)
        self.assertEqual(block_center_offset(2.0), 0.5)
        one = self.render({"e": (64, 96)}, RenderItem("e", (2, 3), fit_tiles=1.0))
        none = self.render({"e": (64, 96)}, RenderItem("e", (2, 3)))
        self.assertEqual(one.dest, none.dest)

    def test_defaults_are_todays_behaviour(self):
        plain = self.render({"ent": (64, 96)}, RenderItem("ent", (1, 1)))
        item = RenderItem("ent", (1, 1))
        self.assertEqual((item.fit_tiles, item.scale), (0.0, 1.0))
        self.assertEqual(plain.dest, (-32.0, 0.0))
        self.assertEqual(plain.size, (64.0, 96.0))

    def test_manifest_offsets_nudge_and_ride_the_scale(self):
        sizes = {"ent": (64, 96)}
        offsets = {"ent": (4, -6)}
        plain = self.render(sizes, RenderItem("ent", (0, 0)), offsets=offsets)
        self.assertEqual(plain.dest, (-32.0 + 4, 16.0 - 48.0 - 6))

        halved = self.render(sizes, RenderItem("ent", (0, 0), scale=0.5),
                             offsets=offsets)
        self.assertEqual(halved.dest, (-16.0 + 4 * 0.5, 16.0 - 24.0 - 6 * 0.5))


class TestOverlayLines(unittest.TestCase):
    """E-24 overlay primitive (Phase 6): world-space polylines drawn after
    every sprite call, converted through the coords authority."""

    def test_overlay_draws_after_all_sprites(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit_overlay_lines(((0, 0), (5, 0)), color=(255, 0, 0))
        r.submit(RenderItem("ovl", (0, 0), layer="overlay"))
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        self.assertEqual(r.flush(target=None), 3)
        self.assertNotIsInstance(backend.calls[0], OverlayLines)
        self.assertNotIsInstance(backend.calls[1], OverlayLines)
        self.assertIsInstance(backend.calls[2], OverlayLines)

    def test_points_convert_via_world_to_screen(self):
        backend = RecordingBackend()
        cs = make_cs()
        r = Renderer(cs, FakeAssets(), backend=backend)
        world = ((0, 0), (3, 1), (2.5, 2.5))
        r.submit_overlay_lines(world, color=(0, 255, 0), width=2, closed=True)
        r.flush(target=None)
        call = backend.calls[0]
        self.assertEqual(
            call.points, tuple(cs.world_to_screen(*p) for p in world))
        self.assertEqual(call.color, (0, 255, 0))
        self.assertEqual(call.width, 2)
        self.assertTrue(call.closed)

    def test_flush_clears_overlay_queue(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit_overlay_lines(((0, 0), (1, 1)), color=(1, 2, 3))
        r.flush(target=None)
        self.assertEqual(r.flush(target=None), 0)
        self.assertEqual(len(backend.calls), 1)

    def test_too_few_points_rejected(self):
        r = Renderer(make_cs(), FakeAssets(), backend=RecordingBackend())
        with self.assertRaises(ValueError):
            r.submit_overlay_lines(((0, 0),), color=(255, 255, 255))

    def test_real_backend_draws_lines(self):
        import pygame

        pygame.init()
        from engine.assets.store import AssetStore

        cs = make_cs()
        cs.pan(-320, -100)
        r = Renderer(cs, AssetStore())
        world = ((0, 0), (8, 0), (8, 8))
        r.submit_overlay_lines(world, color=(255, 0, 255))
        target = pygame.Surface((640, 480))
        target.fill((0, 0, 0))
        r.flush(target)
        for p in world:  # every vertex pixel carries the line color
            px, py = cs.world_to_screen(*p)
            self.assertEqual(
                target.get_at((round(px), round(py)))[:3], (255, 0, 255))


class TestHeadlessRender(unittest.TestCase):
    """E-21/E-22/E-23: real pipeline, real backend, SDL dummy target surface."""

    def test_grid_of_unassigned_tiles_renders_nonempty(self):
        import pygame

        pygame.init()
        from engine.assets.store import AssetStore

        cs = make_cs()
        cs.pan(-320, -100)  # bring tile (0,0) to screen (320, 100)
        renderer = Renderer(cs, AssetStore())
        for row in range(8):
            for col in range(8):
                renderer.submit(RenderItem("tile", (col, row), layer="ground"))
        target = pygame.Surface((640, 480))
        target.fill((0, 0, 0))
        self.assertEqual(renderer.flush(target), 64)

        px, py = cs.world_to_screen(4, 4)
        sample = target.get_at((round(px), round(py) + 16))
        self.assertNotEqual(sample[:3], (0, 0, 0))
        touched = sum(
            1
            for x in range(0, 640, 16)
            for y in range(0, 480, 16)
            if target.get_at((x, y))[:3] != (0, 0, 0)
        )
        self.assertGreater(touched, 0)

    def test_missing_asset_never_raises(self):
        import pygame

        pygame.init()
        from engine.assets.store import AssetStore

        renderer = Renderer(make_cs(), AssetStore())
        renderer.submit(RenderItem("no_such_slot_ever", (1, 1), layer="entities"))
        renderer.flush(pygame.Surface((64, 64)))  # must not raise (E-23)


class TestBackendThroughput(unittest.TestCase):
    """Scaled-frame cache + batched blits (perf) must not change pixels."""

    def test_scaled_cache_reuses_scale(self):
        import pygame
        from engine.render import backend
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        src = pygame.Surface((8, 8), pygame.SRCALPHA)
        src.fill((10, 200, 30, 255))
        # Three draws of the SAME surface at the SAME size -> one scale, reused.
        calls = [DrawCall(surface=src, dest=(i * 4, 0), size=(16, 16))
                 for i in range(3)]
        real_scale = pygame.transform.scale
        count = {"n": 0}

        def counting_scale(surface, size):
            count["n"] += 1
            return real_scale(surface, size)

        pygame.transform.scale = counting_scale
        try:
            backend.draw(pygame.Surface((64, 64)), calls)
        finally:
            pygame.transform.scale = real_scale
        self.assertEqual(count["n"], 1, "same (surface,size) must scale once")

    def test_batch_equals_per_blit(self):
        import pygame
        from engine.render import backend
        from engine.render import OverlayLines
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        src = pygame.Surface((8, 8), pygame.SRCALPHA)
        src.fill((200, 40, 40, 255))
        calls = [
            DrawCall(surface=src, dest=(2, 3), size=(8, 8)),
            DrawCall(surface=src, dest=(30, 3), size=(16, 16)),
            OverlayLines(points=((1, 1), (40, 1)), color=(0, 255, 0), width=2),
            DrawCall(surface=src, dest=(10, 30), size=(8, 8), flip=True),
        ]
        via_backend = pygame.Surface((64, 64))
        via_backend.fill((0, 0, 0))
        backend.draw(via_backend, calls)

        # Reference: exactly the old per-call semantics, one blit at a time.
        ref = pygame.Surface((64, 64))
        ref.fill((0, 0, 0))
        for c in calls:
            if isinstance(c, OverlayLines):
                pts = [(round(x), round(y)) for x, y in c.points]
                pygame.draw.lines(ref, c.color, c.closed, pts, c.width)
                continue
            surf = c.surface
            size = (max(1, round(c.size[0])), max(1, round(c.size[1])))
            if size != surf.get_size():
                surf = pygame.transform.scale(surf, size)
            if c.flip:
                surf = pygame.transform.flip(surf, True, False)
            ref.blit(surf, (round(c.dest[0]), round(c.dest[1])))
        self.assertEqual(pygame.image.tobytes(via_backend, "RGB"),
                         pygame.image.tobytes(ref, "RGB"))

    def test_placeholder_surfaces_do_not_leak(self):
        import gc as _gc
        import pygame
        from engine.render import backend
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        target = pygame.Surface((64, 64))
        for _ in range(50):  # each a fresh surface, like the grey-X placeholder
            fresh = pygame.Surface((8, 8), pygame.SRCALPHA)
            backend.draw(target, [DrawCall(surface=fresh, dest=(0, 0), size=(16, 16))])
        _gc.collect()
        self.assertLessEqual(len(backend._scale_cache), 1,
                             "transient surfaces must evict from the scale cache")


class TestNineSliceThrough(unittest.TestCase):
    """A2: the manifest's slice margins ride Frame -> DrawCall for HUD sprites
    only. Nothing between the manifest and the backend interprets them."""

    def assets(self):
        return FakeAssets(sizes={"btn": (16, 16)},
                          slices={"btn": (2, 2, 2, 2)})

    def test_hud_sprite_drawcall_carries_slice(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), self.assets(), backend=backend)
        r.submit_hud(HudSprite("btn", (0, 0), (64, 32)))
        r.flush(target=None)
        self.assertEqual(backend.calls[0].slice, (2, 2, 2, 2))

    def test_world_sprite_drawcall_never_sets_slice(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), self.assets(), backend=backend)
        r.submit(RenderItem("btn", (0, 0)))   # same slot, world path
        r.flush(target=None)
        self.assertIsNone(backend.calls[0].slice,
                          "world sprites keep uniform zoom scaling")

    def test_unsliced_hud_sprite_has_no_slice(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(sizes={"icon": (16, 16)}),
                     backend=backend)
        r.submit_hud(HudSprite("icon", (0, 0), (16, 16)))
        r.flush(target=None)
        self.assertIsNone(backend.calls[0].slice)


class TestCropThrough(unittest.TestCase):
    """feature-enemy-intro-dialogue: HudSprite.crop -> DrawCall.crop_rect and
    HudSprite.hidden_frames -> assets.frame(extra_hidden=...), HUD only,
    mirroring TestNineSliceThrough's shape for `slice`."""

    def assets(self):
        return FakeAssets(sizes={"btn": (64, 64)})

    def test_hud_sprite_drawcall_carries_crop_rect(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), self.assets(), backend=backend)
        r.submit_hud(HudSprite("btn", (0, 0), (32, 32), crop=(4, 4, 16, 16)))
        r.flush(target=None)
        self.assertEqual(backend.calls[0].crop_rect, (4, 4, 16, 16))

    def test_uncropped_hud_sprite_has_no_crop_rect(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), self.assets(), backend=backend)
        r.submit_hud(HudSprite("btn", (0, 0), (32, 32)))
        r.flush(target=None)
        self.assertIsNone(backend.calls[0].crop_rect)

    def test_world_sprite_drawcall_never_sets_crop_rect(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), self.assets(), backend=backend)
        r.submit(RenderItem("btn", (0, 0)))   # same slot, world path
        r.flush(target=None)
        self.assertIsNone(backend.calls[0].crop_rect)

    def test_hidden_frames_reach_assets_frame_as_extra_hidden(self):
        recording = RecordingAssetsWithHidden()
        backend = RecordingBackend()
        r = Renderer(make_cs(), recording, backend=backend)
        r.submit_hud(HudSprite("btn", (0, 0), (32, 32), hidden_frames=(1, 3)))
        r.flush(target=None)
        self.assertEqual(recording.last_extra_hidden, {1, 3})

    def test_empty_hidden_frames_passes_none_not_empty_tuple(self):
        # An empty tuple is the HudSprite default (no per-entry narrowing) —
        # `renderer.py` passes `hud.hidden_frames or None`, never `()`, so a
        # falsy-but-truthiness-sensitive extra_hidden consumer sees "absent".
        recording = RecordingAssetsWithHidden()
        r = Renderer(make_cs(), recording, backend=RecordingBackend())
        r.submit_hud(HudSprite("btn", (0, 0), (32, 32)))
        r.flush(target=None)
        self.assertIsNone(recording.last_extra_hidden)


class RecordingAssetsWithHidden(FakeAssets):
    """FakeAssets that also records the `extra_hidden` it was asked for."""

    def __init__(self):
        super().__init__(sizes={"btn": (64, 64)})
        self.last_extra_hidden = None

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None):
        self.last_extra_hidden = set(extra_hidden) if extra_hidden else extra_hidden
        return super().frame(slot_key, animation, anim_time_ms)


class TestCropBackend(unittest.TestCase):
    """`backend._cropped`: pixel-correct sub-rect, clamped so an
    out-of-bounds crop degrades instead of raising (E-37), sharing the
    `_scale_cache`'s weak eviction like `_nine_patch`."""

    def test_crop_selects_the_right_sub_rect(self):
        import pygame
        from engine.render import backend
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        src = pygame.Surface((64, 64), pygame.SRCALPHA)
        pygame.draw.rect(src, (255, 0, 0, 255), (0, 0, 32, 32))
        pygame.draw.rect(src, (0, 255, 0, 255), (32, 32, 32, 32))
        target = pygame.Surface((64, 64))
        backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=(10, 10),
                                       crop_rect=(32, 32, 32, 32))])
        self.assertEqual(target.get_at((5, 5))[:3], (0, 255, 0))

    def test_out_of_bounds_crop_clamps_instead_of_raising(self):
        import pygame
        from engine.render import backend
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        src = pygame.Surface((32, 32), pygame.SRCALPHA)
        target = pygame.Surface((64, 64))
        backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=(10, 10),
                                       crop_rect=(9999, 9999, 9999, 9999))])
        backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=(10, 10),
                                       crop_rect=(0, 0, 0, 0))])
        backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=(10, 10),
                                       crop_rect=(-5, -5, 20, 20))])

    def test_crop_result_shares_the_weak_scale_cache(self):
        import pygame
        from engine.render import backend
        from engine.render.item import DrawCall

        backend._scale_cache.clear()
        src = pygame.Surface((32, 32), pygame.SRCALPHA)
        target = pygame.Surface((64, 64))
        for _ in range(3):
            backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=(10, 10),
                                           crop_rect=(4, 4, 8, 8))])
        # One crop cache entry keyed on `src`, reused across all three draws —
        # never leaks a growing set of surfaces per call.
        self.assertIn(src, backend._scale_cache)
        self.assertEqual(len(backend._scale_cache[src]), 1)


class TestPixelQuantizer(unittest.TestCase):
    """JitteryMapFix: the backend's pixel quantizer breaks .5 ties UP, never
    half-to-even — banker's rounding made two dests both ending in .5 land on
    different pixels, and a pan crossing a tie double-step 2px per item."""

    def test_half_up_ties(self):
        from engine.render.item import round_half_up
        self.assertEqual(round_half_up(0.5), 1)
        self.assertEqual(round_half_up(1.5), 2)   # round() gives 2 too
        self.assertEqual(round_half_up(2.5), 3)   # round() gives 2 — the bug
        self.assertEqual(round_half_up(-0.5), 0)
        self.assertEqual(round_half_up(3.2), 3)
        self.assertEqual(round_half_up(3.7), 4)


class TestPurity(unittest.TestCase):
    """Hard rule: coords / data_io / render orchestration / asset metadata
    import no pygame."""

    def test_pure_modules_do_not_import_pygame(self):
        code = (
            "import sys; "
            "import engine.coords, engine.data_io, engine.render, engine.assets, "
            "engine.assets.manifest, engine.assets.registry, engine.tilemap; "
            "assert 'pygame' not in sys.modules, 'pygame leaked into pure modules'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


class TestBackendResolution(unittest.TestCase):
    """G1: default backend resolution is unchanged when nothing is injected —
    the explicit `backend_api.default_backend()` seam must still resolve to
    the same callable, at the same time (first flush), memoised the same way."""

    def test_default_backend_is_the_pygame_draw_function(self):
        from engine.render import backend, default_backend

        self.assertIs(default_backend(), backend.draw)

    def test_unspecified_backend_resolves_lazily_and_memoises(self):
        import pygame
        from engine.assets.store import AssetStore
        from engine.render import backend

        pygame.init()
        r = Renderer(make_cs(), AssetStore())
        self.assertIsNone(r._backend)
        r.submit(RenderItem("no_such_slot_ever", (0, 0), layer="ground"))
        r.flush(target=pygame.Surface((16, 16)))
        self.assertIs(r._backend, backend.draw)

    def test_injected_backend_is_never_replaced(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        r.flush(target=None)
        self.assertIs(r._backend, backend)
        self.assertEqual(len(backend.calls), 1)


if __name__ == "__main__":
    unittest.main()
