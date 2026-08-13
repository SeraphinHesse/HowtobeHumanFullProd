# Phase TR-3 — The run engine (`editor/test_runner.py`)

Plan: `planning/TestRunnerPLAN.md` §"TR-3 — The run engine" (lines 163–185),
Decisions D2 (line 68) / D6 (line 95), Risks §4 (lines 266–291).
Depends on: **TR-1** (`tools/test_domains.py`). Consumed by: **TR-4** (report),
**TR-5** (panel), **TR-6** (ledger credit).

**You are implementing a parser and a process wrapper. You must never make this
phase's tests launch a real test run** — see §1.6 and §4.

---

## 1. Behavioral spec

### 1.0 What the module is

A Qt-free, pygame-free module `editor/test_runner.py` (D6, plan line 95:
"the run engine is Qt-free … the panel is the only Qt") exposing:

- `build_command(domain: str | None = None) -> list[str]` — the CANONICAL
  command for a run.
- `build_stream_command(domain: str | None = None) -> list[str]` — the command
  `TestRun` actually launches (see §2.1; this is the one that produces live
  per-file output).
- `parse_line(line: str) -> Event | None` — pure, stateless, one line in.
- `TestRun` — drives a child process (or, in tests, a canned line iterator),
  accumulates per-domain state, calls `on_progress(domain, done, total, state)`
  and `on_finished(result)`.
- `child_env(base: Mapping[str, str] | None = None) -> dict[str, str]` (§1.5).

Qt-free is load-bearing twice: it puts this module's tests in the `core` tier
instead of the slow `editor` tier (D6), and it lets TR-5 drive `TestRun` from a
worker thread and marshal the callbacks itself.

### 1.1 The exact line formats `parse_line` must handle

All of these arrive with **ANSI SGR escapes possibly wrapping the leading
token**. `tools/testgate.py:102-104` records the incident: `\x1b[31mFAILED` is
invisible to `^FAILED`, and the gate printed PASS over two red tests for a
working session. Strip escapes with the same pattern (`\x1b\[[0-9;]*m`,
`tools/testgate.py:104`) **before** matching, and `.strip()` the remainder
(`tools/testgate.py:124`).

**A. Per-test verbose lines — xdist form** (what a `-n auto` run emits under
`-v`; this is the live-progress signal):

```
[gw3] [ 45%] PASSED tools/tests/test_boss.py::TestBoss::test_dead_goal_repaths
[gw0] [  7%] FAILED tools/tests/test_enemies.py::TestWaves::test_spawn
```

**B. Per-test verbose lines — non-xdist form** (`-n0`; CI's heavy shards use
`-n0`, `tools/ci_shards.py:66`, and a domain re-run may too):

```
tools/tests/test_boss.py::TestBoss::test_dead_goal_repaths PASSED [ 45%]
```

Outcomes to accept in both forms: `PASSED`, `FAILED`, `ERROR`, `SKIPPED`,
`XFAIL`, `XPASS`, `SUBFAILED`/`SUBERROR` (pytest-subtests may emit its own
verbose line). Unknown outcome tokens → return `None` rather than guessing.

**C. Short-report FAILED / ERROR** (`-rfEsX`; `tools/testgate.py:68`):

```
FAILED tools/tests/test_a.py::T::test_x - AssertionError: ...
ERROR tools/tests/test_a.py::T::test_x
ERROR tools/tests/test_a.py
```
Node-id is `\S+`; the ` - <message>` tail is optional and is the failure's
short message (keep it — TR-4 puts it in the report).

**D. Short-report SUBFAILED** (`tools/testgate.py:76-78`) — outcome first,
params in parentheses, node-id trailing:

```
SUBFAILED(file="'x.json'", key="'K'") tools/tests/test_a.py::T::test_x
```
**The params are part of the key** (`tools/testgate.py:73-75`): one test can
fail N subtests independently, and collapsing them lets N-1 vanish. Key on
`nodeid + params`.

**E. Short-report SKIPPED** (`tools/testgate.py:84`) — a DIFFERENT shape;
parsing it with the FAILED pattern captures `[1]` as the node-id
(`tools/testgate.py:61-66`):

```
SKIPPED [1] tools/tests/test_a.py:120: a build already exists
```
Key a skip by **file + reason, never the line number** (`tools/testgate.py:79-83`).

**F. The tally line** (`tools/testgate.py:89`):

```
5 failed, 1170 passed, 3 skipped, 2 xfailed in 62.74s
```
Sum every `(\d+) (?:passed|failed)` match, do **not** take the first (a
`.search` grabbing the `5` is how the gate once announced "5 ran" for a full
suite, `tools/testgate.py:86-88`). `N subtests passed` must NOT be counted —
the digits there are followed by `subtests`, not `passed`.

**G. testgate's own verdict lines** (only present when the child is testgate):

```
GATE PASS  2245 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips   (testgate.py:219)
GATE FAIL  1 problem(s)                                                (testgate.py:228)
  NEW FAILURE   tools/tests/test_boss.py::TestBoss::test_x             (testgate.py:230)
  UNEXPECTED SKIP tools/tests/test_a.py: some reason                   (testgate.py:232)
GATE INFO  --affected: …                                               (testgate.py:176)
GATE ABORT  --affected cannot narrow this diff.                        (testgate.py:182)
```
`parse_line` recognises `GATE PASS` / `GATE FAIL` / `GATE ABORT` as a
`gate` event carrying the verbatim line. `NEW FAILURE` / `UNEXPECTED SKIP`
lines are `failure` events (kinds `failed` / `unexpected_skip`).

**H. Anything else** → `None`. Progress dots (`....F..`), headers,
tracebacks, `[gw2] node down`, and blank lines are not events. (Tracebacks are
still kept in `result.raw_tail`, §3.3.)

### 1.2 Node-id → module → domain

Every event that carries a node-id yields `module = basename(nodeid.split("::")[0])`
(e.g. `test_boss.py`), normalising `\` → `/` first — `tools/testgate.py:137-141`
records why: pytest reports paths with the platform separator, and a Windows
run would otherwise match nothing a Linux-authored table lists.

`domain = domain_for(module)` from TR-1 (§3.1). A module TR-1 does not claim is
**surfaced, never dropped** (plan line 180): it is accumulated under the
reserved domain key `"unknown"` and its module name is added to
`result.unknown_modules`.

### 1.3 Progress callbacks

`on_progress(domain: str, done: int, total: int | None, state: str)` fires
whenever a domain's counters change:

- `domain` — a TR-1 domain key, or `"unknown"`.
- `done` — tests seen for that domain so far (passed + failed + subfailed +
  skipped).
- `total` — `None` until known; see §2.2. TR-5 must render a growing count when
  it is `None` (plan line 281: "TR-5 must not depend on a total existing").
- `state` — `"running"` while the run is live and nothing has failed in that
  domain, `"failed"` the moment that domain records a failure/error/subfailure,
  `"passed"` when the run finishes with no failure in it. A domain never leaves
  `"failed"`.

Callbacks are optional (`None` = no-op) and are called **synchronously on the
thread driving the run**. Marshalling onto the UI thread is TR-5's job; this
module must not know Qt exists.

### 1.4 Commands

- `build_command(None)` → `[sys.executable, "tools/testgate.py", "check"]` —
  the canonical full-run command (D2, plan line 68). This is the string TR-6
  hands the ledger as the run's target, so it must stay literally the gate
  command an agent would type.
- `build_command("enemies")` → `[sys.executable, "-m", "pytest", "-q",
  "--no-header", "-rfEsX", "tools/tests/test_boss.py", …]` — one path per file
  in `DOMAINS["enemies"]`, sorted, POSIX separators, only files that exist.
- `build_command("nosuchdomain")` → raises `ValueError` naming the known
  domains. `build_command("unknown")` likewise raises — `"unknown"` is a
  reporting bucket, not a runnable domain.
- `build_stream_command(...)` → §2.1.

A domain re-run is **explicitly not a gate** (D2, plan line 73): its result must
carry `gate_line = None`, and TR-4/TR-5 must not print a `GATE …` line for it.

### 1.5 The child environment

`child_env()` reproduces `tools/testgate.py:114-118` — drop `FORCE_COLOR` and
`CLICOLOR_FORCE` from the inherited environment, set `NO_COLOR=1` and
`PY_COLORS=0` — **and additionally** sets `PYTHONUNBUFFERED=1`. Without the
last one, Python block-buffers stdout off a tty and the panel shows nothing
until exit; this is the same lesson `editor/run_controls.py` already learned
(`editor/CLAUDE.md:100`). The parser still strips ANSI anyway
(`tools/testgate.py:44-46`: "the next color-forcing knob will not be one we
have heard of").

### 1.6 The one rule about this phase's tests

**`tools/tests/test_editor_test_runner.py` must never launch pytest, testgate,
or any subprocess.** Plan §4's first risk (lines 267–272): "the thing under
test launches pytest … would take minutes inside the suite, trip the
concurrency guard, and could recurse. If a phase cannot be tested without a
real run, the phase is wrong."

Mechanically: every test drives `TestRun` through `feed_lines()` with a canned
fixture string (§2.4), or calls `parse_line` directly. `TestRun`'s process
launcher is injected (`spawn=` parameter); the test suite passes a fake, and one
test passes a `spawn` that raises `AssertionError` to prove nothing spawns on
the canned path.

Coverage required (plan lines 176–180): a green run; a run with a failure; a
subtest failure; an unexpected skip; an ANSI-coloured stream; output for a file
in no known domain.

---

## 2. Architecture plan

### 2.1 Resolving the conflict between D2 and live progress — READ THIS FIRST

**Measured from source, not inferred:** `tools/testgate.py:119-120` runs pytest
with `subprocess.run(..., capture_output=True)`. testgate therefore emits
**nothing until the whole run is over**. Second, testgate runs pytest with `-q`
(`tools/testgate.py:110`), and a `-q` run's live output is progress dots with no
node-ids at all; the `FAILED`/`SKIPPED` short-report lines only appear in the
final summary.

So a child of `py tools/testgate.py check` cannot produce live per-file
progress, by construction. The plan's headline (rows filling in live) and D2
(the same `GATE …` line agents read) cannot both come from one child process
without editing `tools/testgate.py`, which §2's diagram pins as unchanged
(plan line 41).

**Decision for TR-3 (amends D2's mechanism, keeps its intent):**

- `build_command(None)` stays the testgate command — it is the canonical name of
  the run, what TR-6 records, and what the Quick Test prints.
- `build_stream_command(None)` returns the command `TestRun` actually launches:
  `[sys.executable, "-m", "pytest", "-v", "--no-header", "-rfEsX"]` — same flags
  as `tools/testgate.py:110` except `-q` → `-v`, so every test emits a node-id
  line (§1.1 A/B) as it finishes. `build_stream_command(domain)` is
  `build_command(domain)` with `-q` replaced by `-v`.
- **TR-3 does not compute a `GATE …` verdict itself.** `RunResult.gate_line` is
  populated only from a `GATE …` line seen in the stream (§1.1 G). When the
  stream is a raw pytest run, `gate_line is None` and `verdict` is derived from
  the parsed counters (`fail` if any failure/error/subfailure/unexpected skip,
  else `pass`). Nothing in TR-3 prints or fabricates the string `GATE PASS`.

Consequence to carry upward, **not** to solve here: with `gate_line is None`,
TR-6's ledger credit (D4) would be recording a verdict testgate did not
pronounce. **This is an open decision for the orchestrator** (see the report):
either TR-5 runs the streamed pytest for the rows and then a second testgate
pass for the verdict, or `tools/testgate.py` gains a line-passthrough mode in a
new phase. TR-3 is designed so both remain possible: it parses either stream,
and it never invents a gate line.

### 2.2 The per-domain total — growing count, NOT `--collect-only`

Plan §4, lines 279–281, leaves this to TR-3. **Decision: growing count.
`total` is `None` for every domain until the run's tally line arrives; no
`--collect-only` pass is made.** Reasons:

1. A `--collect-only` pass imports every test module, including the entire Qt
   tier — the same imports that make the `editor` tier dominate wall clock
   (`tools/ci_shards.py:14-19`). Paying that before the run makes the button
   feel slower at exactly the moment the user is waiting for first feedback.
   (Cost not measured; the direction is structural, not the size.)
2. A collected total is not the total that runs. Dynamic skips, xdist worker
   death (`--max-worker-restart=0`, `pytest.ini:8`, turns a killed worker into a
   failed run mid-flight) and `-k`/marker interaction all make the denominator
   lie, and a progress bar that lies is worse than a counter that does not.
3. The plan already forbids depending on it (line 281), so a fraction buys
   nothing TR-5 is allowed to require.

`total` may become non-`None` for a domain when a domain re-run's tally line
arrives (a single-domain run's tally IS that domain's total). The field exists
for that case and for a future `--collect-only` opt-in; the panel treats `None`
as "count up".

### 2.3 The parser keys on node-ids, never stream position

**`pytest.ini:4-8` pins `--dist loadfile` and `-n auto`.** Files finish out of
order and interleave across workers; a `[gw3]` line for `test_boss.py` can sit
between two `test_enemies.py` lines. Therefore:

- **Every event's identity is the node-id in its own line.** There is no
  "current file" cursor, no "the last file mentioned", no ordering assumption,
  no inference that a file is done because another file started.
- A domain's `state` transitions on its own counters only.
- This mirrors `tools/testgate.py`'s design rule 1 (lines 24–27: "KEY ON
  NODE-IDS, NOT COUNTS") and §4's risk (plan lines 283–285).
- A test must prove it: feed an interleaved two-worker fixture and assert the
  per-domain counts are identical to the same lines in sorted order.

### 2.4 Shape of the code

```
_ANSI, _VERBOSE_XDIST, _VERBOSE_PLAIN, _FAILED, _SUBFAILED, _SKIPPED,
_TOTAL, _GATE            module-level compiled regexes (C/D/E/F copied in
                         SHAPE from tools/testgate.py — see §3.2 on why they
                         are copied, not imported)

@dataclass(frozen=True) Event
    kind: "test" | "failure" | "skip" | "tally" | "gate"
    nodeid / module / domain / outcome / params / message / count / line

parse_line(line) -> Event | None      pure; strips ANSI; no state

class TestRun:
    def __init__(self, domain=None, command=None, on_progress=None,
                 on_finished=None, spawn=None)
    def feed(self, line) -> None      # parse + accumulate + fire on_progress
    def feed_lines(self, lines)
    def finish(self, returncode=0, cancelled=False) -> RunResult  # fires on_finished
    def run(self) -> RunResult        # spawn(); stream stdout lines -> feed();
                                      # finish(proc.returncode)
    def cancel(self) -> None          # sets a flag; run() terminates the child
                                      # and calls finish(cancelled=True)
```

`run()` is blocking and the ONLY method that touches `subprocess`; `spawn`
defaults to a small `_default_spawn(cmd, env)` using
`subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, bufsize=1,
cwd=REPO, env=child_env())`. **stderr is merged into stdout** so ordering is
preserved and nothing is lost (`tools/testgate.py:123` reads both).

Tests use `feed_lines()` + `finish()` and never call `run()`.

---

## 3. File scope + shared-file contract

### 3.1 What TR-3 ASSUMES of TR-1's `tools/test_domains.py`

TR-1 is a dependency (plan line 109) and may or may not have landed when you
read this. **The assumed API, from plan lines 122–133:**

```python
DOMAINS: dict[str, tuple[str, ...]]
# keys exactly: "buildings", "enemies", "map", "ui", "engine", "editor", "data"
# values: test-module BASENAMES, e.g. ("test_boss.py", "test_enemies.py", ...)

def domain_for(module: str) -> str
# module is a BASENAME ("test_boss.py") -> "enemies"   (plan line 133's Quick Test)
```

Defensive rules you must follow, because TR-1's exact error behaviour is not
pinned by the plan:

- Call `domain_for` through ONE private helper
  `_domain_of_module(module) -> str` that returns `"unknown"` when
  `domain_for` raises **any** exception or returns a falsy value. TR-1 treats an
  unclaimed module as a hard error (plan line 64); TR-3 must not crash a live
  run over it — it surfaces it (§1.2).
- Import lazily-safe at module top: `from tools.test_domains import DOMAINS,
  domain_for`. Precedent for `editor/` importing `tools/`: `editor/main.py:79`
  (`from tools.smoke import validate_data`). Do **not** import anything else
  from TR-1 — the display label whose name the plan does not fix (line 123) is
  TR-5's business, not yours.
- If `tools/test_domains.py` does not exist yet, STOP and report it; do not
  create it (that is TR-1's file).

### 3.2 What TR-3 assumes of `tools/testgate.py` — nothing; it does not import it

Copy the regex SHAPES from `tools/testgate.py:68-89` into `editor/test_runner.py`
rather than importing the private `_FAILED` / `_SUBFAILED` / `_SKIPPED` /
`_TOTAL` names. They are underscore-private, and `tools/testgate.py` is pinned
"unchanged" by the plan (line 41) — importing privates would make any future
edit there a silent break here. Add a comment on each regex citing its
`tools/testgate.py` line number and the failure shape it exists for, so the
copy is traceable. Do **not** re-implement testgate's baseline diff or verdict
composition (§2.1); that is the fork D2 forbids.

### 3.3 The `result` object — the CONTRACT for TR-4 and TR-5

TR-4 writes `.claude/testruns/<ts>.json` + `.md` from this (plan lines 195–197);
TR-5 renders rows from it; TR-6 decides ledger credit from `completed` +
`domain`. Frozen dataclasses in `editor/test_runner.py`, all fields always
present:

```python
@dataclass(frozen=True)
class Failure:
    nodeid: str        # "tools/tests/test_boss.py::TestBoss::test_x" (POSIX)
    module: str        # "test_boss.py"
    domain: str        # TR-1 key, or "unknown"
    kind: str          # "failed" | "error" | "subfailed" | "unexpected_skip"
    params: str        # subtest params verbatim incl. parens, else ""
    message: str       # short reason after " - ", or the skip reason, else ""

@dataclass(frozen=True)
class DomainResult:
    domain: str        # TR-1 key, or "unknown"
    state: str         # "pending" | "running" | "passed" | "failed"
    done: int          # passed + failed + subfailed + skipped
    total: int | None  # None unless known (§2.2)
    passed: int
    failed: int        # FAILED + ERROR at test level
    subfailed: int
    skipped: int
    modules: tuple[str, ...]      # basenames seen, sorted
    failures: tuple[Failure, ...] # this domain's, in arrival order

@dataclass(frozen=True)
class RunResult:
    command: tuple[str, ...]      # what build_command(domain) returns (canonical)
    stream_command: tuple[str, ...]  # what was actually launched
    domain: str | None            # None == full run; else the re-run's domain
    verdict: str                  # "pass" | "fail" | "cancelled" | "error"
    gate_line: str | None         # verbatim "GATE PASS …"/"GATE FAIL …" if the
                                  # stream carried one; None otherwise (ALWAYS
                                  # None for a domain re-run — D2, plan line 73)
    completed: bool               # process ended AND a tally or gate line was
                                  # parsed; False for cancelled/crashed (D4)
    cancelled: bool
    returncode: int | None
    total_ran: int                # from the tally line (§1.1 F), 0 if absent
    started_at: float             # time.time()
    finished_at: float
    duration_s: float
    domains: dict[str, DomainResult]   # every TR-1 domain relevant to the run,
                                       # plus "unknown" iff it has content
    failures: tuple[Failure, ...]      # flat, all domains, arrival order
    unknown_modules: tuple[str, ...]   # sorted; empty on a healthy run
    raw_tail: tuple[str, ...]          # last 200 raw (unstripped) lines, for
                                       # the report's traceback section
```

Guarantees TR-4/TR-5/TR-6 may rely on, and which you must test:

1. `verdict == "pass"` **iff** `failures` is empty and `cancelled` is False and
   no `GATE FAIL`/`GATE ABORT` line was seen.
2. `completed is False` ⇒ TR-6 records nothing (D4, plan lines 85–87). A
   cancelled run still produces a `RunResult` with whatever was parsed.
3. `domain is not None` ⇒ `gate_line is None`. A re-run is not a gate.
4. Every `Failure` in a `DomainResult.failures` also appears in
   `RunResult.failures`; the flat tuple is the union, deduplicated on
   `(nodeid, params, kind)`.
5. All paths are POSIX-separated (§1.2).

### 3.4 Files

**New**
- `editor/test_runner.py` — everything above. Qt-free, pygame-free, stdlib +
  `tools.test_domains`.
- `tools/tests/test_editor_test_runner.py` — canned-fixture tests only (§1.6).
  Put the fixtures in the test module as module-level triple-quoted strings
  (including one with literal `\x1b[31m` escapes); do not add fixture files.

**Modified — shared with other phases; exact insertion points**
- `conftest.py` — add `"test_editor_test_runner": "core",` to the **core**
  block, alphabetically between `"test_defence_aoe_beam": "core",`
  (`conftest.py:101`) and `"test_enemies": "core",` (`conftest.py:102`). A
  module missing from `TIERS` is a hard error, not a silent skip
  (`conftest.py:19`). `core`, not `editor`, is the point of D6.
  *TR-4 adds `test_editor_test_report` and TR-5 adds
  `test_editor_test_run_panel` (that one `editor`) to the same table later —
  one line each, no reflow; do not reorder the table.*
- `tools/tests/test_editor_viewport.py` — add `"editor.test_runner, "` to
  `TestPurity.test_editor_does_not_import_game`'s import string
  (`tools/tests/test_editor_viewport.py:1492-1528`), on its own line
  immediately after `"editor.timeline_curve, editor.timeline_ops, "`
  (line 1520). Required by `editor/CLAUDE.md:78`. *TR-4 appends
  `editor.test_report` and TR-5 `editor.panels.test_run_panel` at the same
  spot — append, never rewrite the block.*

**Do NOT touch:** `tools/testgate.py`, `tools/test_domains.py`,
`.claude/hooks/test_guard.py`, `pytest.ini`, `tools/ci_shards.py`,
`editor/main.py`, `.gitignore`, `editor/CLAUDE.md` (TR-5 owns the doc update,
plan line 225 — unless this module introduces a pattern that doc lacks, in
which case report it rather than writing it).

---

## 4. Exit gate + Quick Test

**Gate — run exactly these, in this order. You are a subagent: this list is the
whole of what you may run (root `CLAUDE.md` §"Test Suite Policy"). Do not run
the full suite, `py tools/testgate.py check`, `--affected`, or any tier sweep
(`-m core` / `-m editor` / `-m meta`) — the `test_guard.py` hook DENIES all
four and you will stall.**

```bash
py tools/smoke.py
py -m pytest tools/tests/test_editor_test_runner.py -q
py -m pytest tools/tests/test_editor_viewport.py -q -k Purity
```

The third is the layering guard for the file you edited in §3.4 (`-k Purity`
selects one test in that module — it is a named file, not a tier sweep). The
`conftest.py` TIERS entry is pinned by `tools/tests/test_tiers.py`, which is
`meta` tier — **do not** run it as a sweep; the orchestrator's single full
`check` at handoff covers it.

`GATE PASS` is not printed by any of these — read pytest's own summary; zero
failures, zero errors, and **zero unexpected skips** (`tools/testgate.py:31-34`:
a test that quietly stops running is indistinguishable from one that passes).

**Quick Test** (plan line 183; run by the orchestrator or the user, not by you):

```bash
py -c "from editor.test_runner import build_command, build_stream_command; print(build_command()); print(build_command('enemies')); print(build_stream_command())"
```

Expected: line 1 is the testgate command
(`[... , 'tools/testgate.py', 'check']`); line 2 is a pytest command naming
**only** enemy test files and no other domain's; line 3 is the same pytest
invocation as testgate's but with `-v` in place of `-q`. Nothing runs — all
three are list-builders, and no test process starts.

Second Quick Test (proves the live path without a real suite run):

```bash
py -c "from editor.test_runner import TestRun; r=TestRun(on_progress=lambda d,done,t,s: print(d,done,t,s)); r.feed_lines(['[gw3] [ 45%] PASSED tools/tests/test_boss.py::T::test_x','[gw0] [ 46%] FAILED tools/tests/test_editor_panels.py::T::test_y','[gw3] [ 47%] PASSED tools/tests/test_boss.py::T::test_z']); print(r.finish(1).verdict)"
```

Expected: `enemies 1 None running` → `editor 1 None failed` →
`enemies 2 None running` → `fail`. The interleaving across workers is the
point: the second `test_boss.py` line still lands in `enemies`, because
identity comes from the node-id and never from position in the stream.

**Report upward, do not fix:** the D2/live-progress conflict in §2.1 if you find
a cleaner resolution while implementing; anything TR-1 exposes that differs from
§3.1; any need to edit `tools/testgate.py`.
