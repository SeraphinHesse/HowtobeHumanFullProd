"""Headless UI layout exporter (Phase 10L-B, B3).

    py tools/export_ui_layouts.py [--data-root PATH] [--output-dir PATH]

Constructs every one of the 13 live screens (``game/ui`` — the original 12 +
Phase 3's ``overlays``, the map-overlay toggle pills) headlessly, with
canned mock state (love=123, round=7; a mid-game selection for
``building_panel``; ``open(1, "win")`` for ``boss_cutscene``), and emits every
NAMED widget's ``{rect, kind, label}`` from the screen's ``ids`` dict (the B2
contract, ``game/ui/skinning.py`` line ~15: ``ids: {name: (kind, widget)}``).
Writes the flat, schema-validated ``data/ui/screen_defaults.json`` (B1's
``screen_defaults.schema.json``) via ``engine.data_io.write_validated`` — D-3
canonical form (sorted keys, 2-space indent), so re-running the exporter with
no code change is byte-identical.

Every screen is built with a DISK-FREE ``ScreenSkinning.empty()`` (the default
when ``skinning=None``) — this file records the CODE-authored default
geometry, independent of whatever a designer has since written into
``data/ui/screens/*.json``. The editor composes overrides ON TOP of these
defaults; recording the override-applied geometry here would make the two
layers indistinguishable.

No pygame window is ever created: SDL dummy drivers are set before any import
that might pull pygame in transitively (mirrors ``tools/tests/test_game_boot.
py``); ``engine.render.fonts`` needs only the font subsystem (no display), so
even that is headless-safe under dummy drivers.
"""
import argparse
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from engine import data_io  # noqa: E402

# Alphabetical, stable order (plan line 282's 12 screen ids, + Phase 3's
# "overlays" — the map-overlay toggle pills, added the sanctioned "drop in a
# file + ids" way, B1's extension path beyond the original 12). json.dumps'
# sort_keys=True re-sorts the top level anyway, so this only fixes the order
# build_screen_defaults is invoked in, not the file's byte layout.
SCREEN_IDS = [
    "add_name", "boss_cutscene", "building_panel", "cheat_menu", "credits",
    "enemy_intro", "game_log", "game_over", "hud", "levelup", "main_menu",
    "overlays", "pause", "settings",
]

# Common mock state (§1.3): every screen construction reads these where it
# needs a love/round number at all (menu screens need neither — "idle
# defaults").
_LOVE = 123
_ROUND = 7
_COMMON_NOTE = f"love={_LOVE}, round={_ROUND}"

# A starts-unlocked building type (Stone Thrower) — a safe, always-buildable
# pick for the building_panel's ConstructPreview mock (game/buildings/
# CLAUDE.md: "only defence/economic start unlocked").
_MOCK_BUILDING_TYPE = "defence"

# -- UH-4: cosmetic human names for widget ids (D4 — the id stays the on-disk
# contract everywhere; this mapping only feeds an OPTIONAL `display_name` that
# the editor prefers and falls back from). {screen_id: {widget_id:
# display_name}}. `building_panel` is the gated, complete mapping (all 13
# ids, plan's motivating screen); the other 12 screens are mapped on a
# best-effort basis — any id absent here simply gets no `display_name` key
# and the editor falls back to the raw id (harmless, D4).
_DISPLAY_NAMES = {
    "building_panel": {
        "panel": "Building panel",
        "close_btn": "Close button",
        "action_btn": "Unlock / Build / Upgrade button",
        "boss_btn": "Boss history button",
        "boss_close_btn": "Boss history close button",
        "rename_dice_btn": "Rename dice button",
        "move_btn": "Move building button",
        "preview_panel": "Construct preview window",
        "preview_confirm_btn": "Construct confirm button",
        "preview_cancel_btn": "Construct cancel button",
        "preview_close_btn": "Construct preview close button",
        "preview_dice_btn": "Construct preview dice button",
    },
    "main_menu": {
        "backdrop": "Background backdrop",
        "title": "Title label",
        "subtitle": "Subtitle label",
        "btn_new_game": "Start New Game button",
        "btn_add_name": "Add A Name button",
        "btn_settings": "Settings button",
        "btn_credits": "Credits button",
        "btn_quit": "Quit button",
    },
    "pause": {
        "backdrop": "Background backdrop",
        "title": "Title label",
        "btn_resume": "Resume button",
        "btn_settings": "Settings button",
        "btn_quit_to_menu": "Quit To Menu button",
        "btn_quit_game": "Quit Game button",
    },
    "settings": {
        "backdrop": "Background backdrop",
        "title": "Title label",
        "btn_dm_left": "Display mode left button",
        "btn_dm_right": "Display mode right button",
        "btn_back": "Back button",
        "btn_toggle_income_floaters": "Income Floaters toggle",
        "btn_toggle_bg_art": "Background Art toggle",
        "btn_toggle_gore": "Gore toggle",
    },
    "credits": {
        "backdrop": "Background backdrop",
        "title": "Title label",
        "btn_back": "Back button",
    },
    "add_name": {
        "backdrop": "Background backdrop",
        "panel": "Add name panel",
        "title": "Title label",
        "btn_add": "Add button",
        "btn_back": "Back button",
    },
    "game_over": {
        "backdrop": "Background backdrop",
        "title": "Title label",
        "btn_return_to_menu": "Return To Menu button",
    },
    "cheat_menu": {
        "panel": "Cheat menu panel",
        "title": "Title label",
        "btn_close": "Close button",
        "round_field": "Round field",
        "btn_goto": "Go To Round button",
        "jump_label": "Jump label",
        "btn_add_love": "Add Love button",
        "btn_skip_round": "Skip Round button",
        "btn_trigger_levelup": "Trigger Levelup button",
        "btn_inf_money": "Infinite Money button",
        "btn_unlock_all": "Unlock All Tech button",
    },
    "game_log": {
        "log": "Game log",
    },
    "boss_cutscene": {
        "backdrop": "Background backdrop",
        "headline": "Headline label",
        "subtitle": "Subtitle label",
        "box_a": "Boss option A box",
        "box_b": "Boss option B box",
    },
    "overlays": {
        "btn_range": "Range overlay toggle",
        "btn_heatmap": "Heatmap overlay toggle",
    },
    "enemy_intro": {
        "panel": "Enemy intro panel",
        "close_btn": "Close button",
    },
    "hud": {
        "btn_end_turn": "End Turn button",
        "btn_pause": "Pause button",
        "love_panel": "Love panel",
        "readout_panel": "Income/lives/tiles panel",
        "phase_label": "Phase label",
        "xp_bar": "XP bar",
    },
    "levelup": {
        "backdrop": "Background backdrop",
    },
}


def _apply_display_names(screen_id, entry):
    """Annotate ``widget["display_name"]`` wherever a ``widgets`` mapping
    appears in ``entry`` — the flat top level AND inside every per-mode
    ``views.<name>`` value (R1: walked by key name so this needs no edit when
    a screen grows/loses a ``views`` level). Ids absent from
    ``_DISPLAY_NAMES[screen_id]`` are left untouched — the file stays minimal,
    fallback-to-id is the reader's job (D4). Does not touch ``_widget_entry``/
    ``_widgets_from_ids``/the ``_build_*`` builders (R1 — none of them receive
    the screen id)."""
    names = _DISPLAY_NAMES.get(screen_id)
    if not names:
        return
    for key, value in entry.items():
        if key == "widgets":
            for widget_id, spec in value.items():
                name = names.get(widget_id)
                if name:
                    spec["display_name"] = name
        elif key == "views":
            for view in value.values():
                for widget_id, spec in view.get("widgets", {}).items():
                    name = names.get(widget_id)
                    if name:
                        spec["display_name"] = name


def _logical_resolution(data_root):
    """The logical (view_w, view_h) resolution from ``data/display.json`` —
    never hardcoded (brief §1: "never hardcode 1280x720")."""
    display = data_io.load_validated(
        data_root / "display.json", data_root / "schemas" / "display.schema.json")
    return display["window_w"], display["window_h"]


def _widget_entry(kind, widget):
    """``{rect, kind, label}`` for one ``ids`` entry. ``kind`` is read from the
    ids PAIR (never ``type(widget).__name__``); ``label`` is the widget's own
    ``label`` attribute or ``""``.

    A handful of B2's ``ids`` targets (``hud.phase_label``, ``cheat_menu.
    title``/``jump_label``, ``boss_cutscene.headline``/``subtitle`` — every one
    a dynamically-positioned ``"label"`` whose on-screen spot is computed
    inline at submit() time, never stored) carry NO ``rect`` attribute at all;
    the schema still requires one, so those fall back to ``(0, 0, 0, 0)``
    here rather than crash (a documented B3 finding, not a fix — see the
    phase report)."""
    x, y, w, h = getattr(widget, "rect", (0, 0, 0, 0))
    label = getattr(widget, "label", "") or ""
    return {"rect": [int(x), int(y), int(w), int(h)], "kind": kind,
            "label": label}


def _widgets_from_ids(ids):
    return {name: _widget_entry(kind, widget)
            for name, (kind, widget) in ids.items()}


# -- per-screen builders: (widgets_dict, mock_note) --------------------------

def _build_main_menu(view_w, view_h, data_root):
    from game.ui.main_menu import MainMenu

    screen = MainMenu(view_w, view_h)  # __init__ lays out already
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_pause(view_w, view_h, data_root):
    from game.ui.pause import PauseScreen

    screen = PauseScreen(view_w, view_h)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_settings(view_w, view_h, data_root):
    from game.ui.settings import SessionSettings, SettingsScreen

    screen = SettingsScreen(view_w, view_h, SessionSettings())
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (idle, default SessionSettings — no world state)")


def _build_credits(view_w, view_h, data_root):
    from game.ui.credits import CreditsScreen

    screen = CreditsScreen(view_w, view_h)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_add_name(view_w, view_h, data_root):
    from game.ui.add_name import AddNameScreen

    screen = AddNameScreen(view_w, view_h)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_game_over(view_w, view_h, data_root):
    from game.ui.game_over import GameOverScreen

    screen = GameOverScreen(view_w, view_h)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_levelup(view_w, view_h, data_root):
    from game.ui.levelup import LevelupWindow

    screen = LevelupWindow(view_w, view_h)
    # __init__ leaves ids == {} (layout() only runs from open()/layout()
    # itself — see game/ui/CLAUDE.md); call it directly so "backdrop" emits
    # without needing a real levelup-option roll.
    screen.layout(view_w, view_h)
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (backdrop only — the 1-3 option boxes are "
            "dynamic-count content, not individually overridable)")


def _build_hud(view_w, view_h, data_root):
    from game.ui.hud import Hud

    screen = Hud(view_w, view_h)  # __init__ already calls layout()
    # 2nd ids pass (normally triggered from submit(), see game/ui/CLAUDE.md
    # "hud.py's ~12 stable readouts"): pill-relative readouts need
    # love_panel/end_turn finalized first, so this cannot join layout().
    screen._layout_readouts()
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (layout() + the _layout_readouts() second pass)")


# -- UH-1: per-mode building_panel views --------------------------------
# The exporter used to superimpose all four BuildingUI modes plus the
# ConstructPreview modal into one flattened snapshot the game never shows,
# recording mode-dependent geometry (e.g. action_btn) from __init__ before any
# mode builder ran. Each view below builds its OWN fresh BuildingUI (never
# shared — this is the determinism guarantee at the object level: no mode's
# state leaks into another's rect/label) and records only the ids that mode
# actually draws (building_ui.py hover/click dispatch + the mode builders).
_BP_VIEW_ORDER = ("unlock", "construct", "upgrade", "base_info", "preview")

# Per-view id membership — mirrors building_ui.py's mode dispatch exactly
# (unlock/construct/upgrade panel views + the base_info stand-in + the
# ConstructPreview modal's own disjoint "preview_*" namespace).
_BP_UNLOCK_IDS = ("panel", "close_btn", "action_btn")
_BP_CONSTRUCT_IDS = ("panel", "close_btn")
_BP_UPGRADE_IDS = ("panel", "close_btn", "action_btn", "rename_dice_btn",
                   "move_btn")
_BP_BASE_INFO_IDS = ("panel", "close_btn", "boss_btn", "boss_close_btn")

# Fixed unlock-cost mock (view §2: "mock values go in the view's mock_note") —
# any deterministic constant works since the union exists for the id set, not
# per-mode cost accuracy.
_MOCK_UNLOCK_COST = 40


def _bp_view_widgets(panel, id_names):
    """``_widgets_from_ids`` over a fixed subset of a BuildingUI's mode-
    independent ``ids`` — every view/union entry still routes through the
    one entry-construction path (``_widget_entry``/``_widgets_from_ids``)."""
    return _widgets_from_ids({name: panel.ids[name] for name in id_names})


def _build_bp_unlock(view_w, view_h, ui_balance):
    from types import SimpleNamespace

    from game.ui.building_ui import BuildingUI

    panel = BuildingUI(view_w, view_h, ui_balance)
    tile = SimpleNamespace(col=0, row=0)
    panel.selected_tiles = [tile]
    # A minimal stand-in "session" exposing only the three callables
    # ``_build_unlock`` reads (building_ui.py:472-476) — no real tilemap.
    session = SimpleNamespace(tilemap=SimpleNamespace(
        get_chunk_for_tile=lambda t: [t],
        unlock_cost=lambda t: _MOCK_UNLOCK_COST,
        can_unlock=lambda t: True,
    ))
    panel._build_unlock(session)
    widgets = _bp_view_widgets(panel, _BP_UNLOCK_IDS)
    note = (f"{_COMMON_NOTE}; mock tile (0,0), a single-tile chunk, fixed "
            f"unlock_cost={_MOCK_UNLOCK_COST}, can_unlock=True (always "
            "adjacent)")
    return {"widgets": widgets, "mock_note": note}


def _build_bp_construct(view_w, view_h, ui_balance):
    from game.ui.building_ui import BuildingUI

    panel = BuildingUI(view_w, view_h, ui_balance)
    widgets = _bp_view_widgets(panel, _BP_CONSTRUCT_IDS)
    note = (f"{_COMMON_NOTE}; construct cards are dynamic-count and "
            "deliberately un-id'd (B3 rule) — they inherit "
            "defaults.button_skin instead of an individual override")
    return {"widgets": widgets, "mock_note": note}


def _build_bp_upgrade(view_w, view_h, ui_balance, buildings_balance,
                      core_balance):
    from types import SimpleNamespace

    from game.buildings.registry import create
    from game.core.game_state import RunState
    from game.ui.building_ui import BuildingUI

    panel = BuildingUI(view_w, view_h, ui_balance)
    building = create(_MOCK_BUILDING_TYPE, 0, 0, buildings_balance)
    tile = SimpleNamespace(col=0, row=0)
    panel._selected = building
    panel.selected_tiles = [tile]
    panel._buildings_balance = buildings_balance
    # Open item ruling #3: a real, freshly-constructed run-state
    # (``RunState.from_balance``) constructs headlessly with no world, so it
    # is preferred over a SimpleNamespace stand-in. ``upgrade_gate`` on a
    # freshly-created tier-0/level-1 building resolves the "in_tier" branch
    # deterministically (measured: `upgrade_gate` -> ("in_tier", None, 10)
    # for the mock building type) without touching any research/round field.
    panel._session = SimpleNamespace(
        state=RunState.from_balance(core_balance, buildings_balance))
    panel._build_upgrade()
    widgets = _bp_view_widgets(panel, _BP_UPGRADE_IDS)
    note = (f"{_COMMON_NOTE}; a freshly created {_MOCK_BUILDING_TYPE!r} "
            "building (tier 0, level 1) with a fresh "
            "RunState.from_balance() run-state — upgrade_gate resolves "
            "'in_tier' deterministically")
    return {"widgets": widgets, "mock_note": note}


def _build_bp_base_info(view_w, view_h, ui_balance):
    from game.ui.building_ui import BuildingUI

    # base_info's ids (panel/close_btn/boss_btn/boss_close_btn) are all
    # mode-independent (built once in __init__, Storm Priest rework removed
    # the one id that used to need a forced builder call: lightning_btn).
    panel = BuildingUI(view_w, view_h, ui_balance)
    widgets = _bp_view_widgets(panel, _BP_BASE_INFO_IDS)
    return {"widgets": widgets, "mock_note": _COMMON_NOTE}


def _build_bp_preview(view_w, view_h, ui_balance, buildings_balance):
    from game.buildings.registry import build_cost
    from game.ui.building_ui import ConstructPreview

    # ConstructPreview's disjoint "preview_*" ids (mid-game: a building
    # chosen, the construct-confirm modal open) — its own ids/apply pass runs
    # once in __init__.
    tier_idx = 0
    cost = build_cost(_MOCK_BUILDING_TYPE, buildings_balance, tier_idx)
    preview = ConstructPreview(
        _MOCK_BUILDING_TYPE, cost, buildings_balance, ui_balance,
        view_w, view_h, count=1, tier_idx=tier_idx)
    widgets = _widgets_from_ids(preview.ids)
    note = (f"{_COMMON_NOTE}; ConstructPreview({_MOCK_BUILDING_TYPE!r}) "
            "modal open, count=1, tier_idx=0 (preview_cancel_btn present "
            "iff ui.Timing.construct_show_cancel)")
    return {"widgets": widgets, "mock_note": note}


def _build_building_panel(view_w, view_h, data_root):
    """Five per-mode views (D2) + a deterministic first-wins union over
    ``_BP_VIEW_ORDER`` as the top-level ``widgets`` (the game's known-id set,
    ``game/ui/skinning.py:190-194`` — unchanged by this phase; the game never
    reads ``views``)."""
    from game.core.balance import load_balance

    buildings_balance = load_balance(data_root, "buildings")
    ui_balance = load_balance(data_root, "ui")
    core_balance = load_balance(data_root, "core")

    views = {
        "unlock": _build_bp_unlock(view_w, view_h, ui_balance),
        "construct": _build_bp_construct(view_w, view_h, ui_balance),
        "upgrade": _build_bp_upgrade(
            view_w, view_h, ui_balance, buildings_balance, core_balance),
        "base_info": _build_bp_base_info(view_w, view_h, ui_balance),
        "preview": _build_bp_preview(view_w, view_h, ui_balance,
                                     buildings_balance),
    }

    widgets = {}
    for view_name in _BP_VIEW_ORDER:
        for widget_id, entry in views[view_name]["widgets"].items():
            if widget_id not in widgets:
                widgets[widget_id] = entry

    note = (f"{_COMMON_NOTE}; first-wins union of the five per-mode views "
            f"{_BP_VIEW_ORDER} for ids shared across modes (panel/"
            "close_btn) — see views.<name>.mock_note for that mode's own "
            "mock state")
    return widgets, note, views


def _build_cheat_menu(view_w, view_h, data_root):
    from game.ui.cheat_menu import CheatMenu

    screen = CheatMenu(view_w, view_h)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (idle, no world state)"


def _build_game_log(view_w, view_h, data_root):
    from game.ui.game_log import GameLog

    screen = GameLog()  # no view args — its ONE id is a style holder
    # submit() is what populates ids; with no queued messages it never
    # touches the renderer, so a bare None is safe here.
    screen.submit(None, view_h)
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (empty log, no messages queued)")


def _build_boss_cutscene(view_w, view_h, data_root):
    from game.core import load_balance
    from game.ui.boss_cutscene import BossCutscene

    # The option descs format live BossBonuses magnitudes in — geometry only
    # lands in the export, but the screen still needs a real core balance.
    screen = BossCutscene(view_w, view_h, load_balance(data_root, "core"))
    screen.open(1, "win")  # R3 contract: open(1, "win") + layout(1280, 720)
    return _widgets_from_ids(screen.ids), "open(1, 'win')"


def _build_enemy_intro(view_w, view_h, data_root):
    from game.core import load_balance
    from game.ui.enemy_intro import EnemyIntroWindow

    # feature-enemy-intro-dialogue: entries[] ships empty, so a mock entry is
    # needed to exercise the layout the way boss_cutscene's open(1, "win")
    # does. Only the window's own geometry/timings need to be real (they
    # come from live core.json); the mock entry's content is throwaway.
    core_balance = load_balance(data_root, "core")
    window_balance = core_balance["EnemyIntro"]["window"]
    screen = EnemyIntroWindow(view_w, view_h, window_balance)
    screen.open({
        "enemy_label": "Mock Enemy", "round": 1, "title": "Mock title",
        "body": "Mock body text.", "sprite_slot": "enemy_stage_1_v1",
        "sprite_w": 96, "sprite_h": 96,
    })
    # Recorded at REST (fully open, docked to the right edge), not the
    # instant-of-open off-screen position open() itself leaves it at — a
    # designer previewing/overriding this screen wants the on-screen geometry.
    # One update() past open_seconds deterministically settles the HOLD phase
    # regardless of the configured duration.
    screen.update(window_balance["open_seconds"] + 1.0, 0, 0)
    return _widgets_from_ids(screen.ids), f"{_COMMON_NOTE} (mock entry; open(), settled at rest)"


def _build_overlays(view_w, view_h, data_root):
    from game.ui.overlays import MapOverlays

    # ids are applied once in __init__ (no separate layout() step — mirrors
    # BuildingUI's mode-independent ids), so a bare construction is enough.
    screen = MapOverlays(view_w, view_h)
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (idle, no world state — the two toggle pills)")


_BUILDERS = {
    "add_name": _build_add_name,
    "boss_cutscene": _build_boss_cutscene,
    "building_panel": _build_building_panel,
    "cheat_menu": _build_cheat_menu,
    "credits": _build_credits,
    "enemy_intro": _build_enemy_intro,
    "game_log": _build_game_log,
    "game_over": _build_game_over,
    "hud": _build_hud,
    "levelup": _build_levelup,
    "main_menu": _build_main_menu,
    "overlays": _build_overlays,
    "pause": _build_pause,
    "settings": _build_settings,
}


def build_screen_defaults(screen_id, view_w, view_h, data_root):
    """``{widgets, mock_note}`` for one screen (``{widgets, views, mock_note}``
    for ``building_panel`` — UH-1's per-mode views, D2) — any construction
    failure propagates with context (brief §2 Edit 1.6: "no silent skips")."""
    builder = _BUILDERS[screen_id]
    try:
        result = builder(view_w, view_h, data_root)
    except Exception as exc:
        raise RuntimeError(
            f"export_ui_layouts: screen {screen_id!r} failed to construct "
            f"headless: {exc}") from exc
    if screen_id == "building_panel":
        widgets, mock_note, views = result
        entry = {"widgets": widgets, "views": views, "mock_note": mock_note}
    else:
        widgets, mock_note = result
        entry = {"widgets": widgets, "mock_note": mock_note}
    _apply_display_names(screen_id, entry)
    return entry


def main(data_root=None, output_dir=None):
    """Regenerate ``<output_dir>/ui/screen_defaults.json``. ``data_root``
    defaults to the repo's ``data/``, ``output_dir`` to ``data_root`` itself —
    both injectable so tests can regenerate into a tempdir without touching
    the live tree (§1.6)."""
    data_root = Path(data_root) if data_root is not None else REPO / "data"
    output_dir = Path(output_dir) if output_dir is not None else data_root

    view_w, view_h = _logical_resolution(data_root)

    output = {
        screen_id: build_screen_defaults(screen_id, view_w, view_h, data_root)
        for screen_id in SCREEN_IDS
    }

    output_path = output_dir / "ui" / "screen_defaults.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = data_root / "schemas" / "screen_defaults.schema.json"
    data_io.write_validated(output, output_path, schema_path)
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    sys.exit(main(data_root=args.data_root, output_dir=args.output_dir))
