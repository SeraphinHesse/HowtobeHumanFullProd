"""How To Be Human — window host (G-1). The ONLY entry point:

    py game/main.py

Creates the pygame window, runs the engine loop at the data-driven fps,
routes input. Camera input mapping lives here per E-5 (the engine holds
pure camera state): right-click-drag pans (clamped to map bounds),
scroll-wheel steps through the data-driven zoom levels (viewport centre
kept fixed), Esc opens the pause menu (was: quit). Frame order is fixed per
E-14: input -> Scene.update(dt) -> render submit.

All tunables come from data/ (G-7): geometry.json (tile pitch, zoom
levels), display.json (window size, fps, caption), the ACTIVE MAP (D-21),
and ui.json (Menu.cutscene_length). No iso math here — clicks and zoom
anchoring go through engine.coords only.

Phase 9G wired the in-round UI (game/ui): HUD (love/income/lives/phase +
End Turn + Pause), the building panel, floaters + HP bars, the game over
screen. Phase 9H wraps a run in the top-level shell (game.ui.Shell): the
intro CUTSCENE (full video via engine.video), MAIN_MENU, SETTINGS,
CREDITS, ADD_NAME, PAUSED. The host owns the pygame-only concerns the pure
shell cannot: window (re)creation for display mode, the cutscene frame
blit, background music, the _World lifecycle, and executing the shell's
intent strings (new_game / quit_to_menu / quit_app / set_display_mode /
add_name_commit). GAMEPLAY/GAME_OVER carry the live world; every other
state is a full-screen shell screen with no world.

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
from engine.audio import play_music
from engine.coords import load_coordinate_system
from engine.core import Scene
from engine.physics import TileOccupancy
from engine.render import HudText, Renderer
from engine.video import VideoSource
from game.buildings import BaseBuilding, attach_base
from game.core import Session, append_random_name, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, resolve_combat
from game.map import TileMap, tile_at_screen
from game.ui import BuildingUI, FloaterManager, GameOverScreen, Hud, Shell

BACKGROUND = (24, 20, 32)
_LEFT, _RIGHT = 1, 3
_DRAG_THRESHOLD_SQ = 4 * 4  # a left-press that moves less than this is a click
_WORLD_STATES = (GameState.GAMEPLAY, GameState.GAME_OVER)
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


def _apply_display_mode(mode, view_w, view_h, caption):
    """(Re)create the window for a display mode. The logical surface stays
    view_w x view_h in every mode — SCALED upscales to the monitor and remaps
    mouse coords back to logical space, so coords/renderer/hit-rects never
    change (E-5). Returns the new window Surface (the renderer takes the target
    at flush, so reassigning it mid-run is safe)."""
    flags = pygame.SCALED
    if mode == "borderless":
        flags |= pygame.NOFRAME
    elif mode == "fullscreen":
        flags |= pygame.FULLSCREEN
    window = pygame.display.set_mode((view_w, view_h), flags)
    pygame.display.set_caption(caption)
    return window


class _World:
    """The rebuildable run state: tile grid, occupancy, scene, session. A fresh
    ``_World`` is a fresh game (the base is re-attached to its pre-seeded tile)."""

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


def main(max_frames=None, data_dir=None, autostart=False):
    """``autostart=True`` skips the shell (cutscene/menu) and boots straight into
    a fresh GAMEPLAY run — the headless test seam so tools/smoke.py and the boot
    tests still exercise the full _World/Session construction + sim frames the
    shell would otherwise defer until START NEW GAME."""
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    display = data_io.load_validated(
        data_dir / "display.json", data_dir / "schemas" / "display.schema.json"
    )
    view_w, view_h = display["window_w"], display["window_h"]
    caption = display["caption"]

    pygame.init()

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
    # static map items (tiles + base + deco) — precomputed once, submitted every
    # frame; RenderItems are frozen and reusable
    map_items = tilemap.render_items(map_doc)

    # intro cutscene (full video; graceful skip if cv2/file absent -> MAIN_MENU)
    video = VideoSource(data_dir / "video" / "cutscene.mp4",
                        ui_balance["Menu"]["cutscene_length"],
                        target_size=(view_w, view_h))
    start = GameState.CUTSCENE if video.enabled else GameState.MAIN_MENU
    shell = Shell(view_w, view_h, ui_balance, start_state=start)
    shell.set_pool_count(len(buildings_balance["BuildingsGlobal"]["random_names"]))

    window = _apply_display_mode(shell.settings.display_mode, view_w, view_h,
                                 caption)
    clock = pygame.time.Clock()
    if max_frames is None:  # windowed run only — headless tests stay silent/fast
        play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav", loop=True)

    # gameplay bundle — None until START NEW GAME; dropped on quit-to-menu
    gp = {"world": None, "hud": None, "panel": None, "floaters": None,
          "game_over": None, "prev_phase": None}

    def build_gameplay():
        gp["world"] = _World(map_doc, map_bal, enemies_balance, core_balance,
                             registry)
        gp["hud"] = Hud(view_w, view_h)
        gp["panel"] = BuildingUI(view_w, view_h, ui_balance)
        gp["floaters"] = FloaterManager(ui_balance, core_balance)
        gp["game_over"] = GameOverScreen(view_w, view_h)
        gp["prev_phase"] = gp["world"].session.state.phase
        cs.clamp(view_w, view_h)  # re-centre the map for the fresh run
        shell.enter_gameplay()

    def teardown_gameplay():
        for k in ("world", "hud", "panel", "floaters", "game_over"):
            gp[k] = None

    def execute(intent):
        nonlocal running, window
        if intent == "new_game":
            build_gameplay()
        elif intent == "quit_to_menu":
            teardown_gameplay()  # shell already set state -> MAIN_MENU
        elif intent == "quit_app":
            running = False
        elif intent == "set_display_mode":
            window = _apply_display_mode(shell.settings.display_mode, view_w,
                                         view_h, caption)
        elif intent == "add_name_commit":
            name = shell.pending_name
            added = append_random_name(data_dir, name)
            if added:
                buildings_balance["BuildingsGlobal"]["random_names"].append(
                    name.strip())
                shell.set_pool_count(
                    len(buildings_balance["BuildingsGlobal"]["random_names"]))
            shell.report_add_name(added, name)

    def handle_world_click(mx, my):
        """The in-round click-consume priority ladder (prototype-exact order),
        entered only in GAMEPLAY/GAME_OVER."""
        world = gp["world"]
        session = world.session
        panel = gp["panel"]
        if session.state.state == GameState.GAME_OVER:
            if gp["game_over"].hit(mx, my) == "main_menu":
                teardown_gameplay()
                shell.to_main_menu()
            return
        if panel.preview is not None:                      # modal
            panel.handle_click(mx, my, session, buildings_balance,
                               world.scene, world.occupancy)
            return
        hud_action = gp["hud"].hit(mx, my)
        if hud_action == "pause":
            shell.state = GameState.PAUSED
            return
        if hud_action == "end_turn":
            session.end_turn()
            return
        if panel.handle_click(mx, my, session, buildings_balance,
                              world.scene, world.occupancy):
            return
        if panel.visible and mx >= panel.panel_x:          # spatial block
            return
        if session.state.phase == GamePhase.BUILDING:
            tile = tile_at_screen(world.tile_map, cs, mx, my)
            panel.open_for_tile(tile, session, buildings_balance)

    if autostart:
        build_gameplay()  # headless seam: bypass cutscene/menu -> GAMEPLAY

    frames = 0
    fps_log_ms = 0
    mouse_down = None
    running = True
    while running:
        dt = clock.tick(display["fps"]) / 1000.0

        # 1. input (E-14) — routed per top-level shell state
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            st = shell.state
            if st == GameState.CUTSCENE:
                if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    video.skip()
                continue
            if shell.in_menu or st == GameState.PAUSED:
                if event.type == pygame.KEYDOWN:
                    execute(shell.handle_key(event.unicode, _key_name(event.key)))
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _LEFT:
                    execute(shell.handle_click(*event.pos))
                continue
            # GAMEPLAY / GAME_OVER: the live world is present
            world = gp["world"]
            session = world.session
            panel = gp["panel"]
            if event.type == pygame.KEYDOWN:
                if session.state.state != GameState.GAMEPLAY:
                    continue
                if panel.preview is not None:
                    if event.key == pygame.K_ESCAPE and not panel.preview.editing:
                        panel.preview = None
                    else:
                        panel.handle_key(event.unicode, _key_name(event.key))
                elif event.key == pygame.K_ESCAPE:
                    if panel.visible:
                        panel.close()
                    else:
                        shell.state = GameState.PAUSED  # Esc opens pause
                elif event.key == pygame.K_SPACE:
                    session.end_turn()  # dev convenience beside the button
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _LEFT:
                mouse_down = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == _LEFT:
                if mouse_down is not None:
                    dx = event.pos[0] - mouse_down[0]
                    dy = event.pos[1] - mouse_down[1]
                    if dx * dx + dy * dy <= _DRAG_THRESHOLD_SQ:
                        handle_world_click(*event.pos)
                mouse_down = None
            elif event.type == pygame.MOUSEMOTION and event.buttons[2]:
                cs.pan(-event.rel[0], -event.rel[1])  # right-drag: map follows
                cs.clamp(view_w, view_h)
            elif event.type == pygame.MOUSEWHEEL and event.y:
                step_zoom(cs, 1 if event.y > 0 else -1, view_w, view_h)

        mx, my = pygame.mouse.get_pos()

        # 2. simulate / update — per state
        st = shell.state
        if st == GameState.CUTSCENE:
            video.update(dt)
            if video.done:
                video.release()
                shell.to_main_menu()
        elif st in _WORLD_STATES:
            world = gp["world"]
            session = world.session
            session.pre_sim(dt, world.scene)
            if session.state.state == GameState.GAMEPLAY:
                world.scene.update(dt)
                resolve_combat(world.scene, world.tile_map, dt, buildings_balance,
                               on_base_hit=session.on_base_hit)
                session.post_sim(world.scene)
            # payday fills state.income_events + flips to INCOME; spawn once
            if (session.state.phase == GamePhase.INCOME
                    and gp["prev_phase"] != GamePhase.INCOME):
                gp["floaters"].spawn_income_events(session.state)
            gp["prev_phase"] = session.state.phase
            # mirror a fresh game over up to the shell (never while PAUSED)
            if (st == GameState.GAMEPLAY
                    and session.state.state == GameState.GAME_OVER):
                shell.enter_game_over()
            gp["hud"].update(dt, mx, my, session, gp["panel"])
            gp["panel"].hover(mx, my)
            gp["panel"].update(dt)
            gp["floaters"].update(dt)
            if session.state.state == GameState.GAME_OVER:
                gp["game_over"].update(dt, mx, my)
        else:  # menu states + PAUSED
            shell.update(dt, mx, my)

        # 3. render submit — per state
        window.fill(BACKGROUND)
        st = shell.state
        if st == GameState.CUTSCENE:
            surf = video.frame_surface()
            if surf is not None:
                window.blit(surf, (0, 0))
            renderer.submit_hud(HudText(
                "press any key to skip", (view_w // 2, view_h - 40),
                "md", (210, 210, 210), align="center"))
            renderer.flush(window)
        elif st in _WORLD_STATES or st == GameState.PAUSED:
            world = gp["world"]
            session = world.session
            for item in map_items:
                renderer.submit(item)
            for item in world.scene.render_items():
                renderer.submit(item)
            gp["panel"].submit(renderer, session)
            gp["floaters"].submit_hp_bars(renderer, cs, world.scene)
            gp["floaters"].submit(renderer, cs)
            gp["hud"].submit(renderer, session, view_w, view_h,
                             hover_cost=gp["panel"].hover_cost)
            if session.state.state == GameState.GAME_OVER:
                gp["game_over"].submit(renderer, session.state, view_w, view_h)
            if st == GameState.PAUSED:
                shell.submit(renderer, view_w, view_h)  # overlay on frozen world
            renderer.flush(window)
        else:  # menu states — full-screen shell screen, no world
            shell.submit(renderer, view_w, view_h)
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
