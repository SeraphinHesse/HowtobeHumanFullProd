"""Phase 8 acceptance tests: spawnclaude pure builders + lock-read greying
(ED-60/61/62).

Same headless conventions as the other editor tests (offscreen Qt + SDL dummy
before any Qt import; one QApplication per process). The pure builders are
tested directly; dispatch() is exercised with an injected fake launcher so no
real terminal is spawned. Locked-domain greying runs against a tempfile copy of
data/ (never mutates the repo).
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtWidgets import QApplication

from editor import locks, spawnclaude
from tools.tests.test_editor_panels import TempDataCase, lock_domain

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


class TestSpawnCommand(unittest.TestCase):
    def test_wt_argv_shape(self):
        argv = spawnclaude.spawn_command("hello", repo=r"C:\repo")
        self.assertEqual(
            argv, ["wt", "-d", r"C:\repo", "cmd", "/k", "claude", "hello"])

    def test_prompt_is_a_single_argv_element(self):
        prompt = "/start-domain map"
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
    def test_start_domain_prompt_is_the_literal_slash_command(self):
        self.assertEqual(
            spawnclaude.start_domain_prompt("buildings"), "/start-domain buildings")

    def test_small_tweak_prompt_with_text(self):
        text = spawnclaude.small_tweak_prompt("nudge the base 1 tile")
        self.assertEqual(text, "/smalltweak nudge the base 1 tile")

    def test_small_tweak_prompt_blank(self):
        self.assertEqual(spawnclaude.small_tweak_prompt(""), "/smalltweak")


class TestDomainChoices(TempDataCase):
    def test_all_domains_unlocked_by_default(self):
        choices = spawnclaude.domain_choices(self.data_dir)
        self.assertEqual([c["domain"] for c in choices], list(locks.DOMAINS))
        self.assertTrue(all(not c["locked"] for c in choices))
        self.assertTrue(all(c["owner"] is None for c in choices))

    def test_locked_domain_carries_owner_and_since(self):
        lock_domain(self.data_dir, "enemies", "featureEnemies")
        by_name = {c["domain"]: c for c in spawnclaude.domain_choices(self.data_dir)}
        self.assertTrue(by_name["enemies"]["locked"])
        self.assertEqual(by_name["enemies"]["owner"], "featureEnemies")
        self.assertEqual(by_name["enemies"]["since"], "2026-07-03")
        self.assertFalse(by_name["buildings"]["locked"])


class TestDispatch(TempDataCase):
    def test_dispatch_domain_uses_injected_launcher(self):
        calls = []

        def fake_detach(program, arguments, working_dir):
            calls.append((program, list(arguments), str(working_dir)))
            return True

        ok = spawnclaude.dispatch(domain="map", repo=REPO, detach=fake_detach)
        self.assertTrue(ok)
        self.assertEqual(len(calls), 1)
        program, arguments, _wd = calls[0]
        self.assertEqual(program, "wt")
        self.assertEqual(arguments[-1], "/start-domain map")

    def test_dispatch_small_tweak_loads_the_skill_directly(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        spawnclaude.dispatch(tweak_prompt="tiny fix", repo=REPO, detach=fake_detach)
        self.assertEqual(captured["args"][-1], "/smalltweak tiny fix")

    def test_dispatch_admin_launches_blank_claude(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        spawnclaude.dispatch(admin=True, repo=REPO, detach=fake_detach)
        # blank session: claude is the last arg, no slash command appended
        self.assertEqual(captured["args"][-1], "claude")
        self.assertNotIn("/start-domain", " ".join(captured["args"]))
        self.assertNotIn("/smalltweak", " ".join(captured["args"]))


class TestNoLockWriteAPI(unittest.TestCase):
    def test_spawnclaude_exposes_no_lock_writer(self):
        """ED-61/62/T-1: spawnclaude reads locks but exposes no way to set,
        clear, or force-unlock one (delegation model — /start-domain writes)."""
        for name in dir(spawnclaude):
            lowered = name.lower()
            self.assertNotIn("unlock", lowered)
            self.assertNotIn("set_lock", lowered)
            self.assertNotIn("release", lowered)


class TestDialogGreying(TempDataCase):
    def test_locked_domain_button_disabled(self):
        lock_domain(self.data_dir, "core", "featureCore")
        dialog = spawnclaude.SpawnClaudeDialog(data_dir=self.data_dir)
        self.assertFalse(dialog._domain_buttons["core"].isEnabled())
        self.assertTrue(dialog._domain_buttons["buildings"].isEnabled())
        self.assertIn("locked by featureCore",
                      dialog._domain_buttons["core"].text())

    def test_default_selection_skips_locked_domain(self):
        lock_domain(self.data_dir, "buildings", "featureBuildings")
        dialog = spawnclaude.SpawnClaudeDialog(data_dir=self.data_dir)
        # buildings is first in D-10 order but locked -> enemies should be default
        self.assertEqual(dialog.selected_domain(), "enemies")

    def test_admin_mode_dispatches_blank(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        dialog = spawnclaude.SpawnClaudeDialog(
            data_dir=self.data_dir, detach=fake_detach)
        dialog._admin_radio.setChecked(True)
        self.assertIsNone(dialog.selected_domain())
        dialog._on_dispatch()
        self.assertEqual(captured["args"][-1], "claude")


if __name__ == "__main__":
    unittest.main()
