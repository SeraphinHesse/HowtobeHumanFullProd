"""ESV-3a: engine.vfx emitters + the new `vfx` balancing domain.
ESV-3b adds the scene-object / continuous VFX (beam / crater / lightning /
announce) — see the second module docstring paragraph below.

Six tests per the ESV-3a phase brief
(docs/briefs/phase-esv-3a-vfx-emitters.md §4):
1. Seeded parity, muzzle spray (standard + siege-strong).
2. Seeded parity, building-death shard burst.
3. D5 as a RULE over engine/vfx/ source text (not just an import graph).
4. Domain promotion: "vfx" appears in editor.domains.domains(), in
   slots.json order.
5. Schema completeness: every integer/number leaf carries description +
   minimum + maximum (D-12).
6. Default round-trip: data/balancing/vfx.json's values equal the "today"
   column this phase ported off game/ui/effects.py's old module constants.

Nine more per the ESV-3b phase brief
(docs/briefs/phase-esv-3b-scene-vfx.md §4), appended at the bottom of this
file (extending this module is explicitly sanctioned over a sibling module):
1. Seeded parity, lightning bolt (draw order + count + endpoints + re-roll).
2. Seeded parity, bolt colour fade (zero RNG).
3. Beam parity (tier clamp + width, zero RNG).
4. Crater + lightning-marker alpha parity (zero RNG).
5. Announce parity (zero RNG).
6. Crater/lightning lifetime round-trip (threaded, not the module constant)
   + the D4 negative guard (AOE_TRAVEL_TIME/BEAM_MIN_TICK stay simulation
   timing, never in vfx.json).
7. Purity scan file-count guard (no module can slip past the glob).
8. Schema completeness — confirmed already covered by the generic walker.
9. Default round-trip for beam/crater/lightning/announce.

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
    AnnounceParams, BeamParams, BurstParams, CraterParams, DrummerAuraParams,
    FloaterParams, GoldParams, LightningParams, MuzzleParams,
    ProjectileParams, ShardBurstParams, SlashParams, SplatterParams,
    VfxParams, VfxSystem,
)
# The ONE place a vfx.json key name meets an engine.vfx dataclass field
# (game/ui/CLAUDE.md) — imported so the round-trip tests below check the real
# production mapping rather than re-implementing it.
from game.ui.effects import _params_from_balance

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

# -- ESV-3b "today" column (docs/briefs/phase-esv-3b-scene-vfx.md §1.2) -----
BEAM = BeamParams(colors=((255, 200, 40), (255, 110, 15), (210, 20, 10)),
                  width_base=2, origin_lift_tiles=1.0)

CRATER = CraterParams(color=(120, 78, 66), alpha=150, life=1.0, segments=12)

LIGHTNING = LightningParams(
    bolt_segments=8, bolt_jitter_px=6,
    bolt_color_start=(255, 255, 255), bolt_color_end=(255, 240, 80),
    bolt_width=2, bolt_life=0.5,
    flash_radius_px=20.0, flash_color=(255, 250, 200), flash_alpha=200,
    marker_color=(255, 240, 120), marker_fill_alpha=120,
    marker_outline_width=2, marker_life=1.0, marker_segments=12)

ANNOUNCE = AnnounceParams(color=(220, 40, 40), max_alpha=255)

# -- ESV-6 "today" column (docs/briefs/phase-esv-6-converge.md §1.4) --------
FLOATERS = FloaterParams(
    upkeep_color=(120, 170, 230), xp_color=(202, 140, 245), xp_life=0.9,
    painter_finished_color=(255, 255, 100), painter_lost_color=(255, 100, 100),
    painter_life=1.5, boost_color=(255, 255, 255))

# -- fix-anchor-offset-and-bullet-sprites "today" column (Fix 2 §2.2) -------
PROJECTILE = ProjectileParams(
    stone_color=(185, 180, 170), shell_color=(70, 60, 55),
    stone_size=3, shell_size=5, lift_frac=0.6)

# -- Drummer buff-range telegraph "today" column -----------------------------
DRUMMER_AURA = DrummerAuraParams(
    color=(90, 200, 220), alpha_min=30, alpha_max=150,
    pulse_period_s=0.5, segments=16)

VFX_PARAMS = VfxParams(death_burst=DEATH_BURST, muzzle=MUZZLE, slash=SLASH,
                       gold=GOLD, splatter=SPLATTER, beam=BEAM, crater=CRATER,
                       lightning=LIGHTNING, announce=ANNOUNCE,
                       floaters=FLOATERS, projectile=PROJECTILE,
                       drummer_aura=DRUMMER_AURA)


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

    def test_scanned_file_count_matches_the_package_no_subpackage_slips_past(self):
        """ESV-3b §2.4: ESV-3b added no new engine/vfx module (only appended
        to params.py/__init__.py — see engine/vfx/params.py's/module
        docstring), so the existing `*.py` glob already covers it. This locks
        that down: if a future phase adds a subpackage (a directory, which
        `*.py` cannot see), the scanned count silently dropping below the
        real module count is the tripwire — widen the glob to `**/*.py` when
        it fires.

        ESV-5 DID add a new module (play_once.py) — a flat file, so the bare
        glob picked it up automatically with zero test change to the glob
        itself; only this hardcoded expected-filename SET needed updating,
        which is exactly the tripwire this test exists to force.
        VfxAuthoringPLAN VA-2 added variants.py the same way, and this pin
        fired the same way."""
        vfx_dir = REPO / "engine" / "vfx"
        scanned = sorted((vfx_dir).glob("*.py"))
        actual = sorted(p for p in vfx_dir.rglob("*.py"))
        self.assertEqual(scanned, actual)
        self.assertEqual({p.name for p in scanned},
                         {"__init__.py", "emitters.py", "params.py",
                          "particle.py", "play_once.py", "system.py",
                          "variants.py"})


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

    # -- ESV-3b: beam / crater / lightning / announce (brief §4 test 9) ----

    def test_beam(self):
        b = self.data["procedural"]["beam"]
        self.assertEqual(b["colors"],
                         ramp_stops([255, 200, 40], [255, 110, 15], [210, 20, 10]))
        self.assertEqual(b["width_base"], 2)
        self.assertEqual(b["origin_lift_tiles"], 1.0)

    def test_crater(self):
        """A real ROUND TRIP: every authored key reaches `CraterParams`
        unchanged.

        This used to restate the four magnitudes as literals. That was the
        migration-era contract (brief §1.3: "the values did not change when
        they moved from Python into JSON") and it expired the moment the
        block became a designer lever — `life` was retuned to 0.0 and the
        test went red for balancing doing exactly what balancing is for.
        What still has to hold, and what is asserted now, is that the value
        the ENGINE reads is the value the designer authored."""
        c = self.data["procedural"]["crater"]
        params = _params_from_balance(self.data)[1].crater
        self.assertEqual(list(params.color), list(c["color"]))
        self.assertEqual(params.alpha, c["alpha"])
        self.assertEqual(params.life, c["life"])
        self.assertEqual(params.segments, c["segments"])

    def test_lightning(self):
        lp = self.data["procedural"]["lightning"]
        self.assertEqual(lp["bolt_segments"], 8)
        self.assertEqual(lp["bolt_jitter_px"], 6)
        self.assertEqual(lp["bolt_color_start"], [255, 255, 255])
        self.assertEqual(lp["bolt_color_end"], [255, 240, 80])
        self.assertEqual(lp["bolt_width"], 2)
        self.assertEqual(lp["bolt_life"], 0.5)
        self.assertEqual(lp["flash_radius_px"], 20.0)
        self.assertEqual(lp["flash_color"], [255, 250, 200])
        self.assertEqual(lp["flash_alpha"], 200)
        self.assertEqual(lp["marker_color"], [255, 240, 120])
        self.assertEqual(lp["marker_fill_alpha"], 120)
        self.assertEqual(lp["marker_outline_width"], 2)
        self.assertEqual(lp["marker_life"], 1.0)
        self.assertEqual(lp["marker_segments"], 12)

    def test_announce(self):
        a = self.data["procedural"]["announce"]
        self.assertEqual(a["color"], [220, 40, 40])
        self.assertEqual(a["max_alpha"], 255)

    # -- fix-anchor-offset-and-bullet-sprites Fix 2 (brief §4 test 10) -----

    def test_projectile(self):
        """A real ROUND TRIP — see `test_crater` for why these stopped being
        literals (`stone_size` was retuned 3 -> 32)."""
        p = self.data["procedural"]["projectile"]
        params = _params_from_balance(self.data)[1].projectile
        self.assertEqual(list(params.stone_color), list(p["stone_color"]))
        self.assertEqual(list(params.shell_color), list(p["shell_color"]))
        self.assertEqual(params.stone_size, p["stone_size"])
        self.assertEqual(params.shell_size, p["shell_size"])
        self.assertEqual(params.lift_frac, p["lift_frac"])

    # -- Drummer buff-range telegraph -----------------------------------

    def test_drummer_aura(self):
        da = self.data["procedural"]["drummer_aura"]
        self.assertEqual(da["color"], [90, 200, 220])
        self.assertEqual(da["alpha_min"], 30)
        self.assertEqual(da["alpha_max"], 150)
        self.assertEqual(da["pulse_period_s"], 0.5)
        self.assertEqual(da["segments"], 16)


# ===========================================================================
# ESV-3b: scene-object / continuous VFX (beam / crater / lightning / announce)
# docs/briefs/phase-esv-3b-scene-vfx.md §4. submit_beams/submit_craters/
# submit_lightning/submit_announce stay in game/ui/effects.py (they read
# scene.by_tag(...) and building components — game vocabulary the engine must
# not learn, ESV-3b brief §2.1) — these tests exercise that PRODUCTION code
# through a FloaterManager whose ``_vfx_params`` is swapped for the literal
# bundle above, so the assertions pin against independently stated literals,
# never against data/balancing/vfx.json (TestDefaultRoundTrip above closes
# that loop separately).
# ===========================================================================
from engine.core import GameObject, Scene, Transform
from engine.coords import Camera, CoordinateSystem, Geometry
from game.buildings.components import BeamAttacker, TierState
from game.core.balance import load_balance
from game.core.lightning import (
    BOLT_LIFE, MARKER_LIFE, LightningFX, LightningFXFade,
)
from game.enemies.combat import (
    AOE_TRAVEL_TIME, BEAM_MIN_TICK, CRATER_LIFE, Crater, CraterFade,
)
from game.ui.effects import FloaterManager


class _TagScene:
    """The minimal ``scene.by_tag(tag)`` surface submit_beams/submit_craters/
    submit_lightning actually read — no TileMap/TileOccupancy/spawn-queue
    machinery needed to exercise a pure draw function."""

    def __init__(self, objects):
        self._objects = list(objects)

    def by_tag(self, tag):
        return [o for o in self._objects if tag in o.tags]


class _AliveObj(GameObject):
    """A GameObject that reads as alive (E-11 forbids a bare public
    ``.alive`` attribute — override it as a property instead)."""

    @property
    def alive(self):
        return True


class FakeRenderer:
    """Records every submit_* call instead of drawing — the same role a
    fake backend plays anywhere else in this suite."""

    def __init__(self):
        self.hud = []
        self.overlay_polys = []
        self.overlay_lines = []

    def submit_hud(self, item):
        self.hud.append(item)

    def submit_overlay_polys(self, points, color):
        self.overlay_polys.append((tuple(points), color))

    def submit_overlay_lines(self, points, color, width=1, closed=False):
        self.overlay_lines.append((tuple(points), color, width, closed))


def make_floater_manager():
    """A real ``FloaterManager`` (needs valid ui_balance/core_balance/
    vfx_balance shapes to construct) with ``_vfx_params`` immediately swapped
    for the literal ``VFX_PARAMS`` bundle above — so every assertion below is
    pinned against the literals, never against the fixture JSON just used to
    satisfy the constructor's shape."""
    ui_bal = load_balance(FIXTURE_DATA, "ui")
    core_bal = load_balance(FIXTURE_DATA, "core")
    vfx_bal = data_io.load_json(VFX_DATA_PATH)
    fm = FloaterManager(ui_bal, core_bal, vfx_bal)
    fm._vfx_params = VFX_PARAMS
    return fm


def make_cs():
    """Zoom is pinned EXPLICITLY, never inherited from `Camera`'s dataclass
    default: that default is a live tunable (it moved 1.0 -> 2.0 with the
    camera-zoom balancing change) and every EXPECTED_* point list below is a
    hand-computed screen coordinate, so a default drift would silently double
    them all."""
    return CoordinateSystem(
        Geometry(tile_w=64, tile_h=32, map_cols=8, map_rows=8,
                 zoom_levels=(1.0,)),
        Camera(zoom=1.0))


class TestLightningBoltSeededParity(unittest.TestCase):
    """Draw order per §2.2: for i in range(bolt_segments + 1) — i=0 and
    i=bolt_segments (the endpoints) draw NOTHING; i=1..bolt_segments-1 each
    draw exactly one uniform(-jitter, +jitter). At the default 8 segments
    that is exactly 7 draws, ascending i order. The RNG is consumed at
    SUBMIT time, not emit time: a second submit of the SAME FX object
    re-rolls (the shimmer IS the effect) — pinned below by asserting the two
    point lists differ while the endpoints stay identical.

    Points independently computed by replaying the exact algorithm with
    random.Random(42) against cs.world_to_screen(2.0, 3.0) = (-32.0, 80.0)
    on a 64x32 tile_w/tile_h CoordinateSystem — not by calling
    submit_lightning and trusting it."""

    SEED = 42
    EXPECTED_FIRST = [(-32, 0), (-30, 10), (-37, 20), (-34, 30), (-35, 40),
                      (-29, 50), (-29, 60), (-27, 70), (-32, 80)]
    EXPECTED_SECOND = [(-32, 0), (-36, 10), (-32, 20), (-37, 30), (-35, 40),
                       (-31, 50), (-37, 60), (-35, 70), (-32, 80)]

    def _fx(self):
        fx = LightningFX(2.0, 3.0, 1.5, LIGHTNING.bolt_life,
                          LIGHTNING.marker_life)
        return fx

    def test_draw_order_count_and_unjittered_endpoints(self):
        fm = make_floater_manager()
        fm._rng = random.Random(self.SEED)
        cs = make_cs()
        fx = self._fx()   # age 0.0 -> bolt_frac == 1.0
        scene = _TagScene([fx])
        renderer = FakeRenderer()

        fm.submit_lightning(renderer, cs, scene)

        bolt_lines = [item for item in renderer.hud
                     if len(item.points) == LIGHTNING.bolt_segments + 1]
        self.assertEqual(len(bolt_lines), 1)
        pts = list(bolt_lines[0].points)
        self.assertEqual(pts, self.EXPECTED_FIRST)
        # endpoints exact, un-jittered
        self.assertEqual(pts[0][0], int(-32.0))
        self.assertEqual(pts[-1][0], int(-32.0))

    def test_second_submit_rerolls_the_shimmer(self):
        fm = make_floater_manager()
        fm._rng = random.Random(self.SEED)
        cs = make_cs()
        fx = self._fx()
        scene = _TagScene([fx])
        renderer = FakeRenderer()

        fm.submit_lightning(renderer, cs, scene)   # 1st submit consumes 7
        fm.submit_lightning(renderer, cs, scene)   # 2nd submit, same fx

        first_pts = list(renderer.hud[0].points)
        second_hud = [item for item in renderer.hud
                     if len(item.points) == LIGHTNING.bolt_segments + 1]
        second_pts = list(second_hud[1].points)
        self.assertEqual(first_pts, self.EXPECTED_FIRST)
        self.assertEqual(second_pts, self.EXPECTED_SECOND)
        self.assertNotEqual(first_pts, second_pts)          # re-rolled
        self.assertEqual(first_pts[0], second_pts[0])        # endpoints fixed
        self.assertEqual(first_pts[-1], second_pts[-1])


class TestLightningColourFade(unittest.TestCase):
    """int((start + (end - start) * (1 - bolt)) * bolt) per channel — zero
    RNG draws. At bolt=1.0/0.5 the formula is exercised THROUGH
    submit_lightning's real output (both > 0, so the bolt is actually
    drawn); at bolt=0.0 submit_lightning draws NOTHING at all (the `if bolt
    > 0` gate), so that data point is the same arithmetic expression
    evaluated directly — independently computed, not re-derived from the
    function under test."""

    def test_bolt_1_0_is_the_start_colour(self):
        fm = make_floater_manager()
        fm._rng = random.Random(1)
        cs = make_cs()
        fx = LightningFX(2.0, 3.0, 1.5, LIGHTNING.bolt_life,
                         LIGHTNING.marker_life)   # age 0.0 -> bolt_frac 1.0
        renderer = FakeRenderer()
        fm.submit_lightning(renderer, cs, _TagScene([fx]))
        bolt_lines = [i for i in renderer.hud
                     if len(i.points) == LIGHTNING.bolt_segments + 1]
        self.assertEqual(bolt_lines[0].color, (255, 255, 255))

    def test_bolt_0_5_is_the_hand_computed_midpoint(self):
        fm = make_floater_manager()
        fm._rng = random.Random(1)
        cs = make_cs()
        fx = LightningFX(2.0, 3.0, 1.5, LIGHTNING.bolt_life,
                         LIGHTNING.marker_life)
        fx.get_component(LightningFXFade).age = LIGHTNING.bolt_life / 2
        renderer = FakeRenderer()
        fm.submit_lightning(renderer, cs, _TagScene([fx]))
        bolt_lines = [i for i in renderer.hud
                     if len(i.points) == LIGHTNING.bolt_segments + 1]
        # int((255+(255-255)*0.5)*0.5, int((255+(240-255)*0.5)*0.5), int((255+(80-255)*0.5)*0.5))
        self.assertEqual(bolt_lines[0].color, (127, 123, 83))

    def test_bolt_0_0_is_the_zero_limit_no_line_drawn(self):
        # bolt_frac == 0.0 at age == bolt_life: submit_lightning's `if bolt >
        # 0` gate means NO bolt HudLines is submitted at all.
        fm = make_floater_manager()
        fm._rng = random.Random(1)
        cs = make_cs()
        fx = LightningFX(2.0, 3.0, 1.5, LIGHTNING.bolt_life,
                         LIGHTNING.marker_life)
        fx.get_component(LightningFXFade).age = LIGHTNING.bolt_life
        renderer = FakeRenderer()
        fm.submit_lightning(renderer, cs, _TagScene([fx]))
        bolt_lines = [i for i in renderer.hud
                     if len(i.points) == LIGHTNING.bolt_segments + 1]
        self.assertEqual(bolt_lines, [])
        # the formula's algebraic limit, independently computed (not by
        # calling submit_lightning, which never evaluates it at bolt=0):
        progress = 1.0 - 0.0
        limit = tuple(int((s + (e - s) * progress) * 0.0)
                     for s, e in zip(LIGHTNING.bolt_color_start,
                                     LIGHTNING.bolt_color_end))
        self.assertEqual(limit, (0, 0, 0))


class TestBeamParity(unittest.TestCase):
    """submit_beams: colour = colors[clamp(tier, 2)], width = width_base +
    tier. **verified**: submit_beams's body (game/ui/effects.py) calls no
    rng method anywhere — zero random draws."""

    def _beam_building(self, tier):
        building = GameObject(
            tags=("combat",), transform=Transform(wx=1.0, wy=1.0),
            components=[BeamAttacker(), TierState(current_tier=tier)])
        return building

    def test_tier_clamp_and_width(self):
        fm = make_floater_manager()
        cs = make_cs()
        target = _AliveObj(transform=Transform(wx=3.0, wy=1.0))
        cases = [(0, BEAM.colors[0], 2), (1, BEAM.colors[1], 3),
                 (2, BEAM.colors[2], 4), (3, BEAM.colors[2], 5)]  # 3 clamps
        for tier, expected_color, expected_width in cases:
            with self.subTest(tier=tier):
                building = self._beam_building(tier)
                building.get_component(BeamAttacker)._target = target
                renderer = FakeRenderer()
                fm.submit_beams(renderer, cs, _TagScene([building]))
                self.assertEqual(len(renderer.hud), 1)
                self.assertEqual(renderer.hud[0].color, expected_color)
                self.assertEqual(renderer.hud[0].width, expected_width)

    def test_no_beam_when_target_not_alive(self):
        fm = make_floater_manager()
        cs = make_cs()
        building = self._beam_building(0)
        # no _target set at all -> getattr(..., None) -> skipped
        renderer = FakeRenderer()
        fm.submit_beams(renderer, cs, _TagScene([building]))
        self.assertEqual(renderer.hud, [])


class TestCraterAndMarkerAlphaParity(unittest.TestCase):
    """Crater fill alpha + lightning ground-marker fill alpha both scale
    linearly with their fade fraction. Zero RNG draws (**verified**: neither
    submit_craters nor the marker-drawing tail of submit_lightning calls any
    rng method)."""

    def test_crater_alpha_at_1_0_0_5_0_0(self):
        fm = make_floater_manager()
        cs = make_cs()
        for frac, expected_alpha in ((1.0, 150), (0.5, 75), (0.0, 0)):
            with self.subTest(frac=frac):
                crater = Crater(2.0, 2.0, 0.8, CRATER.life)
                cf = crater.get_component(CraterFade)
                cf.age = cf.life * (1.0 - frac)
                renderer = FakeRenderer()
                fm.submit_craters(renderer, cs, _TagScene([crater]))
                self.assertEqual(len(renderer.overlay_polys), 1)
                _, color = renderer.overlay_polys[0]
                self.assertEqual(color, CRATER.color + (expected_alpha,))

    def test_lightning_marker_alpha_at_1_0_0_5_0_0(self):
        """``age`` drives fade_frac == 1 - age/marker_life directly. The
        marker is now a `marker_segments`-gon (ring helper, feature-storm-
        acolyte-multi-build), same segment count as the flash's own octagon
        by default in the fixture data — so the two are distinguished by
        DRAW ORDER (submit_lightning always submits the flash poly, if any,
        before the marker poly), not by point count any more; at frac=0.5/
        0.0 here age >= bolt_life anyway, so the flash's own `if fr > 0`
        gate is already false and the marker is the only poly submitted."""
        fm = make_floater_manager()
        cs = make_cs()
        for frac, expected_alpha in ((1.0, 120), (0.5, 60), (0.0, 0)):
            with self.subTest(frac=frac):
                fx = LightningFX(2.0, 3.0, 1.5, LIGHTNING.bolt_life,
                                 LIGHTNING.marker_life)
                fxf = fx.get_component(LightningFXFade)
                fxf.age = fxf.marker_life * (1.0 - frac)
                renderer = FakeRenderer()
                fm.submit_lightning(renderer, cs, _TagScene([fx]))
                if frac == 0.0:
                    self.assertEqual(renderer.overlay_polys, [])
                    continue
                _, color = renderer.overlay_polys[-1]   # marker submits last
                self.assertAlmostEqual(color[3], expected_alpha, delta=1)
                self.assertEqual(color[:3], LIGHTNING.marker_color)


class TestAnnounceParity(unittest.TestCase):
    """color + int(max_alpha * k) — zero RNG draws (**verified**:
    submit_announce calls no rng method)."""

    def _fm_with_announce(self, k, fade_in=1.0, hold=1.0, fade_out=1.0):
        fm = make_floater_manager()
        fm._announce = {"fade_in": fade_in, "hold": hold,
                        "fade_out": fade_out, "enabled": True}
        # k==1.0 -> mid-hold; k==0.5/0.0 -> mid fade-out (linear, exact)
        if k == 1.0:
            fm._announce_age = fade_in + hold / 2
        else:
            out_frac = 1.0 - k
            fm._announce_age = fade_in + hold + out_frac * fade_out
        return fm

    def test_k_1_0_0_5_0_0(self):
        for k, expected_alpha in ((1.0, 255), (0.5, 127), (0.0, 0)):
            with self.subTest(k=k):
                fm = self._fm_with_announce(k)
                renderer = FakeRenderer()
                # Spy on submit_centered (the colour is what we're pinning;
                # text layout position is out of ESV-3b's scope).
                import game.ui.effects as effects_mod
                calls = []
                orig = effects_mod.submit_centered
                effects_mod.submit_centered = (
                    lambda r, text, x, y, size, color: calls.append(color))
                try:
                    fm.submit_announce(renderer, 800, 600)
                finally:
                    effects_mod.submit_centered = orig
                self.assertEqual(len(calls), 2)
                for color in calls:
                    self.assertEqual(color[:3], ANNOUNCE.color)
                    self.assertAlmostEqual(color[3], expected_alpha, delta=1)


class TestLifetimeThreading(unittest.TestCase):
    """ESV-3b §2.3 Option A: crater.life / lightning.bolt_life /
    lightning.marker_life flow from the caller's vfx_balance argument, not
    the CRATER_LIFE/BOLT_LIFE/MARKER_LIFE module constants. Construct with a
    life DELIBERATELY DIFFERENT from the module default and confirm the
    despawn clock follows the threaded value, not the constant — the module
    constant is only the Component base's required declared-field fallback
    (`engine/core/CLAUDE.md`: "declared field needs a default"), never the
    runtime source of truth."""

    def test_crater_fades_on_the_threaded_life_not_the_module_constant(self):
        threaded_life = CRATER_LIFE + 5.0
        scene = Scene()
        crater = Crater(1.0, 1.0, 0.8, threaded_life)
        crater.get_component(CraterFade)._scene = scene
        scene.spawn(crater)
        scene.update(0.0)
        self.assertEqual(scene.by_tag("crater"), [crater])
        # past the MODULE constant, still alive: proves no silent fallback
        scene.update(CRATER_LIFE + 1.0)
        self.assertEqual(scene.by_tag("crater"), [crater])
        # past the THREADED life: now despawns (queued+applied same update)
        scene.update(10.0)
        self.assertEqual(scene.by_tag("crater"), [])

    def test_lightning_fades_on_the_threaded_lifetimes_not_the_module_constants(self):
        threaded_bolt = BOLT_LIFE + 1.0
        threaded_marker = MARKER_LIFE + 5.0
        scene = Scene()
        fx = LightningFX(1.0, 1.0, 1.5, threaded_bolt, threaded_marker)
        fx.get_component(LightningFXFade)._scene = scene
        scene.spawn(fx)
        scene.update(0.0)
        scene.update(BOLT_LIFE + 0.1)   # past the MODULE bolt life...
        self.assertGreater(fx.bolt_frac, 0.0)  # ...but not the threaded one
        scene.update(threaded_bolt)
        self.assertEqual(fx.bolt_frac, 0.0)
        scene.update(MARKER_LIFE + 0.1)          # past the MODULE marker life
        self.assertEqual(scene.by_tag("lightning_fx"), [fx])  # still alive
        scene.update(threaded_marker)
        self.assertEqual(scene.by_tag("lightning_fx"), [])

    def test_d4_guard_simulation_timing_never_moved_into_vfx_json(self):
        """AOE_TRAVEL_TIME/BEAM_MIN_TICK stay module constants in
        game/enemies/combat.py and appear NOWHERE in
        data/balancing/vfx.json (D4 fence, §1.3). Write this test even under
        Option B — required unconditionally by the brief."""
        self.assertEqual(AOE_TRAVEL_TIME, 0.55)
        self.assertEqual(BEAM_MIN_TICK, 0.02)
        src = (REPO / "game" / "enemies" / "combat.py").read_text(
            encoding="utf-8")
        self.assertIn("AOE_TRAVEL_TIME = 0.55", src)
        self.assertIn("BEAM_MIN_TICK = 0.02", src)
        # The KEY names are the guard — a bare literal-value scan would false
        # -positive on an unrelated ESV-3a value (spark.presets.level1.life
        # is coincidentally 0.55 too).
        vfx_src = VFX_DATA_PATH.read_text(encoding="utf-8")
        self.assertNotIn("AOE_TRAVEL_TIME", vfx_src)
        self.assertNotIn("BEAM_MIN_TICK", vfx_src)
        vfx_data = data_io.load_json(VFX_DATA_PATH)
        proc = vfx_data["procedural"]
        for block in proc.values():
            self.assertNotIn("aoe_travel_time", block)
            self.assertNotIn("beam_min_tick", block)


if __name__ == "__main__":
    unittest.main()
