"""VfxAuthoringPLAN VA-2: VFX variant selection.

Three pieces under test, one per layer:

* ``engine/vfx/variants.py`` — the pure registry side (which slots are
  interchangeable, clamped indexing). Vocabulary-free by design (D5).
* ``game/vfx_variants.py`` — the mode vocabulary and the source's level.
* ``game/vfx_misc.py`` — the misc provider registry.

The load-bearing test here is ``TestSingleVariantIsAStrictNoOp``: every vfx
slot ships with exactly one variant, so if resolution drew an RNG number on
the common path it would consume from the shared global stream and desync
every downstream roll from what the game did before this feature. VA-2 is a
no-op only because that short-circuit exists.
"""
import random
import unittest
from pathlib import Path

from engine import data_io
from engine.assets.registry import SlotRegistry, load_registry
from engine.vfx import variants as engine_variants
from game import vfx_misc, vfx_variants
from tools.tests.fixture_data import FIXTURE_DATA

REPO = Path(__file__).resolve().parents[2]


def _registry_with_variants():
    """A registry whose `Muzzle` effect has three variants and whose `Hit`
    effect has one — built from a literal doc rather than the fixture, so the
    test states the shape it depends on instead of inheriting it."""
    return SlotRegistry({"categories": [{
        "key": "vfx",
        "display_name": "VFX",
        "frame_w": 64,
        "frame_h": 64,
        "animations": ["idle"],
        "groups": [{"label": "Effects", "children": [
            {"label": "Muzzle",
             "slots": ["vfx_muzzle", "vfx_muzzle_v2", "vfx_muzzle_v3"]},
            {"label": "Hit", "slots": ["vfx_hit"]},
        ]}],
    }]})


class _CountingRandom(random.Random):
    """A Random that records how many draws it served."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.draws = 0

    def randrange(self, *a, **kw):
        self.draws += 1
        return super().randrange(*a, **kw)


# ===========================================================================
# engine/vfx/variants.py — the pure registry side
# ===========================================================================
class TestVariantSlots(unittest.TestCase):
    def test_a_slot_finds_its_own_leaf_group(self):
        reg = _registry_with_variants()
        self.assertEqual(engine_variants.variant_slots(reg, "vfx_muzzle"),
                         ("vfx_muzzle", "vfx_muzzle_v2", "vfx_muzzle_v3"))

    def test_a_variant_finds_the_same_family_as_its_stem(self):
        """Resolution is by GROUP, not by stripping the `_v<k>` suffix — so
        asking from any member returns the whole family."""
        reg = _registry_with_variants()
        self.assertEqual(engine_variants.variant_slots(reg, "vfx_muzzle_v3"),
                         engine_variants.variant_slots(reg, "vfx_muzzle"))

    def test_a_lone_slot_is_its_own_one_member_family(self):
        reg = _registry_with_variants()
        self.assertEqual(engine_variants.variant_slots(reg, "vfx_hit"),
                         ("vfx_hit",))

    def test_an_unknown_slot_degrades_to_itself(self):
        """E-37: a half-renamed or un-registered slot plays its own art
        rather than raising."""
        reg = _registry_with_variants()
        self.assertEqual(engine_variants.variant_slots(reg, "vfx_nope"),
                         ("vfx_nope",))


class TestSlotAt(unittest.TestCase):
    VARIANTS = ("a", "b", "c")

    def test_index_is_clamped_at_both_ends(self):
        for index, expected in ((-5, "a"), (0, "a"), (2, "c"), (99, "c")):
            with self.subTest(index=index):
                self.assertEqual(
                    engine_variants.slot_at(self.VARIANTS, index), expected)

    def test_a_non_integer_index_reads_as_zero(self):
        for index in (None, "two", object()):
            with self.subTest(index=index):
                self.assertEqual(
                    engine_variants.slot_at(self.VARIANTS, index), "a")

    def test_no_variants_is_none(self):
        self.assertIsNone(engine_variants.slot_at((), 0))


class TestEngineSideStaysVocabularyFree(unittest.TestCase):
    """D5: the mode names live in game/, never in engine/. A future edit that
    teaches the engine what "random" means should fail here."""

    def test_no_mode_name_is_a_string_literal_in_the_engine_module(self):
        """Parsed, not grepped. A raw text sweep also matches the module
        docstring, which NAMES the three modes in order to explain that the
        engine must not branch on them — prose stating the rule is not a
        violation of it. What would be a violation is the code comparing
        against one, i.e. a real string literal, so that is what this reads."""
        import ast

        tree = ast.parse((REPO / "engine" / "vfx" / "variants.py").read_text(
            encoding="utf-8"))
        docstrings = {ast.get_docstring(n) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.FunctionDef,
                                        ast.AsyncFunctionDef, ast.ClassDef))}
        literals = {n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)
                    and n.value not in docstrings}
        for mode in vfx_variants.MODES:
            self.assertNotIn(mode, literals,
                             f"{mode!r} is game vocabulary (D5)")


# ===========================================================================
# game/vfx_variants.py — the mode vocabulary
# ===========================================================================
class TestSingleVariantIsAStrictNoOp(unittest.TestCase):
    """The guarantee that makes VA-2 land invisibly."""

    def test_a_lone_slot_resolves_to_itself_under_every_mode(self):
        reg = _registry_with_variants()
        for mode in vfx_variants.MODES:
            with self.subTest(mode=mode):
                self.assertEqual(
                    vfx_variants.resolve(reg, "vfx_hit", mode,
                                         rng=random.Random(0)),
                    "vfx_hit")

    def test_a_lone_slot_consumes_no_rng_draw(self):
        """A draw here would shift the shared global stream and change
        unrelated gameplay rolls."""
        reg = _registry_with_variants()
        rng = _CountingRandom(0)
        vfx_variants.resolve(reg, "vfx_hit", vfx_variants.RANDOM, rng=rng)
        self.assertEqual(rng.draws, 0)

    def test_a_real_family_DOES_draw(self):
        """The counter above only means something if it can go up."""
        reg = _registry_with_variants()
        rng = _CountingRandom(0)
        vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.RANDOM, rng=rng)
        self.assertEqual(rng.draws, 1)

    def test_no_registry_resolves_to_the_slot_unchanged(self):
        self.assertEqual(
            vfx_variants.resolve(None, "vfx_muzzle", vfx_variants.RANDOM),
            "vfx_muzzle")


class TestRandomMode(unittest.TestCase):
    def test_a_seeded_rng_is_deterministic(self):
        reg = _registry_with_variants()
        picks = [vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.RANDOM,
                                      rng=random.Random(7))
                 for _ in range(5)]
        self.assertEqual(len(set(picks)), 1, "same seed, same pick")

    def test_it_only_ever_picks_from_the_family(self):
        reg = _registry_with_variants()
        family = set(engine_variants.variant_slots(reg, "vfx_muzzle"))
        rng = random.Random(1)
        for _ in range(50):
            self.assertIn(
                vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.RANDOM,
                                     rng=rng),
                family)

    def test_no_rng_falls_back_to_the_first_variant(self):
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.RANDOM),
            "vfx_muzzle")


class _FakeTierState:
    def __init__(self, tier):
        self.current_tier = tier


class _FakeBuilding:
    def __init__(self, tier):
        self._tier = _FakeTierState(tier)

    def get_component(self, _cls):
        return self._tier


class _FakeEnemy:
    def __init__(self, era):
        self._enemy_era = era

    def get_component(self, _cls):
        return None


class TestLevelMode(unittest.TestCase):
    def test_a_buildings_tier_picks_the_variant(self):
        reg = _registry_with_variants()
        for tier, expected in ((0, "vfx_muzzle"), (1, "vfx_muzzle_v2"),
                               (2, "vfx_muzzle_v3")):
            with self.subTest(tier=tier):
                self.assertEqual(
                    vfx_variants.resolve(reg, "vfx_muzzle",
                                         vfx_variants.LEVEL,
                                         source=_FakeBuilding(tier)),
                    expected)

    def test_a_tier_past_the_last_variant_clamps(self):
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.LEVEL,
                                 source=_FakeBuilding(99)),
            "vfx_muzzle_v3")

    def test_an_enemys_era_picks_the_variant(self):
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.LEVEL,
                                 source=_FakeEnemy(1)),
            "vfx_muzzle_v2")

    def test_no_source_resolves_to_variant_zero(self):
        """D4: five of the ten events carry only a world point. Deliberate,
        not a bug — and deliberately NOT a random pick."""
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.LEVEL,
                                 rng=random.Random(3)),
            "vfx_muzzle")

    def test_source_level_reads_none_off_a_bare_object(self):
        self.assertIsNone(vfx_variants.source_level(None))
        self.assertIsNone(vfx_variants.source_level(object()))


class TestMiscMode(unittest.TestCase):
    def setUp(self):
        self.addCleanup(vfx_misc.clear)
        vfx_misc.clear()

    def test_an_unregistered_key_resolves_to_variant_zero(self):
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.MISC,
                                 "weather"),
            "vfx_muzzle")

    def test_a_registered_provider_picks_the_variant(self):
        reg = _registry_with_variants()
        vfx_misc.register("weather", lambda: 2)
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.MISC,
                                 "weather"),
            "vfx_muzzle_v3")

    def test_a_provider_value_past_the_last_variant_clamps(self):
        reg = _registry_with_variants()
        vfx_misc.register("weather", lambda: 99)
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", vfx_variants.MISC,
                                 "weather"),
            "vfx_muzzle_v3")

    def test_an_unknown_mode_resolves_to_variant_zero(self):
        """The schema enum is the guard; a cosmetic lever must not take down
        a frame if that guard is ever bypassed (E-37)."""
        reg = _registry_with_variants()
        self.assertEqual(
            vfx_variants.resolve(reg, "vfx_muzzle", "not_a_mode"),
            "vfx_muzzle")


class TestMiscProviderRegistry(unittest.TestCase):
    def setUp(self):
        self.addCleanup(vfx_misc.clear)
        vfx_misc.clear()

    def test_resolve_of_an_unregistered_key_is_zero(self):
        self.assertEqual(vfx_misc.resolve("nope"), 0)

    def test_resolve_of_the_shipped_empty_key_is_zero(self):
        self.assertEqual(vfx_misc.resolve(""), 0)

    def test_a_raising_provider_resolves_to_zero_and_never_propagates(self):
        def boom():
            raise RuntimeError("provider is broken")

        vfx_misc.register("boom", boom)
        self.assertEqual(vfx_misc.resolve("boom"), 0)

    def test_a_non_integer_provider_resolves_to_zero(self):
        vfx_misc.register("junk", lambda: object())
        self.assertEqual(vfx_misc.resolve("junk"), 0)

    def test_a_float_provider_truncates(self):
        vfx_misc.register("f", lambda: 2.9)
        self.assertEqual(vfx_misc.resolve("f"), 2)

    def test_registering_replaces_rather_than_stacks(self):
        vfx_misc.register("k", lambda: 1)
        vfx_misc.register("k", lambda: 5)
        self.assertEqual(vfx_misc.resolve("k"), 5)

    def test_an_empty_key_cannot_be_registered(self):
        """"" is what every trigger row ships with; letting it bind would
        turn every un-configured misc row live at once."""
        with self.assertRaises(ValueError):
            vfx_misc.register("", lambda: 1)

    def test_a_non_callable_provider_is_refused(self):
        with self.assertRaises(TypeError):
            vfx_misc.register("k", 3)

    def test_unregister_and_registered(self):
        vfx_misc.register("a", lambda: 1)
        vfx_misc.register("b", lambda: 2)
        self.assertEqual(vfx_misc.registered(), ("a", "b"))
        vfx_misc.unregister("a")
        self.assertEqual(vfx_misc.registered(), ("b",))
        vfx_misc.unregister("gone")   # a no-op, never a KeyError

    def test_nothing_is_registered_on_import(self):
        """VA-2 ships the hook, not a consumer — the modes are inert until
        gameplay code opts in."""
        self.assertEqual(vfx_misc.registered(), ())


# ===========================================================================
# the shipped data
# ===========================================================================
class TestShippedTriggerRows(unittest.TestCase):
    def setUp(self):
        # Both halves come from the PINNED snapshot, never live `data/`
        # (test_fixture_guard.py enforces this) — a designer rebinding a
        # trigger must not be able to redden the gate.
        self.doc = data_io.load_validated(
            FIXTURE_DATA / "balancing" / "vfx.json",
            FIXTURE_DATA / "schemas" / "vfx.schema.json")

    def test_every_row_carries_both_new_keys(self):
        for event, row in self.doc["triggers"].items():
            with self.subTest(event=event):
                self.assertIn(row["variant_select"]["mode"],
                              vfx_variants.MODES)
                self.assertIsInstance(row["draw_in_front"], bool)

    def test_every_row_ships_draw_in_front(self):
        """D10: the always-on-top default is what makes VA-3 a visual no-op
        until a designer unticks a box."""
        for event, row in self.doc["triggers"].items():
            with self.subTest(event=event):
                self.assertTrue(row["draw_in_front"])

    def test_no_row_ships_a_misc_key(self):
        for event, row in self.doc["triggers"].items():
            with self.subTest(event=event):
                self.assertEqual(row["variant_select"]["misc_key"], "")

    def test_every_shipped_slot_resolves_to_itself_today(self):
        """Nothing has variants yet, so every binding is its own family —
        the concrete statement of "VA-2 changes no pixels"."""
        registry = load_registry(FIXTURE_DATA)
        for event, row in self.doc["triggers"].items():
            slot = row["sprite_slot"]
            if not slot:
                continue
            with self.subTest(event=event):
                self.assertEqual(
                    vfx_variants.resolve(registry, slot,
                                         row["variant_select"]["mode"],
                                         rng=random.Random(0)),
                    slot)


if __name__ == "__main__":
    unittest.main()
