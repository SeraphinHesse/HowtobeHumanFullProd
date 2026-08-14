"""The building panel occludes the HUD's right-edge cluster (pause + End Turn).

The panel is a full-height right sidebar and ``main.py`` submits the HUD AFTER
it, so both right-edge buttons would otherwise paint ON TOP of the panel and
stay clickable through it. ``Hud`` therefore neither draws nor hit-tests them
while any panel mode (unlock / construct / upgrade / base_info) or the construct
preview is open.

Pure + headless (the ``test_lightning`` fixture style): a synth board, a real
``Session`` / ``BuildingUI`` / ``Hud``, and a recording stand-in renderer.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from engine.render import HudRect, HudText
from game.buildings import BaseBuilding, attach_base
from game.buildings.registry import build_cost
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.ui import widgets
from game.ui.building_ui import BuildingUI, ConstructPreview
from game.ui.hud import Hud

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")

VIEW_W, VIEW_H = 640, 360
FIELD = ["bsssss"] + ["ssssss"] * 5
PANEL_MODES = ("unlock", "construct", "upgrade", "base_info")


class RecordingRenderer:
    """``Hud`` only ever emits through ``submit_hud``."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)

    def rects(self):
        return [getattr(i, "rect", None) for i in self.items]


def build():
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(FIELD[0]), rows=len(FIELD),
        legend={}, terrain=[list(r) for r in FIELD],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[])
    tm = TileMap(doc, MAPBAL)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ)
    session.state.state = GameState.GAMEPLAY
    session.state.phase = GamePhase.BUILDING
    return session, BuildingUI(VIEW_W, VIEW_H, UI), Hud(VIEW_W, VIEW_H)


def centre(btn):
    x, y, w, h = btn.rect
    return x + w // 2, y + h // 2


class TestPanelOccludesHudButtons(unittest.TestCase):
    def test_both_buttons_really_sit_under_the_panel_column(self):
        """The premise: if they did not overlap, there would be no bug."""
        _, panel, hud = build()
        for btn in (hud.pause, hud.end_turn):
            bx, by, bw, bh = btn.rect
            self.assertGreaterEqual(bx, panel.panel_x)
            self.assertLess(by, VIEW_H)

    def test_buttons_live_while_the_panel_is_closed(self):
        session, panel, hud = build()
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud.hit(*centre(hud.pause)), "pause")
        self.assertEqual(hud.hit(*centre(hud.end_turn)), "end_turn")

    def test_open_panel_disables_both_buttons(self):
        session, panel, hud = build()
        for mode in PANEL_MODES:
            with self.subTest(mode=mode):
                panel.mode = mode
                hud.update(0.016, 0, 0, session, panel)
                self.assertTrue(panel.visible)
                self.assertIsNone(hud.hit(*centre(hud.pause)))
                self.assertIsNone(hud.hit(*centre(hud.end_turn)))
                self.assertFalse(hud.pause.enabled)
                self.assertFalse(hud.end_turn.enabled)

    def test_open_panel_stops_drawing_both_buttons(self):
        session, panel, hud = build()
        for mode in PANEL_MODES:
            with self.subTest(mode=mode):
                panel.mode = mode
                hud.update(0.016, 0, 0, session, panel)
                r = RecordingRenderer()
                hud.submit(r, session, VIEW_W, VIEW_H)
                drawn = r.rects()
                self.assertNotIn(hud.pause.rect, drawn)
                self.assertNotIn(hud.end_turn.rect, drawn)

    def test_construct_preview_also_hides_them(self):
        """The name-entry modal opens over a `construct` panel."""
        session, panel, hud = build()
        panel.mode, panel.preview = "construct", object()
        hud.update(0.016, 0, 0, session, panel)
        self.assertIsNone(hud.hit(*centre(hud.pause)))
        self.assertIsNone(hud.hit(*centre(hud.end_turn)))

    def test_closing_the_panel_restores_them(self):
        session, panel, hud = build()
        panel.mode = "upgrade"
        hud.update(0.016, 0, 0, session, panel)
        panel.close()
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud.hit(*centre(hud.pause)), "pause")
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        self.assertIn(hud.pause.rect, r.rects())
        self.assertIn(hud.end_turn.rect, r.rects())


class TestHudButtonZOrder(unittest.TestCase):
    """``panel -> button -> text`` (game/ui/CLAUDE.md, engine/render/CLAUDE.md
    "HUD pass": submission order IS draw order). The round-cluster separator
    used to be submitted AFTER the End Turn button, so it drew ON TOP of the
    button's top edge; it must draw BEHIND it instead."""

    def test_separator_precedes_end_turn_button(self):
        session, panel, hud = build()
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        bx, by, bw, _bh = hud.end_turn.rect
        separator = HudRect((bx, by - 2, bw, 1), widgets.C_UI_BORDER)
        sep_idx = r.items.index(separator)
        btn_idx = next(i for i, item in enumerate(r.items)
                       if isinstance(item, HudRect)
                       and item.rect == hud.end_turn.rect)
        self.assertLess(sep_idx, btn_idx,
                        "separator must draw BEHIND (before) the End Turn button")


class TestConstructPreviewZOrder(unittest.TestCase):
    """``ConstructPreview.submit()`` used to intersperse TEXT submissions
    between the panel/name-box and the confirm/cancel/close/dice BUTTONS.
    Every standalone text label (title, cost, name label, stat rows) must now
    draw on top of (after) every button — game/ui/CLAUDE.md "panel -> button
    -> text"."""

    def _preview(self):
        cost = build_cost("defence", BUILD, 0)
        preview = ConstructPreview("defence", cost, BUILD, UI,
                                   VIEW_W, VIEW_H)
        preview.hover(-1000, -1000, False)
        preview.update(0.016)
        return preview

    def test_every_text_submission_follows_every_button_submission(self):
        preview = self._preview()
        r = RecordingRenderer()
        preview.submit(r)

        button_rects = {preview.dice_btn.rect, preview.confirm_btn.rect,
                        preview.close_btn.rect}
        if preview.cancel_btn is not None:
            button_rects.add(preview.cancel_btn.rect)
        button_indices = [i for i, item in enumerate(r.items)
                          if isinstance(item, HudRect)
                          and item.rect in button_rects]
        self.assertTrue(button_indices)
        last_button_idx = max(button_indices)

        # The standalone labels the bug used to draw BEFORE the buttons —
        # not a button's own label (that always rides with its own button).
        standalone = {preview.title,
                     f"Cost  {preview.total_cost}", "Name:"}
        standalone |= {label for label, _value in preview.stats}
        text_indices = [i for i, item in enumerate(r.items)
                        if isinstance(item, HudText) and item.text in standalone]
        self.assertTrue(text_indices)
        self.assertTrue(all(i > last_button_idx for i in text_indices),
                        "every standalone text submission must follow every "
                        "button submission")


class TestLoveHoverCostDisplay(unittest.TestCase):
    """The love pill: plain amount outside a hover, "current - price" while
    hovering a buyable option — both affordable and not — replacing the old
    plain-remainder / bare "-" display. The hover case draws as TWO
    separately-coloured runs (current love stays gold, only " - price"
    reads red), so it emits two HudTexts side by side instead of one."""

    @staticmethod
    def _love_text_item(renderer, hud):
        pos = hud._love_text.rect[:2]
        for item in renderer.items:
            if isinstance(item, HudText) and item.pos == pos:
                return item
        return None

    @staticmethod
    def _love_hover_pair(renderer, hud):
        """(current_item, price_item), left-to-right, both on the love
        text's row — the two-segment hover draw (`Hud._submit_love_hover_
        cost`)."""
        y = hud._love_text.rect[1]
        row = sorted((item for item in renderer.items
                      if isinstance(item, HudText) and item.pos[1] == y),
                     key=lambda item: item.pos[0])
        return row[0], row[1]

    def test_no_hover_shows_the_plain_amount(self):
        session, panel, hud = build()
        session.state.love = 42
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        item = self._love_text_item(r, hud)
        self.assertEqual(item.text, "42")
        self.assertEqual(item.color, widgets.C_GOLD)

    def test_love_display_overrides_the_plain_amount_outside_hover(self):
        """The animated counter (game/ui/effects.py FloaterManager.love_display)
        stands in for the raw state.love outside a hover preview."""
        session, panel, hud = build()
        session.state.love = 42
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H, love_display=17)
        item = self._love_text_item(r, hud)
        self.assertEqual(item.text, "17")

    def test_hover_shows_the_arithmetic_when_affordable(self):
        session, panel, hud = build()
        session.state.love = 30
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H, hover_cost=20)
        current, price = self._love_hover_pair(r, hud)
        self.assertEqual(current.text + price.text, "30 - 20")

    def test_hover_colours_current_gold_and_price_red(self):
        session, panel, hud = build()
        session.state.love = 30
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H, hover_cost=20)
        current, price = self._love_hover_pair(r, hud)
        self.assertEqual(current.text, "30")
        self.assertEqual(current.color, widgets.C_GOLD)
        self.assertEqual(price.text, " - 20")
        self.assertEqual(price.color, widgets.C_RED)
        # side by side, price starting where current's glyphs end
        self.assertGreater(price.pos[0], current.pos[0])

    def test_hover_shows_the_arithmetic_when_unaffordable(self):
        session, panel, hud = build()
        session.state.love = 10
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H, hover_cost=40)
        current, price = self._love_hover_pair(r, hud)
        self.assertEqual(current.text + price.text, "10 - 40")
        # unaffordable still colours the same way — current stays gold,
        # only the price half turns red, even though it exceeds current
        self.assertEqual(current.color, widgets.C_GOLD)
        self.assertEqual(price.color, widgets.C_RED)

    def test_hover_ignores_love_display_and_reads_the_real_love(self):
        """The hover preview is a correctness question ("can I afford this
        right now"), so it must read the real state.love, never the
        animated counter — even if the two currently disagree."""
        session, panel, hud = build()
        session.state.love = 30
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H, hover_cost=20, love_display=999)
        current, price = self._love_hover_pair(r, hud)
        self.assertEqual(current.text + price.text, "30 - 20")


if __name__ == "__main__":
    unittest.main()
