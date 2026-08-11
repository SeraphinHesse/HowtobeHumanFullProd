"""Headless balance-sweep runner (debug-mode-telemetry Phase 6).

    py tools/simrun.py --rounds 20 --strategy greedy_defence --seed 7
    py tools/simrun.py --rounds 20 --strategy none --seed 7     # do-nothing

Plays real rounds over the LIVE ACTIVE MAP with no window and no human, and
writes the same four ``DebugRecorder`` artifacts a played run writes, into
``logs/sim-<strategy>-<seed>-*``. That is the whole point: a balance change can
be diffed by running this twice instead of playing the game twice.

**It is a HOST, not a second game.** Every rule comes from the same objects
``game/main.py`` drives — ``engine.tilemap.load_active_map`` + the real
``load_balance``, a real ``TileMap``/``Scene``/``TileOccupancy``/``Session``,
the real ``resolve_combat``, and the real ``place_building`` for every
placement (so costs, research gates, occupancy and the escalating Storm-Priest
price are the game's). The frame body is ``test_phase_loop.py``'s ``host_frame``
shape — ``pre_sim`` -> ``scene.update`` -> ``resolve_combat`` -> ``post_sim`` —
on the same ENEMY-phase combat-speed scaling ``main.py`` applies.

Three things a windowed run gets from a player, this runner has to answer for
itself, all deterministically:

* **What to build** — ``game/debug/policies.py``, called once per BUILDING
  phase. It only PROPOSES ``(tile, building_type)`` pairs; the real placement
  gate disposes.
* **When to unlock territory and when to end the turn** — ``_expand_territory``
  buys ONE 2×2 chunk per BUILDING phase, and only once the board has run out
  of free buildable tiles. This is a HOST answer, not a policy one, and it is
  not optional: the starting section is a single 2×2 chunk, so a runner that
  never unlocks is capped at three buildings for the whole run and every
  strategy converges to the same degenerate board by round 2.
* **The two modal phases** — LEVELUP takes its first rolled option and
  BOSS_CUTSCENE takes ``"A"``, since neither phase advances on its own
  (``Session.frozen``) and a headless run would otherwise deadlock there.

Everything the runner consumes randomness for goes through ONE
``random.Random(seed)`` — the tile-condition roll, the level-up roll and the
whole spawner (composition, spawn tiles, jitter) — so the same ``--seed``
twice produces byte-identical output (pinned by ``test_simrun.py``).
"""
import argparse
import os
import random
import sys
from pathlib import Path

# SDL dummy drivers before any import that could pull pygame in (tools/smoke.py
# precedent). Nothing here opens a window; this is what makes that true even if
# a transitive import initialises SDL.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import TierState
from game.buildings.coverage import wire_defence_coverage
from game.buildings.registry import PlacementError
from game.core import Session, load_balance
from game.core.boss_bonuses import story_damage_bonus
from game.core.phases import GamePhase, GameState
from game.debug import DebugRecorder, LEVEL_BASIC, LEVELS, LEVEL_VERBOSE
from game.debug import events as dbg
from game.debug.policies import STRATEGIES
from game.enemies import Spawner, resolve_combat
from game.enemies.components import set_damage_hook, set_wall_damage_hook
from game.map.tile_map import TileMap
from game.map.tiles import TileState

#: Fixed sim step. A real run's dt is wall-clock; a sim's must not be, or the
#: machine's speed would leak into the balance numbers.
DT = 1.0 / 60.0

#: Safety valve: frames per requested round before the runner gives up. A
#: wave that can never clear (nothing can reach the base, nothing can die)
#: would otherwise spin forever.
FRAMES_PER_ROUND_CAP = 60 * 240


class _DeterministicTileMap(TileMap):
    """A ``TileMap`` whose three tile-state queries return SORTED lists.

    **This is a runner-local determinism shim, not a gameplay change.**
    ``TileMap._by_state`` is a ``set`` of ``Tile`` objects, and ``Tile`` has
    ``__slots__`` and no ``__eq__``/``__hash__`` — so it hashes by identity and
    the set's iteration order depends on where those objects happened to be
    allocated. It therefore differs between two runs, even in one process with
    one seed. Almost nothing cares (every consumer sums or unions), but the
    hunt queries in ``game/map/pathfinder.py`` break DISTANCE TIES on it, so a
    raider hunting one of two equidistant huts picks a different victim each
    run and the whole wave diverges from there — measured: identical rounds
    1-5, then ``dmg_dealt`` 700 vs 672 at round 6.

    Sorting picks one stable representative of a choice the game already makes
    arbitrarily; it does not make a different KIND of choice. The fix belongs
    in ``game/map`` (sorted accessors, or a value-hashed ``Tile``) and is a
    gameplay-tie-break change with its own blast radius — out of scope here,
    and reported rather than smuggled in.
    """

    @staticmethod
    def _sorted(tiles):
        return sorted(tiles, key=lambda t: (t.col, t.row))

    def built_tiles(self):
        return self._sorted(super().built_tiles())

    def buildable_tiles(self):
        return self._sorted(super().buildable_tiles())

    def spawning_tiles(self):
        return self._sorted(super().spawning_tiles())


class SimWorld:
    """The rebuildable run state — ``game/main.py``'s ``_World``, minus every
    display concern (no coords, no assets, no registry: art cannot change a
    number). One seeded ``Random`` drives the map's condition roll, the
    level-up roll and the spawner."""

    def __init__(self, data_dir, rng):
        self.map_bal = load_balance(data_dir, "map")
        self.buildings_bal = load_balance(data_dir, "buildings")
        self.core_bal = load_balance(data_dir, "core")
        self.enemies_bal = load_balance(data_dir, "enemies")
        self.vfx_bal = load_balance(data_dir, "vfx")
        # TimelinePLAN T4: the sole source of unlock timing — without this a
        # simulated run's level-up roll would offer nothing but the love
        # fallback, defeating the point of a balance-sweep host.
        self.progression_bal = load_balance(data_dir, "progression")
        self.map_doc = tilemap.load_active_map(data_dir)
        # `registry=None`: slot art is display-only. `rng` is what rolls the
        # tile conditions, which DO change balance (speed/damage/yield mods).
        self.tile_map = _DeterministicTileMap(self.map_doc, self.map_bal,
                                              rng=rng)
        self.occupancy = TileOccupancy()
        self.scene = Scene()
        if self.tile_map.base_col is not None:
            attach_base(self.tile_map,
                        BaseBuilding(self.tile_map.base_col,
                                     self.tile_map.base_row, self.core_bal),
                        self.scene, self.occupancy)
        self.spawner = Spawner()
        self.session = Session.create(
            self.spawner, self.tile_map, self.enemies_bal, self.core_bal,
            self.buildings_bal, registry=None, rng=rng,
            occupancy=self.occupancy, progression_balance=self.progression_bal)
        wire_defence_coverage(self.tile_map, self.buildings_bal)


def apply_policy(world, policy, recorder):
    """Run ``policy`` once and place what it proposes through the REAL
    ``place_building``. A proposal the gate rejects (unbuildable tile, not
    researched, not affordable) is skipped silently — that is the policy being
    wrong about the board, not an error.

    The love spend / ``buildings_placed`` bookkeeping mirrors
    ``game/ui/building_ui.py``'s ``_do_place`` exactly, including the
    ``place`` event and its ``note_love_spent``, so a sim row's
    ``buildings_placed`` / ``love_spent_buildings`` mean what a played run's
    mean. It does NOT call ``lightning.unlock_from_placement`` — that is a UI
    seam, and a headless run has no one to click a bolt."""
    session, state = world.session, world.session.state
    for tile, building_type in policy(state, world.tile_map,
                                      world.buildings_bal):
        try:
            building, cost = place_building(
                world.tile_map, tile, building_type, state.love,
                world.buildings_bal, world.scene, world.occupancy, state=state)
        except PlacementError:
            continue
        state.spend_love(cost)
        state.buildings_placed += 1
        if recorder is not None:
            tier_state = building.get_component(TierState)
            recorder.note_love_spent(cost, dbg.SPEND_PLACE)
            recorder.emit(dbg.PLACE, building_type=building_type,
                          col=tile.col, row=tile.row, cost=cost,
                          tier=None if tier_state is None
                          else tier_state.current_tier)


#: Free buildable tiles below which ``_expand_territory`` buys another chunk.
MIN_FREE_TILES = 2


def _expand_territory(world):
    """Buy at most ONE 2×2 chunk, through the real ``can_unlock``/
    ``unlock_cost``/``do_unlock`` seam the UI's UNLOCK button uses — so the
    price, the adjacency rule and the spawn-band recede are the game's.

    Candidates are the COMBAT tiles orthogonally touching owned territory,
    walked off the owned tiles (O(territory), never a full-map scan — the
    ``game/map/CLAUDE.md`` perf invariant). Cheapest first, nearest the base
    to break ties, then ``(col, row)`` so two runs of one seed choose the same
    chunk. A tile unlock deliberately emits NO debug event: it is not a
    building type, and ``game/core/CLAUDE.md`` records that it is wired to
    none — it shows up in the row as love spent between ``love_start`` and
    ``love_end``."""
    tm = world.tile_map
    state = world.session.state
    if len(tm.buildable_tiles()) >= MIN_FREE_TILES:
        return False
    bc, br = tm.base_col or 0, tm.base_row or 0
    seen, candidates = set(), []
    owned = tm.buildable_tiles() + tm.built_tiles()
    for tile in owned:
        for nc, nr in ((tile.col + 1, tile.row), (tile.col - 1, tile.row),
                       (tile.col, tile.row + 1), (tile.col, tile.row - 1)):
            n = tm.get(nc, nr)
            if n is None or n.state != TileState.COMBAT or (nc, nr) in seen:
                continue
            seen.add((nc, nr))
            if tm.can_unlock(n):
                candidates.append(
                    (tm.unlock_cost(n), (n.col - bc) ** 2 + (n.row - br) ** 2,
                     n.col, n.row, n))
    if not candidates:
        return False
    cost, _d, _c, _r, tile = min(candidates, key=lambda e: e[:4])
    if state.love < cost or not tm.do_unlock(tile):
        return False
    state.spend_love(cost)
    return True


def _resolve_modal(session, scene):
    """Answer the phases that freeze the world waiting on a click/window.
    Returns True when one was answered (the caller re-reads the phase and
    loops)."""
    st = session.state
    if st.phase == GamePhase.LEVELUP:
        options = st.levelup_options
        # Deterministic by construction: the roll is already seeded, and this
        # always takes its first card rather than choosing.
        session.resolve_levelup(options[0], scene)
        return True
    if st.phase == GamePhase.BOSS_CUTSCENE:
        session.resolve_boss_cutscene("A", scene)
        return True
    if st.phase == GamePhase.ENEMY_INTRO:
        # feature-enemy-intro-dialogue: a designer-authored enemy-intro entry
        # queued on this round — a headless run has no window to show it, so
        # drain the queue immediately (the same "resolve, don't wait" answer
        # this function already gives LEVELUP/BOSS_CUTSCENE).
        session.resolve_enemy_intro()
        return True
    return False


def run_sim(rounds, strategy, seed, level=LEVEL_BASIC, data_dir=None,
            out_dir=None, run_id=None, outputs=None):
    """Play ``rounds`` paydays and return the recorder (already closed).

    Returns the ``DebugRecorder`` so a caller (``test_simrun.py``) can read
    ``recorder.rounds`` / ``recorder.paths`` without re-parsing the artifacts.
    """
    policy = STRATEGIES[strategy]
    data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
    out_dir = Path(out_dir) if out_dir is not None else REPO / "logs"
    rng = random.Random(seed)
    world = SimWorld(data_dir, rng)
    session = world.session
    state = session.state
    scene = world.scene

    recorder = DebugRecorder(
        out_dir, level=level,
        run_id=run_id or f"sim-{strategy}-{seed}", outputs=outputs)
    session.debug = recorder
    recorder.bind(state)
    recorder.emit(dbg.RUN_START, level=recorder.level, run_id=recorder.run_id,
                  map_id=world.map_doc.map_id, seed=seed, love=state.love,
                  lives=state.base_lives)

    verbose = level >= LEVEL_VERBOSE

    def _on_damage(attacker_kind, target_kind, dmg, target_hp_after):
        recorder.emit(dbg.DAMAGE, attacker=attacker_kind, target=target_kind,
                      dmg=dmg, target_hp_after=target_hp_after)

    def _on_wall_damage(attacker_kind, edge, dmg, hp_after, broke):
        c1, r1, c2, r2 = edge
        recorder.emit(dbg.WALL_DAMAGE, attacker=attacker_kind, col=c1, row=r1,
                      col2=c2, row2=r2, dmg=dmg, hp_after=hp_after, broke=broke)

    def _on_defender_fire(wx, wy):
        # Emit only — deliberately NOT appending to
        # `state.defender_fire_events`: that ledger exists to be drained by the
        # FX layer, and a headless run has no FX layer to drain it.
        recorder.emit(dbg.DEFENDER_FIRE, wx=wx, wy=wy)

    built_for_round = None
    frames = 0
    frame_cap = FRAMES_PER_ROUND_CAP * max(1, rounds)
    outcome = "rounds_reached"
    # The two module-level level-2 seams are installed for the whole run (this
    # process drives exactly one world), and cleared in `finally` so an
    # exception can never leave a live hook behind for the next caller.
    set_damage_hook(_on_damage if verbose else None)
    set_wall_damage_hook(_on_wall_damage if verbose else None)
    try:
        while len(recorder.rounds) < rounds and frames < frame_cap:
            if state.state != GameState.GAMEPLAY:
                outcome = "game_over"
                break
            if _resolve_modal(session, scene):
                continue
            if state.phase == GamePhase.BUILDING:
                if built_for_round != state.round_num:
                    built_for_round = state.round_num
                    _expand_territory(world)
                    apply_policy(world, policy, recorder)
                session.end_turn()
            sim_dt = (DT * session.combat_speed
                      if state.phase == GamePhase.ENEMY else DT)
            session.pre_sim(sim_dt, scene)
            recorder.set_frame(frames)
            if state.state == GameState.GAMEPLAY and not session.frozen:
                scene.update(sim_dt)
                resolve_combat(
                    scene, world.tile_map, sim_dt, world.buildings_bal,
                    world.vfx_bal,
                    on_base_hit=session.on_base_hit,
                    on_enemy_death=session.on_enemy_death,
                    on_kidnap=session.on_kidnap,
                    dmg_bonus=story_damage_bonus(state, world.tile_map,
                                                 world.core_bal),
                    on_defender_fire=_on_defender_fire if verbose else None,
                    on_damage=_on_damage if verbose else None)
                session.post_sim(scene)
            frames += 1
        else:
            if frames >= frame_cap:
                outcome = "frame_cap"
    finally:
        set_damage_hook(None)
        set_wall_damage_hook(None)
        session.debug = None
        recorder.close(outcome=outcome)
    return recorder


def _summary_line(recorder):
    rows = recorder.rounds
    if not rows:
        return "no rounds recorded"
    total = lambda k: sum(r[k] for r in rows)  # noqa: E731
    last = rows[-1]
    return (f"rounds={len(rows)} love_end={last['love_end']} "
            f"lives_end={last['lives_end']} "
            f"income={total('income_actual')}/{total('income_potential')} "
            f"lost_to_damage={total('income_lost_to_damage')} "
            f"upkeep={total('upkeep_actual')} "
            f"dmg_dealt={total('dmg_dealt')} "
            f"dmg_taken={total('dmg_taken_buildings')} "
            f"kills={total('kills')} leaks={total('leaks')} "
            f"placed={total('buildings_placed')}")


def _parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Headless balance-sweep runner (debug mode).")
    parser.add_argument("--rounds", type=int, default=20,
                        help="how many paydays to record (default 20)")
    parser.add_argument("--strategy", choices=sorted(STRATEGIES),
                        default="greedy_defence",
                        help="build policy (game/debug/policies.py)")
    parser.add_argument("--seed", type=int, default=7,
                        help="RNG seed — the same seed replays identically")
    parser.add_argument("--level", type=int, choices=[lv for lv in LEVELS if lv],
                        default=LEVEL_BASIC,
                        help="recorder level: 1 causal trace, 2 adds combat")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default logs/)")
    parser.add_argument("--data-dir", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    recorder = run_sim(args.rounds, args.strategy, args.seed, level=args.level,
                       data_dir=args.data_dir, out_dir=args.out)
    print(f"simrun: {args.strategy} seed={args.seed} level={args.level}")
    print(f"simrun: {_summary_line(recorder)}")
    # Never let a cap pass silently: a run that recorded fewer rounds than
    # asked for looks identical to a completed one once you are reading the
    # CSV, and every per-round total above would be quietly short.
    recorded = len(recorder.rounds)
    if recorded < args.rounds:
        why = {"game_over": "the run ended (game over)",
               "frame_cap": "the per-round frame budget ran out"}.get(
                   recorder.outcome, f"outcome={recorder.outcome}")
        print(f"simrun: WARNING recorded {recorded} of {args.rounds} "
              f"requested rounds — {why}")
    for kind, path in sorted(recorder.paths.items()):
        print(f"simrun: {kind:5s} {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
