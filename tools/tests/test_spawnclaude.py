"""Phase 8 / AD-2 / AD-3 acceptance tests: spawnclaude pure builders + dispatch
modes + the launcher and the generic form dialog (ED-60/61/62, T-1; AD-2 D5/D6;
AD-3).

Same headless conventions as the other editor tests (offscreen Qt + SDL dummy
before any Qt import; one QApplication per process). The pure builders are
tested directly; every dispatch is exercised with an injected fake launcher, so
NO real terminal is ever spawned. Handoffs are written into a throwaway temp
repo, never the real `.claude/dispatch/`. The `/start-domain` path is gone from
spawnclaude (D6) — no lock reads, no domain radios.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import jsonschema

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QLineEdit,
    QPlainTextEdit,
)

from editor import agent_forms, spawnclaude
from editor.agent_form_dialog import AgentFormDialog
from editor.panels.balancing import (
    _NoWheelComboBox,
    _NoWheelDoubleSpinBox,
    _NoWheelSpinBox,
)
from engine import data_io
from tools.tests.test_agent_forms import valid_spec
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]
FORM_SCHEMA = REPO / "data" / "schemas" / "agent_form.schema.json"

_APP = QApplication.instance() or QApplication(sys.argv)


def full_spec(**over):
    """A spec exercising all six field types (asserted schema-valid below)."""
    spec = {
        "schema_version": 1,
        "id": "add-enemy",
        "title": "Add New Enemy",
        "description": "Adds an enemy.",
        "skill": "add-enemy",
        "context": ["game/enemies/CLAUDE.md"],
        "git_default": "branch",
        "slug_field": "name",
        "fields": [
            {"key": "name", "label": "Enemy name", "type": "string",
             "required": True, "placeholder": "Siege Cannon",
             "description": "Display name; drives the branch slug."},
            {"key": "notes", "label": "Notes", "type": "text",
             "description": "Anything else."},
            {"key": "targets_buildings", "label": "Targets buildings",
             "type": "boolean", "default": True,
             "description": "Siege-style targeting."},
            {"key": "era_count", "label": "Era variants", "type": "integer",
             "minimum": 1, "maximum": 8, "default": 4,
             "description": "How many era slots."},
            {"key": "speed", "label": "Speed", "type": "number",
             "minimum": 0.5, "maximum": 4.0, "default": 1.5,
             "description": "Tiles per second."},
            {"key": "registry_group", "label": "Registry group", "type": "enum",
             "options": ["Walker", "Raider", "Boss"], "default": "Raider",
             "description": "REGISTRY_GROUP the variants roll from."},
        ],
    }
    spec.update(over)
    return spec


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
        """main.py passes data_dir= — AD-3 uses it for load_form_specs."""
        dialog = spawnclaude.SpawnClaudeDialog(data_dir=REPO / "data")
        self.assertTrue(dialog._tweak_radio.isChecked())


# -- AD-3: launcher + generic form dialog -----------------------------------

class FormCase(TempDataCase):
    """A temp data/ copy (real schemas + the committed add-enemy spec) plus a
    throwaway repo the handoffs land in, plus a fake launcher — so no test
    writes into the real repo and no test opens a terminal."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.calls = []

        def fake_detach(program, arguments, working_dir):
            self.calls.append((program, list(arguments), str(working_dir)))
            return True

        self.detach = fake_detach

    def launcher(self):
        return spawnclaude.SpawnClaudeDialog(
            data_dir=self.data_dir, repo=self.repo, detach=self.detach)

    def form(self, spec):
        return AgentFormDialog(spec, data_dir=self.data_dir, repo=self.repo,
                               detach=self.detach)

    def handoffs(self):
        return sorted((self.repo / ".claude" / "dispatch").glob("*.json"))

    def payload(self):
        paths = self.handoffs()
        self.assertEqual(len(paths), 1)
        # Re-validate from disk: "the file exists" is not the assertion.
        return data_io.load_validated(
            paths[0], self.data_dir / "schemas" / "dispatch_handoff.schema.json")


class TestLauncher(FormCase):
    def test_synthetic_full_spec_is_schema_valid(self):
        """Guards the fixture: if the form schema moves, this test moves first."""
        jsonschema.validate(
            full_spec(), json.loads(FORM_SCHEMA.read_text(encoding="utf-8")))

    def test_roster_is_one_entry_per_spec_plus_tweak_and_admin(self):
        dialog = self.launcher()
        specs = agent_forms.load_form_specs(self.data_dir)
        self.assertTrue(specs)
        self.assertEqual(sorted(dialog._form_buttons),
                         sorted(spec["id"] for spec in specs))
        labels = [b.text() for b in dialog._form_buttons.values()]
        self.assertIn("Add New Enemy", labels)
        self.assertIsInstance(dialog._tweak_edit, QLineEdit)
        self.assertTrue(dialog._tweak_radio.isChecked())
        self.assertFalse(dialog._admin_radio.isChecked())

    def test_a_new_spec_shows_up_on_the_next_open_no_restart(self):
        """AD-5's premise: specs are loaded FRESH per open."""
        self.assertNotIn("add-thing", self.launcher()._form_buttons)
        spec = valid_spec("add-thing", title="Add New Thing", skill="add-building")
        (self.data_dir / "agent_forms" / "add-thing.json").write_text(
            data_io.dumps_deterministic(spec), encoding="utf-8")
        dialog = self.launcher()  # same data_dir, no module reload
        self.assertIn("add-thing", dialog._form_buttons)
        self.assertEqual(dialog._form_buttons["add-thing"].text(), "Add New Thing")

    def test_admin_and_tweak_write_no_handoff(self):
        """D5: the prompt-only modes bypass dispatch entirely."""
        admin = self.launcher()
        admin._admin_radio.setChecked(True)
        admin._on_dispatch()
        self.assertEqual(self.calls[-1][1][-1], "claude")

        tweak = self.launcher()
        tweak._tweak_edit.setText("nudge the base")
        tweak._on_dispatch()
        self.assertEqual(self.calls[-1][1][-1], "/smalltweak nudge the base")

        self.assertEqual(self.handoffs(), [])


class TestFormDialogWidgets(FormCase):
    def test_one_widget_per_field_type(self):
        dialog = self.form(full_spec())
        self.assertIsInstance(dialog._widgets["name"], QLineEdit)
        self.assertIsInstance(dialog._widgets["notes"], QPlainTextEdit)
        self.assertIsInstance(dialog._widgets["targets_buildings"], QCheckBox)
        self.assertIsInstance(dialog._widgets["era_count"], _NoWheelSpinBox)
        self.assertIsInstance(dialog._widgets["speed"], _NoWheelDoubleSpinBox)
        self.assertIsInstance(dialog._widgets["registry_group"], _NoWheelComboBox)

    def test_spinbox_ranges_come_from_the_spec(self):
        """ED-30: out-of-range input is unrepresentable, not merely rejected."""
        dialog = self.form(full_spec())
        era = dialog._widgets["era_count"]
        self.assertEqual((era.minimum(), era.maximum()), (1, 8))
        speed = dialog._widgets["speed"]
        self.assertAlmostEqual(speed.minimum(), 0.5)
        self.assertAlmostEqual(speed.maximum(), 4.0)
        era.setValue(99)  # clamped by the widget itself
        self.assertEqual(era.value(), 8)

    def test_every_widget_is_tooltipped_with_its_description(self):
        spec = full_spec()
        dialog = self.form(spec)
        for field in spec["fields"]:
            self.assertEqual(dialog._widgets[field["key"]].toolTip(),
                             field["description"])

    def test_enum_combo_lists_exactly_the_options(self):
        dialog = self.form(full_spec())  # keep the dialog alive: Qt owns the combo
        combo = dialog._widgets["registry_group"]
        self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                         ["Walker", "Raider", "Boss"])

    def test_defaults_are_seeded(self):
        dialog = self.form(full_spec())
        values = dialog.values()
        self.assertEqual(values["targets_buildings"], True)
        self.assertEqual(values["era_count"], 4)
        self.assertAlmostEqual(values["speed"], 1.5)
        self.assertEqual(values["registry_group"], "Raider")
        self.assertNotIn("name", values)  # empty strings are omitted, not ""

    def test_free_text_box_is_built_in_not_a_spec_field(self):
        spec = valid_spec()  # its only field is a `string`
        self.assertFalse(any(f["type"] == "text" for f in spec["fields"]))
        dialog = self.form(spec)
        self.assertIsInstance(dialog._free_text, QPlainTextEdit)

    def test_unknown_type_raises_naming_the_field(self):
        spec = full_spec(fields=[{"key": "x", "label": "X", "type": "colour",
                                  "description": "?"}])
        with self.assertRaises(ValueError) as caught:
            self.form(spec)
        self.assertIn("x", str(caught.exception))

    def test_unknown_schema_version_is_rejected_loudly(self):
        with self.assertRaises(ValueError) as caught:
            self.form(full_spec(schema_version=2))
        self.assertIn("schema_version", str(caught.exception))


class TestFormDialogGating(FormCase):
    def test_required_field_gates_dispatch(self):
        dialog = self.form(full_spec())
        self.assertFalse(dialog._dispatch_button.isEnabled())
        self.assertIn("Enemy name", dialog._hint.text())
        dialog._widgets["name"].setText("Siege Cannon")
        self.assertTrue(dialog._dispatch_button.isEnabled())
        dialog._widgets["name"].clear()
        self.assertFalse(dialog._dispatch_button.isEnabled())

    def test_a_required_field_with_a_default_opens_dispatchable(self):
        spec = full_spec()
        spec["fields"][0]["default"] = "Siege Cannon"
        dialog = self.form(spec)
        self.assertTrue(dialog._dispatch_button.isEnabled())

    def test_a_spec_with_no_required_fields_opens_dispatchable(self):
        spec = full_spec()
        spec["fields"][0].pop("required")
        dialog = self.form(spec)
        self.assertTrue(dialog._dispatch_button.isEnabled())


class TestFormDialogGit(FormCase):
    def test_branch_default_checks_the_branch_radio_and_enables_the_edit(self):
        dialog = self.form(full_spec(git_default="branch"))
        self.assertTrue(dialog._branch_radio.isChecked())
        self.assertTrue(dialog._branch_edit.isEnabled())
        self.assertEqual(dialog.git_mode(), "branch")

    def test_current_default_checks_current_and_disables_the_branch_edit(self):
        dialog = self.form(full_spec(git_default="current"))
        self.assertTrue(dialog._current_radio.isChecked())
        self.assertFalse(dialog._branch_edit.isEnabled())
        self.assertEqual(dialog.git_mode(), "current")

    def test_toggling_the_radio_re_enables_the_branch_edit(self):
        dialog = self.form(full_spec(git_default="current"))
        dialog._branch_radio.setChecked(True)
        self.assertTrue(dialog._branch_edit.isEnabled())

    def test_branch_name_live_slugs_from_the_slug_field(self):
        dialog = self.form(full_spec())
        dialog._widgets["name"].setText("Siege Cannon")
        # AD-1 stays the single source of slug truth.
        self.assertEqual(
            dialog.branch_name(),
            agent_forms.default_branch_name(
                full_spec(), dialog.values(), dialog.free_text()))
        self.assertIn("siege-cannon", dialog.branch_name())

    def test_free_text_is_the_fallback_slug_source(self):
        dialog = self.form(full_spec())
        dialog._free_text.setPlainText("A battering ram")
        self.assertEqual(
            dialog.branch_name(),
            agent_forms.default_branch_name(full_spec(), {}, "A battering ram"))

    def test_a_user_edited_branch_name_is_never_clobbered(self):
        dialog = self.form(full_spec())
        dialog._widgets["name"].setText("Siege Cannon")
        dialog._branch_edit.clear()
        QTest.keyClicks(dialog._branch_edit, "agent/my-own-branch")  # textEdited
        dialog._widgets["name"].setText("Battering Ram")
        self.assertEqual(dialog.branch_name(), "agent/my-own-branch")


class TestFormDialogDispatch(FormCase):
    def test_accept_writes_a_valid_handoff_and_spawns_no_terminal(self):
        dialog = self.form(full_spec())
        dialog._widgets["name"].setText("Siege Cannon")
        dialog._free_text.setPlainText("A slow siege unit.")
        branch = dialog.branch_name()
        dialog._on_dispatch()

        payload = self.payload()
        self.assertEqual(payload["form_id"], "add-enemy")
        self.assertEqual(payload["skill"], "add-enemy")
        self.assertEqual(payload["free_text"], "A slow siege unit.")
        self.assertEqual(payload["values"]["name"], "Siege Cannon")
        self.assertEqual(payload["values"]["era_count"], 4)
        self.assertEqual(payload["git"],
                         {"mode": "branch", "base": "Development", "branch": branch})
        self.assertEqual(dialog.result(), QDialog.Accepted)

        self.assertEqual(len(self.calls), 1)  # the fake is the ONLY launcher
        program, arguments, _wd = self.calls[0]
        self.assertEqual(program, "wt")
        relpath = arguments[-1].split(" ", 1)[1]
        self.assertEqual(arguments[-1], f"/dispatch {relpath}")
        self.assertFalse(Path(relpath).is_absolute())
        self.assertNotIn("\\", relpath)  # repo-relative POSIX
        self.assertTrue(relpath.startswith(".claude/dispatch/"))

    def test_current_mode_omits_the_branch(self):
        dialog = self.form(full_spec(git_default="current"))
        dialog._widgets["name"].setText("Siege Cannon")
        dialog._on_dispatch()
        self.assertEqual(self.payload()["git"],
                         {"mode": "current", "base": "Development"})

    def test_an_edited_branch_name_reaches_the_handoff(self):
        dialog = self.form(full_spec())
        dialog._widgets["name"].setText("Siege Cannon")
        dialog._branch_edit.clear()
        QTest.keyClicks(dialog._branch_edit, "agent/hand-named")
        dialog._on_dispatch()
        self.assertEqual(self.payload()["git"]["branch"], "agent/hand-named")


if __name__ == "__main__":
    unittest.main()
