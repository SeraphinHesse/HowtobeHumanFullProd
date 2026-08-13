"""The ONE owner of the key that identifies a test run.

The ledger key — `sha256(normalised target + working-tree fingerprint)` — says
"this exact selection has already been run against this exact tree". Both the
`test_guard` hook (`.claude/hooks/test_guard.py`) and the editor's test runner
import it from here, and neither keeps a copy: two copies of this logic drift
apart the moment either side changes a normalisation rule or a hash input, and
the failure is SILENT — records get filed under a key nothing ever looks up, so
the repeat guard simply stops denying and nobody notices (TestRunner plan, D3,
`planning/TestRunnerPLAN.md:76-80`).

Pure stdlib: no Qt, no pygame, and nothing under `.claude/`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]   # tools/ -> repo root

_STATE_CACHE: list = []


def state_dir() -> Path:
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


# --------------------------------------------------------------------------
# command classification
# --------------------------------------------------------------------------


def normalised_target(command: str) -> str:
    """The command reduced to what it actually RUNS, for fingerprinting.

    Strips leading environment assignments (`QT_QPA_PLATFORM=offscreen ...`),
    collapses whitespace, and drops flags that change reporting but not which
    tests execute — so `-q` vs `-v`, or a different `-n`, is correctly treated
    as the same run rather than as a fresh one.

    It is **idempotent**: normalising an already-normalised target returns
    it unchanged, which is what lets `run_key` accept either a raw command
    or a target.
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
# the key, and the ledger record it names
# --------------------------------------------------------------------------


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


def record_run(state_dir, target, outcome, source="agent", key=None) -> Path:
    """Write the ledger record the repeat guard reads back. Returns the Path.

    `state_dir` is the DIRECTORY (a Path), not this module's `state_dir()`
    function — callers pass `state_dir()` themselves. Never call the module
    function from inside this body; the parameter shadows it.

    `key=None` computes the key from `target` against the CURRENT tree. The
    hook passes the key it stashed at PreToolUse instead, so a tree edited
    mid-run cannot move the record out from under the guard that reads it.
    """
    key = key or run_key(target)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"run-{key}.json"
    path.write_text(json.dumps({
        "finished": time.time(),
        "target": target,
        "outcome": outcome,
        "source": source,
    }), encoding="utf-8")
    return path
