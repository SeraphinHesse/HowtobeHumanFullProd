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
from engine.core import Scene, SpriteAnimator
from engine.physics import TileOccupancy
from engine.render import HudRect, HudText
from game.buildings import BaseBuilding, attach_base
from game.buildings.registry import build_cost, create, place_building
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap
from game.map.tiles import TileState
from game.ui import widgets
from game.ui.building_ui import BuildingUI, ConstructPreview, _swatch_rgb
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


def build_world():
    """``build()`` plus the scene/occupancy handles ``_do_place`` needs."""
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
    return (session, BuildingUI(VIEW_W, VIEW_H, UI), Hud(VIEW_W, VIEW_H),
            scene, occ)


def build():
    session, panel, hud, _scene, _occ = build_world()
    return session, panel, hud


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


class TestButtonStates(unittest.TestCase):
    """UL-5: a ``states`` offset patch nudges what is DRAWN and nothing else.
    ``self.rect`` is the hit-test truth (``_surface_hit``/``hit`` read it on
    the very next frame), so a state that moved it would make a hovered
    button un-clickable at the position it appears to occupy."""

    def test_hover_state_patch_offsets_draw_not_rect(self):
        btn = widgets.Button((40, 50, 60, 20), "END TURN")
        btn.states = {"hover": {"offset": [0, -4]}}
        btn.hover(45, 55, mouse_down=False)          # inside -> hovered
        self.assertTrue(btn.hovered)
        before = btn.rect

        r = RecordingRenderer()
        btn.submit(r)

        drawn = [i for i in r.items if isinstance(i, HudRect)][0]
        self.assertEqual(drawn.rect, (40, 46, 60, 20))
        self.assertEqual(btn.rect, before)
        self.assertTrue(btn.hit(45, 55))             # still hit-tests as laid out


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


#: MasterSheetColumnsPLAN B2 — a LITERAL capability map, never live `data/`
#: (the root CLAUDE.md "never assert against live data" rule). Keyed on the
#: temp building `ConstructPreview` builds for its own stats, so it matches
#: whatever tier-0 slot key `defence` resolves to.
COLOUR_SLOT = create("defence", 0, 0, BUILD, 0).slot_key()
COLOUR_NAMES = ("pink", "red", "purple", "yellow")


class TestConstructPreviewSwatches(unittest.TestCase):
    """B2: the build-confirm modal's colour swatches — present only for a
    colour-capable slot, and the pick is what gets placed."""

    def _preview(self, colours=None):
        cost = build_cost("defence", BUILD, 0)
        return ConstructPreview("defence", cost, BUILD, UI, VIEW_W, VIEW_H,
                                building_colors=colours)

    def _swatch_centre(self, i):
        """The centre of swatch ``i``, taken from a colour-capable preview so
        a colourLESS one can be probed at the exact same point."""
        x, y, w, h = self._preview(
            {COLOUR_SLOT: COLOUR_NAMES}).swatches.buttons[i].rect
        return x + w // 2, y + h // 2

    def test_no_capability_map_means_no_swatches_at_all(self):
        preview = self._preview()
        self.assertFalse(preview.swatches)
        self.assertEqual([], [k for k in preview.ids
                              if k.startswith("preview_color")])
        self.assertIsNone(preview.chosen_column)
        # Nothing new occupies the band, and the name box still answers.
        self.assertIsNone(preview.handle_click(*self._swatch_centre(0)))
        nx, ny, nw, nh = preview.name_rect
        self.assertEqual("name",
                         preview.handle_click(nx + nw // 2, ny + nh // 2))

    def test_colour_capable_slot_gets_one_id_per_colour(self):
        preview = self._preview({COLOUR_SLOT: COLOUR_NAMES})
        ids = {k: v for k, v in preview.ids.items()
               if k.startswith("preview_color")}
        self.assertEqual(len(COLOUR_NAMES), len(ids))
        self.assertTrue(all(kind == "button" for kind, _w in ids.values()))
        self.assertIsNotNone(preview.chosen_column)

    def test_clicking_a_swatch_selects_that_column(self):
        preview = self._preview({COLOUR_SLOT: COLOUR_NAMES})
        for i in (2, 0):          # a NON-zero index first — 0 must not pass
            with self.subTest(i=i):  # by accident
                self.assertEqual("color",
                                 preview.handle_click(*self._swatch_centre(i)))
                self.assertEqual(i, preview.chosen_column)

    def test_placed_building_carries_the_picked_column(self):
        session, panel, _hud, scene, occ = build_world()
        tile = session.tilemap.get(2, 2)
        session.tilemap.set_tile_state(tile, TileState.BUILDABLE)
        session.state.love = 9999
        panel.colour_columns = {COLOUR_SLOT: COLOUR_NAMES}
        panel.tile, panel.selected_tiles = tile, [tile]
        panel.preview = self._preview(panel.colour_columns)
        panel.preview.chosen_column = 3
        panel._do_place(session, BUILD, scene, occ)
        placed = tile.occupant
        self.assertIsNotNone(placed, "the batch must actually have placed")
        self.assertEqual(3, placed.get_component(SpriteAnimator).column)


class TestUpgradePanelSwatches(unittest.TestCase):
    """B3: the same swatch row on the upgrade panel, recolouring the LIVE
    building, plus the `ui.json` palette lookup behind both screens."""

    def _upgrade(self, colours=None):
        """A panel open in upgrade mode on ONE placed defence building."""
        session, panel, _hud, scene, occ = build_world()
        tile = session.tilemap.get(2, 2)
        session.tilemap.set_tile_state(tile, TileState.BUILDABLE)
        place_building(session.tilemap, tile, "defence", 9999, BUILD,
                       scene, occ)
        panel.colour_columns = colours or {}
        panel.open_for_tile(tile, session, BUILD)
        self.assertEqual("upgrade", panel.mode)
        return session, panel, tile.occupant

    def _centre(self, panel, i):
        x, y, w, h = panel.colour_row.buttons[i].rect
        return x + w // 2, y + h // 2

    # 1 -- the D6 gate ---------------------------------------------------
    def test_row_exists_only_for_a_colour_capable_slot(self):
        _s, panel, _b = self._upgrade({COLOUR_SLOT: COLOUR_NAMES})
        self.assertEqual(len(COLOUR_NAMES), len(panel.colour_row.buttons))
        ids = [k for k in panel.ids if k.startswith("upgrade_swatch")]
        self.assertEqual(len(COLOUR_NAMES), len(ids))

        _s, bare, _b = self._upgrade()          # no capability map at all
        self.assertFalse(bare.colour_row)
        self.assertEqual([], [k for k in bare.ids
                              if k.startswith("upgrade_swatch")])

    # 2 -- the click -----------------------------------------------------
    def test_clicking_a_swatch_recolours_the_live_building(self):
        session, panel, b = self._upgrade({COLOUR_SLOT: COLOUR_NAMES})
        for i in (2, 0):        # a NON-zero index first: 0 is a REAL colour
            with self.subTest(i=i):
                mx, my = self._centre(panel, i)
                self.assertTrue(panel.handle_click(mx, my, session, BUILD,
                                                   None, None))
                self.assertEqual(
                    i, b.get_component(SpriteAnimator).column)

    # 3 -- the palette ---------------------------------------------------
    def test_swatch_rgb_reads_building_colors_and_degrades(self):
        bal = {"BuildingColors": {"pink": [1, 2, 3]}}
        self.assertEqual((1, 2, 3), _swatch_rgb("pink", bal))
        # A `columns` name with no entry, an absent group and no balance at
        # all all degrade to the neutral swatch rather than raising.
        self.assertEqual(widgets.C_PANEL_INSET, _swatch_rgb("chartreuse", bal))
        self.assertEqual(widgets.C_PANEL_INSET, _swatch_rgb("pink", {}))
        self.assertEqual(widgets.C_PANEL_INSET, _swatch_rgb("pink"))

    # 4 -- the band ------------------------------------------------------
    def test_the_row_moves_nothing_and_clears_the_action_button(self):
        _s, bare, _b = self._upgrade()
        _s, panel, _b = self._upgrade({COLOUR_SLOT: COLOUR_NAMES})
        self.assertEqual(bare.action_btn.rect, panel.action_btn.rect)
        self.assertEqual(bare.move_btn.rect, panel.move_btn.rect)
        top = panel.action_btn.rect[1]
        for i, btn in enumerate(panel.colour_row.buttons):
            with self.subTest(i=i):
                x, y, w, h = btn.rect
                self.assertLessEqual(y + h, top)      # above the button
                self.assertGreaterEqual(min(w, h), 12)   # UR-5 floor


class TestBossNextIndicatorIcon(unittest.TestCase):
    """The top-right icon beside Pause: reflects whether ``round_num`` (the
    round about to be fought, per ``game/core/game_state.py``'s numbering) is
    a boss round, and draws only during ``GamePhase.BUILDING``. FIXTURE_DATA's
    ``EnemyScaling`` ships ``rounds_per_era: 10, boss_round_in_era: 10``, so
    round 10 is a boss round and round 1 is not."""

    def test_skin_reflects_the_next_round_being_a_boss_round(self):
        session, panel, hud = build()
        session.state.round_num = 10
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud._icon_boss_next.skin, "ui_icon_boss_next")

    def test_skin_reflects_the_next_round_not_being_a_boss_round(self):
        session, panel, hud = build()
        session.state.round_num = 1
        hud.update(0.016, 0, 0, session, panel)
        self.assertEqual(hud._icon_boss_next.skin, "ui_icon_boss_next_off")

    def test_drawn_only_during_building_phase(self):
        session, panel, hud = build()
        session.state.round_num = 10
        hud.update(0.016, 0, 0, session, panel)
        r = RecordingRenderer()
        hud.submit(r, session, VIEW_W, VIEW_H)
        self.assertTrue(any(getattr(i, "slot_key", None) == "ui_icon_boss_next"
                            for i in r.items))

        session.state.phase = GamePhase.ENEMY
        hud.update(0.016, 0, 0, session, panel)
        r2 = RecordingRenderer()
        hud.submit(r2, session, VIEW_W, VIEW_H)
        self.assertFalse(any(getattr(i, "slot_key", "").startswith("ui_icon_boss_next")
                             for i in r2.items))


if __name__ == "__main__":
    unittest.main()
