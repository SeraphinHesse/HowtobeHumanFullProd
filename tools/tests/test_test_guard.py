"""`.claude/hooks/test_guard.py` — the hook that ENFORCES the test policy.

The policy in root `CLAUDE.md` §"Test Suite Policy" was prose for months and
prose lost every time: subagents ran the full suite because the router they are
handed verbatim also said "Universal exit gate", and agents re-ran an unchanged
selection ten times over. This hook is the mechanical half, so the rules are
denied rather than merely discouraged.

Driven the way Claude Code drives it — as a subprocess fed the hook JSON on
stdin, asserting the exit-code contract (0 allows, **2 blocks and shows stderr
to the model**). Every test points the guard at a scratch state directory via
`TESTGUARD_STATE_DIR`, because the guard fires on every Bash call *including
the one running this suite*, and a test must never disturb the live session's
lock or repeat ledger.

The one rule these tests exist to protect above all others: **a guard that
errors must ALLOW.** A hook that can wedge a session is worse than no hook, so
`main()` swallows everything — which is exactly why two of its guards once sat
silently dead (a `WinError 183` on a worktree checkout, then a `cp1252` decode
blowing up inside subprocess's reader thread). Both were invisible until a test
asserted the DENY actually happens.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "test_guard.py"

TARGETED = "py -m pytest tools/tests/test_boss.py -q"
OTHER_TARGET = "py -m pytest tools/tests/test_enemies.py -q"
FULL = "py tools/testgate.py check"


class GuardCase(unittest.TestCase):
    """A fresh scratch state dir per test — no shared ledger, no ordering."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "testguard"

    def run_hook(self, payload, extra_env=None):
        """Feed `payload` to the hook; return (returncode, stderr)."""
        import os
        env = dict(os.environ)
        env.pop("TESTGUARD_OFF", None)
        env["TESTGUARD_STATE_DIR"] = str(self.state)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload),
            capture_output=True, text=True, env=env)
        return result.returncode, result.stderr

    def start(self, session_id, subagent):
        return self.run_hook({
            "hook_event_name": "SubagentStart" if subagent else "SessionStart",
            "session_id": session_id})

    def pre(self, command, session_id="S-MAIN", extra_env=None):
        return self.run_hook({
            "hook_event_name": "PreToolUse", "session_id": session_id,
            "tool_name": "Bash", "tool_input": {"command": command}},
            extra_env)

    def post(self, command, stdout, session_id="S-MAIN"):
        return self.run_hook({
            "hook_event_name": "PostToolUse", "session_id": session_id,
            "tool_name": "Bash", "tool_input": {"command": command},
            "tool_response": {"stdout": stdout}})


class TestFastPath(GuardCase):
    """Anything that is not a test command costs one regex and is allowed."""

    def test_non_test_commands_are_allowed(self):
        self.start("S-MAIN", subagent=False)
        for command in ("git status", "ls -la", "py tools/smoke.py",
                        "py editor/main.py", "py tools/export_ui_layouts.py"):
            with self.subTest(command=command):
                self.assertEqual(self.pre(command)[0], 0)


class TestRoleGuard(GuardCase):
    """A subagent gets its row of the table; the main session keeps the gate."""

    def test_subagent_is_denied_every_wide_run(self):
        self.start("S-MAIN", subagent=False)
        self.start("S-SUB", subagent=True)
        for command in (FULL,
                        "py tools/testgate.py check --affected",
                        "py -m pytest -m core",
                        "py -m pytest -m editor",
                        "py -m unittest discover -s tools/tests -t ."):
            with self.subTest(command=command):
                code, message = self.pre(command, "S-SUB")
                self.assertEqual(code, 2)
                # The denial has to say what to do INSTEAD, or the agent just
                # retries a variant of the same thing.
                self.assertIn("pytest tools/tests/test_", message)

    def test_subagent_may_run_the_files_it_touched(self):
        self.start("S-SUB", subagent=True)
        self.assertEqual(self.pre(TARGETED, "S-SUB")[0], 0)

    def test_main_session_keeps_the_full_gate(self):
        """The role guard must never block the one run the policy is built on."""
        self.start("S-MAIN", subagent=False)
        self.assertEqual(self.pre(FULL)[0], 0)

    def test_an_unknown_session_fails_OPEN(self):
        """No marker (a resumed session, a runtime that shares session ids)
        must not be treated as a subagent — see `_role`'s docstring."""
        self.assertEqual(self.pre(FULL, "S-NEVER-STARTED")[0], 0)


class TestRepeatGuard(GuardCase):
    """The loop-killer: same target + unchanged tree = denied."""

    def test_identical_repeat_on_an_unchanged_tree_is_denied(self):
        self.start("S-MAIN", subagent=False)
        self.assertEqual(self.pre(TARGETED)[0], 0)
        self.post(TARGETED, "49 passed, 34 subtests passed in 1.15s")

        code, message = self.pre(TARGETED)
        self.assertEqual(code, 2)
        # It must hand back the result it already has, or the agent has no way
        # to act on the denial.
        self.assertIn("49 passed", message)

    def test_a_different_target_is_still_allowed(self):
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED)
        self.post(TARGETED, "49 passed")
        self.assertEqual(self.pre(OTHER_TARGET)[0], 0)

    def test_reporting_flags_do_not_make_it_a_new_run(self):
        """`-q` vs `-v`, a different `-n`, `--tb=` — same tests, same result."""
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED)
        self.post(TARGETED, "49 passed")
        variant = "py -m pytest tools/tests/test_boss.py -v --tb=short -n0"
        self.assertEqual(self.pre(variant)[0], 2)

    def test_editing_the_tree_clears_the_denial(self):
        """The fingerprint is diff CONTENT, not `git status` — otherwise a real
        fix would still read as 'unchanged' and the re-run proving it would be
        denied."""
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED)
        self.post(TARGETED, "1 failed, 48 passed")

        scratch = REPO / "tools" / "tests" / "_test_guard_scratch.py"
        scratch.write_text("# transient probe file\n", encoding="utf-8")
        self.addCleanup(lambda: scratch.exists() and scratch.unlink())
        self.assertEqual(self.pre(TARGETED)[0], 0)


class TestConcurrencyGuard(GuardCase):
    def test_a_second_run_while_one_is_in_flight_is_denied(self):
        self.start("S-MAIN", subagent=False)
        self.assertEqual(self.pre(TARGETED)[0], 0)          # takes the lock
        code, message = self.pre(OTHER_TARGET)
        self.assertEqual(code, 2)
        self.assertIn("in flight", message)

    def test_the_lock_releases_when_the_run_finishes(self):
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED)
        self.post(TARGETED, "49 passed")
        self.assertEqual(self.pre(OTHER_TARGET)[0], 0)


class TestNeverWedgesTheSession(GuardCase):
    """A guard that can hang or hard-fail a session is worse than no guard."""

    def test_malformed_stdin_allows(self):
        result = subprocess.run([sys.executable, str(HOOK)], input="not json",
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)

    def test_the_env_escape_hatch_allows_a_denied_run(self):
        self.start("S-SUB", subagent=True)
        self.assertEqual(self.pre(FULL, "S-SUB")[0], 2)
        self.assertEqual(
            self.pre(FULL, "S-SUB", extra_env={"TESTGUARD_OFF": "1"})[0], 0)

    def test_a_missing_tool_input_allows(self):
        self.assertEqual(self.run_hook(
            {"hook_event_name": "PreToolUse", "session_id": "S-MAIN"})[0], 0)


class TestClassification(unittest.TestCase):
    """`classify` is the whole policy surface — pin it directly."""

    def setUp(self):
        sys.path.insert(0, str(REPO / ".claude" / "hooks"))
        self.addCleanup(lambda: sys.path.remove(str(REPO / ".claude" / "hooks")))
        import importlib
        self.guard = importlib.import_module("test_guard")

    def test_every_spelling_lands_in_the_right_bucket(self):
        cases = {
            "py tools/testgate.py check": "full",
            "py tools/testgate.py snapshot": "full",
            "py -m unittest discover -s tools/tests -t .": "full",
            "py -m pytest": "full",
            "py tools/testgate.py check --affected": "affected",
            "py -m pytest -m core": "tier",
            "py -m pytest -m editor -q": "tier",
            "py -m pytest tools/tests/test_boss.py": "targeted",
            "py -m pytest -m core tools/tests/test_boss.py": "targeted",
            "git status": "none",
            "py tools/smoke.py": "none",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.guard.classify(command), expected)


class TestThePolicyIsStatedOnce(unittest.TestCase):
    """The prose half: no doc may contradict the role table.

    The looping this whole rework exists to stop was not caused by agents
    ignoring instructions — it was caused by them FOLLOWING one of several
    contradictory ones. The root router said "subagents never run the full
    suite" and, ~200 lines later, "Step 2 — **Universal** exit gate" with a
    bare `py tools/testgate.py check` under it; three package docs and half the
    command files each carried their own copy. Fixing the copies once is worth
    little if the next doc edit re-adds one, so the invariant is asserted.
    """

    #: Every spelling of "run much more than the files you touched".
    WIDE = ("tools/testgate.py check", "unittest discover",
            "pytest -m core", "pytest -m editor", "pytest -m meta")

    def test_no_subagent_prompt_prescribes_a_wide_run(self):
        """`.claude/agents/*.md` are ALL subagent prompts, by definition."""
        for path in sorted((REPO / ".claude" / "agents").glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for needle in self.WIDE:
                with self.subTest(agent=path.name, command=needle):
                    self.assertNotIn(
                        needle, text,
                        f"{path.name} tells a SUBAGENT to run '{needle}'. "
                        "Subagents run smoke + the test files they touched; "
                        "see the role table in the root CLAUDE.md.")

    def test_package_docs_qualify_every_full_gate_mention(self):
        """A package doc may NAME the full gate, but only as the main
        session's — never as a command the reader should run."""
        for package in ("engine", "game", "editor", "data"):
            path = REPO / package / "CLAUDE.md"
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "tools/testgate.py check" not in line:
                    continue
                window = "\n".join(lines[max(0, index - 4):index + 5])
                with self.subTest(doc=f"{package}/CLAUDE.md", line=index + 1):
                    self.assertIn(
                        "MAIN SESSION", window,
                        f"{package}/CLAUDE.md:{index + 1} names the full gate "
                        "without saying it is the MAIN SESSION's. An agent "
                        "editing in this package reads that as an instruction.")

    def test_the_root_router_states_the_role_table(self):
        router = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        for row in ("Subagent", "Main session, mid-task",
                    "Main session, at handoff"):
            with self.subTest(row=row):
                self.assertIn(row, router)

    def test_step_2_carries_no_copy_pasteable_full_suite_command(self):
        """The specific defect: a runnable full-suite line under a heading a
        subagent reads as addressed to it.

        HEADINGS only — the section deliberately QUOTES the old "Universal exit
        gate" wording while explaining why it was removed, and a substring
        search over the whole file cannot tell the explanation from the
        offence."""
        router = (REPO / "CLAUDE.md").read_text(encoding="utf-8")

        headings = [ln for ln in router.splitlines() if ln.startswith("#")]
        offenders = [h for h in headings if "Universal" in h]
        self.assertEqual(
            offenders, [],
            "a heading still calls the exit gate 'universal'; subagents read "
            "that as addressed to them")

        start = router.index("## Step 2")
        end = router.index("\n## ", start + 1)
        step_2 = router[start:end]
        runnable = [ln for ln in step_2.splitlines()
                    if ln.strip() == "py tools/testgate.py check"]
        self.assertEqual(
            runnable, [],
            "Step 2 carries a bare, copy-pasteable full-suite command; it must "
            "point at the role table instead")

    def test_no_live_doc_teaches_the_pre_pytest_incantation(self):
        """`unittest discover` runs everything and is not the gate. Historical
        records under `docs/briefs/` and `planning/` are exempt: they are what
        was true then, and each carries a SUPERSEDED banner.

        `.claude/worktrees/` is exempt too — a worktree is a full checkout of
        ANOTHER branch, so this sweep would otherwise assert that every branch
        anyone has open already carries this branch's doc fixes. It cannot:
        the offending briefs there are history on branches that predate the
        fix. Scoping to the current checkout is the whole point of the test."""
        offenders = []
        for root in ("engine", "game", "editor", "data", "tools", ".claude"):
            for path in (REPO / root).rglob("*.md"):
                if "worktrees" in path.relative_to(REPO).parts:
                    continue
                if "unittest discover" in path.read_text(encoding="utf-8"):
                    offenders.append(path.relative_to(REPO).as_posix())
        self.assertEqual(offenders, [], "live docs still teach `unittest discover`")


if __name__ == "__main__":
    unittest.main()
