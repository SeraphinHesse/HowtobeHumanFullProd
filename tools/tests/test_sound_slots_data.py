"""SD-1: the sound slot data model — `$defs` drift, slot paths, validation.

The two `$defs` (`sound_clip`, `sound_slot`) are DUPLICATED into five schemas
because cross-file `$ref` is forbidden here; `tools/gen_sound_slot_defs.py`
owns the one literal copy and this module fails CI when a committed schema
drifts from it.

The slot path table is a contract: SD-2..SD-7 index these strings literally.
`core.Sounds.Ambient.default` is asserted present and `...Ambient.loop`
absent, so the rename away from the doubled `Ambient.loop.loop` path cannot
silently regress.
"""
import json
import shutil
import unittest
from pathlib import Path

import jsonschema

from engine import data_io
from tools.gen_sound_slot_defs import DOMAINS, apply, sound_slot_defs

REPO = Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "data" / "schemas"
BAL = REPO / "data" / "balancing"

BUILDING_EVENTS = ("attack", "death", "placement", "selection", "upgrade",
                   "upkeep_boost")
BUILDING_FAMILIES = (
    "BoostBuildings.Damage", "BoostBuildings.HP", "BoostBuildings.Speed",
    "DefenceBuildings.AOEDefence", "DefenceBuildings.BasicDefence",
    "DefenceBuildings.BeamDefence", "DefenceBuildings.StormPriest",
    "EconomyBuildings.Meditators", "EconomyBuildings.Musicians",
    "EconomyBuildings.Painters",
    "StructureBuildings.Blocker", "StructureBuildings.WallBuilder",
)
ENEMY_EVENTS = ("attack", "death", "spawn")
ENEMY_TYPES = ("Boss", "Commander", "Digger", "Drummer", "Formation",
               "Raider", "SiegeCannon", "Sniper", "Standard", "Tutorial")

#: Every slot path this phase creates, as literal dotted strings.
SLOT_PATHS = (
    [f"core.Sounds.Music.{k}" for k in
     ("boss_phase", "building_phase", "combat_phase", "cutscene", "default",
      "menu")]
    + ["core.Sounds.Ambient.default"]
    + [f"core.Sounds.Game.{k}" for k in
       ("game_over", "game_start", "level_up", "round_loss", "round_start",
        "round_win")]
    + ["ui.Sounds.button_click", "ui.Sounds.not_enough_love"]
    + ["map.Sounds.buy_plot", "map.Sounds.tile_placement"]
    + [f"buildings.BuildingsGlobal.Sounds.{e}" for e in BUILDING_EVENTS]
    + [f"buildings.{fam}.sounds.{e}"
       for fam in BUILDING_FAMILIES for e in BUILDING_EVENTS]
    + [f"enemies.EnemySounds.{e}" for e in ENEMY_EVENTS]
    + [f"enemies.EnemyTypes.{t}.sounds.{e}"
       for t in ENEMY_TYPES for e in ENEMY_EVENTS]
)


def committed_defs(domain):
    schema = json.loads(
        (SCHEMAS / f"{domain}.schema.json").read_text(encoding="utf-8"))
    return {k: schema["$defs"][k] for k in ("sound_clip", "sound_slot")}


def resolve_schema(domain, segments):
    """Walk a dotted slot path through a schema, resolving local $defs refs."""
    node = json.loads(
        (SCHEMAS / f"{domain}.schema.json").read_text(encoding="utf-8"))
    schema = node
    for seg in segments:
        node = node["properties"][seg]
        while "$ref" in node:
            node = schema["$defs"][node["$ref"].removeprefix("#/$defs/")]
    return node


def resolve_doc(domain, segments):
    node = json.loads((BAL / f"{domain}.json").read_text(encoding="utf-8"))
    for seg in segments:
        node = node[seg]
    return node


class TestSoundDefsDrift(unittest.TestCase):
    def test_every_schema_carries_the_generated_defs(self):
        canonical = sound_slot_defs()
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                self.assertEqual(
                    committed_defs(domain), canonical,
                    f"{domain}.schema.json's sound $defs are stale — re-run "
                    "`py tools/gen_sound_slot_defs.py`")

    def test_all_five_copies_are_identical(self):
        first = committed_defs(DOMAINS[0])
        for domain in DOMAINS[1:]:
            with self.subTest(domain=domain):
                self.assertEqual(committed_defs(domain), first)

    def test_generator_is_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "core.schema.json"
            shutil.copy(SCHEMAS / "core.schema.json", target)
            apply(target)
            once = target.read_bytes()
            apply(target)
            self.assertEqual(once, target.read_bytes())

    def test_x_widget_lives_inside_the_def_not_beside_the_ref(self):
        """editor/panels/balancing.py derefs before reading x- extensions, so
        a sibling marker would be silently dropped."""
        self.assertEqual(
            committed_defs("core")["sound_slot"].get("x-widget"),
            "sound_slot")
        site = json.loads(
            (SCHEMAS / "map.schema.json").read_text(encoding="utf-8")
        )["properties"]["Sounds"]["properties"]["buy_plot"]
        self.assertNotIn("x-widget", site)

    def test_pick_enum_is_exactly_random_and_sequential(self):
        pick = sound_slot_defs()["sound_slot"]["properties"]["pick"]
        self.assertEqual(pick["enum"], ["random", "sequential"])


class TestSlotPaths(unittest.TestCase):
    def test_every_slot_path_exists_in_schema_and_content(self):
        """Existence and SHAPE, never the authored VALUE.

        `clips`/`loop`/`pick` become designer-owned at SD-3 (the clip
        importer): asserting `clips == []` here would turn all 127 paths red
        the first time someone imports a sound through the editor, in a commit
        that touched none of this. What holds forever is that the path exists
        and still carries a well-formed slot. The state SD-1 SHIPPED is pinned
        separately in TestShippedSlotDefaults, against the schema rather than
        against live data.
        """
        for path in SLOT_PATHS:
            domain, *segments = path.split(".")
            with self.subTest(path=path):
                node = resolve_schema(domain, segments)
                self.assertEqual(node.get("x-widget"), "sound_slot")
                value = resolve_doc(domain, segments)
                self.assertIsInstance(value, dict)
                self.assertEqual(sorted(value), ["clips", "loop", "pick"])
                self.assertIsInstance(value["clips"], list)
                self.assertIsInstance(value["loop"], bool)
                self.assertIn(value["pick"], ("random", "sequential"))

    def test_ambient_slot_is_default_not_loop(self):
        core = json.loads((BAL / "core.json").read_text(encoding="utf-8"))
        ambient = core["Sounds"]["Ambient"]
        self.assertIn("default", ambient)
        self.assertNotIn("loop", ambient)

    def test_ui_sounds_is_closed_to_two_keys(self):
        node = json.loads(
            (SCHEMAS / "ui.schema.json").read_text(encoding="utf-8")
        )["properties"]["Sounds"]
        self.assertIs(node["additionalProperties"], False)
        self.assertEqual(sorted(node["properties"]),
                         ["button_click", "not_enough_love"])


class TestShippedSlotDefaults(unittest.TestCase):
    """The empty slot SD-1 ships, pinned as a literal against the SCHEMA.

    Deliberately NOT read back out of data/balancing/*.json: that content is
    designer-owned from SD-3 onward. What must not drift is the meaning of the
    empty form — `clips: []` is SD-2's "silence on a global default, inherit on
    an element override" contract — and that both the one-shot and the looping
    form stay valid in every domain.
    """

    EMPTY = {"clips": [], "loop": False, "pick": "random"}
    EMPTY_LOOPING = {"clips": [], "loop": True, "pick": "random"}

    def test_the_shipped_empty_slot_validates_in_every_domain(self):
        for domain in DOMAINS:
            defs = committed_defs(domain)
            schema = dict(defs["sound_slot"],
                          **{"$defs": {"sound_clip": defs["sound_clip"]}})
            for value in (self.EMPTY, self.EMPTY_LOOPING):
                with self.subTest(domain=domain, loop=value["loop"]):
                    jsonschema.validate(value, schema)

    def test_the_shipped_empty_slot_carries_exactly_the_required_keys(self):
        self.assertEqual(sorted(self.EMPTY),
                         sorted(committed_defs("core")["sound_slot"]["required"]))


class TestSlotValidation(unittest.TestCase):
    """Validate slot values against the real committed map schema."""

    SCHEMA = SCHEMAS / "map.schema.json"

    def doc_with(self, slot):
        doc = json.loads((BAL / "map.json").read_text(encoding="utf-8"))
        doc["Sounds"]["buy_plot"] = slot
        return doc

    def clip(self, **over):
        clip = {"file": "imported/a.ogg", "volume": 0.5, "start": 0.0,
                "end": 0.0}
        clip.update(over)
        return clip

    def test_empty_slot_validates(self):
        data_io.validate(
            self.doc_with({"clips": [], "loop": False, "pick": "random"}),
            self.SCHEMA)

    def test_two_clips_and_sequential_validate(self):
        data_io.validate(
            self.doc_with({"clips": [self.clip(), self.clip(end=2.5)],
                           "loop": True, "pick": "sequential"}),
            self.SCHEMA)

    def test_volume_above_one_is_rejected(self):
        with self.assertRaises(jsonschema.ValidationError):
            data_io.validate(
                self.doc_with({"clips": [self.clip(volume=1.5)],
                               "loop": False, "pick": "random"}), self.SCHEMA)

    def test_unknown_key_in_a_clip_is_rejected(self):
        clip = self.clip()
        clip["bus"] = "sfx"
        with self.assertRaises(jsonschema.ValidationError):
            data_io.validate(
                self.doc_with({"clips": [clip], "loop": False,
                               "pick": "random"}), self.SCHEMA)

    def test_null_end_is_rejected(self):
        with self.assertRaises(jsonschema.ValidationError):
            data_io.validate(
                self.doc_with({"clips": [self.clip(end=None)],
                               "loop": False, "pick": "random"}), self.SCHEMA)

    def test_unknown_pick_is_rejected(self):
        with self.assertRaises(jsonschema.ValidationError):
            data_io.validate(
                self.doc_with({"clips": [], "loop": False, "pick": "first"}),
                self.SCHEMA)


class TestNoTypelessNodes(unittest.TestCase):
    """A type-less or oneOf node crashes the balancing panel for the whole
    domain, so every node this phase added carries an explicit type."""

    def subtrees(self, schema):
        props = schema["properties"]
        for key in ("Sounds", "EnemySounds"):
            if key in props:
                yield props[key]
        if "BuildingsGlobal" in props:
            yield props["BuildingsGlobal"]["properties"]["Sounds"]
        for group in ("BoostBuildings", "DefenceBuildings", "EconomyBuildings",
                      "StructureBuildings", "EnemyTypes"):
            for fam in props.get(group, {}).get("properties", {}).values():
                if "sounds" in fam.get("properties", {}):
                    yield fam["properties"]["sounds"]
        for name in ("sound_clip", "sound_slot"):
            yield schema["$defs"][name]

    def walk(self, node, path, seen):
        self.assertNotIn("oneOf", node, f"oneOf at {path}")
        if "$ref" in node:
            self.assertTrue(node["$ref"].startswith("#/$defs/"), path)
            return
        self.assertIn("type", node, f"type-less node at {path}")
        for key, sub in node.get("properties", {}).items():
            self.walk(sub, f"{path}.{key}", seen)
        if "items" in node:
            self.walk(node["items"], f"{path}[]", seen)

    def test_no_typeless_or_oneof_nodes_in_the_new_subtrees(self):
        for domain in DOMAINS:
            schema = json.loads(
                (SCHEMAS / f"{domain}.schema.json").read_text(
                    encoding="utf-8"))
            for i, node in enumerate(self.subtrees(schema)):
                with self.subTest(domain=domain, subtree=i):
                    self.walk(node, f"{domain}#{i}", set())


if __name__ == "__main__":
    unittest.main()
