"""Tests for engine.render.ground_cache.GroundCache (perf: cached static
ground layer) AND its GPU port, engine.render.ground_cache_gpu.GroundCacheGpu
(G3). Pins the load-bearing correctness property — a cached ground render is
PIXEL-IDENTICAL to the direct per-tile render for a static camera — plus the
rebuild-trigger logic and the blit-offset sign, for BOTH implementations via
a shared mixin (`GroundCacheMixin`) so the pins cannot drift apart between
them.

SDL dummy driver: set in-code so surfaces AND the SDL2 Window/Renderer/Texture
path work headless (no display needed; measured — GpuAndMasterSheetsPLAN §4)."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from pygame._sdl2.video import Renderer as SdlRenderer, Texture, Window

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import Renderer, backend_gpu
from engine.render import ground_cache_gpu
from engine.render.ground_cache import GroundCache
from engine.render.ground_cache_gpu import GroundCacheGpu

DATA = FIXTURE_DATA
SCHEMA = DATA / "schemas" / "map_file.schema.json"
VIEW_W, VIEW_H = 320, 240
BG = (24, 20, 32)

# Max allowed per-channel |CPU - GPU| difference for the GPU subclass's pixel-
# equality pins. NOT zero — exact byte equality was tried first (as the brief
# asks) and did NOT hold. MEASURED on this fixture (pygame-ce 2.5.7 / SDL
# 2.32.10; the fixture data has no real sprite art, so every tile draws
# through the grey-X placeholder, which has per-pixel alpha and so exercises
# the same alpha-blend rounding path test_render_backend_parity.py already
# pinned at CHANNEL_TOLERANCE=1 for backend_gpu directly):
#   zoom1 scroll-free : worst delta 1, on 38100/76800 px, hist {1: 38100}
#   zoom2 (scale path): worst delta 1, on 47585/76800 px, hist {1: 47585}
#   tint (editor path): worst delta 2, on 43133/76800 px, hist {1: 35795, 2: 7338}
#   map edge           : worst delta 1, on 25965/76800 px, hist {1: 25965}
#   scroll (11 steps across zoom1 and zoom2, `test_pixel_equal_after_scroll`
#     and its zoom2 sibling): worst delta 1 on every step, 521776 differing
#     pixels total across all 11 steps, hist {1: 521776}
# This is a real (if tiny, at most 2/255) SDL-vs-Surface blend rounding
# difference, not a resampling or seam bug — reported as a finding, not
# silently widened past what was measured. See engine/render/CLAUDE.md's
# "GPU variant" bullet.
GPU_CHANNEL_TOLERANCE = 2


def make_doc(cols=40, rows=40):
    """A doc with mixed terrain codes so tiles differ (checkerboard + zones),
    making a pixel-equality check meaningful rather than a flat field."""
    legend, base_slot = tilemap.defaults_from_schema(data_io.load_json(SCHEMA))
    codes = list(legend)
    terrain = [[codes[(c + r) % len(codes)] for c in range(cols)]
               for r in range(rows)]
    return tilemap.TileMapDoc(
        map_id="gc_test", display_name="GC", cols=cols, rows=rows,
        legend=legend, terrain=terrain,
        base={"col": cols // 2, "row": rows // 2, "slot": base_slot}, deco=[])


class GroundCacheMixin:
    """Body shared by the CPU (`GroundCache`) and GPU (`GroundCacheGpu`) pins.
    NOT a TestCase by itself — the concrete subclasses below mix this in with
    `unittest.TestCase` and supply the four implementation-specific seams
    (`_make_cache`, `_blit_to_surface`, `_capture_blit_dest`, plus
    `setUpClass`'s `cls.assets`)."""

    # 0 -> exact byte equality (the CPU class's pin). A subclass overrides
    # this to a measured, named, non-zero tolerance if exact equality does
    # not hold for it (see GPU_CHANNEL_TOLERANCE above).
    CHANNEL_TOLERANCE = 0

    @classmethod
    def setUpClass(cls):
        pygame.init()
        registry = load_registry(DATA)
        cls.assets = AssetStore(
            manifest=load_manifest(DATA / "sprites" / "asset_manifest.json"),
            registry=registry, sprites_dir=DATA / "sprites")

    def _coords(self, cols, rows, zoom=1.0):
        cs = load_coordinate_system(DATA, map_cols=cols, map_rows=rows)
        cs.set_zoom(zoom)
        cs.clamp(VIEW_W, VIEW_H)
        return cs

    def _ground_fn(self, doc, tint=None):
        return lambda dmn, dmx, smn, smx: tilemap.band_render_items(
            doc, dmn, dmx, smn, smx, tint_for_code=tint)

    def _direct(self, cs, doc, tint=None):
        """The old path: fill bg, then submit+flush the ground window
        directly. Implementation-agnostic (plain Surface backend) — used
        as the ground truth for BOTH cache implementations."""
        surf = pygame.Surface((VIEW_W, VIEW_H))
        surf.fill(BG)
        r = Renderer(cs, self.assets)
        cmin, cmax, rmin, rmax = cs.visible_tile_window(VIEW_W, VIEW_H, margin=4)
        for it in tilemap.visible_render_items(
                doc, cmin, cmax, rmin, rmax, base=False, deco=False,
                tint_for_code=tint):
            r.submit(it)
        r.flush(surf)
        return surf

    def _assert_same(self, a, b, msg):
        """Exact byte equality when CHANNEL_TOLERANCE is 0 (the CPU pin);
        otherwise a per-channel |a-b| <= CHANNEL_TOLERANCE check (the GPU
        pin — see GPU_CHANNEL_TOLERANCE's measured numbers above)."""
        if self.CHANNEL_TOLERANCE == 0:
            self.assertEqual(pygame.image.tobytes(a, "RGB"),
                             pygame.image.tobytes(b, "RGB"), msg)
            return
        worst = 0
        for y in range(a.get_height()):
            for x in range(a.get_width()):
                pa, pb = a.get_at((x, y)), b.get_at((x, y))
                d = max(abs(pa[i] - pb[i]) for i in range(3))
                if d > worst:
                    worst = d
        self.assertLessEqual(
            worst, self.CHANNEL_TOLERANCE,
            f"{msg}: max per-channel delta {worst} > tolerance {self.CHANNEL_TOLERANCE}")

    # -- implementation-specific seams, supplied by subclasses --------------

    def _make_cache(self, cs, margin=256, bg=BG):
        raise NotImplementedError

    def _blit_to_surface(self, gc):
        """ensure() has already run; blit the cache and read it back as an
        RGB pygame.Surface comparable to `_direct`'s output."""
        raise NotImplementedError

    def _capture_blit_dest(self, gc):
        """Blit `gc` and return the (x, y) dest it drew at, without actually
        needing a real target surface."""
        raise NotImplementedError

    def _cached(self, cs, doc, tint=None, margin=256):
        gc = self._make_cache(cs, margin=margin)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc, tint))
        return self._blit_to_surface(gc)

    # -- pixel equality (the correctness anchor) ---------------------------

    def test_pixel_equal_zoom1(self):
        cs = self._coords(40, 40, zoom=1.0)
        cs.pan(37, -19)  # off a tile boundary so rounding is exercised
        cs.clamp(VIEW_W, VIEW_H)
        doc = make_doc()
        self._assert_same(self._cached(cs, doc), self._direct(cs, doc),
                          "cached ground != direct at zoom 1.0")

    def test_pixel_equal_zoom2(self):
        cs = self._coords(40, 40, zoom=2.0)
        cs.pan(53, 41)
        cs.clamp(VIEW_W, VIEW_H)
        doc = make_doc()
        self._assert_same(self._cached(cs, doc), self._direct(cs, doc),
                          "cached ground != direct at zoom 2.0 (scale path)")

    def test_pixel_equal_with_tint(self):
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        tint = {list(doc.legend)[0]: (150, 235, 150, 255)}
        self._assert_same(self._cached(cs, doc, tint),
                          self._direct(cs, doc, tint),
                          "cached ground != direct with tint (editor path)")

    def test_pixel_equal_at_map_edge(self):
        """Camera at a corner so the window runs off the map — off-map area must
        read back as BG in both paths (transparency/edge handling)."""
        cs = self._coords(24, 24, zoom=1.0)
        cs.camera.pan_x, cs.camera.pan_y = -100, -100  # push top-left off-map
        doc = make_doc(24, 24)
        self._assert_same(self._cached(cs, doc), self._direct(cs, doc),
                          "cached ground != direct at map edge")

    def test_pixel_equal_after_scroll(self):
        """The scroll-and-fill path is the load-bearing one: after building once
        and then panning in small steps (so ensure SCROLLS + repaints only the
        exposed edge), the cached surface must stay pixel-identical to a
        from-scratch direct render at each panned position. Successive steps in
        every direction catch seam gaps and sub-pixel drift."""
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        gc = self._make_cache(cs, margin=64)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))  # initial full build
        # deltas mix signs and both axes so both exposed strips fire; magnitudes
        # stay well inside the 64px margin so every step scrolls (never rebuilds).
        for dx, dy in [(23, -17), (17, 29), (-31, 11), (-9, -25), (40, 3),
                       (3, 40), (-40, -40)]:
            cs.pan(dx, dy)
            cs.clamp(VIEW_W, VIEW_H)
            gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
            surf = self._blit_to_surface(gc)
            self._assert_same(surf, self._direct(cs, doc),
                              f"scrolled ground != direct after pan {(dx, dy)}")

    def test_pixel_equal_after_scroll_zoom2(self):
        """Same scroll invariant at a non-1 zoom (the band's half_w/half_h scale)."""
        cs = self._coords(40, 40, zoom=2.0)
        doc = make_doc()
        gc = self._make_cache(cs, margin=64)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        for dx, dy in [(19, -13), (-27, 21), (11, 33), (-40, -8)]:
            cs.pan(dx, dy)
            cs.clamp(VIEW_W, VIEW_H)
            gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
            surf = self._blit_to_surface(gc)
            self._assert_same(surf, self._direct(cs, doc),
                              f"scrolled ground != direct (zoom2) after {(dx, dy)}")

    # -- blit-offset sign --------------------------------------------------

    def test_blit_offset_sign(self):
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        gc = self._make_cache(cs, margin=256)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        anchor = gc._anchor_pan
        # A small in-margin pan: dest must be anchor_pan - current_pan - margin.
        cs.camera.pan_x = anchor[0] + 30
        cs.camera.pan_y = anchor[1] - 12

        dest = self._capture_blit_dest(gc)
        self.assertEqual(dest,
                         (round(anchor[0] - cs.camera.pan_x - 256),
                          round(anchor[1] - cs.camera.pan_y - 256)))

    # -- rebuild triggers --------------------------------------------------

    def test_rebuild_vs_scroll_triggers(self):
        """A full rebuild (whole surface recomposited) fires only on first use /
        zoom / invalidate / resize / a jump clear off the cached surface. An
        in-surface pan SCROLLS instead (cheap edge repaint); a no-op ensure does
        nothing. Spy on _rebuild vs _scroll to tell them apart (both call the
        item fn, so counting fn calls can't distinguish them)."""
        cs = self._coords(200, 200, zoom=1.0)
        doc = make_doc(200, 200)
        gc = self._make_cache(cs, margin=256)
        fn = self._ground_fn(doc)
        n = {"rebuild": 0, "scroll": 0}
        real_rebuild, real_scroll = gc._rebuild, gc._scroll
        gc._rebuild = lambda *a, **k: (n.__setitem__("rebuild", n["rebuild"] + 1),
                                       real_rebuild(*a, **k))[1]
        gc._scroll = lambda *a, **k: (n.__setitem__("scroll", n["scroll"] + 1),
                                      real_scroll(*a, **k))[1]

        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (1, 0), "first ensure builds")

        cs.pan(20, 20)  # in-surface pan -> scroll
        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (1, 1), "in-margin pan scrolls")

        gc.ensure(VIEW_W, VIEW_H, fn)  # no movement -> nothing
        self.assertEqual((n["rebuild"], n["scroll"]), (1, 1), "no-op does nothing")

        cs.pan(20, 20)  # still on the (oversized) surface -> scroll, not rebuild
        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (1, 2), "moderate pan scrolls")

        cs.pan(5000, 5000)  # jump clear off the surface -> full rebuild
        cs.clamp(VIEW_W, VIEW_H)
        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (2, 2), "off-surface jump rebuilds")

        cs.set_zoom(2.0)
        cs.clamp(VIEW_W, VIEW_H)
        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (3, 2), "zoom rebuilds")

        gc.invalidate()
        gc.ensure(VIEW_W, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (4, 2), "invalidate rebuilds")

        gc.ensure(VIEW_W + 40, VIEW_H, fn)
        self.assertEqual((n["rebuild"], n["scroll"]), (5, 2), "resize rebuilds")


class TestGroundCacheCpu(GroundCacheMixin, unittest.TestCase):
    """The Surface implementation — exact byte equality throughout."""

    def _make_cache(self, cs, margin=256, bg=BG):
        return GroundCache(cs, self.assets, pixel_margin=margin, bg_color=bg)

    def _blit_to_surface(self, gc):
        surf = pygame.Surface((VIEW_W, VIEW_H))
        surf.fill(BG)
        gc.blit(surf)
        return surf

    def _capture_blit_dest(self, gc):
        class FakeTarget:  # Surface.blit is read-only; capture the dest instead
            pos = None

            def blit(self, surface, pos):
                self.pos = pos

        target = FakeTarget()
        gc.blit(target)
        return target.pos


class _SpyTexture(Texture):
    """Texture subclass that records the dstrect handed to the most recent
    draw() call. `Texture` is an immutable C type (measured: assigning to
    `tex.draw` or `Texture.draw` both raise TypeError/AttributeError), so
    subclassing is the only spy seam SDL2's binding allows here."""
    last_dstrect = None

    def draw(self, **kwargs):
        _SpyTexture.last_dstrect = kwargs.get("dstrect")
        return super().draw(**kwargs)


class TestGroundCacheGpu(GroundCacheMixin, unittest.TestCase):
    """The SDL2 Texture implementation (G3). Exact byte equality was tried
    first and did NOT hold (measured — see GPU_CHANNEL_TOLERANCE above);
    pixel-equality pins here compare within that named, measured tolerance
    instead."""

    CHANNEL_TOLERANCE = GPU_CHANNEL_TOLERANCE

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.window = Window("ground_cache_gpu_test", size=(VIEW_W, VIEW_H))
        cls.renderer = SdlRenderer(cls.window)

    @classmethod
    def tearDownClass(cls):
        backend_gpu.clear_cache()
        cls.renderer = None
        cls.window.destroy()
        cls.window = None

    def setUp(self):
        backend_gpu.clear_cache()
        # GroundCacheGpu builds its render-target Texture pair through the
        # module-level `Texture` name in ground_cache_gpu.py; swap it for the
        # spy subclass for the lifetime of each test so test_blit_offset_sign
        # can observe the dstrect without a real target surface. The spy is a
        # pure pass-through (`super().draw(**kwargs)`), so every other pin in
        # this class exercises the exact same SDL calls as production.
        self._orig_texture = ground_cache_gpu.Texture
        ground_cache_gpu.Texture = _SpyTexture
        _SpyTexture.last_dstrect = None

    def tearDown(self):
        ground_cache_gpu.Texture = self._orig_texture

    def _make_cache(self, cs, margin=256, bg=BG):
        return GroundCacheGpu(self.renderer, cs, self.assets,
                              pixel_margin=margin, bg_color=bg)

    def _blit_to_surface(self, gc):
        self.renderer.target = None
        self.renderer.draw_color = (*BG, 255)
        self.renderer.clear()
        gc.blit(self.renderer)
        return self.renderer.to_surface()

    def _capture_blit_dest(self, gc):
        _SpyTexture.last_dstrect = None
        gc.blit(self.renderer)
        r = _SpyTexture.last_dstrect
        return (r.x, r.y)

    # -- GPU mechanics (no CPU equivalent; §4 items 5-6) --------------------

    def test_state_restored_after_ensure_and_blit(self):
        """A leaked SDL render target or viewport silently corrupts the
        host's entire next frame with no error — nothing else in the suite
        would catch it."""
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        gc = self._make_cache(cs, margin=64)
        full_viewport = pygame.Rect(0, 0, VIEW_W, VIEW_H)

        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        self.assertIsNone(self.renderer.target, "target leaked after ensure")
        self.assertEqual(self.renderer.get_viewport(), full_viewport,
                         "viewport leaked after ensure")

        gc.blit(self.renderer)
        self.assertIsNone(self.renderer.target, "target leaked after blit")
        self.assertEqual(self.renderer.get_viewport(), full_viewport,
                         "viewport leaked after blit")

        # And again after a SCROLL (not just the initial rebuild), which
        # brackets an extra self-blit target switch.
        cs.pan(10, -6)
        cs.clamp(VIEW_W, VIEW_H)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        self.assertIsNone(self.renderer.target, "target leaked after scroll")
        self.assertEqual(self.renderer.get_viewport(), full_viewport,
                         "viewport leaked after scroll")

    def test_scroll_ping_pongs_distinct_textures(self):
        """SDL cannot read and write one render target in a single pass, so
        _scroll self-blits into a SECOND texture and swaps — pin that the
        pair are two distinct objects whose front/back identity actually
        swaps across a scrolling ensure()."""
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        gc = self._make_cache(cs, margin=64)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        self.assertIsNot(gc._front, gc._back)
        front_before, back_before = id(gc._front), id(gc._back)

        cs.pan(20, -15)  # in-margin -> scroll, not rebuild
        cs.clamp(VIEW_W, VIEW_H)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))

        self.assertIsNot(gc._front, gc._back)
        self.assertEqual(id(gc._front), back_before,
                         "front should be the old back after one scroll")
        self.assertEqual(id(gc._back), front_before,
                         "back should be the old front after one scroll")


if __name__ == "__main__":
    unittest.main()
