# Phase TR-2 — One owner of the ledger key

Plan: `planning/TestRunnerPLAN.md` §"TR-2 — One owner of the ledger key"
(`planning/TestRunnerPLAN.md:138-160`), Decision D3
(`planning/TestRunnerPLAN.md:76-80`) and D4 (`planning/TestRunnerPLAN.md:82-87`).
Package: **tools**. Depends on: nothing. Blocks: TR-6.

This is a **pure extraction**. The hook's observable behaviour — every exit
code, every deny message, every key it writes — must be byte-identical
afterwards. If you find yourself improving the guard, stop: that is TR-6 or a
different task.

---

## 1. Behavioral spec

### What exists today

`.claude/hooks/test_guard.py` is a standalone script registered on four hook
events (`.claude/hooks/test_guard.py:25-29`). It owns, privately, the four
pieces of logic that identify a test run:

| Piece | Today | Role |
|---|---|---|
| `_state()` | `.claude/hooks/test_guard.py:56-99` | the guard's per-worktree state dir, resolved via `git rev-parse --git-dir`; honours `TESTGUARD_STATE_DIR` |
| `normalised_target()` | `.claude/hooks/test_guard.py:163-176` | the command reduced to *what it runs* |
| `_git_bytes()` / `SEP` / `tree_fingerprint()` | `.claude/hooks/test_guard.py:183-220` | hash of HEAD + diff content + untracked list |
| the key expression | `.claude/hooks/test_guard.py:446` | `sha256(f"{target}\n{fingerprint}")[:32]` |

The ledger record is written by `post()` at
`.claude/hooks/test_guard.py:504-508` as `<state>/run-<key>.json` carrying
`finished`, `target`, `outcome`; the repeat guard reads it back at
`.claude/hooks/test_guard.py:446-465` and denies with exit 2 when the record is
younger than `REPEAT_TTL_SECONDS` (`.claude/hooks/test_guard.py:113`).

Two details are load-bearing and easy to break:

1. **The key is computed at PreToolUse and stashed in the lock**
   (`.claude/hooks/test_guard.py:469-472`), then re-used verbatim by `post()`
   (`.claude/hooks/test_guard.py:492`, `504`). It is **not** recomputed after
   the run. If the tree changes *during* a run, the record must still land
   under the pre-run key. A `record_run` that recomputes the fingerprint would
   silently file every long run under a key nothing looks up — the exact
   failure D3 exists to prevent (`planning/TestRunnerPLAN.md:76-80`).
2. **A broken guard must ALLOW.** `main()` swallows every exception and returns
   0 (`.claude/hooks/test_guard.py:528-530`); the whole contract is stated at
   `.claude/hooks/test_guard.py:31-33` and pinned by
   `tools/tests/test_test_guard.py:294-310`. An unguarded top-level `import`
   in the hook runs *before* `main()`, so an import failure would bypass that
   protection and print a traceback on every Bash call in the session.

The tests drive the hook as a subprocess with fabricated hook JSON
(`tools/tests/test_test_guard.py:46-74`), so they pin behaviour, not layout —
they must pass **unchanged** (`planning/TestRunnerPLAN.md:152-154`). Two
classes do reach inside the module by name and must keep working:
`TestLivenessProbe` (`tools/tests/test_test_guard.py:223-291`, uses
`_looks_like_a_test_process`, `_probe_command_lines`, `_lock_is_dead`, and
rebinds `guard.subprocess`) and `TestClassification`
(`tools/tests/test_test_guard.py:313-338`, uses `classify`).

### What must be true after this phase

- `tools/testguard_ledger.py` exists and exports `state_dir`,
  `normalised_target`, `tree_fingerprint`, `run_key`, `record_run` — importable
  from anywhere in the repo with no Qt, no pygame, no import of anything under
  `.claude/`.
- `.claude/hooks/test_guard.py` contains **no copy** of that logic; it imports
  it. Its deny messages, exit codes and JSON layout are unchanged.
- A caller outside the hook (TR-6's editor) that calls
  `run_key("py tools/testgate.py check")` gets the *same* string the hook would
  have computed for that command on the same tree.
- `record_run` writes a file the hook's repeat guard reads back and denies on.

---

## 2. Architecture plan

### 2.1 New file — `tools/testguard_ledger.py`

Module docstring must say, in one paragraph: this is the ONE owner of the key
that identifies a test run; the hook and the editor both import it; two copies
of this logic drift and the failure is silent (D3,
`planning/TestRunnerPLAN.md:76-80`).

Imports: `hashlib`, `json`, `os`, `re`, `subprocess`, `tempfile`, `time`,
`from pathlib import Path`. Plus `from __future__ import annotations`.

```python
REPO = Path(__file__).resolve().parents[1]   # tools/ -> repo root

_STATE_CACHE: list = []
```

Then, **moved verbatim** (docstrings included — they carry the incident history
and must not be summarised away):

- `_state()` from `.claude/hooks/test_guard.py:56-99`, **renamed `state_dir()`**.
  Body unchanged; it already reads `REPO`, which now resolves to the same path.
- `normalised_target()` from `.claude/hooks/test_guard.py:163-176`, unchanged.
  Add one sentence to the docstring: it is **idempotent** — normalising an
  already-normalised target returns it unchanged — which is what lets `run_key`
  accept either a raw command or a target.
- `_git_bytes()` from `.claude/hooks/test_guard.py:183-199`, `SEP` from
  `.claude/hooks/test_guard.py:202`, `tree_fingerprint()` from
  `.claude/hooks/test_guard.py:205-220`, all unchanged. `SEP` is
  `b"\x1f"`-style unit separator written as a literal in the source — copy the
  literal byte-for-byte from the file, do not retype it from this brief.

Two new functions:

```python
def run_key(command: str, fingerprint: str | None = None) -> str:
    """The ledger key for `command` against a working tree.

    `command` may be a raw shell command or an already-normalised target —
    `normalised_target` is idempotent, so both give the same key. Pass
    `fingerprint` to key against a tree state captured EARLIER (the hook does
    this: it keys at PreToolUse and records under that same key at
    PostToolUse, so an edit made *during* a run cannot move the record).
    """
    target = normalised_target(command)
    if fingerprint is None:
        fingerprint = tree_fingerprint()
    return hashlib.sha256(f"{target}\n{fingerprint}".encode()).hexdigest()[:32]
```

The f-string is copied from `.claude/hooks/test_guard.py:446` and must stay
byte-identical, `\n` separator and `[:32]` truncation included.

```python
def record_run(state_dir, target, outcome, source="agent", key=None):
    """Write the ledger record the repeat guard reads back. Returns the Path.

    `state_dir` is the directory (a Path), NOT this module's `state_dir()`
    function — callers pass `state_dir()` themselves. Never call the module
    function from inside this body; the parameter shadows it.

    `key=None` computes the key from `target` against the CURRENT tree. The
    hook passes the key it stashed at PreToolUse instead.
    """
```

Body: `key = key or run_key(target)`; `state_dir.mkdir(parents=True,
exist_ok=True)` (defensive — `pre()` already creates it, and TR-6's editor
caller may not have); write `json.dumps({"finished": time.time(), "target":
target, "outcome": outcome, "source": source})` to `state_dir /
f"run-{key}.json"` with `encoding="utf-8"`; return the path.

The `"source"` field is **new but inert** in this phase: nothing reads it yet.
TR-6 adds the reader. Do not touch the deny message.

### 2.2 Modified — `.claude/hooks/test_guard.py`

**Import strategy (the hook is a standalone script, not a package member).**
`REPO` is already computed at `.claude/hooks/test_guard.py:51`. Immediately
after it, insert:

```python
# The ledger key lives in tools/ so the editor can import it too (TestRunner
# plan, D3). The hook runs as a standalone script, so put the repo ROOT on
# sys.path and import the package path — never `sys.path.insert(REPO/"tools")`,
# which would shadow stdlib-adjacent names with this repo's tools/*.py.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
try:
    from tools.testguard_ledger import (          # noqa: E402
        normalised_target, record_run, run_key, state_dir)
except Exception as _ledger_error:                 # a broken guard must ALLOW
    print(f"test_guard: ledger unavailable ({_ledger_error})", file=sys.stderr)
    raise SystemExit(0)
```

The `try` is not optional: a top-level `ImportError` fires before `main()`'s
blanket handler (`.claude/hooks/test_guard.py:528-530`) and would traceback on
every Bash call. Exiting 0 there is "allow", which is the documented failure
direction (`.claude/hooks/test_guard.py:31-33`). `sys` is already imported at
`.claude/hooks/test_guard.py:47`; keep the existing import block where it is
and put this stanza after `REPO`.

Deletions (and nothing else):

| Delete | Replace with |
|---|---|
| `_STATE_CACHE` (`:53`) and `_state()` (`:56-99`) | one line, at `:53`'s position: `_state = state_dir  # noqa: E305 — alias keeps every call site below unchanged` |
| `normalised_target()` (`:163-176`) | nothing (imported) |
| `_git_bytes()`, `SEP`, `tree_fingerprint()` (`:183-220`) and their section banner comment (`:179-181`) | nothing (imported) |

Keep the alias. `_state()` is called at `.claude/hooks/test_guard.py:242, 243,
268, 285, 389, 447, 504` — aliasing keeps those seven call sites byte-identical
and keeps this phase's diff away from TR-6's.

Whether `hashlib`, `tempfile` and `subprocess` are still needed in the hook:
`subprocess` **yes** (`_probe_command_lines`, and
`tools/tests/test_test_guard.py:268-282` rebinds the name in the hook's
namespace — do not remove it). `hashlib` and `tempfile` become unused once
`_state`, `tree_fingerprint` and the key expression are gone; drop those two
imports only after confirming no other use remains in the file.

Two call-site edits:

- `pre()`, currently `.claude/hooks/test_guard.py:444-446`:
  ```python
  target = normalised_target(command)
  key = run_key(target)
  ```
  (the local `fingerprint` variable disappears; nothing else reads it). The
  lock write at `:469-472` is unchanged.
- `post()`, currently `.claude/hooks/test_guard.py:504-508`: replace the
  `write_text` with
  ```python
  record_run(_state(), lock.get("target"), outcome, source="agent",
             key=key)
  ```
  Passing `key=key` — the key the lock carried — is what preserves detail (1)
  from §1. Everything above it in `post()` (`:480-502`) is untouched.

### 2.3 Modified — `tools/tests/test_test_guard.py`

Add ONE class, `TestLedgerIsOneOwner(GuardCase)`, with two tests (bare minimum;
do not expand coverage beyond the plan's line
`planning/TestRunnerPLAN.md:152-155`):

1. **The hook and a direct `run_key` agree.** `self.start("S-MAIN",
   subagent=False)`; `self.pre(TARGETED)`; `self.post(TARGETED, "49 passed")`;
   then in-process `from tools.testguard_ledger import run_key` and assert
   `(self.state / f"run-{run_key(TARGETED)}.json")` exists and its `outcome`
   contains `"49 passed"`. (The test writes no files between the two, so the
   fingerprint cannot move.)
2. **`record_run` writes what the repeat guard reads.** Call `record_run` in
   process into `self.state` with `TARGETED` and a fabricated outcome, then
   assert `self.pre(TARGETED)` returns 2 and the message quotes that outcome.
   This is the round-trip the editor will rely on in TR-6 — and it needs no
   real test run at all.

`tools/` is a package (`tools/__init__.py` exists, empty) and sibling suites
already do `from tools.x import y` (e.g.
`tools/tests/test_bake_ui_sheets.py:22`), so import it that way — no
`sys.path` juggling in the test.

---

## 3. File scope + shared-file contract

**You may touch exactly these three files. Nothing else.**

| File | Change |
|---|---|
| `tools/testguard_ledger.py` | NEW (§2.1) |
| `.claude/hooks/test_guard.py` | MODIFIED (§2.2) |
| `tools/tests/test_test_guard.py` | MODIFIED (§2.3) |

Explicitly **not** in scope: `CLAUDE.md` (TR-6 edits §"Test Suite Policy"),
`tools/testgate.py`, `.claude/settings.json`, anything under `editor/`.

### Shared-file contract with TR-6

TR-6 also modifies `.claude/hooks/test_guard.py` and
`tools/tests/test_test_guard.py` (`planning/TestRunnerPLAN.md:244-252`). Hold
these lines so TR-6 layers cleanly:

**`.claude/hooks/test_guard.py`**

| Region | Owner | Rule |
|---|---|---|
| imports + `REPO` + the ledger-import stanza (`:39-53`) | **TR-2** | TR-6 must not touch it |
| the `_state = state_dir` alias line | **TR-2** | TR-6 must not touch it |
| `pre()` guard-2 **deny message** string, currently `:452-465` | **TR-6** | TR-2 leaves it **byte-identical**, including `record.get("outcome")` at `:451`. TR-6 adds `record.get("source")` to it. Do not reflow, re-indent, or reword this string. |
| `pre()` key computation, currently `:444-446` | **TR-2** | TR-6 must not touch it |
| `post()` body, currently `:480-509` | **TR-2** | TR-6 reads the `source` it writes but must not re-edit the write |

Net effect: TR-2 changes the *top* of the file and the two computation sites;
TR-6 changes one string literal in the middle. They do not overlap.

**`tools/tests/test_test_guard.py`** — anchored appends, two different anchors:

- **TR-2** inserts `class TestLedgerIsOneOwner(GuardCase)` between
  `TestClassification` (ends `tools/tests/test_test_guard.py:338`) and
  `class TestThePolicyIsStatedOnce` (`tools/tests/test_test_guard.py:341`).
- **TR-6** appends its class at the END of the file, after
  `TestThePolicyIsStatedOnce` and immediately before the
  `if __name__ == "__main__":` block (`tools/tests/test_test_guard.py:440-441`).

Do not renumber, reorder, or edit any existing class in this file. Existing
tests pass **unchanged** or the extraction is wrong
(`planning/TestRunnerPLAN.md:152-154`).

### Interaction with TR-1

None. TR-2 adds no new module to `tools/tests/`, so TR-1's exactly-one-domain
table (`planning/TestRunnerPLAN.md:116-134`) needs no new entry. The two
phases can land in either order.

---

## 4. Exit gate + Quick Test

You are a **subagent**. Root `CLAUDE.md` §"Test Suite Policy" governs and
overrides anything wider you read anywhere else, including in the plan doc.
Run exactly these, nothing wider:

```bash
py tools/smoke.py
py -m pytest tools/tests/test_test_guard.py -q
```

**Do not** run the full suite, `py tools/testgate.py check`, `--affected`, or a
tier sweep (`-m core` / `-m editor` / `-m meta`). The guard you are editing
DENIES all four from a subagent — you would produce a denied command, not a
check. The single full gate is the main session's, once, at handoff.

The gate is **GATE PASS / zero failures**, and an unexpected skip counts as a
failure.

### Quick Test — replaces the plan's

The plan's Quick Test (`planning/TestRunnerPLAN.md:158-160`, "run any targeted
pytest twice in a row in a Claude session — the second is still denied") is
**not executable by you**. Its whole point is that the second run is blocked,
so following it means deliberately provoking a denial; worse, the first run
consumes your one allowed run of that target on an unchanged tree, so your real
gate above would then be denied too. Use these instead — neither launches a
test run:

**(a) The module computes a stable key, no run involved.** Note the string
splicing: any shell command containing the literal token `pytest`, `testgate`
or `unittest` is classified by the hook you are editing and would take its
in-flight lock (`.claude/hooks/test_guard.py:123`, `:469-472`). Keep the token
broken.

```bash
py -c "from tools.testguard_ledger import normalised_target, run_key; t = normalised_target('py -m py' + 'test tools/tests/test_boss.py -q'); print(t); print(run_key(t)); print(run_key(t) == run_key('QT_QPA_PLATFORM=offscreen ' + t + ' -v'))"
```

Expect: the normalised target printed without the env prefix and without `-q`,
a 32-char hex key, and `True` — the same tree and the same tests give one key
regardless of reporting flags.

**(b) The hook still runs at all.** Feed it a malformed payload and confirm it
allows (this is the fail-open contract, and it exercises the new import path):

```bash
echo "not json" | py .claude/hooks/test_guard.py; echo "exit=$?"
```

Expect `exit=0` and no traceback. A traceback here means the ledger import is
wrong.

**(c) For the orchestrator/user, not you:** in a fresh Claude session, run a
targeted test file twice and confirm the second is denied with the first's
result quoted, and that touching any file clears the denial.

Report: the three files' paths, the gate line, and — tagged **measured** — the
output of (a) and (b).
