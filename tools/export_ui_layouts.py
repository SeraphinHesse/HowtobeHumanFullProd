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
    "game_log", "game_over", "hud", "levelup", "main_menu", "overlays",
    "pause", "settings",
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


def _build_building_panel(view_w, view_h, data_root):
    from types import SimpleNamespace

    from game.buildings.registry import build_cost
    from game.core.balance import load_balance
    from game.ui.building_ui import BuildingUI, ConstructPreview

    buildings_balance = load_balance(data_root, "buildings")
    ui_balance = load_balance(data_root, "ui")
    core_balance = load_balance(data_root, "core")

    # BuildingUI's mode-independent ids (panel/close_btn/action_btn/boss_btn/
    # rename_dice_btn/boss_close_btn) are set once in __init__ — no
    # open_for_tile()/layout() call needed to populate them (game/ui/
    # CLAUDE.md "mode-independent ids").
    panel = BuildingUI(view_w, view_h, ui_balance)
    widgets = dict(_widgets_from_ids(panel.ids))

    # lightning_btn is the one id that is NOT mode-independent — it is
    # (re)created inside _build_base_info, so a bare construction never
    # populates it. A minimal stand-in "session" (only the two attributes
    # _build_base_info reads) exercises the real builder so its default rect
    # is recorded too — skipping this would leave "lightning_btn" out of
    # screen_defaults.json's known-id set, and a real building_panel.json
    # override naming it would raise ValueError at load (Phase 3).
    panel._build_base_info(SimpleNamespace(
        state=SimpleNamespace(lightning_level=1), core_balance=core_balance))
    if panel.lightning_btn is not None:
        widgets.update(_widgets_from_ids(
            {"lightning_btn": ("button", panel.lightning_btn)}))

    # ConstructPreview's disjoint "preview_*" ids (mid-game: a building
    # chosen, the construct-confirm modal open) — its own ids/apply pass runs
    # once in __init__ too.
    tier_idx = 0
    cost = build_cost(_MOCK_BUILDING_TYPE, buildings_balance, tier_idx)
    preview = ConstructPreview(
        _MOCK_BUILDING_TYPE, cost, buildings_balance, ui_balance,
        view_w, view_h, count=1, tier_idx=tier_idx)
    widgets.update(_widgets_from_ids(preview.ids))

    note = (f"{_COMMON_NOTE}; mid-game selection — BuildingUI panel + a "
            f"ConstructPreview({_MOCK_BUILDING_TYPE!r}) modal open "
            "(disjoint preview_* id namespace)")
    return widgets, note


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
    from game.ui.boss_cutscene import BossCutscene

    screen = BossCutscene(view_w, view_h)
    screen.open(1, "win")  # R3 contract: open(1, "win") + layout(1280, 720)
    return _widgets_from_ids(screen.ids), "open(1, 'win')"


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
    """``{widgets, mock_note}`` for one screen — any construction failure
    propagates with context (brief §2 Edit 1.6: "no silent skips")."""
    builder = _BUILDERS[screen_id]
    try:
        widgets, mock_note = builder(view_w, view_h, data_root)
    except Exception as exc:
        raise RuntimeError(
            f"export_ui_layouts: screen {screen_id!r} failed to construct "
            f"headless: {exc}") from exc
    return {"widgets": widgets, "mock_note": mock_note}


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
