"""ESV-3a: engine.vfx emitters + the new `vfx` balancing domain.

Six tests per the phase brief (docs/briefs/phase-esv-3a-vfx-emitters.md §4):
1. Seeded parity, muzzle spray (standard + siege-strong).
2. Seeded parity, building-death shard burst.
3. D5 as a RULE over engine/vfx/ source text (not just an import graph).
4. Domain promotion: "vfx" appears in editor.domains.domains(), in
   slots.json order.
5. Schema completeness: every integer/number leaf carries description +
   minimum + maximum (D-12).
6. Default round-trip: data/balancing/vfx.json's values equal the "today"
   column this phase ported off game/ui/effects.py's old module constants.

Every test that reads data uses the pinned FIXTURE_DATA snapshot (never live
data/, TestFixturePinningPLAN) or a random.Random(seed) with values encoded
as literals — never live data/, never the deleted legacy code path.
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy


def ramp_stops(stop_0, stop_1, stop_2):
    """The `procedural.*.ramp`/`colors` JSON shape (named stop_0/1/2, not a
    bare array of arrays — see data/schemas/vfx.schema.json's $defs.ramp)."""
    return {"stop_0": stop_0, "stop_1": stop_1, "stop_2": stop_2}

from editor import domains
from engine import data_io
from engine.vfx import (
    BurstParams, GoldParams, MuzzleParams, ShardBurstParams, SlashParams,
    SplatterParams, VfxParams, VfxSystem,
)

VFX_DATA_PATH = FIXTURE_DATA / "balancing" / "vfx.json"
VFX_SCHEMA_PATH = FIXTURE_DATA / "schemas" / "vfx.schema.json"

# -- the "today" column (docs/briefs/phase-esv-3a-vfx-emitters.md §1.3) -----
# Every value here is cited to game/ui/effects.py's pre-ESV-3a module
# constants; data/balancing/vfx.json's content MUST equal these exactly
# (test 6) and they build the params used to pin the seeded draws (1, 2).

MUZZLE = MuzzleParams(
    life=0.20, life_strong=0.32, count=8, count_strong=13,
    gravity=0.0, ramp=((255, 230, 120), (220, 90, 50), (130, 30, 20)),
    smoke_color=(100, 80, 80), smoke_chance=0.25,
    vx_min=-90.0, vx_max=-30.0, vy_min=-35.0, vy_max=35.0,
    size_w=2, size_h=2)

DEATH_BURST = ShardBurstParams(
    life=0.65, count=14, gravity=60.0,
    colors=((150, 90, 200), (120, 70, 170), (180, 120, 230)),
    vx_min=-45.0, vx_max=45.0, vy_min=-80.0, vy_max=-10.0,
    size_w_min=2, size_w_max=4, size_h_min=2, size_h_max=5)

SPARK_PRESETS = {
    "place": BurstParams(life=0.75, count=10, gravity=55.0,
                          ramp=((255, 230, 80), (255, 150, 40), (210, 60, 30)),
                          vx_min=-28.0, vx_max=28.0, vy_min=-70.0, vy_max=-20.0,
                          size_w=2, size_h=2),
    "level1": BurstParams(life=0.55, count=7, gravity=55.0,
                           ramp=((255, 230, 80), (255, 150, 40), (210, 60, 30)),
                           vx_min=-28.0, vx_max=28.0, vy_min=-70.0, vy_max=-20.0,
                           size_w=2, size_h=2),
    "level2": BurstParams(life=0.88, count=16, gravity=55.0,
                           ramp=((255, 230, 80), (255, 150, 40), (210, 60, 30)),
                           vx_min=-28.0, vx_max=28.0, vy_min=-70.0, vy_max=-20.0,
                           size_w=2, size_h=2),
    "tier": BurstParams(life=1.20, count=26, gravity=55.0,
                         ramp=((255, 230, 80), (255, 150, 40), (210, 60, 30)),
                         vx_min=-28.0, vx_max=28.0, vy_min=-70.0, vy_max=-20.0,
                         size_w=2, size_h=2),
}

SLASH = SlashParams(
    life=0.28, colors=((220, 230, 255), (200, 215, 245), (255, 255, 255)),
    lines_min=2, lines_max=3, ox_min=-6.0, ox_max=6.0, oy_min=-10.0, oy_max=2.0,
    size=7, size_large=11)

GOLD = GoldParams(
    life=1.20, fade_in=0.15, hold=0.35,
    fill_color=(255, 215, 0), border_color=(255, 240, 80),
    fill_alpha=90, border_width=2)

SPLATTER = SplatterParams(color=(180, 30, 30), alpha=170, radius_px=4.0,
                          jitter=0.6)

VFX_PARAMS = VfxParams(death_burst=DEATH_BURST, muzzle=MUZZLE, slash=SLASH,
                       gold=GOLD, splatter=SPLATTER)


def make_system(seed):
    return VfxSystem(VFX_PARAMS, rng=random.Random(seed))


class TestMuzzleSeededParity(unittest.TestCase):
    """Draw order per particle (brief §2.4): random() [smoke roll] FIRST,
    then uniform(vx), uniform(vy) — 3 calls, matching effects.py:362-368
    verbatim. Values below are `random.Random(12345)` run through that exact
    sequence, encoded as literals (not by calling any deleted code path)."""

    SEED = 12345

    # (smoke, vx, vy) per particle, standard (count=8) and strong (count=13),
    # each from its OWN fresh random.Random(SEED) — i.e. one seeded stream
    # per emit_muzzle call, matching how a single attack event draws.
    STANDARD = [
        (False, -89.3898498325759, 22.76445564776202),
        (False, -67.89529863069146, -21.443705566844802),
        (False, -80.2987305642379, -26.30131810015289),
        (False, -56.27529071544942, -22.795950749338772),
        (False, -68.70591681980407, 32.0645349569684),
        (True, -31.281600265775396, -6.151642494248929),
        (False, -81.11122986418864, 15.327699821061955),
        (True, -69.50637445358687, -33.353514730045966),
    ]
    STRONG = STANDARD + [
        (False, -31.951052467207717, 33.51589179299597),
        (False, -89.79272335469426, 30.816695216841993),
        (False, -43.74993968899135, -22.47883647635394),
        (True, -65.12805188928854, 26.987552700183564),
        (False, -45.805067103355064, -18.716522774011462),
    ]

    def test_standard_count_life_and_draw_order(self):
        system = make_system(self.SEED)
        system.emit_muzzle(1.0, 2.0, strong=False)
        particles = system._particles
        self.assertEqual(len(particles), MUZZLE.count)
        for p, (smoke, vx, vy) in zip(particles, self.STANDARD):
            self.assertAlmostEqual(p.vx, vx)
            self.assertAlmostEqual(p.vy, vy)
            self.assertEqual(p.life, MUZZLE.life)
            self.assertEqual(p.gravity, MUZZLE.gravity)
            self.assertEqual(p.size, (MUZZLE.size_w, MUZZLE.size_h))
            expected_ramp = (MUZZLE.smoke_color,) if smoke else MUZZLE.ramp
            self.assertEqual(p.ramp, expected_ramp)

    def test_strong_count_life_and_draw_order(self):
        system = make_system(self.SEED)
        system.emit_muzzle(1.0, 2.0, strong=True)
        particles = system._particles
        self.assertEqual(len(particles), MUZZLE.count_strong)
        for p, (smoke, vx, vy) in zip(particles, self.STRONG):
            self.assertAlmostEqual(p.vx, vx)
            self.assertAlmostEqual(p.vy, vy)
            self.assertEqual(p.life, MUZZLE.life_strong)
            expected_ramp = (MUZZLE.smoke_color,) if smoke else MUZZLE.ramp
            self.assertEqual(p.ramp, expected_ramp)


class TestDeathBurstSeededParity(unittest.TestCase):
    """Draw order per shard (brief §2.4): uniform(vx), uniform(vy),
    choice(colors), randint(size_w), randint(size_h) — 5 calls, matching
    effects.py:320-323 verbatim. The strictest pin: each shard's ramp is a
    1-tuple of its OWN picked colour (never a 3-stop age ramp like a
    spark)."""

    SEED = 999
    SHARDS = [
        (25.321219646132676, -74.39540697074099, (180, 120, 230), 4, 5),
        (-1.4953300961375149, -18.52639477024624, (180, 120, 230), 3, 2),
        (13.09913836042503, -21.37030092507446, (150, 90, 200), 3, 2),
        (18.18918772151475, -62.24064858359317, (150, 90, 200), 4, 5),
        (-38.26237459270845, -78.35457475999544, (150, 90, 200), 4, 3),
        (-28.23272765908542, -32.747268727784196, (150, 90, 200), 2, 5),
        (35.533457567298484, -14.38485829448426, (120, 70, 170), 2, 5),
        (-3.154453476355414, -27.582897813210124, (150, 90, 200), 2, 3),
        (-8.639381292737916, -17.374659633741857, (180, 120, 230), 3, 2),
        (37.04288549405301, -68.49800868516087, (150, 90, 200), 3, 3),
        (-26.144457381271348, -72.85462159147393, (150, 90, 200), 2, 2),
        (1.6183226287964558, -60.27419380598131, (150, 90, 200), 3, 4),
        (32.34479771572323, -17.487129964200513, (150, 90, 200), 3, 2),
        (24.277835443273034, -40.216140250705934, (180, 120, 230), 2, 4),
    ]

    def test_count_life_gravity_and_1tuple_ramp(self):
        system = make_system(self.SEED)
        system.emit_shards(3.0, 4.0)
        particles = system._particles
        self.assertEqual(len(particles), DEATH_BURST.count)
        for p, (vx, vy, color, sw, sh) in zip(particles, self.SHARDS):
            self.assertAlmostEqual(p.vx, vx)
            self.assertAlmostEqual(p.vy, vy)
            self.assertEqual(p.life, DEATH_BURST.life)
            self.assertEqual(p.gravity, DEATH_BURST.gravity)
            self.assertEqual(p.ramp, (color,))   # 1-tuple, NOT a 3-stop ramp
            self.assertEqual(p.size, (sw, sh))


class TestEnginePurity(unittest.TestCase):
    """D5 as a RULE over engine/vfx/'s SOURCE TEXT, not an import smoke test
    (brief §4 test 3): the emitters take injected params, full stop. A future
    convenience `load_defaults()` helper pulling in a balancing loader would
    pass an import-graph-only check (the package "already depends on" it
    transitively) — this scans the literal text instead."""

    FORBIDDEN = (
        "open(",
        "import json",
        "from json",
        "import pygame",
        "from pygame",
        "engine.data_io",
        "import game",
        "from game",
        "import editor",
        "from editor",
    )

    def test_no_data_io_pygame_or_game_editor_imports(self):
        offenders = {}
        for path in sorted((REPO / "engine" / "vfx").glob("*.py")):
            src = path.read_text(encoding="utf-8")
            hits = [tok for tok in self.FORBIDDEN if tok in src]
            if hits:
                offenders[path.name] = hits
        self.assertEqual(offenders, {}, f"engine/vfx purity violation: {offenders}")


class TestDomainPromotion(unittest.TestCase):
    """`vfx` appears exactly once in editor.domains.domains(), in slots.json
    order — against a TEMP COPY of the pinned fixture, never live data/. The
    expected POSITION is confirmed directly against data/slots.json's
    categories[] order (buildings, enemies, map, ui, core, vfx, deco,
    backgrounds), not inferred from any test this phase invalidates."""

    def test_vfx_is_a_domain_in_slots_order(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = fixture_copy(tmp)
            result = domains.domains(data_dir)
        self.assertEqual(result.count("vfx"), 1)
        self.assertEqual(
            result,
            ("buildings", "enemies", "map", "ui", "core", "vfx"))


class TestSchemaCompleteness(unittest.TestCase):
    """D-12: every integer/number leaf in vfx.schema.json carries a
    description, minimum and maximum — the cheap generic guard that keeps
    ESV-3b/ESV-5's future keys honest."""

    def _leaves(self, schema, node=None, path=()):
        if node is None:
            node = schema
        if "$ref" in node:
            ref = node["$ref"].removeprefix("#/$defs/")
            node = schema["$defs"][ref]
        if node.get("type") == "object":
            for key, prop in node.get("properties", {}).items():
                yield from self._leaves(schema, prop, path + (key,))
        elif node.get("type") == "array":
            yield from self._leaves(schema, node["items"], path + ("<items>",))
        else:
            yield path, node

    def test_every_numeric_leaf_has_description_and_bounds(self):
        schema = data_io.load_json(VFX_SCHEMA_PATH)
        count = 0
        for path, node in self._leaves(schema):
            if node.get("type") in ("integer", "number"):
                with self.subTest(path="/".join(path)):
                    self.assertTrue(node.get("description"))
                    self.assertIn("minimum", node)
                    self.assertIn("maximum", node)
                count += 1
        self.assertGreater(count, 0)


class TestDefaultRoundTrip(unittest.TestCase):
    """data/balancing/vfx.json's values equal the "today" column exactly —
    the byte-identity contract in test form (brief §1.3)."""

    def setUp(self):
        self.data = data_io.load_validated(VFX_DATA_PATH, VFX_SCHEMA_PATH)

    def test_spark(self):
        spark = self.data["procedural"]["spark"]
        presets = spark["presets"]
        self.assertEqual(presets["place"], {"life": 0.75, "count": 10})
        self.assertEqual(presets["level1"], {"life": 0.55, "count": 7})
        self.assertEqual(presets["level2"], {"life": 0.88, "count": 16})
        self.assertEqual(presets["tier"], {"life": 1.20, "count": 26})
        self.assertEqual(spark["gravity"], 55.0)
        self.assertEqual(spark["ramp"],
                         ramp_stops([255, 230, 80], [255, 150, 40], [210, 60, 30]))
        self.assertEqual((spark["vx_min"], spark["vx_max"]), (-28.0, 28.0))
        self.assertEqual((spark["vy_min"], spark["vy_max"]), (-70.0, -20.0))
        self.assertEqual((spark["size_w"], spark["size_h"]), (2, 2))

    def test_death_burst(self):
        d = self.data["procedural"]["death_burst"]
        self.assertEqual(d["life"], 0.65)
        self.assertEqual(d["count"], 14)
        self.assertEqual(d["gravity"], 60.0)
        self.assertEqual(d["colors"],
                         ramp_stops([150, 90, 200], [120, 70, 170], [180, 120, 230]))
        self.assertEqual((d["vx_min"], d["vx_max"]), (-45.0, 45.0))
        self.assertEqual((d["vy_min"], d["vy_max"]), (-80.0, -10.0))
        self.assertEqual((d["size_w_min"], d["size_w_max"]), (2, 4))
        self.assertEqual((d["size_h_min"], d["size_h_max"]), (2, 5))

    def test_muzzle(self):
        m = self.data["procedural"]["muzzle"]
        self.assertEqual((m["life"], m["life_strong"]), (0.20, 0.32))
        self.assertEqual((m["count"], m["count_strong"]), (8, 13))
        self.assertEqual(m["ramp"],
                         ramp_stops([255, 230, 120], [220, 90, 50], [130, 30, 20]))
        self.assertEqual(m["smoke_color"], [100, 80, 80])
        self.assertEqual(m["smoke_chance"], 0.25)
        self.assertEqual((m["vx_min"], m["vx_max"]), (-90.0, -30.0))
        self.assertEqual((m["vy_min"], m["vy_max"]), (-35.0, 35.0))
        self.assertEqual(m["gravity"], 0.0)
        self.assertEqual((m["size_w"], m["size_h"]), (2, 2))

    def test_slash(self):
        s = self.data["procedural"]["slash"]
        self.assertEqual(s["life"], 0.28)
        self.assertEqual(s["colors"],
                         ramp_stops([220, 230, 255], [200, 215, 245], [255, 255, 255]))
        self.assertEqual((s["lines_min"], s["lines_max"]), (2, 3))
        self.assertEqual((s["ox_min"], s["ox_max"]), (-6.0, 6.0))
        self.assertEqual((s["oy_min"], s["oy_max"]), (-10.0, 2.0))
        self.assertEqual((s["size_large"], s["size"]), (11, 7))

    def test_gold_highlight(self):
        g = self.data["procedural"]["gold_highlight"]
        self.assertEqual(g["life"], 1.20)
        self.assertEqual((g["fade_in"], g["hold"]), (0.15, 0.35))
        self.assertEqual(g["fill_color"], [255, 215, 0])
        self.assertEqual(g["border_color"], [255, 240, 80])
        self.assertEqual(g["fill_alpha"], 90)
        self.assertEqual(g["border_width"], 2)

    def test_splatter(self):
        sp = self.data["procedural"]["splatter"]
        self.assertEqual(sp["color"], [180, 30, 30])
        self.assertEqual(sp["alpha"], 170)
        self.assertEqual(sp["radius_px"], 4.0)
        self.assertEqual(sp["jitter"], 0.6)

    def test_floaters(self):
        f = self.data["procedural"]["floaters"]
        self.assertEqual(f["upkeep_color"], [120, 170, 230])
        self.assertEqual(f["xp_color"], [202, 140, 245])
        self.assertEqual(f["xp_life"], 0.9)
        self.assertEqual(f["painter_finished_color"], [255, 255, 100])
        self.assertEqual(f["painter_lost_color"], [255, 100, 100])
        self.assertEqual(f["painter_life"], 1.5)
        self.assertEqual(f["boost_color"], [255, 255, 255])


if __name__ == "__main__":
    unittest.main()
