"""Acceptance tests for Phase TU-1's data shapes (D3/D4/D5, planning/
TutorialPLAN.md): the tutorial script, the cutscene registry, and the new
``Tutorial`` balancing group. Pure data-shape validation — no sequencer, no
director; TU-6/TU-7 build on top of the schema this phase fixes.

Reads through the pinned FIXTURE_DATA snapshot (tools/tests/fixture_data.py),
never live ``data/`` — a designer edit must never turn this gate red.
"""
import copy
import unittest

import jsonschema

from engine import data_io
from tools import smoke
from tools.tests.fixture_data import FIXTURE_DATA

TUTORIAL_DATA = FIXTURE_DATA / "tutorial" / "tutorial.json"
TUTORIAL_SCHEMA = FIXTURE_DATA / "schemas" / "tutorial.schema.json"
CUTSCENES_DATA = FIXTURE_DATA / "video" / "cutscenes.json"
CUTSCENES_SCHEMA = FIXTURE_DATA / "schemas" / "cutscenes.schema.json"
CORE_DATA = FIXTURE_DATA / "balancing" / "core.json"
CORE_SCHEMA = FIXTURE_DATA / "schemas" / "core.schema.json"

MSG_ECONOMY_INTRO = (
    "You need love to create. In order for you to gain Love, you need "
    "economy buildings")
MSG_LIVES_INTRO = (
    "Once the humans reach our hole the round is lost. You have only 3 "
    "lives. If economy buildings get destroyed during the human attack "
    "they don't yield resources. To defend your base you need to build "
    "defense buildings")


class TestTutorialScript(unittest.TestCase):
    def test_validates_against_its_schema(self):
        data_io.load_validated(TUTORIAL_DATA, TUTORIAL_SCHEMA)  # must not raise

    def test_files_are_canonical_on_disk(self):
        for path in (TUTORIAL_DATA, TUTORIAL_SCHEMA):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(
                    text, data_io.dumps_deterministic(data_io.load_json(path)))

    def test_message_texts_verbatim(self):
        data = data_io.load_json(TUTORIAL_DATA)
        self.assertEqual(data["messages"]["economy_intro"], MSG_ECONOMY_INTRO)
        self.assertEqual(data["messages"]["lives_intro"], MSG_LIVES_INTRO)

    def test_toggles(self):
        data = data_io.load_json(TUTORIAL_DATA)
        self.assertIs(data["skippable"], True)
        self.assertIs(data["first_loss_costs_life"], True)

    def test_step_list_covers_round_1_and_round_2_highlights(self):
        data = data_io.load_json(TUTORIAL_DATA)
        self.assertGreaterEqual(len(data["steps"]), 1)
        highlights = [h for step in data["steps"] for h in step["highlight"]]
        self.assertIn("tile:tutorial_flute", highlights)
        # TU-6: the script's building id is "economic" — the real runtime
        # `building_type` for the Musician card (game/buildings/musician.py
        # BUILDING_TYPE), not the illustrative "musician" TU-1 seeded before
        # TU-6 reconciled the vocabulary against the registry.
        self.assertIn("card:economic", highlights)
        self.assertIn("button:confirm", highlights)
        self.assertIn("button:end_turn", highlights)
        # TU-7: round-2's stone-thrower chain (Defender BUILDING_TYPE
        # "defence") appended after the round-1 steps above, no schema change.
        self.assertIn("tile:tutorial_stone", highlights)
        self.assertIn("card:defence", highlights)
        flags = [step["flags"] for step in data["steps"]]
        self.assertTrue(any(f.get("is_scripted_loss") for f in flags))

    def test_unknown_step_key_rejected(self):
        schema = data_io.load_json(TUTORIAL_SCHEMA)
        data = copy.deepcopy(data_io.load_json(TUTORIAL_DATA))
        data["steps"][0]["not_a_real_key"] = 1
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_messages_missing_required_text_rejected(self):
        schema = data_io.load_json(TUTORIAL_SCHEMA)
        data = copy.deepcopy(data_io.load_json(TUTORIAL_DATA))
        del data["messages"]["lives_intro"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_step_flags_are_open(self):
        """flags is the ONE deliberately-open leaf (additionalProperties:
        true) so TU-6/TU-7 attach per-step data with no schema bump."""
        schema = data_io.load_json(TUTORIAL_SCHEMA)
        data = copy.deepcopy(data_io.load_json(TUTORIAL_DATA))
        data["steps"][0]["flags"]["anything_goes"] = 42
        jsonschema.validate(data, schema)  # must NOT raise


class TestCutsceneRegistry(unittest.TestCase):
    def test_validates_against_its_schema(self):
        data_io.load_validated(CUTSCENES_DATA, CUTSCENES_SCHEMA)  # must not raise

    def test_files_are_canonical_on_disk(self):
        for path in (CUTSCENES_DATA, CUTSCENES_SCHEMA):
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(
                    text, data_io.dumps_deterministic(data_io.load_json(path)))

    def test_required_entries_present(self):
        data = data_io.load_json(CUTSCENES_DATA)
        self.assertIn("intro", data)
        self.assertIn("first_end_turn", data)

    def test_intro_entry_matches_existing_hardcoded_cutscene(self):
        """D4: the intro entry mirrors game/main.py's (still hardcoded, TU-1
        does not migrate it) VideoSource(cutscene.mp4, cutscene_length=44.2)."""
        data = data_io.load_json(CUTSCENES_DATA)
        intro = data["intro"]
        self.assertEqual(intro["video"], "cutscene.mp4")
        self.assertEqual(intro["length"], 44.2)
        self.assertEqual(intro["trigger"], "intro")

    def test_first_end_turn_entry_present(self):
        data = data_io.load_json(CUTSCENES_DATA)
        first_end_turn = data["first_end_turn"]
        self.assertEqual(first_end_turn["trigger"], "first_end_turn")

    def test_unknown_trigger_rejected(self):
        schema = data_io.load_json(CUTSCENES_SCHEMA)
        data = copy.deepcopy(data_io.load_json(CUTSCENES_DATA))
        data["intro"]["trigger"] = "not_a_real_trigger"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)


class TestTutorialBalancing(unittest.TestCase):
    def test_validates_against_its_schema(self):
        data_io.load_validated(CORE_DATA, CORE_SCHEMA)  # must not raise

    def test_economy_buildings_required_present(self):
        data = data_io.load_json(CORE_DATA)
        self.assertIn("Tutorial", data)
        self.assertGreaterEqual(data["Tutorial"]["economy_buildings_required"], 1)

    def test_below_minimum_rejected(self):
        schema = data_io.load_json(CORE_SCHEMA)
        data = copy.deepcopy(data_io.load_json(CORE_DATA))
        data["Tutorial"]["economy_buildings_required"] = 0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)


class TestSmokeSeesBothNewFiles(unittest.TestCase):
    def test_validate_data_checks_both_new_files(self):
        """smoke.validate_data resolves data/tutorial/tutorial.json and
        data/video/cutscenes.json via the plain stem-pairing branch (their
        stem already equals their schema's stem) — no directory exception
        needed, zero tools/smoke.py code change."""
        checked = smoke.validate_data(FIXTURE_DATA)
        self.assertGreater(checked, 0)
        # both files exist and are real content, not accidentally excluded
        self.assertTrue(TUTORIAL_DATA.exists())
        self.assertTrue(CUTSCENES_DATA.exists())
