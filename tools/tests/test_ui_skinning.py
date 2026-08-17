"""Golden parity pin + skinning.apply() contract (10L-B phase B2).

``test_all_screens_parity`` is the phase's golden pin: every one of the 12
live screens, with NO ``data/ui/screens/`` overrides, must emit the exact
HUD-primitive stream it emits today. The baseline below was captured from the
screens BEFORE any B2 production edit landed (no ``ids``/``skinning.apply()``
wiring existed yet) — see ``docs/briefs/phase-B2-ids-skinning.md`` §2.7 and
the plan's risk note ("record first, then edit"). If this test ever needs to
change, the first question is "did a screen's DEFAULT geometry/text change on
purpose for an unrelated reason", never "relax the pin".

Headless, no pygame: every HUD primitive (``HudRect``/``HudText``/
``HudSprite``/``HudLines``) is a pure screen-space dataclass, and ``game/ui``
is pygame-free by construction (TestPurity). Real ``Session``/``TileMap`` over
the shipped starter map + a plain recording stand-in renderer — the
``test_hud_panel.py`` / ``test_10j_qol.py`` fixture style.
"""
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy

from engine import data_io, tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from engine.render import HudLines, HudRect, HudSprite, HudText
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui import skinning as skinning_module
from game.ui.skinning import ScreenSkinning
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

VIEW_W, VIEW_H = 640, 360
OFF = (-1000, -1000)  # off-screen cursor: every button reports "idle"

MAP = FIXTURE_DATA / "maps" / "first_light.json"
MAP_SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
MAP_BAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
ENEM = load_balance(FIXTURE_DATA, "enemies")
CORE = load_balance(FIXTURE_DATA, "core")
UI = load_balance(FIXTURE_DATA, "ui")


class RecordingRenderer:
    """Records every ``submit_hud`` call verbatim (screens never call
    ``submit``/``submit_overlay_*`` — matches ``test_hud_panel.py``'s
    stand-in)."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


def _session():
    """A real ``Session`` over the shipped starter map, seeded and parked in
    BUILDING/GAMEPLAY — identical setup on every call (T-3 determinism)."""
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    tm = TileMap(doc, MAP_BAL)
    scene = Scene()
    occ = TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD,
                             rng=random.Random(3), occupancy=occ)
    session.state.state = GameState.GAMEPLAY
    session.state.phase = GamePhase.BUILDING
    return session



def _capture(fn):
    r = RecordingRenderer()
    fn(r)
    return r.items


def _screen_captures():
    """``{screen_id: recorded_items}`` for all 12 screens.

    Delegates to ``tools/screen_preview.py``'s driver — the SAME code that
    records ``data/ui/screen_previews.json`` for the editor's screen-mode
    preview (UT-2). That is deliberate: this golden pin then guards the
    preview generator too, so a driver that stops reproducing what the game
    draws turns the pin red before the editor starts lying to a designer.
    """
    from tools import screen_preview

    return screen_preview.capture_screens(FIXTURE_DATA, VIEW_W, VIEW_H)



#: THE golden baseline — captured from the pre-B2 code (no ``ids``/``apply``
#: wiring, no ``data/ui/screens`` consumption at all existed). Do not
#: hand-tune; a screen's DEFAULT geometry/text changing for reasons unrelated
#: to B2 is the only legitimate reason to regenerate an entry, and it should
#: be regenerated from the base commit, not guessed.
#: Regenerated ONCE since, for exactly that reason (debug-mode-telemetry Phase
#: 5): ``main_menu`` gained the PLAY DEBUG row + its gear and ``cheat_menu``
#: gained the Debug Log row (and 30px of panel to hold it), so both screens'
#: DEFAULT geometry moved on purpose. Every other screen's entry is untouched,
#: which is what says the change was contained.
#: Regenerated a SECOND time (boss-upgrade rework): ``boss_cutscene``'s two
#: option DESCS are new copy for the redesigned set-1 bonuses (and now quote
#: live ``core.json BossBonuses`` magnitudes). Only those four HudText strings
#: moved — every rect/pos/colour in the entry is untouched, which is what says
#: the change was contained.
#: Regenerated a THIRD time (player-identity): ``main_menu`` gained the
#: HIGHSCORES row, so every row below it in the stack shifts down one slot
#: (52 + 14 px) and its DEFAULT geometry moved on purpose. Only ``main_menu``
#: changed — every other screen's entry is byte-identical, which is what says
#: the change was contained.
#: Regenerated a FOURTH time (drag-selection toggle): ``hud`` gained the DRAG
#: SEL toggle button on its own row under the speed row, so three primitives
#: are APPENDED to that entry. Nothing already in it moved, and every other
#: screen's entry is byte-identical — which is what says the change was
#: contained.
#: Regenerated a FIFTH time (persist-boot-display-mode): ``SessionSettings``'s
#: shipped default flipped from ``windowed`` to ``fullscreen`` on purpose, to
#: match ``data/display.json``, so the settings screen's DEFAULT value row now
#: reads FULLSCREEN. Exactly ONE HudText changed — same item count, same rects,
#: same colours, every other screen byte-identical — which is what says the
#: change was contained. Note the new SET DEFAULT button does NOT appear here:
#: the capture builds the screen bare, and ``saved_default`` is then ``None``,
#: which by design draws no line.
#: Regenerated an EIGHTH time (editable buy options): the level-up option
#: boxes became individually overridable widgets (`option_box_0..2`), and
#: `tools/screen_mocks.LEVELUP_OPTIONS` grew from two mock cards to THREE so
#: every option SLOT gets recorded — the roll's maximum. So `levelup` is the
#: only entry that moved, and it moved because its INPUT changed, not its
#: code: the two existing cards re-centre (a 3-wide row is centred
#: differently than a 2-wide one) and a third card's five primitives are
#: appended. **Containment was measured, not assumed**: capturing with
#: `LEVELUP_OPTIONS` truncated back to its original two reproduces THIS
#: file's previous baseline byte-for-byte on every screen, `levelup` and
#: `hud` included — i.e. the option-box holders, the id'd construct cards,
#: the `button_kwargs` forwarding and `hud.round_label`'s align moving from
#: its call site onto its holder are all rendering no-ops.
#: Regenerated a SIXTH time (UR-2: the logical surface flipped 1280x720 ->
#: 640x360, so EVERY screen's default geometry moved on purpose). This is the
#: one regeneration where "only one screen changed" is NOT the containment
#: signal — the whole surface halved, so every rect and every text anchor in
#: every entry moved, and an entry that did NOT move would be the suspicious
#: one. What IS pinned: the font presets in ``data/ui/fonts.json`` were
#: deliberately left alone (they were always 640-scale), so every ``font_key``
#: here is byte-identical, as is every colour and alpha. Regenerated
#: mechanically from ``_screen_captures()`` on the converted tree — never
#: hand-tuned, never relaxed.
#: Regenerated a SEVENTH time (UR-5: the eyeball/polish pass over UR-2). Four
#: entries moved, each for a measured reason: ``hud`` (the income/lives/tiles
#: row step is font-scale and had been halved to 8px against a 13px line
#: height, so the three rows overlapped — and the speed-button row now derives
#: from the readout pill's bottom instead of a literal), ``levelup`` (the
#: option box was smaller than its own font-sized contents), ``cheat_menu``
#: (rows widened to hold "Unlock All Tech"; close/GO raised over the 12px
#: click-target floor), ``main_menu`` (the SET gear widened to hold its label).
#: The other eight entries are byte-identical, which is what says the change
#: was contained. Regenerated mechanically from ``_screen_captures()``.
#: Regenerated a NINTH time (bottom-right phase readout): ``hud``'s
#: ``phase_label`` moved from the bottom-LEFT corner into the bottom-RIGHT
#: cluster, directly above the round label, and its copy became the two-state
#: "Building Phase"/"Defending Phase" instead of the six-way ``hud.phase.*``
#: string-table lookup. Exactly ONE primitive in the entry changed (text +
#: pos, same index) — nothing else moved, and every other screen's entry is
#: byte-identical.
#: Regenerated a TENTH time (shipped-font label fit): twelve static button
#: labels overhung their buttons under the font the game ACTUALLY boots
#: (``data/ui/active_font.json`` -> ``pixel_emulator``), which is wider per
#: glyph than the ``SysFont("monospace")`` metrics every pixel constant in
#: ``game/ui`` was authored against. Six entries moved, and ONLY as copy or
#: ``font_key``: ``add_name`` (ADD NAME -> ADD), ``cheat_menu`` (Unlock All
#: Tech -> Unlock Tech, Go to Round -> Round), ``game_over`` (RETURN TO MENU
#: -> MAIN MENU), ``hud`` (DRAG SEL -> DRAG; END TURN lg -> md, which shifts
#: its centred baseline 1px), ``main_menu`` (the SET gear lg -> md, same 1px
#: shift), ``pause`` (QUIT TO MENU -> MAIN MENU). **Not one rect in this
#: baseline changed**, which is what says the fix was copy and per-widget
#: font, never layout. (``overlays``'s TIERS pill DID narrow 76 -> 41, but
#: that screen is not in this capture — see ``data/ui/screen_defaults.json``.)
#: The measurement itself now lives in
#: ``test_ui_min_targets.py``, which installs the shipped face for its own
#: module so this can never regress invisibly again; THIS file still captures
#: under the fallback face, which is why its ``pos`` values are unchanged.
#: Regenerated an ELEVENTH time (hide-speed-buttons-build-mode): the 1x/1.5x/
#: 2x speed buttons are now hidden outright in ``GamePhase.BUILDING`` (the
#: mock session's default phase, ``tools/screen_mocks.py``), since they have
#: nothing to control there — ``main.py``'s ``sim_dt`` only ever scales the
#: ENEMY phase, so build mode always played at 1x regardless of the selected
#: speed even before this change. The ten speed-button primitives are
#: DROPPED from ``hud``'s entry; nothing else moved (the DRAG SEL row's rect
#: is unchanged — its position was never derived from the speed row's
#: runtime visibility, only from its default layout) and every other
#: screen's entry is byte-identical.
#: Regenerated a TWELFTH time (boss-round indicator icon): ``hud`` gained a
#: new BUILDING-phase-only icon immediately left of Pause (a
#: `ui_icon_boss_next`/`ui_icon_boss_next_off` HudSprite, tinted while
#: neither slot carries real art), so ONE primitive is INSERTED into that
#: entry between END TURN and Pause — nothing already there moved, and every
#: other screen's entry is byte-identical, which is what says the change was
#: contained.
#: Regenerated a THIRTEENTH time (feature: rebindable hotkeys): ``settings``
#: gained a CONTROLS button (opens the new Controls/rebind screen) beside
#: BACK. Three primitives are APPENDED to that entry; nothing already in it
#: moved, and every other screen's entry is byte-identical — which is what
#: says the change was contained. This entry and the TWELFTH above touch
#: disjoint screens (``settings`` vs ``hud``), so the merge of the two
#: features is the union of their two contained additions, not a
#: re-baseline: both are present below, unmodified.

_BASELINE = {
    "main_menu": [
        HudRect(rect=(0, 0, 640, 360), color=(18, 30, 20), border_radius=0, width=0),
        HudSprite(slot_key='main_menu_bg', dest=(0, 0), size=(640, 360), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='HOW TO BE HUMAN', pos=(320, 105), font_key='xxl', color=(168, 105, 222), align='center'),
        HudText(text='defend the munckins', pos=(320, 125), font_key='md', color=(168, 105, 222), align='center'),
        HudRect(rect=(240, 150, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 150, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='START NEW GAME', pos=(320, 155), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 180, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 180, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='PLAY DEBUG', pos=(320, 185), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 210, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 210, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ADD A NAME', pos=(320, 215), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 240, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 240, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='HIGHSCORES', pos=(320, 245), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 270, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 270, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='SETTINGS', pos=(320, 275), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 300, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 300, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='CREDITS', pos=(320, 305), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(240, 330, 160, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(240, 330, 160, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='QUIT', pos=(320, 335), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(405, 180, 30, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(405, 180, 30, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='SET', pos=(420, 186), font_key='md', color=(235, 225, 195), align='center'),
    ],
    "pause": [
        HudRect(rect=(0, 0, 640, 360), color=(0, 0, 0, 150), border_radius=0, width=0),
        HudRect(rect=(245, 100, 150, 160), color=(24, 20, 40), border_radius=6, width=0),
        HudRect(rect=(245, 100, 150, 160), color=(80, 65, 120), border_radius=6, width=2),
        HudText(text='PAUSED', pos=(320, 116), font_key='xl', color=(255, 200, 50), align='center'),
        HudRect(rect=(260, 142, 120, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(260, 142, 120, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='RESUME', pos=(320, 146), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(260, 171, 120, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(260, 171, 120, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='SETTINGS', pos=(320, 175), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(260, 200, 120, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(260, 200, 120, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='MAIN MENU', pos=(320, 204), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(260, 229, 120, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(260, 229, 120, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='QUIT GAME', pos=(320, 233), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "settings": [
        HudRect(rect=(0, 0, 640, 360), color=(12, 20, 14), border_radius=0, width=0),
        HudText(text='SETTINGS', pos=(320, 90), font_key='xxl', color=(255, 200, 50), align='center'),
        HudText(text='Display Mode', pos=(320, 108), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='FULLSCREEN', pos=(320, 125), font_key='lg', color=(255, 200, 50), align='center'),
        HudRect(rect=(245, 122, 20, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(245, 122, 20, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='<', pos=(255, 124), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(375, 122, 20, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(375, 122, 20, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='>', pos=(385, 124), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Income Floaters', pos=(245, 160), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(350, 156, 45, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(350, 156, 45, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(372, 158), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Background Art', pos=(245, 188), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(350, 184, 45, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(350, 184, 45, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(372, 186), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Gore', pos=(245, 216), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(350, 212, 45, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(350, 212, 45, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(372, 214), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Master Audio', pos=(245, 237), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(275, 249, 90, 6), color=(80, 65, 120), border_radius=0, width=0),
        HudRect(rect=(275, 249, 72, 6), color=(75, 60, 115), border_radius=0, width=0),
        HudText(text='(no audio yet)', pos=(320, 259), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(270, 279, 100, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(270, 279, 100, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(320, 283), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(380, 279, 90, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(380, 279, 90, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='CONTROLS', pos=(425, 285), font_key='sm', color=(235, 225, 195), align='center'),
    ],
    "credits": [
        HudRect(rect=(0, 0, 640, 360), color=(12, 20, 14), border_radius=0, width=0),
        HudText(text='CREDITS', pos=(320, 35), font_key='xxl', color=(255, 200, 50), align='center'),
        HudText(text='Producer', pos=(300, 75), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Seraphin Hesse', pos=(340, 75), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Design Lead', pos=(300, 90), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Fabian Krüger', pos=(340, 90), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Art Lead', pos=(300, 105), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Hendrik Wagner', pos=(340, 105), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programming Lead', pos=(300, 120), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Johann Heinrich', pos=(340, 120), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='UI Lead/2D Artist', pos=(300, 142), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Alicia Jaison', pos=(340, 142), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='2D Artist', pos=(300, 157), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Varvara Kozačuk', pos=(340, 157), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='2D Artist', pos=(300, 172), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Jakob Dahlkar', pos=(340, 172), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Designer', pos=(300, 194), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Joel Hoch', pos=(340, 194), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Designer', pos=(300, 209), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Benjamin Riese', pos=(340, 209), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programmer', pos=(300, 231), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Pantelis Charalambous', pos=(340, 231), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programmer', pos=(300, 246), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Alfons Kavalic', pos=(340, 246), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(270, 315, 100, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(270, 315, 100, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(320, 319), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "add_name": [
        HudRect(rect=(0, 0, 640, 360), color=(12, 20, 14), border_radius=0, width=0),
        HudRect(rect=(205, 115, 230, 130), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(205, 115, 230, 130), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='ADD A NAME', pos=(320, 125), font_key='xl', color=(255, 200, 50), align='center'),
        HudText(text='Appears on the building-naming dice button.', pos=(320, 146), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(217, 169, 206, 18), color=(40, 32, 58), border_radius=0, width=0),
        HudRect(rect=(217, 169, 206, 18), color=(255, 200, 50), border_radius=0, width=1),
        HudText(text='_', pos=(221, 173), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Names in pool: 3', pos=(217, 206), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(217, 217, 80, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(217, 217, 80, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ADD', pos=(257, 219), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(358, 217, 65, 20), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(358, 217, 65, 20), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(390, 219), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "game_over": [
        HudRect(rect=(0, 0, 640, 360), color=(10, 5, 15), border_radius=0, width=0),
        HudText(text='THE COLONY WAS DESTROYED', pos=(320, 120), font_key='xxl', color=(210, 55, 55), align='center'),
        HudText(text='Round Reached: 4', pos=(320, 165), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Buildings Placed: 2', pos=(320, 179), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Enemies Killed: 9', pos=(320, 193), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(260, 235, 120, 23), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(260, 235, 120, 23), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='MAIN MENU', pos=(320, 239), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "levelup": [
        HudRect(rect=(0, 0, 640, 360), color=(0, 0, 0, 185), border_radius=0, width=0),
        HudText(text='CHOOSE YOUR REWARD', pos=(320, 65), font_key='xxl', color=(255, 200, 50), align='center'),
        HudRect(rect=(121, 103, 130, 154), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(121, 103, 130, 154), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='Card A', pos=(186, 108), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Cost  5', pos=(186, 162), font_key='sm', color=(255, 200, 50), align='center'),
        HudText(text='does a thing', pos=(186, 175), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(255, 103, 130, 154), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(255, 103, 130, 154), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='Old Name', pos=(320, 108), font_key='sm', color=(150, 140, 120), align='center'),
        HudLines(points=((318, 124), (320, 121), (322, 124)), color=(80, 210, 80), width=2, closed=False),
        HudText(text='Card B', pos=(320, 126), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='tiered thing', pos=(320, 193), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='Tier 2 of 3', pos=(320, 243), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(389, 103, 130, 154), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(389, 103, 130, 154), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='Card C', pos=(454, 108), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Cost  12', pos=(454, 162), font_key='sm', color=(255, 200, 50), align='center'),
        HudText(text='a third thing', pos=(454, 175), font_key='sm', color=(150, 140, 120), align='center'),
    ],
    "hud": [
        HudRect(rect=(6, 6, 95, 17), color=(40, 32, 58), border_radius=4, width=0),
        HudRect(rect=(6, 6, 95, 17), color=(150, 135, 185), border_radius=4, width=1),
        HudSprite(slot_key='ui_icon_love', dest=(9, 10), size=(9, 9), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='25', pos=(20, 9), font_key='xl', color=(255, 200, 50), align='left'),
        HudText(text='LVL 1', pos=(107, 6), font_key='hud_lvl', color=(255, 200, 50), align='left'),
        HudSprite(slot_key='ui_icon_xp', dest=(107, 21), size=(9, 9), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudRect(rect=(118, 23, 55, 4), color=(48, 34, 66), border_radius=0, width=0),
        HudRect(rect=(118, 23, 55, 4), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='0/50', pos=(118, 28), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(6, 23, 95, 49), color=(40, 32, 58), border_radius=4, width=0),
        HudRect(rect=(6, 23, 95, 49), color=(150, 135, 185), border_radius=4, width=1),
        HudText(text='+5/round', pos=(8, 25), font_key='sm', color=(214, 96, 136), align='left'),
        HudSprite(slot_key='ui_icon_lives', dest=(8, 41), size=(9, 9), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='LIVES 3', pos=(19, 41), font_key='md', color=(200, 55, 55), align='left'),
        HudText(text='0/4 tiles', pos=(8, 57), font_key='md', color=(150, 140, 120), align='left'),
        HudText(text='Building Phase', pos=(552, 287), font_key='hud_phase', color=(150, 140, 120), align='left'),
        HudText(text='ROUND 1', pos=(592, 307), font_key='md', color=(150, 140, 120), align='center'),
        HudRect(rect=(552, 320, 80, 1), color=(80, 65, 120), border_radius=0, width=0),
        HudRect(rect=(552, 322, 80, 30), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(552, 322, 80, 30), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='END TURN', pos=(592, 330), font_key='md', color=(235, 225, 195), align='center'),
        HudSprite(slot_key='ui_icon_boss_next_off', dest=(568, 6), size=(15, 15), tint=(150, 150, 150, 255), flip=False, animation='idle', anim_time_ms=0),
        HudRect(rect=(587, 6, 45, 15), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(587, 6, 45, 15), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='PAUSE', pos=(609, 7), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(6, 93, 45, 14), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(6, 93, 45, 14), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='DRAG', pos=(28, 94), font_key='sm', color=(235, 225, 195), align='center'),
    ],
    "building_panel": [
    ],
    "cheat_menu": [
        HudRect(rect=(0, 0, 640, 360), color=(0, 0, 0, 150), border_radius=0, width=0),
        HudRect(rect=(258, 108, 124, 144), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(258, 108, 124, 144), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='CHEATS', pos=(320, 112), font_key='lg', color=(255, 200, 50), align='center'),
        HudRect(rect=(365, 111, 14, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(365, 111, 14, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='X', pos=(372, 111), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 124, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 124, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='+10 Love', pos=(320, 124), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 139, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 139, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Skip Round', pos=(320, 139), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 154, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 154, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='LEVEL UP', pos=(320, 154), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 169, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 169, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Infinite Money', pos=(320, 169), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 184, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 184, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Unlock Tech', pos=(320, 184), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 199, 114, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(263, 199, 114, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Debug Log', pos=(320, 199), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(263, 216, 114, 1), color=(80, 65, 120), border_radius=0, width=0),
        HudText(text='Jump to round:', pos=(263, 218), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(263, 227, 48, 13), color=(40, 32, 58), border_radius=0, width=0),
        HudRect(rect=(263, 227, 48, 13), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='round', pos=(266, 229), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(314, 227, 63, 13), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(314, 227, 63, 13), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Round', pos=(345, 228), font_key='sm', color=(235, 225, 195), align='center'),
    ],
    "game_log": [
        HudText(text='Test message', pos=(4, 344), font_key='sm', color=(220, 200, 155, 255), align='left'),
    ],
    "boss_cutscene": [
        HudRect(rect=(0, 0, 640, 360), color=(0, 0, 0, 210), border_radius=0, width=0),
        HudText(text='Cutscene: Round Won :)', pos=(320, 101), font_key='xxl', color=(100, 220, 100), align='center'),
        HudText(text='How will we react?', pos=(320, 139), font_key='md', color=(150, 140, 120), align='center'),
        HudRect(rect=(225, 158, 90, 65), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(225, 158, 90, 65), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='WinA', pos=(270, 164), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Per unbuilt tile, buildings', pos=(270, 184), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='deal +1 extra damage', pos=(270, 197), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(325, 158, 90, 65), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(325, 158, 90, 65), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='WinB', pos=(370, 164), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Per building placed, buildings', pos=(370, 184), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='deal +1 extra damage', pos=(370, 197), font_key='sm', color=(150, 140, 120), align='center'),
    ],
}


class TestGoldenParity(unittest.TestCase):
    """The golden parity pin (§1.1). MANDATORY per the phase brief."""

    def test_all_screens_parity(self):
        captured = _screen_captures()
        self.assertEqual(sorted(captured), sorted(_BASELINE))
        for screen_id, items in captured.items():
            self.assertEqual(items, _BASELINE[screen_id],
                             f"{screen_id} parity failed")


class ScreenSkinningCase(unittest.TestCase):
    """A ``ScreenSkinning`` over a tempdir copy of the pinned fixture — never
    the live repo (T-3/data guard).

    The fixture USED to ship no ``data/ui/screens/`` and no
    ``screen_defaults.json``, so the tests below that exercise the ABSENCE
    (E-37 degrade) paths simply relied on that. It ships both now — the
    snapshot is re-mirrored from live ``data/`` by ``fixture_data.refresh()``
    — and those tests started failing for reasons unconnected to the code
    they cover. That is exactly the "never assert against fixture state you
    did not pin" rule (``editor/CLAUDE.md``, the 18 permanently-red tests):
    a test that needs a file absent must REMOVE it, not assume it. Hence the
    two helpers below."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = fixture_copy(self._tmp.name)

    def drop_screen_defaults(self):
        """Guarantee ``data/ui/screen_defaults.json`` is absent."""
        path = self.data_dir / "ui" / "screen_defaults.json"
        if path.exists():
            path.unlink()

    def drop_screen_overrides(self):
        """Guarantee ``data/ui/screens/`` is absent."""
        screens = self.data_dir / "ui" / "screens"
        if screens.exists():
            shutil.rmtree(screens)


class TestScreenSkinningLoad(ScreenSkinningCase):
    def test_missing_screens_directory_is_graceful(self):
        """No data/ui/screens/ at all -> empty overrides, never a crash
        (§1.3 E-37 degrade). The absence is PINNED, not assumed."""
        self.drop_screen_overrides()
        skinning = ScreenSkinning(self.data_dir)
        self.assertEqual(skinning._overrides, {})

    def test_absent_defaults_file_is_none(self):
        """No data/ui/screen_defaults.json -> `_defaults` is None (§1.4).
        The absence is PINNED, not assumed."""
        self.drop_screen_defaults()
        skinning = ScreenSkinning(self.data_dir)
        self.assertIsNone(skinning._defaults)

    def test_skinning_loads_once(self):
        """apply() never re-reads disk — pinned by patching the loader AFTER
        construction and calling apply() many times (the cheat_menu
        every-frame ``layout()`` -> ``apply()`` case)."""
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {"test_widget": {"rect": [1, 2, 3, 4]}}}
        widget = SimpleNamespace(rect=(0, 0, 1, 1))
        with mock.patch.object(
                skinning_module.data_io, "load_validated",
                side_effect=AssertionError("apply() re-read disk")):
            for _ in range(50):
                skinning.apply("test_screen", {"test_widget": ("button", widget)})
        self.assertEqual(widget.rect, (1, 2, 3, 4))


def _repo_schemas_dir():
    """The repo's real ``data/schemas/`` — a READ-ONLY source for the one
    test that exercises the genuine on-disk load-and-validate path (review
    LOW finding). Never compared against, never written to; ``tools/tests/
    fixtures/data/schemas`` is missing both ``ui_screen.schema.json`` and
    ``screen_defaults.schema.json`` (stale since B1 — reported upward, not
    fixed here, since refreshing that snapshot is outside this phase's file
    scope), so copying the two live schema files is the only way to run the
    real loader against the real schema shape it validates against in
    production."""
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root.joinpath("data").joinpath("schemas")


class TestRealFileLoadPath(unittest.TestCase):
    """LOW finding: every other test here injects into ``_overrides``
    directly, never exercising ``load_screen_overrides``/
    ``load_screen_defaults`` themselves (the actual ``data_io.load_validated``
    call against a real file). This builds a throwaway tempdir with REAL
    schema files (byte-copied, read-only, from the repo) plus a real
    ``ui/screens/*.json`` / ``ui/screen_defaults.json`` written through
    ``data_io.write_validated``, so the genuine load path runs at least
    once end to end."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        schemas_dir = self.data_dir / "schemas"
        schemas_dir.mkdir(parents=True)
        src = _repo_schemas_dir()
        for name in ("ui_screen.schema.json", "screen_defaults.schema.json"):
            (schemas_dir / name).write_bytes((src / name).read_bytes())

    def test_loads_and_applies_a_real_override_file(self):
        screens_dir = self.data_dir / "ui" / "screens"
        screens_dir.mkdir(parents=True)
        doc = {"widgets": {"btn_new_game": {"rect": [40, 100, 200, 52]}}}
        data_io.write_validated(doc, screens_dir / "main_menu.json",
                               self.data_dir / "schemas" / "ui_screen.schema.json")
        skinning = ScreenSkinning(self.data_dir)
        widget = SimpleNamespace(rect=(0, 0, 1, 1))
        skinning.apply("main_menu", {"btn_new_game": ("button", widget)})
        self.assertEqual(widget.rect, (40, 100, 200, 52))

    def test_a_real_screen_defaults_file_drives_validation(self):
        (self.data_dir / "ui").mkdir(parents=True, exist_ok=True)
        defaults_doc = {"main_menu": {"widgets": {"btn_new_game": {
            "rect": [0, 0, 1, 1], "kind": "button", "label": "btn_new_game"}}}}
        data_io.write_validated(
            defaults_doc, self.data_dir / "ui" / "screen_defaults.json",
            self.data_dir / "schemas" / "screen_defaults.schema.json")
        screens_dir = self.data_dir / "ui" / "screens"
        screens_dir.mkdir(parents=True)
        bad_doc = {"widgets": {"totally_unknown_id": {"rect": [0, 0, 1, 1]}}}
        data_io.write_validated(bad_doc, screens_dir / "main_menu.json",
                               self.data_dir / "schemas" / "ui_screen.schema.json")
        skinning = ScreenSkinning(self.data_dir)
        self.assertIsNotNone(skinning._defaults)
        widget = SimpleNamespace(rect=(0, 0, 1, 1))
        with self.assertRaises(ValueError):
            skinning.apply("main_menu", {"totally_unknown_id": ("button", widget)})


class TestApplyMutatesWidgets(ScreenSkinningCase):
    def test_apply_mutates_rect(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {"test_widget": {"rect": [10, 20, 80, 90]}}}
        widget = SimpleNamespace(rect=(0, 0, 100, 100))
        skinning.apply("test_screen", {"test_widget": ("button", widget)})
        self.assertEqual(widget.rect, (10, 20, 80, 90))

    def test_apply_mutates_label(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {"btn": {"label": "PRESS ME"}}}
        widget = SimpleNamespace(label="old")
        skinning.apply("test_screen", {"btn": ("button", widget)})
        self.assertEqual(widget.label, "PRESS ME")

    def test_apply_mutates_skin(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "widgets": {"btn": {"skin": "ui_button"}}}
        widget = SimpleNamespace(skin=None)
        skinning.apply("test_screen", {"btn": ("button", widget)})
        self.assertEqual(widget.skin, "ui_button")

    def test_apply_is_a_noop_with_no_override(self):
        # PIN the "no override file" precondition — the fixture ships real
        # screen JSONs now, and main_menu's carries a skin/defaults block.
        self.drop_screen_overrides()
        skinning = ScreenSkinning(self.data_dir)
        widget = SimpleNamespace(rect=(1, 2, 3, 4), label="stock")
        skinning.apply("main_menu", {"btn_new_game": ("button", widget)})
        self.assertEqual(widget.rect, (1, 2, 3, 4))
        self.assertEqual(widget.label, "stock")


class TestIdValidation(ScreenSkinningCase):
    def test_unknown_id_fails_loud_when_defaults_present(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._defaults = {"test_screen": {"widgets": {"known_id": {}}}}
        skinning._overrides["test_screen"] = {
            "widgets": {"unknown_id": {"rect": [0, 0, 100, 100]}}}
        widget = SimpleNamespace(rect=(0, 0, 1, 1))
        with self.assertRaises(ValueError) as cm:
            skinning.apply("test_screen", {"unknown_id": ("button", widget)})
        self.assertIn("unknown_id", str(cm.exception))

    def test_absent_defaults_file_silent(self):
        """No screen_defaults.json -> unknown ids tolerated, never raise
        (§1.4). The absence is PINNED, not assumed."""
        self.drop_screen_defaults()
        skinning = ScreenSkinning(self.data_dir)
        self.assertIsNone(skinning._defaults)
        skinning._overrides["test_screen"] = {
            "widgets": {"unknown_id": {"rect": [0, 0, 100, 100]}}}
        widget = SimpleNamespace(rect=(0, 0, 1, 1))
        skinning.apply("test_screen", {"unknown_id": ("button", widget)})
        self.assertEqual(widget.rect, (0, 0, 100, 100))


class TestScreenBackground(ScreenSkinningCase):
    def test_screen_background_slot(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "background": {"slot": "ui_bg_main_menu"}}
        self.assertEqual(skinning.screen_background("test_screen"),
                         {"slot": "ui_bg_main_menu"})

    def test_screen_background_color(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["test_screen"] = {
            "background": {"color": [20, 20, 20]}}
        self.assertEqual(skinning.screen_background("test_screen"),
                         {"color": (20, 20, 20)})

    def test_screen_background_absent(self):
        skinning = ScreenSkinning(self.data_dir)
        self.assertIsNone(skinning.screen_background("nonexistent_screen"))

    def test_submit_background_draws_nothing_with_no_override(self):
        """Every shipped screen JSON has no ``background`` key today — the
        call each screen's submit() makes must be a true no-op."""
        skinning = ScreenSkinning(self.data_dir)
        renderer = RecordingRenderer()
        skinning.submit_background(renderer, "main_menu", VIEW_W, VIEW_H)
        self.assertEqual(renderer.items, [])


class TestButtonOverrideEndToEnd(unittest.TestCase):
    """Review HIGH 2: a real screen (``main_menu``, off-screen cursor so no
    button is hovered/flashing), not just ``ScreenSkinning.apply()`` in
    isolation."""

    def _skinned_menu(self, widget_spec):
        skinning = ScreenSkinning.empty()
        skinning._overrides["main_menu"] = {"widgets": {"btn_new_game": widget_spec}}
        menu = MainMenu(VIEW_W, VIEW_H, skinning=skinning)
        menu.update(0.0, *OFF, False)
        return menu

    def test_color_and_text_color_override_reach_the_recorded_primitives(self):
        menu = self._skinned_menu({"color": [10, 20, 30], "text_color": [1, 2, 3]})
        items = _capture(lambda r: menu.submit(r, VIEW_W, VIEW_H))
        fills = [i for i in items if isinstance(i, HudRect)
                and i.rect == menu.buttons[0][0].rect and i.width == 0]
        texts = [i for i in items if isinstance(i, HudText)
                and i.text == "START NEW GAME"]
        self.assertEqual(fills[0].color, (10, 20, 30))
        self.assertEqual(texts[0].color, (1, 2, 3))

    def test_visible_false_draws_nothing_and_is_never_hit(self):
        menu = self._skinned_menu({"visible": False})
        btn = menu.buttons[0][0]
        cx, cy = btn.rect[0] + btn.rect[2] // 2, btn.rect[1] + btn.rect[3] // 2
        items = _capture(lambda r: menu.submit(r, VIEW_W, VIEW_H))
        self.assertFalse(any(
            isinstance(i, HudRect) and i.rect == btn.rect for i in items))
        self.assertFalse(any(
            isinstance(i, HudText) and i.text == "START NEW GAME" for i in items))
        menu.update(0.0, cx, cy, False)  # cursor squarely over the hidden button
        self.assertIsNone(menu.hit(cx, cy))


class TestReviewFixLabelRects(unittest.TestCase):
    """Review fix (B3 surfaced this): five ids targets carried no ``.rect`` —
    their position was computed inline at ``submit()`` time and never
    stored, so the exporter emitted ``rect: [0, 0, 0, 0]`` and a rect
    override could never move them. All five now carry a stored, real
    default rect (the anchor point the centred/left-aligned draw derives
    from — W/H nominal 0, the position-only-text convention documented in
    ``game/ui/CLAUDE.md``), and the draw call is routed through it."""

    def test_five_label_ids_have_a_real_default_rect(self):
        hud = Hud(VIEW_W, VIEW_H)
        # phase_label moved into the End-Turn-relative second ids pass (the
        # round_label precedent), which __init__'s layout() does not run — the
        # exporter's _build_hud calls it the same way.
        hud._layout_readouts()
        cheat = CheatMenu(VIEW_W, VIEW_H)
        boss = BossCutscene(VIEW_W, VIEW_H, CORE)
        boss.open(1, "win")
        holders = {
            "hud.phase_label": hud._phase_label,
            "cheat_menu.title": cheat._title,
            "cheat_menu.jump_label": cheat._jump_label,
            "boss_cutscene.headline": boss._headline,
            "boss_cutscene.subtitle": boss._subtitle,
        }
        for name, holder in holders.items():
            self.assertNotEqual(tuple(holder.rect), (0, 0, 0, 0), name)

    def test_cheat_menu_title_rect_override_moves_the_recorded_text(self):
        skinning = ScreenSkinning.empty()
        skinning._overrides["cheat_menu"] = {
            "widgets": {"title": {"rect": [640, 999, 0, 0]}}}
        menu = CheatMenu(VIEW_W, VIEW_H, skinning=skinning)
        items = _capture(lambda r: menu.submit(r, VIEW_W, VIEW_H))
        title = next(i for i in items
                    if isinstance(i, HudText) and i.text == "CHEATS")
        self.assertEqual(title.pos, (640, 999))

    def test_cheat_menu_title_default_position_is_unchanged_by_the_fix(self):
        """No-override output for the specific widget the fix touched (the
        whole-screen golden pin already covers this too)."""
        menu = CheatMenu(VIEW_W, VIEW_H)
        items = _capture(lambda r: menu.submit(r, VIEW_W, VIEW_H))
        title = next(i for i in items
                    if isinstance(i, HudText) and i.text == "CHEATS")
        px, py, pw, _ph = menu.panel_rect
        # UR-2: the title's inset halved with the logical surface (8 -> 4).
        self.assertEqual(title.pos, (px + pw // 2, py + 4))

    def test_hud_phase_label_rect_override_moves_the_recorded_text(self):
        skinning = ScreenSkinning.empty()
        skinning._overrides["hud"] = {
            "widgets": {"phase_label": {"rect": [500, 501, 0, 0]}}}
        hud = Hud(VIEW_W, VIEW_H, skinning=skinning)
        session = _session()
        panel = BuildingUI(VIEW_W, VIEW_H, UI)
        hud.update(0.0, *OFF, session, panel, False)
        items = _capture(lambda r: hud.submit(r, session, VIEW_W, VIEW_H))
        phase = next(i for i in items
                    if isinstance(i, HudText) and i.text == "Building Phase")
        self.assertEqual(phase.pos, (500, 501))

    def test_boss_cutscene_headline_rect_override_moves_the_recorded_text(self):
        skinning = ScreenSkinning.empty()
        skinning._overrides["boss_cutscene"] = {
            "widgets": {"headline": {"rect": [12, 34, 0, 0]}}}
        boss = BossCutscene(VIEW_W, VIEW_H, CORE, skinning=skinning)
        boss.open(1, "win")
        items = _capture(lambda r: boss.submit(r, VIEW_W, VIEW_H))
        headline = next(i for i in items
                       if isinstance(i, HudText) and i.text.startswith("Cutscene"))
        self.assertEqual(headline.pos, (12, 34))


class TestLogicalSurface(unittest.TestCase):
    """UR-2: the shipped logical surface is 640x360, and the layout exporter
    reads THAT number rather than one of its own.

    Reads the PINNED snapshot (``FIXTURE_DATA``), never live ``data/`` — the
    root CLAUDE.md rule, so a designer editing live data can never turn the
    gate red. The drift this pair catches is an exporter that derives a
    resolution of its own instead of reading the surface it is handed, which
    is a same-tree question and needs no live read: point the exporter at the
    pin and it must agree with the pin."""

    def test_shipped_surface_is_640x360(self):
        display = data_io.load_validated(
            FIXTURE_DATA / "display.json",
            FIXTURE_DATA / "schemas" / "display.schema.json")
        self.assertEqual((display["window_w"], display["window_h"]), (640, 360))

    def test_exporter_resolution_cannot_drift_from_the_surface(self):
        from tools.export_ui_layouts import _logical_resolution
        display = data_io.load_validated(
            FIXTURE_DATA / "display.json",
            FIXTURE_DATA / "schemas" / "display.schema.json")
        self.assertEqual(_logical_resolution(FIXTURE_DATA),
                         (display["window_w"], display["window_h"]))


if __name__ == "__main__":
    unittest.main()
