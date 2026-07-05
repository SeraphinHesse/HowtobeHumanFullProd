"""How To Be Human — window host (G-1). The ONLY entry point:

    py game/main.py

Creates the pygame window, runs the engine loop at the data-driven fps,
routes input. Camera input mapping lives here per E-5 (the engine holds
pure camera state): right-click-drag pans (clamped to map bounds),
scroll-wheel steps through the data-driven zoom levels (viewport centre
kept fixed), Esc closes the panel / quits. Frame order is fixed per E-14:
input → Scene.update(dt) → render submit.

All tunables come from data/ (G-7): geometry.json (tile pitch, zoom
levels), display.json (window size, fps, caption), and — Phase 6 — the
ACTIVE MAP (D-21): data/maps/active_map.json points at the map file whose
grid dims, painted terrain/zone tiles, deco (above entities, E-26) and
base render through engine.tilemap + the one pipeline. Invalid map data
fails LOUD (D-2) — the E-37 log-and-placeholder tolerance is for art
only. No iso math here — clicks and zoom anchoring go through
engine.coords only.

Phase 9G wires the real UI (game/ui): the HUD (love/income/lives/phase +
End Turn button), the building panel (unlock/construct/upgrade/base-info +
ConstructPreview), income/upkeep floaters + building HP bars, and the game
over screen. Left-click drives all of it; the input-priority ladder
(game_over > preview modal > HUD > panel > panel spatial block > tile pick)
mirrors the prototype's click-consume order so clicks never bleed through
the panel to the world behind it.

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
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, resolve_combat
from game.map import TileMap, tile_at_screen
from game.ui import BuildingUI, FloaterManager, GameOverScreen, Hud

BACKGROUND = (24, 20, 32)
_LEFT, _RIGHT = 1, 3
_DRAG_THRESHOLD_SQ = 4 * 4  # a left-press that moves less than this is a click
_KEY_NAMES = None  # lazily built (needs pygame constants)


def _key_name(key):
    """Map a pygame keycode to the neutral name game/ui expects (keeps game/ui
    pygame-free). Unknown keys -> None (treated as a typed character)."""
    global _KEY_NAMES
    if _KEY_NAMES is None:
        _KEY_NAMES = {
            pygame.K_BACKSPACE: "backspace",
            pygame.K_RETURN: "return",
            pygame.K_KP_ENTER: "return",
            pygame.K_ESCAPE: "escape",
        }
    return _KEY_NAMES.get(key)


class _World:
    """The rebuildable run state: tile grid, occupancy, scene, session. A fresh
    ``_World`` is a fresh game — the game-over 'restart' path just makes a new
    one (the base is re-attached to its pre-seeded tile)."""

    def __init__(self, map_doc, map_bal, enemies_bal, core_bal, registry):
        self.tile_map = TileMap(map_doc, map_bal)
        self.occupancy = TileOccupancy()
        self.scene = Scene()
        base = BaseBuilding(self.tile_map.base_col, self.tile_map.base_row,
                            core_bal)
        attach_base(self.tile_map, base, self.scene, self.occupancy)
        self.spawner = Spawner()
        self.session = Session.create(self.spawner, self.tile_map, enemies_bal,
                                      core_bal, registry=registry)


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
    registry = load_registry(data_dir)
    assets = AssetStore(
        manifest=load_manifest(data_dir / "sprites" / "asset_manifest.json"),
        registry=registry,
        sprites_dir=data_dir / "sprites",
    )
    renderer = Renderer(cs, assets)
    map_bal = load_balance(data_dir, "map")
    buildings_balance = load_balance(data_dir, "buildings")
    enemies_balance = load_balance(data_dir, "enemies")
    core_balance = load_balance(data_dir, "core")
    ui_balance = load_balance(data_dir, "ui")

    world = _World(map_doc, map_bal, enemies_balance, core_balance, registry)
    hud = Hud(view_w, view_h)
    panel = BuildingUI(view_w, view_h, ui_balance)
    floaters = FloaterManager(ui_balance, core_balance)
    game_over = GameOverScreen(view_w, view_h)
    # static map items (tiles + base + deco) — precomputed once, submitted every
    # frame; RenderItems are frozen and reusable
    map_items = tilemap.render_items(map_doc)

    def handle_left_click(mx, my):
        """The click-consume priority ladder (prototype-exact order)."""
        nonlocal world, panel, floaters
        st = world.session.state
        if st.state == GameState.GAME_OVER:
            if game_over.hit(mx, my) == "restart":
                world = _World(map_doc, map_bal, enemies_balance, core_balance,
                               registry)
                panel = BuildingUI(view_w, view_h, ui_balance)
                floaters = FloaterManager(ui_balance, core_balance)
            return
        if panel.preview is not None:                      # modal
            panel.handle_click(mx, my, world.session, buildings_balance,
                               world.scene, world.occupancy)
            return
        if hud.hit(mx, my) == "end_turn":
            world.session.end_turn()
            return
        if panel.handle_click(mx, my, world.session, buildings_balance,
                              world.scene, world.occupancy):
            return
        if panel.visible and mx >= panel.panel_x:          # spatial block
            return
        if st.state == GameState.GAMEPLAY and st.phase == GamePhase.BUILDING:
            tile = tile_at_screen(world.tile_map, cs, mx, my)
            panel.open_for_tile(tile, world.session, buildings_balance)

    frames = 0
    fps_log_ms = 0
    mouse_down = None
    prev_phase = world.session.state.phase
    running = True
    while running:
        dt = clock.tick(display["fps"]) / 1000.0

        # 1. input (E-14) — camera mapping per E-5 lives in this host
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if panel.preview is not None:
                    if event.key == pygame.K_ESCAPE and not panel.preview.editing:
                        panel.preview = None
                    else:
                        panel.handle_key(event.unicode, _key_name(event.key))
                elif event.key == pygame.K_ESCAPE:
                    if panel.visible:
                        panel.close()
                    else:
                        running = False
                elif event.key == pygame.K_SPACE:
                    world.session.end_turn()  # dev convenience beside the button
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _LEFT:
                mouse_down = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == _LEFT:
                if mouse_down is not None:
                    dx, dy = event.pos[0] - mouse_down[0], event.pos[1] - mouse_down[1]
                    if dx * dx + dy * dy <= _DRAG_THRESHOLD_SQ:
                        handle_left_click(*event.pos)
                mouse_down = None
            elif event.type == pygame.MOUSEMOTION and event.buttons[2]:
                cs.pan(-event.rel[0], -event.rel[1])  # right-drag: map follows
                cs.clamp(view_w, view_h)
            elif event.type == pygame.MOUSEWHEEL and event.y:
                step_zoom(cs, 1 if event.y > 0 else -1, view_w, view_h)

        # 2. simulate — the Session drives the phase machine; on GAME_OVER the
        #    whole world FREEZES (scene tick + combat gated on GAMEPLAY).
        session = world.session
        session.pre_sim(dt, world.scene)
        if session.state.state == GameState.GAMEPLAY:
            world.scene.update(dt)
            resolve_combat(world.scene, world.tile_map, dt, buildings_balance,
                           on_base_hit=session.on_base_hit)
            session.post_sim(world.scene)

        # payday fills state.income_events + flips to INCOME; spawn floaters once
        if session.state.phase == GamePhase.INCOME and prev_phase != GamePhase.INCOME:
            floaters.spawn_income_events(session.state)
        prev_phase = session.state.phase

        # 3. UI update (mouse hover, timers)
        mx, my = pygame.mouse.get_pos()
        hud.update(dt, mx, my, session, panel)
        panel.hover(mx, my)
        panel.update(dt)
        floaters.update(dt)
        if session.state.state == GameState.GAME_OVER:
            game_over.update(dt, mx, my)

        # 4. render submit — world, then UI (HUD pass draws on top)
        for item in map_items:
            renderer.submit(item)
        for item in world.scene.render_items():
            renderer.submit(item)
        panel.submit(renderer, session)             # tile-highlight overlays + panel
        floaters.submit_hp_bars(renderer, cs, world.scene)
        floaters.submit(renderer, cs)
        hud.submit(renderer, session, view_w, view_h, hover_cost=panel.hover_cost)
        if session.state.state == GameState.GAME_OVER:
            game_over.submit(renderer, session.state, view_w, view_h)
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
