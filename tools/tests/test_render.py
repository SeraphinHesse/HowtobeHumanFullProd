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
from engine.render import LAYERS, RenderItem, Renderer

REPO = pathlib.Path(__file__).resolve().parents[2]


def make_cs(**camera):
    geo = Geometry(
        tile_w=64, tile_h=32, map_cols=20, map_rows=20, zoom_levels=(0.5, 1.0, 2.0)
    )
    return CoordinateSystem(geo, Camera(**camera))


class FakeAssets:
    """Resolves every slot to a token 'surface' so tests stay pygame-free."""

    def __init__(self, sizes=None, default=(64, 32)):
        self.sizes = sizes or {}
        self.default = default

    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        w, h = self.sizes.get(slot_key, self.default)
        return Frame(surface=f"SURF:{slot_key}", frame_w=w, frame_h=h)


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


class TestLayerAndDepthOrder(unittest.TestCase):
    """E-26 layer order ground→entities→deco→overlay; E-21/E-4 iso sort within."""

    def test_named_layer_order(self):
        self.assertEqual(LAYERS, ("ground", "entities", "deco", "overlay"))

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
        # world (1,1) → screen (0, 32); bottom of 96-tall frame sits at 32+32
        self.assertEqual(call.dest, (-32.0, -32.0))
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


class TestPurity(unittest.TestCase):
    """Hard rule: coords / data_io / render orchestration / asset metadata
    import no pygame."""

    def test_pure_modules_do_not_import_pygame(self):
        code = (
            "import sys; "
            "import engine.coords, engine.data_io, engine.render, engine.assets; "
            "assert 'pygame' not in sys.modules, 'pygame leaked into pure modules'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
