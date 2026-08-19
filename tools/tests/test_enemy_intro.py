"""feature-enemy-intro-dialogue: the ENEMY_INTRO phase machine.

Pure-Python, headless — the ``test_lightning.py``/``test_boss.py`` fixture
style: a synth ``TileMapDoc`` -> ``TileMap`` board + real balancing via
``load_balance``. ``core.json``'s ``EnemyIntro.entries`` ships empty in the
fixture (as in live data), so each test that needs a match builds its own
deep-copied ``core_balance`` with entries injected — never mutates the
module-level fixture dict shared across tests.
"""
import copy
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")

_MOCK_ENTRY = {
    "enemy_label": "Test Enemy", "round": 1, "title": "Test title",
    "body": "Test body.", "sprite_slot": "enemy_stage_1_v1",
    "sprite_w": 96, "sprite_h": 96,
    "animation": "idle", "anim_speed": 1.0, "hidden_frames": [],
    "crop_x": 0, "crop_y": 0, "crop_w": 0, "crop_h": 0,
    "sprite_offset_x": 0, "sprite_offset_y": 0, "sprite_flip_h": False,
    "background_tint": [0, 0, 0, 0],
}


def _core_with_entries(*rounds):
    """A deep copy of the fixture's core balance with one EnemyIntro entry
    per given round number (never mutates the shared module-level CORE)."""
    core = copy.deepcopy(CORE)
    core["EnemyIntro"]["entries"] = [
        {**_MOCK_ENTRY, "round": r} for r in rounds]
    return core


def _core_with_tutorial_entry(round_num=1, flagged=True):
    """A deep copy of the fixture's core balance with ONE entry authored at
    ``round_num``, opting into (or out of) the tutorial's own combat round."""
    core = copy.deepcopy(CORE)
    core["EnemyIntro"]["entries"] = [
        {**_MOCK_ENTRY, "round": round_num,
         "show_on_tutorial_round": flagged}]
    return core


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_session(core_balance, rng=None):
    tm = synth(["cccc"] * 4)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, core_balance),
                scene, occ)
    session = Session.create(Spawner(), tm, ENEM, core_balance, BUILD,
                             rng=rng or random.Random(1), occupancy=occ)
    return session, scene


class TestNoMatchingEntries(unittest.TestCase):
    """An empty entries list (schema minItems is 1, but never rely on that —
    pin the fixture explicitly rather than reading live/fixture content) is
    byte-identical to before the feature existed."""

    def test_end_turn_enters_enemy_directly(self):
        core = _core_with_entries()  # no rounds -> entries == []
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])
        self.assertFalse(session.frozen)


class TestOneMatchingEntry(unittest.TestCase):
    def setUp(self):
        self.core = _core_with_entries(1)  # RunState.from_balance starts round 1
        self.session, self.scene = build_session(self.core)

    def test_end_turn_queues_it_and_enters_enemy_intro(self):
        self.session.end_turn()
        st = self.session.state
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertEqual(st.pending_enemy_intros[0]["round"], 1)

    def test_frozen_covers_enemy_intro(self):
        self.session.end_turn()
        self.assertTrue(self.session.frozen)

    def test_pre_sim_does_not_drain_the_wave_while_frozen(self):
        """The wave is already queued by begin_round() (inside end_turn()),
        but pre_sim must not spawn anything onto the field until the phase
        actually reaches ENEMY."""
        self.session.end_turn()
        before = len(self.session.spawner.pending())
        for _ in range(5):
            self.session.pre_sim(0.5, self.scene)
        self.assertEqual(len(self.session.spawner.pending()), before)
        self.assertEqual(len(self.scene.by_tag("enemy")), 0)

    def test_resolve_enemy_intro_drains_the_queue_and_starts_the_round(self):
        self.session.end_turn()
        self.session.resolve_enemy_intro()
        st = self.session.state
        self.assertEqual(st.pending_enemy_intros, [])
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertFalse(self.session.frozen)


class TestQueuedEntries(unittest.TestCase):
    """Two entries sharing the same round both fire, one after another."""

    def test_both_entries_queue_on_the_same_round(self):
        core = _core_with_entries(1, 1)
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(session.state.pending_enemy_intros), 2)

    def test_resolve_enemy_intro_pops_one_at_a_time(self):
        core = _core_with_entries(1, 1)
        session, _scene = build_session(core)
        session.end_turn()
        session.resolve_enemy_intro()
        st = session.state
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)  # queue not drained yet
        session.resolve_enemy_intro()
        self.assertEqual(st.pending_enemy_intros, [])
        self.assertEqual(st.phase, GamePhase.ENEMY)

    def test_resolve_enemy_intro_is_a_safe_no_op_once_drained(self):
        core = _core_with_entries(1)
        session, _scene = build_session(core)
        session.end_turn()
        session.resolve_enemy_intro()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        session.resolve_enemy_intro()  # nothing queued — must not raise/misbehave
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])


class TestNonMatchingRound(unittest.TestCase):
    def test_entry_for_a_later_round_does_not_fire_on_round_one(self):
        core = _core_with_entries(2)  # round 1 is what end_turn() will see first
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])


class _RecordingRenderer:
    def __init__(self):
        self.hud = []

    def submit_hud(self, item):
        self.hud.append(item)


class TestWindowSpriteFields(unittest.TestCase):
    """feature-enemy-intro-dialogue's sprite/animation controls: every new
    entry field's effect on the emitted HudSprite/HudRect."""

    WINDOW_BALANCE = {"width": 320, "height": 420, "open_seconds": 0.3,
                      "hold_seconds": 3.0, "close_seconds": 0.3}

    def window(self):
        from game.ui.enemy_intro import EnemyIntroWindow
        return EnemyIntroWindow(1280, 720, self.WINDOW_BALANCE)

    def submitted_sprite(self, entry, elapsed=0.5):
        from engine.render import HudSprite

        w = self.window()
        w.open({**_MOCK_ENTRY, **entry})
        w.update(elapsed, 0, 0, False)
        r = _RecordingRenderer()
        w.submit(r, 1280, 720)
        return next(i for i in r.hud if isinstance(i, HudSprite))

    def submitted_rects(self, entry, elapsed=0.5):
        from engine.render import HudRect

        w = self.window()
        w.open({**_MOCK_ENTRY, **entry})
        w.update(elapsed, 0, 0, False)
        r = _RecordingRenderer()
        w.submit(r, 1280, 720)
        return [i for i in r.hud if isinstance(i, HudRect)]

    def test_default_entry_carries_no_crop_or_hidden_frames(self):
        sprite = self.submitted_sprite({})
        self.assertIsNone(sprite.crop)
        self.assertEqual(sprite.hidden_frames, ())

    def test_crop_composes_into_a_four_tuple(self):
        sprite = self.submitted_sprite(
            {"crop_x": 4, "crop_y": 8, "crop_w": 16, "crop_h": 24})
        self.assertEqual(sprite.crop, (4, 8, 16, 24))

    def test_zero_crop_w_and_h_means_no_crop(self):
        sprite = self.submitted_sprite(
            {"crop_x": 4, "crop_y": 8, "crop_w": 0, "crop_h": 0})
        self.assertIsNone(sprite.crop)

    def test_hidden_frames_pass_through_as_a_tuple(self):
        sprite = self.submitted_sprite({"hidden_frames": [1, 3]})
        self.assertEqual(sprite.hidden_frames, (1, 3))

    def test_sprite_flip_h_wires_to_hud_sprite_flip(self):
        self.assertFalse(self.submitted_sprite({"sprite_flip_h": False}).flip)
        self.assertTrue(self.submitted_sprite({"sprite_flip_h": True}).flip)

    def test_animation_field_wires_to_hud_sprite_animation(self):
        sprite = self.submitted_sprite({"animation": "walk"})
        self.assertEqual(sprite.animation, "walk")

    def test_sprite_offset_nudges_the_dest_box(self):
        base = self.submitted_sprite({})
        offset = self.submitted_sprite(
            {"sprite_offset_x": 5, "sprite_offset_y": -3})
        self.assertEqual(offset.dest, (base.dest[0] + 5, base.dest[1] - 3))

    def test_anim_speed_scales_the_window_clock(self):
        normal = self.submitted_sprite({"anim_speed": 1.0}, elapsed=1.0)
        doubled = self.submitted_sprite({"anim_speed": 2.0}, elapsed=1.0)
        # anim_speed only scales the clock fed into widgets.anim_ms — a
        # bigger multiplier must never produce a SMALLER resolved time.
        self.assertGreaterEqual(doubled.anim_time_ms, normal.anim_time_ms)

    def test_zero_alpha_background_tint_emits_no_rect(self):
        rects = self.submitted_rects({"background_tint": [10, 20, 30, 0]})
        self.assertFalse(any(r.color[:3] == (10, 20, 30) for r in rects))

    def test_nonzero_alpha_background_tint_emits_a_rect_behind_the_sprite(self):
        sprite = self.submitted_sprite({"background_tint": [10, 20, 30, 200]})
        rects = self.submitted_rects({"background_tint": [10, 20, 30, 200]})
        tint_rects = [r for r in rects if r.color[:3] == (10, 20, 30)]
        self.assertEqual(len(tint_rects), 1)
        rect = tint_rects[0]
        self.assertEqual(rect.rect, (*sprite.dest, *sprite.size))

    def test_background_tint_alpha_composes_with_window_fade(self):
        # Mid-open (not yet HOLD), the window's own alpha is < 255 — the
        # rect's alpha must be scaled down from the entry's authored value,
        # not the raw 200.
        w = self.window()
        w.open({**_MOCK_ENTRY, "background_tint": [1, 2, 3, 200]})
        w.update(0.05, 0, 0, False)   # still OPENING (open_seconds=0.3)
        r = _RecordingRenderer()
        w.submit(r, 1280, 720)
        from engine.render import HudRect
        rect = next(i for i in r.hud
                    if isinstance(i, HudRect) and i.color[:3] == (1, 2, 3))
        self.assertLess(rect.color[3], 200)

    def test_widened_sprite_slot_from_a_non_enemy_category_still_submits(self):
        # ui_button lives under the "ui" category, not "enemies" -- the
        # user-confirmed "any category" requirement.
        sprite = self.submitted_sprite({"sprite_slot": "ui_button"})
        self.assertEqual(sprite.slot_key, "ui_button")


class TestTutorialRoundEntry(unittest.TestCase):
    """`show_on_tutorial_round`: the tutorial's OWN combat round is round 0
    (TU-9, seeded host-side in game/main.py), and the flagged entry belongs
    there instead of on its authored round — once, never twice."""

    def _tutorial_session(self, core):
        session, scene = build_session(core)
        session.state.round_num = 0   # what an ACTIVE tutorial run seeds
        return session, scene

    def test_flagged_entry_fires_on_the_tutorial_round(self):
        session, _scene = self._tutorial_session(_core_with_tutorial_entry())
        session.end_turn()
        st = session.state
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertTrue(st.tutorial_intros_shown)

    def test_flagged_entry_does_not_fire_again_on_its_authored_round(self):
        session, _scene = self._tutorial_session(_core_with_tutorial_entry())
        session.end_turn()
        st = session.state
        # drain the tutorial round's dialogue, then reach round 1's End Turn
        while st.phase == GamePhase.ENEMY_INTRO:
            session.resolve_enemy_intro()
        st.round_num = 1
        st.phase = GamePhase.BUILDING
        session.end_turn()
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertEqual(st.pending_enemy_intros, [])

    def test_flagged_entry_fires_on_round_1_when_the_tutorial_was_skipped(self):
        # No round 0 ever happened (RunState.from_balance starts at 1) —
        # the flag must not cost the entry its normal appearance.
        session, _scene = build_session(_core_with_tutorial_entry())
        self.assertEqual(session.state.round_num, 1)
        session.end_turn()
        st = session.state
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertFalse(st.tutorial_intros_shown)

    def test_unflagged_entry_is_untouched_by_the_tutorial_round(self):
        session, _scene = self._tutorial_session(
            _core_with_tutorial_entry(flagged=False))
        session.end_turn()
        st = session.state
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertEqual(st.pending_enemy_intros, [])
        self.assertFalse(st.tutorial_intros_shown)


class TestSpawnTriggeredEntry(unittest.TestCase):
    """`show_on_spawn_of` entries wait for the etype to actually spawn (the
    Commander is summoned mid-boss-fight, never queued into a wave), so they
    must NOT fire on their authored round the way an unflagged entry does."""

    def _session(self):
        core = copy.deepcopy(CORE)
        core["EnemyIntro"]["entries"] = [
            {**_MOCK_ENTRY, "round": 1, "show_on_spawn_of": "commander"}]
        return build_session(core)

    def test_end_turn_ignores_it_even_on_its_authored_round(self):
        session, _scene = self._session()
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])

    def test_it_fires_when_that_etype_spawns(self):
        # `_queue_spawn_intros` direct rather than through `post_sim`: this
        # 4x4 synth map has no spawn tiles, so the wave is empty and post_sim
        # would end the round before ever reaching the intro check.
        session, scene = self._session()
        session.end_turn()
        session.spawner._spawned_types.append("commander")
        session._queue_spawn_intros()
        st = session.state
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertIn("commander", st.spawn_intros_shown)
        # Back to the round the moment the card closes, and never a second
        # time however many more Commanders the fight summons.
        session.resolve_enemy_intro()
        self.assertEqual(st.phase, GamePhase.ENEMY)
        session.spawner._spawned_types.append("commander")
        session._queue_spawn_intros()
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertEqual(st.pending_enemy_intros, [])

    def test_another_etype_spawning_does_not_fire_it(self):
        session, scene = self._session()
        session.end_turn()
        session.spawner._spawned_types.append("standard")
        session._queue_spawn_intros()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])


if __name__ == "__main__":
    unittest.main()
