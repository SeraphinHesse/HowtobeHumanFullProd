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
import gc
import math
import random
import sys
import time
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
from engine.core import Scene, SpriteAnimator
from engine.physics import TileOccupancy
from engine.render import HudText, Renderer
from engine.render.fonts import configure_fonts
from engine.render.ground_cache import GroundCache
from engine.video import VideoSource
from game.buildings import BaseBuilding, attach_base
# -- 10I: defence-range coverage producer (injected into the tilemap) --
from game.buildings.coverage import wire_defence_coverage
# -- /10I --
from game.core import Session, append_random_name, load_balance
from game.core.boss_bonuses import story_damage_bonus
from game.core.phases import GamePhase, GameState
from game.enemies import DEATH_ANIM, Spawner, resolve_combat, spawn_corpse
from game.map import TileMap, condition_render_items, tile_at_screen
from game.map.tiles import CONDITION_CATEGORY
from game.map.tiles import TileState  # 10J: multi-select category
from game.ui import (
    BossCutscene, BuildingUI, CheatMenu, FloaterManager, GameLog,
    GameOverScreen, Hud, LevelupWindow, MapOverlays, Shell,
)
from game.ui import widgets  # 10L-A: R2 hit-seam wiring
from game.ui.skinning import ScreenSkinning  # 10L-B: per-screen overrides

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

    def __init__(self, map_doc, map_bal, enemies_bal, core_bal, buildings_bal,
                 registry):
        # -- 10I: the live run rolls tile conditions (rng=None would keep the
        # all-GRASS fixture mode the headless tests rely on). `registry` also
        # rolls each tile's condition ART slot (the `terrain` draw layer). --
        self.tile_map = TileMap(map_doc, map_bal, rng=random, registry=registry)
        # -- /10I --
        self.occupancy = TileOccupancy()
        self.scene = Scene()
        # A hole-less map (editor allows it with a warning) has no base to
        # attach — the run just isn't winnable. Skip rather than crash.
        if self.tile_map.base_col is not None:
            base = BaseBuilding(self.tile_map.base_col, self.tile_map.base_row,
                                core_bal)
            attach_base(self.tile_map, base, self.scene, self.occupancy)
        self.spawner = Spawner()
        self.session = Session.create(self.spawner, self.tile_map, enemies_bal,
                                      core_bal, buildings_bal, registry=registry,
                                      occupancy=self.occupancy)
        # -- 10I: defence coverage feeds enemy path weights (pre-query refresh
        # in the pathfinder reads the injected callable) --
        wire_defence_coverage(self.tile_map, buildings_bal)
        # -- /10I --


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
    # core's Camera group is the balancing tunable overriding geometry.json's
    # zoom fallback (hoisted ahead of the other balance loads below so it's
    # available before cs is built).
    core_balance = load_balance(data_dir, "core")
    cs = load_coordinate_system(
        data_dir, map_cols=map_doc.cols, map_rows=map_doc.rows,
        zoom_levels=core_balance["Camera"]["zoom_levels"],
        default_zoom=core_balance["Camera"]["default_zoom"])

    def frame_camera():
        """Open the camera centred on the map's camera-startpoint object if it
        has one (center_on parks it at the viewport centre, then clamps);
        otherwise the default corner clamp."""
        if map_doc.camera_start is not None:
            cs.center_on(map_doc.camera_start["col"],
                         map_doc.camera_start["row"], view_w, view_h)
        else:
            cs.clamp(view_w, view_h)

    frame_camera()  # centre on the startpoint / map at boot
    registry = load_registry(data_dir)
    manifest = load_manifest(data_dir / "sprites" / "asset_manifest.json")
    assets = AssetStore(
        manifest=manifest,
        registry=registry,
        sprites_dir=data_dir / "sprites",
    )
    # Tile-condition art: {slot key -> tint_overlay} over the condition slots
    # that actually have an imported sheet. THE one map both consumers read —
    # the `terrain`-layer emitter (sprite iff the slot is in here) and the
    # overlay tint (drawn iff the slot is absent, or its entry asks for it) —
    # so a sprite and its tint can never disagree about what exists. Derived
    # once per boot; art cannot change mid-run.
    condition_art = {
        slot: manifest.entry(slot).tint_overlay
        for slot in registry.group_slots(CONDITION_CATEGORY)
        if manifest.entry(slot) is not None
    }
    widgets.set_skin_hit_test(assets.hit_opaque)  # R2: pixel-perfect click targets
    # D5/UH-6: theme data, loaded + schema-validated once at boot, before the
    # Shell/screens are built (so every screen's FIRST submit already sees
    # it). A missing/invalid file fails LOUD (D-2 — this is data, not art;
    # E-37 does not apply) via the same data_io.load_validated every other
    # required data/ file goes through.
    fonts_doc = data_io.load_validated(
        data_dir / "ui" / "fonts.json", data_dir / "schemas" / "fonts.schema.json")
    palette_doc = data_io.load_validated(
        data_dir / "ui" / "palette.json",
        data_dir / "schemas" / "palette.schema.json")
    configure_fonts(fonts_doc)
    widgets.configure_palette(palette_doc)
    renderer = Renderer(cs, assets)
    # The static ground layer is composited once into an oversized surface and
    # blitted at a pan offset (perf: a 1024² map is one blit/frame while panning
    # instead of thousands of tile blits). Shares the AssetStore with `renderer`.
    ground_cache = GroundCache(cs, assets, bg_color=BACKGROUND)
    map_bal = load_balance(data_dir, "map")
    buildings_balance = load_balance(data_dir, "buildings")
    enemies_balance = load_balance(data_dir, "enemies")
    ui_balance = load_balance(data_dir, "ui")
    # debug: draw the camera-startpoint marker in-game (default off)
    show_camera_start = ui_balance["Debug"]["show_camera_startpoint"]

    # intro cutscene (full video; graceful skip if cv2/file absent -> MAIN_MENU)
    video = VideoSource(data_dir / "video" / "cutscene.mp4",
                        ui_balance["Menu"]["cutscene_length"],
                        target_size=(view_w, view_h))
    start = GameState.CUTSCENE if video.enabled else GameState.MAIN_MENU
    # 10L-B: one ScreenSkinning for the whole run, loaded once here (the
    # shell shares it with its five menu screens; build_gameplay threads the
    # SAME instance into the seven gameplay screens it constructs itself).
    skinning = ScreenSkinning(data_dir)
    shell = Shell(view_w, view_h, ui_balance, start_state=start,
                 skinning=skinning)
    shell.set_pool_count(len(buildings_balance["BuildingsGlobal"]["random_names"]))

    window = _apply_display_mode(shell.settings.display_mode, view_w, view_h,
                                 caption)
    clock = pygame.time.Clock()

    if max_frames is None:  # windowed run only — headless tests stay silent/fast
        play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav", loop=True)

    # A large map builds one Tile per cell (a 1024² map = ~1M long-lived
    # objects); the per-frame render/sim churn (RenderItems, DrawCalls, dying
    # entities that form reference cycles) otherwise makes Python's cyclic GC
    # periodically walk that entire static grid — an 80–140 ms stall that
    # scales with map size and drags a big map to a few fps. gc.freeze() moves
    # everything currently alive (the tile grid + all setup) into a permanent
    # generation the collector never scans again, so a collection costs <1 ms
    # regardless of map size (young entity garbage is still collected normally).
    # Windowed run only — headless tests/smoke re-boot main() in-process and
    # should not have their GC state mutated.
    tune_gc = max_frames is None

    def freeze_static():
        if tune_gc:
            gc.collect()
            gc.freeze()

    # gameplay bundle — None until START NEW GAME; dropped on quit-to-menu
    gp = {"world": None, "hud": None, "panel": None, "floaters": None,
          "game_over": None, "levelup": None, "boss_cutscene": None,
          "cheat": None, "overlays": None, "prev_phase": None,
          # -- 10J: game log + shift multi-select state --
          "game_log": None, "sel": [], "sel_cat": None}

    def build_gameplay():
        gp["world"] = _World(map_doc, map_bal, enemies_balance, core_balance,
                             buildings_balance, registry)
        # Ground follows runtime zone changes: unlock/recede invalidates the
        # cached ground surface (repainted next ensure). Fresh game -> fresh
        # TileMap with empty overrides; invalidate drops the previous run's
        # unlocked-tile visuals too.
        gp["world"].tile_map.on_zone_change = ground_cache.invalidate
        ground_cache.invalidate()
        # 10L-B: every gameplay screen shares the shell's ScreenSkinning (the
        # shell owns no world, so it cannot construct these itself).
        gp["hud"] = Hud(view_w, view_h, skinning=shell.skinning)
        gp["panel"] = BuildingUI(view_w, view_h, ui_balance,
                                 skinning=shell.skinning)
        gp["floaters"] = FloaterManager(ui_balance, core_balance)
        gp["game_over"] = GameOverScreen(view_w, view_h, skinning=shell.skinning)
        gp["levelup"] = LevelupWindow(view_w, view_h, skinning=shell.skinning)
        gp["boss_cutscene"] = BossCutscene(view_w, view_h,  # -- 10G boss --
                                          skinning=shell.skinning)
        gp["cheat"] = CheatMenu(view_w, view_h, skinning=shell.skinning)  # 10H
        # -- 10I: condition tint + RANGE/HEATMAP overlay toggles --
        gp["overlays"] = MapOverlays(view_w, view_h, skinning=shell.skinning)
        # The tint is a FALLBACK for conditions with no imported art (plus any
        # slot whose entry opts back into it) — see `condition_art` above.
        gp["overlays"].condition_art = condition_art
        # -- /10I --
        # -- 10J: game log + VFX wiring + a fresh multi-selection --
        gp["game_log"] = GameLog(skinning=shell.skinning)
        gp["sel"], gp["sel_cat"] = [], None
        gp["panel"].log = gp["game_log"]
        gp["panel"].on_build_vfx = gp["floaters"].spawn_building_vfx
        gp["floaters"].log = gp["game_log"]
        # -- /10J --
        gp["prev_phase"] = gp["world"].session.state.phase
        frame_camera()  # re-centre on the startpoint / map for the fresh run
        freeze_static()  # exclude the fresh tile grid from GC scans
        shell.enter_gameplay()

    def teardown_gameplay():
        if tune_gc:
            gc.unfreeze()  # let the old world's tile grid become collectable
        for k in ("world", "hud", "panel", "floaters", "game_over", "levelup",
                  "boss_cutscene", "cheat", "overlays", "game_log"):
            gp[k] = None
        gp["sel"], gp["sel_cat"] = [], None  # 10J
        if tune_gc:
            gc.collect()

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

    # -- 10H: lightning + cheat menu --------------------------------------
    def _execute_cheat(action):
        """Map a cheat-menu action onto the Session cheat methods. The
        stays-open rule lives here: only close / trigger_levelup / a committed
        goto_round close the menu (prototype cheat_menu.py:49-56). After any
        phase-changing action that leaves LEVELUP, close the level-up window
        so no orphaned modal lingers — ``levelup_pending`` survives, so the
        window re-opens at the next ROUND_END (the prototype's pending-flag
        behavior)."""
        world = gp["world"]
        session = world.session
        if action == "close":
            gp["cheat"].close()
        elif action == "add_love":
            session.cheat_add_love(10)
        elif action == "skip_round":
            session.cheat_skip_round(world.scene)
        elif action == "inf_money":
            session.cheat_add_love(999999)
        elif action == "unlock_all":
            session.cheat_unlock_all()
        elif action == "trigger_levelup":
            gp["cheat"].close()
            session.cheat_trigger_levelup()
        elif isinstance(action, tuple) and action[0] == "goto_round":
            gp["cheat"].close()
            session.cheat_goto_round(action[1], world.scene)
        if (session.state.phase != GamePhase.LEVELUP
                and gp["levelup"].visible):
            gp["levelup"].close()  # orphan guard (pending flag survives)
    # -- /10H ---------------------------------------------------------------

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
        # -- 10H: the open cheat menu consumes EVERY click (renders topmost,
        # directly under GAME_OVER in the ladder — above every other modal) --
        if gp["cheat"].visible:
            _execute_cheat(gp["cheat"].hit(mx, my))
            return
        # -- /10H --
        # -- 10G boss: the cutscene is fully modal — A/B or nothing (clicks
        # elsewhere swallowed; keys are already swallowed by the frozen gate).
        if session.state.phase == GamePhase.BOSS_CUTSCENE:
            choice = gp["boss_cutscene"].hit(mx, my)
            if choice is not None:
                gp["boss_cutscene"].close()
                session.resolve_boss_cutscene(choice, world.scene)
            return
        # -- /10G --
        if session.frozen:                                 # LEVELUP: fully modal
            option = gp["levelup"].hit(mx, my)
            if option is not None:
                gp["levelup"].close()
                session.resolve_levelup(option, world.scene)  # -> payday -> INCOME
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
        # -- 10L: fast-forward combat-speed buttons --
        if isinstance(hud_action, tuple) and hud_action[0] == "speed":
            session.set_combat_speed(hud_action[1])
            return
        # -- /10L speed --
        # -- 10I: RANGE/HEATMAP overlay toggles consume the click --
        if gp["overlays"].hit(mx, my):
            return
        # -- /10I --
        if panel.handle_click(mx, my, session, buildings_balance,
                              world.scene, world.occupancy):
            return
        if panel.visible and mx >= panel.panel_x:          # spatial block
            return
        if session.state.phase == GamePhase.BUILDING:
            tile = tile_at_screen(world.tile_map, cs, mx, my)
            # -- 10J: shift multi-select (prototype game.py:440-490) --
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            update_selection(tile, shift, session)
            # -- /10J --
        # -- 10H: ENEMY-phase lightning click at the ladder BOTTOM (prototype
        # game.py:426-431 — a non-drag left-up no UI element consumed) --
        elif session.state.phase == GamePhase.ENEMY:
            wx, wy = cs.screen_to_world(mx, my)
            session.lightning_strike(world.scene, cs, wx, wy)
        # -- /10H --

    def handle_world_right_click(mx, my):
        """Right-click is a universal DISMISS, never a world action — it peels
        one stage off whatever is open, wherever the cursor is. A right-DRAG
        still pans; the _DRAG_THRESHOLD_SQ gate in the event loop is what keeps
        the two apart. Mirrors handle_world_click's precedence so the two
        ladders cannot drift."""
        session = gp["world"].session
        if session.state.state == GameState.GAME_OVER:
            return
        if gp["cheat"].visible:
            gp["cheat"].close()
            return
        if session.frozen or session.state.phase == GamePhase.BOSS_CUTSCENE:
            return  # LEVELUP / boss cutscene: a choice, not a dismiss
        gp["panel"].dismiss()
        if not gp["panel"].visible:
            gp["sel"], gp["sel_cat"] = [], None

    # -- 10J: shift multi-select (prototype _handle_tile_click,
    # game.py:440-490): same-category shift-clicks toggle tiles in/out of the
    # batch; a different category is ignored SILENTLY; a plain click starts a
    # fresh single selection; background/spawning/no tile clears + closes. --
    _SEL_CATEGORY = {TileState.BUILT: "built", TileState.BUILDABLE: "buildable",
                     TileState.COMBAT: "combat"}

    def update_selection(tile, shift, session):
        panel = gp["panel"]
        if not panel.visible:   # panel closed elsewhere -> selection is stale
            gp["sel"], gp["sel_cat"] = [], None
        cat = _SEL_CATEGORY.get(tile.state) if tile is not None else None
        if cat is None:
            gp["sel"], gp["sel_cat"] = [], None
            panel.close()
            return
        if shift and gp["sel"] and cat == gp["sel_cat"]:
            if tile in gp["sel"]:
                gp["sel"].remove(tile)
                if not gp["sel"]:
                    gp["sel_cat"] = None
                    panel.close()
                    return
            else:
                gp["sel"].append(tile)
        elif shift and gp["sel"] and cat != gp["sel_cat"]:
            return  # mixed categories: ignored silently (prototype :481-482)
        else:
            gp["sel"], gp["sel_cat"] = [tile], cat
        panel.open_for_tile(gp["sel"][0], session, buildings_balance,
                            selected_tiles=gp["sel"])
    # -- /10J --

    if autostart:
        build_gameplay()  # headless seam: bypass cutscene/menu -> GAMEPLAY

    frames = 0
    fps_log_ms = 0
    # Per-section frame-time accumulators (windowed runs only — the print is
    # gated on tune_gc). sim = update; submit = fill + RenderItem generation;
    # flush = renderer.flush (the tile blits); flip = display.flip (SCALED
    # upscale). Lets us see on real hardware where a slow frame actually goes.
    perf = {"sim": 0.0, "submit": 0.0, "flush": 0.0, "flip": 0.0}
    perf_frames = 0
    mouse_down = None
    rmouse_down = None  # right-press origin: a short press dismisses, a drag pans
    pan_from = None  # set on a left-press that began over the world (not UI)
    deco_clock_ms = 0.0  # wall-clock accumulator for deco idle animation
    running = True
    while running:
        dt = clock.tick(display["fps"]) / 1000.0
        deco_clock_ms += dt * 1000.0  # wall-clock: deco keeps animating while paused
        _t_frame = time.perf_counter()
        _t_flush_start = _t_frame  # each render branch resets this before flush

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
                # -- 10H: cheat menu — BEFORE the frozen guard (it must work
                # over LEVELUP, prototype game.py:293-325) but never on
                # GAME_OVER. Ctrl+L toggles (deliberate divergence from the
                # prototype's Ctrl+P — bare P is the quick-skip key here);
                # while open the menu consumes ALL keys. --
                if session.state.state == GameState.GAMEPLAY:
                    if (event.key == pygame.K_l
                            and pygame.key.get_mods() & pygame.KMOD_CTRL):
                        gp["cheat"].toggle()
                        continue
                    if gp["cheat"].visible:
                        _execute_cheat(gp["cheat"].handle_key(
                            event.unicode, _key_name(event.key)))
                        continue
                # -- /10H --
                if session.state.state != GameState.GAMEPLAY or session.frozen:
                    continue  # the LEVELUP window owns all input
                if panel.preview is not None:
                    if event.key == pygame.K_ESCAPE and not panel.preview.editing:
                        panel.preview = None
                    else:
                        panel.handle_key(event.unicode, _key_name(event.key))
                elif panel.name_editing:  # 10J: upgrade-panel rename capture
                    panel.handle_key(event.unicode, _key_name(event.key))
                elif event.key == pygame.K_ESCAPE:
                    if panel.visible:
                        panel.close()
                    else:
                        shell.state = GameState.PAUSED  # Esc opens pause
                elif event.key == pygame.K_SPACE:
                    session.end_turn()  # dev convenience beside the button
                elif session.state.phase == GamePhase.ENEMY:
                    # Combat-speed shortcuts + quick-skip (10F). 1.5x/2x are
                    # round-gated inside Session, so a locked key is a no-op.
                    # The 1x/1.5x/2x/pause BUTTONS are 10L.
                    if event.key in (pygame.K_1, pygame.K_KP1):
                        session.set_combat_speed(0)
                    elif event.key in (pygame.K_2, pygame.K_KP2):
                        session.set_combat_speed(1)   # 1.5x
                    elif event.key in (pygame.K_3, pygame.K_KP3):
                        session.set_combat_speed(2)   # 2x
                    elif event.key == pygame.K_p:
                        session.quick_skip_combat(world.scene)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _LEFT:
                mouse_down = event.pos
                # a left-press over the world (not a UI panel/HUD button) arms
                # left-drag panning; a short press still clicks (drag threshold)
                px, py = event.pos
                over_ui = (
                    panel.preview is not None
                    or (panel.visible and px >= panel.panel_x)
                    or gp["hud"].hit(px, py) is not None
                    or gp["cheat"].visible  # 10H: no pan-arming on the menu
                    or gp["overlays"].over(px, py)   # 10I: toggle pills
                )
                pan_from = None if over_ui else event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == _LEFT:
                if mouse_down is not None:
                    dx = event.pos[0] - mouse_down[0]
                    dy = event.pos[1] - mouse_down[1]
                    if dx * dx + dy * dy <= _DRAG_THRESHOLD_SQ:
                        handle_world_click(*event.pos)
                mouse_down = None
                pan_from = None
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _RIGHT:
                rmouse_down = event.pos
            elif event.type == pygame.MOUSEBUTTONUP and event.button == _RIGHT:
                # No over_ui gate: right-click dismisses from ANYWHERE, panel
                # and HUD included. Past the drag threshold it was a pan.
                if rmouse_down is not None:
                    dx = event.pos[0] - rmouse_down[0]
                    dy = event.pos[1] - rmouse_down[1]
                    if dx * dx + dy * dy <= _DRAG_THRESHOLD_SQ:
                        handle_world_right_click(*event.pos)
                rmouse_down = None
            elif event.type == pygame.MOUSEMOTION and (
                    event.buttons[2] or (event.buttons[0] and pan_from is not None)):
                if gp["cheat"].visible:  # 10H: open menu swallows drag-pan
                    continue
                cs.pan(-event.rel[0], -event.rel[1])  # left/right-drag: map follows
                cs.clamp(view_w, view_h)
            elif event.type == pygame.MOUSEWHEEL and event.y:
                if gp["cheat"].visible:  # 10H: open menu swallows wheel zoom
                    continue
                step_zoom(cs, 1 if event.y > 0 else -1, view_w, view_h)

        mx, my = pygame.mouse.get_pos()
        held = pygame.mouse.get_pressed()[0]   # 10L-A: skinned pressed state

        # 2. simulate / update — per state
        _t_sim0 = time.perf_counter()
        st = shell.state
        if st == GameState.CUTSCENE:
            video.update(dt)
            if video.done:
                video.release()
                shell.to_main_menu()
        elif st in _WORLD_STATES:
            world = gp["world"]
            session = world.session
            # Combat speed (10F) scales the ENEMY-phase sim ONLY — spawner,
            # movement and the combat sweep together (prototype game.py:1211-13).
            # ROUND_END/INCOME timers always run on real time, and the pause is
            # just a 0.0 multiplier, so the round machine is never touched.
            sim_dt = (dt * session.combat_speed
                      if session.state.phase == GamePhase.ENEMY else dt)
            session.pre_sim(sim_dt, world.scene)
            # LEVELUP/BOSS_CUTSCENE freeze the world entirely (no sim/anim).
            if session.state.state == GameState.GAMEPLAY and not session.frozen:
                world.scene.update(sim_dt)
                # 10G: the flat boss-bonus story damage (Boss1A/3A), computed
                # once per frame and threaded as a plain int.
                dmg_bonus = story_damage_bonus(session.state, world.tile_map)

                # Play the death animation if the dead enemy's sheet has a
                # `death` row (Art/enemies): the session bookkeeping runs first
                # and the enemy still despawns this frame, but a cosmetic Corpse
                # lingers at its spot to play the row once. Dormant when the
                # sheet has no `death` track (no duration -> no corpse).
                def _on_enemy_death(enemy, _scene=world.scene):
                    session.on_enemy_death(enemy)
                    anim = enemy.get_component(SpriteAnimator)
                    if anim is not None:
                        ms = assets.animation_total_ms(anim.slot_key, DEATH_ANIM)
                        if ms:
                            spawn_corpse(_scene, enemy, ms)

                resolve_combat(world.scene, world.tile_map, sim_dt,
                               buildings_balance,
                               on_base_hit=session.on_base_hit,
                               on_enemy_death=_on_enemy_death,
                               dmg_bonus=dmg_bonus)
                session.post_sim(world.scene)
            # payday fills state.income_events + flips to INCOME; spawn once
            if (session.state.phase == GamePhase.INCOME
                    and gp["prev_phase"] != GamePhase.INCOME):
                gp["floaters"].spawn_income_events(session.state)
                gp["floaters"].spawn_painter_events(session.state)
                gp["floaters"].spawn_boost_events(session.state)
            # -- 10J: the previous round's blood clears when the next wave
            # starts (prototype clear_splatters on End Turn, game.py:815) --
            if (session.state.phase == GamePhase.ENEMY
                    and gp["prev_phase"] != GamePhase.ENEMY):
                gp["floaters"].clear_splatters()
            # -- /10J --
            # pre_sim rolled the cards when it entered LEVELUP; open on the edge
            if (session.state.phase == GamePhase.LEVELUP
                    and gp["prev_phase"] != GamePhase.LEVELUP):
                gp["panel"].close()  # the modal owns the screen
                gp["levelup"].open(session.state.levelup_options)
            # -- 10G boss: open the cutscene on ITS phase edge (same pattern) --
            if (session.state.phase == GamePhase.BOSS_CUTSCENE
                    and gp["prev_phase"] != GamePhase.BOSS_CUTSCENE):
                pending = session.state.pending_boss_cutscene or {}
                gp["panel"].close()  # the modal owns the screen
                gp["boss_cutscene"].open(pending.get("boss_num", 1),
                                         pending.get("outcome", "win"))
            # -- /10G --
            # -- 10I: heatmap traffic tracking (accumulates during ENEMY;
            # snapshots the round's counts on the ENEMY->anything edge) --
            gp["overlays"].track(session.state.phase, gp["prev_phase"],
                                 world.scene)
            # -- /10I --
            gp["prev_phase"] = session.state.phase
            gp["floaters"].spawn_xp_events(session.state)
            gp["floaters"].spawn_boss_events(session.state)  # 10G announcement
            # mirror a fresh game over up to the shell (never while PAUSED)
            if (st == GameState.GAMEPLAY
                    and session.state.state == GameState.GAME_OVER):
                gp["cheat"].close()  # 10H: never hide the game-over screen
                shell.enter_game_over()
            gp["hud"].update(dt, mx, my, session, gp["panel"], mouse_down=held)
            gp["panel"].hover(mx, my, mouse_down=held)
            gp["panel"].update(dt)
            gp["overlays"].update(dt, mx, my, mouse_down=held)   # 10I: toggle-pill hover
            gp["floaters"].update(dt)
            # -- 10J: game log + FX watchers (building deaths -> purple burst
            # + kill message; enemy attack cadence -> muzzle/slash; enemy
            # deaths -> blood splatters, double-gated on gore) --
            gp["floaters"].watch_buildings(world.scene, gp["game_log"])
            gp["floaters"].watch_enemies(world.scene)
            gp["floaters"].spawn_death_events(session.state,
                                              shell.settings.gore)
            gp["game_log"].drain(session.state)
            gp["game_log"].update(dt)
            # -- /10J --
            gp["cheat"].update(dt, mx, my, mouse_down=held)  # 10H (animates its own buttons)
            if session.frozen:
                gp["levelup"].update(dt, mx, my, mouse_down=held)
                gp["boss_cutscene"].update(dt, mx, my, mouse_down=held)  # 10G (its phase only)
            if session.state.state == GameState.GAME_OVER:
                gp["game_over"].update(dt, mx, my, mouse_down=held)
        else:  # menu states + PAUSED
            shell.update(dt, mx, my, mouse_down=held)

        # 3. render submit — per state
        _t_render0 = time.perf_counter()
        window.fill(BACKGROUND)
        st = shell.state
        if st == GameState.CUTSCENE:
            surf = video.frame_surface()
            if surf is not None:
                window.blit(surf, (0, 0))
            renderer.submit_hud(HudText(
                "press any key to skip", (view_w // 2, view_h - 40),
                "md", (210, 210, 210), align="center"))
            _t_flush_start = time.perf_counter()
            renderer.flush(window)
        elif st in _WORLD_STATES or st == GameState.PAUSED:
            world = gp["world"]
            session = world.session
            # -- 10G boss: screen shake — a transient render-only camera-pan
            # jitter while a live boss walks the ENEMY phase (prototype
            # game.py:1879-1890). Undone right after flush, with NO clamp in
            # between, so the offset restores exactly; sim state untouched.
            shake_ox = shake_oy = 0
            if (session.state.phase == GamePhase.ENEMY
                    and any(getattr(b, "alive", False)
                            for b in world.scene.by_tag("boss"))):
                shake = enemies_balance["EnemyTypes"]["Boss"]["shake"]
                t_ms = time.perf_counter() * 1000.0
                period_ms = shake["interval"] * 1000.0
                shake_ox = int(math.sin(t_ms / period_ms * 6.28)
                               * shake["strength"])
                shake_oy = int(math.cos(t_ms / period_ms * 9.42)
                               * shake["strength"])
            if shake_ox or shake_oy:
                cs.pan(shake_ox, shake_oy)
            # -- /10G --
            # Ground (static terrain) via the cached surface: blitted first,
            # once, at the current pan offset (below the entities/deco/overlay
            # the layer order guarantees draw on top). Rebuilds only on zoom /
            # resize / panning past the margin / a zone change (unlock/recede
            # fires tile_map.on_zone_change -> invalidate) — not every frame.
            # The runtime zone overrides keep unlocked/receded tiles' ground
            # visuals in sync WITHOUT mutating the shared map_doc.
            ground_cache.ensure(
                view_w, view_h,
                lambda dmn, dmx, smn, smx: tilemap.band_render_items(
                    map_doc, dmn, dmx, smn, smx,
                    code_overrides=world.tile_map.terrain_overrides))
            ground_cache.blit(window)
            # Base + deco stay dynamic (their own layers, above ground); windowed.
            cmin, cmax, rmin, rmax = cs.visible_tile_window(view_w, view_h, margin=4)
            for item in tilemap.visible_render_items(
                    map_doc, cmin, cmax, rmin, rmax, terrain=False,
                    camera=show_camera_start, anim_time_ms=int(deco_clock_ms)):
                renderer.submit(item)
            # Condition art on the `terrain` layer — above the ground tiles,
            # below everything on `entities`/`deco`. Reuses the window above;
            # emits nothing for conditions with no imported sheet.
            for item in condition_render_items(
                    world.tile_map, cmin, cmax, rmin, rmax, condition_art,
                    anim_time_ms=int(deco_clock_ms)):
                renderer.submit(item)
            for item in world.scene.render_items():
                renderer.submit(item)
            # -- 10I: condition tint + RANGE/HEATMAP overlays — before the
            # panel submit so selection highlights draw over them; reuses the
            # visible-tile window computed above --
            gp["overlays"].submit(renderer, world.tile_map, world.scene,
                                  (cmin, cmax, rmin, rmax))
            # -- /10I --
            # -- 10J: blood + gold-highlight fills (world overlay, before the
            # panel's selection highlights) --
            gp["floaters"].submit_splatters(renderer, cs)
            gp["floaters"].submit_gold_highlights(renderer)
            # -- /10J --
            gp["floaters"].submit_craters(renderer, cs, world.scene)  # 10B: world
            gp["floaters"].submit_lightning(renderer, cs, world.scene)  # 10H
            gp["panel"].submit(renderer, session)
            gp["floaters"].submit_beams(renderer, cs, world.scene)    # 10B: HUD
            gp["floaters"].submit_hp_bars(renderer, cs, world.scene)
            gp["floaters"].submit_enemy_hp_bars(renderer, cs, world.scene)
            gp["floaters"].submit(renderer, cs)
            gp["floaters"].submit_projectiles(renderer, cs, world.scene)  # 10J
            gp["floaters"].submit_fx(renderer, cs)  # 10J sparks/shards/slashes
            gp["floaters"].submit_boss_bars(renderer, cs, world.scene,  # 10G
                                            session.state.phase, view_w, view_h)
            gp["floaters"].submit_announce(renderer, view_w, view_h)    # 10G
            gp["hud"].submit(renderer, session, view_w, view_h,
                             hover_cost=gp["panel"].hover_cost)
            gp["game_log"].submit(renderer, view_h)   # 10J: fading log lines
            gp["overlays"].submit_buttons(renderer)   # 10I: RANGE/HEATMAP pills
            if gp["levelup"].visible:
                gp["levelup"].submit(renderer, view_w, view_h)
            # -- 10G boss: the cutscene modal draws over everything below --
            if session.state.phase == GamePhase.BOSS_CUTSCENE:
                gp["boss_cutscene"].submit(renderer, view_w, view_h)
            # -- /10G --
            if session.state.state == GameState.GAME_OVER:
                gp["game_over"].submit(renderer, session.state, view_w, view_h)
            if st == GameState.PAUSED:
                shell.submit(renderer, view_w, view_h)  # overlay on frozen world
            # -- 10H: the cheat menu renders TOPMOST (prototype game.py:2061-62)
            if gp["cheat"].visible:
                gp["cheat"].submit(renderer, view_w, view_h)
            # -- /10H --
            _t_flush_start = time.perf_counter()
            renderer.flush(window)
            # -- 10G boss: undo the shake pan exactly (no clamp in between) --
            if shake_ox or shake_oy:
                cs.pan(-shake_ox, -shake_oy)
            # -- /10G --
        else:  # menu states — full-screen shell screen, no world
            shell.submit(renderer, view_w, view_h)
            _t_flush_start = time.perf_counter()
            renderer.flush(window)
        _t_flush_end = time.perf_counter()
        pygame.display.flip()
        _t_flip_end = time.perf_counter()

        perf["sim"] += _t_render0 - _t_sim0
        perf["submit"] += _t_flush_start - _t_render0
        perf["flush"] += _t_flush_end - _t_flush_start
        perf["flip"] += _t_flip_end - _t_flush_end
        perf_frames += 1

        fps_log_ms += dt * 1000
        if fps_log_ms >= 1000:
            if tune_gc and perf_frames:  # windowed only — keep headless silent
                n = perf_frames
                print(f"fps: {clock.get_fps():.1f}  "
                      f"sim={perf['sim'] / n * 1000:.1f}ms  "
                      f"submit={perf['submit'] / n * 1000:.1f}ms  "
                      f"flush={perf['flush'] / n * 1000:.1f}ms  "
                      f"flip={perf['flip'] / n * 1000:.1f}ms")
            else:
                print(f"fps: {clock.get_fps():.1f}")
            for k in perf:
                perf[k] = 0.0
            perf_frames = 0
            fps_log_ms = 0
        frames += 1
        if max_frames is not None and frames >= max_frames:
            running = False

    pygame.quit()
    return frames


if __name__ == "__main__":
    main()
