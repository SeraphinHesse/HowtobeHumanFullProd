"""The editor's test-run engine — Qt-free, pygame-free (TestRunnerPLAN TR-3, D6).

What this module is: a PARSER plus a thin process wrapper. It turns a live
pytest/testgate stream into per-domain counters the panel can render, and into
one ``RunResult`` that TR-4 (report), TR-5 (panel) and TR-6 (ledger credit) all
read. It renders nothing, it launches nothing by itself, and it never imports
Qt — that is what puts its tests in the fast ``core`` tier and lets TR-5 drive a
run from a worker thread and marshal the callbacks itself.

Three rules, and none of them is decorative:

1. **IDENTITY COMES FROM THE NODE-ID, NEVER FROM STREAM POSITION.**
   ``pytest.ini`` pins ``-n auto --dist loadfile``: files finish out of order and
   interleave across workers, so a ``[gw3]`` line for ``test_boss.py`` can sit
   between two ``test_enemies.py`` lines. There is no "current file" cursor here
   and there must never be one. (Same rule as ``tools/testgate.py``'s design
   rule 1.)

2. **THIS MODULE NEVER INVENTS A VERDICT.** ``RunResult.gate_line`` is populated
   only when a real ``GATE …`` line was seen in the stream. TR-6's ledger credit
   depends on that: a recorded verdict testgate did not pronounce is worse than
   no record at all. A per-area re-run is explicitly NOT a gate (D2), so its
   ``gate_line`` is always ``None``.

3. **COLOR IS A FAILURE SHAPE.** Every line is ANSI-stripped before matching —
   ``tools/testgate.py`` printed PASS over two red tests for a whole session
   because ``\\x1b[31mFAILED`` is invisible to ``^FAILED``. The child env also
   disables color; both, because the next color-forcing knob will not be one we
   have heard of.

Why one run is now both live and authoritative (reconciliation R2): testgate
grew a ``--stream`` mode. ``build_command(None)`` is therefore the real gate
command with ``--stream`` appended — testgate echoes every ``-v`` node-id line
as it arrives and still prints its own authoritative ``GATE …`` verdict at the
end. There is no separate "stream command"; the earlier ``build_stream_command``
is gone.

The short-report regexes below are COPIED in shape from ``tools/testgate.py``
(cited per regex), deliberately not imported: they are underscore-private there,
and importing them would make any edit to that file a silent break here.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from tools.test_domains import DOMAIN_LABELS, DOMAINS, domain_for

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = "tools/tests"

#: The reserved bucket for a module ``tools/test_domains.py`` does not claim.
#: An unmapped module must SURFACE, never vanish: a row that quietly reads
#: "0 tests" looks like success.
UNKNOWN = "unknown"

#: How many raw lines are kept for the report's traceback section.
RAW_TAIL = 200


# --------------------------------------------------------------------------
# Line shapes
# --------------------------------------------------------------------------

#: ANSI SGR escapes — stripped before ANY matching (tools/testgate.py:104).
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

#: Per-test verbose line, xdist form. This is the live-progress signal of a
#: `-n auto` run under `-v`:  "[gw3] [ 45%] PASSED tools/tests/test_boss.py::T::t"
_VERBOSE_XDIST = re.compile(
    r"^\[gw\d+\]\s+\[\s*\d+%\]\s+(?P<outcome>[A-Z]+)\s+(?P<nodeid>\S+)")

#: Per-test verbose line, non-xdist form (`-n0`, which CI's heavy shards use —
#: tools/ci_shards.py:66):  "tools/tests/test_boss.py::T::t PASSED [ 45%]"
_VERBOSE_PLAIN = re.compile(
    r"^(?P<nodeid>\S+::\S+)\s+(?P<outcome>[A-Z]+)(?:\s+\[\s*\d+%\])?\s*$")

#: Short-report FAILED/ERROR (`-rfEsX`; tools/testgate.py:68). The " - message"
#: tail is optional and is the failure's short reason — TR-4 puts it in the
#: report, so unlike testgate we KEEP it.
_FAILED = re.compile(
    r"^(?P<outcome>FAILED|ERROR)\s+(?P<nodeid>\S+?)(?:\s+-\s+(?P<message>.*))?$")

#: Short-report SUBFAILED (tools/testgate.py:76-78) — outcome first, params in
#: parentheses, node-id trailing. THE PARAMS ARE PART OF THE KEY: one test can
#: fail N subtests independently, and collapsing them lets N-1 vanish.
_SUBFAILED = re.compile(
    r"^SUB(?P<outcome>FAILED|ERROR)(?P<params>\(.*\))?\s+(?P<nodeid>\S+?)"
    r"(?:\s+-\s+(?P<message>.*))?$")

#: Short-report SKIPPED (tools/testgate.py:84) — a DIFFERENT shape. Parsing it
#: with the FAILED pattern captures "[1]" as the node-id. Keyed by FILE +
#: REASON, never the line number (adding an import shifts the line).
_SKIPPED = re.compile(
    r"^SKIPPED\s+\[\d+\]\s+(?P<file>[^\s:]+):\d+:\s*(?P<reason>.*)$")

#: The tally line (tools/testgate.py:89). SUMMED, not first-match: "5 failed,
#: 1170 passed, …" and a `.search` grabs the 5. "N subtests passed" is NOT
#: counted — those digits are followed by "subtests", not "passed".
_TOTAL = re.compile(r"(\d+) (?:passed|failed)")

#: testgate's own verdict lines (tools/testgate.py:176/182/219/228).
_GATE = re.compile(r"^GATE\s+(?P<outcome>PASS|FAIL|ABORT|INFO)\b")
_GATE_NEW_FAILURE = re.compile(r"^NEW FAILURE\s+(?P<nodeid>\S+)\s*$")
_GATE_SKIP = re.compile(r"^UNEXPECTED SKIP\s+(?P<file>[^\s:]+):\s*(?P<reason>.*)$")

#: outcome token -> counter bucket. An outcome NOT in here is not guessed at:
#: parse_line returns None rather than inventing a meaning for it.
_BUCKET = {
    "PASSED": "passed",
    "XFAIL": "passed",
    "XPASS": "passed",
    "FAILED": "failed",
    "ERROR": "failed",
    "SKIPPED": "skipped",
    "SUBFAILED": "subfailed",
    "SUBERROR": "subfailed",
}

#: Precedence when the same node-id reports twice (the verbose line AND the
#: short report, or a subtest failure followed by the test's own outcome). The
#: worse outcome wins and the counters are re-bucketed, so nothing double-counts.
_RANK = {"passed": 0, "skipped": 1, "subfailed": 2, "failed": 3}

#: Failure.kind values.
_KIND_FOR_BUCKET = {"failed": "failed", "subfailed": "subfailed"}


def posix(nodeid: str) -> str:
    """Normalise separators. pytest reports paths with the PLATFORM separator,
    so a Windows run would match nothing a Linux-authored table lists
    (tools/testgate.py:137-141)."""
    return nodeid.replace("\\", "/")


def module_of(nodeid: str) -> str:
    """"tools/tests/test_boss.py::T::test_x" -> "test_boss.py"."""
    return posix(nodeid).split("::")[0].rsplit("/", 1)[-1]


def _domain_of_module(module: str) -> str:
    """The domain a test module belongs to, or ``"unknown"``.

    ``tools.test_domains.domain_for`` RAISES ``KeyError`` for an unmapped module
    — that hard error is right for the table's own test, and wrong for a live
    run: the panel must surface the stray module, not crash mid-stream. Any
    exception (and any falsy return) becomes ``UNKNOWN`` here, and the module is
    listed in ``RunResult.unknown_modules``.
    """
    try:
        return domain_for(module) or UNKNOWN
    except Exception:
        return UNKNOWN


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def build_command(domain: str | None = None) -> list[str]:
    """The command a run launches. This IS the canonical command (R2).

    ``domain is None`` -> the real gate, in streaming mode. Streaming is what
    makes one run both live (node-id lines as they finish) and authoritative
    (testgate's own ``GATE …`` line at the end), so the editor never needs a
    second pass and never computes a verdict itself.

    ``domain`` -> a per-area re-run: pytest directly, over exactly that domain's
    files. It is NOT a gate (D2) and produces no ``GATE`` line. ``-v`` for the
    same reason the gate streams: the panel needs node-ids to fill rows.
    """
    if domain is None:
        return [sys.executable, "tools/testgate.py", "check", "--stream"]
    if domain not in DOMAINS:
        known = ", ".join(DOMAINS)
        extra = (" ('unknown' is a reporting bucket, not a runnable domain)"
                 if domain == UNKNOWN else "")
        raise ValueError(f"unknown test domain {domain!r}{extra}; known: {known}")
    files = sorted(f"{TESTS_DIR}/{name}" for name in DOMAINS[domain]
                   if (REPO / TESTS_DIR / name).exists())
    return [sys.executable, "-m", "pytest", "-v", "--no-header", "-rfEsX", *files]


def child_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a run's child gets (tools/testgate.py:114-118, plus one).

    Color OFF whatever the agent shell exports (pytest obeys FORCE_COLOR even
    when piped), and ``PYTHONUNBUFFERED=1`` — without it Python block-buffers
    stdout off a tty and the panel shows nothing until exit, the same lesson
    ``editor/run_controls.py`` already learned (editor/CLAUDE.md:100).
    """
    env = {k: v for k, v in (base if base is not None else os.environ).items()
           if k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env["NO_COLOR"] = "1"
    env["PY_COLORS"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    return env


# --------------------------------------------------------------------------
# Events + the result contract
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    """One parsed line. ``kind`` is the only field callers should switch on."""
    kind: str            # "test" | "failure" | "skip" | "tally" | "gate"
    line: str = ""       # the ANSI-stripped, stripped line
    nodeid: str = ""     # POSIX, "" when the shape carries none
    module: str = ""     # "test_boss.py"
    domain: str = ""     # a test_domains key, or "unknown"
    outcome: str = ""    # the verbatim outcome token
    params: str = ""     # subtest params incl. parens, else ""
    message: str = ""    # short reason after " - ", or a skip reason
    count: int = 0       # tally lines only


@dataclass(frozen=True)
class Failure:
    nodeid: str      # "tools/tests/test_boss.py::T::test_x" (POSIX)
    module: str      # "test_boss.py"
    domain: str      # a test_domains key, or "unknown"
    kind: str        # "failed" | "subfailed" | "unexpected_skip"
    params: str = ""   # subtest params verbatim incl. parens, else ""
    message: str = ""  # short reason after " - ", or the skip reason, else ""


@dataclass(frozen=True)
class DomainResult:
    domain: str                    # a test_domains key, or "unknown"
    state: str                     # "pending" | "running" | "passed" | "failed"
    done: int                      # passed + failed + subfailed + skipped
    total: int | None              # None unless known — TR-5 counts UP
    passed: int
    failed: int                    # FAILED + ERROR at test level
    subfailed: int
    skipped: int
    modules: tuple[str, ...]       # basenames seen, sorted
    failures: tuple[Failure, ...]  # this domain's, in arrival order


@dataclass(frozen=True)
class RunResult:
    command: tuple[str, ...]        # the canonical build_command(domain)
    stream_command: tuple[str, ...]  # what was actually launched (== command
                                     # unless TestRun was given command=)
    domain: str | None              # None == full run; else the re-run's domain
    verdict: str                    # "pass" | "fail" | "cancelled" | "error"
    gate_line: str | None           # verbatim "GATE PASS …"/"GATE FAIL …" iff
                                    # the stream carried one; ALWAYS None for a
                                    # domain re-run (D2)
    completed: bool                 # ended AND a tally or gate verdict parsed
    cancelled: bool
    returncode: int | None
    total_ran: int                  # from the tally line, 0 if absent
    started_at: float
    finished_at: float
    duration_s: float
    domains: dict[str, DomainResult]
    failures: tuple[Failure, ...]     # flat, all domains, arrival order
    unknown_modules: tuple[str, ...]  # sorted; empty on a healthy run
    raw_tail: tuple[str, ...]         # last RAW_TAIL raw lines


def parse_line(line: str) -> Event | None:
    """One line in, one Event or ``None``. Pure and stateless.

    ``None`` means "not an event": progress dots, headers, tracebacks, blank
    lines, ``[gw2] node down``, and any outcome token we do not recognise (we
    do not guess at unknown outcomes).
    """
    text = _ANSI.sub("", line).strip()
    if not text:
        return None

    if m := _GATE.match(text):
        return Event(kind="gate", line=text, outcome=m["outcome"])
    if m := _GATE_NEW_FAILURE.match(text):
        nodeid = posix(m["nodeid"])
        module = module_of(nodeid)
        return Event(kind="failure", line=text, nodeid=nodeid, module=module,
                     domain=_domain_of_module(module), outcome="FAILED")
    if m := _GATE_SKIP.match(text):
        nodeid = posix(m["file"])
        module = module_of(nodeid)
        return Event(kind="skip", line=text, nodeid=nodeid, module=module,
                     domain=_domain_of_module(module),
                     outcome="UNEXPECTED_SKIP", message=m["reason"].strip())
    # SKIPPED before FAILED: the short-report skip has its own shape, and the
    # FAILED pattern would capture "[1]" as its node-id (tools/testgate.py:61-66).
    if m := _SKIPPED.match(text):
        nodeid = posix(m["file"])
        module = module_of(nodeid)
        return Event(kind="skip", line=text, nodeid=nodeid, module=module,
                     domain=_domain_of_module(module), outcome="SKIPPED",
                     message=m["reason"].strip())
    if m := _SUBFAILED.match(text):
        nodeid = posix(m["nodeid"])
        module = module_of(nodeid)
        return Event(kind="failure", line=text, nodeid=nodeid, module=module,
                     domain=_domain_of_module(module),
                     outcome="SUB" + m["outcome"], params=m["params"] or "",
                     message=(m["message"] or "").strip())
    if m := _FAILED.match(text):
        nodeid = posix(m["nodeid"])
        module = module_of(nodeid)
        return Event(kind="failure", line=text, nodeid=nodeid, module=module,
                     domain=_domain_of_module(module), outcome=m["outcome"],
                     message=(m["message"] or "").strip())
    for pattern in (_VERBOSE_XDIST, _VERBOSE_PLAIN):
        if m := pattern.match(text):
            if m["outcome"] not in _BUCKET:
                return None
            nodeid = posix(m["nodeid"])
            module = module_of(nodeid)
            return Event(kind="test", line=text, nodeid=nodeid, module=module,
                         domain=_domain_of_module(module), outcome=m["outcome"])
    if counts := _TOTAL.findall(text):
        return Event(kind="tally", line=text,
                     count=sum(int(n) for n in counts))
    return None


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

class _Domain:
    """Mutable per-domain accumulator; frozen into a DomainResult at finish."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.state = "pending"
        self.passed = self.failed = self.subfailed = self.skipped = 0
        self.total: int | None = None
        self.modules: set[str] = set()
        self.failures: list[Failure] = []

    @property
    def done(self) -> int:
        return self.passed + self.failed + self.subfailed + self.skipped


def _default_spawn(cmd: Sequence[str], env: Mapping[str, str]):
    """The ONE place this module touches subprocess. stderr is MERGED into
    stdout so ordering is preserved and nothing is lost."""
    return subprocess.Popen(
        list(cmd), cwd=str(REPO), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1, env=dict(env))


class TestRun:
    """Drives one run and accumulates per-domain state.

    Tests drive it with :meth:`feed_lines` + :meth:`finish` and never call
    :meth:`run` — nothing in this repo's suite may launch a real test run
    (TestRunnerPLAN §4).
    """

    def __init__(self, domain: str | None = None,
                 command: Sequence[str] | None = None,
                 on_progress: Callable[[str, int, int | None, str], None] | None = None,
                 on_finished: Callable[[RunResult], None] | None = None,
                 spawn: Callable[..., object] | None = None) -> None:
        self.domain = domain
        self.command = tuple(build_command(domain))
        self.stream_command = tuple(command) if command else self.command
        self.on_progress = on_progress
        self.on_finished = on_finished
        self._spawn = spawn or _default_spawn

        self._domains: dict[str, _Domain] = {}
        # A full run shows every known domain from the start (pending rows);
        # a re-run shows only its own.
        for key in (DOMAIN_LABELS if domain is None else (domain,)):
            self._domains[key] = _Domain(key)
        self._counted: dict[tuple[str, str], str] = {}
        self._subfail_placeholder: set[str] = set()
        self._failures: dict[tuple[str, str, str], Failure] = {}
        self._unknown: set[str] = set()
        self._raw: deque[str] = deque(maxlen=RAW_TAIL)
        self._gate_line: str | None = None
        self._gate_outcome: str | None = None
        self._total_ran = 0
        self._saw_tally = False
        self._cancel_requested = False
        self._proc = None
        self.started_at = time.time()
        self.finished_at: float | None = None

    # -- accumulation ------------------------------------------------------

    def _domain(self, key: str) -> _Domain:
        d = self._domains.get(key)
        if d is None:
            d = self._domains[key] = _Domain(key)
        return d

    def _emit(self, d: _Domain) -> None:
        if self.on_progress is not None:
            self.on_progress(d.key, d.done, d.total, d.state)

    def _activate(self, d: _Domain) -> None:
        if d.state == "pending":
            d.state = "running"

    def _count(self, d: _Domain, key: tuple[str, str], bucket: str) -> None:
        prev = self._counted.get(key)
        if prev is None:
            self._counted[key] = bucket
            setattr(d, bucket, getattr(d, bucket) + 1)
            return
        if _RANK[bucket] > _RANK[prev]:
            # The same node-id reported twice (verbose line + short report, or a
            # subtest failure then the test's own outcome). Re-bucket; never add.
            setattr(d, prev, getattr(d, prev) - 1)
            setattr(d, bucket, getattr(d, bucket) + 1)
            self._counted[key] = bucket

    def _record_failure(self, failure: Failure) -> None:
        key = (failure.nodeid, failure.params, failure.kind)
        existing = self._failures.get(key)
        if existing is None:
            self._failures[key] = failure
        elif failure.message and not existing.message:
            self._failures[key] = failure

    def feed(self, line: str) -> None:
        """Parse one raw line, accumulate it, and fire ``on_progress``."""
        self._raw.append(line)
        event = parse_line(line)
        if event is None:
            return

        if event.kind == "gate":
            # Only a real verdict counts. GATE INFO is narration.
            if event.outcome in ("PASS", "FAIL", "ABORT"):
                self._gate_line = event.line
                self._gate_outcome = event.outcome
            return

        if event.kind == "tally":
            self._saw_tally = True
            self._total_ran = max(self._total_ran, event.count)
            if self.domain is not None:
                # A single-domain run's tally IS that domain's total.
                d = self._domain(self.domain)
                d.total = event.count
                self._emit(d)
            return

        if event.domain == UNKNOWN and event.module:
            self._unknown.add(event.module)
        d = self._domain(event.domain)
        if event.module:
            d.modules.add(event.module)
        self._activate(d)

        if event.kind == "skip" and event.outcome == "UNEXPECTED_SKIP":
            # testgate's own verdict on a skip nobody signed off on. A raw
            # `SKIPPED [1] …` short-report line is NOT this: it carries no
            # node-id and no judgement, so it only counts through the verbose
            # per-test line for the same test (which does carry one).
            d.state = "failed"
            self._record_failure(Failure(
                nodeid=event.nodeid, module=event.module, domain=event.domain,
                kind="unexpected_skip", message=event.message))
            self._emit(d)
            return
        if event.kind == "skip":
            self._emit(d)
            return

        bucket = _BUCKET.get(event.outcome)
        if bucket is None:
            return

        key = (event.nodeid, event.params)
        if bucket == "subfailed":
            if event.params and event.nodeid in self._subfail_placeholder:
                # A verbose SUB* line arrived without params and the short
                # report now names them: RENAME the key rather than counting a
                # second subtest failure for the same one.
                placeholder = (event.nodeid, "")
                if self._counted.get(placeholder) == "subfailed":
                    del self._counted[placeholder]
                    self._counted[key] = "subfailed"
                    self._failures.pop((event.nodeid, "", "subfailed"), None)
                    self._subfail_placeholder.discard(event.nodeid)
                else:
                    self._count(d, key, bucket)
            else:
                if not event.params:
                    self._subfail_placeholder.add(event.nodeid)
                self._count(d, key, bucket)
        else:
            self._count(d, key, bucket)

        if bucket in _KIND_FOR_BUCKET:
            d.state = "failed"
            self._record_failure(Failure(
                nodeid=event.nodeid, module=event.module, domain=event.domain,
                kind=_KIND_FOR_BUCKET[bucket], params=event.params,
                message=event.message))
        self._emit(d)

    def feed_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.feed(line)

    # -- finishing ---------------------------------------------------------

    def finish(self, returncode: int | None = 0, cancelled: bool = False) -> RunResult:
        """Freeze the accumulated state into a RunResult and fire on_finished."""
        cancelled = bool(cancelled or self._cancel_requested)
        self.finished_at = time.time()

        for d in self._domains.values():
            if d.state == "running" and not cancelled:
                d.state = "passed"
            # A cancelled run leaves in-flight domains "running" on purpose:
            # they neither passed nor failed, and saying either would be a lie.

        failures = tuple(self._failures.values())
        domains = {
            key: DomainResult(
                domain=key, state=d.state, done=d.done, total=d.total,
                passed=d.passed, failed=d.failed, subfailed=d.subfailed,
                skipped=d.skipped, modules=tuple(sorted(d.modules)),
                failures=tuple(f for f in failures if f.domain == key))
            for key, d in self._domains.items()
            if key != UNKNOWN or d.done or d.failures or d.modules
        }

        # A re-run is NOT a gate (D2): it can never carry a gate line, even if
        # something in its output looked like one.
        gate_line = None if self.domain is not None else self._gate_line
        gate_outcome = None if self.domain is not None else self._gate_outcome
        completed = bool(not cancelled and (self._saw_tally or gate_outcome))

        if cancelled:
            verdict = "cancelled"
        elif gate_outcome in ("FAIL", "ABORT") or failures:
            verdict = "fail"
        elif not completed and returncode not in (0, 1, None):
            # The child died without ever saying what happened.
            verdict = "error"
        else:
            verdict = "pass"

        result = RunResult(
            command=self.command, stream_command=self.stream_command,
            domain=self.domain, verdict=verdict, gate_line=gate_line,
            completed=completed, cancelled=cancelled, returncode=returncode,
            total_ran=self._total_ran, started_at=self.started_at,
            finished_at=self.finished_at,
            duration_s=self.finished_at - self.started_at,
            domains=domains, failures=failures,
            unknown_modules=tuple(sorted(self._unknown)),
            raw_tail=tuple(self._raw))
        if self.on_finished is not None:
            self.on_finished(result)
        return result

    # -- the live path (never exercised by the test suite) ------------------

    def cancel(self) -> None:
        """Ask the run to stop. Safe to call before or during :meth:`run`."""
        self._cancel_requested = True
        self._terminate()

    def _terminate(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:
            pass

    def run(self) -> RunResult:
        """Blocking. The ONLY method that starts a process."""
        self.started_at = time.time()
        self._proc = self._spawn(list(self.stream_command), child_env())
        stdout = getattr(self._proc, "stdout", None)
        if self._cancel_requested:
            self._terminate()
        elif stdout is not None:
            for raw in stdout:
                self.feed(raw.rstrip("\r\n"))
                if self._cancel_requested:
                    self._terminate()
                    break
        returncode = None
        wait = getattr(self._proc, "wait", None)
        if wait is not None:
            try:
                returncode = wait()
            except Exception:
                returncode = None
        return self.finish(returncode=returncode, cancelled=self._cancel_requested)
