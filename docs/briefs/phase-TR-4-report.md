# Phase TR-4 — Report writer + agent prompt

Brief for the coder / phase-executor. Source plan: `planning/TestRunnerPLAN.md`
§1 Vision (L9–28), §2 Architecture + D7 (L30–101), §3 build order row TR-4
(L110), the `## TR-4 — Report + agent prompt` section (L188–207), and §4 Risks
first bullet (L267–272). Package: **editor** — read `editor/CLAUDE.md` before
you start (it is the ONE package doc for this phase).

**This phase ships NO Qt.** `editor/test_report.py` is a pure, stdlib-only
module (same purity class as `editor/agent_forms.py`), plus its test file, plus
one `.gitignore` line and one line in the purity guard. **Do not touch**
`editor/test_runner.py` (TR-3 owns it), `editor/panels/test_run_panel.py` or
`editor/main.py` (TR-5 owns them), `tools/testguard_ledger.py` (TR-2 owns it),
or the hook.

**Hard constraint, from plan §4 L267–272:** nothing you write may launch a real
test run, and no test in this phase may shell out to pytest or testgate. Every
test drives a **canned result object** you construct in the test file. A test
that starts a real run would take minutes inside the suite, trip the
concurrency guard, and could recurse.

---

## 1. Behavioral spec

TR-4's job (plan L190–191): *"A finished run leaves behind something an agent
can act on without being told anything else."* Concretely, when a run finishes,
the panel (TR-5) hands the run's result to this module, which writes a durable
report to disk and produces one block of text a human can paste at a Claude
session.

### 1a. Where reports live

`.claude/testruns/<timestamp>.json`, with a human-readable `.md` beside it.
Plan D7 (L100–101): *"Reports live in `.claude/testruns/`, gitignored, beside
`.claude/dispatch/`. Same reasoning: agent-facing scratch, never committed."*

The sibling to copy is the dispatch handoff writer:
- `editor/agent_forms.py:140-141` — `dispatch_dir()` returns
  `_repo(repo) / ".claude" / "dispatch"`; `_repo(repo=None)` at
  `editor/agent_forms.py:42` resolves the repo default from
  `REPO = Path(__file__).resolve().parents[1]` (`editor/agent_forms.py:28`).
  **Copy this injection convention exactly** — every public function here takes
  `repo=None` and defaults to the real repo, so tests write into a tempdir.
- `editor/agent_forms.py:144-158` — `write_handoff`: derive a stamp from the
  timestamp, `mkdir(parents=True, exist_ok=True)`, build the path, and on a
  name collision suffix `-2`, `-3`, … before the extension. Same shape here.
- `.gitignore:18` already carries `.claude/dispatch/` under the
  "Editor / tooling state" header (`.gitignore:15`); `.claude/worktrees/` is at
  `.gitignore:19`. `.claude/testruns/` joins that block.

One deliberate difference from the handoff writer: **reports are NOT written
through `engine.data_io.write_validated`, and get no `data/schemas/` entry.** A
handoff is a contract consumed by the `/dispatch` skill; a report is a
read-only artefact for a human and an agent's eyeballs. Adding a schema would
put build telemetry into the schema store and make `tools/smoke.py`'s pairing
rule a hazard for a gitignored directory. Write it with `json.dumps(...,
indent=2, sort_keys=True)` + a trailing newline (deterministic, diffable, but
not schema-gated).

### 1b. What the report must contain

Plan L194–196: *"`write_report(result) -> Path` producing
`.claude/testruns/<ts>.json` (gate line, per-domain totals, failing node-IDs,
tracebacks) and a `.md` beside it; `agent_prompt(path) -> str`."*

So the JSON carries, at minimum: the **gate line** verbatim, **per-domain
totals**, **every failing node-ID**, and the **traceback** for each failure.
The gate line is testgate's own output — `tools/testgate.py:219-220` prints
`GATE PASS  {total} ran | {n} known | 0 new | {n} fixed | 0 unexpected skips`
and `tools/testgate.py:228` prints `GATE FAIL  {problems} problem(s)`, with
`NEW FAILURE` / `UNEXPECTED SKIP` detail lines at `tools/testgate.py:229-232`.
Store the line **exactly as parsed by TR-3** — never re-derive or re-word it.
Per plan D2 (L68–75), a per-domain re-run *is not a gate*: when the result is a
per-domain re-run, the report must carry no gate line at all (`null`) and must
say so.

### 1c. What the agent prompt must do

Plan L202: *"the prompt names the report path and the failing areas."* The
prompt is what a designer copies out of the panel (TR-5's *Copy agent prompt*
button, plan L219) and pastes at a fresh Claude session that has no memory of
the run. It must therefore be self-contained: the report's repo-relative path,
the verdict, which **areas** are red and how badly, and a short instruction on
what to do next. It names areas — plan §1 L25–26: *"a failure is attributed to
an area of the game rather than to a test module nobody outside the suite
recognises."*

### 1d. Green runs still write

Plan L200–203 ("a green run still writes a report"). A `GATE PASS` produces
both files, with `failures: []`, and `agent_prompt` returns a short "nothing to
do" text that still names the report path — never an empty string and never a
raise.

---

## 2. Architecture plan

### 2a. Module `editor/test_report.py` (new, PURE)

Allowed imports: stdlib only (`datetime`, `json`, `pathlib`). It may import
`tools.test_domains` (TR-1) **for display labels only**, guarded — see 2e. No
PySide6, no pygame, no `game.*`, no `engine.*`. Module docstring follows the
`editor/agent_forms.py` house pattern: what it is, why it is pure, why it is in
`TestPurity`.

Constants:

```python
REPO = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1          # report format version, not a data/ schema
```

Public API (every path-taking function keeps `repo=None` injection):

| Function | Returns | Notes |
|---|---|---|
| `testruns_dir(repo=None)` | `Path` — `<repo>/.claude/testruns`. No I/O, no mkdir. | Mirrors `agent_forms.dispatch_dir` (`editor/agent_forms.py:140`). |
| `build_report(result)` | `dict` — the JSON document of §2b. No I/O. Pure function of the result object; this is the seam the tests drive. | Split out from `write_report` deliberately: it lets the round-trip test compare structures without touching disk. |
| `write_report(result, repo=None)` | `Path` — the **`.json`** path. Writes `<stamp>.json` and `<stamp>.md` beside it, `mkdir(parents=True, exist_ok=True)` first. Collision → `-2`, `-3`, … before the extension, applied to BOTH files so the pair always shares a stem. | The plan's named signature is `write_report(result) -> Path`; `repo=None` is the one additive keyword, defaulted, so that call shape still works. |
| `render_markdown(report)` | `str` — the `.md` body from a report dict. No I/O. | Kept public so TR-5 could preview without writing. |
| `agent_prompt(path, repo=None)` | `str` — the paste-at-Claude text of §2c, built by **reading the `.json` at `path`**. | The plan's signature takes the path, not the result: the prompt must be reproducible from a report on disk days later. |
| `load_report(path)` | `dict` — `json.loads` of the file. | The round-trip test's read half. |

Do not add any other public functions. Private helpers as needed; the one
required one is `_get(result, name, default)` (see §3b).

### 2b. Exact JSON schema of the report

`.claude/testruns/<YYYYMMDD-HHMMSS>.json`, keys sorted on write, 2-space
indent, trailing newline. This IS the document — do not add or rename keys:

```json
{
  "schema_version": 1,
  "kind": "gate",
  "gate_line": "GATE FAIL  2 problem(s)",
  "passed": false,
  "cancelled": false,
  "command": ["py", "tools/testgate.py", "check"],
  "started_at": "2026-08-13T09:41:02Z",
  "finished_at": "2026-08-13T09:47:38Z",
  "duration_s": 396.4,
  "totals": {
    "ran": 2245,
    "failed": 2,
    "unexpected_skips": 0,
    "subtest_failures": 0
  },
  "domains": {
    "buildings": {
      "label": "Buildings",
      "ran": 310, "passed": 310, "failed": 0,
      "skipped": 4, "subtest_failures": 0, "unexpected_skips": 0,
      "state": "done"
    },
    "enemies": {
      "label": "Enemies",
      "ran": 288, "passed": 286, "failed": 2,
      "skipped": 0, "subtest_failures": 0, "unexpected_skips": 0,
      "state": "done"
    }
  },
  "failures": [
    {
      "nodeid": "tools/tests/test_boss.py::TestBossPhases::test_phase_two_hp",
      "module": "test_boss.py",
      "domain": "enemies",
      "outcome": "FAILED",
      "traceback": "Traceback (most recent call last):\n  ...\nAssertionError: 240 != 260"
    }
  ],
  "unknown_modules": ["test_brand_new_thing.py"]
}
```

Field rules, all load-bearing:

- **`kind`** — `"gate"` for a full `tools/testgate.py check` run, `"domain"` for
  a per-area re-run (plan D2, L73–75). On `"domain"` the report additionally
  carries `"domain": "<key>"` at top level, and **`gate_line` MUST be `null`**.
  A per-area re-run report must never present a gate verdict.
- **`gate_line`** — the verbatim testgate line as TR-3 parsed it
  (`tools/testgate.py:219`, `:228`), or `null`. Never reconstructed here.
- **`passed`** — the boolean TR-3 computed. On `kind: "domain"` it means "this
  area's files were green", not "the gate passed".
- **`cancelled`** — `true` when the run did not complete. A cancelled run STILL
  writes a report (it is useful scratch) but its `gate_line` is `null` and
  `passed` is `false`. This flag is the one TR-6 keys on (§3c): a cancelled or
  crashed run must record nothing in the ledger (plan D4, L86–87).
- **`command`** — the argv list TR-3 ran, so the report says how to reproduce.
- **`started_at` / `finished_at`** — UTC ISO 8601 with a `Z` suffix,
  `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` — the exact
  format `editor/agent_forms.py:128` already uses. If the result object carries
  `datetime` objects, format them; if it carries floats (epoch), convert; if it
  carries strings already in that shape, pass them through.
- **`domains`** — one entry per domain the run touched, keyed by the TR-1 domain
  key. `label` is TR-1's display label (§2e). Missing counters default to `0`,
  missing `state` defaults to `"done"`.
- **`failures`** — one entry per failing node-ID, **sorted by `nodeid`** so two
  reports of the same failures are byte-comparable. `traceback` may be `""`
  when the stream carried none; the key is always present. Every failing
  node-ID TR-3 saw appears here — this is the plan's L201 pin.
- **`unknown_modules`** — test modules TR-3 could not map to a domain (plan
  L179–180: *"output for a file in no known domain (must surface, not
  vanish)"*). Sorted, may be empty, key always present.
- Absent optional data is represented by `null` or an empty list/dict, never by
  a missing key. A consumer must be able to index every key above.

The filename stamp is `finished_at` reduced the same way
`editor/agent_forms.py:146-147` reduces `created_at`: strip `-` and `:`,
`T` → `-`, drop the trailing `Z`, giving `20260813-094738`.

### 2c. The `.md` beside it

`render_markdown(report)` — a human artefact, so shape it for reading, not
parsing:

```markdown
# Test run — 2026-08-13 09:47:38Z

**GATE FAIL  2 problem(s)**   ·  full gate run  ·  6m 36s
Report: `.claude/testruns/20260813-094738.json`

| Area | Ran | Failed | Skipped | Unexpected skips |
|---|---|---|---|---|
| Buildings | 310 | 0 | 4 | 0 |
| Enemies | 288 | **2** | 0 | 0 |

## Failures

### Enemies
- `tools/tests/test_boss.py::TestBossPhases::test_phase_two_hp`

```
Traceback (most recent call last):
  ...
AssertionError: 240 != 260
```

## Test modules in no known domain
- `test_brand_new_thing.py` — add it to `tools/test_domains.py`.
```

Rules: rows in a stable order (TR-1's domain order, then any extras
alphabetically); a green run renders the table and the line
`No failures.` instead of a `## Failures` section; a `kind: "domain"` report
replaces the bold gate line with `Re-run of one area — this is not a gate.`;
the "no known domain" section is omitted entirely when the list is empty.

### 2d. The agent prompt text

`agent_prompt(path)` reads the JSON at `path` and returns a single block. It
must name the report path and the failing areas (plan L202). Failing case:

```
The editor ran the test suite. It failed.

  GATE FAIL  2 problem(s)

Report (JSON + Markdown, gitignored):
  .claude/testruns/20260813-094738.json
  .claude/testruns/20260813-094738.md

Failing areas: Enemies (2 failed), UI (1 failed).

Failing tests:
  tools/tests/test_boss.py::TestBossPhases::test_phase_two_hp
  tools/tests/test_hud.py::TestHud::test_love_counter
  ... and 3 more (full list + tracebacks in the report)

Please read the report, fix the failures, and re-check with a targeted run over
the files you touched. Which tests you may run is role-scoped — root CLAUDE.md
§"Test Suite Policy" is the only authority. The full gate already ran; do not
run it again to reproduce this.
```

Green case:

```
The editor ran the test suite. It passed.

  GATE PASS  2245 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips

Report: .claude/testruns/20260813-094738.json

Nothing to fix. This run is the handoff gate for this working tree.
```

Per-area case (`kind: "domain"`): opens `The editor re-ran one area (Enemies).
This is NOT a gate.` and omits any gate line.

Constraints the tests pin:
- The report's repo-relative POSIX path (forward slashes on Windows) appears in
  the string. Reuse the `handoff_relpath` idiom at
  `editor/agent_forms.py:161-168` — `.relative_to(repo).as_posix()`, falling
  back to the absolute path rather than raising when the report is outside the
  repo (a report is scratch; a prompt that raises is worse than one with a long
  path).
- Every failing area's **display label** appears, with its failure count.
- The node-ID list is capped (**cap at 8**, then `... and N more`) so the prompt
  stays pasteable; the report holds the full list.
- The last paragraph routes to root `CLAUDE.md` §"Test Suite Policy" rather than
  restating a rule — that section is the only authority and must not be forked
  into this string.
- No tracebacks in the prompt. They live in the report.

### 2e. Domain labels — guarded import

Labels come from TR-1 (`tools/test_domains.py`, plan L123–125: *"plus a display
label per domain"*). Import it inside a `try/except ImportError` and fall back
to `key.replace("_", " ").title()`. Reason: this module must stay independently
importable and independently testable even if TR-1's label accessor is named
differently than the plan's prose implies. If the result object already carries
a `label` per domain, prefer that; then TR-1; then the fallback. Do not make
`editor/test_report.py` hard-fail on a TR-1 API detail — that would couple two
phases through an unversioned name.

---

## 3. File scope + shared-file contract

**New (owned entirely by TR-4):**
- `editor/test_report.py`
- `tools/tests/test_editor_test_report.py`

**Modified (shared — keep each edit surgical):**

| File | Exact insertion point | Other phases |
|---|---|---|
| `.gitignore` | Append **one line** immediately after `.claude/worktrees/` (`.gitignore:19`), inside the "Editor / tooling state" block that starts at `.gitignore:15`: `.claude/testruns/`. Change nothing else in the file. | none |
| `tools/tests/test_editor_viewport.py` | `TestPurity.test_editor_does_not_import_game` builds one implicit-concatenation `import …` string (`tools/tests/test_editor_viewport.py:1491-1528`). Add **exactly one line**, `"editor.test_report, "`, immediately after `"editor.timeline_curve, editor.timeline_ops, "` (`:1520`) and **before** the `# ES-1:` comment at `:1521`. Its own line; change nothing else. | TR-3 adds `"editor.test_runner, "` as a sibling line at the same anchor; TR-5 adds `"editor.panels.test_run_panel, "`. One line each keeps the merge trivial. If TR-3's line is already there, put yours directly after it. |

Required by `editor/CLAUDE.md:77-78` (*"Every new editor module MUST be added to
`test_editor_viewport.TestPurity`'s import list"*) — the plan's TR-4 file list
(L193–198) omits it; the package doc's hard rule wins. Flagged as an open item.

**Do NOT touch:** `editor/test_runner.py`, `editor/main.py`,
`editor/panels/**`, `tools/test_domains.py`, `tools/testguard_ledger.py`,
`.claude/hooks/test_guard.py`, `tools/testgate.py`, `data/**`, root `CLAUDE.md`,
`PLAN.md`.

### 3a. Doc update

None required. `editor/CLAUDE.md:40-58` already covers "pure helpers used by
panels … all Qt-free/pygame-free, in `TestPurity`", and `editor/test_report.py`
is exactly that kind. TR-5 owns the editor-doc section for this feature (plan
L224–225). Do not pre-write it.

### 3b. The TR-3 `result` contract — ASSUMED, must be reconciled

**TR-3's brief (`docs/briefs/phase-TR-3-run-engine.md`) does not exist at the
time of writing, and `editor/test_runner.py` does not exist on disk (verified:
`ls editor/test_runner.py` → no such file).** The contract below is TR-4's
*assumption*, derived from plan L168–180. The orchestrator must reconcile it
with TR-3's actual output before TR-5 wires the two together.

Assumed shape — a `RunResult` (dataclass or plain object) with these attributes:

```python
result.kind              # "gate" | "domain"
result.domain            # str | None   — set only when kind == "domain"
result.gate_line         # str | None   — verbatim testgate line, None for a domain run
result.passed            # bool
result.cancelled         # bool
result.command           # list[str]    — the argv that was run
result.started_at        # datetime (UTC) | float epoch | ISO-Z str
result.finished_at       # same
result.domains           # dict[str, obj] — domain key -> counters object/mapping with
                         #   .ran .passed .failed .skipped .subtest_failures
                         #   .unexpected_skips .state (and optionally .label)
result.failures          # iterable of objects/mappings with
                         #   .nodeid .module .domain .outcome .traceback
result.unknown_modules   # iterable[str]
```

**Insulate against drift with ONE helper.** Every read of the result goes
through:

```python
def _get(obj, name, default=None):
    """Read `name` off an object OR a mapping; missing -> default."""
```

so `build_report` works identically against a TR-3 dataclass and against the
canned dicts the tests use. Derive `totals` (`ran`/`failed`/
`unexpected_skips`/`subtest_failures`) by **summing the per-domain counters**
rather than reading a separate total, unless the result carries an explicit
`totals` — one fewer field to agree on. `duration_s` is computed from
`finished_at - started_at` when the result does not carry it.

If TR-3 lands a materially different shape (different attribute names, a
different failure record), the fix belongs in `build_report`'s reads and
nowhere else — that is the whole point of routing every read through `_get`.
**Report the delta upward rather than editing `editor/test_runner.py`.**

### 3c. TR-6 modifies this file — the named insertion point

Plan TR-6 (L244–247) says *"modified: `editor/test_report.py` or
`editor/main.py` — on a COMPLETED full run only, call `record_run(...,
source="editor")`."* To make that a one-place edit, TR-4 must leave a seam:

- `write_report` ends with a single `return path`, and the last thing before it
  is a **lone comment line**:
  `# TR-6 inserts the ledger record here: a COMPLETED full run only.`
  placed immediately after both files are written and immediately before the
  `return`.
- The condition TR-6 will use must be computable from the report dict already
  in scope at that point: `report["kind"] == "gate" and not
  report["cancelled"] and report["gate_line"] is not None`. Keep that dict in a
  local named `report` so TR-6's insert reads naturally.
- **TR-4 must NOT import `tools.testguard_ledger`** and must not write a
  no-op hook function for it. The seam is a comment and a well-named local,
  nothing more; an unused import or an empty hook is a half-built feature that
  looks finished.

---

## 4. Exit gate + Quick Test

### Exit gate (run from the repo root — these three commands, nothing wider)

```bash
py tools/smoke.py
py -m pytest tools/tests/test_editor_test_report.py -q
py -m pytest tools/tests/test_editor_viewport.py::TestPurity -q
```

`py tools/smoke.py` must still print its data-file count and `OK` — TR-4 adds
no `data/` file, so the count is unchanged from before your edit; if it moved,
you touched something you should not have. The third command is the purity
guard for the one line you added at `tools/tests/test_editor_viewport.py:1520`
— run **that node only**, never the whole `test_editor_viewport.py` file (it is
the Qt tier and takes minutes).

**Which tests you may run is role-scoped: root `CLAUDE.md` §"Test Suite Policy"
is the only authority, and a `PreToolUse` hook enforces it.** You are a
subagent, so those three commands are your ceiling — no full suite, no
`py tools/testgate.py check`, no `--affected`, no tier sweep (`-m core` /
`-m editor` / `-m meta`). All four are DENIED to you and produce a stalled
agent, not a result. The single full gate belongs to the main session at
handoff and is not part of this phase. The gate is ZERO failures.

### Required tests in `tools/tests/test_editor_test_report.py`

Plan L200–203. **Every test builds a canned result object in the test file and
writes into a `tempfile.TemporaryDirectory()` repo. No test may import
`editor.test_runner`, shell out to pytest/testgate, or touch the real
`.claude/`.** Give the file a module-level helper `_canned(**overrides)`
returning a plain dict in the §3b shape so each test states only its delta.

Suggested classes (names are the contract for later phases):

- **`TestBuildReport`** — a failing canned result produces every key in §2b;
  `failures` is sorted by `nodeid`; per-domain counters survive verbatim;
  `totals` equals the sum of the per-domain counters; a `kind: "domain"` result
  yields `gate_line is None` and a top-level `"domain"` key.
- **`TestRoundTrip`** — `write_report` then `load_report` gives back a dict
  equal to `build_report(result)` (plan L200: *"the report round-trips (write
  then read gives the same failures)"*); the file text ends in a newline and is
  stable across two writes of the same result.
- **`TestFailingNodeIds`** — a canned result with 5 failures across 2 domains:
  all 5 node-IDs appear in the JSON, each with its `traceback` string intact
  (assert on a distinctive substring, not the whole blob), and each carries the
  domain TR-3 assigned.
- **`TestPathsAndCollision`** — the written path is under
  `<tmp>/.claude/testruns/`, the stem matches
  `^[0-9]{8}-[0-9]{6}(-[0-9]+)?$`, a `.md` exists beside it with the same stem,
  and writing twice with the same `finished_at` produces a `-2` pair (both
  files sharing the stem, no overwrite).
- **`TestGreenRunStillWrites`** — a `GATE PASS` canned result writes both files
  with `failures == []`, and `agent_prompt` returns a non-empty string
  containing the report path and the word `PASS` (plan L203).
- **`TestAgentPrompt`** — the prompt names the report's repo-relative POSIX
  path (assert `"\\" not in` the path fragment), names each failing area's
  display label with its count, caps the node-ID list at 8 with an
  `and N more` tail, contains no traceback text, and for a `kind: "domain"`
  report contains no `GATE` line.
- **`TestCancelledRun`** — a cancelled canned result still writes both files,
  with `cancelled` true, `gate_line` null and `passed` false. (This is the case
  TR-6 must refuse to record — the test pins the flag it will read.)
- **`TestUnknownModules`** — a canned result carrying an unmapped module lands
  it in `unknown_modules` and in the `.md`, sorted, never silently dropped
  (plan L179–180).

Keep the file to bare-minimum coverage of the behaviours above — one clear
assertion per behaviour, no exhaustive matrices.

### Quick Test (for the PR body — run by the orchestrator or the user, not you)

Plan L205–207. From the repo root:

```bash
py -c "from editor import test_report as tr; \
r={'kind':'gate','gate_line':'GATE FAIL  1 problem(s)','passed':False,'cancelled':False, \
   'command':['py','tools/testgate.py','check'], \
   'started_at':'2026-08-13T09:41:02Z','finished_at':'2026-08-13T09:47:38Z', \
   'domains':{'enemies':{'label':'Enemies','ran':288,'passed':287,'failed':1,'skipped':0, \
              'subtest_failures':0,'unexpected_skips':0,'state':'done'}}, \
   'failures':[{'nodeid':'tools/tests/test_boss.py::TestBossPhases::test_phase_two_hp', \
                'module':'test_boss.py','domain':'enemies','outcome':'FAILED', \
                'traceback':'AssertionError: 240 != 260'}], \
   'unknown_modules':[]}; \
p=tr.write_report(r); print(p); print(tr.agent_prompt(p))"
```

Expect: a path under `.claude/testruns/`, the `.md` beside it, and a printed
prompt that names the report path with forward slashes and says
`Failing areas: Enemies (1 failed)`. Then:

1. Open the `.md` in an editor — the table and the traceback block read cleanly,
   no raw dict repr, no broken fences.
2. Confirm `git status` does NOT list `.claude/testruns/` (the `.gitignore`
   line works).
3. Paste the printed prompt into a Claude session and confirm it reads as a
   usable task on its own — the agent can find the report and knows which area
   is red without being told anything else.

Delete the generated report afterwards, or leave it — it is gitignored scratch.
