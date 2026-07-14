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
import unittest.mock
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

from editor import agent_forms, plans, spawnclaude
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
    """Always `repo=` a throwaway dir: the launcher prunes `<repo>/.claude/
    dispatch/` on open, and no test may reach into the real one — a designer's
    day-old handoff is live data."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)

    def test_admin_mode_dispatches_blank(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        dialog = spawnclaude.SpawnClaudeDialog(repo=self.repo, detach=fake_detach)
        dialog._admin_radio.setChecked(True)
        dialog._on_dispatch()
        self.assertEqual(captured["args"][-1], "claude")

    def test_small_tweak_is_the_default_mode(self):
        captured = {}

        def fake_detach(program, arguments, working_dir):
            captured["args"] = arguments
            return True

        dialog = spawnclaude.SpawnClaudeDialog(repo=self.repo, detach=fake_detach)
        self.assertTrue(dialog._tweak_radio.isChecked())
        dialog._tweak_edit.setText("nudge the base")
        dialog._on_dispatch()
        self.assertEqual(captured["args"][-1], "/smalltweak nudge the base")

    def test_dialog_still_accepts_data_dir_kwarg(self):
        """main.py passes data_dir= — AD-3 uses it for load_form_specs."""
        dialog = spawnclaude.SpawnClaudeDialog(data_dir=REPO / "data",
                                               repo=self.repo)
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
        # The expectation comes from DISK — the handoff that was actually
        # written — not from the argv under test, or a hardcoded path in
        # _on_dispatch would satisfy its own assertion.
        expected = agent_forms.handoff_relpath(self.handoffs()[0], self.repo)
        self.assertEqual(arguments[-1], f"/dispatch {expected}")
        self.assertFalse(Path(expected).is_absolute())
        self.assertNotIn("\\", expected)  # repo-relative POSIX
        self.assertTrue(expected.startswith(".claude/dispatch/"))

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


# -- AD-7: plan management (pure helpers + the launcher's Plans group) -------

MARKER = "<!-- active-plan: MIGRATION_PLAN.md | set: 2026-07-13 -->\n"


class TempRepoCase(unittest.TestCase):
    """A throwaway repo with a `planning/` dir and a root `PLAN.md` — the real
    repo's PLAN.md is live data and no test may write it."""

    PLANS = ["AlphaPLAN.md", "BetaPLAN.md"]

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.planning = self.repo / "planning"
        self.planning.mkdir()
        for name in self.PLANS:
            (self.planning / name).write_text("# plan\n", encoding="utf-8")
        (self.planning / "notes.pdf").write_bytes(b"%PDF-")  # non-.md: excluded
        self.write_mirror(f"<!-- active-plan: {self.PLANS[0]} | set: 2026-07-13 -->\n")

    def write_mirror(self, text):
        (self.repo / "PLAN.md").write_text(text, encoding="utf-8")


class TestPlansPure(TempRepoCase):
    def test_active_plan_parses_the_line_1_marker(self):
        self.assertEqual(plans.active_plan(self.repo), "AlphaPLAN.md")

    def test_active_plan_is_none_when_plan_md_is_missing(self):
        (self.repo / "PLAN.md").unlink()
        self.assertIsNone(plans.active_plan(self.repo))  # and raises nothing

    def test_active_plan_is_none_on_an_empty_plan_md(self):
        self.write_mirror("")
        self.assertIsNone(plans.active_plan(self.repo))

    def test_active_plan_is_none_when_a_hand_edit_stripped_the_marker(self):
        self.write_mirror("# Some plan\n\n<!-- active-plan: AlphaPLAN.md -->\n")
        # Line 1 only — the marker is pinned there by /setcurrentplan step 4.
        self.assertIsNone(plans.active_plan(self.repo))

    def test_the_real_repo_mirror_names_a_real_plan(self):
        """The live contract: root PLAN.md's marker must name a planning/ doc."""
        active = plans.active_plan(REPO)
        self.assertIsNotNone(active)
        self.assertIn(active, plans.list_plans(REPO))

    def test_list_plans_is_sorted_md_names_only(self):
        self.assertEqual(plans.list_plans(self.repo), sorted(self.PLANS))

    def test_list_plans_is_empty_when_planning_is_missing(self):
        empty = self.repo / "nothing-here"
        empty.mkdir()
        self.assertEqual(plans.list_plans(empty), [])

    def test_reveal_command_branches_per_platform(self):
        path = self.planning
        with unittest.mock.patch.object(plans.sys, "platform", "win32"):
            self.assertEqual(plans.reveal_command(path), ["explorer", str(path)])
        with unittest.mock.patch.object(plans.sys, "platform", "darwin"):
            self.assertEqual(plans.reveal_command(path), ["open", str(path)])
        with unittest.mock.patch.object(plans.sys, "platform", "linux"):
            self.assertEqual(plans.reveal_command(path), ["xdg-open", str(path)])

    def test_planning_dir_hangs_off_the_repo(self):
        self.assertEqual(plans.planning_dir(self.repo), self.repo / "planning")
        self.assertEqual(plans.plan_mirror_path(self.repo), self.repo / "PLAN.md")

    def test_prompts_are_the_literal_slash_commands(self):
        self.assertEqual(plans.set_current_plan_prompt("MIGRATION_PLAN.md"),
                         "/setcurrentplan MIGRATION_PLAN.md")
        self.assertEqual(plans.create_plan_prompt("AudioPLAN — port audio"),
                         "/createplan AudioPLAN — port audio")
        self.assertEqual(plans.create_plan_prompt(""), "/createplan")
        self.assertEqual(plans.create_plan_prompt(None), "/createplan")


class TestDispatchPlanPrompt(unittest.TestCase):
    """AD-2's precedence, extended: admin > handoff > plan > tweak."""

    def setUp(self):
        self.calls = []

        def fake_detach(program, arguments, working_dir):
            self.calls.append((program, list(arguments), str(working_dir)))
            return True

        self.fake_detach = fake_detach

    def test_plan_prompt_is_passed_through_verbatim(self):
        spawnclaude.dispatch(plan_prompt="/setcurrentplan AlphaPLAN.md",
                             repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "/setcurrentplan AlphaPLAN.md")

    def test_admin_still_beats_a_plan_prompt(self):
        spawnclaude.dispatch(admin=True, plan_prompt="/createplan",
                             repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "claude")

    def test_handoff_still_beats_a_plan_prompt(self):
        spawnclaude.dispatch(handoff=".claude/dispatch/x.json",
                             plan_prompt="/createplan",
                             repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1],
                         "/dispatch .claude/dispatch/x.json")

    def test_a_plan_prompt_beats_a_tweak(self):
        spawnclaude.dispatch(plan_prompt="/createplan AudioPLAN",
                             tweak_prompt="x", repo=REPO, detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "/createplan AudioPLAN")

    def test_no_plan_prompt_leaves_the_ad_2_chain_untouched(self):
        spawnclaude.dispatch(tweak_prompt="tiny fix", repo=REPO,
                             detach=self.fake_detach)
        self.assertEqual(self.calls[0][1][-1], "/smalltweak tiny fix")


class TestOpenPlanningFolder(TempRepoCase):
    def setUp(self):
        super().setUp()
        self.calls = []

        def fake_detach(program, arguments, working_dir):
            self.calls.append((program, list(arguments), str(working_dir)))
            return True

        self.detach = fake_detach

    def test_argv_is_split_into_program_and_arguments(self):
        with unittest.mock.patch.object(plans.sys, "platform", "win32"):
            ok = spawnclaude.open_planning_folder(repo=self.repo,
                                                  detach=self.detach)
        self.assertTrue(ok)
        self.assertEqual(self.calls,
                         [("explorer", [str(self.planning)], str(self.repo))])

    def test_it_honours_the_platform(self):
        with unittest.mock.patch.object(plans.sys, "platform", "linux"):
            spawnclaude.open_planning_folder(repo=self.repo, detach=self.detach)
        self.assertEqual(self.calls[0][0], "xdg-open")


class TestPlansGroup(TempRepoCase):
    """The launcher's Plans group, offscreen, with a fake launcher — no real
    terminal and no real explorer ever opens."""

    def setUp(self):
        super().setUp()
        self.calls = []

        def fake_detach(program, arguments, working_dir):
            self.calls.append((program, list(arguments), str(working_dir)))
            return True

        self.detach = fake_detach

    def launcher(self):
        return spawnclaude.SpawnClaudeDialog(repo=self.repo, detach=self.detach)

    def combo_items(self, dialog):
        combo = dialog._plan_combo
        return [combo.itemText(i) for i in range(combo.count())]

    def test_label_shows_the_active_plan(self):
        dialog = self.launcher()
        self.assertEqual(dialog._active_plan_label.text(),
                         "Active plan: AlphaPLAN.md")

    def test_label_says_none_set_when_the_marker_is_absent(self):
        self.write_mirror("# hand-edited, marker stripped\n")
        dialog = self.launcher()
        self.assertEqual(dialog._active_plan_label.text(),
                         "Active plan: — none set")

    def test_picker_lists_exactly_the_planning_md_files(self):
        dialog = self.launcher()
        self.assertEqual(self.combo_items(dialog), sorted(self.PLANS))
        self.assertEqual(dialog._plan_combo.currentText(), "AlphaPLAN.md")  # active
        self.assertTrue(dialog._plan_combo.isEnabled())

    def test_an_empty_planning_dir_disables_the_picker_and_the_button(self):
        for name in self.PLANS:
            (self.planning / name).unlink()
        dialog = self.launcher()
        self.assertEqual(self.combo_items(dialog), [])
        self.assertFalse(dialog._plan_combo.isEnabled())
        self.assertFalse(dialog._set_plan_button.isEnabled())
        dialog._on_set_current_plan()  # no-op, not a crash
        self.assertEqual(self.calls, [])

    def test_set_as_current_spawns_setcurrentplan_and_writes_no_plan_md(self):
        before = (self.repo / "PLAN.md").read_text(encoding="utf-8")
        dialog = self.launcher()
        dialog._plan_combo.setCurrentIndex(1)  # BetaPLAN.md
        dialog._on_set_current_plan()
        self.assertEqual(len(self.calls), 1)
        program, arguments, working_dir = self.calls[0]
        self.assertEqual(program, "wt")
        self.assertEqual(arguments[-1], "/setcurrentplan BetaPLAN.md")
        self.assertEqual(working_dir, str(self.repo))
        self.assertEqual(dialog.result(), QDialog.Accepted)
        # The editor delegates the write to the spawned skill.
        self.assertEqual((self.repo / "PLAN.md").read_text(encoding="utf-8"),
                         before)

    def test_open_planning_folder_reveals_and_leaves_the_dialog_open(self):
        dialog = self.launcher()
        with unittest.mock.patch.object(plans.sys, "platform", "win32"):
            dialog._on_open_planning_folder()
        self.assertEqual(self.calls,
                         [("explorer", [str(self.planning)], str(self.repo))])
        self.assertNotEqual(dialog.result(), QDialog.Accepted)  # stays open

    def test_create_a_new_plan_radio_dispatches_createplan_with_the_brief(self):
        dialog = self.launcher()
        dialog._create_plan_radio.setChecked(True)
        dialog._create_plan_edit.setText("AudioPLAN — port the prototype's audio")
        dialog._on_dispatch()
        self.assertEqual(self.calls[0][1][-1],
                         "/createplan AudioPLAN — port the prototype's audio")

    def test_a_blank_brief_still_loads_the_skill(self):
        dialog = self.launcher()
        dialog._create_plan_radio.setChecked(True)
        dialog._on_dispatch()
        self.assertEqual(self.calls[0][1][-1], "/createplan")

    def test_the_create_plan_radio_is_exclusive_with_tweak_and_admin(self):
        dialog = self.launcher()
        self.assertTrue(dialog._tweak_radio.isChecked())  # unchanged default
        dialog._create_plan_radio.setChecked(True)
        self.assertFalse(dialog._tweak_radio.isChecked())
        self.assertFalse(dialog._admin_radio.isChecked())
        dialog._admin_radio.setChecked(True)
        self.assertFalse(dialog._create_plan_radio.isChecked())
        dialog._on_dispatch()
        self.assertEqual(self.calls[0][1][-1], "claude")  # admin still wins


if __name__ == "__main__":
    unittest.main()
