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

VIEW_W, VIEW_H = 1280, 720
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


_LEVELUP_OPTIONS = [
    {"kind": "fallback", "title": "Card A", "cost": 5,
     "explanation": "does a thing", "prev_name": None, "sprite_key": None,
     "cost_label": "Cost", "display_cost": 5},
    {"kind": "tier", "title": "Card B", "cost": 0,
     "explanation": "tiered thing", "prev_name": "Old Name",
     "sprite_key": None, "cost_label": None, "tier_no": 2, "tier_max": 3},
]


class _GameOverState:
    round_num = 4
    buildings_placed = 2
    enemies_killed = 9


def _capture(fn):
    r = RecordingRenderer()
    fn(r)
    return r.items


def _screen_captures():
    """``{screen_id: recorded_items}`` for all 12 screens — fresh instances
    every call, no state shared between screens."""
    session = _session()

    mm = MainMenu(VIEW_W, VIEW_H)
    mm.update(0.0, *OFF, False)

    ps = PauseScreen(VIEW_W, VIEW_H)
    ps.update(0.0, *OFF, False)

    settings = SettingsScreen(VIEW_W, VIEW_H, SessionSettings.from_balance(UI))
    settings.update(0.0, *OFF, False)

    credits = CreditsScreen(VIEW_W, VIEW_H)
    credits.update(0.0, *OFF, False)

    add_name = AddNameScreen(VIEW_W, VIEW_H)
    add_name.pool_count = 3
    add_name.update(0.0, *OFF, False)

    game_over = GameOverScreen(VIEW_W, VIEW_H)
    game_over.update(0.0, *OFF, False)

    levelup = LevelupWindow(VIEW_W, VIEW_H)
    levelup.open(_LEVELUP_OPTIONS)
    levelup.update(0.0, *OFF, False)

    hud = Hud(VIEW_W, VIEW_H)
    hud_panel = BuildingUI(VIEW_W, VIEW_H, UI)
    hud.update(0.0, *OFF, session, hud_panel, False)

    panel = BuildingUI(VIEW_W, VIEW_H, UI)
    panel.hover(*OFF, False)
    panel.update(0.0)

    cheat = CheatMenu(VIEW_W, VIEW_H)
    cheat.update(0.0, *OFF, False)

    game_log = GameLog()
    game_log.post("Test message")
    game_log.update(0.0)

    boss = BossCutscene(VIEW_W, VIEW_H)
    boss.open(1, "win")
    boss.update(0.0, *OFF, False)

    return {
        "main_menu": _capture(lambda r: mm.submit(r, VIEW_W, VIEW_H)),
        "pause": _capture(lambda r: ps.submit(r, VIEW_W, VIEW_H)),
        "settings": _capture(lambda r: settings.submit(r, VIEW_W, VIEW_H)),
        "credits": _capture(lambda r: credits.submit(r, VIEW_W, VIEW_H)),
        "add_name": _capture(lambda r: add_name.submit(r, VIEW_W, VIEW_H)),
        "game_over": _capture(
            lambda r: game_over.submit(r, _GameOverState(), VIEW_W, VIEW_H)),
        "levelup": _capture(lambda r: levelup.submit(r, VIEW_W, VIEW_H)),
        "hud": _capture(lambda r: hud.submit(
            r, session, VIEW_W, VIEW_H, hover_cost=hud_panel.hover_cost)),
        "building_panel": _capture(lambda r: panel.submit(r, session)),
        "cheat_menu": _capture(lambda r: cheat.submit(r, VIEW_W, VIEW_H)),
        "game_log": _capture(lambda r: game_log.submit(r, VIEW_H)),
        "boss_cutscene": _capture(lambda r: boss.submit(r, VIEW_W, VIEW_H)),
    }


#: THE golden baseline — captured from the pre-B2 code (no ``ids``/``apply``
#: wiring, no ``data/ui/screens`` consumption at all existed). Do not
#: hand-tune; a screen's DEFAULT geometry/text changing for reasons unrelated
#: to B2 is the only legitimate reason to regenerate an entry, and it should
#: be regenerated from the base commit, not guessed.
_BASELINE = {
    "main_menu": [
        HudRect(rect=(0, 0, 1280, 720), color=(18, 30, 20), border_radius=0, width=0),
        HudSprite(slot_key='main_menu_bg', dest=(0, 0), size=(1280, 720), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='HOW TO BE HUMAN', pos=(640, 210), font_key='xxl', color=(168, 105, 222), align='center'),
        HudText(text='defend the munckins', pos=(640, 250), font_key='md', color=(168, 105, 222), align='center'),
        HudRect(rect=(480, 300, 320, 52), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(480, 300, 320, 52), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='START NEW GAME', pos=(640, 318), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(480, 366, 320, 52), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(480, 366, 320, 52), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ADD A NAME', pos=(640, 384), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(480, 432, 320, 52), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(480, 432, 320, 52), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='SETTINGS', pos=(640, 450), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(480, 498, 320, 52), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(480, 498, 320, 52), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='CREDITS', pos=(640, 516), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(480, 564, 320, 52), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(480, 564, 320, 52), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='QUIT', pos=(640, 582), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "pause": [
        HudRect(rect=(0, 0, 1280, 720), color=(0, 0, 0, 150), border_radius=0, width=0),
        HudRect(rect=(490, 200, 300, 320), color=(24, 20, 40), border_radius=6, width=0),
        HudRect(rect=(490, 200, 300, 320), color=(80, 65, 120), border_radius=6, width=2),
        HudText(text='PAUSED', pos=(640, 232), font_key='xl', color=(255, 200, 50), align='center'),
        HudRect(rect=(520, 284, 240, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(520, 284, 240, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='RESUME', pos=(640, 299), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(520, 342, 240, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(520, 342, 240, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='SETTINGS', pos=(640, 357), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(520, 400, 240, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(520, 400, 240, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='QUIT TO MENU', pos=(640, 415), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(520, 458, 240, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(520, 458, 240, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='QUIT GAME', pos=(640, 473), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "settings": [
        HudRect(rect=(0, 0, 1280, 720), color=(12, 20, 14), border_radius=0, width=0),
        HudText(text='SETTINGS', pos=(640, 180), font_key='xxl', color=(255, 200, 50), align='center'),
        HudText(text='Display Mode', pos=(640, 216), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='WINDOWED', pos=(640, 250), font_key='lg', color=(255, 200, 50), align='center'),
        HudRect(rect=(490, 244, 40, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(490, 244, 40, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='<', pos=(510, 256), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(750, 244, 40, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(750, 244, 40, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='>', pos=(770, 256), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Income Floaters', pos=(490, 320), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(700, 312, 90, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(700, 312, 90, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(745, 324), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Background Art', pos=(490, 376), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(700, 368, 90, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(700, 368, 90, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(745, 380), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Gore', pos=(490, 432), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(700, 424, 90, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(700, 424, 90, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ON', pos=(745, 436), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Master Audio', pos=(490, 474), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(550, 498, 180, 12), color=(80, 65, 120), border_radius=0, width=0),
        HudRect(rect=(550, 498, 144, 12), color=(75, 60, 115), border_radius=0, width=0),
        HudText(text='(no audio yet)', pos=(640, 518), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(540, 558, 200, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 558, 200, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(640, 573), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "credits": [
        HudRect(rect=(0, 0, 1280, 720), color=(12, 20, 14), border_radius=0, width=0),
        HudText(text='CREDITS', pos=(640, 70), font_key='xxl', color=(255, 200, 50), align='center'),
        HudText(text='Producer', pos=(600, 150), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Seraphin Hesse', pos=(680, 150), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Design Lead', pos=(600, 180), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Fabian Krüger', pos=(680, 180), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Art Lead', pos=(600, 210), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Hendrik Wagner', pos=(680, 210), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programming Lead', pos=(600, 240), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Johann Heinrich', pos=(680, 240), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='UI Lead/2D Artist', pos=(600, 284), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Alicia Jaison', pos=(680, 284), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='2D Artist', pos=(600, 314), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Varvara Kozačuk', pos=(680, 314), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='2D Artist', pos=(600, 344), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Jakob Dahlkar', pos=(680, 344), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Designer', pos=(600, 388), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Joel Hoch', pos=(680, 388), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Game Designer', pos=(600, 418), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Benjamin Riese', pos=(680, 418), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programmer', pos=(600, 462), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Pantelis Charalambous', pos=(680, 462), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Programmer', pos=(600, 492), font_key='sm', color=(150, 140, 120), align='right'),
        HudText(text='Alfons Kavalic', pos=(680, 492), font_key='md', color=(235, 225, 195), align='left'),
        HudRect(rect=(540, 630, 200, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 630, 200, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(640, 645), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "add_name": [
        HudRect(rect=(0, 0, 1280, 720), color=(12, 20, 14), border_radius=0, width=0),
        HudRect(rect=(410, 230, 460, 260), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(410, 230, 460, 260), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='ADD A NAME', pos=(640, 250), font_key='xl', color=(255, 200, 50), align='center'),
        HudText(text='Appears on the building-naming dice button.', pos=(640, 292), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(434, 338, 412, 36), color=(40, 32, 58), border_radius=0, width=0),
        HudRect(rect=(434, 338, 412, 36), color=(255, 200, 50), border_radius=0, width=1),
        HudText(text='_', pos=(442, 347), font_key='md', color=(235, 225, 195), align='left'),
        HudText(text='Names in pool: 3', pos=(434, 412), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(434, 434, 160, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(434, 434, 160, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='ADD NAME', pos=(514, 446), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(716, 434, 130, 40), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(716, 434, 130, 40), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='BACK', pos=(781, 446), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "game_over": [
        HudRect(rect=(0, 0, 1280, 720), color=(10, 5, 15), border_radius=0, width=0),
        HudText(text='THE COLONY WAS DESTROYED', pos=(640, 240), font_key='xxl', color=(210, 55, 55), align='center'),
        HudText(text='Round Reached: 4', pos=(640, 330), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Buildings Placed: 2', pos=(640, 358), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Enemies Killed: 9', pos=(640, 386), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(520, 470, 240, 46), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(520, 470, 240, 46), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='RETURN TO MENU', pos=(640, 485), font_key='lg', color=(235, 225, 195), align='center'),
    ],
    "levelup": [
        HudRect(rect=(0, 0, 1280, 720), color=(0, 0, 0, 185), border_radius=0, width=0),
        HudText(text='CHOOSE YOUR REWARD', pos=(640, 204), font_key='xxl', color=(255, 200, 50), align='center'),
        HudRect(rect=(436, 250, 200, 220), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(436, 250, 200, 220), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='Card A', pos=(536, 260), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='Cost  5', pos=(536, 355), font_key='sm', color=(255, 200, 50), align='center'),
        HudText(text='does a thing', pos=(536, 370), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(644, 250, 200, 220), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(644, 250, 200, 220), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='Old Name', pos=(744, 260), font_key='sm', color=(150, 140, 120), align='center'),
        HudLines(points=((739, 279), (744, 273), (749, 279)), color=(80, 210, 80), width=2, closed=False),
        HudText(text='Card B', pos=(744, 283), font_key='md', color=(235, 225, 195), align='center'),
        HudText(text='tiered thing', pos=(744, 393), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='Tier 2 of 3', pos=(744, 453), font_key='sm', color=(150, 140, 120), align='center'),
    ],
    # NOTE: the round-cluster separator rect (80, 65, 120)-colored, height 1)
    # moved to just BEFORE the END TURN button rects (was after) — a
    # deliberate panel->button->text ordering fix (game/ui/CLAUDE.md), not a
    # geometry/text change. See TestHudButtonZOrder in test_hud_panel.py.
    "hud": [
        HudRect(rect=(12, 12, 190, 34), color=(40, 32, 58), border_radius=4, width=0),
        HudRect(rect=(12, 12, 190, 34), color=(150, 135, 185), border_radius=4, width=1),
        HudSprite(slot_key='ui_icon_love', dest=(18, 20), size=(18, 18), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='25', pos=(40, 19), font_key='xl', color=(255, 200, 50), align='left'),
        HudText(text='LVL 1', pos=(214, 12), font_key='hud_lvl', color=(255, 200, 50), align='left'),
        HudSprite(slot_key='ui_icon_xp', dest=(214, 25), size=(18, 18), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudRect(rect=(236, 29, 110, 9), color=(48, 34, 66), border_radius=0, width=0),
        HudRect(rect=(236, 29, 110, 9), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='0/50', pos=(236, 40), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(12, 46, 190, 55), color=(40, 32, 58), border_radius=4, width=0),
        HudRect(rect=(12, 46, 190, 55), color=(150, 135, 185), border_radius=4, width=1),
        HudText(text='+5/round', pos=(16, 50), font_key='sm', color=(214, 96, 136), align='left'),
        HudSprite(slot_key='ui_icon_lives', dest=(16, 66), size=(18, 18), tint=None, flip=False, animation='idle', anim_time_ms=0),
        HudText(text='LIVES 3', pos=(38, 66), font_key='md', color=(200, 55, 55), align='left'),
        HudText(text='0/4 tiles', pos=(16, 84), font_key='md', color=(150, 140, 120), align='left'),
        HudText(text='BUILDING', pos=(12, 694), font_key='hud_phase', color=(150, 140, 120), align='left'),
        HudText(text='ROUND 1', pos=(1184, 627), font_key='md', color=(150, 140, 120), align='center'),
        HudRect(rect=(1104, 642, 160, 1), color=(80, 65, 120), border_radius=0, width=0),
        HudRect(rect=(1104, 644, 160, 60), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(1104, 644, 160, 60), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='END TURN', pos=(1184, 666), font_key='lg', color=(235, 225, 195), align='center'),
        HudRect(rect=(1174, 12, 90, 30), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(1174, 12, 90, 30), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='PAUSE', pos=(1219, 20), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(12, 110, 56, 28), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(12, 110, 56, 28), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='1×', pos=(40, 118), font_key='sm', color=(255, 200, 50), align='center'),
        HudRect(rect=(12, 110, 56, 28), color=(255, 200, 50), border_radius=3, width=2),
        HudRect(rect=(74, 110, 56, 28), color=(50, 45, 70), border_radius=3, width=0),
        HudRect(rect=(74, 110, 56, 28), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='1.5×', pos=(102, 118), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(136, 110, 56, 28), color=(50, 45, 70), border_radius=3, width=0),
        HudRect(rect=(136, 110, 56, 28), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='2×', pos=(164, 118), font_key='sm', color=(150, 140, 120), align='center'),
    ],
    "building_panel": [
    ],
    "cheat_menu": [
        HudRect(rect=(0, 0, 1280, 720), color=(0, 0, 0, 150), border_radius=0, width=0),
        HudRect(rect=(530, 231, 220, 258), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(530, 231, 220, 258), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='CHEATS', pos=(640, 239), font_key='lg', color=(255, 200, 50), align='center'),
        HudRect(rect=(724, 237, 20, 18), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(724, 237, 20, 18), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='X', pos=(734, 239), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 263, 200, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 263, 200, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='+10 Love', pos=(640, 269), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 293, 200, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 293, 200, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Skip Round', pos=(640, 299), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 323, 200, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 323, 200, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='LEVEL UP', pos=(640, 329), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 353, 200, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 353, 200, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Infinite Money', pos=(640, 359), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 383, 200, 26), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(540, 383, 200, 26), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Unlock All Tech', pos=(640, 389), font_key='md', color=(235, 225, 195), align='center'),
        HudRect(rect=(540, 415, 200, 1), color=(80, 65, 120), border_radius=0, width=0),
        HudText(text='Jump to round:', pos=(540, 421), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(540, 439, 96, 22), color=(40, 32, 58), border_radius=0, width=0),
        HudRect(rect=(540, 439, 96, 22), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='round', pos=(546, 443), font_key='sm', color=(150, 140, 120), align='left'),
        HudRect(rect=(642, 439, 98, 22), color=(75, 60, 115), border_radius=3, width=0),
        HudRect(rect=(642, 439, 98, 22), color=(80, 65, 120), border_radius=3, width=1),
        HudText(text='Go to Round', pos=(691, 444), font_key='sm', color=(235, 225, 195), align='center'),
    ],
    "game_log": [
        HudText(text='Test message', pos=(8, 688), font_key='sm', color=(220, 200, 155, 255), align='left'),
    ],
    "boss_cutscene": [
        HudRect(rect=(0, 0, 1280, 720), color=(0, 0, 0, 210), border_radius=0, width=0),
        HudText(text='Cutscene: Round Won :)', pos=(640, 244), font_key='xxl', color=(100, 220, 100), align='center'),
        HudText(text='How will we react?', pos=(640, 290), font_key='md', color=(150, 140, 120), align='center'),
        HudRect(rect=(450, 315, 180, 130), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(450, 315, 180, 130), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='WinA', pos=(540, 327), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Per unbuilt tile, buildings do', pos=(540, 352), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='+1 extra damage', pos=(540, 365), font_key='sm', color=(150, 140, 120), align='center'),
        HudRect(rect=(650, 315, 180, 130), color=(42, 34, 68), border_radius=0, width=0),
        HudRect(rect=(650, 315, 180, 130), color=(80, 65, 120), border_radius=0, width=1),
        HudText(text='WinB', pos=(740, 327), font_key='lg', color=(235, 225, 195), align='center'),
        HudText(text='Per building level past 2,', pos=(740, 352), font_key='sm', color=(150, 140, 120), align='center'),
        HudText(text='generate +1 love per round', pos=(740, 365), font_key='sm', color=(150, 140, 120), align='center'),
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
    """A ``ScreenSkinning`` over a tempdir copy of the pinned fixture (which
    ships NO ``data/ui/screens/`` at all — the "missing directory" graceful
    path) — never the live repo (T-3/data guard)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = fixture_copy(self._tmp.name)


class TestScreenSkinningLoad(ScreenSkinningCase):
    def test_missing_screens_directory_is_graceful(self):
        """No data/ui/screens/ at all (today's fixture) -> empty overrides,
        never a crash (§1.3 E-37 degrade)."""
        skinning = ScreenSkinning(self.data_dir)
        self.assertEqual(skinning._overrides, {})

    def test_absent_defaults_file_is_none(self):
        """data/ui/screen_defaults.json doesn't exist until B3 lands (§1.4)."""
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
        """No screen_defaults.json (B3 not landed) -> unknown ids tolerated,
        never raise (§1.4)."""
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
        cheat = CheatMenu(VIEW_W, VIEW_H)
        boss = BossCutscene(VIEW_W, VIEW_H)
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
        self.assertEqual(title.pos, (px + pw // 2, py + 8))

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
                    if isinstance(i, HudText) and i.text == "BUILDING")
        self.assertEqual(phase.pos, (500, 501))

    def test_boss_cutscene_headline_rect_override_moves_the_recorded_text(self):
        skinning = ScreenSkinning.empty()
        skinning._overrides["boss_cutscene"] = {
            "widgets": {"headline": {"rect": [12, 34, 0, 0]}}}
        boss = BossCutscene(VIEW_W, VIEW_H, skinning=skinning)
        boss.open(1, "win")
        items = _capture(lambda r: boss.submit(r, VIEW_W, VIEW_H))
        headline = next(i for i in items
                       if isinstance(i, HudText) and i.text.startswith("Cutscene"))
        self.assertEqual(headline.pos, (12, 34))


if __name__ == "__main__":
    unittest.main()
