"""Payday — the income phase, ordered EXACTLY like the prototype (Phase 9F).

``run_payday`` mirrors ``Game._begin_income_phase`` (``src/core/game.py``) step
for step. The ordering is SACROSANCT: later phases (10A-10G) fill the reserved
slots at their exact ordinal positions — notably the painter / boost /
wall-teardown slots MUST stay BEFORE the revive sweep so they observe a building
that died this round as ``alive == False`` (the prototype relies on this). Do
not reorder without the user.

9F drives steps 1, 2, 4, 5, 9, 11, 12 (snapshot -> base income + yield -> upkeep
clamp-0 -> revive -> round++ -> INCOME). 10C fills step 6 (the Painter payout
sweep, before revive); 10D step 7 (boosts); 10E steps 8 + 10 (walls); step 3 is
the boss story love payout (``boss_bonuses.love_bonus_income``, silent) — a
whole-board sum since the boss-upgrade rework, which DELETED the old Boss2A/2B
per-recipient fold-in from the step-4 income sweep. The income + upkeep sweeps
are duck-typed
(``yield_amount`` / ``upkeep``) exactly like the prototype, so future building
types are picked up here with no edit to this loop; the ONE exception is the
Meditator, whose streak compounding needs an ordered reset->pay->advance the
income sweep drives via ``collect_income`` (its ``yield_amount()`` stays pure).

``occupancy`` + ``scene`` are optional (logic tests omit them): the Painter slot
frees a completed painter's tile — clearing occupancy + despawning the building
GameObject — so both are threaded from the ``Session``.

``debug`` (debug-mode-telemetry Phase 2) is an optional ``DebugRecorder``,
threaded from ``Session`` exactly like ``occupancy``/``scene``: ``None`` (every
pre-existing caller/test) is a no-op — the three hooks below are the ONLY new
code, and they sit BETWEEN existing steps, never reordering them. This module
never imports ``game.debug`` — the caller hands over an object with the three
known methods (duck-typed, the ``occupancy``/``scene`` precedent) and this file
just calls them at the right ordinal position. See ``game/debug/recorder.py``'s
docstring for what each hook captures and why it must sit exactly there.
"""
from game.buildings.components import BoostEmitter, PainterProgress, RoundStats
from game.buildings.movement import process_moves
from game.map.tiles import TileState
from .boss_bonuses import love_bonus_income
from .phases import GamePhase
from .xp import scaled_base_income


def _built_tiles_with_occupant(tilemap):
    """(tile, occupant) for every BUILT tile that has an occupant (base + all
    built buildings). Tiles carry ``col``/``row`` for floater anchoring (9G)."""
    return [(t, t.occupant) for t in tilemap.built_tiles()
            if t.occupant is not None]


def _amount(building, method):
    """Duck-typed call of a zero-arg stat method; absent -> 0."""
    fn = getattr(building, method, None)
    return fn() if fn is not None else 0


def _free_tile(tilemap, tile, occupancy, scene):
    """Remove ``tile``'s building and return it to empty BUILDABLE ground
    (prototype frees ``tile.building`` + sets BUILDABLE; the content key reverts
    to the buildable-zone weight). The building GameObject is despawned from the
    scene (unlike the prototype, buildings are live scene objects); occupancy is
    cleared. Both ``occupancy`` and ``scene`` are optional for logic tests."""
    building = tile.occupant
    # Through the TileMap seam: clearing the content key changes the tile's
    # path weight, which must invalidate the pathfinder's cached flow field.
    tilemap.set_tile_content(tile, None, None)
    tilemap.set_tile_state(tile, TileState.BUILDABLE)
    if occupancy is not None:
        occupancy.clear((tile.col, tile.row))
    if scene is not None and building is not None:
        scene.despawn(building)


def _process_painters(state, tilemap, occupancy, scene):
    """Reserved payday slot 6 (prototype ``Game._process_painters``): every ALIVE
    Painter advances one progress cycle; one that reaches its threshold pays a
    large lump sum, then removes itself and permanently bars its tile. Dead
    painters are skipped here (no progress) and handled at the revive step. Runs
    BEFORE revive so a painter that died this round is not credited. A snapshot
    list is iterated so freeing tiles mid-sweep is safe."""
    for tile in list(tilemap.built_tiles()):
        b = tile.occupant
        if b is None or not getattr(b, "alive", False):
            continue
        if getattr(b, "building_type", None) != "painter":
            continue
        b.advance_progress()
        if not b.is_ready():
            continue
        payout = b.payout_amount()
        state.add_love(payout)
        state.income_events.append((tile.col, tile.row, payout, "income"))
        state.painter_events.append(
            (tile.col, tile.row, "painting finished!", "finished"))
        state.used_painter_tiles.add((tile.col, tile.row))
        _free_tile(tilemap, tile, occupancy, scene)


def _process_boosts(state, tilemap):
    """Reserved payday slot 7 (prototype ``Game._process_boosts`` + the death half
    of ``_on_boost_destroyed``): sweep every boost building on a built tile.

    An ALIVE booster in RAMP mode accumulates one turn of its stat onto its
    cardinal-adjacent combat neighbours (a floater per neighbour); in FLAT mode the
    boost was already applied at placement, so it only pays upkeep. A booster that
    DIED this round (seen here BEFORE the revive step, exactly like painters) stamps
    its one-shot explosion debuff on those neighbours — guarded by ``BoostEmitter``
    so a single death explodes once; flat mode also reverses its 10× contribution
    here. The revive step then rebuilds it and clears the guard."""
    for tile in list(tilemap.built_tiles()):
        b = tile.occupant
        if b is None or "boost" not in getattr(b, "tags", ()):
            continue
        emitter = b.get_component(BoostEmitter)
        if getattr(b, "alive", False):
            if not b.flat_mode():
                for col, row, text in b.apply_per_turn(tilemap):
                    state.boost_events.append((col, row, text))
        elif not emitter.exploded:
            if b.flat_mode() and emitter.flat_applied:
                b.remove_flat(tilemap)
                emitter.flat_applied = False
            b.apply_explosion_debuff(tilemap)
            emitter.exploded = True


def _process_wall_teardown(tilemap):
    """Reserved payday slot 8 (prototype ``Game._begin_income_phase`` teardown
    sweep): every WallBuilder that DIED this round has its perimeter walls torn
    down. Runs BEFORE revive so a builder about to be revived is still seen as
    ``alive == False`` (same pattern as painters / boosts). A revived builder's
    walls are then restored in slot 10; only a builder that stays dead (revive
    off) loses its walls for good."""
    for tile in list(tilemap.built_tiles()):
        b = tile.occupant
        if (b is not None
                and getattr(b, "building_type", None) == "wall_builder"
                and not getattr(b, "alive", False)):
            tilemap.remove_walls_for_builder(b)


def run_payday(state, tilemap, core_balance, occupancy=None, scene=None,
               debug=None):
    hole = core_balance["TheHole"]
    built = _built_tiles_with_occupant(tilemap)
    buildings = [b for _, b in built]

    # 1. Reset income floaters — the per-tile ledger the 9G UI reads to spawn
    #    income/upkeep floaters (gated by ui.FX.income_floaters_enabled). Filled
    #    in steps 4 (income) + 5 (upkeep) below; the floater VFX itself is 9G.
    state.income_events.clear()

    # debug-mode-telemetry: captured BEFORE step 2 zeroes RoundStats, so the
    # damage totals + the potential ledger both still see this round's true
    # numbers. Observation only — reads yield_amount(), never collect_income().
    if debug is not None:
        debug.on_payday_start(state, tilemap, core_balance, built)

    # 2. Snapshot RoundStats: roll this-round -> last-round, then zero. Covers
    #    the base + every building (all sit on BUILT tiles). MUST be first — the
    #    reserved Boss3B bonus reads ``dmg_dealt_last_round``.
    for b in buildings:
        rs = b.get_component(RoundStats)
        if rs is None:
            continue
        rs.dmg_taken_last_round = rs.dmg_taken_this_round
        rs.dmg_dealt_last_round = rs.dmg_dealt_this_round
        rs.dmg_taken_this_round = 0
        rs.dmg_dealt_this_round = 0

    # 3. Boss-bonus love payout, Boss2A / Boss2B. A whole-board sum, AFTER the
    #    snapshot and BEFORE base income (slot position unchanged from 10G).
    #    Paid silently: NO income_events floater.
    story = love_bonus_income(state, tilemap, core_balance)
    if story > 0:
        state.add_love(story)

    # debug-mode-telemetry: immediately after step 3 — story_income is
    # measured as the exact love delta across this ONE step, since the
    # Boss1B/3B payouts leave no income_events trace to split later.
    if debug is not None:
        debug.on_payday_story(state)

    # 4. Base income + yield sweep. Base income is always paid, scaled by the
    #    village level (10A). Then a duck-typed sweep adds each alive economy
    #    building's yield. Each payout is recorded as a floater event anchored
    #    on the paying tile.
    base_income = scaled_base_income(state, core_balance)
    state.add_love(base_income)
    state.income_events.append(
        (tilemap.base_col, tilemap.base_row, base_income, "income"))
    for tile, b in built:
        if not getattr(b, "alive", False):
            continue
        # Meditators compound: a dedicated income-time method resets the streak
        # if the building took damage this round (its RoundStats was rolled
        # this->last in the snapshot above), pays the current streak, then
        # advances it — the prototype's read-once yield_amount side-effect made
        # explicit (yield_amount() itself stays pure for the UI/HUD).
        collect = getattr(b, "collect_income", None)
        if collect is not None:
            rs = b.get_component(RoundStats)
            disturbed = rs is not None and rs.dmg_taken_last_round > 0
            amount = collect(disturbed)
        else:
            amount = _amount(b, "yield_amount")
        if amount > 0:
            state.add_love(amount)
            state.income_events.append((tile.col, tile.row, amount, "income"))

    # 5. Upkeep sweep. Mirror of income: every alive building is asked for its
    #    upkeep(); the total is deducted, love clamped at 0 (bills never push it
    #    negative — the prototype logs any shortfall; the log is 9G).
    total_upkeep = 0
    for tile, b in built:
        if not getattr(b, "alive", False):
            continue
        up = _amount(b, "upkeep")
        if up > 0:
            total_upkeep += up
            state.income_events.append((tile.col, tile.row, -up, "upkeep"))
    if total_upkeep > 0:
        state.spend_love(total_upkeep)

    # 6. Painter payout sweep — BEFORE revive (10C).
    _process_painters(state, tilemap, occupancy, scene)

    # debug-mode-telemetry: immediately after step 6 — income_events now holds
    # base + yields + upkeep + painter payouts, and round_num has not yet been
    # incremented (step 11). This is also where the recorder appends the
    # finished round row and emits round_summary/payday internally.
    if debug is not None:
        debug.on_payday_end(state, tilemap)

    # 7. Boost sweep — BEFORE revive (10D): alive boosters accumulate their
    #    per-turn buff, dead boosters explode their debuff onto neighbours.
    _process_boosts(state, tilemap)
    # 8. Wall-teardown for dead wall-builders — BEFORE revive (10E): a builder
    #    that died this round loses its perimeter walls now; a revived one gets
    #    them back in slot 10.
    _process_wall_teardown(tilemap)

    # 9. Revive / heal: every non-base building full-heals (revives if dead).
    #    ``BaseBuilding.rebuild`` is a no-op — the base never revives. A Painter
    #    that DIED before payout is handled here instead of reviving: if it is
    #    gone-for-good (every current tier) it is removed with a "painting lost!"
    #    message and its tile freed (NOT barred — a lost tile can be reused);
    #    otherwise its progress resets and it revives like any building.
    if hole["building_revive"]:
        for tile, b in list(built):
            if getattr(b, "building_type", None) == "base":
                continue
            if (b.building_type == "painter"
                    and not getattr(b, "alive", True)):
                if b.goneforgood():
                    state.painter_events.append(
                        (tile.col, tile.row, "painting lost!", "lost"))
                    _free_tile(tilemap, tile, occupancy, scene)
                    continue
                b.get_component(PainterProgress).progress = 0
            b.rebuild()

    # 10. Rebuild walls (10E): every alive WallBuilder restores its frozen
    #     perimeter to full HP — walls damaged during the round regenerate, and a
    #     builder revived at step 9 gets the walls torn down at step 8 back.
    tilemap.rebuild_walls()

    # 10b. Building Movement: tick every in-transit building down one round and
    #      land the ones that arrive. A pure APPEND at the tail of the existing
    #      order — nothing above it moved. It sits AFTER revive on purpose: an
    #      arriving building is spawned back into the scene here, so it was
    #      never a candidate for steps 7-9's sweeps this payday (it holds no
    #      tile while in transit), and it starts its first round on the new tile
    #      fully healed like any other building at this point.
    process_moves(tilemap, occupancy, scene)

    # 11. round++
    state.round_num += 1

    # 12. phase -> INCOME, start the payday-floater timer.
    state.phase = GamePhase.INCOME
    state.phase_timer = core_balance["PhaseLoop"]["income_phase_duration"]
