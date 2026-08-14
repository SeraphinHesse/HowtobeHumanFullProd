"""feature-enemy-intro-dialogue: core.schema.json's enemy_intro_entry
sprite_slot/animation enums must stay in sync with the live slot registry.

Both enums are GENERATED (tools/gen_sprite_slot_enum.py), not hand-maintained
— this pins the drift check so forgetting to re-run the generator after
touching data/slots.json fails CI loudly instead of shipping a slot/
animation the enemy-intro dialogue silently can't select.

VfxAuthoringPLAN VA-1/D2 added a THIRD generated enum on the same mechanism:
vfx.schema.json's trigger_row.sprite_slot. It was hand-typed and had already
drifted to six keys against thirteen real vfx slots. Its sibling
trigger_row.procedural is deliberately NOT generated and NOT pinned here —
those values name game-code kinds (game/ui/effects.py::_run_procedural's
ladder), not procedural.* balancing keys; see the generator's docstring.
"""
import json
import unittest
from pathlib import Path

from engine.assets.registry import load_registry
from tools.gen_sprite_slot_enum import compute_enums, compute_vfx_slot_enum

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


class TestVfxTriggerSlotEnumSync(unittest.TestCase):
    """VA-1/D2: vfx.schema.json's trigger_row.sprite_slot enum is generated
    from the `vfx` slot category, so add/remove/rename (VA-6) cannot leave it
    behind."""

    def committed_enum(self):
        schema = json.loads(
            (REPO / "data" / "schemas" / "vfx.schema.json").read_text(
                encoding="utf-8"))
        return schema["$defs"]["trigger_row"]["properties"]["sprite_slot"]["enum"]

    def test_enum_matches_live_registry(self):
        self.assertEqual(
            self.committed_enum(), compute_vfx_slot_enum(REPO / "data"),
            "vfx.schema.json's trigger_row.sprite_slot enum is stale — re-run "
            "`py tools/gen_sprite_slot_enum.py`")

    def test_enum_covers_every_vfx_slot(self):
        """The drift this replaced: the hand-typed list held six of thirteen
        slots, so a designer binding a real slot got a schema rejection."""
        registry = load_registry(REPO / "data")
        committed = set(self.committed_enum())
        missing = set(registry.group_slots("vfx")) - committed
        self.assertEqual(missing, set(), f"vfx slots absent from the enum: "
                                         f"{sorted(missing)}")

    def test_enum_allows_empty_and_nothing_foreign(self):
        """"" means "no sprite — run the procedural fallback"; every other
        value must be a real vfx slot (a key from another category would let a
        trigger bind art the vfx path cannot resolve)."""
        registry = load_registry(REPO / "data")
        committed = self.committed_enum()
        self.assertIn("", committed)
        vfx_slots = set(registry.group_slots("vfx"))
        foreign = [k for k in committed if k and k not in vfx_slots]
        self.assertEqual(foreign, [], f"non-vfx keys in the enum: {foreign}")

    def test_shipped_trigger_rows_validate_against_the_enum(self):
        """Every binding data/balancing/vfx.json actually ships is selectable.
        The stale enum happened to still cover the shipped rows, which is why
        it went unnoticed — pin it so a future regeneration cannot silently
        drop one."""
        balance = json.loads(
            (REPO / "data" / "balancing" / "vfx.json").read_text(
                encoding="utf-8"))
        allowed = set(self.committed_enum())
        for event, row in balance["triggers"].items():
            self.assertIn(row["sprite_slot"], allowed,
                          f"trigger {event!r} binds a slot the enum rejects")


if __name__ == "__main__":
    unittest.main()
