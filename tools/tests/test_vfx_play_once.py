"""ESV-5: sprite one-shots (`PlayOnceVfx`) + the trigger table.

Tests 1-9 per the phase brief (docs/briefs/phase-esv-5-sprite-oneshots.md
§4); test 10 (the editor MainWindow routing fix) lives in
tools/tests/test_editor_viewport.py (TestMainWindowVfxMode) alongside the
other MainWindow-routing tests it structurally mirrors. Test 11 (TestPurity
module-count confirmation) needs no new entry — no new editor module was
added.

Every test uses the pinned FIXTURE_DATA snapshot (never live data/) or a
random.Random(seed); nothing here writes into data/.

**Deviation from the brief's suggested kw shape (report this loudly):**
`enemy_death` fires over a BATCH of simultaneous death points, and `_play`'s
signature takes exactly one (wx, wy) — there is no single shared spawn point
a `points=` kwarg could hand to the sprite-one-shot branch (one death should
get one one-shot, once art exists). `spawn_death_events` therefore calls
`_play` ONCE PER POINT instead of once with `points=events`; the procedural
fallback (`add_splatters([(wx, wy)])` per point) extends the SAME list in
the SAME order a single batched call would have, so the no-art landing
condition is unaffected — see TestByteIdenticalFallbackAllEvents.
test_enemy_death below.
"""
import random
import tempfile
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy

from engine import data_io
from engine.assets import load_registry
from engine.core import Scene
from engine.vfx import PlayOnceFade, PlayOnceVfx, VfxSystem, spawn_play_once
from game.core.balance import load_balance
from game.ui.effects import FloaterManager

VFX_DATA_PATH = FIXTURE_DATA / "balancing" / "vfx.json"
VFX_SCHEMA_PATH = FIXTURE_DATA / "schemas" / "vfx.schema.json"

_LIVE_EVENTS = (
    "building_placed", "building_level_up", "building_tier_up",
    "building_destroyed", "enemy_attack_melee", "enemy_attack_ranged",
    "enemy_death", "splash_impact",
)
# ESV-6 adds the 10th event, projectile_hit (also shipped inert, like
# defender_fire) — see docs/briefs/phase-esv-6-converge.md §1.3.
_ALL_EVENTS = _LIVE_EVENTS + ("defender_fire", "projectile_hit")


class _FakeAssets:
    """The ONLY method `spawn_play_once` reads: `animation_total_ms(slot,
    name)`. `sheets` maps slot_key -> total_ms (absent/None = no art)."""

    def __init__(self, sheets):
        self._sheets = sheets

    def animation_total_ms(self, slot_key, name):
        return self._sheets.get(slot_key)


def _fm(vfx_bal=None):
    """A real FloaterManager built from the pinned fixture (ui/core always
    the fixture snapshot; vfx defaults to the fixture's vfx.json, or a
    caller-mutated copy of it — the doc is never written to disk)."""
    ui_bal = load_balance(FIXTURE_DATA, "ui")
    core_bal = load_balance(FIXTURE_DATA, "core")
    if vfx_bal is None:
        vfx_bal = data_io.load_json(VFX_DATA_PATH)
    fm = FloaterManager(ui_bal, core_bal, vfx_bal)
    fm.assets = None
    fm.scene = None
    return fm


def _slots(obj):
    """Read every __slots__ field off a Particle/GoldHighlight/Slash — those
    classes carry no __dict__, so vars() cannot compare them."""
    return {name: getattr(obj, name) for name in obj.__slots__}


class TestSpawnPlayOnceArtTolerance(unittest.TestCase):
    """§4 test 1: spawn_play_once returns None for a slot with no art and
    spawns nothing into the scene — the entire art-tolerance mechanism."""

    def test_returns_none_and_spawns_nothing_with_no_art(self):
        scene = Scene()
        assets = _FakeAssets({})   # the slot is absent from the manifest
        result = spawn_play_once(scene, assets, "vfx_muzzle", 1.0, 2.0)
        self.assertIsNone(result)
        scene.update(0.0)
        self.assertEqual(scene.by_tag("vfx_oneshot"), [])
        self.assertEqual(scene.objects(), [])


class TestPlayOnceVfxLifetime(unittest.TestCase):
    """§4 test 2: PlayOnceVfx despawns after exactly one play — stepping the
    scene to just under the fixture duration keeps it alive, just over
    despawns it. Scene object count asserted both sides."""

    def test_despawns_after_exactly_one_play(self):
        scene = Scene()
        assets = _FakeAssets({"vfx_muzzle": 500})   # 500 ms fixture duration
        vfx = spawn_play_once(scene, assets, "vfx_muzzle", 1.0, 2.0)
        self.assertIsInstance(vfx, PlayOnceVfx)
        scene.update(0.0)   # apply the spawn queue
        self.assertEqual(scene.objects(), [vfx])

        scene.update(0.49)   # 490 ms < 500 ms: still alive
        self.assertEqual(scene.objects(), [vfx])

        scene.update(0.02)   # 510 ms total > 500 ms: despawns THIS update
        self.assertEqual(scene.objects(), [])


class TestByteIdenticalFallbackAllEvents(unittest.TestCase):
    """§4 test 3 (the landing-condition contract in test form): with no art
    (assets/scene None), each of the 8 LIVE events' `_play` dispatch
    produces the SAME particle/gold/slash/splatter effect as calling the
    matching VfxSystem method directly with an identically-seeded rng.
    `defender_fire` (event #9) has no production call site — see
    TestDefenderFireInert."""

    SEED = 4242

    def _pair(self):
        fm = _fm()
        fm._vfx = VfxSystem(fm._vfx_params, rng=random.Random(self.SEED))
        direct = VfxSystem(fm._vfx_params, rng=random.Random(self.SEED))
        return fm, direct

    def _assert_particles_equal(self, fm, direct):
        self.assertGreater(len(direct._particles), 0)
        self.assertEqual(len(fm._vfx._particles), len(direct._particles))
        for p1, p2 in zip(fm._vfx._particles, direct._particles):
            self.assertEqual(_slots(p1), _slots(p2))

    def test_building_placed(self):
        fm, direct = self._pair()
        preset = fm._spark_presets["place"]
        fm._play("building_placed", 1.0, 2.0, preset=preset)
        direct.emit_burst(preset, 1.0, 2.0)
        self._assert_particles_equal(fm, direct)

    def test_building_level_up(self):
        fm, direct = self._pair()
        preset = fm._spark_presets["level1"]
        fm._play("building_level_up", 1.0, 2.0, preset=preset)
        direct.emit_burst(preset, 1.0, 2.0)
        self._assert_particles_equal(fm, direct)

    def test_building_tier_up(self):
        fm, direct = self._pair()
        preset = fm._spark_presets["tier"]
        fm._play("building_tier_up", 1.0, 2.0, preset=preset)
        direct.emit_burst(preset, 1.0, 2.0)
        self._assert_particles_equal(fm, direct)

    def test_building_destroyed(self):
        fm, direct = self._pair()
        fm._play("building_destroyed", 1.0, 2.0)
        direct.emit_shards(1.0, 2.0)
        self._assert_particles_equal(fm, direct)

    def test_enemy_attack_melee(self):
        fm, direct = self._pair()
        fm._play("enemy_attack_melee", 1.0, 2.0, large=True)
        direct.emit_slash(1.0, 2.0, large=True)
        self.assertEqual(len(fm._vfx._slashes), 1)
        self.assertEqual(len(direct._slashes), 1)
        self.assertEqual(_slots(fm._vfx._slashes[0]), _slots(direct._slashes[0]))

    def test_enemy_attack_ranged(self):
        fm, direct = self._pair()
        fm._play("enemy_attack_ranged", 1.0, 2.0, strong=True)
        direct.emit_muzzle(1.0, 2.0, strong=True)
        self._assert_particles_equal(fm, direct)

    def test_enemy_death(self):
        """The per-point dispatch deviation (module docstring): a single
        _play call for one death point extends _splatters exactly like a
        batched add_splatters([(wx, wy)]) call would."""
        fm, direct = self._pair()
        fm._play("enemy_death", 1.0, 2.0)
        direct.add_splatters([(1.0, 2.0)])
        self.assertEqual(fm._vfx._splatters, direct._splatters)
        self.assertEqual(fm._vfx._splatters, [(1.0, 2.0)])

    def test_splash_impact(self):
        """procedural="crater": the Crater GameObject's own continuous fade
        mark spawns unconditionally in game/enemies/combat.py, independent
        of this table — so _play emits NOTHING into the VfxSystem either
        side."""
        fm, direct = self._pair()
        fm._play("splash_impact", 1.0, 2.0)
        self.assertEqual(fm._vfx._particles, direct._particles)
        self.assertEqual(fm._vfx._gold, direct._gold)
        self.assertEqual(fm._vfx._slashes, direct._slashes)
        self.assertEqual(fm._vfx._splatters, direct._splatters)
        self.assertEqual(fm._vfx._particles, [])


class TestDefenderFireInert(unittest.TestCase):
    """§4 test 4: dispatching defender_fire with no art and the shipped row
    (both fields "") emits nothing and raises nothing."""

    def test_dispatch_is_a_true_no_op(self):
        fm = _fm()
        before = (list(fm._vfx._particles), list(fm._vfx._gold),
                  list(fm._vfx._slashes), list(fm._vfx._splatters))
        fm._play("defender_fire", 1.0, 2.0)   # must not raise
        after = (list(fm._vfx._particles), list(fm._vfx._gold),
                 list(fm._vfx._slashes), list(fm._vfx._splatters))
        self.assertEqual(before, after)
        self.assertEqual(fm._triggers["defender_fire"], ("", ""))


class TestReassignmentWorks(unittest.TestCase):
    """§4 test 5: rewriting a row's procedural in a temp vfx.json changes
    which effect plays; rewriting sprite_slot to a slot WITH a fixture sheet
    spawns a PlayOnceVfx instead of particles."""

    def test_rewriting_procedural_changes_the_effect(self):
        vfx_bal = data_io.load_json(VFX_DATA_PATH)
        vfx_bal["triggers"]["enemy_attack_ranged"]["procedural"] = "slash"
        fm = _fm(vfx_bal)
        fm._play("enemy_attack_ranged", 1.0, 2.0, strong=False, large=False)
        self.assertEqual(fm._vfx._particles, [])   # muzzle would have added some
        self.assertEqual(len(fm._vfx._slashes), 1)

    def test_rewriting_sprite_slot_to_a_slot_with_art_spawns_a_sprite(self):
        vfx_bal = data_io.load_json(VFX_DATA_PATH)
        vfx_bal["triggers"]["enemy_attack_ranged"]["sprite_slot"] = "vfx_muzzle"
        fm = _fm(vfx_bal)
        fm.assets = _FakeAssets({"vfx_muzzle": 250})
        scene = Scene()
        fm.scene = scene
        fm._play("enemy_attack_ranged", 1.0, 2.0, strong=False)
        scene.update(0.0)
        self.assertEqual(len(scene.by_tag("vfx_oneshot")), 1)
        self.assertEqual(fm._vfx._particles, [])   # procedural did NOT run


class TestMissingEmptyNoneHandles(unittest.TestCase):
    """§4 test 6: an event absent from the table, a row with both fields
    "", and a FloaterManager with assets=None or scene=None each degrade
    silently — no raise, ever."""

    def test_event_absent_from_the_table_degrades_silently(self):
        fm = _fm()
        fm._play("this_event_does_not_exist", 1.0, 2.0)   # must not raise

    def test_both_fields_empty_degrades_silently(self):
        fm = _fm()
        fm._triggers["custom_inert"] = ("", "")
        fm._play("custom_inert", 1.0, 2.0)   # must not raise

    def test_assets_none_degrades_to_procedural(self):
        vfx_bal = data_io.load_json(VFX_DATA_PATH)
        vfx_bal["triggers"]["enemy_attack_ranged"]["sprite_slot"] = "vfx_muzzle"
        fm = _fm(vfx_bal)
        fm.assets = None   # never set
        fm.scene = Scene()
        fm._play("enemy_attack_ranged", 1.0, 2.0, strong=False)
        self.assertGreater(len(fm._vfx._particles), 0)

    def test_scene_none_degrades_to_procedural(self):
        vfx_bal = data_io.load_json(VFX_DATA_PATH)
        vfx_bal["triggers"]["enemy_attack_ranged"]["sprite_slot"] = "vfx_muzzle"
        fm = _fm(vfx_bal)
        fm.assets = _FakeAssets({"vfx_muzzle": 250})
        fm.scene = None   # never set
        fm._play("enemy_attack_ranged", 1.0, 2.0, strong=False)
        self.assertGreater(len(fm._vfx._particles), 0)


class TestTriggerTableSchema(unittest.TestCase):
    """§4 test 7. The generic walker in test_vfx.py's TestSchemaCompleteness
    only checks integer/number leaves for description+bounds (D-12) — it
    does NOT visit string-enum leaves, so it does not already cover
    triggers' descriptions; this test covers them independently rather than
    duplicating that walker."""

    def setUp(self):
        self.schema = data_io.load_json(VFX_SCHEMA_PATH)

    def test_fixture_data_validates_with_all_nine_events(self):
        doc = data_io.load_validated(VFX_DATA_PATH, VFX_SCHEMA_PATH)
        self.assertIn("triggers", doc)
        self.assertEqual(set(doc["triggers"]), set(_ALL_EVENTS))

    def test_unknown_event_key_fails(self):
        doc = data_io.load_json(VFX_DATA_PATH)
        doc["triggers"]["not_a_real_event"] = {"sprite_slot": "", "procedural": ""}
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_sprite_slot_not_in_enum_fails(self):
        doc = data_io.load_json(VFX_DATA_PATH)
        doc["triggers"]["defender_fire"]["sprite_slot"] = "not_a_real_slot"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_procedural_not_in_enum_fails(self):
        doc = data_io.load_json(VFX_DATA_PATH)
        doc["triggers"]["defender_fire"]["procedural"] = "not_a_real_kind"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, self.schema)

    def test_every_trigger_schema_node_carries_a_description(self):
        triggers = self.schema["properties"]["triggers"]
        self.assertTrue(triggers.get("description"))
        row = self.schema["$defs"]["trigger_row"]
        self.assertTrue(row.get("description"))
        for key in ("sprite_slot", "procedural"):
            self.assertTrue(row["properties"][key].get("description"))


class TestNewVfxSlotsRegistered(unittest.TestCase):
    """§4 test 8: the four new vfx_* slots resolve through
    registry.frame_size (importable) and inherit the vfx category's 64x64."""

    def test_four_new_slots_resolve_at_64x64(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = fixture_copy(tmp)
            registry = load_registry(data_dir)
        for slot in ("vfx_muzzle", "vfx_death", "vfx_slash", "vfx_crater"):
            with self.subTest(slot=slot):
                self.assertEqual(registry.frame_size(slot), (64, 64))


class TestEnginePurityCoversPlayOnce(unittest.TestCase):
    """§4 test 9: engine/vfx/*.py's glob (test_vfx.py's TestEnginePurity)
    already covers play_once.py automatically (a bare `*.py` glob, no
    subpackage) — confirmed here two ways: an independent re-scan of this
    ONE file's source text, and that test_vfx.py's file-count assertion
    (which pins the exact filename SET) was updated to include it."""

    def test_play_once_source_has_no_forbidden_imports(self):
        src = (REPO / "engine" / "vfx" / "play_once.py").read_text(
            encoding="utf-8")
        forbidden = ("open(", "import json", "from json", "import pygame",
                    "from pygame", "engine.data_io", "import game",
                    "from game", "import editor", "from editor")
        hits = [tok for tok in forbidden if tok in src]
        self.assertEqual(hits, [])

    def test_play_once_is_covered_by_the_bare_star_glob(self):
        vfx_dir = REPO / "engine" / "vfx"
        self.assertIn(vfx_dir / "play_once.py", sorted(vfx_dir.glob("*.py")))


if __name__ == "__main__":
    unittest.main()
