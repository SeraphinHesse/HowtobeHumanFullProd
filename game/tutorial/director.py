"""``TutorialDirector`` — binds the engine's game-agnostic step-sequencer
(``engine.tutorial``) to real tiles/cards/buttons (Phase TU-6).

This is where "flute"/"musician"/"economy"/"stone"/"defence" vocabulary
lives — never in ``engine/tutorial.py`` (D2). Reads
``data/tutorial/tutorial.json`` (TU-1's schema) and the map doc's
``tutorial_flute``/``tutorial_stone`` markers; auto-skips (empty sequencer,
one logged warning, never raises) when the script or the flute marker is
missing/invalid so an old/unpainted map is always fully playable. TU-7 adds
the round-2 stone-thrower chain, the scripted first-round loss (optionally
free) and the tutorial-end state riding the SAME sequencer/script.

TU-8 adds two independent fixes riding the same sequencer:
- **Fix 1 (un-stick on panel close)**: ``on_panel_closed()`` fires the
  opaque ``"panel_closed"`` event on every panel-close path that did NOT
  just land a placement (the host discriminates via
  ``panel.last_placed_type``, same as ``on_building_placed``). The card and
  Confirm steps of both chains carry ``revert_on: "panel_closed"`` in the
  script, reverting the sequencer back to their own tile step
  (``engine.tutorial.TutorialSequencer.revert``) — closing the panel without
  placing re-highlights the designated tile instead of leaving the chain
  dead.
- **Fix 2 (close-panel hint)**: one new step, flute chain only, between the
  Confirm step and End Turn — highlights the panel's own CLOSE button
  (``"button:close"``, resolved by ``ui_highlight_rects`` via
  ``panel.close_rect()``) and shows a non-modal banner (``banner_text()``,
  resolved off the step's ``flags["banner"]`` key against the script's
  ``messages`` map — never the modal ``message`` field). Its
  ``advance_on`` is the SAME ``"panel_closed"`` event ``on_panel_closed()``
  feeds — the sequencer's ordinary forward `advance` on this step, the
  backward `revert` on the card/Confirm steps; only one of the two can ever
  match the CURRENT step, so ``on_panel_closed()`` simply tries both. End
  Turn stays gated (not in this step's ``allow``) for free, the same
  whitelist mechanism every other step already uses.
"""
import json
import logging

import jsonschema

from engine import data_io
from engine.tutorial import Step, TutorialSequencer

log = logging.getLogger(__name__)

# The guided chain's forced-first economy building (the Musician line,
# game/buildings/musician.py BUILDING_TYPE = "economic") — matches the data
# script's literal `building_selected:economic` / `building_placed:economic`
# event ids (data/tutorial/tutorial.json). Game vocabulary belongs here, not
# in engine/tutorial.py.
ECONOMY_BUILDING_TYPE = "economic"


def _load_script(data_dir):
    """Load + validate data/tutorial/tutorial.json into (skippable,
    first_loss_costs_life, messages, steps), or None on any load/validation
    failure (never raises)."""
    try:
        doc = data_io.load_validated(
            data_dir / "tutorial" / "tutorial.json",
            data_dir / "schemas" / "tutorial.schema.json")
    except (OSError, ValueError, jsonschema.ValidationError,
            json.JSONDecodeError) as exc:
        log.warning("tutorial: could not load tutorial.json (%s) — "
                    "auto-skipping", exc)
        return None
    steps = tuple(
        Step(id=s["id"], message=s["message"], highlight=tuple(s["highlight"]),
             advance_on=s["advance_on"], allow=tuple(s["allow"]),
             flags=dict(s["flags"]), revert_on=s["revert_on"],
             revert_to=s["revert_to"])
        for s in doc["steps"])
    return (doc["skippable"], doc["first_loss_costs_life"], doc["messages"],
            steps)


class TutorialDirector:
    def __init__(self, data_dir, map_doc, tutorial_balance):
        self._flute = map_doc.tutorial_flute  # nullable {"col", "row"}
        self._stone = map_doc.tutorial_stone  # nullable {"col", "row"} (TU-7)
        self._messages = {}
        self._required = 0
        self._economy_placed = 0
        self._first_loss_costs_life = True

        loaded = None
        if self._flute is None:
            log.warning(
                "tutorial: map has no tutorial_flute marker — auto-skipping")
        else:
            loaded = _load_script(data_dir)

        if loaded is None:
            self.sequencer = TutorialSequencer((), skippable=False)
            self.sequencer.skip()
            self.active = False
            return

        skippable, first_loss_costs_life, messages, steps = loaded
        self._messages = messages
        self._first_loss_costs_life = first_loss_costs_life
        self._required = tutorial_balance["economy_buildings_required"]
        self.sequencer = TutorialSequencer(steps, skippable=skippable)
        self.active = True

    @property
    def finished(self):
        """The D6 zero-overhead fast path: True once skipped or past the
        last step — every gate collapses to a single bool check."""
        return self.sequencer.finished

    # -- action resolution --------------------------------------------------

    def _action_id(self, action):
        kind = action[0]
        if kind == "tile":
            _, col, row = action
            if self._flute is not None and (
                    col, row) == (self._flute["col"], self._flute["row"]):
                return "tile_click:tutorial_flute"
            if self._stone is not None and (
                    col, row) == (self._stone["col"], self._stone["row"]):
                return "tile_click:tutorial_stone"
            return "tile_click:other"
        if kind == "card":
            return f"card_select:{action[1]}"
        if kind == "confirm":
            return "button:confirm"
        if kind == "end_turn":
            return "button:end_turn"
        return "other"

    def allows(self, action):
        """``action``: ``("tile", col, row) | ("card", building_type) |
        ("confirm",) | ("end_turn",) | ("other",)``. True immediately when
        the sequencer is finished (D6 zero-overhead path)."""
        if self.sequencer.finished:
            return True
        return self.sequencer.allows(self._action_id(action))

    def allows_end_turn(self):
        """The exact callable ``Session.end_turn`` holds as its gate."""
        return self.allows(("end_turn",))

    def charges_life_on_base_hit(self, round_num):
        """True (charge the life, normal rules) unless the tutorial is
        actively holding on round 0's scripted first-loss step (TU-9: the
        tutorial round is round 0, not round 1) AND the script says that
        loss is free (``first_loss_costs_life: false``, TU-7). A pure read —
        never mutates the sequencer; the actual advance past this step
        happens via ``on_round_end``'s event feed."""
        if self.sequencer.finished or round_num != 0:
            return True
        step = self.sequencer.current
        if step is None or not step.flags.get("is_scripted_loss", False):
            return True
        return self._first_loss_costs_life

    # -- event feed -----------------------------------------------------------

    def on_tile_clicked(self, col, row):
        if self._flute is not None and (
                col, row) == (self._flute["col"], self._flute["row"]):
            self.sequencer.advance("tile_clicked:tutorial_flute")
            return
        if self._stone is not None and (
                col, row) == (self._stone["col"], self._stone["row"]):
            self.sequencer.advance("tile_clicked:tutorial_stone")

    def on_card_selected(self, building_type):
        self.sequencer.advance(f"building_selected:{building_type}")

    def on_building_placed(self, building_type):
        """The round-1 economy building counts toward
        ``Tutorial.economy_buildings_required`` before advancing — the
        running counter lets a required count > 1 hold off the End-Turn
        unlock until every required placement has landed. Any OTHER building
        type (round-2's defence placement, TU-7) advances the sequencer on a
        single placement — additive, the economy-counting path is
        untouched."""
        if building_type == ECONOMY_BUILDING_TYPE:
            self._economy_placed += 1
            if self._economy_placed >= self._required:
                self.sequencer.advance(f"building_placed:{building_type}")
            return
        self.sequencer.advance(f"building_placed:{building_type}")

    def on_panel_closed(self):
        """TU-8 Fix 1/Fix 2: fired from every host panel-close path that did
        NOT just land a placement. Either advances the dedicated
        close-panel-hint step (flute chain only, ``advance_on:
        "panel_closed"``) or reverts the card/Confirm steps back to their
        tile step (``revert_on: "panel_closed"``) — whichever the CURRENT
        step is wired for; a no-op otherwise (e.g. mid the message box, or
        any panel mode the script doesn't gate)."""
        if not self.sequencer.advance("panel_closed"):
            self.sequencer.revert("panel_closed")

    def on_message_dismissed(self):
        mid = self.sequencer.message_id()
        if mid is not None:
            self.sequencer.advance(f"message_dismissed:{mid}")

    def on_end_turn(self):
        self.sequencer.advance("end_turn")

    def on_round_end(self, round_num):
        """Notified from ``Session._begin_round_end`` on EVERY road to
        ROUND_END (TU-7); ``round_num`` isn't needed in the event id itself —
        only one step in the whole script ever has ``advance_on ==
        "round_end"``, so this is harmless outside the scripted round-1 "wait
        for the loss" step (``advance`` no-ops unless it matches the CURRENT
        step, D6's zero-overhead principle)."""
        self.sequencer.advance("round_end")

    def skip(self):
        self.sequencer.skip()

    # -- queries for the host -------------------------------------------------

    @property
    def message_visible(self):
        return self.sequencer.message_id() is not None

    def message_text(self):
        mid = self.sequencer.message_id()
        return None if mid is None else self._messages.get(mid)

    def banner_text(self):
        """TU-8 Fix 2: the CURRENT step's non-modal banner text, resolved
        via its ``flags["banner"]`` key against the script's ``messages``
        map — or None when the current step carries no banner / the
        tutorial is finished. Never the modal ``message`` path
        (``message_text``) — a banner must never consume the click it is
        instructing the player to make."""
        step = self.sequencer.current
        if step is None:
            return None
        mid = step.flags.get("banner")
        return None if mid is None else self._messages.get(mid)

    def skippable(self):
        return self.sequencer.skippable

    def highlight_targets(self):
        """Passthrough for the overlay-submit code to resolve into rects."""
        return self.sequencer.highlight_ids()

    def tile_highlight_targets(self):
        """``(col, row)`` pairs for the current step's tile highlights (0 or
        1 entries) — resolves ``"tile:tutorial_flute"``/``"tile:
        tutorial_stone"`` (TU-7) against their bound markers."""
        out = []
        for hid in self.highlight_targets():
            if hid == "tile:tutorial_flute" and self._flute is not None:
                out.append((self._flute["col"], self._flute["row"]))
            elif hid == "tile:tutorial_stone" and self._stone is not None:
                out.append((self._stone["col"], self._stone["row"]))
        return out

    def ui_highlight_rects(self, panel, hud):
        """Resolve highlight target ids into screen rects for the UI-box
        highlight overlay (card / Confirm / End Turn / the panel's own Close,
        TU-8), skipping any that resolve to ``None`` (panel not in the right
        mode yet — never crashes mid-transition)."""
        out = []
        for hid in self.highlight_targets():
            rect = None
            if hid.startswith("card:"):
                rect = panel.card_rect(hid.split(":", 1)[1])
            elif hid == "button:confirm":
                rect = panel.confirm_rect()
            elif hid == "button:end_turn":
                rect = hud.end_turn.rect
            elif hid == "button:close":
                rect = panel.close_rect()
            if rect is not None:
                out.append(rect)
        return out
