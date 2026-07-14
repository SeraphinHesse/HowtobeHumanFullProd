"""Phase 8 / AD-2 acceptance tests: spawnclaude pure builders + dispatch modes
(ED-60/61/62, T-1; AD-2 D5/D6).

Same headless conventions as the other editor tests (offscreen Qt + SDL dummy
before any Qt import; one QApplication per process). The pure builders are
tested directly; dispatch() is exercised with an injected fake launcher so no
real terminal is spawned. The `/start-domain` path is gone from spawnclaude
(D6) — no lock reads, no domain radios, so these tests need no temp data dir.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtWidgets import QApplication

from editor import spawnclaude

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


class TestSpawnCommand(unittest.TestCase):
    def test_wt_argv_shape(self):
        argv = spawnclaude.spawn_command("hello", repo=r"C:\repo")
        self.assertEqual(
            argv, ["wt", "-d", r"C:\repo", "cmd", "/k", "claude", "hello"])

    def test_prompt_is_a_single_argv_element(self):
        prompt = "/dispatch .claude/dispatch/x.json"
        argv = spawnclaude.spawn_command(prompt, repo=r"C:\repo")
        self.assertEqual(argv[-1], prompt)  # spaces stay in one element

    def test_no_prompt_launches_blank_claude(self):
        # admin mode: no trailing prompt, claude is the last element
        argv = spawnclaude.spawn_command(None, repo=r"C:\repo")
        self.assertEqual(
            argv, ["wt", "-d", r"C:\repo", "cmd", "/k", "claude"])
        self.assertEqual(spawnclaude.spawn_command("", repo=r"C:\repo")[-1],
                         "claude")

    def test_repo_defaults_to_module_repo(self):
        argv = spawnclaude.spawn_command("x")
        self.assertEqual(Path(argv[2]), spawnclaude.REPO)

    def test_wt_program_is_first(self):
        argv = spawnclaude.spawn_command("x")
        self.assertEqual(argv[0], "wt")


class TestPrompts(unittest.TestCase):
    def test_dispatch_prompt_is_the_literal_slash_command(self):
        relpath = ".claude/dispatch/20260713-140322-add-enemy.json"
        self.assertEqual(spawnclaude.dispatch_prompt(relpath),
                         f"/dispatch {relpath}")

    def test_dispatch_prompt_survives_spawn_command_as_one_argv_element(self):
        relpath = ".claude/dispatch/20260713-140322-add-enemy.json"
        prompt = spawnclaude.dispatch_prompt(relpath)
        argv = spawnclaude.spawn_command(prompt, repo=r"C:\repo")
        self.assertEqual(argv[-1], prompt)
        self.assertEqual(len(argv), 7)  # prompt is ONE element, not split

    def test_small_tweak_prompt_with_text(self):
        text = spawnclaude.small_tweak_prompt("nudge the base 1 tile")
        self.assertEqual(text, "/smalltweak nudge the base 1 tile")

    def test_small_tweak_prompt_blank(self):
        self.assertEqual(spawnclaude.small_tweak_prompt(""), "/smalltweak")


class TestDispatch(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def fake_detach(program, arguments, working_dir):
            self.calls.append((program, list(arguments), str(working_dir)))
            return True

        self.fake_detach = fake_detach

    def test_dispatch_handoff_uses_injected_launcher(self):
        relpath = ".claude/dispatch/20260713-140322-add-enemy.json"
        ok = spawnclaude.dispatch(handoff=relpath, repo=REPO,
                                  detach=self.fake_detach)
        self.assertTrue(ok)
        self.assertEqual(len(self.calls), 1)
        program, arguments, _wd = self.calls[0]
        self.assertEqual(program, "wt")
        self.assertEqual(arguments[-1], f"/dispatch {relpath}")

    def test_dispatch_small_tweak_loads_the_skill_directly(self):
        spawnclaude.dispatch(tweak_prompt="tiny fix", repo=REPO,
                             detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "/smalltweak tiny fix")

    def test_dispatch_admin_launches_blank_claude(self):
        spawnclaude.dispatch(admin=True, repo=REPO, detach=self.fake_detach)
        arguments = self.calls[0][1]
        # blank session: claude is the last arg, no slash command appended
        self.assertEqual(arguments[-1], "claude")
        self.assertNotIn("/dispatch", " ".join(arguments))
        self.assertNotIn("/smalltweak", " ".join(arguments))

    def test_admin_beats_handoff_and_tweak(self):
        """Precedence (D5): admin > handoff > small tweak."""
        spawnclaude.dispatch(handoff=".claude/dispatch/x.json",
                             tweak_prompt="tiny fix", admin=True,
                             repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "claude")

    def test_handoff_beats_tweak(self):
        spawnclaude.dispatch(handoff=".claude/dispatch/x.json",
                             tweak_prompt="tiny fix",
                             repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "/dispatch .claude/dispatch/x.json")


class TestNoLockWriteAPI(unittest.TestCase):
    def test_spawnclaude_exposes_no_lock_writer(self):
        """ED-61/62/T-1: spawnclaude exposes no way to set, clear, or
        force-unlock a domain lock. It no longer reads locks either (AD-2 D6 —
        the protocol is suspended); this guard keeps it that way."""
        for name in dir(spawnclaude):
            lowered = name.lower()
            self.assertNotIn("unlock", lowered)
            self.assertNotIn("set_lock", lowered)
            self.assertNotIn("release", lowered)


class TestDialog(unittest.TestCase):
    def test_admin_mode_dispatches_blank(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        dialog = spawnclaude.SpawnClaudeDialog(detach=fake_detach)
        dialog._admin_radio.setChecked(True)
        dialog._on_dispatch()
        self.assertEqual(captured["args"][-1], "claude")

    def test_small_tweak_is_the_default_mode(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        dialog = spawnclaude.SpawnClaudeDialog(detach=fake_detach)
        self.assertTrue(dialog._tweak_radio.isChecked())
        dialog._tweak_edit.setText("nudge the base")
        dialog._on_dispatch()
        self.assertEqual(captured["args"][-1], "/smalltweak nudge the base")

    def test_dialog_still_accepts_data_dir_kwarg(self):
        """main.py:534 passes data_dir= (AD-3 rewires it); accepted-and-unused."""
        dialog = spawnclaude.SpawnClaudeDialog(data_dir=REPO / "data")
        self.assertTrue(dialog._tweak_radio.isChecked())


if __name__ == "__main__":
    unittest.main()
