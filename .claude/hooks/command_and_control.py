#!/usr/bin/env python
"""Command and Control Structure (C2) — enforcement half.

This hook is the *forcing* half of the repo's Command and Control Structure
(the readable half is the "Command and Control Structure (C2)" section in the
root CLAUDE.md). Grep "command and control" to find the whole system.

Fires on:
  PreToolUse (Agent) -> inspect tool_input.subagent_type and DENY the agent
                        types the mandated workflow forbids, redirecting to the
                        right ones.

The mandated workflow:
  - explore with `scout` only (never `Explore` / `general-purpose`),
  - the main session writes the plan itself (never a delegated `Plan` agent),
  - execute with `coder` / `engine-coder` / `phase-executor` opening the
    matching skill, then review with `reviewer`.

Emits the PreToolUse decision contract on stdout when it denies:
    {"hookSpecificOutput": {"hookEventName": "PreToolUse",
      "permissionDecision": "deny", "permissionDecisionReason": ...}}

Never fails the session: any error, malformed input, or WORKFLOW_HOOK_OFF being
set degrades to "allow" (no output, exit 0).
"""

from __future__ import annotations

import json
import os
import sys

# Agent types the C2 workflow replaces. Matched case-insensitively.
DENIED = {"explore", "plan", "general-purpose"}

REASON = (
    "BLOCKED by the Command and Control Structure (C2). '{name}' is not an "
    "allowed agent for this workflow. Instead:\n"
    "  - Exploration -> spawn `scout` (never Explore / general-purpose).\n"
    "  - Planning    -> the main session writes the plan itself (no `Plan` agent).\n"
    "  - Execution   -> `coder` / `engine-coder` / `phase-executor`, opening the "
    "matching skill (/add-building, /add-enemy, ...).\n"
    "  - Review      -> `reviewer`.\n"
    "Re-issue the Agent call with one of those. See the 'Command and Control "
    "Structure (C2)' section in CLAUDE.md; set WORKFLOW_HOOK_OFF=1 to bypass."
)


def deny(name: str) -> None:
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REASON.format(name=name),
            }
        },
        sys.stdout,
    )


def main() -> int:
    if os.environ.get("WORKFLOW_HOOK_OFF"):
        return 0  # user bypass — allow everything

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # can't parse -> don't block

    tool_input = payload.get("tool_input") or {}
    subagent = tool_input.get("subagent_type")
    if isinstance(subagent, str) and subagent.strip().lower() in DENIED:
        deny(subagent)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # never break the session over enforcement
        print(f"command_and_control hook: {exc}", file=sys.stderr)
        raise SystemExit(0)
