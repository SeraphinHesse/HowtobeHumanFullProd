"""G0 render profiler — where does a frame actually go?

Phase G0 of `planning/GpuAndMasterSheetsPLAN.md` exists to stop Part A
rewriting the wrong thing. It answers, in numbers: of `GroundCache.ensure`,
the sprite submit, `Renderer.flush` and `display.flip`, which one dominates a
frame — and how much memory the asset store's per-slot sheet cache wastes on
duplicate decodes of one PNG.

**This is a RENDER harness, not the game.** It builds the same render stack
`game/main.py` builds (same map doc, same `AssetStore`, same `Renderer`, same
`GroundCache`, same `BACKGROUND`, same SCALED window) and drives it with a
controlled sprite population instead of a live `Session`. That is deliberate:
the render cost of an enemy sprite is identical whether a real `Enemy` object
or this harness produced the `RenderItem`, and holding the population fixed is
the only way successive runs compare. Simulation cost is NOT measured here —
`game/main.py`'s own per-frame `sim` bucket already measures that on real
hardware, and G0's verdict reads both.

Deterministic by construction: a fixed map file (never `active_map.json` — a
baseline that moves when a designer flips the active map is not a baseline), a
seeded RNG for sprite placement, a fixed pan path, and a fixed frame count.

Output is a table on stdout; nothing is written to `data/`. Run it windowed
(the default) — `display.flip` under `SDL_VIDEODRIVER=dummy` is close to free
and would make the flip bucket a lie.

    py tools/profile_render.py
    py tools/profile_render.py --enemies 300 --zoom max --pan
    py tools/profile_render.py --map data/maps/holex.json --frames 600

**G4 (§2.9b): the same harness on either backend, plus the overlay pass.**
`--backend={surface,gpu}` selects the SAME two stacks `game/main.py` builds —
it calls `game.main._build_render_stack` rather than rebuilding the GPU wiring,
so the profiled stack cannot drift from the shipped one. A silent D8 fallback
(GPU asked for, Surface delivered) ABORTS instead of measuring: a row labelled
`gpu` that is really the CPU blitter would be a lie.

`--overlays N` submits N tile diamonds shaped exactly like `game/ui/widgets.py`'s
`submit_tile_diamond_fill`, and the harness then runs EVERY case twice — once
with 0 overlays and once with N over the identical (deterministic) frame
sequence. **`flush(N) − flush(0)` is the overlay pass**, and it is the number
the phase is after: `backend.py` draws overlays straight onto the target and
clips, while `backend_gpu.py` rasterizes each one into an unclipped bounding-box
SRCALPHA scratch surface and uploads it per call, per frame, uncached
(`backend_gpu.py:110-156`) — and PR #122's `WorldFill` routes every tile
highlight and wall segment through that path.

`--far-polyline` adds the pathological case: ONE polyline whose second point is
far off-screen (world→screen conversion does not clip), which asks `backend_gpu`
for a scratch surface that wide every frame. Its bounding box is printed.

    py tools/profile_render.py --backend=gpu --overlays 40 --far-polyline
"""
import argparse
import gc
import random
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pygame  # noqa: E402

from engine import data_io, tilemap  # noqa: E402
from engine.assets import load_manifest, load_registry  # noqa: E402
from engine.assets.store import AssetStore  # noqa: E402
from engine.coords import load_coordinate_system  # noqa: E402
from engine.render.item import RenderItem  # noqa: E402
from game.core import load_balance  # noqa: E402
# _build_render_stack is THE host's frame-target + Renderer + ground-cache
# construction (G4 §2.1). Importing it is deliberate: a second GPU construction
# path here would profile a stack the game does not ship.
from game.main import BACKGROUND, _build_render_stack  # noqa: E402

# The committed map G0's baseline is taken on. NOT the active map.
DEFAULT_MAP = "data/maps/first_light.json"
# Slots the harness populates the world with — real entries with real art, so
# frame sizes and per-frame `assets.frame()` lookups cost what they cost in
# game. Enemies dominate a late-round frame; the rest stand in for placed
# buildings.
ENEMY_SLOTS = ("enemy_stage_1_v1", "enemy_stage_2", "enemy_stage_3", "raider")
BUILDING_SLOTS = ("flute_player_t1_lvl1", "base_level_1")
WARMUP_FRAMES = 30  # discarded: first-frame sheet decodes + cache fills
CAPTION = "G0 render profile"
# The overlay diamond, in the shape game/ui/widgets.py's
# submit_tile_diamond_fill produces: a translucent fill plus a border, i.e.
# ONE OverlayPolys + ONE OverlayLines DrawCall per diamond.
OVERLAY_FILL = (80, 180, 255, 90)
OVERLAY_BORDER = (255, 255, 255, 160)
# --far-polyline: how many TILES past the first visible tile the off-screen
# point sits. The renderer converts world->screen with no clipping, so
# backend_gpu's scratch surface is the whole bounding box of that line.
FAR_POLYLINE_TILES = 50
FAR_POLYLINE_COLOR = (255, 0, 255)


def rss_bytes():
    """Resident set size of this process, or None where unavailable.

    Windows-native via psapi so the harness needs no psutil (it is not a
    declared dependency and G0 must not add one for a throwaway measurement).
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        handle = kernel32.GetCurrentProcess()
        # Modern Windows exports this from kernel32 as K32GetProcessMemoryInfo;
        # psapi.dll is the older home. Try both before giving up.
        fn = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if fn is None:
            fn = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        if not fn(handle, ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    except Exception:
        return None


def sheet_stats(assets, manifest):
    """(loaded sheet Surfaces, distinct source PNGs behind them, wasted bytes).

    `AssetStore._sheets` is keyed by SLOT KEY today, so ten slots sharing one
    PNG hold ten Surfaces of the same pixels. The gap between the two counts is
    exactly what phase M2's re-key onto `entry.sheet` removes; the byte figure
    is what it gives back.
    """
    loaded = 0
    by_path = {}
    for slot_key, surface in assets._sheets.items():
        if not hasattr(surface, "get_size"):
            continue  # _LOAD_FAILED sentinel
        loaded += 1
        entry = manifest.entry(slot_key)
        path = getattr(entry, "sheet", None) if entry is not None else None
        by_path.setdefault(path, []).append(surface)
    wasted = 0
    for path, surfaces in by_path.items():
        if path is None:
            continue
        for surface in surfaces[1:]:  # every copy after the first is duplicate
            w, h = surface.get_size()
            wasted += w * h * surface.get_bytesize()
    return loaded, len(by_path), wasted


def warm_store_report(data_dir):
    """Force EVERY manifest slot's sheet into the store and report the cost.

    This is the duplicate-decode number Part A claims to fix, measured over the
    whole manifest rather than the handful of slots one profiled frame happens
    to touch. `_sheets` is keyed by slot key, so N slots sharing one PNG hold N
    Surfaces; `distinct` is what the M2 re-key onto `entry.sheet` would hold
    instead.
    """
    registry = load_registry(data_dir)
    manifest = load_manifest(data_dir / "sprites" / "asset_manifest.json")
    assets = AssetStore(manifest=manifest, registry=registry,
                        sprites_dir=data_dir / "sprites")
    before = rss_bytes()
    slots = sorted(manifest.slots())
    for slot_key in slots:
        try:
            assets.frame(slot_key, "idle", 0)  # pulls the sheet in
        except Exception:
            pass
    after = rss_bytes()
    loaded, distinct, wasted = sheet_stats(assets, manifest)
    total_bytes = 0
    for surface in assets._sheets.values():
        if hasattr(surface, "get_size"):
            w, h = surface.get_size()
            total_bytes += w * h * surface.get_bytesize()
    print()
    print("=== asset store, warm (every manifest slot resolved) ===")
    print(f"  manifest entries          : {len(slots)}")
    print(f"  sheet Surfaces held       : {loaded}")
    print(f"  distinct source PNGs      : {distinct}")
    print(f"  duplicate Surfaces        : {loaded - distinct}")
    print(f"  sheet pixel memory        : {total_bytes / (1024 * 1024):.1f} MB")
    print(f"  of which duplicate decode : {wasted / (1024 * 1024):.1f} MB")
    if before is not None and after is not None:
        print(f"  process RSS cold -> warm  : "
              f"{before / (1024 * 1024):.0f} MB -> {after / (1024 * 1024):.0f} MB")


def build_stack(data_dir, map_path, view_w, view_h, backend="surface"):
    """The same construction `game/main.py` performs, on a NAMED map.

    The frame target, the `Renderer` (and with it the backend) and the ground
    cache come from `game.main._build_render_stack` — the host's own G4 seam —
    so `--backend=gpu` here profiles exactly the stack `py game/main.py
    --backend=gpu` runs: `_sdl2` Window + `Renderer(window,
    target_texture=True)` + `GroundCacheGpu` + `Renderer(cs, assets,
    backend=backend_gpu.draw)`.

    `_build_render_stack` implements D8: a GPU failure falls back to the whole
    Surface stack rather than raising. That is right for a player and WRONG for
    a measurement, so a fallback aborts here instead — an unlabelled Surface row
    in a GPU column would invalidate every comparison in the phase.
    """
    map_doc = tilemap.load_map(
        map_path, data_dir / "schemas" / "map_file.schema.json")
    core_balance = load_balance(data_dir, "core")
    cs = load_coordinate_system(
        data_dir, map_cols=map_doc.cols, map_rows=map_doc.rows,
        zoom_levels=core_balance["Camera"]["zoom_levels"],
        default_zoom=core_balance["Camera"]["default_zoom"])
    if map_doc.camera_start is not None:
        cs.center_on(map_doc.camera_start["col"], map_doc.camera_start["row"],
                     view_w, view_h)
    else:
        cs.clamp(view_w, view_h)
    registry = load_registry(data_dir)
    manifest = load_manifest(data_dir / "sprites" / "asset_manifest.json")
    assets = AssetStore(manifest=manifest, registry=registry,
                        sprites_dir=data_dir / "sprites")
    presenter, renderer, ground_cache, log_line = _build_render_stack(
        backend, view_w, view_h, CAPTION, "windowed", cs, assets)
    if presenter.name != backend:
        presenter.close()
        raise SystemExit(
            f"--backend={backend} requested but the host fell back:\n  "
            f"{log_line}\nRefusing to profile a fallback stack under the "
            f"requested backend's label.")
    return (map_doc, cs, manifest, assets, presenter, renderer, ground_cache,
            log_line)


def sprite_population(map_doc, n_enemies, n_buildings, seed=1234):
    """A fixed, seeded set of world RenderItems — the controlled load.

    Positions are drawn once and reused every frame, so the only thing moving
    between frames is the camera. Enemies land on the `entities` layer and
    buildings on `deco`, matching how the game submits them.
    """
    rng = random.Random(seed)
    items = []
    for i in range(n_enemies):
        items.append(RenderItem(
            slot_key=ENEMY_SLOTS[i % len(ENEMY_SLOTS)],
            world_pos=(rng.uniform(0, map_doc.cols - 1),
                       rng.uniform(0, map_doc.rows - 1)),
            layer="entities",
            anim_time_ms=rng.randrange(0, 2000),
            fit_tiles=1.0))
    for i in range(n_buildings):
        items.append(RenderItem(
            slot_key=BUILDING_SLOTS[i % len(BUILDING_SLOTS)],
            world_pos=(rng.uniform(0, map_doc.cols - 1),
                       rng.uniform(0, map_doc.rows - 1)),
            layer="deco",
            fit_tiles=1.0))
    return items


def summarize(samples_ms):
    """(mean, p95) in ms. p95 is the nearest-rank order statistic — with a few
    hundred samples an interpolated percentile would imply precision the
    measurement does not have."""
    if not samples_ms:
        return 0.0, 0.0
    ordered = sorted(samples_ms)
    idx = min(len(ordered) - 1, int(round(0.95 * len(ordered))) - 1)
    return statistics.fmean(samples_ms), ordered[max(idx, 0)]


def _submit_overlays(renderer, count, cmin, cmax, rmin, rmax):
    """`count` tile diamonds over the first visible tiles, in the exact shape
    `game/ui/widgets.py::submit_tile_diamond_fill` produces (a `WorldFill` with
    a fill AND a border → one OverlayPolys + one OverlayLines DrawCall each).

    On-screen tiles on purpose: `backend.py` clips to the target and
    `backend_gpu.py` does not, so overlays that are off-screen would compare
    the two backends on different amounts of work.
    """
    left = count
    for row in range(rmin, rmax + 1):
        for col in range(cmin, cmax + 1):
            if left <= 0:
                return
            renderer.submit_world_fill(
                [(col, row), (col + 1, row), (col + 1, row + 1),
                 (col, row + 1)],
                world_pos=(col, row), color=OVERLAY_FILL,
                border=OVERLAY_BORDER, border_width=2)
            left -= 1


def _far_polyline_bbox(cs, cmin, rmin):
    """The screen-space bounding box `backend_gpu` would allocate a scratch
    SRCALPHA surface for, for the --far-polyline case."""
    p0 = cs.world_to_screen(float(cmin), float(rmin))
    p1 = cs.world_to_screen(float(cmin + FAR_POLYLINE_TILES), float(rmin))
    w = int(abs(p1[0] - p0[0])) + 3
    h = int(abs(p1[1] - p0[1])) + 3
    return w, h


def _measure_pass(data_dir, map_path, view_w, view_h, backend, n_enemies,
                  n_buildings, zoom_mode, frames, pan, overlays,
                  far_polyline):
    """One measured run of the fixed frame sequence. Every determinism
    property of the G0 harness holds: fixed map file, seeded placement, fixed
    serpentine pan, WARMUP_FRAMES discarded + `frames` measured. Each pass
    builds its OWN stack, so the 0-overlay and N-overlay passes see the
    identical camera path from the identical starting state."""
    (map_doc, cs, manifest, assets, presenter, renderer,
     ground_cache, log_line) = build_stack(
        data_dir, map_path, view_w, view_h, backend)
    try:
        if zoom_mode == "max":
            cs.set_zoom(max(cs.geometry.zoom_levels))
            cs.clamp(view_w, view_h)
        elif zoom_mode == "min":
            cs.set_zoom(min(cs.geometry.zoom_levels))
            cs.clamp(view_w, view_h)
        items = sprite_population(map_doc, n_enemies, n_buildings)
        band = (lambda dmn, dmx, smn, smx:
                tilemap.band_render_items(map_doc, dmn, dmx, smn, smx))

        buckets = {"ground": [], "submit": [], "world": [], "hud": [],
                   "composite": [], "present": [], "backend": []}
        total = []
        far_bbox = None
        gc.collect()
        for frame in range(frames + WARMUP_FRAMES):
            pygame.event.pump()  # keep the OS from marking the window dead
            if pan:
                # A fixed serpentine pan: the ground cache's whole point is
                # that cost tracks pan SPEED, so a static camera would measure
                # its best case and miss the case the user is complaining
                # about.
                cs.pan(3 if (frame // 60) % 2 == 0 else -3, 1)
                cs.clamp(view_w, view_h)
            t0 = time.perf_counter()
            presenter.begin_frame()
            ground_cache.ensure(view_w, view_h, band)
            # GroundCacheGpu.blit ignores its target by design (it draws
            # through the SDL Renderer it was built with) — the same call is
            # correct on both paths, exactly as in game/main.py.
            ground_cache.blit(presenter.world_target)
            t1 = time.perf_counter()
            cmin, cmax, rmin, rmax = cs.visible_tile_window(
                view_w, view_h, margin=4)
            for item in tilemap.visible_render_items(
                    map_doc, cmin, cmax, rmin, rmax, terrain=False):
                renderer.submit(item)
            for item in items:
                renderer.submit(item)
            if overlays:
                _submit_overlays(renderer, overlays, cmin, cmax, rmin, rmax)
            if far_polyline:
                renderer.submit_overlay_lines(
                    [(float(cmin), float(rmin)),
                     (float(cmin + FAR_POLYLINE_TILES), float(rmin))],
                    FAR_POLYLINE_COLOR, width=2)
                if far_bbox is None:
                    far_bbox = _far_polyline_bbox(cs, cmin, rmin)
            t2 = time.perf_counter()
            # hud_target is None on the Surface path (the historical single
            # flat list) and the host's SRCALPHA HUD surface on the GPU path —
            # the harness submits no HUD items, so `hud` measures 0.0 and
            # `composite` measures the per-frame texture upload+draw the GPU
            # host pays whether or not the HUD drew anything.
            renderer.flush(presenter.world_target,
                           hud_target=presenter.hud_target)
            t3 = time.perf_counter()
            presenter.end_frame()
            t4 = time.perf_counter()
            if frame >= WARMUP_FRAMES:
                split = renderer.last_flush_ms
                composite = presenter.last_composite_ms
                buckets["ground"].append((t1 - t0) * 1000)
                buckets["submit"].append((t2 - t1) * 1000)
                # `world` = everything in flush except the HUD backend call —
                # the depth sort + DrawCall build + the world backend, i.e.
                # exactly what G0's `flush` column contained, so the two are
                # directly comparable. `backend` is the world backend call
                # alone (renderer.last_flush_ms["world"]).
                buckets["world"].append((t3 - t2) * 1000 - split["hud"])
                buckets["hud"].append(split["hud"])
                buckets["backend"].append(split["world"])
                buckets["composite"].append(composite)
                buckets["present"].append((t4 - t3) * 1000 - composite)
                total.append((t4 - t0) * 1000)

        loaded, distinct, wasted = sheet_stats(assets, manifest)
        return {
            "map": Path(map_path).name,
            "dims": f"{map_doc.cols}x{map_doc.rows}",
            "zoom": cs.camera.zoom,
            "sprites": len(items),
            "raw": buckets,
            "buckets": {k: summarize(v) for k, v in buckets.items()},
            "total": summarize(total),
            "fps": (1000.0 / statistics.fmean(total)) if total else 0.0,
            "sheets_loaded": loaded,
            "sheets_distinct": distinct,
            "sheet_waste_mb": wasted / (1024 * 1024),
            "rss_mb": (rss_bytes() or 0) / (1024 * 1024),
            "far_bbox": far_bbox,
            "log_line": log_line,
        }
    finally:
        presenter.close()


def run_case(label, data_dir, map_path, view_w, view_h, n_enemies,
             n_buildings, zoom_mode, frames, pan, backend="surface",
             overlays=0, far_polyline=False):
    """One table row. With overlays (or the far polyline) asked for, the case
    runs TWICE over the identical frame sequence — 0 overlays, then N — and
    the reported `overlay_delta` is `world(N) − world(0)`. That delta IS the
    overlay pass, and it is the only honest way to get it: an overlay's cost
    is inside the same backend call as 1016 sprites."""
    extra = bool(overlays) or far_polyline
    baseline = None
    if extra:
        baseline = _measure_pass(
            data_dir, map_path, view_w, view_h, backend, n_enemies,
            n_buildings, zoom_mode, frames, pan, 0, False)
    result = _measure_pass(
        data_dir, map_path, view_w, view_h, backend, n_enemies, n_buildings,
        zoom_mode, frames, pan, overlays, far_polyline)
    result["label"] = label
    result["backend"] = backend
    result["overlays"] = overlays
    result["far_polyline"] = far_polyline
    result["overlay_delta"] = (
        None if baseline is None
        else result["buckets"]["world"][0] - baseline["buckets"]["world"][0])
    result["baseline_world"] = (
        None if baseline is None else baseline["buckets"]["world"][0])
    return result


_COLUMNS = ("ground", "submit", "world", "hud", "composite", "present")


def print_table(results):
    head = (f"{'case':<26}{'bk':<8}{'map':<16}{'zoom':>5}{'spr':>6}"
            + "".join(f"{c:>16}" for c in _COLUMNS)
            + f"{'ovl d':>8}{'frame':>16}{'fps':>7}")
    print()
    print(head)
    print(f"{'':<26}{'':<8}{'':<16}{'':>5}{'':>6}"
          + "".join(f"{'mean / p95':>16}" for _ in _COLUMNS)
          + f"{'mean':>8}{'mean / p95':>16}{'':>7}")
    print("-" * len(head))
    for r in results:
        cells = ""
        for key in _COLUMNS:
            mean, p95 = r["buckets"][key]
            cells += f"{mean:>7.2f} /{p95:>7.2f}"
        delta = r.get("overlay_delta")
        cells += "       -" if delta is None else f"{delta:>8.2f}"
        mean, p95 = r["total"]
        cells += f"{mean:>7.2f} /{p95:>7.2f}"
        print(f"{r['label']:<26}{r.get('backend', 'surface'):<8}"
              f"{r['map']:<16}{r['zoom']:>5.2f}"
              f"{r['sprites']:>6}{cells}{r['fps']:>7.1f}")
    print()
    for r in results:
        print(f"{r['label']:<26}{r.get('backend', ''):<8} sheets: "
              f"{r['sheets_loaded']:>3} Surfaces "
              f"over {r['sheets_distinct']:>3} distinct PNGs  "
              f"(duplicate decode waste {r['sheet_waste_mb']:.1f} MB)  "
              f"RSS {r['rss_mb']:.0f} MB  "
              f"backend-only world {r['buckets']['backend'][0]:.2f} ms")
    for r in results:
        if r.get("far_bbox") is not None:
            w, h = r["far_bbox"]
            print(f"{r['label']:<26}{r.get('backend', ''):<8} far polyline: "
                  f"{FAR_POLYLINE_TILES} tiles off-screen -> scratch bbox "
                  f"{w}x{h} px ({w * h * 4 / (1024 * 1024):.1f} MB SRCALPHA), "
                  f"allocated + uploaded EVERY frame on the gpu backend")
    print()
    print("ground = GroundCache(.Gpu).ensure + blit | submit = tile emit + "
          "Renderer.submit (+ overlay submit) | world = Renderer.flush minus "
          "the HUD backend call (depth sort + DrawCall build + the world "
          "backend, i.e. G0's `flush` column) | hud = the Surface HUD backend "
          "call (0 here: this harness submits no HUD) | composite = the GPU "
          "HUD texture update+draw | present = display.flip / "
          "renderer.present | ovl d = world(N overlays) - world(0), the "
          "overlay pass")


def build_parser():
    """The CLI, separated from `main` so it can be exercised without booting
    pygame or profiling anything."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--map", default=DEFAULT_MAP,
                    help=f"map file to profile (default {DEFAULT_MAP})")
    ap.add_argument("--data-dir", default=str(REPO / "data"))
    ap.add_argument("--frames", type=int, default=300,
                    help="measured frames per case (default 300)")
    ap.add_argument("--enemies", type=int, default=120,
                    help="enemy sprites on the board (default 120)")
    ap.add_argument("--buildings", type=int, default=40)
    ap.add_argument("--zoom", default=None,
                    choices=("min", "default", "max"),
                    help="single-case zoom; omit to sweep default+max")
    ap.add_argument("--pan", action="store_true",
                    help="pan the camera every frame (ground-cache scroll path)")
    ap.add_argument("--static", action="store_true",
                    help="force the static-camera case only")
    ap.add_argument("--warm-store", action="store_true",
                    help="report warm asset-store memory instead of profiling")
    ap.add_argument("--backend", default="surface", choices=("surface", "gpu"),
                    help="frame target + render backend (default surface); "
                         "gpu builds game/main.py's _sdl2 Window + "
                         "Renderer(target_texture=True) + GroundCacheGpu stack")
    ap.add_argument("--overlays", type=int, default=0, metavar="N",
                    help="submit N tile diamonds per frame and report "
                         "world(N) - world(0) as the overlay pass (runs each "
                         "case twice)")
    ap.add_argument("--far-polyline", action="store_true",
                    help="also submit ONE polyline with a point far "
                         "off-screen (the unclipped-scratch pathological case)")
    return ap


def parse_args(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.overlays < 0:
        ap.error("--overlays must be >= 0")
    return args


def main(argv=None):
    args = parse_args(argv)

    data_dir = Path(args.data_dir)
    display = data_io.load_validated(
        data_dir / "display.json", data_dir / "schemas" / "display.schema.json")
    view_w, view_h = display["window_w"], display["window_h"]
    pygame.init()
    # NOTE: no pygame.display.set_mode here. The window belongs to the
    # presenter now — on the GPU path there is no display surface at all (an
    # SDL Renderer cannot attach to the display-module window), so creating one
    # up front would be a second, unused frame target.

    if args.warm_store:
        warm_store_report(data_dir)
        pygame.quit()
        return 0

    if args.zoom is not None:
        zooms = [args.zoom]
    else:
        zooms = ["default", "max"]
    if args.static:
        pans = [False]
    elif args.pan:
        pans = [True]
    else:
        pans = [False, True]

    results = []
    for zoom_mode in zooms:
        for pan in pans:
            label = f"zoom={zoom_mode} {'panning' if pan else 'static'}"
            results.append(run_case(
                label, data_dir, args.map, view_w, view_h,
                args.enemies, args.buildings, zoom_mode, args.frames, pan,
                backend=args.backend, overlays=args.overlays,
                far_polyline=args.far_polyline))
            print(f"  ...{label} [{args.backend}] done", flush=True)
    if results:
        print(results[0]["log_line"])
    print_table(results)
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
