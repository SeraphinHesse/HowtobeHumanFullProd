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


def entry(slot="tower", frames=(3, 2), offset=(0, 0)):
    rows = [{"animation": "idle", "frames": frames[0], "fps": 8,
             "hidden": [], "loop_start": 0, "loop_end": 0, "loop_count": 1}]
    if len(frames) > 1:
        rows.append({"animation": "attack", "frames": frames[1], "fps": 4,
                     "hidden": [], "loop_start": 0, "loop_end": 0,
                     "loop_count": 1})
    return entry_from_dict(slot, {
        "sheet": f"imported/{slot}.png",
        "frame_w": FRAME_W, "frame_h": FRAME_H,
        "offset_x": offset[0], "offset_y": offset[1],
        "rows": rows,
    })


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
