# Phase TR-6 — Gate credit: record the editor's full run in the guard's ledger

Brief for the TR-6 coder. Source of truth: `planning/TestRunnerPLAN.md` §1
(lines 18–24), §2 decision **D4** (lines 82–87), §4 Risks (lines 273–276: *"a
wrong ledger record is worse than none"*), and `## TR-6 — Gate credit`
(lines 239–262). Base branch: `Development`.

**TR-6 merges LAST.** It layers on files TR-2, TR-4 and TR-5 also touch. Where
this brief and the merged state of those phases disagree about a name, **adapt
to what is on disk** — never rewrite their code to match this brief. §3 names
the exact insertion points and the assumed contracts.

**Read before you touch anything:** root `CLAUDE.md` §"Test Suite Policy"
(lines 21–62) is the only authority on which tests you may run. §4 of this
brief restates your allowance; nothing in the plan doc widens it.

---

## 1. Behavioral spec

### 1.1 What exists today (verified, with citations)

- The guard's **repeat guard** is `pre()` in `.claude/hooks/test_guard.py:443`–
  `465`. It builds `target = normalised_target(command)`
  (`test_guard.py:444`, defined at `:163`), `fingerprint = tree_fingerprint()`
  (`:445`, defined at `:205`), then
  `key = sha256(f"{target}\n{fingerprint}").hexdigest()[:32]` (`:446`), reads
  `state_dir/run-<key>.json` (`:447`) and — if the record is younger than
  `REPEAT_TTL_SECONDS` (6h, `:113`) — denies with exit 2 (`:452`–`465`).
- The record is written by `post()` at `.claude/hooks/test_guard.py:504`–`508`,
  with exactly three fields: `finished`, `target`, `outcome`. **There is no
  `source` field today** (verified, `:504`–`508`).
- The deny message today (`:452`–`465`) opens with *"you already ran this exact
  target and NOTHING has changed since"* and prints `target:` / `ran:` /
  `result:` lines. For an editor-sourced record that first line is **false** —
  the agent never ran it. That falsehood is exactly what TR-6 fixes.
- `classify()` (`test_guard.py:129`–`160`) maps `py tools/testgate.py check`
  to `"full"` (`:145`–`147`). The role guard (`:393`–`403`) denies `full` for
  subagents *before* the repeat guard is reached — TR-6 changes none of that.
- State lives in `_state()` (`test_guard.py:56`–`99`), overridable for tests by
  `TESTGUARD_STATE_DIR` (`:77`).
- The guard's tests drive the hook **as a subprocess** fed hook JSON on stdin
  (`tools/tests/test_test_guard.py:46`–`74`), each with a fresh scratch state
  dir (`:41`–`44`). Constants `FULL` / `TARGETED` at `:33`–`35`. The
  "editing the tree clears the denial" pattern is `:149`–`160`.
- Root `CLAUDE.md` §"Test Suite Policy" is `CLAUDE.md:21`–`62`; the bullet TR-6
  extends is **"The full `py tools/testgate.py check` runs exactly ONCE"** at
  `CLAUDE.md:49`–`51`.
- Editor toolbar anchor for TR-5: the *Agents* toolbar / *Summon a Drunken
  Robot* action at `editor/main.py:333`–`341` (verified).
- `tools/testguard_ledger.py`, `editor/test_runner.py` and
  `editor/test_report.py` **do not exist yet** (verified by `ls`) — TR-2, TR-3
  and TR-4 create them. You inherit them.

### 1.2 The invariant TR-6 must uphold

> A ledger record asserts: *"the full gate ran, on THIS working tree, and said
> THIS."* A record that is not true in every one of those three ways hides a
> red suite from the one run that would have caught it.

So the editor records a gate run **if and only if all five hold**:

1. **It was a full run** — the `testgate check` invocation, not a per-area
   re-run. A per-area re-run is explicitly NOT a gate (plan D2, lines 68–73) and
   records **nothing**, ever.
2. **It COMPLETED** — the child process exited on its own. Cancelled by the
   user, killed, crashed, or still running → record nothing (plan D4, line 86).
3. **A verdict was parsed** — the run produced a `GATE PASS` or `GATE FAIL`
   line. No verdict line, or `GATE ABORT`, → record nothing. "(no verdict line
   captured)" must never be written by the editor.
4. **The working tree did not change during the run.** Capture
   `tree_fingerprint()` when the run STARTS and again when it FINISHES. If they
   differ, record nothing: the run tested a tree that no longer exists, so a
   record under the start key credits a stale tree and one under the end key
   credits a tree that was never tested. Both are the wrong-record failure the
   Risks section names. (This is the one rule not spelled out in the plan; it
   follows directly from "a wrong ledger record is worse than none".)
5. **The key is computed by `tools/testguard_ledger`**, never by editor-local
   copies of the hashing (plan D3, lines 75–80).

Both verdicts are recorded — a `GATE FAIL` record is correct and useful: the
repeat guard hands the failure back and tells the agent to fix the code
(`test_guard.py:463`–`464`). Only *pass* is not a precondition.

### 1.3 What the recorded run must be keyed on

The record must land under the key an agent's own handoff gate will look up:
`normalised_target("py tools/testgate.py check")` + the tree fingerprint. Use
the **exact canonical spelling** the role table prescribes (`CLAUDE.md:33`), fed
through the ledger's `normalised_target` — do not hand-build the string that
comes out of it.

**Known gap, by design:** an agent that types a non-canonical spelling
(`python tools/testgate.py check`, a backslash path) computes a different
target and gets no credit — it runs the gate honestly. That is the safe
direction of failure. Do NOT paper over it by recording under several
speculative spellings; see §"Open questions".

### 1.4 What the hook must say

When the record it found carries `source == "editor"`, the deny message must
attribute it, so an agent is not told it ran something it has no memory of
(plan lines 247–249). Required content:

- The first line must **not** claim the agent ran it. Use, e.g.:
  `DENIED by test_guard: this tree's full gate ALREADY RAN — from the editor —
  and nothing has changed since.`
- The `ran:` line names the source: `ran:    340s ago, from the editor`.
- One added sentence saying why this counts: the user started it from the
  editor's *Run tests* button; it is the same command on the same tree, so it
  IS the handoff gate (root `CLAUDE.md` §"Test Suite Policy").
- The `target:` / `result:` lines and the "editing anything clears this" /
  `TESTGUARD_OFF=1` escape lines stay exactly as they are today
  (`test_guard.py:455`–`465`).

When `source` is absent or is anything else (an agent's own run, and every
record written before this phase), the message is **byte-unchanged** from
today. Existing tests pin that wording (`test_test_guard.py:133`) — do not
break them.

### 1.5 What TR-6 must NOT do

- **No lock.** The panel takes no lock of its own (plan D5, lines 89–93); TR-6
  writes the finished record only. Do not write `inflight.json`.
- **No change** to `classify()`, the role guard, the concurrency guard, the
  liveness probe, or `REPEAT_TTL_SECONDS`.
- **No new key logic** anywhere outside `tools/testguard_ledger.py`.
- **No test may launch a real test run.** See §4.

---

## 2. Architecture plan

```
editor/test_runner.py   (TR-3)  ── result object: full-vs-domain, completed, verdict
        │
editor/main.py          (TR-5)  ── captures fingerprint at run START,
        │                          calls record_gate_credit() on finish
        ▼
editor/test_report.py   (TR-4 + TR-6)
    record_gate_credit(result, started_fingerprint) -> bool
        ├─ all five preconditions in §1.2, else return False
        └─ tools.testguard_ledger.record_run(state_dir(), target, outcome,
                                             source="editor")
                                   │
tools/testguard_ledger.py (TR-2)  ─┴─ THE only owner of run_key / record file
                                   │
.claude/hooks/test_guard.py (TR-2 + TR-6)
    pre() repeat guard reads run-<key>.json ── message branches on `source`
```

**Where the call site lives: `editor/test_report.py`, not `editor/main.py`.**
The plan offers either (line 245); pick `test_report.py` because it is Qt-free
(D6, lines 95–98), so the whole decision table of §1.2 is unit-testable in the
fast `core` tier instead of the slow `editor` tier. `editor/main.py` gets two
mechanical lines and no logic.

Layering: `editor/` importing `tools/` is the existing pattern for shared,
Qt-free helpers and is what D3 requires. The hook imports the same module —
that shared import is the entire point of TR-2.

`record_gate_credit` returns `bool` (recorded / not) purely so the panel can
show a small "counted as the gate" note and so tests can assert the negative
cases without inspecting the filesystem.

---

## 3. File scope + shared-file contract

You may edit **only** these files.

| File | Owner | TR-6's change |
|---|---|---|
| `editor/test_report.py` | TR-4 | **append** `record_gate_credit(...)` |
| `editor/main.py` | TR-5 | two lines inside TR-5's run start/finish handlers |
| `.claude/hooks/test_guard.py` | TR-2 | repeat-deny message branches on `source` |
| `tools/testguard_ledger.py` | TR-2 | only if it lacks a `source` field (see below) |
| `tools/tests/test_test_guard.py` | TR-2 | **append** one new test class |
| `tools/tests/test_editor_test_report.py` | TR-4 | **append** one new test class |
| `CLAUDE.md` (root) | — | ONE bullet in §"Test Suite Policy" |

`tools/tests/test_editor_test_report.py` is a scope addition over the plan's
file list (plan line 252 names only the guard tests): the "a cancelled run
records nothing" and "a per-area re-run records nothing" tests are editor-side
and have nowhere else to live. Append-only, one new class — see below.

### 3.1 Assumed contract with TR-2 (`tools/testguard_ledger.py`)

No `docs/briefs/phase-TR-2-ledger-key.md` exists (verified). Assumed, from
plan lines 144–147:

```python
state_dir() -> Path
normalised_target(command: str) -> str
tree_fingerprint() -> str
run_key(target: str, fingerprint: str) -> str
record_run(state_dir, target, outcome, source) -> Path
```

- If `record_run` already takes `source` and writes it into the JSON: **use it,
  change nothing.**
- If it does not: add a keyword-only `source: str = "agent"` parameter and write
  it as a `"source"` field, and pass `source="agent"` explicitly from the hook's
  `post()` call site. That is the smallest possible edit to a TR-2 file.
- If TR-2 spelled a name differently (`make_key`, `ledger_dir`, …), use TR-2's
  name. Do not rename TR-2's API.

Records written before this phase have no `source` key — every read must be
`record.get("source")`, never `record["source"]`.

### 3.2 Insertion point in `.claude/hooks/test_guard.py`

The **only** block you touch is the repeat guard's deny, currently
`test_guard.py:447`–`465` (line numbers will have shifted after TR-2). Read the
record's `source` alongside `outcome` (today: `:453`) and build the message with
a branch. Everything above `# -- guard 2: repeat --` (`:443`) and everything
below the deny is TR-2's or untouched.

If TR-2 has already extracted the message into a helper, extend that helper.
Do **not** reintroduce private `normalised_target` / `tree_fingerprint` copies
into the hook — TR-2 deleted them on purpose (plan D3).

### 3.3 Insertion point in `editor/test_report.py` (TR-4)

Append at module end. Do not alter `write_report` or `agent_prompt` signatures
or behaviour.

```python
def record_gate_credit(result, started_fingerprint: str) -> bool:
    """Record a COMPLETED FULL editor run as this tree's gate run. …"""
```

Assumed TR-3 result contract (no TR-3/TR-4 brief exists — verified): the object
carries which domain was run (`None`/empty for a full run), whether it completed
normally, and the parsed gate line. **Read TR-3's actual attribute names off
`editor/test_runner.py` and use those.** Isolate every access in one small
private predicate so an adaptation is a one-line change. If TR-3 exposes no
"completed" flag, treat "a `GATE PASS`/`GATE FAIL` line was parsed" as the
completion signal and say so in the docstring — a cancelled run cannot have
produced one.

### 3.4 Insertion point in `editor/main.py` (TR-5)

TR-5 owns the toolbar action (anchor `editor/main.py:333`–`341`, the *Agents*
toolbar) and the worker thread. TR-6 adds exactly:

1. In TR-5's run-start path: `self._test_run_fingerprint = tree_fingerprint()`
   — captured **before** the process launches.
2. In TR-5's finished handler, after `write_report(...)`: call
   `record_gate_credit(result, self._test_run_fingerprint)` and (optionally)
   surface the returned bool in the panel's completion line.

No other change to `main.py`. If TR-5 named the handler differently, use its
name; if TR-5 already stores a start-time snapshot, reuse it.

### 3.5 Insertion point in `tools/tests/test_test_guard.py` (TR-2)

Append **one** new class immediately before `if __name__ == "__main__":`
(currently `:440`). Reuse `GuardCase` (`:38`), `FULL` (`:35`) and `self.pre`
(`:64`) — do not modify them, do not modify any existing class.

The class fakes ledger state and drives the hook as a subprocess. It must
cover, per plan lines 254–257:

- an editor-sourced record for `FULL` on the current tree denies a subsequent
  main-session `py tools/testgate.py check` (exit 2);
- that deny message contains the verdict text AND names the editor as the
  source, and does not claim the agent ran it;
- editing the tree clears it (copy the scratch-file pattern at `:157`–`160`);
- a record with no `source` (an agent's own, the pre-TR-6 shape) still produces
  today's wording — the regression pin for §1.4.

Fake the state by calling `tools.testguard_ledger.record_run` against the
scratch `TESTGUARD_STATE_DIR` this case already creates (`:44`, `:51`), so the
test exercises the real key computation. Writing the JSON by hand would prove
only that the test can spell the key.

### 3.6 Insertion point in `tools/tests/test_editor_test_report.py` (TR-4)

Append one class covering the §1.2 decision table with a hand-built fake result
object (no subprocess, no pytest, no testgate): full+completed+verdict records
once; per-area re-run records nothing; not-completed/cancelled records nothing;
no verdict / `GATE ABORT` records nothing; a fingerprint that changed between
start and finish records nothing; a `GATE FAIL` verdict **is** recorded. Point
the ledger at a tempdir — **these tests must never write into the live guard
state dir**, or they will suppress a real session's gate.

### 3.7 Root `CLAUDE.md` — exactly one bullet

Insert directly after the "runs exactly ONCE" bullet (`CLAUDE.md:49`–`51`),
inside §"Test Suite Policy". Wording of this shape:

> - **A completed full run from the editor's *Run tests* button IS that gate,
>   for that working tree.** It is recorded in the guard's ledger, so the main
>   session's handoff run is handed that result instead of running again; any
>   edit to the tree clears it.

Constraints on the edit:

- Prose only. **Never add a standalone, copy-pasteable full-suite command
  line** — `tools/tests/test_test_guard.py:393`–`418` asserts against exactly
  that defect (it scans §Step 2, but the doctrine is repo-wide).
- Do not touch the role table (`:29`–`33`); `test_the_root_router_states_the_
  role_table` (`:386`) pins its rows.
- Do not add the words `unittest discover` anywhere (`:420`–`437`).
- One bullet. Not a subsection, not a second copy of the policy.

---

## 4. Exit gate + Quick Test

### Your allowance (root `CLAUDE.md` §"Test Suite Policy", lines 21–33)

You are a **subagent**. You may run `py tools/smoke.py` and targeted
`py -m pytest tools/tests/<file>.py -q` over the files this phase touches — and
nothing else. The full suite, `testgate check`, `--affected` and tier sweeps
(`-m core` / `-m editor` / `-m meta`) are **denied by the hook you are
editing**; asking for one produces a denial, not a result. The single full gate
is the main session's, at handoff, and is not part of this phase.

### Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_test_guard.py -q
py -m pytest tools/tests/test_editor_test_report.py -q
```

All green, no new skips. If TR-4's report tests are red for reasons outside
your diff, report it and stop — do not investigate.

### Hard rule: no test may launch a real run

Plan §4 line 267: the single largest hazard here is a test that shells out to
pytest or testgate. Your tests drive the **hook** as a subprocess with a
**faked ledger record**, and the editor-side tests use a **fake result object**.
Neither ever starts a test run. A test that took minutes, tripped the
concurrency guard, or recursed into the suite is a failed phase, not a slow one.

### The plan's Quick Test is NOT yours

`planning/TestRunnerPLAN.md:261`–`262` says *"run the full suite from the editor,
then ask a Claude session to run the gate"*. **You cannot execute that** — it
needs a GUI, minutes of real suite time, and a second Claude session. It is the
**orchestrator's / user's** verification step. Hand it up in your report as
pending; do not attempt it.

### Your substitute Quick Test (canned state, no run)

Write a small probe script into the session scratchpad — **not into the repo**
— and run it.

**Two traps, both mandatory:**

1. **Do not put the words `pytest`, `testgate` or `unittest` in the shell
   command line.** The guard fires on every Bash call and matches those words
   (`test_guard.py:123`); a command containing `testgate ... check` classifies
   as `full` (`:145`–`147`) and you, a subagent, get denied (`:393`). So name
   the script something like `tr6_probe.py` and invoke it as `py <abs path>`.
   Put the command string inside the script, where the hook never sees it.
2. **Point the probe at a scratch `TESTGUARD_STATE_DIR`** (`test_guard.py:77`).
   A probe that writes into the live state dir would suppress the
   orchestrator's real handoff gate — the exact wrong-record failure this phase
   exists to prevent.

The probe should:

1. set `TESTGUARD_STATE_DIR` to a fresh temp dir;
2. call `record_run(state, target=normalised_target("py tools/testgate.py check"),
   outcome="GATE PASS — 2251 passed", source="editor")`;
3. feed a `PreToolUse` payload for that same command to
   `.claude/hooks/test_guard.py` as a subprocess (the shape at
   `tools/tests/test_test_guard.py:64`–`68`), with a `SessionStart` marker first
   so the role is `main`;
4. print the exit code and stderr.

**Expected:** exit code `2`, and stderr that names the editor as the source,
quotes `GATE PASS — 2251 passed`, and does not tell the agent it ran the gate
itself. Paste those two facts (code + the `ran:` line) into your report as
**measured**.
