# Phase 10H Brief — Lightning Strike + Cheat Menu

> Coordination artifact for the 10G–10I subagent batch. Planner fills §1–§4;
> orchestrator reconciles §3 across the three briefs; coder treats §3 as a hard
> boundary; reviewer verifies the diff against §1/§2/§4.

**Phase goal (MIGRATION_PLAN.md 10H):** lightning unlock/upgrade at base-info
panel, click-to-strike + effect + cooldown HUD; full cheat menu (Ctrl+L).

## Known repo state (verified at umbrella base — do not re-derive)

- Balancing data DONE: `data/balancing/core.json` → `LightningStrike`
  (`cooldown[3]`, `damage[3]`, `radius[3]`, `max_level:3`, `unlock_cost:20`,
  `upgrade_costs[2]`); schema complete. No cheat-menu balancing subtree exists
  (cheats are debug UI; `ui.Debug.*` exists if a toggle is truly needed).
- Reserved hook: the cheat `return_phase` path in
  `game/core/session.py:130` is explicitly reserved for 10H.
- Templates: `game/ui/levelup.py` + `game/ui/game_over.py` = modal template
  (open/layout/update/hit/submit, top of click ladder, swallows keys);
  `game/ui/effects.py` shows world-anchored VFX + AOE application patterns
  (`ProjectileAOE`/`Crater` splash in `game/enemies/combat.py`); HUD readouts
  belong in `game/ui/hud.py` (docstring reserves "boss/lightning readouts").
- main.py click ladder `game/main.py:271-285` (lightning click-to-strike
  inserts during ENEMY phase), key handling near `:363` (Ctrl+L; combat-speed
  keys 1/2/3/P already live there from 10F).
- `game/ui` is pygame-free (TestPurity); `game.ui → game.core` one-way;
  balancing via `game/core/balance.py` only.

## 1. Behavioral spec (planner)

All prototype citations are into `../HowToBeHuman/ClaudePrototype/HowToBeHuman`
(READ-ONLY). **The live `balancing/Balancing_Core.json` values win over the
`.py` defaults** — and they DIFFER here, so beware stale docs:

| key | live JSON (`Balancing_Core.json:29-34`) — AUTHORITATIVE | stale `.py` default (`balancing_core.py:56-61`) |
|---|---|---|
| `LIGHTNING_MAX_LEVEL` | 3 | 3 |
| `LIGHTNING_UNLOCK_COST` | 20 | 20 |
| `LIGHTNING_UPGRADE_COSTS` | **[35, 80]** (L1→2 = 35, L2→3 = 80) | [25, 35] |
| `LIGHTNING_DAMAGE` | **[10, 15, 32]** (×10-scale field; live values verbatim) | [30, 350, 500] |
| `LIGHTNING_RADIUS` | **[1, 2, 3]** tiles | [2, 3, 4] |
| `LIGHTNING_COOLDOWN` | **[5, 3, 2]** s | [1.0, 15.0, 10.0] |

`MIGRATION_AGENT_READ_FIRST.md` §4 quotes the stale `.py` numbers — ignore
them. This repo's `data/balancing/core.json LightningStrike` already matches
the live JSON exactly (verified: cooldown [5,3,2], damage [10,15,32], radius
[1,2,3], unlock 20, upgrade_costs [35,80]). **No balancing change needed.**

### 1.1 Lightning — ability state

- Two state fields on the prototype `Game`: `lightning_level` (0 = locked,
  1–3 = active) and `lightning_cooldown_timer` (`game.py:116-119`).
- **Starts at level 1.** `__init__` sets `lightning_level = 1`
  (`game.py:117`) and `_start_new_game` (`game.py:747-810`) never resets it —
  so in the live prototype every run begins with lightning already unlocked at
  L1, and the L0 "unlock for 20♥" branch is unreachable from a normal boot
  (dead code kept alive by the panel + `upgrade_lightning`). Rebuild: seed
  `lightning_level = 1` in a fresh `RunState`; keep the L0 unlock branch
  implemented (it is 3 lines and the data key exists). A fresh `Session` per
  run also erases the prototype's quirk of lightning upgrades persisting
  across "new game" in the same app session — same treatment 10F gave combat
  speed. (Open question below if the user prefers a locked start.)

### 1.2 Unlock / upgrade (base-info panel)

- `upgrade_lightning` (`game.py:517-526`): cost = `unlock_cost` at L0, else
  `upgrade_costs[level-1]`; at `max_level` → no-op; applies only if
  `currency >= cost` (deduct, `level += 1`). The cooldown timer is NOT
  touched by an upgrade.
- Base-info panel section (`src/ui/building_ui.py:1194-1243`), drawn under the
  base stat rows: divider → header `⚡ LIGHTNING STRIKE` in (255,240,80) →
  - L0: dim line `LOCKED — upgrade at The Hole`;
  - L1+: `Level {lvl} / 3` + three label/value rows: `DMG` =
    `damage[lvl-1]`, `Radius` = `{radius[lvl-1]} tiles`, `Atk Spd` =
    `{cooldown[lvl-1]:.1f}s`.
- Button (`building_ui.py:825-836`, click handling `:804-816`): label
  `UNLOCK LIGHTNING ♥20` at L0 else `UPGRADE LIGHTNING ♥{cost}`; clicking
  with insufficient love flashes the NOT-ENOUGH-LOVE red button
  (`:1235-1238`); at max level the button disappears and a gold `MAX LEVEL`
  line replaces it (`:1241-1243`).

### 1.3 Click-to-strike

- Dispatch (`game.py:426-431`): a LEFT mouse-up that was not a camera drag —
  BUILDING phase → tile click; **ENEMY phase → lightning click**. No other
  phase fires it. UI clicks (HUD buttons, open panels, modals) are consumed
  higher in the event ladder and never reach it.
- `_handle_lightning_click` (`game.py:492-500`): silent no-op if
  `lightning_level <= 0` **or** `lightning_cooldown_timer > 0`; otherwise the
  click converts to world coordinates and strikes. Any world point is a valid
  target — no tile/zone/bounds check, no enemies-required check.
- `_activate_lightning` (`game.py:502-514`):
  - `dmg = LIGHTNING_DAMAGE[level-1]`, applied FLAT via `e.take_damage(dmg)`
    to EVERY enemy in radius — no falloff, no target cap, no love cost.
  - **Radius semantics — a circle in the PROJECTED pixel plane, not tile
    space** (`game.py:505-508`): `radius_px = LIGHTNING_RADIUS[level-1] *
    TILE_HW` where `TILE_HW = 32` = half the iso tile WIDTH
    (`constants.py:9-11`); hit test is Euclidean on world-PIXEL coords:
    `(e.wx - wx)² + (e.wy - wy)² <= radius_px²`. Because iso x-steps are 32 px
    and y-steps 16 px per tile, this is an ellipse on the ground plane (≈2
    tiles wide along the screen-horizontal diagonal per radius unit, ≈1 along
    the vertical) — i.e. "what looks near the click on screen". It is NOT the
    Chebyshev-square defender range and NOT tile-space Euclidean like the
    mortar splash (`combat.py ProjectileArc._impact`). Port as: project both
    strike point and enemy through `engine.coords` `world_to_screen` and
    compare screen distance against `radius_tiles * geometry.tile_w/2 *
    camera.zoom` (pan cancels in the delta; zoom scales linearly — exact, and
    iso math stays inside the coords authority).
  - Cooldown is set to `LIGHTNING_COOLDOWN[level-1]` **unconditionally** —
    a whiff that hits nothing still spends the full cooldown and still plays
    the VFX.
  - Kills flow through the normal enemy-death sweep, so they pay XP and count
    as kills like any other kill (rebuild: the dead enemy is picked up by the
    next `resolve_combat` pass → `on_enemy_death` → XP; zero extra wiring).
- **Cooldown ticks ONLY during the ENEMY phase, on the combat-speed-scaled
  dt** (`game.py:1243-1246`, fed `dt * COMBAT_SPEEDS[idx]` at `:1211-1213`):
  2× drains it twice as fast, the in-combat pause freezes it, and it does not
  drain at all during BUILDING/ROUND_END/INCOME/LEVELUP (it persists, frozen,
  across rounds — never reset at round end or on upgrade).

### 1.4 Strike VFX (`src/effects.py:222-289`, `LightningEffect`)

- Spawned per strike with `(wx, wy, radius_px, crater_dur)` where
  `crater_dur = AOE_DEF_CRATER_DURATION = 1.0 s` (`balancing_buildings.py:164`;
  `getattr` default 1.0 at `game.py:513` — this repo's precedent is the code
  constant `CRATER_LIFE = 1.0` in `game/enemies/combat.py:42`).
- Three parts, world-anchored: (1) **bolt** — jagged 8-segment polyline from
  the top of the screen (y=0) down to the impact point, ±6 px horizontal
  jitter re-rolled every frame, white→yellow colour fading out over
  `life = 0.5 s`; (2) **impact flash** — expanding circle `r = progress*20 px`,
  alpha gone by progress 0.5; (3) **ground marker** — squashed ellipse sized
  to the real blast radius (w = 2r, h = r), fill (255,240,120)/outline
  (255,255,200), fading over `crater_dur` exactly like the mortar crater.
- Effects update on the same scaled ENEMY dt (`game.py:1247-1250`) and are
  force-cleared at `_begin_round_end` (`game.py:943`).
- Rebuild primitives have no per-pixel alpha and no filled-circle: bolt =
  screen-space `HudLines`, ground marker = fading overlay-lines diamond (the
  `submit_craters` pattern); the alpha flash circle is 10J polish (same
  accepted divergence class as the opaque level-up backdrop).

### 1.5 Cooldown HUD indicator (`game.py:1829-1863`, drawn at `:2048-2049`)

- Shown **only while `phase == ENEMY` and `lightning_level > 0`**.
- Bottom-left label on a dark backing (0,0,0,140): ready →
  `⚡ CLICK TO STRIKE` in (255,240,80); cooling →
  `⚡ {timer:.1f}s` in (120,120,140).
- Plus a tiny cursor-attached progress bar: 22×3 px at
  `(mouse_x - 11, mouse_y + 16)`, black alpha-140 track, white fill with
  fraction `1 - timer/cooldown[level-1]` (full = ready).
- Rebuild: opaque dark backing (no alpha in the HUD pass — 10J note).

### 1.6 Cheat menu (`src/ui/cheat_menu.py` + `game.py:293-318`)

- **Hotkey — the docs disagree; the code says Ctrl+P.** Prototype toggle is
  `Ctrl+P` (`game.py:293-300`; `cheat_menu.py:2` docstring). MIGRATION_PLAN.md
  10H line (`MIGRATION_PLAN.md:99`) mandates **Ctrl+L** for the rebuild.
  **Implement Ctrl+L**: the plan line is the binding scope statement for this
  phase (echoed by this brief's header), and in this repo bare `P` is already
  the quick-skip key (10F) — a mistimed Ctrl+P would silently throw away a
  whole wave. Deliberate, documented divergence from the prototype code.
- **Availability**: gameplay only — the toggle lives in `_handle_gameplay`,
  works in ANY gameplay phase and even over the LEVELUP modal (the Ctrl+P
  branch precedes the LEVELUP-modal branch, `game.py:293-325`); NOT available
  on the game-over screen (separate handler `:286-289`) nor in pause/menus.
  While open it consumes ALL input (`game.py:302-318`) and renders on top of
  everything (`game.py:2061-2062`). Esc closes it.
- **Layout** (`cheat_menu.py:16-46,141-185`): full-screen dim (0,0,0,150)
  overlay; centred 220×258 panel titled `CHEATS`; X close top-right; five
  stacked buttons — `+10 Love`, `Skip Round`, `LEVEL UP`, `Infinite Money`,
  `Unlock All Tech`; divider; `Jump to round:` label over a click-to-focus
  digit field (max 4 digits, backspace edits, gold border while focused,
  Enter commits) and a `Go to Round` confirm button.
- **Stays-open rule** (`cheat_menu.py:49-56`): the menu stays open after
  `+10 Love` / `Skip Round` / `Infinite Money` / `Unlock All Tech`; it closes
  on X/Esc, on `LEVEL UP`, and on a successful `Go to Round`
  (`_commit`, `:130-138`: requires an int ≥ 1; empty/invalid input = no-op,
  menu stays open).
- **Exact effects** (host side, `game.py:305-317`):
  - **+10 Love** — `currency += 10`. Repeatable.
  - **Skip Round** — `enemies.clear(); _spawn_queue.clear();
    _begin_round_end()`, from ANY phase (no guard). Mid-ENEMY this wipes the
    wave paying **no XP** (same as bare-`P` quick-skip); the normal ROUND_END
    → (LEVELUP if pending) → payday flow then runs untouched, so `round_num++`
    happens inside payday with the sacrosanct ordering intact. Pressing it
    during ROUND_END/INCOME restarts ROUND_END (a second payday — a cheat
    corner the prototype allows; keep it).
  - **LEVEL UP** (`_cheat_trigger_levelup`, `game.py:1493-1499`): set
    `levelup_pending = True`, close the menu; if the phase is NOT in
    (ENEMY, LEVELUP) → `_begin_levelup(run_income=False,
    return_phase=<current phase>)`: the modal opens immediately and
    `_resolve_levelup` (`game.py:1501-1517`) **restores the saved phase
    instead of running payday** (`:1514-1517`) — this is the reserved
    `return_phase` path in `game/core/session.py`. Mid-ENEMY it only flags
    pending; the window then fires at the natural ROUND_END with the normal
    `run_income=True` payday path. Village level / threshold / XP-remainder
    math is identical on both paths.
  - **Infinite Money** (`cheat_menu.py:13,109-111`) —
    `currency += 999999`; applied immediately, repeatable, menu stays open.
  - **Unlock All Tech** (`cheat_menu.py:113-128`) — every
    `unlocked_buildings` key → True; tier research set to 3 for defence,
    economic, aoe_defence, painter, sun_scorcher, boost_speed/damage/hp,
    wall_builder. **Prototype bug: it omits `meditator` and `blocker`** —
    meditator stays at 0 researched tiers and remains unplaceable. Rebuild:
    sweep the `game/buildings/research.py RESEARCH` table instead, setting
    `unlocked_buildings[bt] = True` and `tiers_unlocked[bt] = <that type's
    total tier count from buildings.json>` for EVERY type — a deliberate,
    documented fix (debug tooling, not gameplay).
  - **Go to Round n** (`game.py:311-315`) — `enemies.clear();
    _spawn_queue.clear(); round_num = n; phase = BUILDING`. No payday runs,
    no love changes, timers untouched; jumps may go forward OR backward;
    everything round-derived (enemy scale tier, era gates, speed gates,
    zoom) simply reads the new `round_num`. Payday ordering is untouched
    because payday is simply not invoked (prototype-exact).

## 2. Architecture plan (planner)

Layering: ability state + all rules in `game/core`; menus/panels/HUD/VFX
emission in `game/ui` (pygame-free); the host (`game/main.py`) routes input
and maps UI action strings onto `Session` methods — the same split the
prototype has between `CheatMenu.handle_event` returning actions and `Game`
applying them.

### Files to CREATE

- **`game/core/lightning.py`** (pure; imports `engine.core` only — NOT
  `game/enemies`, keeping core free of that package):
  - Pure functions over `RunState` + `core_balance["LightningStrike"]`:
    `next_cost(state, core) -> int | None` (unlock cost at L0, else
    `upgrade_costs[level-1]`, None at max — `game.py:517-523`);
    `upgrade(state, core) -> bool` (love gate, spend via `state.spend_love`,
    `level += 1` — `game.py:524-526`); `tick(state, dt)` (drain toward 0,
    `game.py:1245-1246`); `can_strike(state)` (level > 0 and cooldown ≤ 0,
    `game.py:493`); `strike(state, core, scene, cs, wx, wy) -> bool` — guard
    `can_strike`, damage every alive `"enemy"`-tagged object whose
    `cs.world_to_screen` distance from the strike point ≤
    `radius_tiles * cs.geometry.tile_w / 2 * cs.camera.zoom` (§1.3), via
    `Health.damage` (the `ProjectileArc._impact` scene-query pattern,
    `combat.py:152-165` — no `RoundStats` credit: lightning has no shooter),
    set the cooldown unconditionally, spawn the FX object, return whether it
    fired.
  - `LightningFX(GameObject)` (tag `"lightning_fx"`, overlay layer) +
    `LightningFXFade(Component)` — mirror of `Crater`/`CraterFade`
    (`combat.py:184-227`): fields `radius_tiles`, `age`; code constants
    `BOLT_LIFE = 0.5`, `MARKER_LIFE = 1.0` (prototype `effects.py:232` + §1.4;
    same "cosmetic constant, not balancing" precedent as `CRATER_LIFE`);
    ages in `scene.update` (so it ticks on the host's ENEMY-scaled `sim_dt`,
    prototype-exact) and self-despawns at `MARKER_LIFE`.
- **`game/ui/cheat_menu.py`** (pure, the `game_over.py`/`levelup.py` modal
  template): `CheatMenu(view_w, view_h)` with `visible`, `open()/close()/
  toggle()`, `layout`, `update(dt, mx, my)`, `handle_key(char, key) ->
  action | None` (Esc → `"close"`; digit/backspace/return editing for the
  round field), `hit(mx, my) -> action | None`, `submit(renderer, view_w,
  view_h)`. Actions: `"close"`, `"add_love"`, `"skip_round"`,
  `"trigger_levelup"`, `"inf_money"`, `"unlock_all"`, `("goto_round", n)`.
  All effects are applied by the HOST via `Session` — the menu never mutates
  game state (uniform, unlike the prototype's two in-menu appliers; the
  stays-open semantics are preserved by the host simply not closing it).
  Opaque backdrop instead of the alpha dim (10J note). Uses `widgets.Button`
  + palette.
- **`tools/tests/test_lightning.py`** — see §4.

### Files to MODIFY

- **`game/core/game_state.py`** — `RunState` gains two fields:
  `lightning_level: int = 1` (§1.1 seed; comment citing `game.py:117` + the
  never-reset quirk) and `lightning_cooldown: float = 0.0`. No
  `from_balance` change (the seed is structural, like `combat_speed_idx`).
- **`game/core/session.py`** (SHARED — §3 contract): lightning tick in
  `pre_sim`, the `_begin_levelup`/`resolve_levelup` `return_phase` branch,
  and one fenced block of delegate methods: `lightning_strike(scene, cs, wx,
  wy)`, `cheat_add_love(amount)`, `cheat_skip_round(scene)`,
  `cheat_goto_round(n, scene)`, `cheat_trigger_levelup()`,
  `cheat_unlock_all()`. All cheat methods no-op unless
  `state.state == GameState.GAMEPLAY`. `cheat_skip_round` = despawn enemies +
  `spawner.clear()` + `_wipe_pending = False` + `_begin_round_end()` (no XP —
  reuse/mirror `quick_skip_combat`'s body WITHOUT its ENEMY-phase guard,
  §1.6). `cheat_goto_round` = despawn enemies + `spawner.clear()` +
  `state.round_num = n` + `state.phase = GamePhase.BUILDING` +
  `_wipe_pending = False`. `cheat_unlock_all` sweeps `RESEARCH` +
  `LEAF_CLASSES[bt]._resolve_tiers(self.buildings_balance)` lengths (local
  import, same pattern as `RunState.from_balance`).
- **`game/ui/building_ui.py`** — base_info mode grows the lightning section:
  a `self.lightning_btn` built in `open_for_tile`'s base_info branch (and
  rebuilt after a successful upgrade), a base_info branch in `handle_click`
  (currently falls straight to the consume-inside-panel return) calling
  `lightning.next_cost`/`session` love gate → `lightning.upgrade` or
  NOT-ENOUGH-LOVE flash, a tick in `update`, and the §1.2 rows/button/`MAX
  LEVEL` line in `_submit_base_info`. Reads via `game.core.lightning`
  (sanctioned ui→core direction).
- **`game/ui/hud.py`** (SHARED — §3 contract): store `self._mx/_my` in
  `update`; append a `_submit_lightning(renderer, session)` section to
  `submit` — §1.5 label + cursor bar, gated `phase == ENEMY and
  state.lightning_level > 0`; full-cooldown denominator from
  `session.core_balance["LightningStrike"]["cooldown"][level-1]`.
- **`game/ui/effects.py`** — `FloaterManager.submit_lightning(renderer, cs,
  scene)` mirroring `submit_craters`: for each `"lightning_fx"` scene object
  draw (a) the bolt as screen-space `HudLines` from `(sx, 0)` to the impact
  with per-frame ±6 px jitter (stdlib `random` — pure), colour fading
  white→yellow while `age < BOLT_LIFE`; (b) the ground marker as a fading
  yellow overlay-lines diamond sized `radius_tiles` (crater pattern) until
  `MARKER_LIFE`. Flash circle omitted (10J).
- **`game/main.py`** (SHARED — §3 contract): Ctrl+L toggle + cheat key
  routing + a `_execute_cheat(action)` helper; cheat-menu click consumption at
  the top of the ladder; ENEMY-phase strike at the ladder bottom;
  `gp["cheat"]` lifecycle; `submit_lightning` + cheat-menu render calls.
  `_execute_cheat` maps actions → `Session` cheat methods and, when a
  phase-changing action (`skip_round`/`goto_round`/`trigger_levelup` resolve)
  leaves LEVELUP, closes `gp["levelup"]` so no orphaned modal lingers
  (`levelup_pending` survives, so the window re-opens at the next ROUND_END —
  the prototype's pending-flag behavior).
- **`game/core/CLAUDE.md` + `game/ui/CLAUDE.md`** — exit-gate doc updates
  (new modules + the return_phase path now live).

**No data/ changes**: all lightning tunables exist in `core.json`; cheats get
no balancing subtree (prototype has none; always available in gameplay, like
the prototype); no new sprite slots (bolt/marker are line art).

### Data flow (one frame, ENEMY phase)

click → host ladder (cheat? panel? HUD?) → `session.lightning_strike(scene,
cs, wx, wy)` → `game.core.lightning.strike` damages enemies + sets
`state.lightning_cooldown` + spawns `LightningFX` → next `resolve_combat`
despawns lightning-killed enemies via `on_enemy_death` (XP/kills) →
`scene.update(sim_dt)` ages the FX → `effects.submit_lightning` draws it →
`hud._submit_lightning` shows the timer. `session.pre_sim(sim_dt)` drains the
cooldown only in its ENEMY branch — the host already passes the speed-scaled
`sim_dt` there, giving the prototype's scaled/frozen cooldown for free.

## 3. File scope + shared-file contract (planner → orchestrator reconciles)

10G lands BEFORE this phase and 10I after; every anchor below is
function-relative (not line-absolute) — expect to rebase onto 10G's landed
diff. Each shared-file insertion is ONE clearly fenced block
(`# -- 10H: lightning + cheat menu --` … `# -- /10H --`).

**Full touchable set (exhaustive):**

| file | kind |
|---|---|
| `game/core/lightning.py` | create |
| `game/ui/cheat_menu.py` | create |
| `tools/tests/test_lightning.py` | create |
| `game/core/game_state.py` | modify (2 fields, RunState block) |
| `game/core/session.py` | modify — SHARED, contract below |
| `game/ui/building_ui.py` | modify (base_info mode only) |
| `game/ui/hud.py` | modify — SHARED, contract below |
| `game/ui/effects.py` | modify (one new submit method) |
| `game/main.py` | modify — SHARED, contract below |
| `game/ui/__init__.py` | modify (one line: export `CheatMenu` — orchestrator addition) |
| `game/core/CLAUDE.md`, `game/ui/CLAUDE.md` | modify (doc exit gate) |

> **Orchestrator:** also read `docs/briefs/phase-10g-i-coordination.md` —
> cross-phase file matrix + rulings; it wins over this brief on conflicts.

Off-limits: everything else — notably `game/enemies/**`, `game/map/**`,
`game/buildings/**` (research.py is READ, not edited), `data/**`,
`engine/**`, `game/ui/levelup.py`, `game/ui/shell.py`.

### `game/core/session.py` (shared with 10G)

1. **Imports**: add `from . import lightning as lt` beside the existing
   `from . import levelup as lv` import block.
2. **`pre_sim`** — inside the `if st.phase == GamePhase.ENEMY:` branch,
   FIRST statement (before `self.spawner.update(dt, scene)`): one line
   `lt.tick(st, dt)` (prototype ticks the cooldown at the top of
   `_update_enemy_phase`, `game.py:1244-1246`).
3. **`_begin_levelup` / `resolve_levelup`** — the reserved cheat path
   (docstring at `session.py:190-192` / `game/core/CLAUDE.md`):
   `_begin_levelup(run_income=True, return_phase=None)` stores
   `self._levelup_run_income` / `self._levelup_return_phase`;
   `resolve_levelup`'s tail becomes `if self._levelup_run_income:
   run_payday(...)` `else: st.phase = self._levelup_return_phase or
   GamePhase.BUILDING` (prototype `game.py:1484-1517`). The natural
   ROUND_END call site keeps its defaults — zero behavior change there.
4. **One fenced method block** inserted immediately AFTER
   `quick_skip_combat` (i.e. between it and the `end_turn` section header):
   `lightning_strike`, `cheat_add_love`, `cheat_skip_round`,
   `cheat_goto_round`, `cheat_trigger_levelup`, `cheat_unlock_all` (§2
   semantics). 10G's expected edits (`_begin_round_end` boss queueing,
   BOSS_CUTSCENE resolve) touch other functions — no overlap beyond
   `resolve_levelup` IF 10G routes its cutscene through it (orchestrator:
   watch that one function).

### `game/ui/hud.py` (shared with 10G's boss HP bar)

1. **`update`** — add `self._mx, self._my = mx, my` (one line, start of the
   method body).
2. **`submit`** — append `self._submit_lightning(renderer, session)` as the
   LAST statement (after the pause-button submit; 10G will be appending a
   boss-bar section in the same tail — order between the two is cosmetic-only,
   accept either on rebase).
3. **New private method `_submit_lightning`** at the class bottom (below
   `_submit_xp`), fenced. Nothing else in the file changes (docstring line
   about reserved readouts may drop the word "lightning").

### `game/main.py` (shared with 10G + 10I)

1. **Imports**: add `CheatMenu` to the existing `from game.ui import (...)`
   list (alphabetical slot).
2. **`build_gameplay` / `teardown_gameplay` / gp dict**: add key
   `"cheat": None` to the `gp` literal; `gp["cheat"] = CheatMenu(view_w,
   view_h)` beside the other constructions in `build_gameplay`; add
   `"cheat"` to `teardown_gameplay`'s reset tuple.
3. **`_execute_cheat(action)` helper**: define next to
   `handle_world_click` (same closure level). Maps: `"add_love"` →
   `session.cheat_add_love(10)`; `"skip_round"` →
   `session.cheat_skip_round(world.scene)`; `"inf_money"` →
   `session.cheat_add_love(999999)`; `"unlock_all"` →
   `session.cheat_unlock_all()`; `"trigger_levelup"` → close menu +
   `session.cheat_trigger_levelup()`; `("goto_round", n)` → close menu +
   `session.cheat_goto_round(n, world.scene)`; `"close"` → close menu.
   After any action, if `session.state.phase != GamePhase.LEVELUP` and
   `gp["levelup"].visible`: `gp["levelup"].close()` (§2 orphan guard).
4. **KEYDOWN routing** — inside the GAMEPLAY/GAME_OVER event branch, in
   `if event.type == pygame.KEYDOWN:`, insert as the FIRST statements,
   BEFORE the existing `if session.state.state != GameState.GAMEPLAY or
   session.frozen: continue` guard (the menu must work over LEVELUP,
   prototype-exact, but not on GAME_OVER — guard on
   `session.state.state == GameState.GAMEPLAY`):
   (a) Ctrl+L (`event.key == pygame.K_l and pygame.key.get_mods() &
   pygame.KMOD_CTRL`) → `gp["cheat"].toggle()`; `continue`.
   (b) `if gp["cheat"].visible:` →
   `_execute_cheat(gp["cheat"].handle_key(event.unicode,
   _key_name(event.key)))`; `continue`.
5. **`handle_world_click` ladder** — TWO insertions:
   (a) cheat-menu consumption immediately AFTER the GAME_OVER branch and
   BEFORE the `if session.frozen:` (LEVELUP) branch:
   `if gp["cheat"].visible: _execute_cheat(gp["cheat"].hit(mx, my)); return`.
   (b) strike at the ladder BOTTOM: extend the final
   `if session.state.phase == GamePhase.BUILDING:` tile-pick with
   `elif session.state.phase == GamePhase.ENEMY:` →
   `wx, wy = cs.screen_to_world(mx, my);
   session.lightning_strike(world.scene, cs, wx, wy)`.
   (10G inserts a BOSS_CUTSCENE modal branch in this same ladder — the cheat
   branch stays directly under GAME_OVER, above every other modal.)
6. **`over_ui` pan-arming tuple** (MOUSEBUTTONDOWN handler): add
   `or gp["cheat"].visible` so a press on the open menu can't arm panning.
7. **Update block** (world states): `gp["cheat"].update(dt, mx, my)` beside
   the `gp["levelup"].update` line (unconditional while world exists — the
   menu animates its own buttons only).
8. **Render block** (world states): (a) `gp["floaters"].submit_lightning(
   renderer, cs, world.scene)` immediately after the existing
   `submit_craters` call (world-anchored FX group); (b) `if
   gp["cheat"].visible: gp["cheat"].submit(renderer, view_w, view_h)` as the
   LAST submit in the world/PAUSED branch — above the game-over screen and
   everything 10G adds (prototype draws it topmost, `game.py:2061-2062`).

## 4. Exit gate + Quick Test (planner)

### `tools/tests/test_lightning.py` (new; fixture style of
`test_phase_loop.py`: module-level `load_balance(REPO/"data", ...)`, `synth`
board helper, headless, no SDL; values read from `CORE["LightningStrike"]`
so tests track data, with the current literals asserted once as a
parity-canary: cooldown [5,3,2] / damage [10,15,32] / radius [1,2,3] /
unlock 20 / upgrades [35,80])

1. **Seed + cost math** — fresh `RunState`: `lightning_level == 1`,
   cooldown 0; `next_cost` == 35 → `upgrade` with enough love → level 2 and
   exactly 35 spent; next 80 → level 3; at max `next_cost` is None and
   `upgrade` no-ops (no love spent); insufficient love → refused, level and
   love unchanged; manually set level 0 → `next_cost` == 20 (unlock branch).
2. **Cooldown gating** — `strike` sets cooldown to `cooldown[level-1]`;
   `can_strike` False while > 0; a strike attempt while cooling deals NO
   damage and spawns NO FX; `tick` drains linearly and clamps at 0; a whiff
   (no enemies in range) still spends the full cooldown and spawns FX;
   `Session.pre_sim` drains it in ENEMY phase and leaves it untouched in
   BUILDING/INCOME (phase-gated tick).
3. **Radius vs hand-computed prototype geometry** — real
   `CoordinateSystem` (Geometry tile_w 64 / tile_h 32), zoom 1, enemies via
   `create_enemy`: strike on an enemy's tile hits it (hp drops by exactly
   `damage[level-1]`); at radius 1 an enemy Δ(+1,+1) tiles (iso Δ = (0,32),
   d = 32) is HIT on the boundary (≤) while Δ(+1,0) (iso (32,16),
   d ≈ 35.78) is MISSED; at radius 2, Δ(+1,0) hits and Δ(+2,0)
   (d ≈ 71.55) misses; at radius 3, Δ(+2,0) hits. All in-radius enemies
   take FULL damage (two-enemy assertion). Zoom invariance: same layout at
   zoom 2 → identical hit set. A lightning-killed enemy is despawned by the
   next `resolve_combat` and fires `on_enemy_death` (XP/kill path).
4. **Cheat operations on session state** —
   `cheat_add_love(10)`/`(999999)` love math; `cheat_skip_round` mid-ENEMY:
   enemies despawned, spawner drained, phase ROUND_END, NO XP awarded, and
   the timers then run exactly ONE payday (round advances once — payday
   ordering intact); `cheat_goto_round(7)`: round_num 7, phase BUILDING,
   love/lives untouched, and the next `end_turn` composes a round-7 wave
   (count formula check); `cheat_trigger_levelup` from BUILDING: phase
   LEVELUP with options rolled, `resolve_levelup` applies the option,
   bumps village level, and returns to BUILDING with NO payday (love changes
   only by the option cost; round_num unchanged); from ENEMY: pending flag
   only, phase still ENEMY, and the natural round end then runs the
   `run_income=True` path (regression on the default);
   `cheat_unlock_all`: every `RESEARCH` type has `unlocked_buildings` True
   AND `tiers_unlocked == len(tiers)` — including meditator + blocker (the
   documented prototype-omission fix) — and `buildable()` is True for all.
5. **Purity** — confirm the existing `game/ui` TestPurity source scan covers
   the new `cheat_menu.py` (it is directory-wide; if it enumerates modules,
   add it) and that `game/core/lightning.py` imports no pygame.

### Live Quick Test (windowed, `py game/main.py`)

Start a run → click The Hole: base-info shows the ⚡ section at Level 1/3
with DMG 10 / Radius 1 tiles / Atk Spd 5.0s and an `UPGRADE LIGHTNING ♥35`
button (red-flash if poor). End Turn → during combat the bottom-left shows
`⚡ CLICK TO STRIKE` + a full white cursor bar; click a clump of enemies →
bolt + fading yellow ground diamond, enemies lose 10 HP (kills pay XP),
label flips to a 5.0s countdown and the cursor bar refills — faster at 2×
speed, frozen on in-combat pause; a whiff still starts the cooldown. Upgrade
twice (35♥ then 80♥) → panel shows MAX LEVEL, radius visibly wider, cooldown
2s. Ctrl+L → CHEATS opens (also over the level-up window; not on game over):
+10 Love and Infinite Money bump the pill; Skip Round mid-wave jumps to
REBUILDING and pays a normal payday; LEVEL UP in BUILDING opens the reward
window and returns to BUILDING with no payday; Unlock All Tech makes every
building line constructible/advanceable (incl. meditator + blocker); Jump to
round 20 → ROUND 20 in BUILDING, next wave is round-20 sized; Esc/X closes.

### Reviewer checklist

- [ ] Numbers match live `Balancing_Core.json` ([35,80]/[10,15,32]/[1,2,3]/
      [5,3,2]/20), read ONLY through `core_balance["LightningStrike"]` — no
      literals in game code; no `data/` diffs.
- [ ] Radius = screen-plane Euclidean via `engine.coords` (no iso math
      outside coords; zoom-correct); damage flat, no falloff/cap/RoundStats;
      whiff spends cooldown; strike only ENEMY phase, level > 0, cooldown ≤ 0,
      below HUD/panel/modals in the ladder.
- [ ] Cooldown ticks ONLY in `pre_sim`'s ENEMY branch on the host's
      `sim_dt` (speed-scaled, pause-frozen); never reset by round end or
      upgrade.
- [ ] `resolve_levelup` default path (natural round end) still runs payday —
      `test_levelup`/`test_phase_loop` untouched and green; the cheat path
      restores `return_phase` and runs NO payday; `cheat_goto_round` runs NO
      payday; `cheat_skip_round` reaches payday only through the normal
      ROUND_END flow (ordering sacrosanct, G-5).
- [ ] Cheat menu: Ctrl+L (divergence from prototype Ctrl+P documented in the
      module docstring), gameplay-only, works over LEVELUP, not on
      GAME_OVER/pause/menus, swallows all input while open, renders topmost,
      stays-open semantics per §1.6, goto-round input digits-only max 4 /
      n ≥ 1.
- [ ] `game/ui` purity green (`cheat_menu.py` scanned); `game.ui → game.core`
      one-way holds; shared-file edits confined to the §3 fenced blocks;
      full suite `py -m unittest discover -s tools/tests -t .` + smoke
      `py tools/smoke.py` green; CLAUDE.md docs updated (core + ui).
