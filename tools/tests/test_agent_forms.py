"""AD-1: the agent-dispatch data layer — form specs (data/agent_forms/*.json)
and handoff payloads (.claude/dispatch/*.json), plus the pure helpers in
editor/agent_forms.py that turn one into the other.

Everything here is pure: no Qt, no pygame, no game import. Temp trees stand in
for both data/ and the repo, so no test ever writes into the real repo.
"""
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]

from editor import agent_forms
from engine import data_io
from tools import smoke

HANDOFF_SCHEMA = REPO / "data" / "schemas" / "dispatch_handoff.schema.json"


def valid_spec(spec_id="add-enemy", **over):
    """A minimal spec that validates against agent_form.schema.json."""
    spec = {
        "schema_version": 1,
        "id": spec_id,
        "title": "Add New Enemy",
        "description": "Adds an enemy.",
        "skill": "add-enemy",
        "context": ["game/enemies/CLAUDE.md"],
        "git_default": "branch",
        "slug_field": "name",
        "fields": [
            {"key": "name", "label": "Enemy name", "type": "string",
             "description": "Display name."},
        ],
    }
    spec.update(over)
    return spec


class TempTreeCase(unittest.TestCase):
    """A throwaway repo root holding data/schemas (copied) — no .git, so
    _current_branch() resolves to None and spawned_from stays absent."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.data_dir = self.repo / "data"
        self.data_dir.mkdir()
        shutil.copytree(REPO / "data" / "schemas", self.data_dir / "schemas")

    def write_spec(self, stem, spec):
        directory = self.data_dir / "agent_forms"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}.json"
        path.write_text(data_io.dumps_deterministic(spec), encoding="utf-8")
        return path


class TestSlugify(unittest.TestCase):
    def test_spaces_become_single_dashes(self):
        self.assertEqual(agent_forms.slugify("Siege Cannon"), "siege-cannon")

    def test_punctuation_and_case_fold_without_stray_dashes(self):
        slug = agent_forms.slugify("The Hole's Bane!")
        self.assertEqual(slug, "the-hole-s-bane")
        self.assertFalse(slug.startswith("-") or slug.endswith("-"))
        self.assertNotIn("--", slug)

    def test_accents_fold_to_ascii(self):
        self.assertEqual(agent_forms.slugify("Crème Brûlée"), "creme-brulee")

    def test_max_len_truncates_and_leaves_no_trailing_dash(self):
        slug = agent_forms.slugify("aaaaaaaa bbbbbbbb cccccccc dddddddd", max_len=18)
        self.assertLessEqual(len(slug), 18)
        self.assertFalse(slug.endswith("-"))
        self.assertEqual(slug, "aaaaaaaa-bbbbbbbb")

    def test_empty_and_none(self):
        self.assertEqual(agent_forms.slugify(""), "")
        self.assertEqual(agent_forms.slugify(None), "")
        self.assertEqual(agent_forms.slugify("!!!"), "")


class TestDefaultBranchName(unittest.TestCase):
    def test_uses_slug_field(self):
        self.assertEqual(
            agent_forms.default_branch_name(
                valid_spec(), {"name": "Siege Cannon"}, ""),
            "agent/add-enemy-siege-cannon")

    def test_falls_back_to_free_text(self):
        for values in ({}, {"name": ""}):
            self.assertEqual(
                agent_forms.default_branch_name(
                    valid_spec(), values, "A slow armored cannon"),
                "agent/add-enemy-a-slow-armored-cannon")

    def test_both_empty_has_no_trailing_dash(self):
        self.assertEqual(
            agent_forms.default_branch_name(valid_spec(), {}, ""), "agent/add-enemy")

    def test_slug_field_default_is_name(self):
        spec = valid_spec()
        del spec["slug_field"]
        self.assertEqual(
            agent_forms.default_branch_name(spec, {"name": "Walker"}, ""),
            "agent/add-enemy-walker")


class TestLoadFormSpecs(TempTreeCase):
    def test_committed_add_enemy_spec_loads_and_validates(self):
        specs = agent_forms.load_form_specs()
        ids = [s["id"] for s in specs]
        self.assertIn("add-enemy", ids)
        spec = next(s for s in specs if s["id"] == "add-enemy")
        self.assertEqual(spec["skill"], "add-enemy")
        self.assertEqual(spec["schema_version"], agent_forms.SCHEMA_VERSION)
        self.assertEqual([f["key"] for f in spec["fields"]],
                         ["name", "registry_group", "targets_buildings", "era_count"])

    def test_specs_come_back_sorted_by_id(self):
        for stem in ("zebra", "alpha", "middle"):
            self.write_spec(stem, valid_spec(stem, skill="add-enemy"))
        specs = agent_forms.load_form_specs(self.data_dir)
        self.assertEqual([s["id"] for s in specs], ["alpha", "middle", "zebra"])

    def test_missing_directory_returns_empty(self):
        self.assertEqual(agent_forms.load_form_specs(self.data_dir), [])

    def test_numeric_field_without_bounds_is_invalid(self):
        spec = valid_spec()
        spec["fields"] = [{"key": "era_count", "label": "Eras", "type": "integer",
                           "description": "How many."}]  # no minimum/maximum
        self.write_spec("add-enemy", spec)
        with self.assertRaises(jsonschema.ValidationError):
            agent_forms.load_form_specs(self.data_dir)

    def test_enum_field_without_options_is_invalid(self):
        spec = valid_spec()
        spec["fields"] = [{"key": "group", "label": "Group", "type": "enum",
                           "description": "Which group."}]  # no options
        self.write_spec("add-enemy", spec)
        with self.assertRaises(jsonschema.ValidationError):
            agent_forms.load_form_specs(self.data_dir)

    def test_unknown_top_level_key_is_invalid(self):
        self.write_spec("add-enemy", valid_spec(surprise="nope"))
        with self.assertRaises(jsonschema.ValidationError):
            agent_forms.load_form_specs(self.data_dir)

    def test_id_stem_mismatch_raises_value_error(self):
        self.write_spec("add-enemy", valid_spec("add-building"))
        with self.assertRaises(ValueError):
            agent_forms.load_form_specs(self.data_dir)


class TestPayloadRoundTrip(TempTreeCase):
    def test_branch_mode_round_trips_through_write_validated(self):
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Siege Cannon", "era_count": 2},
            "  shells buildings  ", "branch", repo=self.repo)
        self.assertEqual(payload["git"]["branch"], "agent/add-enemy-siege-cannon")
        self.assertEqual(payload["git"]["base"], "Development")
        self.assertEqual(payload["free_text"], "shells buildings")
        self.assertNotIn("spawned_from", payload)  # temp repo has no .git

        path = agent_forms.write_handoff(payload, repo=self.repo,
                                         data_dir=self.data_dir)
        self.assertTrue(path.is_relative_to(self.repo / ".claude" / "dispatch"))
        self.assertEqual(path.name[-len("-add-enemy.json"):], "-add-enemy.json")
        self.assertEqual(path.read_text(encoding="utf-8"),
                         data_io.dumps_deterministic(payload))
        self.assertEqual(data_io.load_validated(path, HANDOFF_SCHEMA), payload)

    def test_current_mode_omits_branch_and_still_validates(self):
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Siege Cannon"}, "", "current", repo=self.repo)
        self.assertEqual(payload["git"], {"mode": "current", "base": "Development"})
        path = agent_forms.write_handoff(payload, repo=self.repo,
                                         data_dir=self.data_dir)
        data_io.load_validated(path, HANDOFF_SCHEMA)

    def test_explicit_branch_overrides_the_default_name(self):
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Siege Cannon"}, "", "branch",
            branch="agent/custom", repo=self.repo)
        self.assertEqual(payload["git"]["branch"], "agent/custom")

    def test_values_are_copied_not_aliased(self):
        values = {"name": "Walker"}
        payload = agent_forms.build_payload(
            valid_spec(), values, "", "current", repo=self.repo)
        values["name"] = "Mutated"
        self.assertEqual(payload["values"], {"name": "Walker"})

    def test_branch_mode_without_a_branch_is_schema_invalid(self):
        # the if/then on the git subschema is what makes it unrepresentable
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Walker"}, "", "branch", repo=self.repo)
        del payload["git"]["branch"]
        with self.assertRaises(jsonschema.ValidationError):
            agent_forms.write_handoff(payload, repo=self.repo,
                                      data_dir=self.data_dir)
        # write_validated validates first -> nothing reached disk
        self.assertEqual(list((self.repo / ".claude" / "dispatch").glob("*.json")), [])

    def test_bad_git_mode_raises(self):
        with self.assertRaises(ValueError):
            agent_forms.build_payload(valid_spec(), {}, "", "sideways",
                                      repo=self.repo)

    def test_name_collision_gets_a_numeric_suffix(self):
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Walker"}, "", "current", repo=self.repo)
        first = agent_forms.write_handoff(payload, repo=self.repo,
                                          data_dir=self.data_dir)
        second = agent_forms.write_handoff(payload, repo=self.repo,
                                           data_dir=self.data_dir)
        self.assertNotEqual(first, second)
        self.assertTrue(second.stem.endswith("-2"))


class TestHandoffRelpath(TempTreeCase):
    def test_returns_posix_repo_relative_path(self):
        payload = agent_forms.build_payload(
            valid_spec(), {"name": "Walker"}, "", "branch", repo=self.repo)
        path = agent_forms.write_handoff(payload, repo=self.repo,
                                         data_dir=self.data_dir)
        rel = agent_forms.handoff_relpath(path, repo=self.repo)
        self.assertNotIn("\\", rel)            # POSIX even on Windows
        self.assertTrue(rel.startswith(".claude/dispatch/"))
        self.assertTrue(rel.endswith(".json"))
        self.assertNotIn(" ", rel)             # one argv element for /dispatch

    def test_path_outside_the_repo_raises(self):
        with tempfile.TemporaryDirectory() as other:
            stray = Path(other) / "handoff.json"
            stray.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                agent_forms.handoff_relpath(stray, repo=self.repo)


class TestPruneDone(TempTreeCase):
    def backdate(self, path, days):
        old = time.time() - days * 86400
        os.utime(path, (old, old))

    def touch(self, rel):
        path = self.repo / ".claude" / "dispatch" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def test_missing_dirs_return_zero(self):
        self.assertEqual(agent_forms.prune_done(repo=self.repo), 0)

    def test_only_the_old_archived_file_goes(self):
        old = self.touch("done/20200101-000000-add-enemy.json")
        fresh = self.touch("done/20260713-000000-add-enemy.json")
        self.backdate(old, 40)
        self.assertEqual(agent_forms.prune_done(repo=self.repo, days=30), 1)
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_fresh_live_handoff_survives_and_stale_one_is_pruned(self):
        live = self.touch("20260713-120000-add-enemy.json")
        stale = self.touch("20260710-120000-add-enemy.json")
        self.backdate(stale, 2)
        self.assertEqual(agent_forms.prune_done(repo=self.repo, live_days=1), 1)
        self.assertTrue(live.exists())
        self.assertFalse(stale.exists())


class TestSmokePairing(TempTreeCase):
    """The THIRD tools/smoke.py directory exception: any stem under
    data/agent_forms/ pairs with agent_form.schema.json, not <stem>.schema.json
    (which does not exist — the plain stem rule would raise FileNotFoundError)."""

    def test_arbitrary_stem_pairs_to_agent_form_schema(self):
        self.write_spec("whatever_stem", valid_spec("whatever-stem"))
        self.assertEqual(smoke.validate_data(self.data_dir), 1)

    def test_invalid_form_file_fails_loud(self):
        self.write_spec("whatever_stem", {"not": "a form spec"})
        with self.assertRaises(jsonschema.ValidationError):
            smoke.validate_data(self.data_dir)

    def test_repo_data_still_validates(self):
        self.assertGreater(smoke.validate_data(), 0)


class TestFormSpecFreshLoad(TempTreeCase):
    """AD-5's load-bearing property: a spec file that lands in agent_forms/ is
    picked up by the NEXT load_form_specs call, in the same process, with no
    reload and no editor restart. That is what makes "add a form" a pure data
    change — the launcher re-reads the directory on every open, so a new spec
    file IS a new feature."""

    def test_committed_add_form_spec_is_the_meta_form(self):
        spec = next(s for s in agent_forms.load_form_specs()
                    if s["id"] == "add-form-spec")
        self.assertEqual(spec["skill"], "add-form-spec")
        self.assertEqual(spec["slug_field"], "thing_name")
        self.assertEqual([f["key"] for f in spec["fields"]],
                         ["thing_name", "target_skill", "needs_new_skill",
                          "git_default"])
        # the two git_defaults are DIFFERENT things and must both survive:
        # top-level = this form's own pre-selected radio; the field = the
        # default the GENERATED form will carry.
        self.assertEqual(spec["git_default"], "branch")
        field = next(f for f in spec["fields"] if f["key"] == "git_default")
        self.assertEqual(field["type"], "enum")
        self.assertEqual(field["options"], ["branch", "current"])

    def test_a_spec_dropped_on_disk_appears_on_the_next_load(self):
        schema = self.data_dir / "schemas" / "agent_form.schema.json"
        forms = self.data_dir / "agent_forms"
        forms.mkdir(parents=True, exist_ok=True)
        self.write_spec("add-enemy", valid_spec())

        before = [s["id"] for s in agent_forms.load_form_specs(self.data_dir)]
        self.assertEqual(before, ["add-enemy"])

        # the generated spec goes down the same sanctioned path the skill uses
        generated = valid_spec("add-sound-effect", title="Add New Sound Effect",
                               skill="add-sound-effect")
        data_io.write_validated(generated, forms / "add-sound-effect.json", schema)

        after = [s["id"] for s in agent_forms.load_form_specs(self.data_dir)]
        self.assertIn("add-sound-effect", after)        # no restart, no reload
        self.assertEqual(after, sorted(after))          # still sorted by id
        self.assertEqual(after, ["add-enemy", "add-sound-effect"])

    def test_an_invalid_generated_spec_never_reaches_disk(self):
        schema = self.data_dir / "schemas" / "agent_form.schema.json"
        forms = self.data_dir / "agent_forms"
        forms.mkdir(parents=True, exist_ok=True)
        bad = valid_spec("add-sound-effect")
        bad["fields"] = [{"key": "gain", "label": "Gain", "type": "number",
                          "description": "Volume."}]  # no minimum/maximum
        with self.assertRaises(jsonschema.ValidationError):
            data_io.write_validated(bad, forms / "add-sound-effect.json", schema)
        self.assertEqual(list(forms.glob("*.json")), [])
        self.assertEqual(agent_forms.load_form_specs(self.data_dir), [])


if __name__ == "__main__":
    unittest.main()
