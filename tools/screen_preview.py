"""Headless screen DRAW-LIST capture (UT-2) — what the editor's screen-mode
preview replays so a designer sees the real panel instead of placeholder boxes.

`editor/` may never import `game/` (design pillar 2), but `tools/` may. So the
faithful preview is produced HERE, by driving every screen's real `submit()`
against the canned mock state in `tools/screen_mocks.py`, and shipped to the
editor as data (`data/ui/screen_previews.json`, written by
`tools/export_ui_layouts.py`). The editor replays the serialized items through
the same `engine/render` backend the game uses, so ED-22's one-render-path
still holds.

**This module owns the ONE headless screen driver.**
`tools/tests/test_ui_skinning.py`'s golden parity pin captures through
`capture_screens` too, which is deliberate: the pin then guards the preview
generator as well — if this driver ever stops reproducing what the game draws,
the pin goes red before the editor starts lying to a designer.
"""
from engine.render import hud_item_from_json, hud_item_to_json
from tools.screen_mocks import (
    BP_VIEW_ORDER,
    GameOverState,
    LEVELUP_OPTIONS,
    OFF,
    build_bp_view,
    build_session,
    load_balances,
)


class RecordingRenderer:
    """Records every `submit_hud` call verbatim.

    Screens are HUD-only — none calls `submit`/`submit_overlay_*`/
    `submit_world_fill` except `BuildingUI`: `capture_building_panel_views`'s
    unlock/construct/preview/upgrade mocks DO populate `_highlight_tiles`
    (`screen_mocks.py build_bp_view` calls `_build_unlock`/`_build_construct`/
    `_build_upgrade` after setting `selected_tiles`), so `panel.submit()`
    really does call `submit_world_fill` (fix/depth-sorted-world-fills — see
    `engine/render/CLAUDE.md`) for those views. The three methods below exist
    so any screen that uses them records rather than crashes; none of their
    output is read back by this module.
    """

    def __init__(self):
        self.items = []
        self.overlay = []
        self.world_fills = []

    def submit_hud(self, item):
        self.items.append(item)

    def submit_overlay_lines(self, points, color, width=1, closed=False):
        self.overlay.append(("lines", points, color, width, closed))

    def submit_overlay_polys(self, points, rgba):
        self.overlay.append(("polys", points, rgba))

    def submit_world_fill(self, points, world_pos, layer="entities",
                          color=None, border=None, border_width=2, rank=0):
        # `rank` (VA-3) is accepted and dropped: this recorder feeds the
        # screen-preview capture, which is about WHAT is drawn, not the depth
        # order it is drawn in.
        self.world_fills.append(
            (points, world_pos, layer, color, border, border_width))


def _capture(fn):
    r = RecordingRenderer()
    fn(r)
    return r.items


# -- serialization -----------------------------------------------------------
#
# The round-trip itself lives in `engine/render/hud.py`, beside the dataclasses
# it describes: the EDITOR reads this file back and may never import `tools/`
# or `game/`, so writing the rule twice is exactly the drift we would not
# notice until a preview quietly stopped matching the game.

def serialize(items):
    return [hud_item_to_json(i) for i in items]


def deserialize(specs):
    return [hud_item_from_json(s) for s in specs]


# -- the driver --------------------------------------------------------------

def capture_screens(data_root, view_w, view_h, *, skinning=None,
                    balances=None, session=None):
    """`{screen_id: [HudItem, ...]}` for the twelve single-view screens.

    `skinning` is a `ScreenSkinning` (None = the disk-free `empty()` default,
    i.e. the OVERRIDE-FREE look every committed artifact records). `balances`
    and `session` are injectable so a caller that already built them does not
    pay twice.
    """
    from game.ui.add_name import AddNameScreen
    from game.ui.boss_cutscene import BossCutscene
    from game.ui.building_ui import BuildingUI
    from game.ui.cheat_menu import CheatMenu
    from game.ui.credits import CreditsScreen
    from game.ui.game_log import GameLog
    from game.ui.game_over import GameOverScreen
    from game.ui.hud import Hud
    from game.ui.levelup import LevelupWindow
    from game.ui.main_menu import MainMenu
    from game.ui.pause import PauseScreen
    from game.ui.settings import SessionSettings, SettingsScreen

    bal = balances if balances is not None else load_balances(data_root)
    ui, core = bal["ui"], bal["core"]
    kw = {} if skinning is None else {"skinning": skinning}
    if session is None:
        session = build_session(data_root, bal)

    mm = MainMenu(view_w, view_h, **kw)
    mm.update(0.0, *OFF, False)

    ps = PauseScreen(view_w, view_h, **kw)
    ps.update(0.0, *OFF, False)

    settings_state = SessionSettings.from_balance(ui)
    settings = SettingsScreen(view_w, view_h, settings_state, **kw)
    # What the HOST sets from `data/display.json` at boot, so the recorded
    # preview carries the "Boot: ..." note under SET DEFAULT. Pinned to the
    # mock's OWN mode, never read off disk — flipping the shipped boot mode
    # must not re-record every preview (the same determinism rule the pinned
    # `first_light` map follows).
    settings.saved_default = settings_state.display_mode
    settings.update(0.0, *OFF, False)

    credits = CreditsScreen(view_w, view_h, **kw)
    credits.update(0.0, *OFF, False)

    add_name = AddNameScreen(view_w, view_h, **kw)
    add_name.pool_count = 3
    add_name.update(0.0, *OFF, False)

    game_over = GameOverScreen(view_w, view_h, **kw)
    game_over.update(0.0, *OFF, False)

    levelup = LevelupWindow(view_w, view_h, **kw)
    levelup.open(LEVELUP_OPTIONS)
    levelup.update(0.0, *OFF, False)

    hud = Hud(view_w, view_h, **kw)
    hud_panel = BuildingUI(view_w, view_h, ui, **kw)
    hud.update(0.0, *OFF, session, hud_panel, False)

    panel = BuildingUI(view_w, view_h, ui, **kw)
    panel.hover(*OFF, False)
    panel.update(0.0)

    cheat = CheatMenu(view_w, view_h, **kw)
    cheat.update(0.0, *OFF, False)

    game_log = GameLog(**kw)
    game_log.post("Test message")
    game_log.update(0.0)

    boss = BossCutscene(view_w, view_h, core, **kw)
    boss.open(1, "win")
    boss.update(0.0, *OFF, False)

    return {
        "main_menu": _capture(lambda r: mm.submit(r, view_w, view_h)),
        "pause": _capture(lambda r: ps.submit(r, view_w, view_h)),
        "settings": _capture(lambda r: settings.submit(r, view_w, view_h)),
        "credits": _capture(lambda r: credits.submit(r, view_w, view_h)),
        "add_name": _capture(lambda r: add_name.submit(r, view_w, view_h)),
        "game_over": _capture(
            lambda r: game_over.submit(r, GameOverState(), view_w, view_h)),
        "levelup": _capture(lambda r: levelup.submit(r, view_w, view_h)),
        "hud": _capture(lambda r: hud.submit(
            r, session, view_w, view_h, hover_cost=hud_panel.hover_cost)),
        "building_panel": _capture(lambda r: panel.submit(r, session)),
        "cheat_menu": _capture(lambda r: cheat.submit(r, view_w, view_h)),
        "game_log": _capture(lambda r: game_log.submit(r, view_h)),
        "boss_cutscene": _capture(lambda r: boss.submit(r, view_w, view_h)),
    }


def capture_overlays(data_root, view_w, view_h, *, skinning=None,
                     balances=None):
    """`overlays`' two toggle pills. Separate from `capture_screens` because
    its `submit` takes a tilemap/scene/window rather than a view size, and
    because it is not one of the twelve the golden pin covers."""
    from game.ui.overlays import MapOverlays

    kw = {} if skinning is None else {"skinning": skinning}
    ov = MapOverlays(view_w, view_h, **kw)
    return _capture(lambda r: ov.submit_buttons(r))


def capture_building_panel_views(data_root, view_w, view_h, *, skinning=None,
                                 balances=None, session=None):
    """`{view: [HudItem, ...]}` for `building_panel`'s five per-mode views —
    each off the SAME `screen_mocks.build_bp_view` state the per-view defaults
    are recorded from."""
    bal = balances if balances is not None else load_balances(data_root)
    if session is None:
        session = build_session(data_root, bal)
    out = {}
    for view in BP_VIEW_ORDER:
        bp = build_bp_view(view, view_w, view_h, bal, session,
                           skinning=skinning, data_root=data_root)
        out[view] = _capture(lambda r, bp=bp: bp.submit(r, session))
    return out


def capture_all(data_root, view_w, view_h, *, skinning=None, balances=None):
    """Everything the generated `screen_previews.json` holds, as LIVE items:
    `{screen_id: {"items": [...]}}` plus `building_panel`'s
    `{"views": {view: {"items": [...]}}}`."""
    bal = balances if balances is not None else load_balances(data_root)
    session = build_session(data_root, bal)
    out = {sid: {"items": items} for sid, items in capture_screens(
        data_root, view_w, view_h, skinning=skinning, balances=bal,
        session=session).items()}
    out["overlays"] = {"items": capture_overlays(
        data_root, view_w, view_h, skinning=skinning, balances=bal)}
    out["building_panel"]["views"] = {
        view: {"items": items}
        for view, items in capture_building_panel_views(
            data_root, view_w, view_h, skinning=skinning, balances=bal,
            session=session).items()}
    return out


def serialize_all(captured):
    """`capture_all`'s live items -> the JSON document shape."""
    out = {}
    for screen_id, entry in captured.items():
        doc = {"items": serialize(entry["items"])}
        if "views" in entry:
            doc["views"] = {view: {"items": serialize(v["items"])}
                            for view, v in entry["views"].items()}
        out[screen_id] = doc
    return out
