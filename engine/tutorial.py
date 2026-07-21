"""A pure step-sequencer for a scripted guided tutorial (Phase TU-6).

No pygame, no game vocabulary (no "flute", no "musician", no "confirm button")
— every id here is an OPAQUE string chosen by the data script
(``data/tutorial/tutorial.json``) and interpreted only by the game-side
``game.tutorial.director.TutorialDirector``. This mirrors ``video_playback``'s
"pure clock the caller gives game meaning to" shape (``engine/CLAUDE.md``).

``TutorialSequencer`` walks a fixed ``list[Step]`` one at a time: the current
step names what event ends it (``advance_on``), what input is allowed while it
holds (``allow``), and what to highlight (``highlight``)/show
(``message``/``flags``). ``advance(event_id)`` only moves past the CURRENT step
when the id matches — an unrelated event is a no-op. ``skip()`` is terminal and
only takes effect when the script marked itself ``skippable``; once
finished (skipped or past the last step) every query resolves to the
zero-overhead "tutorial is over" answer, at the cost of one bool check per
gated call site (D6).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Step:
    id: str
    message: str | None = None
    highlight: tuple[str, ...] = ()
    advance_on: str | None = None
    allow: tuple[str, ...] = ()
    flags: dict = field(default_factory=dict)


class TutorialSequencer:
    """Walks a fixed step list. ``skipped`` and "past the last step" are both
    terminal, folded into the single ``finished`` state every consumer checks."""

    def __init__(self, steps, *, skippable=True):
        self._steps = list(steps)
        self._skippable = skippable
        self._index = 0
        self._skipped = False

    @property
    def active(self):
        """Not skipped, not past the last step."""
        return not self.finished

    @property
    def finished(self):
        """Skipped OR past the last step — the zero-overhead terminal state."""
        return self._skipped or self._index >= len(self._steps)

    @property
    def current(self):
        if self.finished:
            return None
        return self._steps[self._index]

    @property
    def skippable(self):
        return self._skippable

    def advance(self, event_id):
        """Advance past ``current`` iff ``current.advance_on == event_id``.
        No-op (returns False) if finished, if ``current.advance_on`` is None,
        or the id doesn't match — an unrelated event never advances the
        chain."""
        step = self.current
        if step is None or step.advance_on is None:
            return False
        if step.advance_on != event_id:
            return False
        self._index += 1
        return True

    def skip(self):
        """Terminal, only if ``skippable``; a no-op otherwise (defensive: no
        UI should ever call this when the script disallows it, but the
        engine does not trust the caller)."""
        if self._skippable:
            self._skipped = True

    def allows(self, action_id):
        """True when finished (D6 zero-overhead path) or when ``action_id``
        is in ``current.allow``; False otherwise."""
        if self.finished:
            return True
        return action_id in self.current.allow

    def highlight_ids(self):
        """The current step's highlight target ids, or ``()`` when finished."""
        if self.finished:
            return ()
        return self.current.highlight

    def message_id(self):
        """The current step's message id, or ``None`` when finished."""
        if self.finished:
            return None
        return self.current.message

    def flags(self):
        """A copy of the current step's flags dict, or ``{}`` when finished."""
        if self.finished:
            return {}
        return dict(self.current.flags)
