"""feature-enemy-intro-dialogue: core.schema.json's enemy_intro_entry
sprite_slot/animation enums must stay in sync with the live slot registry.

Both enums are GENERATED (tools/gen_sprite_slot_enum.py), not hand-maintained
— this pins the drift check so forgetting to re-run the generator after
touching data/slots.json fails CI loudly instead of shipping a slot/
animation the enemy-intro dialogue silently can't select.
"""
import json
import unittest
from pathlib import Path

from engine.assets.registry import load_registry
from tools.gen_sprite_slot_enum import compute_enums

REPO = Path(__file__).resolve().parents[2]


class TestSpriteSlotEnumSync(unittest.TestCase):
    def committed_enums(self):
        schema = json.loads(
            (REPO / "data" / "schemas" / "core.schema.json").read_text(
                encoding="utf-8"))
        entry = schema["$defs"]["enemy_intro_entry"]
        return (entry["properties"]["sprite_slot"]["enum"],
               entry["properties"]["animation"]["enum"])

    def test_sprite_slot_enum_matches_live_registry(self):
        committed_slots, _committed_animations = self.committed_enums()
        live_slots, _live_animations = compute_enums(REPO / "data")
        self.assertEqual(
            committed_slots, live_slots,
            "core.schema.json's sprite_slot enum is stale — re-run "
            "`py tools/gen_sprite_slot_enum.py`")

    def test_animation_enum_matches_live_registry(self):
        _committed_slots, committed_animations = self.committed_enums()
        _live_slots, live_animations = compute_enums(REPO / "data")
        self.assertEqual(
            committed_animations, live_animations,
            "core.schema.json's animation enum is stale — re-run "
            "`py tools/gen_sprite_slot_enum.py`")

    def test_generator_is_idempotent_on_live_data(self):
        registry = load_registry(REPO / "data")
        slots, animations = compute_enums(REPO / "data")
        self.assertEqual(slots, sorted(registry.slot_keys()))
        self.assertEqual(slots, sorted(set(slots)), "no duplicate slot keys")
        self.assertEqual(animations, sorted(set(animations)),
                         "no duplicate animation names")


if __name__ == "__main__":
    unittest.main()
