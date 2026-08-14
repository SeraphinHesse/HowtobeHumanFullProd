"""Fading game log (Phase 10J) — port of the prototype's ``src/ui/game_log.py``.

Pure logic: short event messages ("<name> has been killed", unlock refusals,
painter losses) stack bottom-left just above the phase banner, newest first,
and fade out. Timings/colour are the prototype's hard-coded constants
(LIFETIME 4.0 s, fade from 3.0 s, max 5 lines, 12 px step, (220, 200, 155)).
The fade uses the 10J RGBA ``HudText`` alpha.

Posts arrive two ways: direct ``post()`` calls from the UI layer, and the
``drain(state)`` sweep over ``RunState.log_events`` (the drained-by-UI ledger
contract) so pure core code can log without importing ``game/ui``.

10L-B (plan R3, PINNED): ONE id, ``log`` — a rect-holder for the line anchor
(``rect``), ``font_key``, ``text_color`` (the age-fade base colour) and
``visible``. ``get_style_holder()`` exposes the SAME mutable object
``skinning.apply()`` mutates. The line-feeding loop (``post``/``drain``/
``update``, the LIFETIME/FADE_START timings) stays code-driven and never
reads the holder — only ``submit()`` (rendering) does.
"""
from types import SimpleNamespace

from .skinning import ScreenSkinning
from .widgets import submit_text

LIFETIME = 4.0     # seconds a message lives
FADE_START = 3.0   # age at which the fade begins (linear to LIFETIME)
MAX_MESSAGES = 5
_COLOR = (220, 200, 155)
# UR-5 fix (triage Step 1, bucket "already 640-scale"): UR-2 halved this 12 ->
# 6 with the surface, but a text LINE STEP is a font-scale quantity and
# data/ui/fonts.json did not halve. Measured: the log draws at "sm", whose
# layout_h is 11, so all five stacked lines overlapped each other by 5px.
# Back to 12 — one pixel of leading over an 11px line, as before UR-2.
_LINE_STEP = 12
_X = 4
_LIFT = 16         # first line sits view_h - _LIFT (just above the phase label)

SCREEN_ID = "game_log"


class GameLog:
    def __init__(self, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self._messages = []  # [text, age] — newest appended last
        self._style = SimpleNamespace(rect=(_X, 0, 0, 0), font_key="sm",
                                      text_color=_COLOR, visible=True)
        self.ids = {}

    def get_style_holder(self):
        """The mutable ``{rect, font_key, text_color, visible}`` object
        ``skinning.apply("game_log", {"log": ...})`` mutates in place (10L-B)."""
        return self._style

    def post(self, text):
        self._messages.append([text, 0.0])
        if len(self._messages) > MAX_MESSAGES:
            self._messages.pop(0)

    def drain(self, state):
        """Post + clear ``state.log_events`` (messages queued by core code)."""
        for text in state.log_events:
            self.post(text)
        state.log_events.clear()

    def clear(self):
        self._messages.clear()

    def update(self, dt):
        for m in self._messages:
            m[1] += dt
        self._messages = [m for m in self._messages if m[1] < LIFETIME]

    def submit(self, renderer, view_h):
        self._style.rect = (_X, view_h - _LIFT, 0, 0)
        self.ids = {"log": ("label", self._style)}
        self.skinning.apply(self.screen_id, self.ids)
        if not self._style.visible:
            return
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        x, y = self._style.rect[0], self._style.rect[1]
        base = tuple(self._style.text_color[:3])
        for text, age in reversed(self._messages):  # newest at the bottom
            if age <= FADE_START:
                alpha = 255
            else:
                fade = LIFETIME - FADE_START
                alpha = int(255 * max(0.0, 1.0 - (age - FADE_START) / fade))
            submit_text(renderer, text, (x, y), self._style.font_key,
                       base + (alpha,))
            y -= _LINE_STEP
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
