"""How To Be Human — window host (G-1). The ONLY entry point:

    py game/main.py

Creates the pygame window, runs the engine loop at the data-driven fps,
routes input. Camera input mapping lives here per E-5 (the engine holds
pure camera state): right-click-drag pans (clamped to map bounds),
scroll-wheel steps through the data-driven zoom levels (viewport centre
kept fixed), Esc opens the pause menu (was: quit). Frame order is fixed per
E-14: input -> Scene.update(dt) -> render submit.

All tunables come from data/ (G-7): geometry.json (tile pitch, zoom
levels), display.json (window size, fps, caption), and the ACTIVE MAP
(D-21). No iso math here — clicks and zoom anchoring go through
engine.coords only.

Phase 9G wired the in-round UI (game/ui): HUD (love/income/lives/phase +
End Turn + Pause), the building panel, floaters + HP bars, the game over
screen. Phase 9H wraps a run in the top-level shell (game.ui.Shell): the
intro CUTSCENE, MAIN_MENU, SETTINGS, CREDITS, ADD_NAME, PAUSED. The host
owns the pygame-only concerns the pure shell cannot: window (re)creation
for display mode, the cutscene frame blit, background music, the _World
lifecycle, and executing the shell's intent strings (new_game /
quit_to_menu / quit_app / set_display_mode / add_name_commit).
GAMEPLAY/GAME_OVER carry the live world; every other state is a
full-screen shell screen with no world. Phase TU-5 generalized the intro
cutscene into a registry-driven ``game.ui.cutscene_player.CutscenePlayer``
(``data/video/cutscenes.json``) and added a second, in-gameplay trigger:
``Session.end_turn()``'s ``pending_cutscene`` request freezes the sim and
overlays the matching cutscene the first time a round ends.

main(max_frames=N) lets tools/smoke.py drive the same code headlessly (G-8).

Phase G4 put the frame target behind ONE host-side seam, the "presenter":
`_SurfacePresenter` is today's SCALED display Surface verbatim, `_GpuPresenter`
is a standalone `_sdl2` Window + Renderer with the Surface-drawn HUD
composited over it as one streaming-texture upload per frame. Pick with
`--backend={auto,gpu,surface}` (default auto; `HTBH_RENDER_BACKEND` when there
is no argv); any GPU failure logs one line and falls back to the whole Surface
stack (D8). F12 saves the live frame to `build/`.
"""
import gc
import logging
import math
import os
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
from engine import input as key_input  # feature: rebindable hotkeys
from engine.assets import load_manifest, load_registry
from engine.assets import master_registry  # B1: the colour-column registry
from engine.assets.store import AssetStore
from engine.audio import play_music
from engine.coords import CameraLimit, load_coordinate_system
from engine.core import Scene, SpriteAnimator
from engine.physics import TileOccupancy
from engine.render import HudSprite, HudText, Renderer
from engine.render.fonts import configure_fonts
from engine.render.ground_cache import GroundCache
from game.buildings import BaseBuilding, attach_base
# -- 10I: defence-range coverage producer (injected into the tilemap) --
from game.buildings.coverage import wire_defence_coverage
# -- /10I --
# -- B1: the slots.json category whose slots may carry a colour column --
from game.buildings.registry import BUILDINGS_CATEGORY
# -- Building Movement: the in-transit sign slot + the cost/time formulas the
# destination-pick preview quotes --
from game.buildings.movement import (
    MOVING_SIGN_SLOT, move_cost, move_distance, move_time,
)
# -- BossUpgradeTimelinePLAN BU-3 3.1: the building-sweep half of the ONE-TIME
# `stone_thrower_sync` upgrade, installed into game/core's injected hook seam
# below (the host is the one layer that may import both packages) --
from game.buildings.boss_upgrade_effects import sync_stone_throwers
from game.buildings.components import SplashAttacker  # BU-3 3.3: the mortar
from game.core import Session, append_random_name, load_balance
from game.core import boss_upgrades  # BU-3: the one-time-hook seam
from game.core import highscores  # player-identity: the run-history document
from game.core import lightning  # BU-3 3.3: the stormpriest_slow hook seam
from game.core.phases import GamePhase, GameState
from game.debug import (  # debug-mode-telemetry
    DebugRecorder, LEVELS, LEVEL_BASIC, LEVEL_OFF, LEVEL_VERBOSE,
)
from game.debug import events as dbg
from game.enemies import (
    DEATH_ANIM, KIDNAP_ANIM, Spawner, apply_crowd_spacing, resolve_combat,
    restore_crowd_positions, set_kidnap_pose, spawn_corpse,
)
from game.enemies.components import (  # debug-mode-telemetry Phase 3 + 5
    set_damage_hook, set_wall_damage_hook,
)
from game.enemies.components import apply_slow  # BU-3 3.3: the slow primitive
from game.enemies.components import (  # BU-3 3.4: the thorns hook pair seam
    set_boss_upgrade_pair,
)
from game.map import (
    TileMap, condition_render_items, spawn_deco_render_items,
    spawn_tree_slots, tile_at_screen, wall_render_items,
)
from game.map.tiles import CONDITION_CATEGORY
from game.map.tiles import TileState  # 10J: multi-select category
from game.map.wall_render import FRONT_SIDES, WALL_CATEGORY
from game.tutorial import TutorialDirector  # TU-6
from game.ui import (
    BossCutscene, BuildingUI, CheatMenu, EnemyIntroWindow, FloaterManager,
    GameLog, GameOverScreen, Hud, LevelupWindow, MapOverlays, Shell,
    TutorialMessageScreen,
)
from game.ui import widgets  # 10L-A: R2 hit-seam wiring
from game.ui.building_ui import MovePreview  # Building Movement confirm modal
from game.ui.cutscene_player import CutscenePlayer, load_cutscene_registry
from game.ui.skinning import ScreenSkinning  # 10L-B: per-screen overrides
from game.ui.strings import configure_strings  # Phase C: global string table

BACKGROUND = (24, 20, 32)
_LEFT, _RIGHT = 1, 3
_DRAG_THRESHOLD_SQ = 4 * 4  # a left-press that moves less than this is a click
# cutscene skip prompt: fully visible for this many idle seconds, then fades
# to invisible over the following duration; any mouse movement snaps it back.
_SKIP_FADE_DELAY = 2.5
_SKIP_FADE_DURATION = 0.5
# HudLines points round to whole screen pixels (engine/render/item.py's
# round_half_up), so a small ring's growing tip only advances a rounded
# pixel every couple of frames and hops when it does — reads as jitter
# regardless of arc segment count, since the arc's endpoint is already an
# exact float angle. A wider stroke (_SKIP_RING_WIDTH) softens that hop
# instead — a 1px position jump reads as much less abrupt against a 3px-wide
# line than a 2px one, so the radius can stay small.
_SKIP_RING_RADIUS = 13
_SKIP_RING_WIDTH = 3
_WORLD_STATES = (GameState.GAMEPLAY, GameState.GAME_OVER)
_KEY_NAMES = None  # lazily built (needs pygame constants)

_log = logging.getLogger(__name__)


def _derive_colour_columns(registry, manifest, data_dir):
    """``{slot_key: (colour_name, ...)}`` for every BUILDINGS slot whose art is
    actually driven by a live colour column (MasterSheetColumnsPLAN B1).

    THE HOST DOES THIS LOOKUP, ONCE, AND PASSES THE RESULT DOWN. ``game/ui``
    and ``game/buildings`` may never reach into the asset layer themselves
    (D6) — the same rule (and the same derive-once-at-boot argument: art cannot
    change mid-run) that puts ``condition_art``/``tree_slots``/``wall_art`` in
    ``main()`` rather than in their consumers.

    A SLOT IS COLOUR-CAPABLE IFF BOTH HOLD:
      1. its master sheet declares ``columns`` (``columns_for`` is non-empty) —
         D6's stated rule; and
      2. its manifest entry has ``column_mode == "building_color"``.
    Condition 2 is the conjunct D6 does not state, and it is required by D3:
    under ``column_mode == "manual"`` the entry's own STORED ``column`` wins and
    a live column is ignored, so a manual slot would offer the player swatches
    that change nothing. It is recorded as an open finding for the section
    orchestrator; S4 faces the identical question for ``season``.

    E-37: a missing or unreadable registry degrades to an EMPTY map with ONE
    logged warning and never raises. An empty map simply means no building has
    colours — exactly the escape hatch the three derived-art blocks above use.
    """
    try:
        master_doc = master_registry.load_registry(data_dir)
    except Exception as exc:                       # noqa: BLE001 — E-37
        _log.warning(
            "master-sheet registry unreadable (%s) — no building has colour "
            "columns this run; the run itself is unaffected", exc)
        return {}
    colours = {}
    for slot in registry.group_slots(BUILDINGS_CATEGORY):
        entry = manifest.entry(slot)
        if entry is None or entry.column_mode != "building_color":
            continue
        names = master_registry.columns_for(master_doc, entry.sheet)
        if names:
            colours[slot] = names
    return colours


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
            # player-identity: the high-score table scrolls on Up/Down. No
            # gameplay handler binds an arrow key, so nothing is shadowed.
            pygame.K_UP: "up",
            pygame.K_DOWN: "down",
        }
    return _KEY_NAMES.get(key)


#: Keys `_binding_key_name` names explicitly, beyond bare letters/digits
#: (pygame's keycodes for the basic ASCII range equal the character's
#: ordinal, so `chr(event.key)` already gives "a".."z"/"0".."9" for those).
_BINDING_KEY_NAMES = None  # lazily built (needs pygame constants)


def _binding_key_names_table():
    """The pygame-keycode -> neutral-name table `_binding_key_name` and its
    reverse, `_binding_pygame_key`, both share — built once (needs pygame
    constants)."""
    global _BINDING_KEY_NAMES
    if _BINDING_KEY_NAMES is None:
        _BINDING_KEY_NAMES = {
            pygame.K_SPACE: "space",
            pygame.K_RETURN: "return",
            pygame.K_KP_ENTER: "return",
            pygame.K_ESCAPE: "escape",
            pygame.K_BACKSPACE: "backspace",
        }
    return _BINDING_KEY_NAMES


def _binding_key_name(event):
    """A KEYDOWN event's NEUTRAL binding string — "space", "ctrl+l", "h",
    "1", "return" — the vocabulary ``engine.input``'s bindings dict and
    ``data/keybindings.json`` use (feature: rebindable hotkeys). ``None`` for
    a key with no binding representation (arrow keys, function keys, …).

    ``game/ui`` never sees this (D5/G6): only this module's hotkey dispatch
    and the Controls screen's rebind-capture routing resolve a keypress
    through it, so a captured rebind and a dispatched hotkey can never
    disagree about what a key means. Numpad digits are deliberately NOT
    named here — they stay a fixed always-on alias in the combat-speed
    dispatch, outside the rebindable set (rebinding only ever changes the
    primary key)."""
    name = _binding_key_names_table().get(event.key)
    if name is None and 0 < event.key < 128 and chr(event.key).isalnum():
        name = chr(event.key)
    if name is None:
        return None
    if event.mod & pygame.KMOD_CTRL:
        return f"ctrl+{name}"
    return name


def _binding_pygame_key(binding):
    """Reverse of `_binding_key_name`: a binding string ("w", "ctrl+l") -> the
    base pygame keycode to poll, or `None` if it can't be resolved. The
    movement hotkeys are POLLED every frame via `pygame.key.get_pressed()`
    (held-down panning), not KEYDOWN-dispatched like every other action, so
    they need this reverse lookup instead of a live event's `.key`."""
    name = binding[len("ctrl+"):] if binding.startswith("ctrl+") else binding
    if len(name) == 1 and name.isalnum():
        return ord(name)
    for key, mapped in _binding_key_names_table().items():
        if mapped == name:
            return key
    return None


def _binding_held(binding, keys_pressed):
    """True while the (possibly rebound) key for `binding` is currently held
    down — the `keys[pygame.K_SPACE]` cutscene-hold-to-skip precedent,
    generalized to any binding string for the movement hotkeys."""
    base = _binding_pygame_key(binding)
    if base is None or not keys_pressed[base]:
        return False
    if binding.startswith("ctrl+"):
        return bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
    return True


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


_BACKEND_CHOICES = ("auto", "gpu", "surface")
_ENV_BACKEND = "HTBH_RENDER_BACKEND"


def backend_choice_from_argv(argv, env=None):
    """Parse ``--backend={auto,gpu,surface}`` (G4, plan D6).

    Hand-rolled in the same shape as ``debug_level_from_argv`` below and for
    the same reason: this and ``--debug`` are the entry point's only flags,
    and ``main``'s ``max_frames``/``autostart`` test seams must stay off the
    command line. The CLI flag WINS; ``HTBH_RENDER_BACKEND`` is consulted only
    when no flag is present (a double-clicked frozen build gets no argv).
    An unrecognised value exits LOUD — a silently ignored ``--backend=gpu``
    would make every A/B measurement a lie."""
    for arg in argv:
        if arg == "--backend":
            raise SystemExit(
                f"--backend needs a value, one of {list(_BACKEND_CHOICES)} "
                f"(e.g. --backend=gpu)")
        if arg.startswith("--backend="):
            value = arg.split("=", 1)[1].strip().lower()
            if value not in _BACKEND_CHOICES:
                raise SystemExit(
                    f"--backend must be one of {list(_BACKEND_CHOICES)}: "
                    f"{value!r}")
            return value
    value = (os.environ if env is None else env).get(_ENV_BACKEND, "")
    value = value.strip().lower()
    if not value:
        return "auto"
    if value not in _BACKEND_CHOICES:
        raise SystemExit(
            f"{_ENV_BACKEND} must be one of {list(_BACKEND_CHOICES)}: "
            f"{value!r}")
    return value


class _SurfacePresenter:
    """Today's frame target, verbatim (G4 §2.1): ONE ``pygame.SCALED`` display
    Surface that the world, the overlays and the HUD all draw into, presented
    with ``pygame.display.flip()``.

    ``hud_target`` is ``None``, so ``Renderer.flush`` keeps its historical
    single-call path — that is the whole no-regression argument for the D8
    fallback, the editor, ``tools/smoke.py`` and every existing render test."""

    name = "surface"
    hud_target = None

    def __init__(self, view_w, view_h, caption, display_mode):
        self._view_w, self._view_h = view_w, view_h
        self._caption = caption
        self._window = _apply_display_mode(display_mode, view_w, view_h,
                                           caption)
        self.last_composite_ms = 0.0   # no composite on this path, ever

    @property
    def world_target(self):
        return self._window

    def begin_frame(self):
        self._window.fill(BACKGROUND)

    def blit_fullscreen(self, surface):
        self._window.blit(surface, (0, 0))

    def set_display_mode(self, mode):
        self._window = _apply_display_mode(mode, self._view_w, self._view_h,
                                           self._caption)

    def map_event(self, event):
        return event          # SCALED already remaps mouse coords for free

    def mouse_pos(self):
        return pygame.mouse.get_pos()

    def end_frame(self, capture_path=None):
        if capture_path is not None:
            pygame.image.save(self._window, str(capture_path))
        pygame.display.flip()

    def describe(self):
        return (f"render backend: Surface (CPU blitter) | window "
                f"{self._view_w}x{self._view_h} SCALED | "
                f"ground cache: GroundCache")

    def close(self):
        pass


class _GpuPresenter:
    """The GPU frame target (G4 §2.1/§2.4): a standalone ``_sdl2`` Window +
    Renderer, with the Surface-drawn HUD composited over it as ONE streaming-
    texture upload per frame.

    Two measured mechanics decide this shape and must not be "simplified":
    - ``pygame.display.set_mode`` is NOT used at all. An SDL ``Renderer``
      cannot attach to the display-module window (``Surface already associated
      with window``), and ``Renderer.from_window`` "works" only by handing back
      SCALED's own internal renderer, whose frame ``display.flip()`` then
      overwrites. Hence a standalone window and ``renderer.present()``.
    - The HUD is NEVER a ``DrawCall`` handed to ``backend_gpu``: that backend's
      texture cache SNAPSHOTS a source surface at first upload and never
      refreshes it, and the HUD surface is mutated every frame. It would freeze
      at frame 1 with no exception and no log line. So the host owns an
      explicit streaming ``Texture`` and calls ``update()`` every frame."""

    name = "gpu"

    def __init__(self, view_w, view_h, caption, display_mode):
        from pygame._sdl2 import video as sdl2
        self._sdl2 = sdl2
        self._view_w, self._view_h = view_w, view_h
        self._window = sdl2.Window(caption, size=(view_w, view_h))
        # target_texture=True because GroundCacheGpu is built entirely on
        # render-target Textures. The software/dummy renderer happens to allow
        # targets without the flag (which is why G3's suite is green without
        # it); a real D3D/OpenGL driver may not.
        self._renderer = sdl2.Renderer(self._window, target_texture=True)
        # The SCALED equivalent: the game keeps drawing at 640x360 whatever the
        # window is, and coordinates_from_window maps clicks back (§2.6).
        self._renderer.logical_size = (view_w, view_h)
        # The HUD's own frame target: a screen-sized SRCALPHA Surface the
        # Surface backend draws into (fonts, nine-slice, crop — D7 keeps them
        # single-implementation), uploaded once per frame in end_frame().
        self.hud_target = pygame.Surface((view_w, view_h), pygame.SRCALPHA)
        self._hud_texture = self._new_streaming_texture()
        self._fullscreen_texture = None   # cutscene only, built on first use
        self._fullscreen_scratch = None
        self.last_composite_ms = 0.0
        self.set_display_mode(display_mode)

    def _new_streaming_texture(self):
        tex = self._sdl2.Texture(
            self._renderer, (self._view_w, self._view_h), streaming=True,
            scale_quality=self._sdl2.SCALEQUALITY_NEAREST)
        # MEASURED: the constructor leaves blend_mode at BLENDMODE_NONE (0),
        # the same trap G2 hit. Unset, the HUD's transparent pixels paint an
        # opaque black sheet over the whole world.
        tex.blend_mode = pygame.BLENDMODE_BLEND
        return tex

    @property
    def sdl_renderer(self):
        return self._renderer

    @property
    def world_target(self):
        return self._renderer

    def begin_frame(self):
        self._renderer.draw_color = tuple(BACKGROUND) + (255,)
        self._renderer.clear()
        self.hud_target.fill((0, 0, 0, 0))

    def blit_fullscreen(self, surface):
        """A full-screen opaque paint (a cutscene video frame). On the Surface
        path this COVERS everything drawn so far, HUD included — so the HUD
        surface is cleared here too, or the composite at end_frame would put
        the game's HUD back on top of the video."""
        if self._fullscreen_texture is None:
            self._fullscreen_texture = self._new_streaming_texture()
        if surface.get_size() != (self._view_w, self._view_h):
            if self._fullscreen_scratch is None:
                self._fullscreen_scratch = pygame.Surface(
                    (self._view_w, self._view_h), pygame.SRCALPHA)
            self._fullscreen_scratch.fill((0, 0, 0, 0))
            self._fullscreen_scratch.blit(surface, (0, 0))
            surface = self._fullscreen_scratch
        self._fullscreen_texture.update(surface)
        self._fullscreen_texture.draw(
            dstrect=pygame.Rect(0, 0, self._view_w, self._view_h))
        self.hud_target.fill((0, 0, 0, 0))

    def set_display_mode(self, mode):
        window = self._window
        if mode == "fullscreen":
            window.borderless = False
            window.set_fullscreen(desktop=True)
        elif mode == "borderless":
            window.set_windowed()
            window.borderless = True
        else:
            window.set_windowed()
            window.borderless = False

    def _to_logical(self, point):
        x, y = self._renderer.coordinates_from_window(point)  # floats
        return int(x), int(y)

    def map_event(self, event):
        """IDENTITY — and that is the measured, non-obvious part.

        pygame-ce ALREADY delivers mouse EVENTS in renderer-logical
        coordinates once ``renderer.logical_size`` is set, exactly as it does
        under ``pygame.SCALED``. MEASURED on pygame-ce 2.5.7 / SDL 2.32.10: a
        1280x720 window at logical 640x360 (scale 2) clicked at physical
        (640, 360) delivers ``event.pos == (320, 180)``; the same window at
        logical 320x180 (scale 4) delivers ``(160, 90)``. ``MOUSEMOTION.rel``
        rides the same scale — a physical (+200, +100) move arrives as
        ``rel == (100, 50)``.

        G4 originally mapped ``pos``/``rel`` through
        ``coordinates_from_window`` here, which applied that scale a SECOND
        time: at the shipped fullscreen default (1920x1080 window, logical
        640x360, scale 3) every click landed at a third of its true position,
        so no button ever fired while hover — which reads ``mouse_pos()``, a
        different and genuinely unmapped source — kept working. Do not
        reintroduce the mapping here.

        The seam itself stays: it is the one insertion point if a future SDL
        or pygame version stops doing this for us, and the Surface presenter
        implements the same identity for symmetry."""
        return event

    def mouse_pos(self):
        # NOT the identity: pygame.mouse.get_pos() is the OTHER half of the
        # asymmetry above — it returns WINDOW PIXELS, unscaled by the
        # renderer's logical size (measured: (640, 360) where the matching
        # event reported (320, 180)). So this one really does need the remap.
        return self._to_logical(pygame.mouse.get_pos())

    def end_frame(self, capture_path=None):
        t0 = time.perf_counter()
        self._hud_texture.update(self.hud_target)   # ONE upload per frame
        self._hud_texture.draw(
            dstrect=pygame.Rect(0, 0, self._view_w, self._view_h))
        self.last_composite_ms = (time.perf_counter() - t0) * 1000.0
        # After the composite, before present: the PNG is the whole frame.
        if capture_path is not None:
            pygame.image.save(self._renderer.to_surface(), str(capture_path))
        self._renderer.present()

    def describe(self):
        # pygame-ce 2.5.7 exposes no per-renderer driver query (no
        # get_renderer_info), so this names the FIRST driver SDL offers —
        # which is the one SDL_CreateRenderer(index=-1) takes when it
        # succeeds. Approximate by construction; say so rather than imply a
        # readback.
        try:
            driver = next(iter(self._sdl2.get_drivers())).name
        except Exception:                                     # noqa: BLE001
            driver = "unknown"
        w, h = self._window.size
        return (f"render backend: GPU (SDL2 texture, {driver}) | window "
                f"{self._view_w}x{self._view_h} logical, {w}x{h} actual | "
                f"ground cache: GroundCacheGpu")

    def close(self):
        try:
            self._window.destroy()
        except Exception:                                     # noqa: BLE001
            pass


def _build_render_stack(choice, view_w, view_h, caption, display_mode, cs,
                        assets):
    """Build the frame target + Renderer + ground cache as ONE unit, and
    return ``(presenter, renderer, ground_cache, log_line)``.

    D8: any failure creating the window, the renderer, the HUD texture or the
    ground-cache render targets logs one line and falls back to the WHOLE
    Surface stack — never a hard failure, and never a GPU/Surface hybrid (a
    half-migrated host has no defined draw order)."""
    if choice in ("auto", "gpu"):
        presenter = None
        try:
            from engine.render import backend_gpu
            from engine.render.ground_cache_gpu import GroundCacheGpu
            presenter = _GpuPresenter(view_w, view_h, caption, display_mode)
            renderer = Renderer(cs, assets, backend=backend_gpu.draw)
            ground_cache = GroundCacheGpu(presenter.sdl_renderer, cs, assets,
                                          bg_color=BACKGROUND)
            return presenter, renderer, ground_cache, presenter.describe()
        except Exception as exc:                              # noqa: BLE001
            if presenter is not None:
                presenter.close()
            surface = _SurfacePresenter(view_w, view_h, caption, display_mode)
            return (surface, Renderer(cs, assets),
                    GroundCache(cs, assets, bg_color=BACKGROUND),
                    f"render backend: Surface (CPU blitter) — GPU requested "
                    f"but unavailable: {type(exc).__name__}: {exc}")
    presenter = _SurfacePresenter(view_w, view_h, caption, display_mode)
    return (presenter, Renderer(cs, assets),
            GroundCache(cs, assets, bg_color=BACKGROUND), presenter.describe())


def _capture_path(backend_name):
    """``build/capture_<backend>_<stamp>.png`` — build/ is gitignored, so a
    capture can never dirty the tree, and the filename carries the backend so
    a PAIR of PNGs is self-identifying without the terminal."""
    out = REPO / "build"
    out.mkdir(parents=True, exist_ok=True)
    return out / (f"capture_{backend_name}_"
                  f"{time.strftime('%Y%m%d-%H%M%S')}.png")


class _World:
    """The rebuildable run state: tile grid, occupancy, scene, session. A fresh
    ``_World`` is a fresh game (the base is re-attached to its pre-seeded tile)."""

    def __init__(self, map_doc, map_bal, enemies_bal, core_bal, buildings_bal,
                 registry, progression_bal=None, boss_upgrades_bal=None):
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
                                      occupancy=self.occupancy,
                                      progression_balance=progression_bal,
                                      boss_upgrades_balance=boss_upgrades_bal)
        # -- 10I: defence coverage feeds enemy path weights (pre-query refresh
        # in the pathfinder reads the injected callable) --
        wire_defence_coverage(self.tile_map, buildings_bal)
        # -- /10I --


def _recenter_zoom(cs, new_zoom, view_w, view_h):
    """Apply `new_zoom`, keeping the world point at the viewport centre fixed
    (coords authority only, E-5) — the shared body of `step_zoom` (a relative
    step) and `set_zoom_level` (an absolute jump, feature: rebindable
    hotkeys)."""
    cx, cy = view_w / 2, view_h / 2
    anchor = cs.screen_to_world(cx, cy)
    cs.set_zoom(new_zoom)
    px, py = cs.world_to_screen(*anchor)
    cs.pan(px - cx, py - cy)
    cs.clamp(view_w, view_h)


def step_zoom(cs, direction, view_w, view_h):
    """Move one step through the data-driven zoom levels, keeping the world
    point at the viewport centre fixed."""
    levels = sorted(cs.geometry.zoom_levels)
    i = levels.index(cs.camera.zoom) + direction
    if not 0 <= i < len(levels):
        return
    _recenter_zoom(cs, levels[i], view_w, view_h)


def set_zoom_level(cs, index, view_w, view_h):
    """Jump straight to the zoom level at `index` (0-based, sorted ascending)
    — `step_zoom`'s ABSOLUTE-jump sibling for the zoom-level hotkeys (feature:
    rebindable hotkeys). A silent no-op if that index doesn't exist (fewer
    zoom levels authored than hotkeys) — the combat-speed round-gate
    precedent."""
    levels = sorted(cs.geometry.zoom_levels)
    if not 0 <= index < len(levels):
        return
    _recenter_zoom(cs, levels[index], view_w, view_h)


def _cutscene_skip_alpha(idle_t):
    """255 for the first ``_SKIP_FADE_DELAY`` idle seconds, then ramps to 0
    over the following ``_SKIP_FADE_DURATION`` — the cutscene skip prompt's
    idle fade (feature: cutscene skip UI polish)."""
    if idle_t <= _SKIP_FADE_DELAY:
        return 255
    k = (idle_t - _SKIP_FADE_DELAY) / _SKIP_FADE_DURATION
    return max(0, round(255 * (1.0 - min(1.0, k))))


def _submit_cutscene_skip(renderer, view_w, view_h, skip_progress, idle_t):
    """The "hold to skip" ring + text, bottom-right, fading together after
    ``_SKIP_FADE_DELAY`` idle seconds (feature: cutscene skip UI polish).
    ``HudLines`` (what the ring is built from) carries no per-pixel alpha
    (`game/ui/CLAUDE.md`'s beam-FX note), so the ring's fade is approximated
    by lerping its line colors toward black by the same fraction the text's
    real alpha is fading by — the same color-ramp technique the lightning
    charge bar uses where true alpha isn't available."""
    alpha = _cutscene_skip_alpha(idle_t)
    if alpha <= 0:
        return
    k = alpha / 255.0

    def _dim(c):
        return tuple(round(v * k) for v in c)

    text = "hold to skip"
    tw, th = widgets.text_size(text, "md")
    text_x, text_y = view_w - 8, view_h - 8 - th
    # Ring stacks ABOVE the text (not beside it) so its diameter never
    # overflows the row when placed this close to the bottom edge.
    ring_cx = text_x - tw // 2
    ring_cy = text_y - 4 - _SKIP_RING_RADIUS
    widgets.submit_progress_ring(
        renderer, ring_cx, ring_cy, _SKIP_RING_RADIUS, skip_progress,
        bg=_dim(widgets.C_UI_TEXT_DIM), fill=_dim(widgets.C_GOLD),
        width=_SKIP_RING_WIDTH)
    renderer.submit_hud(HudText(
        text, (text_x, text_y), "md", _dim((210, 210, 210)) + (alpha,),
        align="right"))


def main(max_frames=None, data_dir=None, autostart=False, debug_log=None,
         backend=None):
    """``autostart=True`` skips the shell (cutscene/menu) and boots straight into
    a fresh GAMEPLAY run — the headless test seam so tools/smoke.py and the boot
    tests still exercise the full _World/Session construction + sim frames the
    shell would otherwise defer until START NEW GAME.

    ``debug_log`` (debug-mode-telemetry — the CLI/menu activation seam):
    ``None`` (default) — debug off, every code path byte-identical (the
    guardrail this whole feature is built on). An ``int`` (``game.debug.
    LEVEL_BASIC``/``LEVEL_VERBOSE``) builds a fresh ``DebugRecorder`` writing
    to ``REPO / "logs"``. An already-constructed ``DebugRecorder`` is used
    as-is — the seam headless callers/tests (and Phase 5's CLI flag) drive
    directly, e.g. to pick a custom ``out_dir``/``outputs``/``run_id``. The
    recorder (if any) is bound to the run's ``RunState`` and assigned to
    ``session.debug`` inside ``build_gameplay()`` below, and closed at the
    game-over transition and again (idempotent) just before ``pygame.quit()``.
    Phase 5 (CLI flag + menu buttons) builds on top of this — see the
    docstring note beside ``recorder`` below for exactly how.

    ``backend`` (G4) is one of ``"auto"`` / ``"gpu"`` / ``"surface"``;
    ``None`` (the default) means ``"auto"``. ``__main__`` passes what
    ``backend_choice_from_argv`` parsed. **``max_frames is not None`` forces
    the Surface path** unless the caller asked for ``"gpu"`` explicitly —
    that single condition is how ``tools/smoke.py`` and every headless boot
    test stay on today's stack without any change of their own."""
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    # debug-mode-telemetry: `recorder` is a plain local, deliberately NOT
    # nested inside an `if` — so a later dispatch (Phase 5's "PLAY DEBUG"
    # menu button / cheat-menu arm-disarm toggle) can reassign it with
    # `nonlocal recorder` from `execute()`/`_execute_cheat()` without
    # restructuring this function. `None` (the default) is debug off.
    recorder = None
    if isinstance(debug_log, DebugRecorder):
        recorder = debug_log
    elif isinstance(debug_log, int) and debug_log > LEVEL_OFF:
        recorder = DebugRecorder(REPO / "logs", level=debug_log)
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

    # The camera leash: how far the player may drag the view from the map's
    # camera_limit_center marker — the designer-painted CENTRE of the play
    # area, which the camera never starts on. A map that paints none falls
    # back to camera_start, then to the map centre. Installed on `cs` rather
    # than passed per call, so every clamp site — drag-pan, step_zoom,
    # frame_camera's center_on — honours it with no extra wiring; the editor
    # never installs one, so its viewport stays free-roam. 0 = unlimited.
    _cam = core_balance["Camera"]
    _marker = map_doc.camera_limit_center or map_doc.camera_start
    _anchor = ((_marker["col"], _marker["row"]) if _marker is not None
               else (map_doc.cols / 2, map_doc.rows / 2))
    cs.set_camera_limit(CameraLimit(
        _anchor[0], _anchor[1],
        max_tiles_x=_cam["max_offset_tiles_x"],
        max_tiles_y=_cam["max_offset_tiles_y"]))

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
    # Spawn-band tree family, manifest-filtered the same way `condition_art`
    # is: art cannot change mid-run, so it is derived once here rather than
    # per frame. An empty tuple (no tree slots imported yet) makes
    # `spawn_deco_render_items` a no-op, same escape hatch as `condition_art`.
    tree_slots = tuple(
        s for s in spawn_tree_slots(registry)
        if manifest.entry(s) is not None)
    # Edge-wall art, manifest-filtered exactly like the two above: art cannot
    # change mid-run, so it is derived once here rather than per frame. An
    # empty set (no wall tier imported yet) makes `wall_render_items` a no-op —
    # the same E-37 escape hatch `condition_art`/`tree_slots` use, i.e. an
    # un-imported wall draws nothing rather than the grey-X placeholder.
    wall_art = frozenset(
        s for s in registry.group_slots(WALL_CATEGORY)
        if manifest.entry(s) is not None)
    # Building Movement: the in-transit signpost. Manifest-filtered exactly
    # like the three above (art cannot change mid-run, so it is derived once
    # here) — False means the slot has no imported sheet and the overlay draws
    # only its round countdown, never the grey-X placeholder (E-37).
    moving_sign_art = manifest.entry(MOVING_SIGN_SLOT) is not None
    # B1: which building slots offer master-sheet colour columns, and their
    # names. Derived once here for the same reason as the four blocks above —
    # art cannot change mid-run — and handed down to the placement seam
    # (`place_building(..., colour_columns=...)`) and to the construct panel.
    # An empty map (today's live data, which declares no `columns` yet) means
    # no building rolls a colour and every animator keeps its -1 sentinel.
    colour_columns = _derive_colour_columns(registry, manifest, data_dir)
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
    # Phase C: the global UI string table — same fail-loud D-2 load as
    # fonts/palette above (boot config data, not art; E-37 does not apply).
    strings_doc = data_io.load_validated(
        data_dir / "ui" / "strings.json",
        data_dir / "schemas" / "strings.schema.json")
    # UH-Font-A: the game-wide custom font family, ORTHOGONAL to the 7-preset
    # size/bold system above. "default" means today's SysFont behavior; any
    # other id must resolve to a data/fonts/font_manifest.json entry whose
    # file exists on disk — a cross-file check a schema can't express, so it
    # is cross-checked here and fails LOUD (D-2, the engine.tilemap.load_map
    # precedent) rather than degrading like the editor's Theme panel does.
    font_manifest_doc = data_io.load_validated(
        data_dir / "fonts" / "font_manifest.json",
        data_dir / "schemas" / "font_manifest.schema.json")
    active_font_doc = data_io.load_validated(
        data_dir / "ui" / "active_font.json",
        data_dir / "schemas" / "active_font.schema.json")
    active_font_id = active_font_doc["font_id"]
    font_path = None
    if active_font_id != "default":
        entry = font_manifest_doc["entries"].get(active_font_id)
        if entry is None:
            raise ValueError(
                f"active_font.json references unknown font id {active_font_id!r} "
                f"(no such entry in data/fonts/font_manifest.json)")
        font_path = (data_dir / "fonts" / entry["file"]).resolve()
        if not font_path.is_file():
            raise ValueError(
                f"active_font.json's font {active_font_id!r} points at "
                f"{font_path} which does not exist on disk")
    # UH-Font-B: EVERY manifest entry, so a screen doc can name a family
    # other than the active one per text run. Same D-2 loudness as the active
    # font above — a manifest entry whose file is missing is a broken tree,
    # not something to silently skip, and finding out at boot beats finding
    # out when the one screen that uses it is opened.
    family_paths = {}
    for family_id, entry in font_manifest_doc["entries"].items():
        family_path = (data_dir / "fonts" / entry["file"]).resolve()
        if not family_path.is_file():
            raise ValueError(
                f"font_manifest.json entry {family_id!r} points at "
                f"{family_path} which does not exist on disk")
        family_paths[family_id] = family_path
    configure_fonts(fonts_doc, font_path=font_path, family_paths=family_paths)
    widgets.configure_palette(palette_doc)
    configure_strings(strings_doc)
    # G4: the Renderer and the ground cache are built AFTER the presenter (the
    # GPU variants need its SDL Renderer, which needs the window, which needs
    # the shell's display mode) — see _build_render_stack below. Nothing
    # between here and there used either object before the move.
    map_bal = load_balance(data_dir, "map")
    buildings_balance = load_balance(data_dir, "buildings")
    enemies_balance = load_balance(data_dir, "enemies")
    ui_balance = load_balance(data_dir, "ui")
    vfx_balance = load_balance(data_dir, "vfx")  # ESV-3a: procedural VFX params
    # feature: rebindable hotkeys — `ui.json`'s `Keybindings` group is the
    # DESIGNER-EDITABLE default for every rebindable action (indexed
    # directly, never `.get` — the schema requires the key, D-2, the
    # `ui_balance["Debug"]` precedent just below). The player's LIVE bindings
    # (any in-Settings rebind) live in the gitignored `scores/` dir, the
    # `highscores.json` precedent — read tolerantly (a corrupt save file
    # falls back to the defaults, one logged warning, never crashes boot).
    keybindings_schema_path = data_dir / "schemas" / "keybindings.schema.json"
    keybindings_defaults = ui_balance["Keybindings"]
    keybindings_path = REPO / "scores" / "keybindings.json"
    key_bindings = key_input.load_keybindings(
        keybindings_path, keybindings_schema_path, keybindings_defaults)
    # VA-5: the seven tile highlights are effects now — colour/outline/fill and
    # their sprite bindings come from this same doc. Same fail-loud-on-mismatch
    # shape as configure_palette above, and the same boot slot, which is where
    # three of these colours used to live.
    widgets.configure_highlights(vfx_balance)
    # TimelinePLAN T4: the sole source of unlock timing (game/core/levelup.py).
    progression_balance = load_balance(data_dir, "progression")
    # BossUpgradeTimelinePLAN BU-1: the boss upgrade catalog + milestone
    # timeline (game/core/boss_upgrades.py), threaded onto the Session beside
    # progression_balance.
    boss_upgrades_balance = load_balance(data_dir, "boss_upgrades")
    # BU-3 3.1: install the injected half of the ONE-TIME `stone_thrower_sync`
    # upgrade (#9). `game/core/boss_upgrades.py` may never import
    # `game.buildings`, so the building sweep arrives through this seam — and
    # the HOST is the one layer allowed to import both packages. Once per
    # process, at boot, beside the other host wiring; `apply_pick` calls it
    # only when it has a tilemap AND a scene in hand.
    boss_upgrades.set_one_time_hook("stone_thrower_sync", sync_stone_throwers)

    # BU-3 3.3: `mortar_slow` (#3) is a PERSISTENT passive that still needs one
    # action at PICK time — D16's snapshot: only the mortars ALIVE when the
    # upgrade was picked ever slow, so the set of eligible mortars is frozen
    # here and read back at fire time (`game/enemies/combat.py`'s
    # `_mortar_slow_spec`). It rides the SAME `set_one_time_hook` seam
    # `stone_thrower_sync` uses — the table is keyed by upgrade id and does not
    # care which category the id belongs to (see `boss_upgrades.py`'s docstring).
    def _snapshot_mortar_slow(state, tilemap, scene):
        """Stamp `RunState.mortar_slow_snapshot_ids` with every placed mortar.

        Selected by the `SplashAttacker` CAPABILITY MARKER, never a class or a
        `building_type` string (G-3) — and specifically because that is the
        exact same marker `_update_defender` dispatches the splash-fire path
        on, so the snapshot and the application site can never disagree about
        what "a mortar" is. Walks `built_tiles()` (the `_by_state` index, i.e.
        O(built tiles), never a full-map scan — the large-map invariant), the
        same enumeration `boss_upgrade_effects.placed_buildings` uses. A DEAD
        mortar counts: it is not a freed slot, payday's revive brings it back.
        `scene` is part of the fixed hook signature and is unused here.
        """
        state.mortar_slow_snapshot_ids = {
            id(t.occupant) for t in tilemap.built_tiles()
            if t.occupant is not None
            and t.occupant.get_component(SplashAttacker) is not None}

    boss_upgrades.set_one_time_hook("mortar_slow", _snapshot_mortar_slow)
    # BU-3 3.3: `stormpriest_slow` (#7) applies the shared slow primitive from
    # inside `game/core/lightning.py`, which may not import `game/enemies` —
    # so the host hands it over, exactly like the one-time hook above.
    lightning.set_slow_hook(apply_slow)
    # debug: draw the camera-startpoint marker in-game (default off)
    show_camera_start = ui_balance["Debug"]["show_camera_startpoint"]

    # Cutscenes (TU-5): one CutscenePlayer per data/video/cutscenes.json entry
    # (TU-1). "intro" is the pre-gameplay shell state (graceful skip if
    # cv2/file absent -> MAIN_MENU); "first_end_turn" is an in-gameplay
    # overlay Session.end_turn() requests via state.pending_cutscene.
    cutscene_registry = load_cutscene_registry(data_dir)
    cutscenes = {
        cid: CutscenePlayer(data_dir, entry, target_size=(view_w, view_h))
        for cid, entry in cutscene_registry.items()
    }
    intro_player = cutscenes.get("intro")
    start = (GameState.CUTSCENE if intro_player and intro_player.enabled
             else GameState.MAIN_MENU)
    # 10L-B: one ScreenSkinning for the whole run, loaded once here (the
    # shell shares it with its five menu screens; build_gameplay threads the
    # SAME instance into the seven gameplay screens it constructs itself).
    skinning = ScreenSkinning(data_dir)
    # player-identity: `core.json`'s `Debug` group gates the menu's two
    # launcher rows and the identity prompt. Indexed directly, never `.get` —
    # the schema requires the key, so missing data must fail LOUD (D-2).
    shell = Shell(view_w, view_h, ui_balance, start_state=start,
                 skinning=skinning, debug_balance=core_balance["Debug"],
                 key_bindings=key_bindings)
    shell.set_pool_count(len(buildings_balance["BuildingsGlobal"]["random_names"]))
    # player-identity: the run history lives in the gitignored `scores/` dir at
    # the repo root, NOT in `data/` — it is per-machine play history. Read once
    # here to seed the high-score table and pre-fill the identity prompt with
    # whoever played last; re-read on every `open_highscores` intent below.
    scores_path = highscores.default_path(REPO)
    hs_doc = highscores.load_highscores(scores_path, data_dir)
    shell.set_highscores(hs_doc)
    shell.prefill_identity(*highscores.last_player(hs_doc))

    # G4 (D6/D8): pick the frame target, and with it the render backend and the
    # ground cache — one stack, chosen once, falling back whole. `auto` tries
    # the GPU path; a headless run (`max_frames is not None`, the same seam
    # `tune_gc` uses) stays on the Surface path unless GPU was asked for
    # explicitly, which is how tools/smoke.py needs no flag of its own.
    choice = backend if backend is not None else "auto"
    if choice == "auto" and max_frames is not None:
        choice = "surface"
    presenter, renderer, ground_cache, backend_log = _build_render_stack(
        choice, view_w, view_h, caption, shell.settings.display_mode, cs,
        assets)
    # print(), NOT _log.info: this module's logger has no basicConfig, so an
    # info record is silently dropped — and this line's whole purpose is
    # screenshot self-identification (which backend am I looking at?).
    print(backend_log)
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
          "game_log": None, "sel": [], "sel_cat": None,
          # -- drag-select: the HUD toggle's state (box-select vs. camera pan) --
          "drag_select_enabled": False,
          # -- TU-5: active in-gameplay cutscene overlay, None when none playing --
          "cutscene": None,
          # -- TU-6: the guided-chain director + its Continue/Skip message box --
          "tutorial": None, "tutorial_message": None}

    # player-identity: the per-run latch that keeps the GAME_OVER transition
    # from appending a second high-score row every frame the state holds.
    # Reset for each fresh run in `build_gameplay()`.
    score_recorded = False

    def build_gameplay():
        nonlocal score_recorded
        score_recorded = False
        gp["world"] = _World(map_doc, map_bal, enemies_balance, core_balance,
                             buildings_balance, registry, progression_balance,
                             boss_upgrades_balance)
        # Ground follows runtime zone changes: unlock/recede invalidates the
        # cached ground surface (repainted next ensure). Fresh game -> fresh
        # TileMap with empty overrides; invalidate drops the previous run's
        # unlocked-tile visuals too.
        gp["world"].tile_map.on_zone_change = ground_cache.invalidate
        ground_cache.invalidate()
        # 10L-B: every gameplay screen shares the shell's ScreenSkinning (the
        # shell owns no world, so it cannot construct these itself).
        gp["hud"] = Hud(view_w, view_h, skinning=shell.skinning,
                        ui_balance=ui_balance)
        gp["panel"] = BuildingUI(view_w, view_h, ui_balance,
                                 skinning=shell.skinning)
        # -- TU-6: the round-1 guided-chain director + its message box. Reads
        # data/tutorial/tutorial.json + the map's tutorial_flute marker;
        # auto-skips (never crashes) on an old/unpainted map. --
        gp["tutorial"] = TutorialDirector(data_dir, map_doc,
                                          core_balance["Tutorial"])
        gp["tutorial_message"] = TutorialMessageScreen(
            view_w, view_h, gp["tutorial"].skippable(), skinning=shell.skinning)
        gp["world"].session.tutorial_gate = gp["tutorial"].allows_end_turn
        gp["world"].session.tutorial_director = gp["tutorial"]  # TU-7
        # -- TU-9: an ACTIVE tutorial run starts at round 0 (its own scripted
        # round, always a single forced walker) so real enemy scaling begins
        # at round 1 exactly where it always did. A `RunState` defaults to
        # round 1 (`from_balance`), which is what an old/unpainted map (an
        # auto-skipped, inactive director) and every bare-Session logic test
        # keep — this is the ONE seed site, deliberately host-side rather
        # than a `Session`/`RunState` default, so those stay untouched.
        if gp["tutorial"].active:
            gp["world"].session.state.round_num = 0
        # -- /TU-6 --
        # debug-mode-telemetry: bind the (optional) recorder to THIS run's
        # RunState. `recorder` is the outer main()-scoped variable (closure
        # read, never reassigned here) — None is the default and leaves
        # session.debug at its own None default, byte-identical.
        if recorder is not None:
            gp["world"].session.debug = recorder
            recorder.bind(gp["world"].session.state)
            recorder.emit(
                dbg.RUN_START, level=recorder.level, run_id=recorder.run_id,
                map_id=map_doc.map_id, seed=None,
                love=gp["world"].session.state.love,
                lives=gp["world"].session.state.base_lives,
                # player-identity: read off the RECORDER, never the shell, so
                # the event can never disagree with the run id the four
                # artifact filenames are stamped with.
                player_name=recorder.player_name,
                player_skill=recorder.player_skill)
        gp["floaters"] = FloaterManager(ui_balance, core_balance, vfx_balance)
        gp["game_over"] = GameOverScreen(view_w, view_h, skinning=shell.skinning)
        gp["levelup"] = LevelupWindow(view_w, view_h, skinning=shell.skinning)
        gp["boss_cutscene"] = BossCutscene(view_w, view_h,  # -- 10G boss --
                                          core_balance,
                                          skinning=shell.skinning,
                                          # BU-4: the 3 upgrade cards' copy +
                                          # magnitudes and this bossfight's
                                          # milestone slots.
                                          boss_upgrades_balance=(
                                              boss_upgrades_balance))
        # feature-enemy-intro-dialogue
        gp["enemy_intro"] = EnemyIntroWindow(
            view_w, view_h, core_balance["EnemyIntro"]["window"],
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
        # drag-select: the HUD toggle's state lives HERE, not on the Hud, so
        # the event loop can read it when it decides drag-select vs. camera pan.
        gp["drag_select_enabled"] = False
        gp["panel"].log = gp["game_log"]
        gp["panel"].on_build_vfx = gp["floaters"].spawn_building_vfx
        # The construct card's portrait asks the store whether a dedicated
        # `card_portrait_*` slot has imported art before falling back to the
        # building's own tier sprite (the `floaters.assets` precedent below;
        # None-safe, so a bare BuildingUI in a test needs no store).
        gp["panel"].assets = assets
        # The HUD asks the store the same kind of question: whether the life
        # icon slot really carries a `disabled` (dead) row, and how long its
        # `pressed` (dying) row runs for. Pure manifest metadata, None-safe.
        gp["hud"].assets = assets
        # B1: the colour-capability map, published to the construct flow the
        # same host-sets-an-attribute way `assets` above and
        # `overlays.condition_art` are. B2 is what READS it (swatches in the
        # construct-confirm modal, then `place_building(..., column=...)`), so
        # on this branch it is deliberately published and not yet consumed.
        gp["panel"].colour_columns = colour_columns
        gp["floaters"].log = gp["game_log"]
        # -- /10J --
        # -- ESV-5/6: the handles _play/_anchored need to spawn a sprite
        # one-shot and resolve a manifest anchor. A fresh FloaterManager and
        # a fresh scene are built together right here every run, so these
        # attributes cannot desync; `cs` is a single run-long instance built
        # at module scope above, so it never desyncs either.
        gp["floaters"].assets = assets
        gp["floaters"].scene = gp["world"].scene
        gp["floaters"].cs = cs
        # -- /ESV-5/6 --
        gp["prev_phase"] = gp["world"].session.state.phase
        # BU-3 3.4 (#8 thorns): the standard BU-3 hook pair, spelled off the
        # fresh run's Session exactly like every other hook site — but
        # installed through a module-level seam, because its ONE hook site
        # (`EnemyCombat.update`) is called by `Scene.update`'s generic
        # component sweep, whose signature is `dt` alone. Same reason and same
        # shape as `set_damage_hook`/`set_wall_damage_hook` beside it; see
        # `game/enemies/components.py::set_boss_upgrade_pair`. Re-installed per
        # run so it always points at the CURRENT RunState.
        set_boss_upgrade_pair(gp["world"].session.state,
                              gp["world"].session.boss_upgrades_balance)
        frame_camera()  # re-centre on the startpoint / map for the fresh run
        freeze_static()  # exclude the fresh tile grid from GC scans
        shell.enter_gameplay()

    def teardown_gameplay():
        nonlocal recorder
        # debug-mode-telemetry: a run torn down mid-way (quit to menu, or the
        # game-over screen's MAIN MENU button) must still write its artifacts —
        # `close()` is idempotent, so a run that already closed at GAME_OVER
        # keeps that outcome. Dropping the reference is what lets the NEXT run
        # decide for itself whether it is instrumented.
        if recorder is not None:
            recorder.close(outcome="quit_to_menu")
            recorder = None
        # BU-3 3.4: drop the torn-down run's RunState out of the thorns seam,
        # so a quit-to-menu can never leave a dead run's ledger wired into the
        # next one (the `recorder = None` rule above, applied to the pair).
        set_boss_upgrade_pair()
        if tune_gc:
            gc.unfreeze()  # let the old world's tile grid become collectable
        for k in ("world", "hud", "panel", "floaters", "game_over", "levelup",
                  "boss_cutscene", "enemy_intro", "cheat", "overlays",
                  "game_log", "cutscene", "tutorial", "tutorial_message"):
            gp[k] = None
        gp["sel"], gp["sel_cat"] = [], None  # 10J
        gp["drag_select_enabled"] = False    # drag-select
        if tune_gc:
            gc.collect()

    def _new_recorder():
        """A fresh recorder from the shell's debug-log settings (level +
        which artifacts) — the ONE construction site the PLAY DEBUG button and
        the cheat-menu arm toggle share.

        player-identity: the identity comes off the shell too, and stamps the
        run id (hence all four artifact filenames) + the MD/HTML report
        headers. The level/outputs reads are unchanged — the Shell already
        seeds `DebugSettings` from the `Debug` balancing defaults, so those
        arrive through `shell.debug_settings` and must NOT be re-read here."""
        name, skill = shell.player_identity
        return DebugRecorder(REPO / "logs", level=shell.debug_settings.level,
                             outputs=shell.debug_settings.outputs,
                             player_name=name, player_skill=skill)

    def execute(intent):
        nonlocal running, recorder
        if intent == "new_game":
            build_gameplay()
        elif intent == "new_game_debug":
            # debug-mode-telemetry: PLAY DEBUG. `recorder` is a plain main()
            # local precisely so this can reassign it BEFORE build_gameplay()
            # binds it to the fresh run's RunState and Session.
            recorder = _new_recorder()
            build_gameplay()
        elif intent == "quit_to_menu":
            teardown_gameplay()  # shell already set state -> MAIN_MENU
        elif intent == "quit_app":
            running = False
        elif intent == "set_display_mode":
            # G4: through the presenter — the Surface path re-creates the
            # SCALED window exactly as before, the GPU path moves its own
            # standalone window (set_fullscreen/set_windowed/borderless).
            presenter.set_display_mode(shell.settings.display_mode)
        elif intent == "add_name_commit":
            name = shell.pending_name
            added = append_random_name(data_dir, name)
            if added:
                buildings_balance["BuildingsGlobal"]["random_names"].append(
                    name.strip())
                shell.set_pool_count(
                    len(buildings_balance["BuildingsGlobal"]["random_names"]))
            shell.report_add_name(added, name)
        elif intent == "open_highscores":
            # player-identity: RE-READ from disk — the run that just finished
            # appended its row after this document was last loaded, and the
            # identity prompt should offer the name it was recorded under.
            doc = highscores.load_highscores(scores_path, data_dir)
            shell.set_highscores(doc)
            shell.prefill_identity(*highscores.last_player(doc))

    # -- feature: rebindable hotkeys ----------------------------------------
    def _handle_capture_key(event):
        """The Controls screen is armed (``shell.controls_screen.capturing``
        names the action awaiting a keypress) — resolve THIS keydown as the
        new binding, through the SAME ``_binding_key_name`` hotkey dispatch
        uses, so a captured rebind and a dispatched hotkey can never
        disagree. Esc cancels with no change; a key already bound to another
        action flashes red and drops capture; a key with no representable
        binding (an arrow key, Tab, Shift, an F-key, ...) flashes red and
        drops capture too — bugfix: this used to silently do nothing, so a
        row a player tried to rebind with e.g. an arrow key (the most
        natural key to try for camera movement) looked permanently stuck on
        "PRESS A KEY" with zero feedback; otherwise the binding is written
        into the shared ``key_bindings`` dict (mutated in place, so the
        screen's next frame sees it for free) and persisted to
        ``scores/keybindings.json``."""
        screen = shell.controls_screen
        if event.key == pygame.K_ESCAPE:
            screen.stop_capture()
            return
        new_key = _binding_key_name(event)
        if new_key is None:
            screen.flash_unbindable()
            return
        action = screen.capturing
        if key_input.find_conflict(key_bindings, action, new_key) is not None:
            screen.flash_conflict()
            return
        updated = key_input.rebind(key_bindings, action, new_key)
        key_bindings.clear()
        key_bindings.update(updated)
        key_input.save_keybindings(keybindings_path, keybindings_schema_path,
                                   key_bindings)
        screen.stop_capture()
    # -- /feature: rebindable hotkeys ----------------------------------------

    # -- 10H: lightning + cheat menu --------------------------------------
    def _execute_cheat(action):
        """Map a cheat-menu action onto the Session cheat methods. The
        stays-open rule lives here: only close / trigger_levelup / a committed
        goto_round close the menu (prototype cheat_menu.py:49-56). After any
        phase-changing action that leaves LEVELUP, close the level-up window
        so no orphaned modal lingers — ``levelup_pending`` survives, so the
        window re-opens at the next ROUND_END (the prototype's pending-flag
        behavior).

        debug-mode-telemetry: ``toggle_debug`` arms/disarms the run's
        ``DebugRecorder`` in place (``Session.debug`` is a plain public
        attribute — arming mid-run is one assignment). Both directions record
        a ``cheat`` event, which also latches the round row's ``cheated`` flag
        for the rest of the run: a run captured from round N onward is NOT
        clean balance data, and saying so is the whole point."""
        nonlocal recorder
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
        elif action == "unlock_speed":
            session.cheat_unlock_speeds()
        elif action == "toggle_debug":
            if recorder is not None:
                # Mark the point capture STOPS, then write the artifacts.
                recorder.emit(dbg.CHEAT, action="debug_log_off",
                              round=session.state.round_num)
                recorder.close(outcome="debug_log_disarmed")
                recorder = None
                session.debug = None
            else:
                recorder = _new_recorder()
                recorder.bind(session.state)
                session.debug = recorder
                recorder.emit(
                    dbg.RUN_START, level=recorder.level,
                    run_id=recorder.run_id, map_id=map_doc.map_id, seed=None,
                    love=session.state.love, lives=session.state.base_lives,
                    # player-identity: off the RECORDER, not the shell (see
                    # build_gameplay's matching emit).
                    player_name=recorder.player_name,
                    player_skill=recorder.player_skill)
                # THE arm marker: everything before this round is missing.
                recorder.emit(dbg.CHEAT, action="debug_log_on",
                              round=session.state.round_num)
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

    def _tutorial_allows_panel_click(mx, my):
        """True when the tutorial is inactive/finished, OR the click lands on
        a target the current step allows (musician card / Confirm / the
        tile-buying topic's unlock button). Every other click inside the
        panel (close, cancel, the name box, the dice reroll) passes through
        UNGATED — only the actual whitelisted target is checked (TU-6 §3.3)."""
        tutorial = gp["tutorial"]
        if tutorial.finished:  # fast path, D6
            return True
        panel = gp["panel"]
        if panel.preview is not None:
            if panel.preview.confirm_btn.hit(mx, my):
                return tutorial.allows(("confirm",))
            return True  # cancel/close/name box/dice: not gated
        if panel.mode == "construct":
            for btype, btn in panel.cards:
                if btn.hit(mx, my):
                    return tutorial.allows(("card", btype))
            return True  # clicking the panel body/close, not a card
        if panel.mode == "unlock":
            if panel.action_btn.hit(mx, my):
                return tutorial.allows(("unlock",))
            return True  # clicking the panel body/close, not the action button
        return True  # upgrade/base_info modes: untouched by TU-6

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
        # -- TU-6: the tutorial message box consumes EVERY click while
        # visible (highest priority bar GAME_OVER) --
        tutorial = gp["tutorial"]
        if tutorial.message_visible:
            result = gp["tutorial_message"].hit(mx, my)
            if result == "skip":
                tutorial.skip()
                # TU-9: Skip jumps straight to round 1 — no round 0, no
                # forced single walker, normal wave scaling from here.
                if session.state.round_num == 0:
                    session.state.round_num = 1
            elif result == "continue":
                tutorial.on_message_dismissed()
            return
        # -- /TU-6 --
        # -- 10H: the open cheat menu consumes EVERY click (renders topmost,
        # directly under GAME_OVER in the ladder — above every other modal) --
        if gp["cheat"].visible:
            _execute_cheat(gp["cheat"].hit(mx, my))
            return
        # -- /10H --
        # -- 10G boss: the cutscene is fully modal — one of the 3 upgrade cards
        # (BU-4; `hit` returns the picked catalog id) or nothing (clicks
        # elsewhere swallowed; keys are already swallowed by the frozen gate).
        if session.state.phase == GamePhase.BOSS_CUTSCENE:
            choice = gp["boss_cutscene"].hit(mx, my)
            if choice is not None:
                gp["boss_cutscene"].close()
                session.resolve_boss_cutscene(choice, world.scene)
            return
        # -- /10G --
        # -- feature-enemy-intro-dialogue: a close-X hit closes early (its own
        # slide+fade-out, the SAME path the hold timer uses); any other click
        # is swallowed — the Levelup/Boss "modal swallows clicks" convention,
        # just with one working close affordance. --
        if session.state.phase == GamePhase.ENEMY_INTRO:
            if gp["enemy_intro"].hit(mx, my):
                gp["enemy_intro"].request_close()
            return
        # -- /feature-enemy-intro-dialogue --
        if session.frozen:                                 # LEVELUP: fully modal
            option = gp["levelup"].hit(mx, my)
            if option is not None:
                gp["levelup"].close()
                session.resolve_levelup(option, world.scene)  # -> payday -> INCOME
            return
        if panel.preview is not None:                      # modal
            # -- TU-6/TU-8: only the whitelisted CONFIRM click is gated;
            # closing the preview WITHOUT placing (X/CANCEL) fires
            # panel_closed so the tutorial can revert (Fix 1) --
            if _tutorial_allows_panel_click(mx, my) and panel.handle_click(
                    mx, my, session, buildings_balance, world.scene,
                    world.occupancy):
                if panel.last_placed_type is not None:
                    gp["tutorial"].on_building_placed(panel.last_placed_type)
                    panel.last_placed_type = None
                elif panel.preview is None:  # cancel/close, not a placement
                    gp["tutorial"].on_panel_closed()
            # -- /TU-6/TU-8 --
            return
        hud_action = gp["hud"].hit(mx, my)
        if hud_action == "pause":
            shell.state = GameState.PAUSED
            return
        if hud_action == "end_turn":
            session.end_turn()
            # fix/highlight-render-order: the heatmap always shows the round
            # currently in progress — blank it here so nothing lingers from
            # the round just ended; track()/the ENEMY-phase-edge snapshot
            # rebuild it live over the new round.
            gp["overlays"].path_heatmap.clear()
            gp["tutorial"].on_end_turn()  # TU-6: no-op unless this was the gated step
            return
        # -- 10L: fast-forward combat-speed buttons --
        if isinstance(hud_action, tuple) and hud_action[0] == "speed":
            session.set_combat_speed(hud_action[1])
            return
        # -- /10L speed --
        # -- drag-select: the ONE place the toggle flips. Hud.hit() stays a
        # pure read precisely because it is also called by the pan-arming
        # over_ui probe on MOUSEBUTTONDOWN. --
        if hud_action == "drag_select":
            gp["drag_select_enabled"] = not gp["drag_select_enabled"]
            return
        # -- /drag-select --
        # -- UL-10: the three reserved clickable-layer tokens. All three are
        # SWALLOW on the HUD: it is a persistent overlay, not a window, so it
        # has no "close" and no "back" of its own — the screens that DO own
        # those semantics (building_ui's close()/_back_to_upgrade) handle them
        # on their own hit path. Swallowing is the point: a clickable layer
        # must never fall through to the world underneath it. --
        if hud_action in ("noop", "close_window", "back"):
            return
        # -- /UL-10 --
        # -- 10I: RANGE/HEATMAP overlay toggles consume the click --
        if gp["overlays"].hit(mx, my):
            return
        # -- /10I --
        # -- TU-6/TU-8: only the whitelisted card click is gated; the panel's
        # own X button (bare panel, no preview) passes through ungated —
        # closing it here fires panel_closed for the same revert as above --
        was_visible = panel.visible
        if _tutorial_allows_panel_click(mx, my) and panel.handle_click(
                mx, my, session, buildings_balance, world.scene,
                world.occupancy):
            if panel.mode == "construct" and panel.preview is not None:
                gp["tutorial"].on_card_selected(panel.preview.building_type)
            elif panel.last_unlocked:
                gp["tutorial"].on_tile_unlocked()
                panel.last_unlocked = False
            elif was_visible and not panel.visible:
                gp["tutorial"].on_panel_closed()
            return
        # -- /TU-6/TU-8 --
        if panel.visible and mx >= panel.panel_x:          # spatial block
            return
        if session.state.phase == GamePhase.BUILDING:
            tile = tile_at_screen(world.tile_map, cs, mx, my)
            # -- Building Movement: while the panel is picking a destination,
            # a world click is that pick, never a selection change. A click on
            # anything but a highlighted tile is a silent no-op so the player
            # keeps picking (the panel is the cancel affordance). --
            if gp["panel"].mode == "move_select":
                _pick_move_destination(tile, session)
                return
            # -- /Building Movement --
            # -- TU-6: reject every tile but the one the guided chain allows --
            if tile is not None and not gp["tutorial"].allows(
                    ("tile", tile.col, tile.row)):
                return
            if tile is not None:
                gp["tutorial"].on_tile_clicked(tile.col, tile.row)
            # -- /TU-6 --
            # -- 10J: shift multi-select (prototype game.py:440-490) --
            shift = bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)
            update_selection(tile, shift, session)
            # -- /10J --
        # -- 10H: ENEMY-phase lightning click at the ladder BOTTOM (prototype
        # game.py:426-431 — a non-drag left-up no UI element consumed) --
        elif session.state.phase == GamePhase.ENEMY:
            wx, wy = cs.screen_to_world(mx, my)
            session.lightning_strike(world.scene, cs, wx, wy, vfx_balance)
        # -- /10H --

    def _pick_move_destination(tile, session):
        """Building Movement: the world half of destination-picking.

        A legal destination is an unbuilt BUILDABLE tile that is not already an
        endpoint of a move in progress — exactly the set
        ``BuildingUI._build_move_select`` highlighted. Anything else is a silent
        no-op (the player keeps picking). On a legal pick this only OPENS the
        confirmation modal; ``start_move`` (via ``BuildingUI._do_move``) stays
        the single legal seam that actually moves anything."""
        panel = gp["panel"]
        building = panel._selected
        if (tile is None or building is None
                or tile.state != TileState.BUILDABLE
                or session.tilemap.is_moving(tile.col, tile.row)):
            return
        movement = buildings_balance["BuildingsGlobal"]["Movement"]
        distance = move_distance(building.col, building.row,
                                 tile.col, tile.row)
        panel.preview = MovePreview(
            building, tile, move_cost(distance, movement),
            # BU-3 #4 move_time_cap: the standard optional trailing pair, off
            # the Session — `_do_move` passes the same one into `start_move`,
            # so the quoted round count and the charged one agree.
            move_time(distance, movement, session.state,
                      session.boss_upgrades_balance),
            movement["warning_text"],
            ui_balance, view_w, view_h, skinning=shell.skinning)

    def handle_world_right_click(mx, my):
        """Right-click is a universal DISMISS, never a world action — it peels
        one stage off whatever is open, wherever the cursor is. A right-DRAG
        still pans; the _DRAG_THRESHOLD_SQ gate in the event loop is what keeps
        the two apart. Mirrors handle_world_click's precedence so the two
        ladders cannot drift.

        ONE exception, and only while the DRAG SEL toggle is on: right-clicking
        a tile that is CURRENTLY in the multi-selection peels that single tile
        out of it instead of dismissing. Anything else — the toggle off, a tile
        that isn't selected, an open construct preview — falls through to the
        universal dismiss unchanged."""
        session = gp["world"].session
        panel = gp["panel"]
        if session.state.state == GameState.GAME_OVER:
            return
        if gp["cheat"].visible:
            gp["cheat"].close()
            return
        # -- feature-enemy-intro-dialogue: right-click-anywhere is a manual
        # close (unlike LEVELUP/BOSS_CUTSCENE below, which are choice-only
        # and treat it as a no-op) --
        if session.state.phase == GamePhase.ENEMY_INTRO:
            gp["enemy_intro"].request_close()
            return
        # -- /feature-enemy-intro-dialogue --
        if session.frozen or session.state.phase == GamePhase.BOSS_CUTSCENE:
            return  # LEVELUP / boss cutscene: a choice, not a dismiss
        # -- drag-select: single-tile deselect. Gated on `panel.preview is
        # None` so a right-click over an open construct preview still peels
        # the preview (Shift+Click never reaches the world there either —
        # handle_world_click's preview branch swallows it first). --
        if gp["drag_select_enabled"] and panel.preview is None:
            tile = tile_at_screen(gp["world"].tile_map, cs, mx, my)
            if tile is not None and tile in gp["sel"]:
                gp["sel"].remove(tile)
                if not gp["sel"]:
                    gp["sel_cat"] = None
                    panel.close()
                else:
                    panel.open_for_tile(gp["sel"][0], session,
                                        buildings_balance,
                                        selected_tiles=gp["sel"])
                return
        # -- /drag-select --
        # -- TU-8: dismiss() never places, so a preview it peels or a bare
        # panel it closes both fire panel_closed (Fix 1); peeling only the
        # boss popup (panel stays visible, preview stays None) does not --
        had_preview = panel.preview is not None
        was_visible = panel.visible
        panel.dismiss()
        if (had_preview and panel.preview is None) or (
                was_visible and not panel.visible):
            gp["tutorial"].on_panel_closed()
        if not panel.visible:
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

    # -- drag-select: one press-drag-release == the batch Shift+Click builds
    # one click at a time. Same _SEL_CATEGORY table, same same-category-only
    # filter, same "primary tile first" convention open_for_tile documents;
    # locked/unowned tiles inside the rectangle carry no category and are
    # silently skipped, mirroring today's "a click can't hit them" rule. --
    def finish_drag_select(start_tile, end_tile):
        world = gp["world"]
        session = world.session
        panel = gp["panel"]
        tutorial = gp["tutorial"]
        cat = _SEL_CATEGORY.get(start_tile.state) if start_tile is not None else None
        # The same D6 zero-overhead tutorial gate every other tile click goes
        # through: outside the guided chain it fast-paths to "always allowed",
        # and during it a drag collapses to at most the one highlighted tile
        # rather than bypassing the whitelist.
        if cat is None or not tutorial.allows(
                ("tile", start_tile.col, start_tile.row)):
            gp["sel"], gp["sel_cat"] = [], None
            panel.close()
            return
        end_tile = end_tile if end_tile is not None else start_tile
        c0, c1 = sorted((start_tile.col, end_tile.col))
        r0, r1 = sorted((start_tile.row, end_tile.row))
        picked = [start_tile]
        for row in range(r0, r1 + 1):
            for col in range(c0, c1 + 1):
                t = world.tile_map.get(col, row)
                if (t is not None and t is not start_tile
                        and _SEL_CATEGORY.get(t.state) == cat
                        and tutorial.allows(("tile", t.col, t.row))):
                    picked.append(t)
        gp["sel"], gp["sel_cat"] = picked, cat
        tutorial.on_tile_clicked(start_tile.col, start_tile.row)
        panel.open_for_tile(picked[0], session, buildings_balance,
                            selected_tiles=picked)
    # -- /drag-select --

    if autostart:
        build_gameplay()  # headless seam: bypass cutscene/menu -> GAMEPLAY

    frames = 0
    fps_log_ms = 0
    # Per-section frame-time accumulators in SECONDS (windowed runs only — the
    # print is gated on tune_gc). sim = update; submit = the fill + RenderItem
    # generation; world = the world/overlay backend call inside renderer.flush;
    # hud = the HUD backend call (always the Surface blitter, 0.0 when the HUD
    # rides the same single call on the Surface path); composite = the HUD
    # texture upload + draw (GPU only); present = display.flip / SDL present.
    # G4 split `flush` into world/hud/composite — that is what answers G0's one
    # INFERRED claim (that the HUD is not the dominant cost) with a number.
    perf = {"sim": 0.0, "submit": 0.0, "world": 0.0, "hud": 0.0,
            "composite": 0.0, "present": 0.0}
    perf_frames = 0
    flush_acc = {"world": 0.0, "hud": 0.0}   # seconds, reset each frame

    def flush_frame():
        """THE frame's flush seam: one call shape for all four sites, so the
        world/HUD split and its timing can never be wired at three of them and
        forgotten at the fourth."""
        n = renderer.flush(presenter.world_target,
                           hud_target=presenter.hud_target)
        split = renderer.last_flush_ms
        flush_acc["world"] += split["world"] / 1000.0
        flush_acc["hud"] += split["hud"] / 1000.0
        return n
    mouse_down = None
    rmouse_down = None  # right-press origin: a short press dismisses, a drag pans
    pan_from = None  # set on a left-press that began over the world (not UI)
    # drag-select: the armed box selection's two corners, held as Tiles (not
    # screen coords) so the live preview survives a camera nudge. Mutually
    # exclusive with `pan_from` — arming one clears the other.
    drag_select_from = None
    drag_select_current = None
    deco_clock_ms = 0.0  # wall-clock accumulator for deco idle animation
    # cutscene skip-prompt idle fade: seconds the mouse has sat still
    mouse_idle_t = 0.0
    last_mouse_pos = None
    running = True
    while running:
        dt = clock.tick(display["fps"]) / 1000.0
        deco_clock_ms += dt * 1000.0  # wall-clock: deco keeps animating while paused
        _t_frame = time.perf_counter()
        _t_flush_start = _t_frame  # each render branch resets this before flush
        flush_acc["world"] = flush_acc["hud"] = 0.0
        capture_path = None

        # 1. input (E-14) — routed per top-level shell state
        for event in pygame.event.get():
            # G4 §2.6: the ONE input-mapping seam. Identity on the Surface
            # path; on the GPU path it rewrites a mouse event's pos/rel from
            # window pixels into the logical 640x360 space every handler below
            # already assumes.
            event = presenter.map_event(event)
            if event.type == pygame.QUIT:
                running = False
                continue
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F12:
                # G4 §2.7: capture the live frame (after the HUD composite,
                # before present — end_frame owns that ordering).
                capture_path = _capture_path(presenter.name)
                continue
            st = shell.state
            if st == GameState.CUTSCENE:
                # skip is now a 2s hold (left click/space/esc), polled
                # continuously below — this branch only swallows input.
                continue
            if shell.in_menu or st == GameState.PAUSED:
                if event.type == pygame.KEYDOWN:
                    # feature: rebindable hotkeys — while the Controls screen
                    # is waiting for a keypress, THIS key is the rebind
                    # capture, not a menu navigation key.
                    if (shell.state == GameState.SETTINGS and shell.controls_open
                            and shell.controls_screen.capturing is not None):
                        _handle_capture_key(event)
                    else:
                        execute(shell.handle_key(event.unicode, _key_name(event.key)))
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == _LEFT:
                    execute(shell.handle_click(*event.pos))
                elif event.type == pygame.MOUSEWHEEL and event.y:
                    # player-identity: the high-score table is the only menu
                    # screen that scrolls (Shell.handle_scroll duck-types on a
                    # callable `scroll`; every other screen is a no-op). NEGATED
                    # — pygame's MOUSEWHEEL.y is positive scrolling UP, while
                    # HighscoresScreen.scroll(+dy) moves DOWN the list.
                    shell.handle_scroll(-event.y)
                continue
            # -- TU-5: an in-gameplay cutscene overlay consumes ALL input
            # while active (mirrors the CUTSCENE branch above) --
            if gp["cutscene"] is not None:
                # skip is now a 2s hold (left click/space/esc), polled
                # continuously below — this branch only swallows input.
                continue
            # TU-6: the guided-chain whitelist lives at the existing choke
            # points instead (message-box click-swallow in
            # handle_world_click, the tile-click/panel.handle_click() gates
            # below, and Session.tutorial_gate for End Turn) — no separate
            # keyboard-wide gate needed here.
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
                    if _binding_key_name(event) == key_bindings["toggle_cheat_menu"]:
                        gp["cheat"].toggle()
                        continue
                    if gp["cheat"].visible:
                        _execute_cheat(gp["cheat"].handle_key(
                            event.unicode, _key_name(event.key)))
                        continue
                # -- /10H --
                # -- feature-enemy-intro-dialogue: Esc closes early — BEFORE
                # the frozen guard (the cheat-menu carve-out above), since
                # unlike LEVELUP/BOSS_CUTSCENE this modal DOES have a
                # dismiss. --
                if (session.state.state == GameState.GAMEPLAY
                        and session.state.phase == GamePhase.ENEMY_INTRO
                        and event.key == pygame.K_ESCAPE):
                    gp["enemy_intro"].request_close()
                    continue
                # -- /feature-enemy-intro-dialogue --
                if session.state.state != GameState.GAMEPLAY or session.frozen:
                    continue  # the LEVELUP window owns all input
                if panel.preview is not None:
                    if event.key == pygame.K_ESCAPE and not panel.preview.editing:
                        panel.preview = None
                        gp["tutorial"].on_panel_closed()  # TU-8 Fix 1
                    elif (not panel.preview.editing and _binding_key_name(event)
                          == key_bindings["confirm_purchase"]):
                        # feature: rebindable hotkeys — Enter confirms the
                        # open preview exactly like clicking CONFIRM: the
                        # SAME public entry point (and TU-6/TU-8 gate) a real
                        # mouse click on that button goes through, aimed at
                        # the button's own centre point.
                        cbx, cby, cbw, cbh = panel.preview.confirm_btn.rect
                        px, py = cbx + cbw // 2, cby + cbh // 2
                        if (_tutorial_allows_panel_click(px, py)
                                and panel.handle_click(
                                    px, py, session, buildings_balance,
                                    world.scene, world.occupancy)):
                            if panel.last_placed_type is not None:
                                gp["tutorial"].on_building_placed(
                                    panel.last_placed_type)
                                panel.last_placed_type = None
                            elif panel.preview is None:  # cancel/close
                                gp["tutorial"].on_panel_closed()
                    else:
                        panel.handle_key(event.unicode, _key_name(event.key))
                elif panel.name_editing:  # 10J: upgrade-panel rename capture
                    panel.handle_key(event.unicode, _key_name(event.key))
                elif (panel.mode == "upgrade" and _binding_key_name(event)
                      == key_bindings["confirm_purchase"]):
                    # feature: rebindable hotkeys (Enter also upgrades) — the
                    # SAME confirm_purchase binding that confirms an open
                    # construct/move preview above now ALSO fires the
                    # upgrade panel's UPGRADE/ADVANCE button when no preview
                    # is open, through the identical "click at that button's
                    # own centre" seam a real mouse click goes through. This
                    # covers single AND multi-select batch upgrade/advance
                    # for free — `_upgrade_click`'s action_btn branch already
                    # handles both (game/ui/CLAUDE.md's Stage A/Stage B batch
                    # flow), so keyboard and mouse can never disagree here
                    # either.
                    abx, aby, abw, abh = panel.action_btn.rect
                    px, py = abx + abw // 2, aby + abh // 2
                    if _tutorial_allows_panel_click(px, py):
                        panel.handle_click(px, py, session, buildings_balance,
                                           world.scene, world.occupancy)
                elif event.key == pygame.K_ESCAPE:
                    if panel.visible:
                        panel.close()
                        gp["tutorial"].on_panel_closed()  # TU-8 Fix 1
                    else:
                        shell.state = GameState.PAUSED  # Esc opens pause
                elif _binding_key_name(event) == key_bindings["end_turn"]:
                    session.end_turn()  # dev convenience beside the button
                    gp["overlays"].path_heatmap.clear()  # fix/highlight-render-order
                    gp["tutorial"].on_end_turn()  # TU-6: no-op unless gated step
                elif _binding_key_name(event) == key_bindings["toggle_heatmap"]:
                    # feature: rebindable hotkeys — the same flip
                    # MapOverlays.hit() does for the HEATMAP pill's own click.
                    gp["overlays"].show_heatmap = not gp["overlays"].show_heatmap
                elif _binding_key_name(event) == key_bindings["toggle_tier_overview"]:
                    # feature: rebindable hotkeys — the same flip
                    # MapOverlays.hit() does for the TIERS pill's own click.
                    gp["overlays"].show_tier_overview = (
                        not gp["overlays"].show_tier_overview)
                elif _binding_key_name(event) == key_bindings["toggle_range"]:
                    # feature: rebindable hotkeys — the same flip
                    # MapOverlays.hit() does for the RANGE pill's own click.
                    gp["overlays"].show_range = not gp["overlays"].show_range
                elif _binding_key_name(event) == key_bindings["toggle_drag_select"]:
                    # feature: rebindable hotkeys — the same flip
                    # handle_world_click's "drag_select" HUD action does for
                    # the DRAG SEL button's own click.
                    gp["drag_select_enabled"] = not gp["drag_select_enabled"]
                elif _binding_key_name(event) == key_bindings["zoom_level_1"]:
                    set_zoom_level(cs, 0, view_w, view_h)
                elif _binding_key_name(event) == key_bindings["zoom_level_2"]:
                    set_zoom_level(cs, 1, view_w, view_h)
                elif _binding_key_name(event) == key_bindings["zoom_level_3"]:
                    set_zoom_level(cs, 2, view_w, view_h)
                elif session.state.phase == GamePhase.ENEMY:
                    # Combat-speed shortcuts + quick-skip (10F). 1.5x/2x are
                    # round-gated inside Session, so a locked key is a no-op.
                    # The 1x/1.5x/2x/pause BUTTONS are 10L. Numpad 1/2/3 stay
                    # a fixed always-on alias, outside the rebindable set —
                    # rebinding only ever changes the primary key.
                    key_name = _binding_key_name(event)
                    if (event.key == pygame.K_KP1
                            or key_name == key_bindings["combat_speed_1"]):
                        session.set_combat_speed(0)
                    elif (event.key == pygame.K_KP2
                          or key_name == key_bindings["combat_speed_2"]):
                        session.set_combat_speed(1)   # 1.5x
                    elif (event.key == pygame.K_KP3
                          or key_name == key_bindings["combat_speed_3"]):
                        session.set_combat_speed(2)   # 2x
                    elif key_name == key_bindings["quick_skip_combat"]:
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
                # -- drag-select: `pan_from is not None` IS the "this press
                # began over the world, not a UI element" signal (the new
                # toggle button is part of Hud.hit(), so over_ui already
                # covers it). When the toggle is on in the BUILDING phase the
                # gesture belongs to box-select and never to camera pan. --
                if (gp["drag_select_enabled"] and pan_from is not None
                        and session.state.phase == GamePhase.BUILDING):
                    drag_select_from = tile_at_screen(world.tile_map, cs,
                                                      *event.pos)
                    drag_select_current = drag_select_from
                    pan_from = None
                else:
                    drag_select_from = None
                    drag_select_current = None
                # -- /drag-select --
            elif event.type == pygame.MOUSEBUTTONUP and event.button == _LEFT:
                if mouse_down is not None:
                    dx = event.pos[0] - mouse_down[0]
                    dy = event.pos[1] - mouse_down[1]
                    if dx * dx + dy * dy <= _DRAG_THRESHOLD_SQ:
                        handle_world_click(*event.pos)
                    elif drag_select_from is not None:
                        # drag-select: a real drag past the threshold — the
                        # short-press path above is untouched, so a plain
                        # click still selects one tile the ordinary way.
                        finish_drag_select(
                            drag_select_from,
                            tile_at_screen(world.tile_map, cs, *event.pos))
                mouse_down = None
                pan_from = None
                drag_select_from = None
                drag_select_current = None
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
            # -- drag-select: the live preview's far corner. A sibling of the
            # camera-pan arm above and mutually exclusive with it — `pan_from`
            # is None whenever `drag_select_from` is armed. --
            elif (event.type == pygame.MOUSEMOTION and event.buttons[0]
                  and drag_select_from is not None):
                drag_select_current = tile_at_screen(world.tile_map, cs,
                                                     *event.pos)
            # -- /drag-select --
            elif event.type == pygame.MOUSEWHEEL and event.y:
                if gp["cheat"].visible:  # 10H: open menu swallows wheel zoom
                    continue
                # The construct card list is taller than the panel once
                # several building types are unlocked, so the wheel scrolls it
                # while the cursor is over the panel — and still zooms the
                # camera everywhere else. NEGATED for the same reason the menu
                # wheel arm above is: pygame's MOUSEWHEEL.y is positive
                # scrolling UP, while handle_scroll(+dy) moves DOWN the list.
                if (panel.mode == "construct" and panel.preview is None
                        and widgets.contains(panel.panel_rect,
                                             *presenter.mouse_pos())):
                    panel.handle_scroll(-event.y)
                    continue
                step_zoom(cs, 1 if event.y > 0 else -1, view_w, view_h)

        mx, my = presenter.mouse_pos()
        # cutscene skip-prompt idle fade: reset on any movement, else accrue
        if (mx, my) != last_mouse_pos:
            mouse_idle_t = 0.0
            last_mouse_pos = (mx, my)
        else:
            mouse_idle_t += dt
        held = pygame.mouse.get_pressed()[0]   # 10L-A: skinned pressed state
        keys = pygame.key.get_pressed()
        # cutscene hold-to-skip: left click, space, or esc held continuously
        skip_held = held or keys[pygame.K_SPACE] or keys[pygame.K_ESCAPE]

        # feature: rebindable hotkeys — WASD/arrow-key camera panning, held
        # continuously (polled every frame via `keys`, the skip_held pattern
        # above, not a single KEYDOWN dispatch like every other hotkey).
        # Gated the same way mouse drag-panning already is: only while a
        # world state is live, never while the sim is frozen (LEVELUP/
        # BOSS_CUTSCENE/ENEMY_INTRO), the cheat menu is open, a construct/
        # move preview modal has focus (which also captures typed characters
        # — WASD must not leak into a name field), or the upgrade panel's
        # rename row is capturing keys. Arrow keys ALWAYS pan too, a fixed
        # always-on alias outside the rebindable set (the numpad precedent).
        world = gp["world"]
        if (world is not None and shell.state in _WORLD_STATES
                and not world.session.frozen and not gp["cheat"].visible
                and gp["panel"].preview is None
                and not gp["panel"].name_editing):
            pan_speed = core_balance["Camera"]["keyboard_pan_speed"]
            dx = dy = 0.0
            if _binding_held(key_bindings["move_left"], keys) or keys[pygame.K_LEFT]:
                dx -= pan_speed * dt
            if _binding_held(key_bindings["move_right"], keys) or keys[pygame.K_RIGHT]:
                dx += pan_speed * dt
            if _binding_held(key_bindings["move_up"], keys) or keys[pygame.K_UP]:
                dy -= pan_speed * dt
            if _binding_held(key_bindings["move_down"], keys) or keys[pygame.K_DOWN]:
                dy += pan_speed * dt
            if dx or dy:
                cs.pan(dx, dy)
                cs.clamp(view_w, view_h)

        # 2. simulate / update — per state
        _t_sim0 = time.perf_counter()
        st = shell.state
        if st == GameState.CUTSCENE:
            intro_player.update(dt)
            intro_player.update_skip_hold(dt, skip_held)
            if intro_player.done:
                intro_player.release()
                shell.to_main_menu()
        elif st in _WORLD_STATES:
            world = gp["world"]
            session = world.session
            # -- TU-5: consume a pending in-gameplay cutscene request, then
            # freeze the whole sim body below for as long as one is playing
            # (the wave IS queued by Session.end_turn() before this fires —
            # the freeze just withholds it visually until skip/done). --
            if gp["cutscene"] is None and session.state.pending_cutscene:
                requested = cutscenes.get(
                    session.state.pending_cutscene.get("id"))
                session.state.pending_cutscene = None
                if requested is not None and requested.enabled:
                    requested.start()
                    gp["cutscene"] = requested
                    mouse_idle_t = 0.0  # skip prompt starts fully visible
            if gp["cutscene"] is not None:
                gp["cutscene"].update(dt)
                gp["cutscene"].update_skip_hold(dt, skip_held)
                if gp["cutscene"].done:
                    gp["cutscene"].release()
                    gp["cutscene"] = None
            if gp["cutscene"] is None:
                # Combat speed (10F) scales the ENEMY-phase sim ONLY — spawner,
                # movement and the combat sweep together (prototype game.py:1211-13).
                # ROUND_END/INCOME timers always run on real time, and the pause is
                # just a 0.0 multiplier, so the round machine is never touched.
                # This also means build mode (BUILDING phase) always plays at
                # plain `dt` no matter which speed is selected — the speed
                # buttons are hidden there too (game/ui/hud.py) since they'd
                # have nothing to control.
                sim_dt = (dt * session.combat_speed
                          if session.state.phase == GamePhase.ENEMY else dt)
                session.pre_sim(sim_dt, world.scene)
                # debug-mode-telemetry: stamp the host's frame counter (a
                # cheap int set) once per frame, whenever a recorder is bound.
                if session.debug is not None:
                    session.debug.set_frame(frames)
                # LEVELUP/BOSS_CUTSCENE freeze the world entirely (no sim/anim).
                if session.state.state == GameState.GAMEPLAY and not session.frozen:
                    # debug-mode-telemetry (Phase 3): level-2-only per-tick
                    # damage detail. `_debug_on_damage` is threaded to
                    # resolve_combat's own on_damage= parameter for the three
                    # sites it owns; the enemy-attacks-a-building site
                    # (game/enemies/components.py) runs inside scene.update,
                    # BEFORE resolve_combat, so it needs the SAME callback
                    # installed through the module-level seam instead — hence
                    # set_damage_hook() bracketing scene.update() below.
                    # Everything below is inside `if debug_l2` so debug-off
                    # really does cost ONE attribute check here, as this
                    # package's docs claim — no closure built and no module
                    # global written on a frame that will never emit. The
                    # matching teardown is guarded the same way, which is safe
                    # because arming and clearing always happen on the SAME
                    # frame: a frame that never arms cannot leave a live hook.
                    debug_l2 = (session.debug is not None
                               and session.debug.level >= LEVEL_VERBOSE)
                    _debug_on_damage = None
                    if debug_l2:
                        def _debug_on_damage(attacker_kind, target_kind, dmg,
                                             target_hp_after,
                                             _rec=session.debug):
                            _rec.emit(dbg.DAMAGE, attacker=attacker_kind,
                                     target=target_kind, dmg=dmg,
                                     target_hp_after=target_hp_after)

                        def _debug_on_wall_damage(attacker_kind, edge, dmg,
                                                  hp_after, broke,
                                                  _rec=session.debug):
                            c1, r1, c2, r2 = edge
                            _rec.emit(dbg.WALL_DAMAGE, attacker=attacker_kind,
                                     col=c1, row=r1, col2=c2, row2=r2, dmg=dmg,
                                     hp_after=hp_after, broke=broke)

                        set_damage_hook(_debug_on_damage)
                        # A wall carries no Health and no RoundStats, so its
                        # damage is invisible to `on_damage` — its own seam.
                        set_wall_damage_hook(_debug_on_wall_damage)
                    # Tile-crowding visual offset (feature): undo last
                    # frame's offset BEFORE Movement runs (inside
                    # scene.update) so it steps from the clean path
                    # position, then re-apply the offset AFTER — see
                    # game/enemies/crowd_spacing.py's module docstring for
                    # why this can't be a single per-enemy Component.update().
                    restore_crowd_positions(world.scene)
                    world.scene.update(sim_dt)
                    apply_crowd_spacing(world.scene, sim_dt,
                                        enemies_balance["CrowdSpacing"])
                    # (BU-4/D6: the flat boss-bonus story damage that used to
                    # be computed here and threaded as `dmg_bonus` is retired
                    # with `boss_bonuses.py`. `resolve_combat`'s `dmg_bonus`
                    # parameter stays, defaulted to 0 — it is a generic
                    # whole-board additive seam, not a boss-bonus one.)

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

                    # ESV-5: drains into RunState.splash_impact_events; the UI
                    # side (spawn_splash_impact_events) reads it beside
                    # spawn_death_events below.
                    def _on_splash_impact(gx, gy, _state=session.state):
                        _state.splash_impact_events.append((gx, gy))

                    # ESV-6: the same drained-ledger pattern for the two
                    # convergence-demo triggers — both ship INERT rows, so these
                    # ledgers filling every frame is a no-op emit until a
                    # designer binds art.
                    def _on_defender_fire(wx, wy, _state=session.state,
                                          _rec=session.debug, _l2=debug_l2):
                        _state.defender_fire_events.append((wx, wy))
                        # debug-mode-telemetry (level 2): a shot left a muzzle.
                        # `resolve_combat`'s callback carries only the ALREADY
                        # muzzle-anchored spawn point — the shooter and its
                        # target are not in the signature and are NOT worth a
                        # gameplay-file signature change to reach, so the event
                        # reports exactly what it has (see events.py).
                        if _l2:
                            _rec.emit(dbg.DEFENDER_FIRE, wx=wx, wy=wy)

                    def _on_projectile_hit(wx, wy, _state=session.state):
                        _state.projectile_hit_events.append((wx, wy))

                    # Kidnapping (Art/enemies): the session bookkeeping (XP + kill
                    # count) runs first, then upgrade the default frozen-idle carry
                    # pose to the sheet's own `kidnap` row if it has one —
                    # `animation_total_ms` returns None (never an idle fallback)
                    # for a sheet without one, so this cleanly stays on the
                    # frozen-idle branch.
                    def _on_kidnap(enemy, building):
                        session.on_kidnap(enemy, building)
                        anim = enemy.get_component(SpriteAnimator)
                        if anim is not None:
                            set_kidnap_pose(
                                enemy,
                                bool(assets.animation_total_ms(
                                    anim.slot_key, KIDNAP_ANIM)))

                    resolve_combat(world.scene, world.tile_map, sim_dt,
                                   buildings_balance, vfx_balance,
                                   on_base_hit=session.on_base_hit,
                                   on_enemy_death=_on_enemy_death,
                                   assets=assets, cs=cs,
                                   on_splash_impact=_on_splash_impact,
                                   on_defender_fire=_on_defender_fire,
                                   on_projectile_hit=_on_projectile_hit,
                                   on_kidnap=_on_kidnap,
                                   on_damage=_debug_on_damage,
                                   # BU-3: the standard hook pair, spelled off
                                   # the Session (#3 mortar_slow).
                                   run_state=session.state,
                                   boss_upgrades_balance=(
                                       session.boss_upgrades_balance))
                    if debug_l2:  # armed this frame -> cleared this frame
                        set_damage_hook(None)
                        set_wall_damage_hook(None)
                    session.post_sim(world.scene)
                # payday fills state.income_events + flips to INCOME; queue
                # the payout beat sequence once (boost -> economy(+painter)
                # -> upkeep — game/ui/effects.py FloaterManager.begin_payout).
                if (session.state.phase == GamePhase.INCOME
                        and gp["prev_phase"] != GamePhase.INCOME):
                    gp["floaters"].begin_payout(session.state)
                    # -- N1: the season clock ---------------------------------
                    # payday already ran (it does round++ then flips to INCOME,
                    # game/core/payday.py:277-280), so THIS edge is the round
                    # edge: one frame per round, never per frame. The key is
                    # schema-REQUIRED, so index it — a missing group must fail
                    # loud here, not ship a whole run of wrong ground art.
                    # The invalidate is conditional ON PURPOSE: repainting the
                    # cached ground layer costs a full re-blit, so it fires only
                    # when the season actually turns (once every
                    # rounds_per_season rounds), not on every round edge.
                    if session.state.update_season(
                            core_balance["Seasons"]["rounds_per_season"]):
                        ground_cache.invalidate()
                    # -- /N1 --
                    # VA-4: same edge, same drained-by-UI contract — payday's
                    # revive slot filled it a few steps earlier in the very
                    # transition this branch is reacting to.
                    gp["floaters"].spawn_building_respawn_events(session.state)
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
                                             pending.get("outcome", "win"),
                                             pending.get("love_reward", 0))
                # -- /10G --
                # -- feature-enemy-intro-dialogue: open the first queued entry
                # on ITS phase edge (same pattern). Subsequent queued entries
                # are opened later, in the update block below, once the
                # previous one finishes closing. --
                if (session.state.phase == GamePhase.ENEMY_INTRO
                        and gp["prev_phase"] != GamePhase.ENEMY_INTRO):
                    gp["panel"].close()  # the modal owns the screen
                    gp["enemy_intro"].open(session.state.pending_enemy_intros[0])
                # -- /feature-enemy-intro-dialogue --
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
                    # debug-mode-telemetry: write the reports as soon as THIS
                    # run ends, not just at process exit. close() is
                    # idempotent, so the unconditional call right before
                    # pygame.quit() below stays a harmless no-op afterward.
                    if session.debug is not None:
                        session.debug.close(outcome="game_over")
                    # player-identity: record ONE high-score row per run. This
                    # is INDEPENDENT of the recorder — a regular (uninstrumented)
                    # run still records a row, with `make_entry` normalising the
                    # (None, None) identity to Anonymous / unknown. The latch is
                    # set BEFORE the write so a raising append cannot retry every
                    # frame; a read-only disk or a full volume must never crash a
                    # finished run on the game-over screen, so losing the row is
                    # the correct trade (ONE logged warning).
                    if not score_recorded:
                        score_recorded = True
                        try:
                            name, skill = shell.player_identity
                            highscores.append_score(scores_path, highscores.make_entry(
                                name, skill, session.state.round_num,
                                session.state.buildings_placed,
                                session.state.enemies_killed,
                                run_id=recorder.run_id if recorder is not None else None,
                                debug=recorder is not None), data_dir)
                        except Exception as exc:              # noqa: BLE001
                            _log.warning(
                                "could not record the high score for this run "
                                "(%s) — the run itself is unaffected", exc)
                gp["hud"].update(dt, mx, my, session, gp["panel"], mouse_down=held)
                gp["panel"].hover(mx, my, mouse_down=held)
                gp["panel"].update(dt)
                gp["overlays"].update(dt, mx, my, mouse_down=held)   # 10I: toggle-pill hover
                gp["floaters"].update(dt, session.state)
                # -- 10J: game log + FX watchers (building deaths -> purple burst
                # + kill message; enemy attack cadence -> muzzle/slash; enemy
                # deaths -> blood splatters, double-gated on gore) --
                gp["floaters"].watch_buildings(world.scene, gp["game_log"])
                gp["floaters"].watch_enemies(world.scene)
                gp["floaters"].spawn_death_events(session.state,
                                                  shell.settings.gore)
                gp["floaters"].spawn_splash_impact_events(session.state)  # ESV-5
                gp["floaters"].spawn_defender_fire_events(session.state)  # ESV-6
                gp["floaters"].spawn_projectile_hit_events(session.state)  # ESV-6
                gp["game_log"].drain(session.state)
                gp["game_log"].update(dt)
                # -- /10J --
                gp["cheat"].update(dt, mx, my, mouse_down=held)  # 10H (animates its own buttons)
                gp["tutorial_message"].update(dt, mx, my, mouse_down=held)  # TU-6
                if session.frozen:
                    gp["levelup"].update(dt, mx, my, mouse_down=held)
                    gp["boss_cutscene"].update(dt, mx, my, mouse_down=held)  # 10G (its phase only)
                    # feature-enemy-intro-dialogue: the window drives its own
                    # open/hold/close clock; once its close animation ends
                    # (timer or a manual close) pop the shown entry and open
                    # the next queued one, or let resolve_enemy_intro() start
                    # the round (it flips the phase to ENEMY once the queue
                    # drains).
                    gp["enemy_intro"].update(dt, mx, my, mouse_down=held)
                    if (session.state.phase == GamePhase.ENEMY_INTRO
                            and not gp["enemy_intro"].visible):
                        session.resolve_enemy_intro()
                        if session.state.phase == GamePhase.ENEMY_INTRO:
                            gp["enemy_intro"].open(
                                session.state.pending_enemy_intros[0])
                if session.state.state == GameState.GAME_OVER:
                    gp["game_over"].update(dt, mx, my, mouse_down=held)
        else:  # menu states + PAUSED
            shell.update(dt, mx, my, mouse_down=held)

        # 3. render submit — per state
        _t_render0 = time.perf_counter()
        presenter.begin_frame()
        st = shell.state
        if st == GameState.CUTSCENE:
            surf = intro_player.frame_surface()
            if surf is not None:
                presenter.blit_fullscreen(surf)
            _submit_cutscene_skip(renderer, view_w, view_h,
                                  intro_player.skip_progress, mouse_idle_t)
            _t_flush_start = time.perf_counter()
            flush_frame()
        elif st in _WORLD_STATES or st == GameState.PAUSED:
            world = gp["world"]
            session = world.session
            # -- 10G boss: screen shake — a transient render-only camera-pan
            # jitter while a live boss walks the ENEMY phase (prototype
            # game.py:1879-1890). Undone right after flush, with NO clamp in
            # between, so the offset restores exactly; sim state untouched.
            shake_ox = shake_oy = 0
            shake = None
            if session.state.phase == GamePhase.ENEMY:
                # BR-1: shake is a PER-ERA boss variable, so it comes off the
                # live boss object (which knows its own era) — never
                # re-derived from the round number.
                for b in world.scene.by_tag("boss"):
                    if getattr(b, "alive", False):
                        shake = getattr(b, "shake", None)
                        break
            if shake:
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
                    code_overrides=world.tile_map.terrain_overrides,
                    # Read INSIDE the lambda body, never bound as a default
                    # argument: the cache calls this back only on a rebuild,
                    # so the season must be sampled when the repaint happens.
                    column=session.state.season))
            # The GPU cache IGNORES this argument by design (it always draws
            # through the SDL Renderer it was built with — see
            # ground_cache_gpu.blit's docstring), so both classes take the same
            # call and the host needs no branch here. Do not "fix" it away.
            ground_cache.blit(presenter.world_target)
            # Base + deco stay dynamic (their own layers, above ground); windowed.
            cmin, cmax, rmin, rmax = cs.visible_tile_window(view_w, view_h, margin=4)
            for item in tilemap.visible_render_items(
                    map_doc, cmin, cmax, rmin, rmax, terrain=False,
                    camera=show_camera_start, anim_time_ms=int(deco_clock_ms),
                    column=session.state.season):
                renderer.submit(item)
            # Spawn-band tree deco on the `deco` layer — draws ABOVE enemies
            # (`entities`), so units emerging from the treeline are partly
            # occluded by it; submission order within a layer doesn't matter,
            # the renderer depth-sorts. Reuses the window above; vanishes on
            # its own the frame a SPAWNING tile converts to COMBAT (the
            # emitter reads `tile.state` live).
            for item in spawn_deco_render_items(
                    world.tile_map, cmin, cmax, rmin, rmax, tree_slots,
                    anim_time_ms=int(deco_clock_ms),
                    column=session.state.season):
                renderer.submit(item)
            # Condition art on the `terrain` layer — above the ground tiles,
            # below everything on `entities`/`deco`. Reuses the window above;
            # emits nothing for conditions with no imported sheet.
            for item in condition_render_items(
                    world.tile_map, cmin, cmax, rmin, rmax, condition_art,
                    anim_time_ms=int(deco_clock_ms),
                    column=session.state.season):
                renderer.submit(item)
            # Edge-wall art (fix/depth-sorted-world-fills) — every wall item
            # is on the SAME `entities` layer as buildings now, so it sorts
            # by real tile position against ANY building on the map (the
            # ordinary iso depth rule, not a fixed layer). The ONE thing
            # position can't resolve is a wall and a building on the SAME
            # tile (an exact depth-sort tie) — that's decided by SUBMISSION
            # ORDER instead: the two far sides (edge_nw/edge_ne) submit HERE,
            # before world.scene.render_items(), so a same-tile building
            # draws on top of its own back wall; the two near sides
            # (edge_se/edge_sw, `wall_render.FRONT_SIDES`, imported as
            # `FRONT_SIDES`) submit AFTER it,
            # below, so a same-tile building draws BEHIND its own near wall
            # (a fence in front of a house). See `game/map/wall_render.py`'s
            # module docstring. Nothing at all for a wall tier with no
            # imported sheet.
            wall_items = wall_render_items(world.tile_map, cmin, cmax, rmin, rmax,
                                           wall_art, anim_time_ms=int(deco_clock_ms))
            front_wall_items = []
            for item in wall_items:
                if item.animation in FRONT_SIDES:
                    front_wall_items.append(item)
                else:
                    renderer.submit(item)
            # -- fix/depth-sorted-world-fills (supersedes fix/highlight-render-
            # order): every colored tile highlight/overlay (condition tint,
            # RANGE, HEATMAP, TIER OVERVIEW, the tutorial guided-chain
            # highlight, the drag-select live rectangle, and the panel's
            # click/drag-select selection highlights) goes through
            # `widgets.submit_tile_diamond`/`_fill`, which now submits a
            # WorldFill — a REAL depth-sorted item, not the always-last
            # overlay pass. Submitting these BEFORE world.scene.render_items()
            # is what makes them draw BEHIND a same-tile building (a
            # submission-order tie-break, same mechanism as the walls above);
            # against a building on ANY OTHER tile they sort correctly by
            # real position regardless of submission order. See
            # `engine/render/CLAUDE.md`'s "Depth-sorted world fills". --
            gp["overlays"].submit(renderer, world.tile_map, world.scene,
                                  (cmin, cmax, rmin, rmax))
            # -- TU-6: the guided-chain tile highlight (0 or 1 tiles) — world
            # overlay, before buildings and before the panel's own selection
            # highlights. Pulses/glows (tile-buying-topic ask): alpha + border
            # width both breathe off the same deco_clock_ms wall clock. --
            tutorial_pulse_rgba, tutorial_pulse_width = \
                widgets.tutorial_pulse_style(deco_clock_ms)
            for col, row in gp["tutorial"].tile_highlight_targets():
                widgets.submit_highlight(
                    renderer, "tutorial_highlight", col, row, assets=assets,
                    pulse_color=tutorial_pulse_rgba,
                    pulse_width=tutorial_pulse_width)
            # -- /TU-6 --
            # -- drag-select: the live rectangle, same world-overlay slot as
            # the tutorial highlight. It runs the SAME _SEL_CATEGORY filter
            # AND the same tutorial.allows(("tile", ...)) gate finish_drag_select
            # does (review fix: a preview that skipped the gate could show a
            # tile during the round-0 tutorial that release would then refuse
            # to select), so a tile shown here is exactly a tile that will be
            # selected on release. --
            if gp["drag_select_enabled"] and drag_select_from is not None:
                cur = drag_select_current or drag_select_from
                sel_cat = _SEL_CATEGORY.get(drag_select_from.state)
                tutorial = gp["tutorial"]
                if sel_cat is not None and tutorial.allows(
                        ("tile", drag_select_from.col, drag_select_from.row)):
                    c0, c1 = sorted((drag_select_from.col, cur.col))
                    r0, r1 = sorted((drag_select_from.row, cur.row))
                    for row in range(r0, r1 + 1):
                        for col in range(c0, c1 + 1):
                            t = world.tile_map.get(col, row)
                            if (t is not None
                                    and _SEL_CATEGORY.get(t.state) == sel_cat
                                    and tutorial.allows(("tile", col, row))):
                                widgets.submit_tile_diamond_fill(
                                    renderer, col, row,
                                    widgets.highlight_color("tile_selected") + (70,))
            # -- /drag-select --
            gp["panel"].submit(renderer, session)
            # -- /fix/depth-sorted-world-fills --
            for item in world.scene.render_items():
                renderer.submit(item)
            # fix/depth-sorted-world-fills: the two near-side wall edges,
            # held back above so THEY draw on top of (in front of) a
            # same-tile building (see the comment at the wall_render_items()
            # call) — a fence along the near edge of a tile occludes
            # whatever's behind it.
            for item in front_wall_items:
                renderer.submit(item)
            # -- 10J: blood + gold-highlight fills (world overlay, before the
            # panel's selection highlights) --
            gp["floaters"].submit_splatters(renderer, cs)
            gp["floaters"].submit_gold_highlights(renderer)
            # -- /10J --
            gp["floaters"].submit_craters(renderer, cs, world.scene)  # 10B: world
            # Drummer buff-range telegraph ring — always visible while a
            # Drummer is alive, same world-overlay slot as the mortar crater.
            gp["floaters"].submit_drummer_auras(renderer, cs, world.scene)
            gp["floaters"].submit_lightning(renderer, cs, world.scene)  # 10H
            # feature-storm-acolyte-multi-build: per-acolyte charge bars
            gp["floaters"].submit_lightning_charge_bars(
                renderer, cs, world.scene)
            # -- Building Movement: the in-transit signpost + round countdown
            # on BOTH endpoints of every live move. `moving_orders` holds at
            # most a handful of entries, so this is a per-frame no-op in the
            # overwhelmingly common empty case. E-37: with no imported sheet
            # the sign is skipped and only the countdown draws — never a
            # grey X. --
            for order in world.tile_map.moving_orders:
                for ocol, orow in ((order.from_col, order.from_row),
                                   (order.to_col, order.to_row)):
                    scx, scy = cs.world_to_screen(ocol + 0.5, orow + 0.5)
                    sw = max(8, int(cs.geometry.tile_w * cs.camera.zoom * 0.7))
                    sh = sw * 3 // 2          # the 64x96 core frame ratio
                    # `tools/gen_moving_sign_sheet.py` draws the frame CENTRED
                    # on the tile diamond's centre (local (32, 48) of the
                    # 64x96 frame — the frame's own vertical MIDPOINT, not its
                    # bottom), so the frame's top-left is half a frame above
                    # the anchor point, not a whole frame above it.
                    if moving_sign_art:
                        renderer.submit_hud(HudSprite(
                            MOVING_SIGN_SLOT,
                            (int(scx - sw / 2), int(scy - sh / 2)), (sw, sh)))
                    # The board sits at local y 14-40 of the 96-tall frame,
                    # 21px above the local tile-centre row (48) — i.e. 21/96
                    # of `sh` above `scy` — so the countdown reads on the
                    # board face regardless of the sign's own art/zoom scale.
                    widgets.submit_text(
                        renderer, str(order.rounds_left),
                        (int(scx), int(scy - sh * 21 // 96)), "md",
                        widgets.highlight_color("move_target"), align="center")
            # -- /Building Movement --
            gp["floaters"].submit_beams(renderer, cs, world.scene)    # 10B: HUD
            gp["floaters"].submit_hp_bars(renderer, cs, world.scene)
            gp["floaters"].submit_enemy_hp_bars(renderer, cs, world.scene)
            # Golden arrow above any enemy whose move speed is BUFFED, red
            # arrow above any enemy that is SLOWED (BossUpgradeTimelinePLAN
            # D20 — the two signs of one aggregate, so at most one fires).
            gp["floaters"].submit_buff_arrows(renderer, cs, world.scene)
            gp["floaters"].submit_debuff_arrows(renderer, cs, world.scene)
            # Digger underground telegraph: entry-tile marker + heading arrow.
            gp["floaters"].submit_digger_telegraphs(renderer, cs, world.scene)
            gp["floaters"].submit(renderer, cs)
            gp["floaters"].submit_projectiles(renderer, cs, world.scene)  # 10J
            gp["floaters"].submit_fx(renderer, cs)  # 10J sparks/shards/slashes
            gp["floaters"].submit_boss_bars(renderer, cs, world.scene,  # 10G
                                            session.state.phase, view_w, view_h)
            gp["floaters"].submit_announce(renderer, view_w, view_h)    # 10G
            gp["hud"].submit(renderer, session, view_w, view_h,
                             hover_cost=gp["panel"].hover_cost,
                             love_display=gp["floaters"].love_display,
                             scene=world.scene,
                             drag_select_enabled=gp["drag_select_enabled"])
            # -- TU-6: UI-box highlights (card/Confirm/End Turn/Close/Unlock)
            # + the message box, over the HUD. Same pulse/glow as the world
            # tile highlight above, off the same deco_clock_ms wall clock. --
            ui_pulse_rgba, ui_pulse_width = \
                widgets.tutorial_pulse_style(deco_clock_ms)
            for rect in gp["tutorial"].ui_highlight_rects(gp["panel"], gp["hud"]):
                widgets.submit_ui_box_highlight(
                    renderer, rect, color=ui_pulse_rgba, width=ui_pulse_width)
            # -- TU-8: the non-modal close-panel-hint banner — NOT the
            # message box, so it never consumes the right-click it names --
            banner_text = gp["tutorial"].banner_text()
            if banner_text is not None:
                widgets.submit_tutorial_banner(renderer, banner_text,
                                               view_w, view_h)
            if gp["tutorial"].message_visible:
                gp["tutorial_message"].submit(
                    renderer, gp["tutorial"].message_text(), view_w, view_h)
            # -- /TU-6 --
            gp["game_log"].submit(renderer, view_h)   # 10J: fading log lines
            gp["overlays"].submit_buttons(renderer)   # 10I: RANGE/HEATMAP pills
            if gp["levelup"].visible:
                gp["levelup"].submit(renderer, view_w, view_h)
            # -- 10G boss: the cutscene modal draws over everything below --
            if session.state.phase == GamePhase.BOSS_CUTSCENE:
                gp["boss_cutscene"].submit(renderer, view_w, view_h)
            # -- /10G --
            if gp["enemy_intro"].visible:  # feature-enemy-intro-dialogue
                gp["enemy_intro"].submit(renderer, view_w, view_h)
            if session.state.state == GameState.GAME_OVER:
                gp["game_over"].submit(renderer, session.state, view_w, view_h)
            if st == GameState.PAUSED:
                shell.submit(renderer, view_w, view_h)  # overlay on frozen world
            # -- 10H: the cheat menu renders TOPMOST (prototype game.py:2061-62)
            if gp["cheat"].visible:
                gp["cheat"].submit(renderer, view_w, view_h)
            # -- /10H --
            _t_flush_start = time.perf_counter()
            flush_frame()
            # -- TU-5: an in-gameplay cutscene overlay paints AFTER the
            # (frozen, but still-submitted) world frame, full-screen --
            if gp["cutscene"] is not None:
                surf = gp["cutscene"].frame_surface()
                if surf is not None:
                    presenter.blit_fullscreen(surf)
                _submit_cutscene_skip(renderer, view_w, view_h,
                                      gp["cutscene"].skip_progress,
                                      mouse_idle_t)
                flush_frame()
            # -- 10G boss: undo the shake pan exactly (no clamp in between) --
            if shake_ox or shake_oy:
                cs.pan(-shake_ox, -shake_oy)
            # -- /10G --
        else:  # menu states — full-screen shell screen, no world
            shell.submit(renderer, view_w, view_h)
            _t_flush_start = time.perf_counter()
            flush_frame()
        _t_flush_end = time.perf_counter()
        presenter.end_frame(capture_path)
        _t_present_end = time.perf_counter()
        if capture_path is not None:
            print(f"capture saved: {capture_path}")

        perf["sim"] += _t_render0 - _t_sim0
        perf["submit"] += _t_flush_start - _t_render0
        perf["world"] += flush_acc["world"]
        perf["hud"] += flush_acc["hud"]
        _composite = presenter.last_composite_ms / 1000.0
        perf["composite"] += _composite
        # end_frame is composite + present; the presenter times its own
        # composite, so present is what is left of the call.
        perf["present"] += max(0.0,
                               (_t_present_end - _t_flush_end) - _composite)
        perf_frames += 1

        fps_log_ms += dt * 1000
        if fps_log_ms >= 1000:
            if tune_gc and perf_frames:  # windowed only — keep headless silent
                n = perf_frames
                print(f"fps: {clock.get_fps():.1f}  "
                      f"sim={perf['sim'] / n * 1000:.1f}ms  "
                      f"submit={perf['submit'] / n * 1000:.1f}ms  "
                      f"world={perf['world'] / n * 1000:.1f}ms  "
                      f"hud={perf['hud'] / n * 1000:.1f}ms  "
                      f"composite={perf['composite'] / n * 1000:.1f}ms  "
                      f"present={perf['present'] / n * 1000:.1f}ms")
            else:
                print(f"fps: {clock.get_fps():.1f}")
            for k in perf:
                perf[k] = 0.0
            perf_frames = 0
            fps_log_ms = 0
        frames += 1
        if max_frames is not None and frames >= max_frames:
            running = False

    # debug-mode-telemetry: idempotent — a no-op if the game-over path (or a
    # test) already closed it. Guarantees the reports are written even for a
    # run that ends by window-close rather than reaching GAME_OVER.
    if recorder is not None:
        recorder.close(outcome="quit")
    presenter.close()   # GPU path: destroy the standalone SDL window
    pygame.quit()
    return frames


def debug_level_from_argv(argv):
    """Parse the ``--debug[=N]`` CLI flag (debug-mode-telemetry Phase 5).

    Returns what ``main(debug_log=...)`` wants: ``None`` for "off" (no flag,
    or an explicit ``--debug=0``), else the integer level. Deliberately hand
    rolled rather than argparse: this is the entry point's ONLY flag, and
    ``main``'s other parameters (``max_frames``/``autostart``) are a headless
    test seam that must stay off the command line — a player cannot be given a
    way to boot a 5-frame run by accident.

    An unparseable or out-of-range level exits with a message rather than
    booting silently un-instrumented (the D-2 fail-loud convention: a debug
    run that quietly records nothing is worse than no run)."""
    for arg in argv:
        if arg == "--debug":
            return LEVEL_BASIC
        if arg.startswith("--debug="):
            raw = arg.split("=", 1)[1]
            try:
                level = int(raw)
            except ValueError:
                raise SystemExit(
                    f"--debug expects an integer level {list(LEVELS)}: {raw!r}")
            if level not in LEVELS:
                raise SystemExit(
                    f"--debug level must be one of {list(LEVELS)}: {level}")
            return level if level > LEVEL_OFF else None
    return None


if __name__ == "__main__":
    main(debug_log=debug_level_from_argv(sys.argv[1:]),
         backend=backend_choice_from_argv(sys.argv[1:]))
