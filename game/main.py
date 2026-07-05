"""How To Be Human — window host (G-1). The ONLY entry point:

    py game/main.py

Creates the pygame window, runs the engine loop at the data-driven fps,
routes input. Camera input mapping lives here per E-5 (the engine holds
pure camera state): right-click-drag pans (clamped to map bounds),
scroll-wheel steps through the data-driven zoom levels (viewport centre
kept fixed), Esc quits. Frame order is fixed per E-14:
input → Scene.update(dt) → render submit.

All tunables come from data/ (G-7): geometry.json (tile pitch, zoom
levels), display.json (window size, fps, caption), and — Phase 6 — the
ACTIVE MAP (D-21): data/maps/active_map.json points at the map file whose
grid dims, painted terrain/zone tiles, deco (above entities, E-26) and
base render through engine.tilemap + the one pipeline. Invalid map data
fails LOUD (D-2) — the E-37 log-and-placeholder tolerance is for art
only. No iso math here — clicks and zoom anchoring go through
engine.coords only.

main(max_frames=N) lets tools/smoke.py drive the same code headlessly (G-8).
"""
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller one-folder build (T-4): --add-data bundles data/ under
    # _internal/, not next to the exe — sys._MEIPASS is PyInstaller's own
    # pointer to wherever bundled resources actually live (onedir or onefile).
    REPO = Path(sys._MEIPASS)
else:
    REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pygame

from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import Scene
from engine.physics import TileOccupancy
from engine.render import Renderer
from game.buildings import BaseBuilding, attach_base, place_building
from game.core.balance import load_balance
from game.map import TileMap

BACKGROUND = (24, 20, 32)

# Demo occupants proving the 9D placement seam: one building type per buildable
# tile, placed with unlimited love (player-driven placement + economy arrive
# with the UI/phase machine, 9F/9G).
DEMO_PLACEMENTS = ("defence", "economic")


def build_scene(tile_map, occupancy, buildings_balance, core_balance):
    """Populate the scene: the base occupant (attached to its pre-seeded tile)
    plus a demo Defender + Musician on buildable tiles — proves the placement
    seam and entity render/animation on tiles."""
    scene = Scene()
    base = BaseBuilding(tile_map.base_col, tile_map.base_row, core_balance)
    attach_base(tile_map, base, scene, occupancy)
    for building_type, tile in zip(DEMO_PLACEMENTS, tile_map.buildable_tiles()):
        place_building(tile_map, tile, building_type, love=9999,
                       buildings_balance=buildings_balance,
                       scene=scene, occupancy=occupancy)
    return scene


def step_zoom(cs, direction, view_w, view_h):
    """Move one step through the data-driven zoom levels, keeping the world
    point at the viewport centre fixed (coords authority only, E-5)."""
    levels = sorted(cs.geometry.zoom_levels)
    i = levels.index(cs.camera.zoom) + direction
    if not 0 <= i < len(levels):
        return
    cx, cy = view_w / 2, view_h / 2
    anchor = cs.screen_to_world(cx, cy)
    cs.set_zoom(levels[i])
    px, py = cs.world_to_screen(*anchor)
    cs.pan(px - cx, py - cy)
    cs.clamp(view_w, view_h)


def main(max_frames=None, data_dir=None):
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    display = data_io.load_validated(
        data_dir / "display.json", data_dir / "schemas" / "display.schema.json"
    )
    view_w, view_h = display["window_w"], display["window_h"]

    pygame.init()
    window = pygame.display.set_mode((view_w, view_h))
    pygame.display.set_caption(display["caption"])
    clock = pygame.time.Clock()

    # D-21: the active map decides what the ground IS — and its dims (D-20)
    map_doc = tilemap.load_active_map(data_dir)
    cs = load_coordinate_system(
        data_dir, map_cols=map_doc.cols, map_rows=map_doc.rows)
    cs.clamp(view_w, view_h)  # centre the map in the viewport
    assets = AssetStore(
        manifest=load_manifest(data_dir / "sprites" / "asset_manifest.json"),
        registry=load_registry(data_dir),
        sprites_dir=data_dir / "sprites",
    )
    renderer = Renderer(cs, assets)
    # Runtime tile grid + occupancy (9C), populated with real buildings (9D).
    tile_map = TileMap(map_doc, load_balance(data_dir, "map"))
    occupancy = TileOccupancy()
    scene = build_scene(
        tile_map, occupancy,
        load_balance(data_dir, "buildings"), load_balance(data_dir, "core"))
    # static map items (tiles + base + deco) — precomputed once, submitted
    # every frame; RenderItems are frozen and reusable
    map_items = tilemap.render_items(map_doc)

    frames = 0
    fps_log_ms = 0
    running = True
    while running:
        dt = clock.tick(display["fps"]) / 1000.0

        # 1. input (E-14) — camera mapping per E-5 lives in this host
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.MOUSEMOTION and event.buttons[2]:
                cs.pan(-event.rel[0], -event.rel[1])  # right-drag: map follows mouse
                cs.clamp(view_w, view_h)
            elif event.type == pygame.MOUSEWHEEL and event.y:
                step_zoom(cs, 1 if event.y > 0 else -1, view_w, view_h)

        # 2. simulate
        scene.update(dt)

        # 3. render submit
        for item in map_items:
            renderer.submit(item)
        for item in scene.render_items():
            renderer.submit(item)
        window.fill(BACKGROUND)
        renderer.flush(window)
        pygame.display.flip()

        fps_log_ms += dt * 1000
        if fps_log_ms >= 1000:
            print(f"fps: {clock.get_fps():.1f}")
            fps_log_ms = 0
        frames += 1
        if max_frames is not None and frames >= max_frames:
            running = False

    pygame.quit()
    return frames


if __name__ == "__main__":
    main()
