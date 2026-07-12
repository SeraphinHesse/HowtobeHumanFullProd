"""Fading game log (Phase 10J) — port of the prototype's ``src/ui/game_log.py``.

Pure logic: short event messages ("<name> has been killed", unlock refusals,
painter losses) stack bottom-left just above the phase banner, newest first,
and fade out. Timings/colour are the prototype's hard-coded constants
(LIFETIME 4.0 s, fade from 3.0 s, max 5 lines, 12 px step, (220, 200, 155)).
The fade uses the 10J RGBA ``HudText`` alpha.

Posts arrive two ways: direct ``post()`` calls from the UI layer, and the
``drain(state)`` sweep over ``RunState.log_events`` (the drained-by-UI ledger
contract) so pure core code can log without importing ``game/ui``.
"""
from .widgets import submit_text

LIFETIME = 4.0     # seconds a message lives
FADE_START = 3.0   # age at which the fade begins (linear to LIFETIME)
MAX_MESSAGES = 5
_COLOR = (220, 200, 155)
_LINE_STEP = 12
_X = 8
_LIFT = 32         # first line sits view_h - _LIFT (just above the phase label)


class GameLog:
    def __init__(self):
        self._messages = []  # [text, age] — newest appended last

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
        y = view_h - _LIFT
        for text, age in reversed(self._messages):  # newest at the bottom
            if age <= FADE_START:
                alpha = 255
            else:
                fade = LIFETIME - FADE_START
                alpha = int(255 * max(0.0, 1.0 - (age - FADE_START) / fade))
            submit_text(renderer, text, (_X, y), "sm", _COLOR + (alpha,))
            y -= _LINE_STEP
