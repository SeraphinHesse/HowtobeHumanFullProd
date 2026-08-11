"""game.debug — structured run telemetry for balancing + LLM debugging.

A PURE package: no pygame, no ``data/`` read or write (a ``TestPurity`` in
``tools/tests/test_debug_log.py`` pins the pygame half). It may import
``game.core`` + ``game.buildings.components``, mirroring what ``payday.py``
already does, and nothing else from the game.

Everything here is OBSERVATION. With ``Session.debug is None`` — the default —
no code path in the game changes at all; every emit site is
``if <recorder> is not None: <recorder>.<call>(...)``.

Read ``events.py``'s module docstring for the event-kind contract: it documents
every kind, every field, and exactly what each number does and does not include.
"""
from .events import (
    KIND_LEVEL, LEVEL_BASIC, LEVEL_OFF, LEVEL_VERBOSE, LEVELS,
)
from .metrics import ROUND_FIELDS
from .recorder import ALL_OUTPUTS, DebugRecorder, default_run_id

__all__ = [
    "DebugRecorder", "LEVELS", "LEVEL_OFF", "LEVEL_BASIC", "LEVEL_VERBOSE",
    "KIND_LEVEL", "ROUND_FIELDS", "ALL_OUTPUTS", "default_run_id",
]
