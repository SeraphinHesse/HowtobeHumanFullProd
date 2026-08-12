#!/usr/bin/env python
"""Orientation hook: force every agent through CLAUDE.md + the code graph first.

Fires on:
  SessionStart  -> inject the graph orientation (main session already auto-loads
                   the root CLAUDE.md, so we do not duplicate it there).
  SubagentStart -> inject the root CLAUDE.md *verbatim* plus the graph
                   orientation. Subagents start cold and do not reliably receive
                   the project instructions, which is how they end up grepping
                   the codebase blind.

Emits the hook JSON contract on stdout:
    {"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}

Never fails the session: any error degrades to "no extra context".
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE_MD = REPO / "CLAUDE.md"
GRAPH_JSON = REPO / "graphify-out" / "graph.json"

# Source trees whose churn would make the graph stale.
SOURCE_DIRS = ("engine", "game", "editor", "tools")


def graph_status() -> str:
    """One line on whether graphify-out/ exists and still matches the code."""
    if not GRAPH_JSON.exists():
        return (
            "MISSING — no graph on disk. Rebuild before searching:\n"
            "    graphify extract . --code-only && graphify cluster-only . --no-label"
        )

    built = GRAPH_JSON.stat().st_mtime
    newest = 0.0
    newest_name = ""
    for folder in SOURCE_DIRS:
        for py in (REPO / folder).rglob("*.py"):
            mtime = py.stat().st_mtime
            if mtime > newest:
                newest, newest_name = mtime, py.relative_to(REPO).as_posix()

    age = time.strftime("%Y-%m-%d %H:%M", time.localtime(built))
    if newest > built:
        return (
            f"STALE — graph built {age}, but {newest_name} is newer. The git "
            "post-commit hook only re-extracts committed changes, so uncommitted "
            "edits are not in the graph yet. Trust the files over the graph for "
            "anything you have just touched."
        )
    return f"fresh (built {age}, newer than every .py in {'/'.join(SOURCE_DIRS)})."


GRAPH_BLOCK = """\
# Step 0 — Orient with the code graph BEFORE you search the filesystem

This repo ships a prebuilt Graphify knowledge graph of every symbol in `engine/`,
`game/`, `editor/`, `tools/` (~5k nodes / ~10k edges, built from tree-sitter ASTs
— no LLM, no embeddings). It is the intended *first* move for any "where does X
live", "what calls X", or "what breaks if I change X" question.

Do NOT open with Grep/Glob to locate code. Ask the graph:

    graphify explain "place_building()"     # a symbol's neighbours, in/out edges
    graphify path "BaseBuilding" "TileMap"  # how two symbols connect
    graphify affected "BaseBuilding"        # blast radius before you change a thing
    graphify query "how is balancing json loaded?" --budget 800

Then read the actual files it points you at.

Rules:
- The graph LOCATES code; it is a map, not the source of truth. `data/` JSON and
  the package CLAUDE.md docs still win. Edges tagged INFERRED are guesses,
  EXTRACTED are literal.
- Never run `graphify update` by hand and never hand-edit or commit `graphify-out/`
  — a git post-commit hook rebuilds it on every commit, in a detached process.
- Grep/Glob remain fine for non-locating work: literal string sweeps, config
  values, checking whether a name exists at all.

Graph status: {status}
"""

STEP_1_MAIN = """\

After Step 0, do Step 1 from CLAUDE.md: classify the task and read the ONE package
doc that matches it.
"""

STEP_1_SUBAGENT = """\

After Step 0, do Step 1 from the router below: classify the task and read the ONE
package doc that matches it.
"""

# Appended AFTER the router, deliberately: later text wins, and the router is
# injected verbatim precisely so it cannot drift from the file on disk. This is
# the ONE place the subagent's row of the role table is restated, and it exists
# because a subagent reading the router top-to-bottom meets ~200 lines of
# general policy before anything says "...but not you". Keeping the reminder
# LAST is cheaper and more robust than maintaining a second copy of the router.
SUBAGENT_TEST_ROLE = """\

---

# YOUR ROW OF THE TEST POLICY (read this last; it overrides anything above)

You are a SUBAGENT. The router above is the project's general policy, written
for everyone. Where it shows an exit gate, **your row of the table in
§"Test Suite Policy" is what applies to you**, and it is narrow:

    py tools/smoke.py                            # always
    py -m pytest tools/tests/test_<file>.py -q   # the files YOUR diff touches

You may NOT run:
  * the full suite (`py tools/testgate.py check`)
  * `--affected` (its safety pass is the whole core tier — the main session's
    call, not yours)
  * any tier sweep: `-m core`, `-m editor`, `-m meta`
  * `py -m unittest discover ...` (the pre-pytest incantation; it runs
    everything and is not the gate)

Three further rules, all mechanically enforced by the `test_guard.py`
`PreToolUse` hook — you will be DENIED, not warned:
  1. Run each target ONCE. If you have edited nothing since, the result cannot
     have changed. Re-running "to be sure" is the loop this repo exists to stop.
  2. Never start a test run while another is in flight.
  3. The single full run belongs to the MAIN SESSION, once, after your work
     lands.

If a red test is inside your blast radius, fix it. If it is clearly outside,
report it and STOP — do not go looking, and do not widen your test command to
find out more.
"""


def build_context(event: str) -> str:
    graph = GRAPH_BLOCK.format(status=graph_status())

    if event != "SubagentStart":
        # Main session: the root CLAUDE.md is already auto-loaded as project
        # instructions. Only the graph directive is missing.
        return graph + STEP_1_MAIN

    try:
        router = CLAUDE_MD.read_text(encoding="utf-8")
    except OSError:
        return graph + STEP_1_MAIN

    return (
        graph
        + STEP_1_SUBAGENT
        + "\n---\n\n"
        + "# Project instructions (root CLAUDE.md — read this before touching code)\n\n"
        + "You are a subagent in this repo and did not receive these automatically.\n"
        + "They override your default behavior. Follow them exactly.\n\n"
        + router
        + SUBAGENT_TEST_ROLE
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    event = payload.get("hook_event_name") or payload.get("hookEventName") or "SessionStart"

    try:
        context = build_context(event)
    except Exception as exc:  # never break the session over orientation
        print(f"orient hook: {exc}", file=sys.stderr)
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": context,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
