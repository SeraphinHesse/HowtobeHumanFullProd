"""``TutorialDirector`` — binds the engine's game-agnostic step-sequencer
(``engine.tutorial``) to real tiles/cards/buttons (Phase TU-6).

This is where "flute"/"musician"/"economy" vocabulary lives — never in
``engine/tutorial.py`` (D2). Reads ``data/tutorial/tutorial.json`` (TU-1's
schema) and the map doc's ``tutorial_flute`` marker; auto-skips (empty
sequencer, one logged warning, never raises) when either is missing/invalid
so an old/unpainted map is always fully playable.
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
    """Load + validate data/tutorial/tutorial.json into (skippable, messages,
    steps), or None on any load/validation failure (never raises)."""
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
             flags=dict(s["flags"]))
        for s in doc["steps"])
    return doc["skippable"], doc["messages"], steps


class TutorialDirector:
    def __init__(self, data_dir, map_doc, tutorial_balance):
        self._flute = map_doc.tutorial_flute  # nullable {"col", "row"}
        self._messages = {}
        self._required = 0
        self._economy_placed = 0

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

        skippable, messages, steps = loaded
        self._messages = messages
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

    # -- event feed -----------------------------------------------------------

    def on_tile_clicked(self, col, row):
        if self._flute is not None and (
                col, row) == (self._flute["col"], self._flute["row"]):
            self.sequencer.advance("tile_clicked:tutorial_flute")

    def on_card_selected(self, building_type):
        self.sequencer.advance(f"building_selected:{building_type}")

    def on_building_placed(self, building_type):
        """Only the guided chain's economy building counts; the running
        counter lets ``Tutorial.economy_buildings_required`` > 1 hold off the
        End-Turn unlock until every required placement has landed."""
        if building_type != ECONOMY_BUILDING_TYPE:
            return
        self._economy_placed += 1
        if self._economy_placed >= self._required:
            self.sequencer.advance(f"building_placed:{building_type}")

    def on_message_dismissed(self):
        mid = self.sequencer.message_id()
        if mid is not None:
            self.sequencer.advance(f"message_dismissed:{mid}")

    def on_end_turn(self):
        self.sequencer.advance("end_turn")

    def skip(self):
        self.sequencer.skip()

    # -- queries for the host -------------------------------------------------

    @property
    def message_visible(self):
        return self.sequencer.message_id() is not None

    def message_text(self):
        mid = self.sequencer.message_id()
        return None if mid is None else self._messages.get(mid)

    def skippable(self):
        return self.sequencer.skippable

    def highlight_targets(self):
        """Passthrough for the overlay-submit code to resolve into rects."""
        return self.sequencer.highlight_ids()

    def tile_highlight_targets(self):
        """``(col, row)`` pairs for the current step's tile highlights (0 or
        1 entries) — resolves ``"tile:tutorial_flute"`` against the bound
        marker."""
        out = []
        for hid in self.highlight_targets():
            if hid == "tile:tutorial_flute" and self._flute is not None:
                out.append((self._flute["col"], self._flute["row"]))
        return out

    def ui_highlight_rects(self, panel, hud):
        """Resolve highlight target ids into screen rects for the UI-box
        highlight overlay (card / Confirm / End Turn), skipping any that
        resolve to ``None`` (panel not in the right mode yet — never crashes
        mid-transition)."""
        out = []
        for hid in self.highlight_targets():
            rect = None
            if hid.startswith("card:"):
                rect = panel.card_rect(hid.split(":", 1)[1])
            elif hid == "button:confirm":
                rect = panel.confirm_rect()
            elif hid == "button:end_turn":
                rect = hud.end_turn.rect
            if rect is not None:
                out.append(rect)
        return out
