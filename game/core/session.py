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

from . import boss_bonuses as bb
from . import levelup as lv
from . import lightning as lt  # 10H
from . import payday
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
        # TU-6: optional callable, host-set (BuildingUI/on_build_vfx
        # precedent) — allows()->bool gate consulted by end_turn(). None
        # (default) = always allowed (a bare Session built by a logic test
        # never gates).
        self.tutorial_gate = None
        # TU-7: optional TutorialDirector reference, host-set alongside
        # tutorial_gate in build_gameplay() — consulted by on_base_hit() (the
        # scripted first-loss waiver) and notified by _begin_round_end(). None
        # (default) = normal rules, no notification (a bare Session built by a
        # logic test never gates/notifies).
        self.tutorial_director = None
        self._wipe_pending = False
        # (col, row, plan) death-spawn bursts to flush in post_sim (ER-3; the
        # 10G single-slot `_boss_swarm_pending` generalised — several units can
        # die in one frame). `plan` is an OPAQUE payload from the enemy's
        # `death_spawn_plan`; core never inspects it, it just hands it back.
        self._death_spawns_pending = []
        # Buildings that have already paid their death XP, by id(). NEVER reset
        # (prototype `_buildings_xp_awarded`): a building that dies, revives at
        # payday and dies again pays XP only the first time.
        self._xp_awarded_buildings = set()
        # Combat speed (10F). Persists across rounds; a new run builds a new
        # Session, which is the prototype's "reset to 1x on new game".
        self.combat_speed_idx = 0
        self._prev_combat_speed_idx = 0  # remembered speed for the pause toggle
        # -- 10H: lightning + cheat menu --------------------------------
        # How the NEXT level-up window resolves (set by _begin_levelup): the
        # natural ROUND_END path runs payday; the cheat LEVEL UP path instead
        # restores the phase it interrupted (prototype game.py:1484-1517).
        self._levelup_run_income = True
        self._levelup_return_phase = None
        # -- /10H --

    @classmethod
    def create(cls, spawner, tilemap, enemies_balance, core_balance,
               buildings_balance, registry=None, rng=None, occupancy=None):
        """Fresh session with a run-state seeded from the ``core`` balance."""
        return cls(RunState.from_balance(core_balance, buildings_balance),
                   spawner, tilemap, enemies_balance, core_balance,
                   buildings_balance, registry, rng, occupancy)

    @property
    def frozen(self):
        """LEVELUP / BOSS_CUTSCENE are fully modal: no updates, no animations,
        no combat (prototype ``_update_gameplay`` returns immediately)."""
        return self.state.phase in (GamePhase.LEVELUP, GamePhase.BOSS_CUTSCENE)

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
        # Kidnappers (Art/enemies) hold the round open exactly like a live
        # enemy — a wave-abandon must clear them too, or the round can never
        # end after this. They already paid their XP on the kidnap.
        for e in list(scene.by_tag("enemy")) + list(scene.by_tag("kidnapper")):
            scene.despawn(e)
        self.spawner.clear()
        self._wipe_pending = False
        self._begin_round_end()

    # -- 10H: lightning + cheat menu ---------------------------------------

    def lightning_strike(self, scene, cs, wx, wy, vfx_balance):
        """The ENEMY-phase left-click strike (prototype dispatch game.py:426-31
        + ``_handle_lightning_click``): only fires during a live ENEMY phase;
        locked/cooling strikes are silent no-ops inside ``lightning.strike``.
        Returns whether the bolt actually fired.

        ``vfx_balance`` (ESV-3b, required — no default, G-7): the loaded
        ``vfx.json`` dict, passed straight through to ``lightning.strike``
        for the FX marker's cosmetic fade lifetimes. Not stored on
        ``Session`` — the host already holds it and passes it per call, the
        same way it passes ``scene``/``cs``."""
        st = self.state
        if st.state != GameState.GAMEPLAY or st.phase != GamePhase.ENEMY:
            return False
        return lt.strike(st, self.core_balance, vfx_balance, scene, cs, wx, wy)

    def cheat_add_love(self, amount):
        """``+10 Love`` / ``Infinite Money`` (prototype game.py:305, 313).
        Repeatable; clamped like every currency write."""
        if self.state.state != GameState.GAMEPLAY:
            return
        self.state.add_love(amount)

    def cheat_skip_round(self, scene):
        """``Skip Round`` — ``quick_skip_combat``'s body WITHOUT its ENEMY
        guard (prototype game.py:306-308 has none): from ANY phase, wipe the
        wave paying NO XP and restart ROUND_END. The normal ROUND_END ->
        (LEVELUP if pending) -> payday flow then runs untouched — pressing it
        during ROUND_END/INCOME restarts ROUND_END for a second payday, a
        cheat corner the prototype allows (kept)."""
        if self.state.state != GameState.GAMEPLAY:
            return
        # Kidnappers hold the round open exactly like a live enemy (see
        # quick_skip_combat) — clear them too.
        for e in list(scene.by_tag("enemy")) + list(scene.by_tag("kidnapper")):
            scene.despawn(e)
        self.spawner.clear()
        self._wipe_pending = False
        self._begin_round_end()

    def cheat_goto_round(self, n, scene):
        """``Go to Round n`` (prototype game.py:311-315): clear the field +
        queue, set the round, drop to BUILDING. NO payday runs, no love
        changes, timers untouched; jumps go forward OR backward — everything
        round-derived (scale tier, era gates, speed gates) simply reads the
        new ``round_num``. Payday ordering is untouched because payday is
        simply not invoked (prototype-exact)."""
        if self.state.state != GameState.GAMEPLAY:
            return
        # Kidnappers hold the round open exactly like a live enemy (see
        # quick_skip_combat) — clear them too.
        for e in list(scene.by_tag("enemy")) + list(scene.by_tag("kidnapper")):
            scene.despawn(e)
        self.spawner.clear()
        self._wipe_pending = False
        self.state.round_num = n
        self.state.phase = GamePhase.BUILDING

    def cheat_trigger_levelup(self):
        """``LEVEL UP`` (prototype ``_cheat_trigger_levelup``, game.py:1493-99):
        always arm the pending flag; outside ENEMY/LEVELUP open the window NOW
        with the no-payday ``return_phase`` path. Mid-ENEMY only the flag is
        set — the window then fires at the natural ROUND_END with the normal
        ``run_income=True`` payday path."""
        st = self.state
        if st.state != GameState.GAMEPLAY:
            return
        st.levelup_pending = True
        if st.phase not in (GamePhase.ENEMY, GamePhase.LEVELUP):
            self._begin_levelup(run_income=False, return_phase=st.phase)

    def cheat_unlock_all(self):
        """``Unlock All Tech``: every RESEARCH type unlocked + ALL its tiers
        researched. Deliberate fix of a prototype bug: its hand-written sweep
        omitted meditator + blocker (debug tooling, not gameplay — coordination
        ruling #6). Sweeping the RESEARCH table instead can never miss a type."""
        st = self.state
        if st.state != GameState.GAMEPLAY:
            return
        # Local import — same pattern (and reason) as RunState.from_balance.
        from game.buildings.research import LEAF_CLASSES, RESEARCH

        for bt in RESEARCH:
            st.unlocked_buildings[bt] = True
            st.tiers_unlocked[bt] = len(
                LEAF_CLASSES[bt]._resolve_tiers(self.buildings_balance))

    # -- /10H ---------------------------------------------------------------

    # -- BUILDING -> ENEMY (prototype _begin_enemy_phase) -----------------

    def end_turn(self):
        """Start the current round's wave. No-op unless in BUILDING/GAMEPLAY.

        An empty wave (no spawn tiles / zero count) is fine: ``post_sim`` sees a
        drained spawner with no live enemies next and ends the round at once.
        """
        st = self.state
        if st.state != GameState.GAMEPLAY or st.phase != GamePhase.BUILDING:
            return
        if self.tutorial_gate is not None and not self.tutorial_gate():
            return  # TU-6: the guided chain still owns End Turn
        self.tilemap.set_round(st.round_num)  # 10I: damage-weight round gate
        # TU-9: fires once on the first End Turn of the run — round 0 (the
        # tutorial) or round 1 (a skipped run) alike — never keyed on
        # round_num == 1 directly any more (see game_state.py).
        if not st.first_end_turn_cutscene_requested:
            st.pending_cutscene = {"id": "first_end_turn"}
            st.first_end_turn_cutscene_requested = True
        self.spawner.begin_round(
            st.round_num, self.tilemap, self.enemies_balance,
            rng=self.rng, registry=self.registry)
        # -- 10G boss: End-Turn snapshots + announcement marker --
        # Love snapshot EVERY round (the Boss3A damage base, prototype
        # game.py:838-839); on a boss round also snapshot lives (the cutscene's
        # win/loss compare) and queue one announce marker (drained by the UI —
        # the enabled gate lives in FloaterManager, session stays ui-free).
        # TU-9: round 0 (the tutorial) is never a boss round — `0 % n == 0`
        # for every interval, so it must be excluded explicitly.
        st.boss_love_snapshot = st.love
        boss_interval = \
            self.enemies_balance["EnemyTypes"]["Boss"]["round_interval"]
        if st.round_num != 0 and st.round_num % boss_interval == 0:
            st.boss_lives_snapshot = st.base_lives
            st.boss_events.append(st.round_num)
        # -- /10G --
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
            # 10H: the lightning cooldown drains ONLY here, on the ENEMY-phase
            # sim dt the host already speed-scales (prototype game.py:1243-46):
            # 2x drains it faster, the in-combat pause freezes it, and it
            # persists frozen across BUILDING/ROUND_END/LEVELUP/INCOME.
            lt.tick(st, dt)
            self.spawner.update(dt, scene)
            self._award_building_deaths(scene)
        elif st.phase == GamePhase.ROUND_END:
            st.phase_timer -= dt
            if st.phase_timer <= 0:
                # A pending boss cutscene beats a pending level-up beats
                # payday; each modal's resolve chains into the next step
                # (prototype game.py:1215-1226 — 10G added the first arm).
                if st.pending_boss_cutscene:  # -- 10G boss --
                    self._begin_boss_cutscene()
                elif st.levelup_pending:
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
        # -- ER-3: flush every death-spawn burst BEFORE the wave-clear check, so
        # the burst is submitted to the Spawner while the round is still live.
        # Enemy construction stays in the Spawner.
        if self._death_spawns_pending:
            pending = self._death_spawns_pending
            self._death_spawns_pending = []
            for col, row, plan in pending:
                self.spawner.spawn_death_swarm(scene, col, row, plan)
        # -- /ER-3 --
        if self._wipe_pending:
            self._wipe_round(scene)
            self._begin_round_end()
        elif (self.spawner.done
                and not any(e.alive for e in scene.by_tag("enemy"))
                # ER-5: children burst THIS frame are still in the scene's spawn
                # queue (`spawn` only queues; the merge is the next `update`), so
                # `by_tag` cannot see them. Without this the last enemy of a wave
                # breaking into a swarm ends the round and orphans its children
                # into it.
                and not scene.queued_by_tag("enemy")
                # Art/enemies: a kidnapper walking home HOLDS the round open —
                # the wave cannot end until every carrier has reached a spawn
                # tile and despawned (user decision).
                and not scene.by_tag("kidnapper")
                and not scene.queued_by_tag("kidnapper")):
            self._begin_round_end()

    # -- LEVELUP (10A) ----------------------------------------------------

    def _begin_levelup(self, run_income=True, return_phase=None):
        """Open the modal window on the rolled options (prototype
        ``_begin_levelup``). The natural ROUND_END call site keeps the defaults
        (``run_income=True``); the 10H cheat LEVEL UP passes
        ``run_income=False, return_phase=<interrupted phase>`` so the resolve
        skips payday and restores that phase. The host reads
        ``state.levelup_options``."""
        st = self.state
        # -- 10H: remember how this window must resolve --
        self._levelup_run_income = run_income
        self._levelup_return_phase = return_phase
        # -- /10H --
        st.levelup_options = lv.roll_levelup_options(
            st, self.buildings_balance, self.core_balance, self.rng)
        st.phase = GamePhase.LEVELUP

    def resolve_levelup(self, option, scene=None):
        """Grant the chosen reward, advance the village level, then run the
        payday the level-up deferred (prototype ``_resolve_levelup``). ``scene``
        lets the deferred payday's Painter slot despawn a completed painter.
        The 10H cheat path (``run_income=False``) restores the interrupted
        phase INSTEAD of running payday — the village-level math is identical
        on both paths (prototype game.py:1501-1517)."""
        st = self.state
        lv.apply_levelup_option(st, option, self.core_balance)
        st.levelup_pending = False
        st.levelup_options = []
        xpmod.advance_village_level(st, self.core_balance)
        # -- 10H: the cheat return_phase path — NO payday --
        if not self._levelup_run_income:
            st.phase = self._levelup_return_phase or GamePhase.BUILDING
            self._levelup_run_income = True     # one-shot: back to the default
            self._levelup_return_phase = None
            return
        # -- /10H --
        run_payday(st, self.tilemap, self.core_balance,
                   self.occupancy, scene)  # -> INCOME

    # -- BOSS_CUTSCENE (10G) -----------------------------------------------

    def _begin_boss_cutscene(self):
        """Enter the fully modal A/B phase. ``pending_boss_cutscene`` stays set
        (the host reads boss_num/outcome to open the window on the phase edge —
        the LEVELUP pattern); ``resolve_boss_cutscene`` consumes it."""
        self.state.phase = GamePhase.BOSS_CUTSCENE

    def resolve_boss_cutscene(self, option, scene=None):
        """Apply the ``"A"``/``"B"`` choice (choice sets cycle every 3 bosses),
        log it to the run history, then chain into the LEVELUP the cutscene
        deferred — or straight to payday (prototype game.py:947-963). Payday
        runs exactly once either way."""
        st = self.state
        pending = st.pending_boss_cutscene or {}
        boss_num = pending.get("boss_num", 1)
        outcome = pending.get("outcome", "win")
        bb.apply_choice(st, (boss_num - 1) % 3, option)
        st.boss_choices.append((boss_num, option, outcome))
        st.pending_boss_cutscene = None
        if st.levelup_pending:
            self._begin_levelup()
        else:
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
        # 10J: a base-reach kill splatters too (prototype game.py:1295)
        transform = getattr(enemy, "transform", None)
        if transform is not None:
            st.enemy_death_events.append(transform.world_pos)
        st.enemies_killed += 1
        # TU-7: the scripted round-1 loss may be waived (script-toggleable,
        # `first_loss_costs_life`) — a pure read, never mutates the director.
        charge = True
        if self.tutorial_director is not None:
            charge = self.tutorial_director.charges_life_on_base_hit(
                st.round_num)
        if charge:
            st.base_lives -= 1
        if st.base_lives <= 0:
            st.state = GameState.GAME_OVER
        else:
            self._wipe_pending = True

    # -- enemy death (fed from resolve_combat's on_enemy_death) -----------

    def on_enemy_death(self, enemy):
        """An enemy was killed on the field (not at the base)."""
        # -- ER-3 death spawn: one-shot stash for ANY type carrying an ENABLED
        # `death_spawn` (10G's boss swarm is now just one instance of it).
        # Duck-typed — game/core imports nothing from game/enemies. The
        # DeathSpawn.death_spawned guard makes a second report of the same unit
        # a no-op. A unit despawned by quick-skip / a lives wipe / a cheat never
        # reaches this callback, so it spawns nothing.
        plan = getattr(enemy, "death_spawn_plan", None)
        if plan is not None and not getattr(enemy, "death_spawned", True):
            enemy.mark_death_spawned()
            wx, wy = enemy.transform.world_pos
            self._death_spawns_pending.append((round(wx), round(wy), plan))
        # -- /ER-3 --
        # 10J: every field kill leaves a ground splatter (drained-by-UI
        # ledger; the gore gates live in the FX layer, prototype game.py:1340)
        transform = getattr(enemy, "transform", None)
        if transform is not None:
            self.state.enemy_death_events.append(transform.world_pos)
        self.state.enemies_killed += 1
        self._award_enemy_xp(enemy)

    # -- kidnapping (fed from resolve_combat's on_kidnap) -----------------

    def on_kidnap(self, enemy, building, scene):
        """The mirror of ``on_enemy_death`` for a kidnap transition
        (Art/enemies): the carrier counts as dead for scoring (XP + kill
        count) but leaves NO gore/splatter (``enemy_death_events``) and no
        death-spawn burst — "no VFX" per the design. The building is gone for
        good: its tile is freed back to empty BUILDABLE ground through the
        same helper payday's own free-tile step uses, so there is no payday
        revive."""
        self.state.enemies_killed += 1
        self._award_enemy_xp(enemy)
        # A kidnapped wall builder's perimeter must be torn down explicitly:
        # payday's slot-8 teardown sweeps dead buildings still ON THE BOARD
        # and will never see one that was carried off, so its walls would
        # otherwise be orphaned.
        if getattr(building, "building_type", None) == "wall_builder":
            self.tilemap.remove_walls_for_builder(building)
        tile = self.tilemap.get(building.col, building.row)
        payday._free_tile(self.tilemap, tile, self.occupancy, scene)

    def _award_enemy_xp(self, enemy):
        amount = xpmod.xp_for_etype(getattr(enemy, "ETYPE", "standard"),
                                    self.core_balance)
        transform = getattr(enemy, "transform", None)
        xpmod.award_xp(self.state, amount,
                       transform.world_pos if transform is not None else None)

    # -- helpers ----------------------------------------------------------

    def _begin_round_end(self):
        st = self.state
        # -- 10G boss: queue the cutscene at a boss round's end (round_num is
        # still pre-increment at ROUND_END; GAME_OVER never reaches here — the
        # post_sim/on_base_hit gates stop first). Outcome compares lives to the
        # End-Turn snapshot (prototype game.py:933-938).
        # TU-9: round 0 (the tutorial) is never a boss round (see end_turn()).
        interval = self.enemies_balance["EnemyTypes"]["Boss"]["round_interval"]
        if st.round_num != 0 and st.round_num % interval == 0:
            st.pending_boss_cutscene = {
                "boss_num": st.round_num // interval,
                "outcome": ("win" if st.base_lives >= st.boss_lives_snapshot
                            else "loss"),
            }
        # -- /10G --
        st.phase = GamePhase.ROUND_END
        # TU-7: every road to ROUND_END notifies the tutorial director — a
        # no-op unless its sequencer is actually waiting on this event (the
        # scripted round-1 "wait for the loss" step).
        if self.tutorial_director is not None:
            self.tutorial_director.on_round_end(st.round_num)
        st.phase_timer = self.core_balance["PhaseLoop"]["round_end_delay"]

    def _wipe_round(self, scene):
        """A lives-mode base hit ends the round instantly: clear live enemies +
        drain the spawn queue. Enemies that were QUEUED but never spawned still
        pay their XP, so a life-loss round-clear doesn't rob the player
        (prototype game.py:1300-1303). Enemies already on the field are cleared
        silently — they grant nothing (prototype ``enemies.clear()``)."""
        # Kidnappers hold the round open exactly like a live enemy (see
        # quick_skip_combat) — clear them too; they already paid their XP.
        for e in list(scene.by_tag("enemy")) + list(scene.by_tag("kidnapper")):
            scene.despawn(e)
        for tile, etype in self.spawner.pending():
            xpmod.award_xp(self.state,
                           xpmod.xp_for_etype(etype, self.core_balance),
                           (tile.col + 0.5, tile.row + 0.5))
        self.spawner.clear()
        self._wipe_pending = False
