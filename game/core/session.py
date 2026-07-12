"""Session — the round-loop orchestrator (Phase 9F).

Owns the ``RunState`` + ``Spawner`` and drives the phase machine each frame,
mirroring the prototype's ``_update_gameplay`` dispatcher plus the
``_begin_enemy_phase`` / ``_begin_round_end`` transitions (``src/core/game.py``).
The host (``game/main.py``, and tests) calls it around the per-frame sim:

    session.pre_sim(dt, scene)      # phase timers; spawner during ENEMY; payday
    scene.update(dt)                # engine sim (movement, animations)
    resolve_combat(..., on_base_hit=session.on_base_hit)
    session.post_sim(scene)         # wave-clear / round-wipe -> ROUND_END

``BUILDING -> ENEMY`` is driven by ``end_turn()`` — the real End Turn button is
9G, so 9F triggers it from a keypress. The world FREEZES on GAME_OVER (no phase
advances, no spawning), exactly like the prototype's ``_update`` having no
GAME_OVER branch. Base-breach consequences (lives / game over / round-wipe)
arrive from the combat sweep via the ``on_base_hit`` callback, keeping
``game/enemies`` free of any ``game/core`` import (clean layering); 10A adds a
second such callback, ``on_enemy_death``, for XP + the kill counter.

Phase 10A inserts LEVELUP between ROUND_END and INCOME: at the ROUND_END timer's
expiry a pending level-up opens the modal instead of running payday, and
``resolve_levelup`` runs payday afterwards (the prototype's ``run_income=True``
path). LEVELUP freezes the world completely — the host checks ``frozen`` and
skips the whole sim, so nothing animates behind the window.
"""
import random

from . import levelup as lv
from . import xp as xpmod
from .game_state import RunState
from .payday import run_payday
from .phases import GamePhase, GameState

# Combat-phase speed multipliers, indexed by `Session.combat_speed_idx`
# (prototype `game.py:45-47`). Index 3 is the in-combat pause — a 0.0 multiplier,
# NOT a phase change, so the round machine is untouched while it holds.
COMBAT_SPEEDS = (1.0, 1.5, 2.0, 0.0)
PAUSE_SPEED_IDX = 3


class Session:
    def __init__(self, state, spawner, tilemap, enemies_balance, core_balance,
                 buildings_balance, registry=None, rng=None, occupancy=None):
        self.state = state
        self.spawner = spawner
        self.tilemap = tilemap
        self.enemies_balance = enemies_balance
        self.core_balance = core_balance
        self.buildings_balance = buildings_balance
        self.registry = registry
        self.rng = rng if rng is not None else random
        # Occupancy handle so the payday Painter slot can free a completed
        # painter's tile (clear it here as well as on the tilemap). Optional so
        # logic tests that predate it still construct a Session.
        self.occupancy = occupancy
        self._wipe_pending = False
        # Buildings that have already paid their death XP, by id(). NEVER reset
        # (prototype `_buildings_xp_awarded`): a building that dies, revives at
        # payday and dies again pays XP only the first time.
        self._xp_awarded_buildings = set()
        # Combat speed (10F). Persists across rounds; a new run builds a new
        # Session, which is the prototype's "reset to 1x on new game".
        self.combat_speed_idx = 0
        self._prev_combat_speed_idx = 0  # remembered speed for the pause toggle

    @classmethod
    def create(cls, spawner, tilemap, enemies_balance, core_balance,
               buildings_balance, registry=None, rng=None, occupancy=None):
        """Fresh session with a run-state seeded from the ``core`` balance."""
        return cls(RunState.from_balance(core_balance), spawner, tilemap,
                   enemies_balance, core_balance, buildings_balance, registry,
                   rng, occupancy)

    @property
    def frozen(self):
        """LEVELUP is fully modal: no updates, no animations, no combat
        (prototype ``_update_gameplay`` returns immediately)."""
        return self.state.phase == GamePhase.LEVELUP

    # -- combat speed (10F) -----------------------------------------------

    @property
    def combat_speed(self):
        """The multiplier the host applies to the ENEMY-phase sim tick."""
        return COMBAT_SPEEDS[self.combat_speed_idx]

    def speed_unlocked(self, idx):
        """Is this speed index selectable at the current round? 1× and the pause
        always are; 1.5× and 2× are round-gated by ``core.PhaseLoop`` (prototype
        gated only the HUD buttons — gating here instead means the keys and the
        10L buttons can't drift apart)."""
        loop = self.core_balance["PhaseLoop"]
        if idx == 1:
            return self.state.round_num >= loop["speed_1_5x_min_round"]
        if idx == 2:
            return self.state.round_num >= loop["speed_2x_min_round"]
        return True

    def set_combat_speed(self, idx):
        """Select the combat speed (prototype ``_set_combat_speed``). A locked or
        out-of-range index is a no-op. Remembers the last non-pause index so
        ``toggle_pause`` can restore it."""
        if not 0 <= idx < len(COMBAT_SPEEDS) or not self.speed_unlocked(idx):
            return
        if idx != PAUSE_SPEED_IDX:
            self._prev_combat_speed_idx = idx
        self.combat_speed_idx = idx

    def toggle_pause(self):
        """Toggle the in-combat pause, restoring the last real speed. No key is
        bound to this yet — the 10L HUD button is its control surface."""
        self.set_combat_speed(
            self._prev_combat_speed_idx
            if self.combat_speed_idx == PAUSE_SPEED_IDX else PAUSE_SPEED_IDX)

    def quick_skip_combat(self, scene):
        """``P`` — abandon the rest of the wave and jump straight to ROUND_END
        (prototype ``game.py:393-399``). Unlike a lives-breach ``_wipe_round``,
        this pays NO XP: neither the enemies cleared off the field nor the ones
        still queued (prototype awards nothing on this path)."""
        st = self.state
        if st.state != GameState.GAMEPLAY or st.phase != GamePhase.ENEMY:
            return
        for e in list(scene.by_tag("enemy")):
            scene.despawn(e)
        self.spawner.clear()
        self._wipe_pending = False
        self._begin_round_end()

    # -- BUILDING -> ENEMY (prototype _begin_enemy_phase) -----------------

    def end_turn(self):
        """Start the current round's wave. No-op unless in BUILDING/GAMEPLAY.

        An empty wave (no spawn tiles / zero count) is fine: ``post_sim`` sees a
        drained spawner with no live enemies next and ends the round at once.
        """
        st = self.state
        if st.state != GameState.GAMEPLAY or st.phase != GamePhase.BUILDING:
            return
        self.spawner.begin_round(
            st.round_num, self.tilemap, self.enemies_balance,
            rng=self.rng, registry=self.registry)
        st.phase = GamePhase.ENEMY
        self._wipe_pending = False

    # -- per-frame dispatch (prototype _update_gameplay) ------------------

    def pre_sim(self, dt, scene):
        """Advance phase timers + spawn wave enemies. Call BEFORE
        ``scene.update``. Fully frozen on GAME_OVER."""
        st = self.state
        if st.state != GameState.GAMEPLAY or self.frozen:
            return
        if st.phase == GamePhase.ENEMY:
            self.spawner.update(dt, scene)
            self._award_building_deaths(scene)
        elif st.phase == GamePhase.ROUND_END:
            st.phase_timer -= dt
            if st.phase_timer <= 0:
                # A pending level-up takes priority over payday; the window's
                # resolve runs payday afterwards (prototype game.py:1215-1226).
                if st.levelup_pending:
                    self._begin_levelup()
                else:
                    run_payday(st, self.tilemap, self.core_balance,
                               self.occupancy, scene)  # -> INCOME
        elif st.phase == GamePhase.INCOME:
            st.phase_timer -= dt
            if st.phase_timer <= 0:
                st.phase = GamePhase.BUILDING

    def post_sim(self, scene):
        """Wave-clear / base-breach handling. Call AFTER ``resolve_combat``."""
        st = self.state
        if st.state != GameState.GAMEPLAY or st.phase != GamePhase.ENEMY:
            return
        if self._wipe_pending:
            self._wipe_round(scene)
            self._begin_round_end()
        elif self.spawner.done and not any(
                e.alive for e in scene.by_tag("enemy")):
            self._begin_round_end()

    # -- LEVELUP (10A) ----------------------------------------------------

    def _begin_levelup(self):
        """Open the modal window on the rolled options (prototype
        ``_begin_levelup(run_income=True)``; the cheat ``return_phase`` path is
        10H). The host reads ``state.levelup_options``."""
        st = self.state
        st.levelup_options = lv.roll_levelup_options(
            st, self.buildings_balance, self.core_balance, self.rng)
        st.phase = GamePhase.LEVELUP

    def resolve_levelup(self, option, scene=None):
        """Grant the chosen reward, advance the village level, then run the
        payday the level-up deferred (prototype ``_resolve_levelup``). ``scene``
        lets the deferred payday's Painter slot despawn a completed painter."""
        st = self.state
        lv.apply_levelup_option(st, option, self.core_balance)
        st.levelup_pending = False
        st.levelup_options = []
        xpmod.advance_village_level(st, self.core_balance)
        run_payday(st, self.tilemap, self.core_balance,
                   self.occupancy, scene)  # -> INCOME

    # -- XP award sites (10A) ---------------------------------------------

    def _award_building_deaths(self, scene):
        """Buildings that died this tick pay XP once each, by id (prototype
        ``game.py:1378-1386``). Gated by ``core.XP.xp_from_buildings``."""
        if not self.core_balance["XP"]["xp_from_buildings"]:
            return
        per_type = self.buildings_balance["BuildingsGlobal"]["xp_on_death"]
        for b in scene.by_tag("building"):
            btype = getattr(b, "building_type", None)
            if btype == "base" or getattr(b, "alive", True):
                continue
            if id(b) in self._xp_awarded_buildings:
                continue
            self._xp_awarded_buildings.add(id(b))
            xpmod.award_xp(self.state, per_type.get(btype, 1),
                           b.transform.world_pos)

    # -- base breach (fed from resolve_combat's on_base_hit) --------------

    def on_base_hit(self, enemy):
        """An enemy reached the base (the sweep processes ONE per frame, then
        despawns it — ``base_kills_enemies``). Lose a life + wipe the round
        (game over at 0 lives)."""
        st = self.state
        if st.state == GameState.GAME_OVER:
            return  # world frozen: never drive lives negative on a late arrival
        # The base kill grants XP only when the rule allows it — awarded even on
        # the fatal hit, before the game-over check (prototype game.py:1293-99).
        if self.core_balance["XP"]["xp_on_base_damage_kill"]:
            self._award_enemy_xp(enemy)
        st.enemies_killed += 1
        st.base_lives -= 1
        if st.base_lives <= 0:
            st.state = GameState.GAME_OVER
        else:
            self._wipe_pending = True

    # -- enemy death (fed from resolve_combat's on_enemy_death) -----------

    def on_enemy_death(self, enemy):
        """An enemy was killed on the field (not at the base)."""
        self.state.enemies_killed += 1
        self._award_enemy_xp(enemy)

    def _award_enemy_xp(self, enemy):
        amount = xpmod.xp_for_etype(getattr(enemy, "ETYPE", "standard"),
                                    self.core_balance)
        transform = getattr(enemy, "transform", None)
        xpmod.award_xp(self.state, amount,
                       transform.world_pos if transform is not None else None)

    # -- helpers ----------------------------------------------------------

    def _begin_round_end(self):
        self.state.phase = GamePhase.ROUND_END
        self.state.phase_timer = \
            self.core_balance["PhaseLoop"]["round_end_delay"]

    def _wipe_round(self, scene):
        """A lives-mode base hit ends the round instantly: clear live enemies +
        drain the spawn queue. Enemies that were QUEUED but never spawned still
        pay their XP, so a life-loss round-clear doesn't rob the player
        (prototype game.py:1300-1303). Enemies already on the field are cleared
        silently — they grant nothing (prototype ``enemies.clear()``)."""
        for e in list(scene.by_tag("enemy")):
            scene.despawn(e)
        for tile, etype in self.spawner.pending():
            xpmod.award_xp(self.state,
                           xpmod.xp_for_etype(etype, self.core_balance),
                           (tile.col + 0.5, tile.row + 0.5))
        self.spawner.clear()
        self._wipe_pending = False
