"""editor/test_runner.py — the parser and the per-domain accumulator.

NOTHING HERE LAUNCHES A TEST RUN. Every case drives canned pytest/testgate
output through `feed_lines()` or calls `parse_line()` directly; `TestRun`'s
process launcher is injected, and one case injects a `spawn` that raises to
prove the canned path never reaches it. This is TestRunnerPLAN §4's first risk:
a test that shells out to pytest would take minutes inside the suite, trip the
concurrency guard, and could recurse.
"""
import unittest

from editor import test_runner as tr

# --- canned streams --------------------------------------------------------

GREEN = """\
============================= test session starts =============================
[gw3] [  1%] PASSED tools/tests/test_boss.py::TestBoss::test_dead_goal_repaths
[gw0] [  2%] PASSED tools/tests/test_coords.py::TestCoords::test_iso
tools/tests/test_levelup.py::TestXp::test_curve PASSED [  3%]
3 passed in 1.23s
GATE PASS  3 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips
"""

FAILING = """\
[gw3] [  1%] PASSED tools/tests/test_boss.py::TestBoss::test_a
[gw0] [  2%] FAILED tools/tests/test_boss.py::TestBoss::test_b
FAILED tools/tests/test_boss.py::TestBoss::test_b - AssertionError: 1 != 2
1 failed, 1 passed in 1.00s
GATE FAIL  1 problem(s)
  NEW FAILURE   tools/tests/test_boss.py::TestBoss::test_b
"""

SUBFAILING = """\
[gw1] [  5%] PASSED tools/tests/test_balancing_data.py::T::test_other
SUBFAILED(file="'x.json'", key="'K'") tools/tests/test_balancing_data.py::T::test_x
SUBFAILED(file="'x.json'", key="'L'") tools/tests/test_balancing_data.py::T::test_x
1 failed, 1 passed in 2.00s
"""

SKIPPING = """\
[gw1] [  5%] SKIPPED tools/tests/test_run_controls.py::T::test_b
SKIPPED [1] tools/tests/test_run_controls.py:120: a build already exists
1 skipped in 0.50s
GATE FAIL  1 problem(s)
  UNEXPECTED SKIP tools/tests/test_run_controls.py: a build already exists
"""

ANSI = (
    "\x1b[32m[gw3] [  1%] PASSED\x1b[0m tools/tests/test_boss.py::T::test_a\n"
    "\x1b[31mFAILED\x1b[0m tools/tests/test_boss.py::T::test_b - boom\n"
    "\x1b[1m1 failed, 1 passed in 1.00s\x1b[0m\n"
)

UNMAPPED = """\
[gw2] [  1%] PASSED tools/tests/test_brand_new_thing.py::T::test_a
[gw2] [  2%] FAILED tools/tests/test_brand_new_thing.py::T::test_b
1 failed, 1 passed in 1.00s
"""


def lines(text):
    return text.splitlines()


class TestBuildCommand(unittest.TestCase):
    def test_full_run_is_the_gate_in_streaming_mode(self):
        cmd = tr.build_command()
        self.assertEqual(cmd[1:], ["tools/testgate.py", "check", "--stream"])

    def test_domain_run_names_only_that_domains_files(self):
        cmd = tr.build_command("enemies")
        self.assertIn("-m", cmd)
        self.assertIn("pytest", cmd)
        self.assertIn("-v", cmd)                      # node-ids, not dots
        files = [a for a in cmd if a.endswith(".py")]
        self.assertIn("tools/tests/test_boss.py", files)
        self.assertTrue(all("/" in f and "\\" not in f for f in files))
        self.assertEqual(files, sorted(files))
        for other in ("test_coords.py", "test_editor_panels.py"):
            self.assertNotIn(f"tools/tests/{other}", files)

    def test_an_unknown_domain_raises_and_names_the_real_ones(self):
        with self.assertRaises(ValueError) as ctx:
            tr.build_command("nosuchdomain")
        self.assertIn("enemies", str(ctx.exception))

    def test_the_unknown_bucket_is_not_runnable(self):
        with self.assertRaises(ValueError):
            tr.build_command("unknown")


class TestChildEnv(unittest.TestCase):
    def test_color_off_and_unbuffered(self):
        env = tr.child_env({"FORCE_COLOR": "1", "CLICOLOR_FORCE": "1", "X": "y"})
        self.assertNotIn("FORCE_COLOR", env)
        self.assertNotIn("CLICOLOR_FORCE", env)
        self.assertEqual(env["NO_COLOR"], "1")
        self.assertEqual(env["PY_COLORS"], "0")
        self.assertEqual(env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(env["X"], "y")


class TestParseLine(unittest.TestCase):
    def test_xdist_verbose_line(self):
        ev = tr.parse_line("[gw3] [ 45%] PASSED tools/tests/test_boss.py::T::test_x")
        self.assertEqual((ev.kind, ev.outcome, ev.module, ev.domain),
                         ("test", "PASSED", "test_boss.py", "enemies"))

    def test_plain_verbose_line(self):
        ev = tr.parse_line("tools/tests/test_boss.py::T::test_x PASSED [ 45%]")
        self.assertEqual((ev.kind, ev.outcome, ev.domain), ("test", "PASSED", "enemies"))

    def test_short_report_failure_keeps_its_message(self):
        ev = tr.parse_line("FAILED tools/tests/test_boss.py::T::test_x - AssertionError: x")
        self.assertEqual(ev.kind, "failure")
        self.assertEqual(ev.message, "AssertionError: x")

    def test_subfailed_params_are_part_of_the_event(self):
        ev = tr.parse_line('SUBFAILED(key="\'A\'") tools/tests/test_boss.py::T::test_x')
        self.assertEqual(ev.outcome, "SUBFAILED")
        self.assertEqual(ev.params, '(key="\'A\'")')

    def test_short_report_skip_is_not_parsed_as_a_failure(self):
        ev = tr.parse_line("SKIPPED [1] tools/tests/test_boss.py:120: a build exists")
        self.assertEqual(ev.kind, "skip")
        self.assertEqual(ev.nodeid, "tools/tests/test_boss.py")
        self.assertEqual(ev.message, "a build exists")

    def test_tally_sums_every_count(self):
        ev = tr.parse_line("5 failed, 1170 passed, 1 skipped, 1272 subtests passed in 1s")
        self.assertEqual((ev.kind, ev.count), ("tally", 1175))

    def test_gate_lines(self):
        self.assertEqual(tr.parse_line("GATE PASS  3 ran | 0 known").outcome, "PASS")
        self.assertEqual(tr.parse_line("GATE FAIL  1 problem(s)").outcome, "FAIL")
        self.assertEqual(tr.parse_line("GATE ABORT  cannot narrow").outcome, "ABORT")

    def test_ansi_wrapped_outcome_is_still_seen(self):
        ev = tr.parse_line("\x1b[31mFAILED\x1b[0m tools/tests/test_boss.py::T::t - x")
        self.assertEqual(ev.kind, "failure")

    def test_windows_separators_are_normalised(self):
        ev = tr.parse_line(r"FAILED tools\tests\test_boss.py::T::test_x")
        self.assertEqual(ev.nodeid, "tools/tests/test_boss.py::T::test_x")

    def test_noise_is_not_an_event(self):
        for junk in ("", "....F..", "=== test session starts ===",
                     "[gw2] node down: Not properly terminated",
                     "  File \"x.py\", line 3, in f"):
            self.assertIsNone(tr.parse_line(junk), junk)

    def test_an_unknown_outcome_token_is_not_guessed_at(self):
        self.assertIsNone(
            tr.parse_line("[gw3] [ 45%] WOBBLED tools/tests/test_boss.py::T::t"))


class TestGreenRun(unittest.TestCase):
    def test_a_clean_stream_passes_and_credits_each_domain(self):
        run = tr.TestRun()
        run.feed_lines(lines(GREEN))
        res = run.finish(0)
        self.assertEqual(res.verdict, "pass")
        self.assertTrue(res.completed)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.total_ran, 3)
        self.assertEqual(res.domains["enemies"].passed, 1)
        self.assertEqual(res.domains["engine"].passed, 1)
        self.assertEqual(res.domains["buildings"].passed, 1)
        self.assertEqual(res.domains["enemies"].state, "passed")
        self.assertEqual(res.domains["ui"].state, "pending")   # nothing ran in it
        self.assertEqual(res.gate_line,
                         "GATE PASS  3 ran | 0 known | 0 new | 0 fixed | "
                         "0 unexpected skips")

    def test_every_known_domain_gets_a_row_from_the_start(self):
        run = tr.TestRun()
        res = run.finish(0)
        self.assertEqual(set(res.domains), set(tr.DOMAIN_LABELS))


class TestFailingRun(unittest.TestCase):
    def setUp(self):
        run = tr.TestRun()
        run.feed_lines(lines(FAILING))
        self.res = run.finish(1)

    def test_verdict_and_state(self):
        self.assertEqual(self.res.verdict, "fail")
        self.assertEqual(self.res.domains["enemies"].state, "failed")

    def test_the_failure_is_counted_once_across_all_three_line_shapes(self):
        # verbose FAILED + short-report FAILED + testgate's NEW FAILURE line
        self.assertEqual(len(self.res.failures), 1)
        self.assertEqual(self.res.domains["enemies"].failed, 1)
        self.assertEqual(self.res.domains["enemies"].passed, 1)
        self.assertEqual(self.res.domains["enemies"].done, 2)

    def test_the_short_message_survives_deduplication(self):
        self.assertEqual(self.res.failures[0].message, "AssertionError: 1 != 2")

    def test_flat_failures_are_the_union_of_the_domains(self):
        per_domain = [f for d in self.res.domains.values() for f in d.failures]
        self.assertEqual(sorted(f.nodeid for f in per_domain),
                         sorted(f.nodeid for f in self.res.failures))


class TestSubtestFailures(unittest.TestCase):
    def test_two_subtests_of_one_test_are_two_failures(self):
        run = tr.TestRun()
        run.feed_lines(lines(SUBFAILING))
        res = run.finish(1)
        self.assertEqual(res.verdict, "fail")
        self.assertEqual(res.domains["data"].subfailed, 2)
        self.assertEqual({f.kind for f in res.failures}, {"subfailed"})
        self.assertEqual(len({f.params for f in res.failures}), 2)


class TestSkips(unittest.TestCase):
    def test_an_unexpected_skip_fails_its_domain(self):
        run = tr.TestRun()
        run.feed_lines(lines(SKIPPING))
        res = run.finish(1)
        self.assertEqual(res.verdict, "fail")
        self.assertEqual(res.domains["editor"].state, "failed")
        self.assertEqual(res.domains["editor"].skipped, 1)
        self.assertEqual([f.kind for f in res.failures], ["unexpected_skip"])
        self.assertEqual(res.failures[0].message, "a build already exists")


class TestAnsiStream(unittest.TestCase):
    def test_a_coloured_stream_parses_exactly_like_a_plain_one(self):
        run = tr.TestRun()
        run.feed_lines(ANSI.splitlines())
        res = run.finish(1)
        self.assertEqual(res.verdict, "fail")
        self.assertEqual(res.domains["enemies"].failed, 1)
        self.assertEqual(res.domains["enemies"].passed, 1)


class TestUnknownModules(unittest.TestCase):
    def test_a_module_in_no_domain_surfaces_rather_than_vanishing(self):
        run = tr.TestRun()
        run.feed_lines(lines(UNMAPPED))
        res = run.finish(1)
        self.assertEqual(res.unknown_modules, ("test_brand_new_thing.py",))
        self.assertEqual(res.domains["unknown"].done, 2)
        self.assertEqual(res.domains["unknown"].state, "failed")

    def test_the_unknown_row_is_absent_on_a_healthy_run(self):
        run = tr.TestRun()
        run.feed_lines(lines(GREEN))
        self.assertNotIn("unknown", run.finish(0).domains)


class TestInterleavedWorkers(unittest.TestCase):
    """--dist loadfile means files finish out of order and interleave.

    Identity comes from the node-id in each line, never from stream position.
    """

    INTERLEAVED = [
        "[gw3] [  1%] PASSED tools/tests/test_boss.py::T::test_a",
        "[gw0] [  2%] PASSED tools/tests/test_coords.py::T::test_a",
        "[gw3] [  3%] FAILED tools/tests/test_editor_panels.py::T::test_a",
        "[gw0] [  4%] PASSED tools/tests/test_coords.py::T::test_b",
        "[gw3] [  5%] PASSED tools/tests/test_boss.py::T::test_b",
    ]

    def counts(self, stream):
        run = tr.TestRun()
        run.feed_lines(stream)
        res = run.finish(1)
        return {k: (d.passed, d.failed, d.done)
                for k, d in res.domains.items() if d.done}

    def test_order_does_not_change_a_single_count(self):
        self.assertEqual(self.counts(self.INTERLEAVED),
                         self.counts(sorted(self.INTERLEAVED)))

    def test_each_line_lands_in_its_own_node_ids_domain(self):
        self.assertEqual(self.counts(self.INTERLEAVED), {
            "enemies": (2, 0, 2), "engine": (2, 0, 2), "editor": (0, 1, 1)})


class TestProgressCallbacks(unittest.TestCase):
    def test_progress_counts_up_with_no_total(self):
        seen = []
        run = tr.TestRun(on_progress=lambda *a: seen.append(a))
        run.feed_lines([
            "[gw3] [  1%] PASSED tools/tests/test_boss.py::T::test_a",
            "[gw0] [  2%] FAILED tools/tests/test_editor_panels.py::T::test_b",
            "[gw3] [  3%] PASSED tools/tests/test_boss.py::T::test_c",
        ])
        self.assertEqual(seen, [
            ("enemies", 1, None, "running"),
            ("editor", 1, None, "failed"),
            ("enemies", 2, None, "running"),
        ])

    def test_on_finished_receives_the_result(self):
        got = []
        run = tr.TestRun(on_finished=got.append)
        res = run.finish(0)
        self.assertIs(got[0], res)

    def test_a_domain_rerun_learns_its_total_from_the_tally(self):
        seen = []
        run = tr.TestRun(domain="enemies", on_progress=lambda *a: seen.append(a))
        run.feed_lines(["[gw0] [ 50%] PASSED tools/tests/test_boss.py::T::test_a",
                        "2 passed in 1.0s"])
        self.assertEqual(seen[-1], ("enemies", 1, 2, "running"))


class TestNoFabricatedGateLine(unittest.TestCase):
    def test_a_raw_pytest_stream_yields_no_gate_line(self):
        run = tr.TestRun()
        run.feed_lines(lines(SUBFAILING))
        res = run.finish(1)
        self.assertIsNone(res.gate_line)
        self.assertEqual(res.verdict, "fail")     # derived from the counters

    def test_a_domain_rerun_is_never_a_gate(self):
        run = tr.TestRun(domain="enemies")
        run.feed_lines(lines(GREEN))              # even carrying a GATE PASS
        res = run.finish(0)
        self.assertIsNone(res.gate_line)
        self.assertEqual(res.domain, "enemies")

    def test_a_gate_fail_with_no_parsed_failure_still_fails(self):
        run = tr.TestRun()
        run.feed_lines(["1 passed in 1.0s", "GATE FAIL  1 problem(s)"])
        self.assertEqual(run.finish(1).verdict, "fail")


class TestCancellation(unittest.TestCase):
    def test_a_cancelled_run_is_not_completed_and_keeps_what_it_parsed(self):
        run = tr.TestRun()
        run.feed_lines(lines(GREEN)[:2])
        res = run.finish(None, cancelled=True)
        self.assertEqual(res.verdict, "cancelled")
        self.assertFalse(res.completed)
        self.assertEqual(res.domains["enemies"].done, 1)

    def test_an_unparsed_crash_is_an_error_not_a_pass(self):
        run = tr.TestRun()
        res = run.finish(3)
        self.assertEqual(res.verdict, "error")
        self.assertFalse(res.completed)


class TestNothingSpawns(unittest.TestCase):
    """The one rule of this phase's tests (TestRunnerPLAN §4)."""

    def test_the_canned_path_never_reaches_the_launcher(self):
        def explode(*a, **kw):
            raise AssertionError("a test tried to launch a real test run")

        run = tr.TestRun(spawn=explode)
        run.feed_lines(lines(GREEN))
        self.assertEqual(run.finish(0).verdict, "pass")


class TestRawTail(unittest.TestCase):
    def test_raw_lines_are_kept_for_the_report(self):
        run = tr.TestRun()
        run.feed_lines(["Traceback (most recent call last):", "  boom"])
        self.assertEqual(run.finish(1).raw_tail,
                         ("Traceback (most recent call last):", "  boom"))

    def test_the_tail_is_bounded(self):
        run = tr.TestRun()
        run.feed_lines(f"noise {i}" for i in range(tr.RAW_TAIL + 50))
        self.assertEqual(len(run.finish(0).raw_tail), tr.RAW_TAIL)


if __name__ == "__main__":
    unittest.main()
