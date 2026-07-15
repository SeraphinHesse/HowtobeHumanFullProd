"""AssetStore sheet slicing + tolerance (E-35/E-36/E-37) — pygame side.

Synthetic sheets (distinct solid-colour frames) in temp dirs; nothing here
touches the repo's data/. SDL dummy drivers as everywhere else.
"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from engine.assets import Manifest, SlotRegistry, entry_from_dict  # noqa: E402
from engine.assets.store import AssetStore  # noqa: E402
from engine.render import backend  # noqa: E402
from engine.render.item import DrawCall  # noqa: E402

pygame.init()

FRAME_W, FRAME_H = 8, 16
# colours[row][col] — distinct per frame
COLOURS = [
    [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)],
    [(255, 255, 0, 255), (0, 255, 255, 255), (255, 0, 255, 255)],
]


def make_sheet(path, cols=3, rows=2):
    sheet = pygame.Surface((cols * FRAME_W, rows * FRAME_H), pygame.SRCALPHA)
    for r in range(rows):
        for c in range(cols):
            sheet.fill(COLOURS[r][c],
                       pygame.Rect(c * FRAME_W, r * FRAME_H, FRAME_W, FRAME_H))
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(path))


def make_hole_sheet(path, cols=1, rows=1):
    """Every frame: fully opaque except pixel (0, 0), which is fully
    transparent — a single 'hole' to hit-test against."""
    sheet = pygame.Surface((cols * FRAME_W, rows * FRAME_H), pygame.SRCALPHA)
    sheet.fill((255, 0, 0, 255))
    for r in range(rows):
        for c in range(cols):
            sheet.set_at((c * FRAME_W, r * FRAME_H), (255, 0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(path))


def make_solid_sheet(path, cols=1, rows=1):
    """Every frame: fully opaque, no hole -- for the degenerate-band test,
    where the point is that a whole dest COLUMN/ROW must read as a miss
    regardless of what the source pixels underneath happen to be."""
    sheet = pygame.Surface((cols * FRAME_W, rows * FRAME_H), pygame.SRCALPHA)
    sheet.fill((255, 0, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(path))


def entry(slot="tower", frames=(3, 2), offset=(0, 0), slice_=None):
    rows = [{"animation": "idle", "frames": frames[0], "fps": 8,
             "hidden": [], "loop_start": 0, "loop_end": 0, "loop_count": 1}]
    if len(frames) > 1:
        rows.append({"animation": "attack", "frames": frames[1], "fps": 4,
                     "hidden": [], "loop_start": 0, "loop_end": 0,
                     "loop_count": 1})
    raw = {
        "sheet": f"imported/{slot}.png",
        "frame_w": FRAME_W, "frame_h": FRAME_H,
        "offset_x": offset[0], "offset_y": offset[1],
        "rows": rows,
    }
    if slice_ is not None:
        raw["slice"] = slice_
    return entry_from_dict(slot, raw)


class SheetCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.sprites_dir = Path(tmp.name) / "sprites"

    def store(self, e=None, **kwargs):
        manifest = Manifest({e.slot_key: e} if e is not None else {})
        return AssetStore(manifest=manifest, sprites_dir=self.sprites_dir,
                          **kwargs)

    def frame_colour(self, frame):
        return tuple(frame.surface.get_at((1, 1)))


class TestSlicing(SheetCase):
    def test_time_resolves_to_the_right_subframe(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry())
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         COLOURS[0][0])
        # idle at 8 fps -> 125ms per frame; t=130 sits in column 1
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 130)),
                         COLOURS[0][1])

    def test_second_row_uses_its_sheet_band(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry())
        self.assertEqual(self.frame_colour(store.frame("tower", "attack", 0)),
                         COLOURS[1][0])
        # attack at 4 fps -> 250ms per frame; t=260 sits in column 1
        self.assertEqual(self.frame_colour(store.frame("tower", "attack", 260)),
                         COLOURS[1][1])

    def test_frame_carries_size_and_offsets(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(offset=(3, -8)))
        frame = store.frame("tower", "idle", 0)
        self.assertEqual((frame.frame_w, frame.frame_h), (FRAME_W, FRAME_H))
        self.assertEqual((frame.offset_x, frame.offset_y), (3, -8))
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))

    def test_repeated_calls_hit_the_cache(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry())
        a = store.frame("tower", "idle", 0)
        b = store.frame("tower", "idle", 10)   # same column window
        self.assertIs(a.surface, b.surface)

    def test_frame_carries_slice(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(slice_=[1, 2, 3, 4]))
        self.assertEqual(store.frame("tower", "idle", 0).slice, (1, 2, 3, 4))

    def test_frame_without_a_slice_carries_none(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry())
        self.assertIsNone(store.frame("tower", "idle", 0).slice)

    def test_placeholder_frame_has_no_slice(self):
        # a "no art yet" grey X has no authored margins — it must stay on the
        # plain-scale path (test_render.test_placeholder_surfaces_do_not_leak)
        store = self.store(entry(slice_=[1, 2, 3, 4]))   # no PNG written
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 0)
        self.assertIsNone(frame.slice)

    # ── hit_opaque (A8, pixel-perfect hit test) ─────────────────────────

    def test_hit_opaque_returns_false_for_transparent_pixel(self):
        make_hole_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(frames=(1,)))
        self.assertFalse(store.hit_opaque(
            "tower", rel_xy=(0, 0), dest_size=(FRAME_W, FRAME_H)))

    def test_hit_opaque_returns_true_for_opaque_pixel(self):
        make_hole_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(frames=(1,)))
        self.assertTrue(store.hit_opaque(
            "tower", rel_xy=(1, 1), dest_size=(FRAME_W, FRAME_H)))

    def test_hit_opaque_placeholder_returns_true(self):
        store = self.store()   # empty manifest -> PLACEHOLDER
        self.assertTrue(store.hit_opaque("nope", dest_size=(10, 10)))

    def test_hit_opaque_missing_sheet_returns_true(self):
        store = self.store(entry(frames=(1,)))   # no PNG written
        with self.assertLogs("engine.assets.store", level="WARNING"):
            self.assertTrue(store.hit_opaque(
                "tower", dest_size=(FRAME_W, FRAME_H)))

    def test_hit_opaque_corrupt_sheet_returns_true(self):
        png = self.sprites_dir / "imported" / "tower.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"this is not a png")
        store = self.store(entry(frames=(1,)))
        with self.assertLogs("engine.assets.store", level="WARNING"):
            self.assertTrue(store.hit_opaque(
                "tower", dest_size=(FRAME_W, FRAME_H)))

    def test_hit_opaque_mask_is_cached_per_frame(self):
        make_hole_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(frames=(1,)))
        store.hit_opaque("tower", rel_xy=(1, 1), dest_size=(FRAME_W, FRAME_H))
        store.hit_opaque("tower", rel_xy=(2, 2), dest_size=(FRAME_W, FRAME_H))
        self.assertEqual(len(store._hit_masks), 1)

    def test_hit_opaque_different_frames_have_different_masks(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry())   # idle (row 0) + attack (row 1)
        store.hit_opaque("tower", animation="idle", dest_size=(FRAME_W, FRAME_H))
        store.hit_opaque("tower", animation="attack", dest_size=(FRAME_W, FRAME_H))
        self.assertEqual(sorted(store._hit_masks),
                         sorted([("tower", 0, 0), ("tower", 1, 0)]))
        # same key shape as _frames (store.py's existing subsurface cache)
        self.assertEqual(sorted(store._frames), sorted(store._hit_masks))

    def test_hit_opaque_at_stretched_dest(self):
        make_hole_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(frames=(1,), slice_=[2, 2, 2, 2]))
        # corner pixel maps 1:1 -> (0, 0) is still the hole -> miss
        self.assertFalse(store.hit_opaque(
            "tower", rel_xy=(0, 0), dest_size=(20, 20)))
        # centre pixel maps into the source centre, well away from the hole
        self.assertTrue(store.hit_opaque(
            "tower", rel_xy=(10, 10), dest_size=(20, 20)))

    def test_hit_opaque_out_of_bounds_returns_false(self):
        make_hole_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(frames=(1,)))
        self.assertFalse(store.hit_opaque(
            "tower", rel_xy=(100, 100), dest_size=(20, 20)))

    def test_hit_opaque_agrees_with_composite_in_a_vanished_centre_band(self):
        """A8 carry-over fix (HIGH, interrupted review): slice margins that
        sum to exactly the FRAME_W (left + right == 8) leave `_nine_patch`
        painting NOTHING in the dest's centre band once the dest is wider
        than the frame -- `hit_opaque` must agree with the actual composite
        there, not read the source's boundary pixel (a real, opaque,
        painted pixel one column over) as if the vanished band still had
        content."""
        make_solid_sheet(self.sprites_dir / "imported" / "tower.png")
        slice_ = [4, 0, 4, 0]           # left + right == FRAME_W (8) exactly
        dest_size = (20, FRAME_H)       # dest wider than the frame

        sheet_path = self.sprites_dir / "imported" / "tower.png"
        frame_surface = pygame.image.load(str(sheet_path)).subsurface(
            pygame.Rect(0, 0, FRAME_W, FRAME_H))
        composite = pygame.Surface(dest_size, pygame.SRCALPHA)
        backend.draw(composite, [DrawCall(surface=frame_surface, dest=(0, 0),
                                          size=dest_size, slice=tuple(slice_))])

        store = self.store(entry(frames=(1,), slice_=slice_))
        for x in (4, 8, 12, 15):
            painted = composite.get_at((x, 8))[3] > 0
            self.assertFalse(painted,
                             f"expected the composite transparent at x={x}")
            self.assertEqual(
                store.hit_opaque("tower", rel_xy=(x, 8), dest_size=dest_size),
                painted, f"hit_opaque must agree with the composite at x={x}")

        # sanity: the corners ARE painted and DO still register a hit
        self.assertTrue(composite.get_at((0, 8))[3] > 0)
        self.assertTrue(
            store.hit_opaque("tower", rel_xy=(0, 8), dest_size=dest_size))


class TestFrameSizePrecedence(SheetCase):
    REGISTRY = SlotRegistry({"categories": [
        {"key": "cat", "display_name": "Cat", "frame_w": 10, "frame_h": 20,
         "animations": ["idle"],
         "groups": [{"label": "G", "slots": ["tower", "unassigned"]}]},
    ]})

    def test_manifest_entry_beats_registry(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png")
        store = self.store(entry(), registry=self.REGISTRY)
        self.assertEqual(store.frame_size("tower"), (FRAME_W, FRAME_H))

    def test_registry_beats_frame_sizes_dict(self):
        store = self.store(registry=self.REGISTRY,
                           frame_sizes={"unassigned": (99, 99)})
        self.assertEqual(store.frame_size("unassigned"), (10, 20))

    def test_frame_sizes_dict_then_default(self):
        store = self.store(frame_sizes={"odd": (5, 6)})
        self.assertEqual(store.frame_size("odd"), (5, 6))
        self.assertEqual(store.frame_size("unknown"), (64, 32))

    def test_registry_placeholder_at_category_size(self):
        store = self.store(registry=self.REGISTRY)
        frame = store.frame("unassigned", "idle", 0)
        self.assertEqual(frame.surface.get_size(), (10, 20))


class TestTolerance(SheetCase):
    def test_missing_sheet_file_yields_placeholder(self):
        store = self.store(entry())   # no PNG written
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 0)
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))
        # failure is cached: second call must not raise or re-log loudly
        store.frame("tower", "idle", 0)

    def test_corrupt_png_yields_placeholder(self):
        png = self.sprites_dir / "imported" / "tower.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"this is not a png")
        store = self.store(entry())
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 0)
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))

    def test_frame_outside_sheet_bounds_yields_placeholder(self):
        make_sheet(self.sprites_dir / "imported" / "tower.png", cols=3, rows=1)
        # manifest claims 10 columns; t in column 5's window is off-sheet
        store = self.store(entry(frames=(10,)))
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 5 * 125 + 10)
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))
        # in-bounds columns of the same sheet still resolve
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         COLOURS[0][0])

    def test_no_sprites_dir_yields_placeholder(self):
        manifest = Manifest({"tower": entry()})
        store = AssetStore(manifest=manifest)   # sprites_dir omitted
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 0)
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))


if __name__ == "__main__":
    unittest.main()
