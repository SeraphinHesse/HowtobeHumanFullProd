"""G2 — `engine/render/backend_gpu.py` vs the Surface backend, pixel parity.

`backend.py` is the pin: the same DrawCall list is drawn onto a
`pygame.Surface` and onto a `pygame._sdl2.video.Renderer`, and the readback is
compared per channel.

This is a NORMAL CI module — no live-only marker, no skip, no env gate. The
`SDL_VIDEODRIVER=dummy` driver the whole suite already runs under is measured
to host Window + Renderer + Texture.from_surface + draw + to_surface readback
(GpuAndMasterSheetsPLAN §4). Every surface here is built in-process; nothing
reads or writes `data/`.
"""
import gc
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from pygame import Surface
from pygame._sdl2.video import Renderer, Texture, Window

from engine.render import backend, backend_gpu
from engine.render.hud import HudRect
from engine.render.item import DrawCall, OverlayLines, OverlayPolys

W, H = 200, 160
BG = (30, 40, 50)

# Max allowed per-channel |CPU - GPU| difference.
#
# NOT zero, and deliberately not widened past what was measured. SDL's scaler
# and blender are not guaranteed bit-identical to pygame.transform.scale /
# Surface.blit (GpuAndMasterSheetsPLAN lines 805-809). MEASURED on this
# fixture scene with pygame-ce 2.5.7 / SDL 2.32.10: max delta 1, on 1234 of
# 32000 pixels, ALL of them inside the alpha < 255 OverlayPolys — i.e. a
# one-ULP difference in the alpha-blend rounding, not a resampling difference.
# The scaled, flipped and tinted sprites came back byte-identical, which is the
# property that actually matters: SDL's default render scale quality is nearest
# and `round_half_up`-quantized integer dest rects keep the sprite on the same
# pixel. If this ever needs raising, that is a pixel-art regression to report
# with the numbers, not a knob to turn.
CHANNEL_TOLERANCE = 1


def checker_surface():
    """8x8 pixel-art fixture: hard-edged 1px checks plus a fully transparent
    top row, so both nearest-neighbour resampling and per-pixel alpha edges are
    exercised."""
    s = pygame.Surface((8, 8), pygame.SRCALPHA)
    for y in range(8):
        for x in range(8):
            s.set_at((x, y), (200, 40, 60, 255) if (x + y) % 2 == 0
                     else (20, 220, 90, 255))
    for x in range(8):
        s.set_at((x, 0), (0, 0, 0, 0))
    return s


class GpuBackendCase(unittest.TestCase):
    def setUp(self):
        pygame.init()
        backend_gpu.clear_cache()
        backend._scale_cache.clear()
        self.window = Window("parity", size=(W, H))
        self.renderer = Renderer(self.window)

    def tearDown(self):
        backend_gpu.clear_cache()
        self.renderer = None
        self.window.destroy()
        self.window = None

    def render_gpu(self, calls):
        self.renderer.draw_color = (*BG, 255)
        self.renderer.clear()
        backend_gpu.draw(self.renderer, calls)
        return self.renderer.to_surface()

    @staticmethod
    def render_cpu(calls):
        surface = pygame.Surface((W, H))
        surface.fill(BG)
        backend.draw(surface, calls)
        return surface


class TestParity(GpuBackendCase):
    def scene(self):
        src = self.src
        return [
            # 1:1 identity.
            DrawCall(surface=src, dest=(10.0, 10.0), size=(8, 8)),
            # zoom != 1, non-integer multiple, dest AND size on a .5 tie so
            # round_half_up (floor(v + 0.5)) is actually exercised.
            DrawCall(surface=src, dest=(30.5, 20.5), size=(20.5, 20.5)),
            # Flip at a NON-INTEGER factor (8 -> 21px, a .5 tie). The two
            # backends compose flip and resample in OPPOSITE orders —
            # backend.py:219-221 scales then mirrors, while this one hands SDL
            # an unscaled texture and asks for a mirrored read. At an integer
            # factor k the two are provably equal ((kS-1-i)//k == S-1-i//k), so
            # an x2 case cannot detect a divergence; a non-integer factor can.
            DrawCall(surface=src, dest=(60.0, 20.0), size=(20.5, 20.5),
                     flip=True),
            # The modulation-leak pin: a tinted draw immediately followed by an
            # untinted draw from the SAME (cached, shared) source surface.
            DrawCall(surface=src, dest=(90.0, 20.0), size=(24, 24),
                     tint=(255, 128, 128)),
            DrawCall(surface=src, dest=(120.0, 20.0), size=(24, 24)),
            OverlayLines(points=((10, 100), (60, 120), (100, 95)),
                         color=(255, 255, 0), width=3),
            OverlayLines(points=((110, 100), (150, 100), (130, 130)),
                         color=(0, 200, 255), width=2, closed=True),
            OverlayPolys(points=((10, 60), (50, 60), (40, 90)),
                         color=(255, 0, 255)),
            OverlayPolys(points=((60, 60), (110, 65), (100, 92), (65, 88)),
                         color=(0, 255, 128, 100)),
        ]

    def setUp(self):
        super().setUp()
        self.src = checker_surface()

    def test_scene_matches_surface_backend(self):
        cpu = self.render_cpu(self.scene())
        gpu = self.render_gpu(self.scene())
        worst, where = 0, None
        for y in range(H):
            for x in range(W):
                a, b = cpu.get_at((x, y)), gpu.get_at((x, y))
                delta = max(abs(a[i] - b[i]) for i in range(3))
                if delta > worst:
                    worst, where = delta, (x, y, tuple(a)[:3], tuple(b)[:3])
        self.assertLessEqual(
            worst, CHANNEL_TOLERANCE,
            f"GPU/CPU per-channel delta {worst} > {CHANNEL_TOLERANCE} at {where}")

    def test_untinted_draw_after_tinted_is_not_modulated(self):
        """The tint must not leak through the shared cached Texture: the
        untinted 24x24 draw at (120, 20) must equal the tinted one's source
        colours, not the tinted ones."""
        gpu = self.render_gpu(self.scene())
        cpu = self.render_cpu(self.scene())
        for point in ((124, 27), (130, 33), (137, 40)):
            self.assertEqual(tuple(gpu.get_at(point))[:3],
                             tuple(cpu.get_at(point))[:3], point)
        # And the tinted draw really was tinted (otherwise the pin is vacuous).
        self.assertNotEqual(tuple(gpu.get_at((94, 27)))[:3],
                            tuple(gpu.get_at((124, 27)))[:3])


class TestTextureCache(GpuBackendCase):
    def test_one_upload_per_source_surface(self):
        src = checker_surface()
        calls = [
            DrawCall(surface=src, dest=(x * 3.0, 5.0), size=(8 + x, 8 + x),
                     flip=bool(x % 2),
                     tint=(255, 200, 200) if x % 3 == 0 else None)
            for x in range(12)
        ]
        uploads = []

        def spy(renderer, size, **kwargs):
            uploads.append(size)
            return Texture(renderer, size, **kwargs)

        backend_gpu.Texture = spy
        try:
            self.render_gpu(calls)
        finally:
            backend_gpu.Texture = Texture
        self.assertEqual(len(uploads), 1)
        self.assertEqual(uploads[0], src.get_size())
        by_renderer = backend_gpu._texture_cache[src]
        self.assertEqual(list(by_renderer), [id(self.renderer)])

    def test_gc_of_source_surface_evicts_its_texture(self):
        """The grey-X placeholder is a fresh surface every call
        (backend.py:31-36) — a strong key would leak a Texture per frame."""
        src = checker_surface()
        self.render_gpu([DrawCall(surface=src, dest=(0.0, 0.0), size=(16, 16))])
        self.assertEqual(len(backend_gpu._texture_cache), 1)
        del src
        gc.collect()
        self.assertEqual(len(backend_gpu._texture_cache), 0)


class TestOverlayClipReuse(GpuBackendCase):
    """G5 — the scratch rect is clipped to the target BEFORE allocating, and
    ONE reused buffer replaces the per-call allocate/upload/destroy. See
    docs/briefs/phase-G5-overlay-clip-reuse.md."""

    def _cluster(self, cx, cy):
        """A mix of OverlayLines/OverlayPolys (one alpha < 255 poly), a fixed
        ~80x70 local footprint (roughly x in [-40, 40], y in [-30, 40])
        recentred on (cx, cy). Callers pick (cx, cy) so the cluster straddles
        one edge, or a corner, of the 200x160 target — verified by
        `pygame.Rect.clip` (not just eyeballed): a bbox landing exactly ON a
        boundary clips to a zero-size Rect (half-open interval), so every
        centre below is chosen with margin on both sides of its boundary."""
        def shift(points):
            return tuple((x + cx, y + cy) for x, y in points)

        return [
            OverlayLines(points=shift(((-30, -10), (10, 20), (40, -5))),
                         color=(255, 255, 0), width=3),
            OverlayLines(points=shift(((-20, 10), (20, 10), (0, 40))),
                         color=(0, 200, 255), width=2, closed=True),
            OverlayPolys(points=shift(((-40, -30), (0, -30), (-10, 0))),
                         color=(255, 0, 255)),
            OverlayPolys(points=shift(((-30, -20), (20, -15), (10, 12),
                                       (-25, 8))),
                         color=(0, 255, 128, 100)),
        ]

    def _assert_parity(self, calls):
        cpu = self.render_cpu(calls)
        gpu = self.render_gpu(calls)
        worst, where = 0, None
        for y in range(H):
            for x in range(W):
                a, b = cpu.get_at((x, y)), gpu.get_at((x, y))
                delta = max(abs(a[i] - b[i]) for i in range(3))
                if delta > worst:
                    worst, where = delta, (x, y, tuple(a)[:3], tuple(b)[:3])
        self.assertLessEqual(
            worst, CHANNEL_TOLERANCE,
            f"GPU/CPU per-channel delta {worst} > {CHANNEL_TOLERANCE} at {where}")

    def test_clipped_past_left_edge(self):
        self._assert_parity(self._cluster(cx=-10, cy=80))

    def test_clipped_past_right_edge(self):
        self._assert_parity(self._cluster(cx=210, cy=80))

    def test_clipped_past_top_edge(self):
        self._assert_parity(self._cluster(cx=100, cy=-5))

    def test_clipped_past_bottom_edge(self):
        self._assert_parity(self._cluster(cx=100, cy=165))

    def test_clipped_past_corner(self):
        self._assert_parity(self._cluster(cx=210, cy=165))

    def test_wholly_off_screen_overlay_is_a_no_op(self):
        """The plan's pathological case: an overlay whose points are all far
        off-screen must not raise and must leave the frame identical to the
        same frame without it — no ValueError from a zero-area Texture, and
        no stray pixel."""
        base = [
            DrawCall(surface=checker_surface(), dest=(20.0, 20.0),
                     size=(16, 16)),
        ]
        off_screen = OverlayLines(
            points=((5000, 5000), (5100, 5050)),
            color=(255, 0, 0), width=3)

        without = self.render_gpu(base)
        with_offscreen = self.render_gpu(base + [off_screen])  # must not raise

        for y in range(H):
            for x in range(W):
                self.assertEqual(without.get_at((x, y)),
                                 with_offscreen.get_at((x, y)), (x, y))

    def test_n_overlay_draws_allocate_one_scratch_surface(self):
        # Every shape below has an IDENTICAL clipped bbox footprint (21x21,
        # for the poly; the line's width=1 pad(1) + an 18px span works out to
        # the same 21x21) so the first call sets the high-water mark and no
        # later call ever needs to grow the buffer — the point of this test.
        calls = []
        for i in range(10):
            calls.append(OverlayPolys(
                points=((10 + i, 10 + i), (30 + i, 10 + i), (20 + i, 30 + i)),
                color=(255, 0, 0, 128)))
            calls.append(OverlayLines(
                points=((40 + i, 40 + i), (58 + i, 58 + i)),
                color=(0, 255, 0), width=1))

        allocs = []

        def spy(size, flags=0):
            allocs.append(size)
            return Surface(size, flags)

        backend_gpu.Surface = spy
        try:
            self.render_gpu(calls)
        finally:
            backend_gpu.Surface = Surface
        self.assertEqual(len(allocs), 1)

    def test_buffer_grows_and_is_not_reallocated_for_a_smaller_overlay(self):
        large = [OverlayPolys(
            points=((5, 5), (150, 10), (140, 130), (10, 120)),
            color=(0, 0, 255, 128))]
        small = [OverlayLines(
            points=((10, 10), (20, 20)), color=(255, 0, 0), width=1)]

        allocs = []

        def spy(size, flags=0):
            allocs.append(size)
            return Surface(size, flags)

        backend_gpu.Surface = spy
        try:
            self.render_gpu(large)
            self.assertEqual(len(allocs), 1)
            high_water = backend_gpu._overlay_scratch.get_size()
            self.render_gpu(small)
        finally:
            backend_gpu.Surface = Surface
        self.assertEqual(len(allocs), 1)
        self.assertEqual(backend_gpu._overlay_scratch.get_size(), high_water)


class TestHudOnlyFieldsRejected(GpuBackendCase):
    def test_slice_raises(self):
        call = DrawCall(surface=checker_surface(), dest=(0.0, 0.0),
                        size=(32, 32), slice=(4, 4, 4, 4))
        with self.assertRaises(NotImplementedError):
            self.render_gpu([call])

    def test_all_zero_slice_is_a_plain_scale_and_does_not_raise(self):
        call = DrawCall(surface=checker_surface(), dest=(0.0, 0.0),
                        size=(32, 32), slice=(0, 0, 0, 0))
        self.render_gpu([call])  # must not raise

    def test_crop_rect_raises(self):
        call = DrawCall(surface=checker_surface(), dest=(0.0, 0.0),
                        size=(32, 32), crop_rect=(1, 1, 4, 4))
        with self.assertRaises(NotImplementedError):
            self.render_gpu([call])

    def test_hud_primitive_raises(self):
        with self.assertRaises(NotImplementedError):
            self.render_gpu([HudRect(rect=(0, 0, 10, 10), color=(255, 0, 0))])


if __name__ == "__main__":
    unittest.main()
