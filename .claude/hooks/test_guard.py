#!/usr/bin/env python
"""Mechanically enforce the ONE test policy (root CLAUDE.md, §"Test Suite Policy").

The policy was prose for months and prose lost, every time, in three specific
ways this hook closes:

  1. **Role.**   A subagent ran the full suite because the router it is handed
                 verbatim also contained a section headed "Universal exit gate".
  2. **Repeat.** An agent ran the same targeted selection five, ten times in a
                 row without editing anything in between — the behaviour the
                 user described as "screaming at agents to skip testing after
                 they've already run the affected tests like 10 times".
  3. **Overlap.** Two runs in flight at once, which exhausts memory and makes
                 both slower, so the agent concludes the suite is flaky.

Guard 3 has a failure mode of its own, and it has bitten: a tool call that dies
inside the harness never reaches PostToolUse, so its lock outlives it and
blocks everyone for twenty minutes over nothing. `_lock_is_dead` closes that by
checking whether a test process actually exists before blocking anyone.

Guards 2 and 3 need no notion of who is asking and are therefore always on.
Guard 1 needs to tell a subagent from the main session; see `_role()` for how
that is established and why it FAILS OPEN.

Events (all four registered in `.claude/settings.json`):
  SessionStart / SubagentStart -> record this session's role
  PreToolUse (Bash|PowerShell) -> allow, or deny with a reason
  PostToolUse (Bash|PowerShell) -> release the lock, remember the outcome

Contract: exit 0 allows. **Exit 2 blocks the call and shows stderr to the
model** — that is the whole enforcement mechanism. Any internal error exits 0:
a broken guard must never be able to wedge a session.

Escape hatch: `TESTGUARD_OFF=1` in the environment disables every guard. It is
deliberately an env var and not a flag in the command, so it cannot be reached
by an agent editing its own command line, and it shows up in the transcript.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_STATE_CACHE: list = []


def _state() -> Path:
    """The guard's private state directory: `<real git dir>/testguard`.

    Resolved through `git rev-parse --git-dir`, NEVER as a literal
    `REPO/.git/testguard`. In a linked worktree — which this repo's own
    branching rules REQUIRE for concurrent agents — `.git` is a *file*
    containing a `gitdir:` pointer, so the literal path made `mkdir(parents=
    True)` try to create a directory over that file and raise `WinError 183`.
    Every guard then swallowed the error and allowed the run: the enforcement
    silently did nothing, which is the worst possible failure mode for a guard.

    Resolving it also gives per-worktree isolation for free, which is what you
    want: two agents in two worktrees must not share a lock or a repeat ledger.
    Falls back to a repo-keyed temp dir if git is unavailable for any reason.
    """
    if _STATE_CACHE:
        return _STATE_CACHE[0]
    # Test seam (and a manual escape hatch): point the guard at a scratch
    # directory so its own test suite cannot disturb the live session's lock
    # or repeat ledger — the guard runs on every Bash call INCLUDING the ones
    # pytest itself is invoked with.
    override = os.environ.get("TESTGUARD_STATE_DIR")
    if override:
        path = Path(override)
        _STATE_CACHE.append(path)
        return path
    path = None
    try:
        out = subprocess.run(["git", "rev-parse", "--git-dir"], cwd=REPO,
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="replace")
        gitdir = out.stdout.strip()
        if gitdir:
            candidate = Path(gitdir)
            if not candidate.is_absolute():
                candidate = REPO / candidate
            path = candidate / "testguard"
    except Exception:
        path = None
    if path is None:
        digest = hashlib.sha256(str(REPO).encode()).hexdigest()[:16]
        path = Path(tempfile.gettempdir()) / f"testguard-{digest}"
    _STATE_CACHE.append(path)
    return path

#: A run older than this is assumed dead (the process was killed, the machine
#: slept, a hook was missed) and its lock is ignored rather than wedging every
#: later run. Deliberately longer than the slowest observed full suite (~6 min).
#:
#: This is the BACKSTOP, not the primary release. `_lock_is_dead` looks at
#: whether a test process is actually running and releases the lock the moment
#: one is not, so a crashed run costs nobody twenty minutes. See its docstring.
LOCK_STALE_SECONDS = 20 * 60

#: How long a recorded run keeps suppressing an identical repeat. Long enough
#: to cover a working session, short enough that a stale record cannot haunt a
#: later one forever.
REPEAT_TTL_SECONDS = 6 * 60 * 60


# --------------------------------------------------------------------------
# command classification
# --------------------------------------------------------------------------

#: Cheap pre-filter. The hook fires on EVERY Bash/PowerShell call, so anything
#: that is obviously not a test command must cost one regex and nothing else —
#: no git, no disk.
_LOOKS_LIKE_TESTS = re.compile(r"\b(pytest|testgate|unittest)\b")

_TIER_SWEEP = re.compile(r"-m\s+[\"']?(core|editor|meta)\b")
_TEST_PATH = re.compile(r"tools[/\\]tests[/\\]\S+\.py")


def classify(command: str) -> str:
    """`full` | `tier` | `affected` | `targeted` | `none`.

    `full` is the expensive whole-suite run in any of its spellings; `tier` is
    a marker sweep (hundreds of tests); `affected` is testgate's narrowing mode
    (which also runs the whole core tier as its safety pass); `targeted` names
    specific test files. `none` means "not a test command" and is the fast path.
    """
    if not _LOOKS_LIKE_TESTS.search(command):
        return "none"

    if "unittest" in command and "discover" in command:
        return "full"

    if "testgate" in command:
        if "--affected" in command:
            return "affected"
        if re.search(r"\b(check|snapshot)\b", command):
            return "full"
        return "none"          # `testgate --help` and friends

    if "pytest" in command:
        if _TEST_PATH.search(command):
            # Naming files wins even alongside `-m`: pytest collects only those
            # files, so this is genuinely narrow.
            return "targeted"
        if _TIER_SWEEP.search(command):
            return "tier"
        # Bare `pytest` collects `testpaths` — the whole suite.
        return "full"

    return "none"


def normalised_target(command: str) -> str:
    """The command reduced to what it actually RUNS, for fingerprinting.

    Strips leading environment assignments (`QT_QPA_PLATFORM=offscreen ...`),
    collapses whitespace, and drops flags that change reporting but not which
    tests execute — so `-q` vs `-v`, or a different `-n`, is correctly treated
    as the same run rather than as a fresh one.
    """
    cmd = command.strip()
    cmd = re.sub(r"^(?:\s*[A-Za-z_][A-Za-z_0-9]*=\S*\s+)+", "", cmd)
    cmd = re.sub(r"\$env:[A-Za-z_][A-Za-z_0-9]*\s*=\s*\S+\s*;?\s*", "", cmd)
    cmd = re.sub(r"\s+-(?:q|v|vv|s|x)\b", " ", cmd)
    cmd = re.sub(r"\s+--no-header\b|\s+--tb=\S+|\s+-p\s+\S+|\s+-n\s*\S+", " ", cmd)
    return re.sub(r"\s+", " ", cmd).strip()


# --------------------------------------------------------------------------
# working-tree fingerprint
# --------------------------------------------------------------------------

def _git_bytes(*args: str) -> bytes:
    """Raw stdout, NEVER decoded.

    `text=True` decodes with the locale codec, which on Windows is cp1252 —
    and `git diff HEAD` in this repo carries bytes it cannot represent (an
    imported `.otf`, any non-latin-1 content). The decode blew up inside
    subprocess's reader THREAD, so `run()` returned normally with `stdout` set
    to `None`, the join below raised "expected str instance, NoneType found",
    and the blanket handler in `main()` swallowed it and ALLOWED the run. Both
    stateful guards were silently dead. Hash the bytes; never decode them.
    """
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, timeout=20)
        return out.stdout or b""
    except Exception:
        return b""


SEP = b""   # unit separator: cannot occur in git output we hash


def tree_fingerprint() -> str:
    """A hash that changes whenever anything that could change a test result does.

    HEAD + the full CONTENT of every tracked modification + the list of
    untracked files. Content, not `git status`, is load-bearing: `status` marks
    a file `M` and keeps saying `M` no matter how many times you edit it, so a
    status-only hash would call a real fix "unchanged" and wrongly deny the
    re-run that would have proved it.
    """
    digest = hashlib.sha256()
    for args in (("rev-parse", "HEAD"),
                 ("diff", "HEAD"),
                 ("ls-files", "--others", "--exclude-standard")):
        digest.update(_git_bytes(*args))
        digest.update(SEP)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# role
# --------------------------------------------------------------------------

def _session_id(payload: dict) -> str:
    for key in ("session_id", "sessionId"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def mark_role(payload: dict) -> int:
    """Record this session's role at SessionStart / SubagentStart.

    **A `main` marker is never downgraded to `sub`.** When a subagent inherits
    its parent's session id, its `SubagentStart` writes to the SAME marker path
    the parent's `SessionStart` wrote — so a plain write would relabel the main
    session `sub` and deny it the one full `testgate check` the whole policy is
    built around. That is not hypothetical: it denied phase G2's handoff gate.
    `_role()` is documented to fail OPEN for exactly this collision, and this
    guard is what makes that docstring true.
    """
    sid = _session_id(payload)
    if not sid:
        return 0
    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    role = "sub" if event == "SubagentStart" else "main"
    _state().mkdir(parents=True, exist_ok=True)
    marker = _state() / f"role-{_safe(sid)}"
    if role == "sub":
        try:
            if marker.read_text(encoding="utf-8").strip() == "main":
                return 0
        except OSError:
            pass
    marker.write_text(role, encoding="utf-8")
    return 0


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", text)[:120]


def _role(payload: dict) -> str:
    """`sub`, `main`, or `unknown`.

    **This FAILS OPEN, on purpose.** A subagent is only ever identified by a
    marker written at `SubagentStart` for THIS session id. If the id is absent,
    or the runtime turns out to give a subagent the same session id as its
    parent (in which case the parent's `main` marker is what is on disk), the
    answer is `main`/`unknown` and the role guard simply does not fire.

    That is the right way round: guards 2 and 3 already stop the reported
    behaviour without knowing who is asking, so a role guard that occasionally
    misses costs little, while one that wrongly fires would block the MAIN
    session from the single full run the whole policy is built around.
    """
    sid = _session_id(payload)
    if not sid:
        return "unknown"
    marker = _state() / f"role-{_safe(sid)}"
    try:
        return marker.read_text(encoding="utf-8").strip() or "unknown"
    except OSError:
        return "unknown"


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def _deny(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _lock_path() -> Path:
    return _state() / "inflight.json"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# --------------------------------------------------------------------------
# liveness — is the run named by the lock actually still running?
# --------------------------------------------------------------------------

#: The two words that can only mean "a test run" in this repo. Matched against
#: process command lines, so the wrapping shell of a piped run counts too.
_TEST_PROCESS = re.compile(r"\b(pytest|testgate)\b")

#: The hook's OWN invocation, matched by its path. Deliberately not a bare
#: `"test_guard" in line`: that also matched `pytest tools/tests/
#: test_test_guard.py`, i.e. it made a real run of these very tests invisible
#: to the probe — caught by `test_the_probe_actually_works_on_this_machine`.
_GUARD_ITSELF = re.compile(r"hooks[/\\]test_guard\.py")


def _looks_like_a_test_process(line: str) -> bool:
    """Does this process command line belong to a test run?

    Excludes the guard's own invocation: the hook fires on every Bash call and
    must never mistake itself for the run it is deciding about.
    """
    if _GUARD_ITSELF.search(line):
        return False
    return bool(_TEST_PROCESS.search(line))


def _probe_command_lines():
    """Command lines of the processes that could be a test run, or None.

    None means "could not tell" and is treated as "still running" by every
    caller — an inconclusive probe must never dissolve the concurrency guard.

    Bytes, never `text=True`: the cp1252 lesson from `_git_bytes` applies to
    any output that might carry a path this locale cannot represent.

    An EMPTY result is inconclusive, not "nothing is running". On Windows the
    filter matches `py`/`python`, and this guard is itself running under one,
    so a working probe always returns at least its own line. Zero lines means
    the probe broke, not that the machine is idle.
    """
    try:
        if os.name == "nt":
            script = ("Get-CimInstance Win32_Process -Filter \"Name LIKE 'py%'\""
                      " | ForEach-Object { $_.CommandLine }")
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 script], capture_output=True, timeout=20)
        else:
            out = subprocess.run(["ps", "-eo", "args="],
                                 capture_output=True, timeout=20)
        if out.returncode != 0:
            return None
        text = (out.stdout or b"").decode("utf-8", "replace")
        lines = [line for line in text.splitlines() if line.strip()]
        return lines or None
    except Exception:
        return None


def _lock_is_dead(lock: dict):
    """True (release it), False (a run really is going), or None (unknown).

    The lock is hung at PreToolUse and taken down at PostToolUse. When a tool
    call dies inside the harness, PostToolUse never fires and the lock outlives
    its run — which happened twice in one hour on 2026-08-13 and cost an agent
    a proposed `rm` of the lock file the first time and an escalation to the
    user the second. The 20-minute timer did its job both times; nobody was
    willing to wait for it, because the deny message offered two faster exits
    and no expiry time.

    So the block is now conditional on evidence rather than on the clock: if no
    process on this machine looks like a test run, the lock is released here
    and the run proceeds. The timer stays as the backstop for the case this
    cannot decide.

    `TESTGUARD_PROBE=dead|alive|unknown` overrides the probe. It exists for the
    guard's own tests, which necessarily run *under pytest* and would otherwise
    always observe a live test process.
    """
    override = os.environ.get("TESTGUARD_PROBE")
    if override:
        return {"dead": True, "alive": False}.get(override.strip().lower())
    lines = _probe_command_lines()
    if lines is None:
        return None
    return not any(_looks_like_a_test_process(line) for line in lines)


def pre(payload: dict) -> int:
    command = (payload.get("tool_input") or {}).get("command") or ""
    kind = classify(command)
    if kind == "none":
        return 0

    _state().mkdir(parents=True, exist_ok=True)
    role = _role(payload)

    # -- guard 1: role ----------------------------------------------------
    if role == "sub" and kind in ("full", "tier", "affected"):
        return _deny(
            f"DENIED by test_guard: you are a SUBAGENT and this is a "
            f"'{kind}' test run.\n"
            "Your row of the role table (root CLAUDE.md, §\"Test Suite "
            "Policy\") allows exactly:\n"
            "    py tools/smoke.py\n"
            "    py -m pytest tools/tests/test_<file>.py -q   # files YOUR diff touched\n"
            "The single full run belongs to the main session, once, after your "
            "work lands.\n"
            "Name the test files for what you changed and run those instead.")

    # -- guard 3: concurrency (checked before we record anything) ----------
    lock = _read_json(_lock_path())
    if lock:
        started = float(lock.get("started", 0))
        age = time.time() - started
        if 0 <= age < LOCK_STALE_SECONDS:
            dead = _lock_is_dead(lock)
            if dead:
                # Its run is gone; the lock is a leftover, not a conflict.
                try:
                    _lock_path().unlink()
                except OSError:
                    pass
                lock = {}
            else:
                expires = time.strftime(
                    "%H:%M:%S", time.localtime(started + LOCK_STALE_SECONDS))
                unknown = (
                    "\nThe liveness check could not run this time, so this "
                    "block is on the timer alone.\nIf you have independently "
                    "confirmed no test process exists, re-run with "
                    "TESTGUARD_OFF=1."
                ) if dead is None else ""
                return _deny(
                    "DENIED by test_guard: a test run is already in flight "
                    f"({int(age)}s ago):\n    {lock.get('target', '?')}\n"
                    "Two concurrent runs exhaust memory and make both slower — "
                    "which then reads as a flaky suite.\n"
                    f"\nWAIT. This clears itself at {expires} "
                    f"({int(LOCK_STALE_SECONDS - age)}s from now) with no "
                    "action from you, and the\nguard releases a CRASHED run "
                    "automatically — so if you are reading this, a run really "
                    "is\nalive. Do other work and come back to it.\n"
                    "Do not delete the lock file. Do not raise this with the "
                    "user as a test-policy question:\nit is not one. The full "
                    "gate is not being refused, only queued."
                    + unknown)

    # -- guard 2: repeat --------------------------------------------------
    target = normalised_target(command)
    fingerprint = tree_fingerprint()
    key = hashlib.sha256(f"{target}\n{fingerprint}".encode()).hexdigest()[:32]
    record = _read_json(_state() / f"run-{key}.json")
    if record:
        age = time.time() - float(record.get("finished", 0))
        if 0 <= age < REPEAT_TTL_SECONDS:
            outcome = record.get("outcome") or "(outcome not captured)"
            return _deny(
                "DENIED by test_guard: you already ran this exact target and "
                "NOTHING has changed since.\n"
                f"    target: {target}\n"
                f"    ran:    {int(age)}s ago\n"
                f"    result: {outcome}\n"
                "The working tree is byte-identical to that run, so the result "
                "cannot be different.\n"
                "Re-running to 'make sure' is the loop this guard exists to "
                "stop. Act on the result above:\n"
                "  * it passed  -> move on, or run a DIFFERENT target\n"
                "  * it failed  -> fix the code first; editing anything clears "
                "this automatically\n"
                "If you genuinely must repeat it, re-run with TESTGUARD_OFF=1.")

    # Allowed. Take the lock so a second run cannot start alongside it, and
    # stash the key so PostToolUse can record the outcome against it.
    _lock_path().write_text(json.dumps({
        "started": time.time(), "target": target, "key": key,
        "kind": kind, "role": role,
    }), encoding="utf-8")
    return 0


_VERDICT = re.compile(
    r"^(?:GATE (?:PASS|FAIL|ABORT).*|.*\d+ (?:passed|failed).*)$", re.MULTILINE)


def post(payload: dict) -> int:
    """Release the lock and remember what the run said."""
    command = (payload.get("tool_input") or {}).get("command") or ""
    if classify(command) == "none":
        return 0

    lock = _read_json(_lock_path())
    try:
        _lock_path().unlink()
    except OSError:
        pass

    key = lock.get("key")
    if not key:
        return 0

    response = payload.get("tool_response")
    if isinstance(response, dict):
        text = str(response.get("stdout") or response.get("output") or "")
    else:
        text = str(response or "")
    hits = _VERDICT.findall(text)
    outcome = hits[-1].strip()[:200] if hits else "(no verdict line captured)"

    (_state() / f"run-{key}.json").write_text(json.dumps({
        "finished": time.time(),
        "target": lock.get("target"),
        "outcome": outcome,
    }), encoding="utf-8")
    return 0


def main() -> int:
    if os.environ.get("TESTGUARD_OFF"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    try:
        if event in ("SessionStart", "SubagentStart"):
            return mark_role(payload)
        if event == "PreToolUse":
            return pre(payload)
        if event == "PostToolUse":
            return post(payload)
    except Exception as exc:            # never wedge a session over a guard
        print(f"test_guard: {exc}", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
