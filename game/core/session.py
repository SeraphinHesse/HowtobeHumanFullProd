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
``game/enemies`` free of any ``game/core`` import (clean layering).
"""
from .game_state import RunState
from .payday import run_payday
from .phases import GamePhase, GameState


class Session:
    def __init__(self, state, spawner, tilemap, enemies_balance, core_balance,
                 registry=None, rng=None):
        self.state = state
        self.spawner = spawner
        self.tilemap = tilemap
        self.enemies_balance = enemies_balance
        self.core_balance = core_balance
        self.registry = registry
        self.rng = rng
        self._wipe_pending = False

    @classmethod
    def create(cls, spawner, tilemap, enemies_balance, core_balance,
               registry=None, rng=None):
        """Fresh session with a run-state seeded from the ``core`` balance."""
        return cls(RunState.from_balance(core_balance), spawner, tilemap,
                   enemies_balance, core_balance, registry, rng)

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
        if st.state != GameState.GAMEPLAY:
            return
        if st.phase == GamePhase.ENEMY:
            self.spawner.update(dt, scene)
        elif st.phase == GamePhase.ROUND_END:
            st.phase_timer -= dt
            if st.phase_timer <= 0:
                run_payday(st, self.tilemap, self.core_balance)  # -> INCOME
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

    # -- base breach (fed from resolve_combat's on_base_hit) --------------

    def on_base_hit(self, enemy):
        """An enemy reached the base (the sweep processes ONE per frame, then
        despawns it — ``base_kills_enemies``). Lose a life + wipe the round
        (game over at 0 lives)."""
        st = self.state
        if st.state == GameState.GAME_OVER:
            return  # world frozen: never drive lives negative on a late arrival
        st.enemies_killed += 1
        st.base_lives -= 1
        if st.base_lives <= 0:
            st.state = GameState.GAME_OVER
        else:
            self._wipe_pending = True

    # -- helpers ----------------------------------------------------------

    def _begin_round_end(self):
        self.state.phase = GamePhase.ROUND_END
        self.state.phase_timer = \
            self.core_balance["PhaseLoop"]["round_end_delay"]

    def _wipe_round(self, scene):
        """A lives-mode base hit ends the round instantly: clear live enemies +
        drain the spawn queue (the prototype awards queued-enemy XP here — 10A)."""
        for e in list(scene.by_tag("enemy")):
            scene.despawn(e)
        self.spawner.clear()
        self._wipe_pending = False
