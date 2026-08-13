"""ESV-6 — Converge: anchored impact & muzzle VFX (docs/briefs/
phase-esv-6-converge.md §4). The plan's FINAL phase.

Ten tests per the brief:
1. Muzzle-anchored attack VFX (`watch_enemies`, both `enemy_attack_ranged` and
   `enemy_attack_melee`) — anchored vs exact-unanchored world point.
2. `defender_fire` fires and is anchored; the shipped inert row is a no-op
   emit (both pinned).
3. `projectile_hit` at the target's `impact` anchor; no-anchor is exact;
   fires even when the target dies the same frame.
4. **Guardrail pin (D4)** — bit-identical HP ledger / kill / flight timing
   under large `muzzle` + `impact` anchors on both shooter and target.
5. `None` handles degrade — never raise.
6. Excluded events (`enemy_death`, `splash_impact`, the three building-
   celebration events) stay at their unanchored point even with both anchors
   authored.
7. Floater params come from data (all four spawn sites) + the G-7
   source-text fence (no module constant survives).
8. Floater default round-trip (byte-identity contract, as literals).
9. Schema — `projectile_hit` required; `vfx_hit`/`vfx_explosion` already
   accepted `sprite_slot` values.
10. Engine purity — the `engine/vfx/` file set is unchanged by the
    `params.py` append.

Every value-asserting test reads the pinned `FIXTURE_DATA` snapshot (never
live `data/`) or a temp copy (`fixture_copy`), never writes into `data/`.
"""
import tempfile
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy
from tools.tests.test_combat_anchors import (
    BUILD, CS, VFX, defender_stub, frozen_defender, frozen_target, make_store,
    synth,
)

from engine import data_io
from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.core import GameObject, Health, Scene, SpriteAnimator, Transform
from engine.physics import TileOccupancy
from game.anchors import anchor_world_point
from game.core import load_balance, RunState
from game.enemies import Projectile, resolve_combat
from game.enemies.combat import ProjectileHoming
from game.enemies.components import EnemyCombat, PathAgent
from game.ui.effects import FloaterManager

UI_BAL = load_balance(FIXTURE_DATA, "ui")
CORE_BAL = load_balance(FIXTURE_DATA, "core")

VFX_DATA_PATH = FIXTURE_DATA / "balancing" / "vfx.json"
VFX_SCHEMA_PATH = FIXTURE_DATA / "schemas" / "vfx.schema.json"


def make_store_named(slot_key, anchor_name, anchor_xy, frame_w=64, frame_h=64):
    """Like `test_combat_anchors.make_store`, but for an arbitrary anchor
    NAME — that helper only ever writes `muzzle` (ESV-1's concern); ESV-6
    needs `impact` too."""
    raw = {
        "sheet": "imported/x.png", "frame_w": frame_w, "frame_h": frame_h,
        "offset_x": 0, "offset_y": 0,
        "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                  "loop_start": 0, "loop_end": 0, "loop_count": 1}],
    }
    if anchor_xy is not None:
        raw["anchors"] = {anchor_name: list(anchor_xy)}
    entry = entry_from_dict(slot_key, raw)
    return AssetStore(manifest=Manifest({slot_key: entry}), sprites_dir=None,
                      frame_sizes={slot_key: (frame_w, frame_h)})


def make_store_two(slot_a, anchor_a, slot_b, anchor_b, frame_w=64, frame_h=64,
                   offset_a=(0, 0), offset_b=(0, 0)):
    """Two-entry AssetStore — a defender slot carrying `muzzle` and a target
    slot carrying `impact` (both anchor names on each entry so either read
    site works regardless of which slot it's asked about; the reader only
    ever asks for the ONE name it cares about). `offset_a`/`offset_b`
    (fix-anchor-offset-and-bullet-sprites Fix 1) let a caller pin the D4
    guardrail under a composed, non-zero `offset_x`/`offset_y` too — cosmetic
    only, never read by simulation."""
    def raw(anchor_xy, offset_xy):
        r = {
            "sheet": "imported/x.png", "frame_w": frame_w, "frame_h": frame_h,
            "offset_x": offset_xy[0], "offset_y": offset_xy[1],
            "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                      "loop_start": 0, "loop_end": 0, "loop_count": 1}],
        }
        if anchor_xy is not None:
            r["anchors"] = {"muzzle": list(anchor_xy), "impact": list(anchor_xy)}
        return r

    entries = {
        slot_a: entry_from_dict(slot_a, raw(anchor_a, offset_a)),
        slot_b: entry_from_dict(slot_b, raw(anchor_b, offset_b)),
    }
    frame_sizes = {slot_a: (frame_w, frame_h), slot_b: (frame_w, frame_h)}
    return AssetStore(manifest=Manifest(entries), sprites_dir=None,
                      frame_sizes=frame_sizes)


class _TagScene:
    """The minimal `scene.by_tag(tag)` surface `watch_enemies`/
    `watch_buildings` actually read (the test_vfx.py precedent)."""

    def __init__(self, objects):
        self._objects = list(objects)

    def by_tag(self, tag):
        return [o for o in self._objects if tag in o.tags]


class _RaiderStub(GameObject):
    ETYPE = "raider"


class _ToggleAlive(GameObject):
    """A building stub whose `alive` can flip mid-test (E-11 forbids a bare
    public `.alive` attribute — override as a property backed by a transient
    underscore field)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._alive = True

    @property
    def alive(self):
        return self._alive


def _enemy_stub(cls, col, row, slot_key, cooldown, blocked=True):
    return cls(tags=("enemy",), transform=Transform(wx=col, wy=row),
              components=[EnemyCombat(cooldown=cooldown),
                          PathAgent(blocked=blocked),
                          SpriteAnimator(slot_key=slot_key)])


# ===========================================================================
# 1 — muzzle-anchored attack VFX (watch_enemies)
# ===========================================================================
class TestWatchEnemiesMuzzleAnchor(unittest.TestCase):
    def _fire_twice(self, e, assets):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fm.assets, fm.cs = assets, CS
        calls = []
        fm._play = lambda event, wx, wy, **kw: calls.append((event, wx, wy))
        scene = _TagScene([e])
        fm.watch_enemies(scene)                          # baseline (no dispatch)
        e.get_component(EnemyCombat).cooldown += 1.0      # "reset" (grew)
        fm.watch_enemies(scene)                          # dispatch
        return calls

    def test_ranged_anchored_at_muzzle(self):
        """fix-anchor-origin-parity §1.2: never assert against
        `anchor_world_point` itself — the expected point is the literal
        `game.anchors.anchor_world_point(assets, CS, e, "muzzle")` result,
        computed independently (not via `fm._play`/`watch_enemies`) and
        pinned as a number, for `e.transform.world_pos == (2.0, 3.0)`, a
        `muzzle` anchor of `(40, -10)` and the fixture `anchor_test` slot's
        `frame_w=64`/`fit_tiles=0.0`/`scale=1.0` on `CS`'s real fixture
        geometry (tile_w=64/tile_h=32, zoom=1, no pan)."""
        assets = make_store("anchor_test", anchor_xy=(40, -10))
        e = _enemy_stub(GameObject, 2.0, 3.0, "anchor_test", 1.0)
        calls = self._fire_twice(e, assets)
        self.assertEqual(len(calls), 1)
        event, wx, wy = calls[0]
        self.assertEqual(event, "enemy_attack_ranged")
        self.assertAlmostEqual(wx, 2.8125, places=9)
        self.assertAlmostEqual(wy, 2.5625, places=9)

    def test_ranged_no_anchor_is_exact_world_pos(self):
        assets = make_store("anchor_test", anchor_xy=None)
        e = _enemy_stub(GameObject, 2.0, 3.0, "anchor_test", 1.0)
        calls = self._fire_twice(e, assets)
        event, wx, wy = calls[0]
        self.assertEqual((wx, wy), (2.0, 3.0))   # exact, not approximate

    def test_melee_anchored_at_muzzle(self):
        """Same independent-literal shape as the ranged test above — a
        different `muzzle` anchor, `(15, 5)`, resolves to a different
        literal point."""
        assets = make_store("anchor_test", anchor_xy=(15, 5))
        e = _enemy_stub(_RaiderStub, 2.0, 3.0, "anchor_test", 1.0)
        calls = self._fire_twice(e, assets)
        event, wx, wy = calls[0]
        self.assertEqual(event, "enemy_attack_melee")
        self.assertAlmostEqual(wx, 2.890625, places=9)
        self.assertAlmostEqual(wy, 3.421875, places=9)

    def test_melee_no_anchor_is_exact_world_pos(self):
        assets = make_store("anchor_test", anchor_xy=None)
        e = _enemy_stub(_RaiderStub, 2.0, 3.0, "anchor_test", 1.0)
        calls = self._fire_twice(e, assets)
        event, wx, wy = calls[0]
        self.assertEqual((wx, wy), (2.0, 3.0))


# ===========================================================================
# 1(b) — impact-anchored building_destroyed (watch_buildings)
# ===========================================================================
class TestWatchBuildingsImpactAnchor(unittest.TestCase):
    def _fire(self, assets):
        b = _ToggleAlive(tags=("building",), transform=Transform(wx=2.0, wy=3.0),
                         components=[SpriteAnimator(slot_key="anchor_test")])
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fm.assets, fm.cs = assets, CS
        calls = []
        fm._play = lambda event, wx, wy, **kw: calls.append((event, wx, wy))
        scene = _TagScene([b])
        fm.watch_buildings(scene)     # alive -> records baseline, no dispatch
        b._alive = False
        fm.watch_buildings(scene)     # alive flip -> dispatch
        return calls, b

    def test_anchored_at_impact(self):
        """Literal, independently-computed expected point (§1.2 — never
        against `anchor_world_point` itself): `b.transform.world_pos ==
        (2.0, 3.0)` (note NOT the `(2.5, 3.5)` tile-centre fallback point —
        "anchor wins outright" means an authored anchor resolves from the
        object's OWN transform, ignoring the pre-anchor fallback entirely),
        `impact` anchor `(6, -14)`."""
        assets = make_store_named("anchor_test", "impact", (6, -14))
        calls, b = self._fire(assets)
        self.assertEqual(len(calls), 1)
        event, wx, wy = calls[0]
        self.assertEqual(event, "building_destroyed")
        self.assertAlmostEqual(wx, 2.15625, places=9)
        self.assertAlmostEqual(wy, 2.96875, places=9)

    def test_no_anchor_is_exact_tile_center(self):
        assets = make_store("anchor_test", anchor_xy=None)
        calls, _b = self._fire(assets)
        event, wx, wy = calls[0]
        self.assertEqual((wx, wy), (2.5, 3.5))


# ===========================================================================
# 2 — defender_fire fires and is anchored; the shipped row is inert
# ===========================================================================
class TestDefenderFireEvent(unittest.TestCase):
    def test_ledger_fills_at_the_already_anchored_muzzle_point(self):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        defender = frozen_defender(tm, scene, occ, 1, 0)
        frozen_target(scene, tm, 2, 0)
        assets = make_store("anchor_test", anchor_xy=(40, -10))
        state = RunState()

        def on_fire(wx, wy):
            state.defender_fire_events.append((wx, wy))

        scene.update(0.05)
        resolve_combat(scene, tm, 0.05, BUILD, VFX, assets=assets, cs=CS,
                       on_defender_fire=on_fire)
        self.assertEqual(len(state.defender_fire_events), 1)
        wx, wy = state.defender_fire_events[0]
        # Literal, independently-computed expected point (§1.2): matches
        # test_combat_anchors.TestMuzzleShiftsTheSpawnPoint's own literal —
        # same defender position (1.0, 0.0), same muzzle anchor (40, -10).
        self.assertAlmostEqual(wx, 1.8125, places=9)
        self.assertAlmostEqual(wy, -0.4375, places=9)

    def test_shipped_row_is_inert_no_visible_effect(self):
        """The ledger fills every shot (proven above); draining it through
        the REAL, shipped `defender_fire` row (sprite_slot="", procedural="")
        must produce NO visible effect — pin both halves."""
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fm.assets, fm.scene = None, None
        state = RunState()
        state.defender_fire_events.append((1.0, 2.0))
        fm.spawn_defender_fire_events(state)
        self.assertEqual(state.defender_fire_events, [])   # drained
        self.assertEqual(fm._vfx._particles, [])            # no-op emit


# ===========================================================================
# 3 — projectile_hit at the target's impact anchor
# ===========================================================================
class TestProjectileHitEvent(unittest.TestCase):
    def _homing(self, assets, hp=10, dmg=999):
        tm = synth(["bbs"])
        scene = Scene()
        target = frozen_target(scene, tm, 2, 0, hp=hp)
        target.get_component(SpriteAnimator).slot_key = "anchor_test"
        proj = Projectile(1.0, 0.0, dmg, 5.0)
        hom = proj.get_component(ProjectileHoming)
        hom._assets, hom._cs = assets, CS
        hits = []
        hom._on_hit = lambda wx, wy: hits.append((wx, wy))
        hom.launch(target, defender_stub(), scene, origin=(1.0, 0.0))
        return hom, target, hits

    def test_anchored_at_impact_and_fires_when_target_dies_same_frame(self):
        """Literal, independently-computed expected point (§1.2): target
        `transform.world_pos == (2.0, 0.0)`, `impact` anchor `(12, -30)`."""
        assets = make_store_named("anchor_test", "impact", (12, -30))
        hom, target, hits = self._homing(assets)
        hom.timer = 0.0
        hom.update(0.0)   # forces _impact()
        self.assertEqual(len(hits), 1)
        wx, wy = hits[0]
        self.assertAlmostEqual(wx, 1.75, places=9)
        self.assertAlmostEqual(wy, -0.625, places=9)
        self.assertFalse(target.alive)   # died this same frame — hit still fires

    def test_no_anchor_is_exact_world_pos(self):
        assets = make_store("anchor_test", anchor_xy=None)
        hom, target, hits = self._homing(assets)
        hom.timer = 0.0
        hom.update(0.0)
        tx, ty = target.transform.world_pos
        self.assertEqual(hits[0], (tx, ty))

    def test_no_hit_callback_never_raises(self):
        hom, _target, hits = self._homing(make_store("anchor_test", None))
        hom._on_hit = None
        hom.timer = 0.0
        hom.update(0.0)   # must not raise
        self.assertEqual(hits, [])


# ===========================================================================
# 4 — GUARDRAIL D4: bit-identical HP ledger / kill / flight timing
# ===========================================================================
class TestGuardrailD4BitIdenticalUnderLargeAnchors(unittest.TestCase):
    def _run(self, def_anchor, tgt_anchor, n_frames=200, dt=0.05,
             def_offset=(0, 0), tgt_offset=(0, 0)):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        defender = frozen_defender(tm, scene, occ, 1, 0, slot_key="def_slot")
        target = frozen_target(scene, tm, 2, 0, hp=40)
        target.get_component(SpriteAnimator).slot_key = "tgt_slot"
        assets = make_store_two("def_slot", def_anchor, "tgt_slot", tgt_anchor,
                                offset_a=def_offset, offset_b=tgt_offset)
        health = target.get_component(Health)

        frame = [0]
        hp_ledger = []
        hit_points = []
        fire_points = []

        def on_hit(wx, wy):
            hit_points.append((frame[0], wx, wy))

        def on_fire(wx, wy):
            fire_points.append((frame[0], wx, wy))

        for i in range(n_frames):
            frame[0] = i
            scene.update(dt)
            resolve_combat(scene, tm, dt, BUILD, VFX, assets=assets, cs=CS,
                           on_defender_fire=on_fire, on_projectile_hit=on_hit)
            hp_ledger.append(health.hp)
        return hp_ledger, hit_points, fire_points

    def test_bit_identical_hp_kill_and_flight_timing(self):
        baseline = self._run(None, None)
        large = self._run((40, -10), (35, -25))
        absurd = self._run((2000, -1800), (1900, 1700))
        # fix-anchor-offset-and-bullet-sprites Fix 1 re-pin: the shooter and
        # target ALSO carry a non-zero offset_x/offset_y, composed into the
        # anchor origin now — still cosmetic only (D4), never simulation.
        offset_and_anchor = self._run((40, -10), (35, -25),
                                      def_offset=(0, 8), tgt_offset=(3, -5))

        base_hp, base_hits, base_fires = baseline
        large_hp, large_hits, large_fires = large
        absurd_hp, absurd_hits, absurd_fires = absurd
        off_hp, off_hits, off_fires = offset_and_anchor

        self.assertTrue(any(h < base_hp[0] for h in base_hp))   # it did fight
        self.assertLessEqual(base_hp[-1], 0)                    # and it died

        # HP ledger, frame-for-frame, is byte-identical
        self.assertEqual(base_hp, large_hp)
        self.assertEqual(base_hp, absurd_hp)
        self.assertEqual(base_hp, off_hp)

        # flight timing: the FRAME each projectile_hit landed is identical
        base_frames = [f for f, _, _ in base_hits]
        self.assertEqual(base_frames, [f for f, _, _ in large_hits])
        self.assertEqual(base_frames, [f for f, _, _ in absurd_hits])
        self.assertEqual(base_frames, [f for f, _, _ in off_hits])
        self.assertTrue(base_frames)   # the loop really did land a hit

        # ...but the anchors DID move the cosmetic points (not a vacuous
        # "anchors have zero effect" pass) — the fire ledger's first point
        # differs between the unanchored and large-anchor runs.
        self.assertNotEqual(base_fires[0][1:], large_fires[0][1:])
        self.assertNotEqual(base_hits[0][1:], large_hits[0][1:])
        # ...and the offset-composed run differs from the anchor-only run
        # too (the offset really composed into the cosmetic point), while
        # still landing on the exact same frames/HP above.
        self.assertNotEqual(large_fires[0][1:], off_fires[0][1:])
        self.assertNotEqual(large_hits[0][1:], off_hits[0][1:])


# ===========================================================================
# 5 — None handles degrade, never raise
# ===========================================================================
class TestNoneHandlesDegrade(unittest.TestCase):
    def test_anchored_is_identity_when_cs_and_assets_are_none(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        self.assertIsNone(fm.cs)
        self.assertIsNone(fm.assets)
        wx, wy = fm._anchored(object(), "muzzle", 3.0, 4.0)
        self.assertEqual((wx, wy), (3.0, 4.0))

    def test_watch_enemies_and_watch_buildings_never_raise_bare(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)   # assets/cs/scene all None
        e = _enemy_stub(GameObject, 1.0, 1.0, "anchor_test", 1.0)
        b = _ToggleAlive(tags=("building",), transform=Transform(wx=1.0, wy=1.0),
                         components=[SpriteAnimator(slot_key="anchor_test")])
        fm.watch_enemies(_TagScene([e]))
        fm.watch_buildings(_TagScene([b]))
        e.get_component(EnemyCombat).cooldown += 1.0
        b._alive = False
        fm.watch_enemies(_TagScene([e]))       # dispatch path, still no raise
        fm.watch_buildings(_TagScene([b]))     # dispatch path, still no raise


# ===========================================================================
# 6 — excluded events stay at their unanchored point (§1.2)
# ===========================================================================
class TestExcludedEventsStayUnanchored(unittest.TestCase):
    def test_building_celebration_events_stay_at_tile_center(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fm.assets, fm.cs = make_store("anchor_test", anchor_xy=(50, -50)), CS
        calls = []
        fm._play = lambda event, wx, wy, **kw: calls.append((event, wx, wy))
        fm.spawn_building_vfx(3, 4, "place")
        fm.spawn_building_vfx(3, 4, "level1")
        fm.spawn_building_vfx(3, 4, "tier")
        self.assertEqual(calls, [
            ("building_placed", 3.5, 4.5),
            ("building_level_up", 3.5, 4.5),
            ("building_tier_up", 3.5, 4.5),
        ])

    def test_enemy_death_and_splash_impact_stay_at_the_ledger_point(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fm.assets, fm.cs = make_store("anchor_test", anchor_xy=(50, -50)), CS
        calls = []
        fm._play = lambda event, wx, wy, **kw: calls.append((event, wx, wy))
        state = RunState()
        state.enemy_death_events.append((3.0, 4.0))
        fm.spawn_death_events(state, gore_on=True)
        state.splash_impact_events.append((5.0, 6.0))
        fm.spawn_splash_impact_events(state)
        self.assertEqual(calls, [("enemy_death", 3.0, 4.0),
                                 ("splash_impact", 5.0, 6.0)])

    def test_source_text_never_anchors_the_excluded_call_sites(self):
        """Regression pin against a future 'tidy-up' (brief §1.2)."""
        src = (REPO / "game" / "ui" / "effects.py").read_text(encoding="utf-8")
        chunks = src.split("\n    def ")
        excluded_headers = ("spawn_death_events(", "spawn_splash_impact_events(",
                            "spawn_building_vfx(")
        pinned = 0
        for chunk in chunks:
            if chunk.startswith(excluded_headers):
                pinned += 1
                self.assertNotIn("_anchored(", chunk)
        self.assertEqual(pinned, 3)


# ===========================================================================
# 7 — floater params come from data (all four spawn sites) + G-7 fence
# ===========================================================================
class TestFloaterParamsFromData(unittest.TestCase):
    def test_editing_temp_dir_json_changes_the_emitted_floater(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = fixture_copy(tmp)
            vfx_path = data_dir / "balancing" / "vfx.json"
            schema_path = data_dir / "schemas" / "vfx.schema.json"
            doc = data_io.load_json(vfx_path)
            doc["procedural"]["floaters"]["xp_color"] = [1, 2, 3]
            doc["procedural"]["floaters"]["xp_life"] = 9.5
            data_io.write_validated(doc, vfx_path, schema_path)

            vfx_bal = load_balance(data_dir, "vfx")
            fm = FloaterManager(UI_BAL, CORE_BAL, vfx_bal)
            state = RunState()
            state.xp_events.append((1.0, 2.0, 5))
            fm.spawn_xp_events(state)
            self.assertEqual(fm._floaters[0].color, (1, 2, 3))
            self.assertEqual(fm._floaters[0].life, 9.5)

    def test_all_four_spawn_sites_read_vfx_params_floaters(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        fl = fm._vfx_params.floaters
        state = RunState()

        state.income_events.append((0, 0, -5, "upkeep"))
        fm.spawn_income_events(state)
        self.assertEqual(fm._floaters[-1].color, fl.upkeep_color)

        state.xp_events.append((0.0, 0.0, 3))
        fm.spawn_xp_events(state)
        self.assertEqual(fm._floaters[-1].color, fl.xp_color)
        self.assertEqual(fm._floaters[-1].life, fl.xp_life)

        state.painter_events.append((0, 0, "x", "finished"))
        fm.spawn_painter_events(state)
        self.assertEqual(fm._floaters[-1].color, fl.painter_finished_color)
        self.assertEqual(fm._floaters[-1].life, fl.painter_life)

        state.painter_events.append((0, 0, "x", "lost"))
        fm.spawn_painter_events(state)
        self.assertEqual(fm._floaters[-1].color, fl.painter_lost_color)

        state.boost_events.append((0, 0, "x"))
        fm.spawn_boost_events(state)
        self.assertEqual(fm._floaters[-1].color, fl.boost_color)

    def test_g7_fence_no_module_constant_names_remain(self):
        src = (REPO / "game" / "ui" / "effects.py").read_text(encoding="utf-8")
        for name in ("_UPKEEP_BLUE", "_XP_PURPLE", "_XP_LIFE",
                    "_PAINTER_FINISHED", "_PAINTER_LOST", "_PAINTER_LIFE",
                    "_BOOST_WHITE"):
            with self.subTest(name=name):
                self.assertNotIn(name, src)


# ===========================================================================
# 8 — floater default round-trip (byte-identity contract, as literals)
# ===========================================================================
class TestFloaterDefaultRoundTrip(unittest.TestCase):
    def test_matches_the_todays_table(self):
        data = data_io.load_validated(VFX_DATA_PATH, VFX_SCHEMA_PATH)
        f = data["procedural"]["floaters"]
        self.assertEqual(f["upkeep_color"], [120, 170, 230])
        self.assertEqual(f["xp_color"], [202, 140, 245])
        self.assertEqual(f["xp_life"], 0.9)
        self.assertEqual(f["painter_finished_color"], [255, 255, 100])
        self.assertEqual(f["painter_lost_color"], [255, 100, 100])
        self.assertEqual(f["painter_life"], 1.5)
        self.assertEqual(f["boost_color"], [255, 255, 255])


# ===========================================================================
# 9 — schema: projectile_hit required; vfx_hit/vfx_explosion already accepted
# ===========================================================================
class TestSchema(unittest.TestCase):
    def test_fixture_validates_with_projectile_hit(self):
        data = data_io.load_validated(VFX_DATA_PATH, VFX_SCHEMA_PATH)
        self.assertIn("projectile_hit", data["triggers"])
        # ESV-6 shipped this row INERT, and that is what this pins. It used to
        # assert whole-dict equality, which made it a pin on the row's SHAPE
        # too — so VfxAuthoringPLAN VA-2 adding `variant_select`/
        # `draw_in_front` reddened it without anything about inertness
        # changing. Assert the two fields that decide whether it draws.
        row = data["triggers"]["projectile_hit"]
        self.assertEqual(row["sprite_slot"], "")
        self.assertEqual(row["procedural"], "")

    def test_triggers_missing_projectile_hit_fails_validation(self):
        data = data_io.load_json(VFX_DATA_PATH)
        del data["triggers"]["projectile_hit"]
        schema = data_io.load_json(VFX_SCHEMA_PATH)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(data, schema)

    def test_sprite_slot_enum_already_accepted_vfx_hit_and_vfx_explosion(self):
        """The brief asked to VERIFY this, not add it — the enum already
        carried both keys before ESV-6 (the two long-orphaned `vfx` slots the
        plan's opening complaint named)."""
        schema = data_io.load_json(VFX_SCHEMA_PATH)
        enum = schema["$defs"]["trigger_row"]["properties"]["sprite_slot"]["enum"]
        self.assertIn("vfx_hit", enum)
        self.assertIn("vfx_explosion", enum)


# ===========================================================================
# 10 — engine purity: the file set is unchanged by the params.py append
# ===========================================================================
class TestEnginePurityUnaffectedByFloaterParams(unittest.TestCase):
    def test_file_set_unchanged(self):
        # VfxAuthoringPLAN VA-2 added variants.py (the pure registry half of
        # VFX variant resolution). Still a flat file, still no data access —
        # which is what this pin actually guards.
        vfx_dir = REPO / "engine" / "vfx"
        scanned = sorted(vfx_dir.glob("*.py"))
        self.assertEqual({p.name for p in scanned},
                         {"__init__.py", "emitters.py", "params.py",
                          "particle.py", "play_once.py", "system.py",
                          "variants.py"})

    def test_params_module_stays_pure(self):
        src = (REPO / "engine" / "vfx" / "params.py").read_text(encoding="utf-8")
        for tok in ("open(", "import json", "from json", "import pygame",
                    "from pygame", "engine.data_io", "import game", "from game",
                    "import editor", "from editor"):
            with self.subTest(tok=tok):
                self.assertNotIn(tok, src)


if __name__ == "__main__":
    unittest.main()
