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
from game.ui import strings  # noqa: E402
from game.ui.building_ui import _CARD_ID_PREFIX  # noqa: E402
from tools import screen_mocks  # noqa: E402

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
# defaults"). UT-2 moved the mock state itself into `tools/screen_mocks.py`
# so the preview generator builds from the SAME objects this file reads
# default geometry off; these are re-exported names, not a second copy.
_COMMON_NOTE = screen_mocks.COMMON_NOTE
_MOCK_BUILDING_TYPE = screen_mocks.MOCK_BUILDING_TYPE

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
        # UT-3 text. The ~40 stat/base-info row ids are NOT listed: their
        # names are derived from their own resolved text (see
        # `_derived_display_name`), so renaming a stat renames its two
        # widgets in the editor list too.
        "unlock_title": "Unlock header",
        "unlock_hint": "Unlock subtitle",
        "unlock_blocked": "Not-adjacent warning",
        "construct_title": "Build header",
        "upgrade_title": "Building name header",
        "upgrade_name": "Rename box text",
        "upgrade_tier_level": "Tier / level line",
        "died_last_round": "Died-last-round tag",
        "next_tier_header": "Next-tier card header",
        "upgrade_hint": "Action button hint",
        "base_info_title": "The Hole header",
        "move_title": "Move header",
        "move_name": "Moving building name",
        "move_pick": "Pick-a-tile instruction",
        "move_hint_1": "Move hint line 1",
        "move_hint_2": "Move hint line 2",
        "move_hint_cancel": "Move cancel instruction",
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
    # Every HUD id is named, not just the six that happened to be listed —
    # a designer asked for the round counter, love counter, love-per-round,
    # XP bar and level counter as "individual editable widgets", and they
    # already WERE individual ids; what was missing was a name to find them
    # by (and a hit box to grab them by — see `_widget_entry`).
    "hud": {
        "btn_end_turn": "End Turn button",
        "btn_pause": "Pause button",
        "btn_speed_1x": "Speed 1x button",
        "btn_speed_1_5x": "Speed 1.5x button",
        "btn_speed_2x": "Speed 2x button",
        "btn_drag_select": "Drag-select toggle",
        "love_panel": "Love panel",
        "readout_panel": "Income/lives/tiles panel",
        "phase_label": "Phase label",
        "love_text": "Love counter",
        "income_text": "Love per round",
        "lvl_label": "Level counter",
        "xp_bar": "XP bar",
        "xp_text": "XP progress text",
        "lives_text": "Lives counter",
        "tiles_text": "Tiles counter",
        "round_label": "Round counter",
        "icon_love": "Love icon",
        "icon_xp": "XP icon",
        "icon_lives": "Lives icon",
    },
    "levelup": {
        "backdrop": "Background backdrop",
        "heading": "Heading label",
        "option_box_0": "Level-up option box 1",
        "option_box_1": "Level-up option box 2",
        "option_box_2": "Level-up option box 3",
    },
}


# -- UiEditorParentingPLAN P-2: the DEFAULT widget hierarchy (D1) ------------
# One optional `parent` key per widget record, naming another id in the SAME
# screen+view. The exporter is the right author for it: `hud.py`'s
# `_layout_readouts()` literally computes the readouts off `love_panel`'s
# rect, so "parented sensibly" is a mapping written once here rather than a
# designer chore. Absent `parent` = a root widget (every screen keeps working
# before its mapping is filled in), and a parent naming an id that is not in
# THIS widgets map is never written at all — `building_panel`'s per-mode views
# each show only a slice of the 85 ids.
#
# Parenting is an AUTHORING relationship, not a runtime one (plan D2): the
# game's own `layout()` still recomputes every default each frame with no
# cascade, and nothing in `game/` reads this key.
#
# {screen_id: {widget_id: parent_id}} — the explicit pairs.
_PARENTS = {
    # `_layout_readouts()` places all six off `love_panel`'s rect; the round
    # counter is drawn above the End Turn button and moves with it.
    "hud": {
        "love_text": "love_panel",
        "icon_love": "love_panel",
        "lvl_label": "love_panel",
        "icon_xp": "love_panel",
        "xp_bar": "love_panel",
        "xp_text": "love_panel",
        "income_text": "readout_panel",
        "lives_text": "readout_panel",
        "icon_lives": "readout_panel",
        "tiles_text": "readout_panel",
        "round_label": "btn_end_turn",
    },
    # The construct-preview window is its OWN container, floating over the
    # building panel — its four buttons belong to it, not to `panel`.
    "building_panel": {
        "preview_confirm_btn": "preview_panel",
        "preview_cancel_btn": "preview_panel",
        "preview_close_btn": "preview_panel",
        "preview_dice_btn": "preview_panel",
    },
}

# {screen_id: (parent_id, exempt_ids)} — "every OTHER widget on this screen
# belongs to <parent_id>". These are the screens with one real container that
# genuinely owns everything else on them: a full-screen `backdrop` behind a
# menu, or a `panel` holding a wall of rows. Spelling `building_panel`'s ~80
# stat cells out one pair at a time would be noise that drifts the moment a
# stat row is added — and there is no judgement in those pairs, the panel owns
# every one of them.
#
# `exempt_ids` are the OTHER roots on that screen. An id already carrying an
# explicit `_PARENTS` pair above keeps it (explicit wins), and the container
# itself is never its own child.
_PARENT_CONTAINERS = {
    "main_menu": ("backdrop", ()),
    "pause": ("backdrop", ()),
    "settings": ("backdrop", ()),
    "credits": ("backdrop", ()),
    "game_over": ("backdrop", ()),
    "boss_cutscene": ("backdrop", ()),
    "levelup": ("backdrop", ()),
    # `backdrop` is the full-screen dimmer BEHIND the panel, not a sibling
    # inside it — the panel and it are both roots.
    "add_name": ("panel", ("backdrop",)),
    "cheat_menu": ("panel", ()),
    "building_panel": ("panel", ("preview_panel",)),
}
# `overlays` (2 pills), `game_log` (1 log) and `enemy_intro` (a panel and its
# close button) are deliberately absent: flat, nothing to express.


def _apply_display_names(screen_id, entry):
    """Annotate ``widget["display_name"]`` and ``widget["parent"]`` wherever a
    ``widgets`` mapping appears in ``entry`` — the flat top level AND inside
    every per-mode ``views.<name>`` value (R1: walked by key name so this
    needs no edit when a screen grows/loses a ``views`` level). Ids absent
    from ``_DISPLAY_NAMES[screen_id]`` are left untouched — the file stays
    minimal, fallback-to-id is the reader's job (D4). Does not touch
    ``_widget_entry``/``_widgets_from_ids``/the ``_build_*`` builders (R1 —
    none of them receive the screen id)."""
    names = _DISPLAY_NAMES.get(screen_id)
    for key, value in entry.items():
        if key == "widgets":
            if names is not None:
                _name_widgets(names, value)
            _parent_widgets(screen_id, value)
        elif key == "views":
            for view in value.values():
                if names is not None:
                    _name_widgets(names, view.get("widgets", {}))
                _parent_widgets(screen_id, view.get("widgets", {}))


def _derived_parent(widget_id, widgets):
    """The parent of a widget whose id ENCODES it, or None.

    One rule today: a construct card is a widget tree (`card_<btype>` holding
    `card_<btype>_portrait` / `_name` / `_name_2` / `_price` / `_price_icon` /
    `_price_text`), and the card ids are DYNAMIC — one per buildable building
    type — so `_PARENTS` cannot spell the pairs out the way it does for the
    preview modal's four fixed buttons. The longest matching card id wins, so
    a building type whose name is a prefix of another's could not steal a
    child.
    """
    if not widget_id.startswith(_CARD_ID_PREFIX):
        return None
    candidates = [w for w in widgets
                  if w != widget_id and widget_id.startswith(w + "_")
                  and w.startswith(_CARD_ID_PREFIX)]
    return max(candidates, key=len) if candidates else None


def _parent_widgets(screen_id, widgets):
    """Write ``spec["parent"]`` for every widget of ONE widgets map (P-2).

    A parent is recorded only when the parent id is present in the SAME map,
    so a per-mode view that does not show the container leaves its widgets as
    roots instead of pointing at an absent id. Every other id simply gets no
    key (D-3 minimality — the reader's absent-means-root rule does the rest).

    Precedence, highest first: an explicit `_PARENTS` pair, then `_derived_
    parent` (the construct card's own children), then the screen's
    `_PARENT_CONTAINERS` fallback. The derived rule has to beat the container
    or every card CHILD would parent to `panel` alongside its card instead of
    nesting under it.
    """
    explicit = _PARENTS.get(screen_id, {})
    container, exempt = _PARENT_CONTAINERS.get(screen_id, (None, ()))
    for widget_id, spec in widgets.items():
        parent = explicit.get(widget_id) or _derived_parent(widget_id, widgets)
        if parent is None and container is not None \
                and widget_id != container and widget_id not in exempt:
            parent = container
        if parent is not None and parent != widget_id and parent in widgets:
            spec["parent"] = parent


def _card_human_names(widgets):
    """``{card_id: "Stone Thrower"}`` — each construct card's building name.

    The card BODY carries an empty label since the card became a widget tree,
    so the name comes off its name ROWS: `card_<btype>_name` holds the whole
    name (row 2 is empty — the panel wraps it at draw time, never here, so the
    committed artifact never depends on a live font measurement)."""
    rows = {}
    for widget_id, spec in widgets.items():
        for suffix in ("_name", "_name2"):
            if widget_id.startswith(_CARD_ID_PREFIX) \
                    and widget_id.endswith(suffix):
                rows.setdefault(widget_id[: -len(suffix)], {})[suffix] = \
                    spec.get("label") or ""
    return {card: " ".join(v for _, v in sorted(parts.items()) if v).strip()
            for card, parts in rows.items()}


def _card_part_display_name(widget_id, card_names):
    """``"Stone Thrower card"`` / ``"Stone Thrower card price icon"`` for any
    id in a construct card's tree, or None. The longest owning card id wins,
    so a building type whose name prefixes another's cannot claim its
    children."""
    if not widget_id.startswith(_CARD_ID_PREFIX):
        return None
    owners = [c for c in card_names
              if widget_id == c or widget_id.startswith(c + "_")]
    if not owners:
        return None
    card = max(owners, key=len)
    human = card_names[card]
    if not human:
        return None
    if widget_id == card:
        return f"{human} card"
    part = widget_id[len(card) + 1:].replace("_", " ")
    return f"{human} card {part}"


def _name_widgets(names, widgets):
    card_names = _card_human_names(widgets)
    for widget_id, spec in widgets.items():
        name = (names.get(widget_id)
                or _card_part_display_name(widget_id, card_names)
                or _derived_display_name(widget_id, spec))
        if name:
            spec["display_name"] = name


def _derived_display_name(widget_id, spec):
    """A human name DERIVED from the widget's own text (UT-3), for the id
    families too numerous to list — the ~40 ``stat_<key>_label`` /
    ``stat_<key>_value`` pairs and the base-info rows.

    Reading it off the resolved `sample` rather than a second hand-written
    table means renaming a stat in `strings.json` renames it in the editor's
    widget list too, with no exporter edit.
    """
    # A construct card names itself after the building it sells. The card's
    # own label already reads "<Building Name>  <cost>"; the price is live
    # game state, so only the name half becomes the widget's display name.
    if widget_id.startswith("card_"):
        label = spec.get("label") or ""
        name = label.rsplit("  ", 1)[0].strip() if label else ""
        return f"{name} card" if name else f"{widget_id[len('card_'):]} card"
    for suffix, kind in (("_label", "label"), ("_value", "value")):
        if not widget_id.endswith(suffix):
            continue
        stem = widget_id[: -len(suffix)]
        base = spec.get("sample")
        if base is None:
            # A value cell's template is "{value}" — name it after its row's
            # LABEL sibling instead, which is what a designer looks for.
            base = _row_label_text(stem)
        if base:
            return f"{base} {kind}"
    return None


def _row_label_text(stem):
    """The resolved label text of the row `stem` names, or None."""
    for text_id in (f"building.stat.{stem[len('stat_'):]}"
                    if stem.startswith("stat_") else None,
                    f"building.base_info.{stem[len('info_'):]}"
                    if stem.startswith("info_") else None,
                    f"building.upgrade.{stem}"):
        if text_id is None:
            continue
        try:
            return strings.T(text_id)
        except (KeyError, IndexError):
            continue
    return None


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
    entry = {"rect": [int(x), int(y), int(w), int(h)], "kind": kind,
             "label": label}
    # The two DRAW hints the editor needs to give a POSITION-ONLY text anchor
    # (a `rect` whose w/h are 0 — every readout in hud.py, the phase banner,
    # boss_cutscene's headline, ~40 building_panel stat cells) a real hit box:
    # what font it is drawn at, and which way its text spreads from the
    # stored x. Without them such a widget is a zero-area rect — impossible to
    # click, drag or even see selected in the editor, though its id has been
    # in `screen_defaults.json` since B3. Both are recorded ONLY when the
    # widget actually carries them (D-3 minimality; `align` additionally only
    # when it differs from the "left" default), so every button/panel entry
    # stays byte-identical.
    font_key = getattr(widget, "font_key", None)
    if font_key:
        entry["font_key"] = font_key
    align = getattr(widget, "align", None)
    if align and align != "left":
        entry["align"] = align
    # UT-1/UT-3: the string-table key this widget resolves its text through,
    # plus the resolved text when the template takes no placeholders. A
    # TEMPLATED id gets no `sample` — the exporter cannot know the kwargs the
    # call site passes, and the editor has the recorded preview beside it
    # showing the real substituted text anyway.
    text_id = getattr(widget, "text_id", None)
    if text_id:
        entry["text_id"] = text_id
        try:
            entry["sample"] = strings.T(text_id)
        except (KeyError, IndexError):
            pass
    return entry


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
    # Opened on the SAME three mock options `tools/screen_preview.py` records
    # its picture from — one state, two artifacts, so the editor's draggable
    # boxes and the preview behind them cannot disagree. Three because that
    # is the roll's maximum and each slot is an individually overridable
    # widget now (`option_box_0..2`); a bare `layout()` on an unopened window
    # would emit the backdrop and heading only, leaving all three
    # un-overridable.
    screen.open(screen_mocks.LEVELUP_OPTIONS)
    return (_widgets_from_ids(screen.ids),
            f"{_COMMON_NOTE} (opened on {len(screen_mocks.LEVELUP_OPTIONS)} "
            "mock options — the maximum roll, so every option slot is "
            "recorded)")


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
# mode builder ran. Each view now builds its OWN fresh BuildingUI (never
# shared — the determinism guarantee at the object level: no mode's state
# leaks into another's rect/label) and records only the ids that mode actually
# draws.
#
# UT-2 moved that construction into `tools/screen_mocks.build_bp_view`, which
# `tools/screen_preview.py` also drives to record the per-view DRAW LIST. One
# mock state, two artifacts — the editor's draggable boxes and the preview
# behind them cannot disagree about where a widget is. The mocks are also
# fully submit-able now (a real `Session` over the pinned starter map instead
# of the old `SimpleNamespace` stand-ins), which is what makes the preview a
# real picture rather than a crash.

def _build_building_panel(view_w, view_h, data_root):
    """Five per-mode views (D2) + a deterministic first-wins union over
    ``BP_VIEW_ORDER`` as the top-level ``widgets`` (the game's known-id set,
    ``game/ui/skinning.py:190-194`` — the game never reads ``views``)."""
    balances = screen_mocks.load_balances(data_root)
    session = screen_mocks.build_session(data_root, balances)

    views = {}
    for view_name in screen_mocks.BP_VIEW_ORDER:
        bp = screen_mocks.build_bp_view(view_name, view_w, view_h, balances,
                                        session)
        views[view_name] = {"widgets": _widgets_from_ids(bp.ids),
                            "mock_note": bp.note}

    widgets = {}
    for view_name in screen_mocks.BP_VIEW_ORDER:
        for widget_id, entry in views[view_name]["widgets"].items():
            if widget_id not in widgets:
                widgets[widget_id] = entry

    note = (f"{_COMMON_NOTE}; first-wins union of the five per-mode views "
            f"{screen_mocks.BP_VIEW_ORDER} for ids shared across modes "
            "(panel/close_btn) — see views.<name>.mock_note for that mode's "
            "own mock state")
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
    screen.open(1, "win")  # R3 contract: open(1, "win") + layout(640, 360)
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


def _configure_strings(data_root):
    """Bind the string table to THIS data root's `strings.json`, exactly as
    `game/main.py` does at boot (UT-3).

    Without it both artifacts would record the module's unconfigured
    fallbacks — identical today (a pin test proves it), but silently stale the
    moment a designer edits a template, which is precisely the edit the editor
    re-records a preview for.
    """
    data_root = Path(data_root)
    doc = data_io.load_validated(data_root / "ui" / "strings.json",
                                 data_root / "schemas" / "strings.schema.json")
    strings.configure_strings(doc)


def write_previews(data_root, output_dir, view_w, view_h, *, overrides=None,
                   output_path=None):
    """Regenerate ``<output_dir>/ui/screen_previews.json`` — the DRAW LIST the
    editor's screen mode replays (UT-2).

    ``overrides`` (``{screen_id: override_doc}``) applies a designer's screen
    JSON before recording, which is how the editor re-renders an UNSAVED doc:
    it writes the open doc to a temp file, runs us with ``--overrides``, and
    replays the result. ``output_path`` redirects the write for exactly that
    case, so a preview render never touches the committed file.

    The committed file is always recorded OVERRIDE-FREE (``overrides=None``),
    for the same reason ``screen_defaults.json`` is: the two layers must stay
    distinguishable.
    """
    from game.ui.skinning import ScreenSkinning
    from tools import screen_preview

    skinning = None
    if overrides:
        skinning = ScreenSkinning.from_overrides(overrides)
    captured = screen_preview.capture_all(data_root, view_w, view_h,
                                          skinning=skinning)
    doc = screen_preview.serialize_all(captured)
    if output_path is None:
        output_path = Path(output_dir) / "ui" / "screen_previews.json"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(data_root) / "schemas" / "screen_previews.schema.json"
    data_io.write_validated(doc, output_path, schema_path)
    return doc


def main(data_root=None, output_dir=None, *, overrides=None,
         previews_out=None, previews_only=False):
    """Regenerate ``<output_dir>/ui/screen_defaults.json`` and
    ``screen_previews.json``. ``data_root`` defaults to the repo's ``data/``,
    ``output_dir`` to ``data_root`` itself — both injectable so tests can
    regenerate into a tempdir without touching the live tree (§1.6).

    ``previews_only`` skips the defaults pass: the editor's "re-render this
    unsaved doc" path wants the picture, not a rewritten committed layout
    file.
    """
    data_root = Path(data_root) if data_root is not None else REPO / "data"
    output_dir = Path(output_dir) if output_dir is not None else data_root

    view_w, view_h = _logical_resolution(data_root)
    _configure_strings(data_root)

    if not previews_only:
        output = {
            screen_id: build_screen_defaults(screen_id, view_w, view_h,
                                             data_root)
            for screen_id in SCREEN_IDS
        }
        output_path = output_dir / "ui" / "screen_defaults.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        schema_path = data_root / "schemas" / "screen_defaults.schema.json"
        data_io.write_validated(output, output_path, schema_path)

    write_previews(data_root, output_dir, view_w, view_h, overrides=overrides,
                   output_path=previews_out)
    return 0


def _parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--overrides", type=Path, default=None,
        help="JSON file of {screen_id: override_doc} to apply before "
             "recording the preview (the editor's unsaved-doc render)")
    parser.add_argument(
        "--previews-out", type=Path, default=None,
        help="write the preview draw list here instead of "
             "<output-dir>/ui/screen_previews.json")
    parser.add_argument(
        "--previews-only", action="store_true",
        help="skip the screen_defaults.json pass")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    _overrides = (data_io.load_json(args.overrides)
                  if args.overrides is not None else None)
    sys.exit(main(data_root=args.data_root, output_dir=args.output_dir,
                  overrides=_overrides, previews_out=args.previews_out,
                  previews_only=args.previews_only))
