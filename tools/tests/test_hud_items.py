"""HUD pass tests (E-12): HUD dataclass construction + renderer folding HUD
into the flat draw list via a recording backend, after sprites and overlays,
in screen space. Pure Python — no pygame."""
import unittest

from engine.assets.manifest import Manifest, entry_from_dict
from engine.assets.types import Frame
from engine.coords import Camera, CoordinateSystem, Geometry
from engine.render import (
    DrawCall,
    HudLines,
    HudRect,
    HudSprite,
    HudText,
    OverlayLines,
    RenderItem,
    Renderer,
)


def make_cs(**camera):
    geo = Geometry(
        tile_w=64, tile_h=32, map_cols=20, map_rows=20, zoom_levels=(0.5, 1.0, 2.0)
    )
    return CoordinateSystem(geo, Camera(**camera))


class FakeAssets:
    def __init__(self, sizes=None, default=(64, 32)):
        self.sizes = sizes or {}
        self.default = default

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None,
              column=None):
        w, h = self.sizes.get(slot_key, self.default)
        return Frame(surface=f"SURF:{slot_key}", frame_w=w, frame_h=h)


class RecordingAssets(FakeAssets):
    """FakeAssets that records how the renderer asked for each frame."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.calls = []

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None,
              column=None):
        self.calls.append((slot_key, animation, anim_time_ms))
        return super().frame(slot_key, animation, anim_time_ms,
                             extra_hidden=extra_hidden)


class ManifestAssets:
    """A pure store over a real Manifest: the Frame's `surface` IS the
    (row, col) ref current_frame resolved, so a test can assert which sheet
    cell a HUD sprite would blit without ever touching pygame."""

    def __init__(self, manifest):
        self.manifest = manifest

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None):
        ref = self.manifest.current_frame(slot_key, animation, anim_time_ms,
                                          extra_hidden=extra_hidden)
        entry = self.manifest.entry(slot_key)
        return Frame(surface=ref, frame_w=entry.frame_w, frame_h=entry.frame_h)


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


class TestHudDataclasses(unittest.TestCase):
    def test_construction_and_defaults(self):
        r = HudRect((0, 0, 10, 20), (255, 0, 0))
        self.assertEqual(r.width, 0)
        self.assertEqual(r.border_radius, 0)
        t = HudText("HP", (5, 5), "small", (255, 255, 255))
        self.assertEqual(t.align, "left")
        s = HudSprite("icon", (2, 2), (16, 16))
        self.assertIsNone(s.tint)
        self.assertFalse(s.flip)
        ln = HudLines(((0, 0), (5, 5)), (0, 255, 0))
        self.assertEqual(ln.width, 1)
        self.assertFalse(ln.closed)

    def test_frozen(self):
        r = HudRect((0, 0, 1, 1), (0, 0, 0))
        with self.assertRaises(Exception):
            r.color = (1, 1, 1)


class TestRendererFoldsHud(unittest.TestCase):
    def test_hud_appended_after_sprites_and_overlays(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit(RenderItem("tile", (0, 0), layer="ground"))
        r.submit_overlay_lines(((0, 0), (5, 0)), color=(255, 0, 0))
        r.submit_hud(HudRect((0, 0, 100, 20), (10, 10, 10)))
        count = r.flush(target=None)
        self.assertEqual(count, 3)
        # order: sprite draw call, overlay lines, then HUD
        self.assertIsInstance(backend.calls[0], DrawCall)
        self.assertIsInstance(backend.calls[1], OverlayLines)
        self.assertIsInstance(backend.calls[2], HudRect)

    def test_hud_passthrough_types_unchanged(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        rect = HudRect((1, 2, 3, 4), (5, 6, 7), border_radius=2, width=1)
        text = HudText("42", (8, 9), "big", (255, 255, 255), align="center")
        lines = HudLines(((0, 0), (1, 1)), (9, 9, 9), width=3)
        r.submit_hud(rect)
        r.submit_hud(text)
        r.submit_hud(lines)
        r.flush(target=None)
        # passthrough: same objects, no coords conversion
        self.assertIs(backend.calls[0], rect)
        self.assertIs(backend.calls[1], text)
        self.assertIs(backend.calls[2], lines)

    def test_hud_sprite_resolves_to_screen_space_drawcall(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(sizes={"icon": (16, 16)}), backend=backend)
        r.submit_hud(HudSprite("icon", dest=(30, 40), size=(16, 16),
                               tint=(255, 0, 0), flip=True))
        r.flush(target=None)
        call = backend.calls[0]
        self.assertIsInstance(call, DrawCall)
        self.assertEqual(call.surface, "SURF:icon")
        self.assertEqual(call.dest, (30, 40))  # screen space, no conversion
        self.assertEqual(call.size, (16, 16))
        self.assertEqual(call.tint, (255, 0, 0))
        self.assertTrue(call.flip)

    def test_flush_clears_hud(self):
        backend = RecordingBackend()
        r = Renderer(make_cs(), FakeAssets(), backend=backend)
        r.submit_hud(HudRect((0, 0, 1, 1), (0, 0, 0)))
        r.flush(target=None)
        self.assertEqual(r.flush(target=None), 0)
        self.assertEqual(len(backend.calls), 1)

    def test_bad_hud_type_rejected(self):
        r = Renderer(make_cs(), FakeAssets(), backend=RecordingBackend())
        with self.assertRaises(TypeError):
            r.submit_hud(RenderItem("nope", (0, 0)))


class TestHudSpriteAnimation(unittest.TestCase):
    """A1: HudSprite carries animation/anim_time_ms and the renderer resolves
    the frame with both — the same slot/animation/time contract as RenderItem."""

    # a 1-frame idle row + a 2-frame hover row at 10 fps => 100 ms per frame
    ENTRY = {
        "sheet": "x.png",
        "frame_w": 16,
        "frame_h": 16,
        "rows": [
            {"animation": "idle", "frames": 1},
            {"animation": "hover", "frames": 2, "fps": 10},
        ],
    }

    def manifest_assets(self):
        entry = entry_from_dict("btn", self.ENTRY)
        return ManifestAssets(Manifest({"btn": entry}))

    def test_defaults_unchanged(self):
        sprite = HudSprite("icon", (2, 2), (16, 16))  # the game's positional form
        self.assertEqual(sprite.animation, "idle")
        self.assertEqual(sprite.anim_time_ms, 0)
        # tint/flip keep their positional slots (the new fields went last)
        positional = HudSprite("icon", (2, 2), (16, 16), (1, 2, 3), True)
        self.assertEqual(positional.tint, (1, 2, 3))
        self.assertTrue(positional.flip)

        assets = RecordingAssets(sizes={"icon": (16, 16)})
        backend = RecordingBackend()
        r = Renderer(make_cs(), assets, backend=backend)
        r.submit_hud(sprite)
        r.flush(target=None)
        self.assertEqual(assets.calls, [("icon", "idle", 0)])
        self.assertEqual(
            backend.calls[0],
            DrawCall(surface="SURF:icon", dest=(2, 2), size=(16, 16),
                     tint=None, flip=False),
        )

    def test_animation_and_time_forwarded(self):
        assets = RecordingAssets(sizes={"btn": (64, 32)})
        r = Renderer(make_cs(), assets, backend=RecordingBackend())
        r.submit_hud(HudSprite("btn", (0, 0), (64, 32),
                               animation="hover", anim_time_ms=250))
        r.flush(target=None)
        self.assertEqual(assets.calls, [("btn", "hover", 250)])

    def test_two_times_resolve_different_frames(self):
        assets = self.manifest_assets()
        backend = RecordingBackend()
        r = Renderer(make_cs(), assets, backend=backend)
        for t in (0, 150):
            r.submit_hud(HudSprite("btn", (0, 0), (64, 32),
                                   animation="hover", anim_time_ms=t))
            r.flush(target=None)
        # same row, different column — the timeline advanced with the clock
        self.assertEqual(backend.calls[0].surface, (1, 0))
        self.assertEqual(backend.calls[1].surface, (1, 1))

    def test_missing_animation_falls_back_to_idle(self):
        assets = self.manifest_assets()
        backend = RecordingBackend()
        r = Renderer(make_cs(), assets, backend=backend)
        for t in (0, 150, 999):
            r.submit_hud(HudSprite("btn", (0, 0), (64, 32),
                                   animation="pressed", anim_time_ms=t))
        r.flush(target=None)
        for call in backend.calls:
            self.assertEqual(call.surface, (0, 0))  # the idle row, at any time


if __name__ == "__main__":
    unittest.main()
