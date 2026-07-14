"""The orientation hook forces every agent through the code graph, and hands
subagents the root CLAUDE.md they do not receive automatically.

Driven the way Claude Code drives it — as a subprocess fed the hook JSON on
stdin — asserting the SessionStart / SubagentStart contract:

  SessionStart  -> graph directive only (root CLAUDE.md already auto-loads).
  SubagentStart -> graph directive + root CLAUDE.md verbatim.

Both must emit hookSpecificOutput.additionalContext and exit 0; a hook that
crashes or blocks would break every session in the repo.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "orient.py"
CLAUDE_MD = REPO / "CLAUDE.md"


def run_hook(event, extra=None):
    """Feed a hook payload to orient.py; return (returncode, parsed_stdout)."""
    payload = {"hook_event_name": event}
    payload.update(extra or {})
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
    )
    doc = json.loads(result.stdout) if result.stdout.strip() else {}
    return result.returncode, doc


def context_of(doc):
    return doc.get("hookSpecificOutput", {}).get("additionalContext", "")


class OrientHookCase(unittest.TestCase):

    def test_session_start_emits_graph_directive(self):
        code, doc = run_hook("SessionStart", {"source": "startup"})
        self.assertEqual(code, 0)
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "SessionStart")
        context = context_of(doc)
        self.assertIn("Do NOT open with Grep/Glob", context)
        self.assertIn("graphify explain", context)
        self.assertIn("Graph status:", context)

    def test_session_start_does_not_duplicate_claude_md(self):
        """The main session auto-loads CLAUDE.md; re-injecting it wastes context."""
        _, doc = run_hook("SessionStart", {"source": "startup"})
        self.assertNotIn("Design pillars", context_of(doc))

    def test_subagent_start_injects_claude_md_verbatim(self):
        code, doc = run_hook("SubagentStart", {"agent_type": "Explore"})
        self.assertEqual(code, 0)
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "SubagentStart")
        context = context_of(doc)

        # The graph directive still leads.
        self.assertIn("Do NOT open with Grep/Glob", context)

        # And the whole router follows — VERBATIM, which is the entire claim of
        # this test and is strictly stronger than spot-checking section titles.
        #
        # There used to be a hardcoded list of headings asserted here as well.
        # It was redundant (the verbatim check already covers every heading) and
        # it rotted: it named "TEMPORARY OVERRIDE", a banner the lock-removal
        # work deliberately deleted from the router — so the test went red for
        # documenting the past rather than checking the hook. Assert the file,
        # not a copy of its table of contents.
        router = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertIn(router, context)

    def test_graph_directive_precedes_the_router(self):
        """Step 0 must be read before the package-doc routing in Step 1."""
        _, doc = run_hook("SubagentStart", {"agent_type": "general-purpose"})
        context = context_of(doc)
        self.assertLess(context.index("Step 0"), context.index("Design pillars"))

    def test_malformed_stdin_does_not_break_the_session(self):
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not json", capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("additionalContext", result.stdout)


if __name__ == "__main__":
    unittest.main()
