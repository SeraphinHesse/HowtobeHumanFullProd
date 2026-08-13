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
    """`TESTGUARD_PROBE` pins the liveness answer.

    Without it these tests are undecidable: they run *under pytest*, so the
    real probe correctly reports a live test process no matter which scenario
    is being set up.
    """

    ALIVE = {"TESTGUARD_PROBE": "alive"}
    DEAD = {"TESTGUARD_PROBE": "dead"}
    UNKNOWN = {"TESTGUARD_PROBE": "unknown"}

    def test_a_second_run_while_one_is_in_flight_is_denied(self):
        self.start("S-MAIN", subagent=False)
        self.assertEqual(self.pre(TARGETED, extra_env=self.ALIVE)[0], 0)
        code, message = self.pre(OTHER_TARGET, extra_env=self.ALIVE)
        self.assertEqual(code, 2)
        self.assertIn("in flight", message)

    def test_the_lock_releases_when_the_run_finishes(self):
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED, extra_env=self.ALIVE)
        self.post(TARGETED, "49 passed")
        self.assertEqual(self.pre(OTHER_TARGET, extra_env=self.ALIVE)[0], 0)

    def test_a_lock_left_by_a_CRASHED_run_does_not_block(self):
        """The 2026-08-13 incident: a tool call died inside the harness, so
        PostToolUse never fired and its lock blocked the gate for 20 minutes
        while nothing at all was running."""
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED, extra_env=self.ALIVE)            # takes the lock
        # ...that run dies. No PostToolUse. Lock still on disk:
        self.assertTrue((self.state / "inflight.json").exists())

        self.assertEqual(self.pre(OTHER_TARGET, extra_env=self.DEAD)[0], 0)

    def test_an_inconclusive_probe_still_blocks(self):
        """Unknown must mean 'assume it is running'. A probe that fails open
        would dissolve the concurrency guard on every machine it cannot read."""
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED, extra_env=self.ALIVE)
        code, message = self.pre(OTHER_TARGET, extra_env=self.UNKNOWN)
        self.assertEqual(code, 2)
        # ...but THEN it must name the override, because the timer is now the
        # only thing that will clear it.
        self.assertIn("TESTGUARD_OFF=1", message)

    def test_the_denial_says_wait_and_not_delete_the_lock(self):
        """The message is half the mechanism. The old one ended with 'delete
        <path> or re-run with TESTGUARD_OFF=1' and gave no expiry time, so an
        agent 2.5 minutes from the timer reached for `rm` instead of waiting."""
        self.start("S-MAIN", subagent=False)
        self.pre(TARGETED, extra_env=self.ALIVE)
        code, message = self.pre(OTHER_TARGET, extra_env=self.ALIVE)
        self.assertEqual(code, 2)
        self.assertIn("WAIT", message)
        self.assertNotIn("inflight.json", message)
        self.assertNotIn("TESTGUARD_OFF", message)


class TestLivenessProbe(unittest.TestCase):
    """The probe reads process command lines — pin what counts as a test run."""

    def setUp(self):
        sys.path.insert(0, str(REPO / ".claude" / "hooks"))
        self.addCleanup(lambda: sys.path.remove(str(REPO / ".claude" / "hooks")))
        import importlib
        self.guard = importlib.import_module("test_guard")

    def test_what_counts_as_a_live_test_run(self):
        cases = {
            "py -m pytest tools/tests/test_boss.py -q": True,
            "C:\\Python311\\python.exe tools/testgate.py check": True,
            "bash -c cd /repo && py tools/testgate.py check | tail -15": True,
            # A run of the guard's OWN tests is still a run. The first version
            # excluded any line containing "test_guard" and so made this one
            # invisible.
            "py -m pytest tools/tests/test_test_guard.py -q": True,
            # The guard fires on every Bash call, so it is always running
            # alongside itself and must never count as the run it is judging.
            "py C:/repo/.claude/hooks/test_guard.py": False,
            "py editor/main.py": False,
            "py game/main.py --backend=gpu": False,
            "py tools/smoke.py": False,
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                self.assertEqual(
                    self.guard._looks_like_a_test_process(line), expected)

    def test_the_probe_actually_works_on_this_machine(self):
        """The probe is platform code; a silently broken one degrades the guard
        back to the 20-minute timer without anyone noticing.

        This test IS a live test process, so the probe must both return lines
        and recognise one of them."""
        lines = self.guard._probe_command_lines()
        self.assertIsNotNone(lines, "the process probe returned nothing here")
        self.assertTrue(
            any(self.guard._looks_like_a_test_process(line) for line in lines),
            "the probe cannot see the pytest process running this very test")

    def test_an_empty_process_list_is_inconclusive_not_idle(self):
        """A working probe always sees at least this guard's own python, so
        zero lines means the probe broke — never 'the machine is idle'."""
        original = self.guard.subprocess
        self.addCleanup(lambda: setattr(self.guard, "subprocess", original))

        class _Empty:
            returncode = 0
            stdout = b"   \n\n"

        class _FakeModule:
            run = staticmethod(lambda *a, **k: _Empty())

        # Rebind the NAME in the guard's namespace — never patch `run` on the
        # stdlib module, which the rest of this suite is also using.
        self.guard.subprocess = _FakeModule()
        self.assertIsNone(self.guard._probe_command_lines())
        self.assertIsNone(self.guard._lock_is_dead({}))

    def test_the_env_override_pins_all_three_answers(self):
        import os
        for value, expected in (("dead", True), ("alive", False),
                                ("unknown", None)):
            with self.subTest(value=value):
                os.environ["TESTGUARD_PROBE"] = value
                self.addCleanup(os.environ.pop, "TESTGUARD_PROBE", None)
                self.assertIs(self.guard._lock_is_dead({}), expected)


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


class TestLedgerIsOneOwner(GuardCase):
    """`tools/testguard_ledger.py` owns the key; the hook has no second copy.

    Two copies of the key logic drift and the failure is SILENT — records land
    under a key nothing looks up and the repeat guard just stops denying
    (TestRunner plan, D3). So assert the hook and a direct call agree, and that
    a record written by the module is one the hook reads back.
    """

    def test_the_hook_and_a_direct_run_key_call_agree(self):
        from tools.testguard_ledger import run_key

        self.start("S-MAIN", subagent=False)
        self.assertEqual(self.pre(TARGETED)[0], 0)
        self.post(TARGETED, "49 passed")

        # Nothing was written to the tree between those two calls, so the
        # fingerprint — and therefore the key — cannot have moved.
        record = self.state / f"run-{run_key(TARGETED)}.json"
        self.assertTrue(record.exists(),
                        "the hook filed its record under a different key")
        self.assertIn("49 passed",
                      json.loads(record.read_text(encoding="utf-8"))["outcome"])

    def test_record_run_writes_what_the_repeat_guard_reads(self):
        """The round-trip TR-6's editor relies on — no real test run involved."""
        from tools.testguard_ledger import record_run

        self.start("S-MAIN", subagent=False)
        record_run(self.state, TARGETED, "GATE PASS (0 failures)")

        code, message = self.pre(TARGETED)
        self.assertEqual(code, 2)
        self.assertIn("GATE PASS (0 failures)", message)


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


class TestEditorSourcedCredit(GuardCase):
    """TR-6: a full run started from the EDITOR is this tree's gate.

    No test here launches anything: the ledger state is written directly by
    `tools.testguard_ledger.record_run` — the same call the editor makes — and
    the hook is driven as a subprocess, exactly as every other case above.

    The thing being protected is the WORDING. An agent told "you already ran
    this exact target" about a run it has no memory of concludes the guard is
    broken and reaches for the override, which is the one outcome the credit
    mechanism cannot survive.
    """

    OUTCOME = "GATE PASS  2251 passed, 0 failed"

    def record_editor_run(self, outcome=None):
        from tools.testguard_ledger import record_run
        return record_run(self.state, FULL, outcome or self.OUTCOME,
                          source="editor")

    def test_an_editor_run_denies_the_main_sessions_gate(self):
        self.start("S-MAIN", subagent=False)
        self.record_editor_run()

        code, message = self.pre(FULL)
        self.assertEqual(code, 2)
        self.assertIn(self.OUTCOME, message)

    def test_the_denial_names_the_editor_and_never_claims_the_agent_ran_it(self):
        self.start("S-MAIN", subagent=False)
        self.record_editor_run()

        code, message = self.pre(FULL)
        self.assertEqual(code, 2)
        self.assertIn("from the editor", message)
        self.assertNotIn("you already ran this exact target", message)

    def test_editing_the_tree_clears_editor_credit_too(self):
        """Credit is keyed on the tree, not on who ran it."""
        self.start("S-MAIN", subagent=False)
        self.record_editor_run()

        scratch = REPO / "tools" / "tests" / "_tr6_credit_scratch.py"
        scratch.write_text("# transient probe file\n", encoding="utf-8")
        self.addCleanup(lambda: scratch.exists() and scratch.unlink())
        self.assertEqual(self.pre(FULL)[0], 0)

    def test_a_record_with_no_source_keeps_todays_wording(self):
        """The regression pin: pre-TR-6 records carry no `source` key, and an
        agent's OWN repeat must still be told it ran the thing itself."""
        from tools.testguard_ledger import run_key
        import time as _time

        self.start("S-MAIN", subagent=False)
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / f"run-{run_key(FULL)}.json").write_text(json.dumps({
            "finished": _time.time(), "target": FULL, "outcome": "49 passed",
        }), encoding="utf-8")

        code, message = self.pre(FULL)
        self.assertEqual(code, 2)
        self.assertIn("you already ran this exact target", message)
        self.assertNotIn("from the editor", message)


if __name__ == "__main__":
    unittest.main()
