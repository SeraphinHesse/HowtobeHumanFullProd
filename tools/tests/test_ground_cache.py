"""Tests for engine.render.ground_cache.GroundCache (perf: cached static
ground layer). Pins the load-bearing correctness property — a cached ground
render is PIXEL-IDENTICAL to the direct per-tile render for a static camera —
plus the rebuild-trigger logic and the blit-offset sign.

SDL dummy driver: set in-code so surfaces work headless (no display needed for
surface-to-surface blits)."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

REPO = Path(__file__).resolve().parents[2]

from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import Renderer
from engine.render.ground_cache import GroundCache

DATA = REPO / "data"
SCHEMA = DATA / "schemas" / "map_file.schema.json"
VIEW_W, VIEW_H = 320, 240
BG = (24, 20, 32)


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


class GroundCacheCase(unittest.TestCase):
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
        """The old path: fill bg, then submit+flush the ground window directly."""
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

    def _cached(self, cs, doc, tint=None, margin=256):
        surf = pygame.Surface((VIEW_W, VIEW_H))
        surf.fill(BG)
        gc = GroundCache(cs, self.assets, pixel_margin=margin, bg_color=BG)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc, tint))
        gc.blit(surf)
        return surf

    # -- pixel equality (the correctness anchor) ---------------------------

    def _assert_same(self, a, b, msg):
        self.assertEqual(pygame.image.tobytes(a, "RGB"),
                         pygame.image.tobytes(b, "RGB"), msg)

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
        gc = GroundCache(cs, self.assets, pixel_margin=64, bg_color=BG)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))  # initial full build
        # deltas mix signs and both axes so both exposed strips fire; magnitudes
        # stay well inside the 64px margin so every step scrolls (never rebuilds).
        for dx, dy in [(23, -17), (17, 29), (-31, 11), (-9, -25), (40, 3),
                       (3, 40), (-40, -40)]:
            cs.pan(dx, dy)
            cs.clamp(VIEW_W, VIEW_H)
            surf = pygame.Surface((VIEW_W, VIEW_H))
            surf.fill(BG)
            gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
            gc.blit(surf)
            self._assert_same(surf, self._direct(cs, doc),
                              f"scrolled ground != direct after pan {(dx, dy)}")

    def test_pixel_equal_after_scroll_zoom2(self):
        """Same scroll invariant at a non-1 zoom (the band's half_w/half_h scale)."""
        cs = self._coords(40, 40, zoom=2.0)
        doc = make_doc()
        gc = GroundCache(cs, self.assets, pixel_margin=64, bg_color=BG)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        for dx, dy in [(19, -13), (-27, 21), (11, 33), (-40, -8)]:
            cs.pan(dx, dy)
            cs.clamp(VIEW_W, VIEW_H)
            surf = pygame.Surface((VIEW_W, VIEW_H))
            surf.fill(BG)
            gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
            gc.blit(surf)
            self._assert_same(surf, self._direct(cs, doc),
                              f"scrolled ground != direct (zoom2) after {(dx, dy)}")

    # -- blit-offset sign --------------------------------------------------

    def test_blit_offset_sign(self):
        cs = self._coords(40, 40, zoom=1.0)
        doc = make_doc()
        gc = GroundCache(cs, self.assets, pixel_margin=256, bg_color=BG)
        gc.ensure(VIEW_W, VIEW_H, self._ground_fn(doc))
        anchor = gc._anchor_pan
        # A small in-margin pan: dest must be anchor_pan - current_pan - margin.
        cs.camera.pan_x = anchor[0] + 30
        cs.camera.pan_y = anchor[1] - 12

        class FakeTarget:  # Surface.blit is read-only; capture the dest instead
            pos = None

            def blit(self, surface, pos):
                self.pos = pos

        target = FakeTarget()
        gc.blit(target)
        self.assertEqual(target.pos,
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
        gc = GroundCache(cs, self.assets, pixel_margin=256, bg_color=BG)
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


if __name__ == "__main__":
    unittest.main()
