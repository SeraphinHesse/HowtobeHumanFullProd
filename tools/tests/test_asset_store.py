"""AssetStore sheet slicing + tolerance (E-35/E-36/E-37) — pygame side.

Synthetic sheets (distinct solid-colour frames) in temp dirs; nothing here
touches the repo's data/. SDL dummy drivers as everywhere else.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def make_grid_sheet(path, cols=3, rows=6):
    """A taller sheet whose every frame carries a colour encoding its (row,
    col) — for the `row_start` window tests, where the point is WHICH sheet
    row got cut."""
    sheet = pygame.Surface((cols * FRAME_W, rows * FRAME_H), pygame.SRCALPHA)
    for r in range(rows):
        for c in range(cols):
            sheet.fill(grid_colour(r, c),
                       pygame.Rect(c * FRAME_W, r * FRAME_H, FRAME_W, FRAME_H))
    path.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(path))


def surface_bytes(surface):
    """Raw RGBA pixels — `tostring` is deprecated since pygame 2.3."""
    to_bytes = getattr(pygame.image, "tobytes", None) or pygame.image.tostring
    return to_bytes(surface, "RGBA")


def grid_colour(row, col):
    return (10 + 10 * row, 100 + 10 * col, 200, 255)


def entry(slot="tower", frames=(3, 2), offset=(0, 0), slice_=None,
          row_start=None, sheet=None, column=None, column_mode=None,
          column_width=None):
    rows = [{"animation": "idle", "frames": frames[0], "fps": 8,
             "hidden": [], "loop_start": 0, "loop_end": 0, "loop_count": 1}]
    if len(frames) > 1:
        rows.append({"animation": "attack", "frames": frames[1], "fps": 4,
                     "hidden": [], "loop_start": 0, "loop_end": 0,
                     "loop_count": 1})
    raw = {
        "sheet": sheet if sheet is not None else f"imported/{slot}.png",
        "frame_w": FRAME_W, "frame_h": FRAME_H,
        "offset_x": offset[0], "offset_y": offset[1],
        "rows": rows,
    }
    if slice_ is not None:
        raw["slice"] = slice_
    if row_start is not None:
        raw["row_start"] = row_start
    if column is not None:
        raw["column"] = column
    if column_mode is not None:
        raw["column_mode"] = column_mode
    if column_width is not None:
        raw["column_width"] = column_width
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
                         sorted([("tower", 0, 0, 0), ("tower", 1, 0, 0)]))
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

    def test_hit_opaque_agrees_with_composite_for_a_resampled_corner(self):
        """A8 carry-over fix #2 (MEDIUM, same file/bug class): a corner
        whose dest width shrinks below its (already source-clamped) margin
        is resampled by `_nine_patch` via `pygame.transform.scale`, not
        blitted 1:1 -- `hit_opaque` must read the source pixel the
        composite actually sampled, not the naive rel_x-as-1:1 pixel.

        A 20x10 frame with left+right margins of 8 each, shrunk into a
        10x10 dest: `clamp_pair(8, 8, 10) -> (5, 5)`, so the 8px corner
        resamples to 5px. A single transparent 'hole' column at source x=1
        (opaque everywhere else) is skipped entirely by the real nearest-
        neighbour resample at dest x=1 (it samples source x=2 instead) --
        the naive pre-fix mapping (sx = rel_x = 1) would have read the hole
        and returned False where the composite is actually opaque."""
        frame_w, frame_h = 20, 10
        sheet_path = self.sprites_dir / "imported" / "wide.png"
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        sheet = pygame.Surface((frame_w, frame_h), pygame.SRCALPHA)
        sheet.fill((255, 0, 0, 255))
        sheet.fill((255, 0, 0, 0), (1, 0, 1, frame_h))   # the hole at x=1
        pygame.image.save(sheet, str(sheet_path))

        slice_ = [8, 0, 8, 0]
        dest_size = (10, 10)
        raw = {"sheet": "imported/wide.png", "frame_w": frame_w,
               "frame_h": frame_h, "offset_x": 0, "offset_y": 0,
               "slice": slice_,
               "rows": [{"animation": "idle", "frames": 1, "fps": 8,
                        "hidden": [], "loop_start": 0, "loop_end": 0,
                        "loop_count": 1}]}
        manifest = Manifest({"wide": entry_from_dict("wide", raw)})
        store = AssetStore(manifest=manifest, sprites_dir=self.sprites_dir)

        frame_surface = pygame.image.load(str(sheet_path)).subsurface(
            pygame.Rect(0, 0, frame_w, frame_h))
        composite = pygame.Surface(dest_size, pygame.SRCALPHA)
        backend.draw(composite, [DrawCall(surface=frame_surface, dest=(0, 0),
                                          size=dest_size, slice=tuple(slice_))])

        for x in range(dest_size[0]):
            painted = composite.get_at((x, 5))[3] > 0
            self.assertEqual(
                store.hit_opaque("wide", rel_xy=(x, 5), dest_size=dest_size),
                painted, f"hit_opaque must agree with the composite at x={x}")
        # the divergence this test exists to catch: dest x=1 IS painted
        # (the resample skips the hole), matching hit_opaque == True
        self.assertTrue(composite.get_at((1, 5))[3] > 0)
        self.assertTrue(
            store.hit_opaque("wide", rel_xy=(1, 5), dest_size=dest_size))


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


class TestRowStartWindow(SheetCase):
    """M2: `row_start` windows an entry onto a band of its sheet. Row indices
    above the store keep meaning 'row i of this entry's rows[]'."""

    def test_row_start_offsets_the_sheet_row(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png", rows=6)
        store = self.store(entry(row_start=3))
        # entry row 0 (idle) -> sheet row 3
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         grid_colour(3, 0))
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 130)),
                         grid_colour(3, 1))
        # entry row 1 (attack) -> sheet row 4
        self.assertEqual(self.frame_colour(store.frame("tower", "attack", 0)),
                         grid_colour(4, 0))

    def test_no_row_start_cuts_exactly_where_it_always_did(self):
        png = self.sprites_dir / "imported" / "tower.png"
        make_grid_sheet(png, rows=6)
        e = entry()
        self.assertEqual(e.row_start, 0)   # omitted => 0 => unchanged entry
        store = self.store(e)
        raw = pygame.image.load(str(png))
        for row, animation in ((0, "idle"), (1, "attack")):
            expected = raw.subsurface(
                pygame.Rect(0, row * FRAME_H, FRAME_W, FRAME_H))
            got = store.frame("tower", animation, 0).surface
            self.assertEqual(surface_bytes(got), surface_bytes(expected))

    def test_window_past_the_sheet_yields_placeholder(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png", rows=2)
        store = self.store(entry(row_start=5))
        with self.assertLogs("engine.assets.store", level="WARNING"):
            frame = store.frame("tower", "idle", 0)
        self.assertEqual(frame.surface.get_size(), (FRAME_W, FRAME_H))


class TestColumnBlock(SheetCase):
    """MasterSheetColumnsPLAN C2: `column`/`column_mode`/`column_width` cut a
    master COLUMN block, the horizontal twin of `row_start`. Column indices
    above the store keep meaning 'frame j of this entry's own rows[]'."""

    def test_column_width_and_column_pick_the_block(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(entry(column_width=4, column=2))
        # entry idle frame 0 -> block 2 -> sheet frame-col 2*4 + 0 = 8
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         grid_colour(0, 8))

    def test_no_column_width_cuts_exactly_where_it_always_did(self):
        # PIN 1: the compatibility argument for the whole feature — an entry
        # with no column_width resolves byte-identically to today's pixels.
        png = self.sprites_dir / "imported" / "tower.png"
        make_grid_sheet(png, rows=2)
        e = entry()
        self.assertEqual(e.column_width, 0)   # omitted => 0 => unchanged entry
        store = self.store(e)
        raw = pygame.image.load(str(png))
        for row, animation in ((0, "idle"), (1, "attack")):
            expected = raw.subsurface(
                pygame.Rect(0, row * FRAME_H, FRAME_W, FRAME_H))
            got = store.frame("tower", animation, 0).surface
            self.assertEqual(surface_bytes(got), surface_bytes(expected))

    def test_caller_column_overrides_stored_when_not_manual(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(
            entry(column_width=4, column=1, column_mode="season"))
        # no caller column -> stored column (1) wins
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         grid_colour(0, 4))
        # caller column (2) overrides the stored one
        self.assertEqual(
            self.frame_colour(store.frame("tower", "idle", 0, column=2)),
            grid_colour(0, 8))

    def test_caller_column_ignored_when_manual(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(
            entry(column_width=4, column=1, column_mode="manual"))
        self.assertEqual(
            self.frame_colour(store.frame("tower", "idle", 0, column=2)),
            grid_colour(0, 4))   # stored column still wins

    def test_block_past_the_sheet_clamps_to_last_column(self):
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)   # 3 blocks of width 4: 0, 1, 2
        store = self.store(entry(column_width=4, column=5))
        self.assertEqual(self.frame_colour(store.frame("tower", "idle", 0)),
                         grid_colour(0, 8))   # clamped to block 2

    def test_negative_caller_column_clamps_to_the_first_column(self):
        # D7 clamps on BOTH sides: a negative block would build a negative
        # rect x and degrade to the grey-X placeholder instead of column 0.
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(entry(column_width=4, column=1, column_mode="season"))
        self.assertEqual(
            self.frame_colour(store.frame("tower", "idle", 0, column=-3)),
            grid_colour(0, 0))

    def test_two_columns_of_one_slot_return_different_surfaces(self):
        # PIN 2: the cache key must carry the resolved block, or a second
        # column silently gets the first column's pixels forever.
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(
            entry(column_width=4, column=0, column_mode="season"))
        a = surface_bytes(store.frame("tower", "idle", 0, column=0).surface)
        b = surface_bytes(store.frame("tower", "idle", 0, column=2).surface)
        self.assertNotEqual(a, b)

    def test_season_zero_uses_column_zero_not_the_stored_column(self):
        # N2 regression: `0` is a REAL live column (the FIRST season), not
        # "unset". Only `None` falls back to the stored column, so any
        # `column or entry.column` / truthiness test anywhere in the chain
        # cuts from block 2 here and fails.
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=12, rows=2)
        store = self.store(
            entry(column_width=4, column=2, column_mode="season"))
        self.assertEqual(
            self.frame_colour(store.frame("tower", "idle", 0, column=0)),
            grid_colour(0, 0))

    def test_live_season_clamps_on_a_two_column_sheet(self):
        # D7 clamp driven by the LIVE caller column (the clamp test above
        # drives it from the STORED column, a different branch): a 2-block
        # sheet holds at its last block rather than wrapping or grey-X-ing.
        make_grid_sheet(self.sprites_dir / "imported" / "tower.png",
                        cols=8, rows=2)   # 2 blocks of width 4: 0, 1
        store = self.store(
            entry(column_width=4, column=0, column_mode="season"))
        self.assertEqual(
            self.frame_colour(store.frame("tower", "idle", 0, column=5)),
            grid_colour(0, 4))   # clamped to block 1


class TestSheetDedup(SheetCase):
    """M2: `_sheets` is keyed by source path — one PNG decodes once, however
    many slots window it."""

    def test_two_slots_on_one_sheet_share_one_decoded_surface(self):
        make_grid_sheet(self.sprites_dir / "master" / "pack.png", rows=6)
        a = entry(slot="a", sheet="master/pack.png", row_start=0)
        b = entry(slot="b", sheet="master/pack.png", row_start=2)
        store = AssetStore(manifest=Manifest({"a": a, "b": b}),
                           sprites_dir=self.sprites_dir)
        with mock.patch.object(pygame.image, "load",
                               wraps=pygame.image.load) as spy:
            frame_a = store.frame("a", "idle", 0)
            frame_b = store.frame("b", "idle", 0)
            self.assertEqual(spy.call_count, 1)   # one file, one decode
        self.assertIs(frame_a.surface.get_parent(),
                      frame_b.surface.get_parent())
        # frames stay slot-keyed: each slot still gets its own window
        self.assertEqual(self.frame_colour(frame_a), grid_colour(0, 0))
        self.assertEqual(self.frame_colour(frame_b), grid_colour(2, 0))


if __name__ == "__main__":
    unittest.main()
