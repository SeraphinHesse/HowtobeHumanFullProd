"""DebugRecorder — the ONE telemetry sink. Pure stdlib + ``game.core``/metrics.

There is no event bus (this repo deliberately has none — ``game/core/CLAUDE.md``:
point-to-point callbacks). A recorder hangs off ``Session.debug``, ``None`` by
default, exactly like ``tutorial_director``. Every emit site is
``if <recorder> is not None: <recorder>.<call>(...)``, so debug-off costs one
attribute check and a bare ``Session`` built by a logic test is untouched.

**Everything here is OBSERVATION.** Nothing in this module mutates gameplay
state. In particular the potential-income sweep uses the pure ``yield_amount()``
and never ``collect_income()`` — see ``metrics.py``.

Outputs land in ``out_dir`` (``logs/`` at repo root for a real run; a tempdir in
tests — nothing here reads or writes ``data/``):

    <run_id>-events.jsonl   one JSON object per line, the causal trace
    <run_id>-rounds.csv     one row per round, header == metrics.ROUND_FIELDS
    <run_id>-summary.md     the markdown digest
    <run_id>-report.html    one self-contained file, inline-SVG charts
"""
import json
import time
from datetime import datetime
from pathlib import Path

from . import report
from .events import (
    CHEAT, KIND_LEVEL, LEVEL_BASIC, LEVELS, PAYDAY, ROUND_SUMMARY, RUN_END,
    SPEND_PLACE, WAVE_START,
)
from .metrics import (
    new_accum, payday_start_metrics, round_breakdown, round_summary,
)

#: Which artifacts ``close()`` writes. ``outputs=None`` means all four.
ALL_OUTPUTS = ("jsonl", "csv", "md", "html")

_SUFFIX = {
    "jsonl": "-events.jsonl",
    "csv": "-rounds.csv",
    "md": "-summary.md",
    "html": "-report.html",
}


def default_run_id(prefix="run"):
    """A timestamped slug, unique enough for one run per second."""
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


class DebugRecorder:
    """Level-gated JSONL event sink + per-round balance accumulator.

    A recorder is NEVER constructed at level 0 — call sites guard on
    ``is None`` instead, which is what keeps debug-off byte-identical.
    """

    def __init__(self, out_dir, level=LEVEL_BASIC, run_id=None, outputs=None):
        if level not in LEVELS:
            raise ValueError(f"debug level must be one of {LEVELS}: {level!r}")
        self.level = int(level)
        self.run_id = run_id or default_run_id()
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.outputs = frozenset(ALL_OUTPUTS if outputs is None else outputs)
        self.paths = {k: self.out_dir / f"{self.run_id}{sfx}"
                      for k, sfx in _SUFFIX.items() if k in self.outputs}

        #: The finished per-round rows (``metrics.ROUND_FIELDS``-keyed).
        self.rounds = []
        #: Per-round by-building-type breakdowns, parallel to ``rounds``.
        self.breakdowns = []

        self._state = None
        self._frame = 0
        self._t0 = time.monotonic()
        self._buf = []
        self._acc = new_accum()
        self._spend_by_reason = {}
        self._start = None
        self._cheated = False
        self._closed = False
        self._written = {}

    # -- host wiring -------------------------------------------------------
    def bind(self, state):
        """Bind the ``RunState`` ``emit`` stamps ``round``/``phase`` from."""
        self._state = state
        return self

    def set_frame(self, frame):
        """Stamp the host's frame counter (a cheap int set, called per frame)."""
        self._frame = frame

    # -- the event stream --------------------------------------------------
    def emit(self, kind, **fields):
        """Record one event. Dropped when ``KIND_LEVEL[kind] > self.level``;
        an unknown kind raises ``ValueError`` (typo guard — a silently ignored
        misspelt kind is indistinguishable from a feature that never fired)."""
        min_level = KIND_LEVEL.get(kind)
        if min_level is None:
            raise ValueError(f"unknown debug event kind: {kind!r}")

        # Accumulator side-effects run before the level gate so a level change
        # can never silently change what the round row reports.
        if kind == WAVE_START:
            self._acc["wave_size"] = fields.get("wave_size", 0) or 0
            self._acc["enemy_tier"] = fields.get("enemy_tier", 0) or 0
        elif kind == CHEAT:
            self._cheated = True
            self._acc["cheated"] = 1

        if min_level > self.level:
            return

        rec = {
            "t": kind,
            "round": getattr(self._state, "round_num", 0),
            "phase": self._phase_name(),
            "frame": self._frame,
            "wall_ms": int((time.monotonic() - self._t0) * 1000),
        }
        rec.update(fields)
        # default=str: telemetry must never crash the game on an exotic value.
        self._buf.append(json.dumps(rec, default=str))

    def _phase_name(self):
        phase = getattr(self._state, "phase", None)
        return getattr(phase, "name", "" if phase is None else str(phase))

    def flush(self):
        """Append the buffered lines to the JSONL file and clear the buffer."""
        if not self._buf:
            return
        path = self.paths.get("jsonl")
        if path is not None:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(self._buf) + "\n")
        self._buf = []

    # -- accumulators ------------------------------------------------------
    def note_lightning(self, dmg, hits):
        """The no-shooter accumulator. Lightning has no shooter, so its damage
        is never credited to ``RoundStats`` and is invisible to ``dmg_dealt``.

        ``dmg`` is the TOTAL damage the strike applied (the flat per-enemy
        damage times ``hits``); ``hits`` is the number of enemies inside the
        radius. A whiff (``hits == 0``) still costs the cooldown, so it is
        worth calling with zeros — it keeps the strike count honest."""
        self._acc["dmg_dealt_lightning"] += int(dmg)
        self._acc["lightning_hits"] += int(hits)

    def note_love_spent(self, amount, reason):
        """Love the player spent this round (placements / unlocks / research).
        ``reason`` is one of ``events.SPEND_*``; a ``SPEND_PLACE`` also bumps
        ``buildings_placed``. Every reason sums into ``love_spent_buildings``."""
        amount = int(amount)
        self._acc["love_spent_buildings"] += amount
        if reason == SPEND_PLACE:
            self._acc["buildings_placed"] += 1
        self._spend_by_reason[reason] = (
            self._spend_by_reason.get(reason, 0) + amount)

    def note_base_hit(self, waived=False):
        """An enemy reached the hole. ALWAYS a ``leak``; a life is only lost
        when the tutorial's scripted free-loss waiver did not apply. A base
        breach applies NO HP damage — ``lives_lost`` is never fused into
        ``dmg_taken_buildings``."""
        self._acc["leaks"] += 1
        if not waived:
            self._acc["lives_lost"] += 1

    def note_kill(self):
        self._acc["kills"] += 1

    def note_kidnap(self):
        self._acc["kidnaps"] += 1

    def note_spawn(self, n=1):
        self._acc["enemies_spawned"] += int(n)

    # -- payday lifecycle (three hooks, called from run_payday) -------------
    def on_payday_start(self, state, tilemap, core_balance, built):
        """Called BEFORE payday step 2's ``RoundStats`` snapshot, so the
        this-round damage counters are still live, and the potential ledger can
        see which occupants died during the wave."""
        self._start = payday_start_metrics(state, tilemap, core_balance, built)

    def on_payday_story(self, state):
        """Called immediately after payday step 3. The Boss1B/3B payouts are
        paid silently and never appear in ``income_events``, so ``story_income``
        is measured as the exact love delta across that step."""
        if self._start is not None:
            self._acc["story_income"] = state.love - self._start["love_start"]

    def on_payday_end(self, state, tilemap=None):
        """Called immediately after payday step 6 (painters) — so
        ``income_events`` holds base + yields + upkeep + painter payouts — and
        BEFORE step 11's ``round_num += 1``. Appends the finished row, emits
        ``round_summary`` + ``payday``, then flushes."""
        start, self._start = self._start, None
        if start is None:
            self._reset_round()
            return
        row = round_summary(start, state, self._acc)
        self.rounds.append(row)
        breakdown = round_breakdown(start, state, row)
        breakdown["love_spent_by_reason"] = dict(self._spend_by_reason)
        self.breakdowns.append(breakdown)

        self.emit(ROUND_SUMMARY, **row)
        self.emit(
            PAYDAY,
            income_actual=row["income_actual"],
            income_potential=row["income_potential"],
            income_lost_to_damage=row["income_lost_to_damage"],
            upkeep_actual=row["upkeep_actual"],
            upkeep_potential=row["upkeep_potential"],
            upkeep_unpaid_from_deaths=row["upkeep_unpaid_from_deaths"],
            story_income=row["story_income"],
            painter_income=row["painter_income"],
            love_end=row["love_end"],
            income_by_type=breakdown["income_actual_by_type"],
            upkeep_by_type=breakdown["upkeep_actual_by_type"],
            dmg_dealt_by_type=breakdown["dmg_dealt_by_type"],
            dmg_taken_by_type=breakdown["dmg_taken_by_type"],
        )
        self._reset_round()
        self.flush()

    def _reset_round(self):
        self._acc = new_accum()
        # ``cheated`` is sticky for the rest of the run: a cheated run must be
        # visibly tagged or it silently pollutes the balance data.
        self._acc["cheated"] = 1 if self._cheated else 0
        self._spend_by_reason = {}

    # -- teardown ----------------------------------------------------------
    def close(self, outcome=None):
        """Flush the stream, then write the CSV / markdown / HTML artifacts.
        Returns ``{"jsonl": Path, "csv": Path, ...}`` for what was written.
        Idempotent — a second ``close()`` is a no-op returning the same dict."""
        if self._closed:
            return self._written
        self._closed = True
        self.emit(RUN_END, outcome=outcome, rounds=len(self.rounds))
        self.flush()

        written = {}
        if "jsonl" in self.outputs:
            path = self.paths["jsonl"]
            path.touch()          # an empty run still leaves an honest file
            written["jsonl"] = path
        if "csv" in self.outputs:
            report.write_rounds_csv(self.rounds, self.paths["csv"])
            written["csv"] = self.paths["csv"]
        if "md" in self.outputs:
            report.write_summary(self.rounds, self.breakdowns, self.paths["md"],
                                 run_id=self.run_id, outcome=outcome)
            written["md"] = self.paths["md"]
        if "html" in self.outputs:
            report.write_html(self.rounds, self.paths["html"],
                              run_id=self.run_id, outcome=outcome)
            written["html"] = self.paths["html"]
        self._written = written
        return written
