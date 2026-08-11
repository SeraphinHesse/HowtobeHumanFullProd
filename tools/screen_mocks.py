"""The ONE canned mock state every headless screen artifact is built from.

Two generated files describe the same pictures from two angles —
`data/ui/screen_defaults.json` (each named widget's default rect/kind/label,
`tools/export_ui_layouts.py`) and `data/ui/screen_previews.json` (the full
draw list the editor replays, `tools/screen_preview.py`). If they were built
from two different mock states the editor's draggable boxes and the preview
behind them would disagree about where things are, which is worse than having
no preview at all. So the mock state lives here, once, and both importers
read it.

**Determinism** (both files are generated AND committed, D-3): fixed cursor
(`OFF`), `dt=0.0`, `anim_ms=0`, a seeded RNG, and a session over a PINNED map
(`first_light`) rather than whichever map is currently active — flipping the
active map must not churn a committed artifact.

Imports `game/` freely (that is what `tools/` is for, and why the editor
consumes these as DATA rather than importing a screen itself).
"""
import random
from pathlib import Path

from engine.core import Scene
from engine.physics import TileOccupancy

#: Off-screen cursor: every button reports "idle", so a hover state can never
#: leak into a committed artifact.
OFF = (-1000, -1000)

#: The map every session-dependent mock is built over — pinned by name, never
#: read from `active_map.json` (see the module docstring).
PINNED_MAP = "first_light"

#: Common mock state, quoted in every `mock_note`.
LOVE = 123
ROUND = 7
COMMON_NOTE = f"love={LOVE}, round={ROUND}"

#: A starts-unlocked building type (Stone Thrower) — a safe, always-buildable
#: pick for the building_panel's upgrade/preview mocks (`game/buildings/
#: CLAUDE.md`: "only defence/economic start unlocked").
MOCK_BUILDING_TYPE = "defence"

#: building_panel's five per-mode views, in game order.
BP_VIEW_ORDER = ("unlock", "construct", "upgrade", "base_info", "preview")

#: Per-view id membership — mirrors `building_ui.py`'s mode dispatch exactly.
#: The `preview` view's ids come off the `ConstructPreview` modal's own
#: disjoint `preview_*` namespace instead (see `BPView.ids`).
BP_VIEW_IDS = {
    "unlock": ("panel", "close_btn", "action_btn",
               "unlock_title", "unlock_hint", "unlock_blocked"),
    "construct": ("panel", "close_btn", "construct_title"),
    "upgrade": ("panel", "close_btn", "action_btn", "rename_dice_btn",
                "move_btn",
                "upgrade_title", "upgrade_name", "upgrade_tier_level",
                "dmg_dealt_label", "dmg_dealt_value",
                "dmg_taken_label", "dmg_taken_value",
                "died_last_round", "next_tier_header", "upgrade_hint"),
    "base_info": ("panel", "close_btn", "boss_btn", "boss_close_btn",
                  "base_info_title",
                  "info_lives_label", "info_lives_value",
                  "info_wave_label", "info_wave_value",
                  "info_enemies_killed_label", "info_enemies_killed_value",
                  "info_buildings_label", "info_buildings_value",
                  "info_base_income_label", "info_base_income_value"),
}

#: Id families a view owns by PREFIX rather than by listing, so growing the
#: family needs no edit here: `{view: (prefix, ...)}`.
#:   * `upgrade`/`stat_`  — UT-3's per-stat label/value pairs; a new stat key
#:     is covered automatically.
#:   * `construct`/`card_` — one construct card per building type; a new
#:     `/add-building` type is covered automatically.
BP_VIEW_ID_PREFIXES = {
    "upgrade": ("stat_",),
    "construct": ("card_",),
}

#: Back-compat aliases for the pre-generalization single-family rule.
BP_STAT_ID_VIEW = "upgrade"
BP_STAT_ID_PREFIX = "stat_"

#: Mock level-up options — both option shapes the modal knows how to draw,
#: and THREE of them because that is the roll's maximum and each slot is now
#: an individually overridable widget (`option_box_0..2`). Recording only two
#: would leave the third slot with no entry in `screen_defaults.json`, i.e.
#: un-selectable in the editor and un-overridable on disk.
LEVELUP_OPTIONS = [
    {"kind": "fallback", "title": "Card A", "cost": 5,
     "explanation": "does a thing", "prev_name": None, "sprite_key": None,
     "cost_label": "Cost", "display_cost": 5},
    {"kind": "tier", "title": "Card B", "cost": 0,
     "explanation": "tiered thing", "prev_name": "Old Name",
     "sprite_key": None, "cost_label": None, "tier_no": 2, "tier_max": 3},
    {"kind": "fallback", "title": "Card C", "cost": 12,
     "explanation": "a third thing", "prev_name": None, "sprite_key": None,
     "cost_label": "Cost", "display_cost": 12},
]


class GameOverState:
    """The three fields `GameOverScreen.submit` reads off a run state."""

    round_num = 4
    buildings_placed = 2
    enemies_killed = 9


def load_balances(data_root):
    from game.core import load_balance

    return {d: load_balance(data_root, d)
            for d in ("map", "core", "buildings", "enemies", "ui")}


def build_session(data_root, balances):
    """A real `Session` over the PINNED starter map, seeded and parked in
    BUILDING/GAMEPLAY — byte-identical on every call."""
    from engine import tilemap
    from game.buildings import BaseBuilding, attach_base
    from game.core import Session
    from game.core.phases import GamePhase, GameState
    from game.enemies import Spawner
    from game.map.tile_map import TileMap

    data_root = Path(data_root)
    doc = tilemap.load_map(data_root / "maps" / f"{PINNED_MAP}.json",
                           data_root / "schemas" / "map_file.schema.json")
    tm = TileMap(doc, balances["map"])
    scene = Scene()
    occ = TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, balances["core"]),
                scene, occ)
    session = Session.create(Spawner(), tm, balances["enemies"],
                             balances["core"], balances["buildings"],
                             rng=random.Random(3), occupancy=occ)
    session.state.state = GameState.GAMEPLAY
    session.state.phase = GamePhase.BUILDING
    return session


def _first_tile_in_state(tilemap, state):
    """The lowest `(row, col)` tile in `state` — a stable pick, so a mock
    never depends on dict/scan order."""
    best = None
    for t in tilemap.all_tiles():
        if t.state is not state:
            continue
        key = (t.row, t.col)
        if best is None or key < (best.row, best.col):
            best = t
    return best


class BPView:
    """One fully-driveable `building_panel` view: the object its DEFAULT ids
    are read off AND the object its PREVIEW draw list is recorded from."""

    def __init__(self, view, panel, preview, note):
        self.view = view
        self.panel = panel
        self.preview = preview
        self.note = note

    @property
    def ids(self):
        """`{name: (kind, widget)}` for this view.

        The `preview` view records the modal's own `preview_*` namespace; the
        four panel views record the subset of the panel's mode-independent
        ids that their mode actually draws, plus any prefix-ruled id family
        this view owns (`BP_VIEW_ID_PREFIXES`).
        """
        if self.preview is not None:
            return dict(self.preview.ids)
        names = list(BP_VIEW_IDS[self.view])
        for prefix in BP_VIEW_ID_PREFIXES.get(self.view, ()):
            names += sorted(n for n in self.panel.ids if n.startswith(prefix))
        return {name: self.panel.ids[name] for name in names}

    def submit(self, renderer, session):
        """Draw the whole picture the player would see.

        For the `preview` view that is the construct panel WITH its modal on
        top — `BuildingUI.submit` draws `self.preview` last, exactly as the
        game does — not the bare modal the ids describe.
        """
        self.panel.submit(renderer, session)


def _unlock_every_type(session):
    """Mark every RESEARCH building type unlocked on the mock session.

    `_build_construct` only emits a card for a type `buildable()` accepts, so
    a fresh session would record only the handful unlocked at round 1 and the
    rest would have no `screen_defaults.json` entry — i.e. be invisible to the
    editor and un-overridable on disk. Sweeps the RESEARCH table rather than
    naming types, so a new `/add-building` type is covered with no edit here
    (the same argument `Session.cheat_unlock_all` makes); it writes the state
    directly rather than calling that cheat, which is gated on GameState and
    would emit a debug event.
    """
    from game.buildings.research import RESEARCH

    state = session.state
    for btype in RESEARCH:
        state.unlocked_buildings[btype] = True
        # Tier 1 only — `buildable()` needs nothing more, and researching
        # every tier would change the cards' PRICES (they quote the highest
        # unlocked tier), which is recorded geometry's neighbour in this file.
        state.tiers_unlocked[btype] = max(
            1, state.tiers_unlocked.get(btype, 0))


def build_bp_view(view, view_w, view_h, balances, session, skinning=None):
    """Construct ONE `building_panel` view's mock. See `BP_VIEW_ORDER`."""
    from game.buildings.registry import build_cost, create
    from game.map.tiles import TileState
    from game.ui.building_ui import BuildingUI, ConstructPreview

    ui = balances["ui"]
    buildings = balances["buildings"]
    tm = session.tilemap
    panel = BuildingUI(view_w, view_h, ui, skinning=skinning)
    panel._session = session
    panel._buildings_balance = buildings
    preview = None

    if view == "unlock":
        tile = _first_tile_in_state(tm, TileState.COMBAT)
        panel.mode, panel.tile = "unlock", tile
        panel.selected_tiles = [tile]
        panel._build_unlock(session)
        note = (f"{COMMON_NOTE}; the lowest-(row,col) COMBAT tile of the "
                f"{PINNED_MAP!r} map, its real 2x2 chunk and unlock cost")
    elif view in ("construct", "preview"):
        tile = _first_tile_in_state(tm, TileState.BUILDABLE)
        panel.mode, panel.tile = "construct", tile
        panel.selected_tiles = [tile]
        _unlock_every_type(session)
        panel._build_construct()
        note = (f"{COMMON_NOTE}; the lowest-(row,col) BUILDABLE tile of the "
                f"{PINNED_MAP!r} map, with EVERY building type unlocked so "
                "each construct card (`card_<building_type>`) is recorded — "
                "the count is dynamic in game, the ids are not")
        if view == "preview":
            tier_idx = 0
            cost = build_cost(MOCK_BUILDING_TYPE, buildings, tier_idx)
            preview = ConstructPreview(
                MOCK_BUILDING_TYPE, cost, buildings, ui, view_w, view_h,
                count=1, tier_idx=tier_idx, skinning=skinning)
            panel.preview = preview
            note = (f"{COMMON_NOTE}; ConstructPreview({MOCK_BUILDING_TYPE!r}) "
                    "modal open over the construct panel, count=1, tier_idx=0 "
                    "(preview_cancel_btn present iff "
                    "ui.Timing.construct_show_cancel)")
    elif view == "upgrade":
        tile = _first_tile_in_state(tm, TileState.BUILDABLE)
        building = create(MOCK_BUILDING_TYPE, tile.col, tile.row, buildings)
        panel.mode, panel.tile = "upgrade", tile
        panel._selected = building
        panel.selected_tiles = [tile]
        panel._build_upgrade()
        note = (f"{COMMON_NOTE}; a freshly created {MOCK_BUILDING_TYPE!r} "
                "building (tier 0, level 1) — upgrade_gate resolves "
                "'in_tier' deterministically")
    elif view == "base_info":
        tile = tm.get(tm.base_col, tm.base_row)
        panel.mode, panel.tile = "base_info", tile
        panel.selected_tiles = [tile]
        note = f"{COMMON_NOTE}; the base tile (the hole)"
    else:
        raise KeyError(f"screen_mocks: unknown building_panel view {view!r}")

    panel.hover(*OFF, False)
    return BPView(view, panel, preview, note)
