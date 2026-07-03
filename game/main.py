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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pygame

from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import GameObject, Scene, SpriteAnimator, Transform
from engine.render import Renderer

BACKGROUND = (24, 20, 32)

DUMMY_ENTITIES = [  # slot, world pos, phase offset — prove Scene → RenderItem
    ("stone_thrower_t1_lvl1", (4.0, 4.0), 0),     # migrated multi-row sheet
    ("flute_player_t1_lvl1", (10.0, 7.0), 250),   # migrated 17-frame idle
    ("dummy_entity", (15.0, 12.0), 500),          # no registry slot → grey X
]


def build_scene():
    scene = Scene()
    for i, (slot, pos, phase) in enumerate(DUMMY_ENTITIES):
        scene.spawn(
            GameObject(
                name=f"dummy_{i}",
                tags=("dummy",),
                transform=Transform(wx=pos[0], wy=pos[1]),
                components=[SpriteAnimator(slot_key=slot, phase_ms=phase)],
            )
        )
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
        frame_sizes={"dummy_entity": (64, 96)},  # test dummy, not a registry slot
    )
    renderer = Renderer(cs, assets)
    scene = build_scene()
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
