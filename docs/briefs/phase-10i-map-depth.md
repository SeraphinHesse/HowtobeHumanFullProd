> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase 10I Brief — Map Depth

> Coordination artifact for the 10G–10I subagent batch. Planner fills §1–§4;
> orchestrator reconciles §3 across the three briefs; coder treats §3 as a hard
> boundary; reviewer verifies the diff against §1/§2/§4.

**Phase goal (MIGRATION_PLAN.md 10I):** tile conditions (spawn chances, stat
modifiers, tooltips, badges), damage-based path-weight reduction,
defence-range path weights, RANGE + HEATMAP overlay toggles.

## Known repo state (verified at umbrella base — do not re-derive)

- Balancing data DONE: `data/balancing/map.json` → `TileConditions`
  (`spawn_chances` grass .7 / mountain .1 / pond .1 / forest .1,
  `path_weights`, `modifiers` per condition) and
  `Pathfinding.damage_reduction:{min_round:10, reduction:0.5, top_n:3}`.
- The FULL weight composition already exists fed neutral inputs:
  `TileCondition` enum + `path_weights` lookup (`game/map/tiles.py:31,132`);
  `Tile.__slots__` already has `condition`, `damage_weight_reduced`,
  `defence_range_covered`, `range_highlight`;
  `tile_map.py`: `_defence_coverage_fn` (`:97`), `_defence_range_add` (`:107`),
  `set_round` (`:344`), `refresh_damage_weight_reductions` (`:347`, reads
  occupant `damage_dealt_last_round`, top-N), `refresh_defence_range_coverage`
  (`:370`); pathfinder pre-query refresh hooks (`game/map/pathfinder.py:26-29`).
  10I's job is to PRODUCE the inputs, not rebuild the pipeline.
- Buildings already track `RoundStats` (dmg dealt this/last round) —
  `game/buildings/components.py`; payday snapshots this→last.
- Overlay drawing: `widgets.submit_tile_diamond` → `renderer.submit_overlay_lines`
  (world-space); range highlight today is per-selection in
  `building_ui.py:314-325`. NO persistent overlay-toggle mechanism exists —
  RANGE/HEATMAP toggles are net-new (toggle state + full-grid submit pass).
- Map files carry NO per-tile condition field — conditions roll at runtime
  from `spawn_chances` (must be deterministically seedable for tests).
- Map layer stays import-free of `game.buildings` (duck-typed occupants);
  weights are content-key driven; composition order prototype-exact.

## 1. Behavioral spec (planner)

All citations are prototype files at
`../HowToBeHuman/ClaudePrototype/HowToBeHuman` unless prefixed `repo:`.
`Balancing_Map.json` (live) matches `balancing_map.py` defaults for every 10I
key, so JSON-vs-py drift does not affect this phase (the drifted keys —
`BASE_UNLOCK_COST` 5 vs 10 etc. — are TileUnlocking, out of scope).

### 1.1 Condition roll — timing + exact chances

- **When:** ONCE, at map construction (`TileMap.__init__`,
  `src/map/tile_map.py:69-91`), i.e. per new game. Conditions never re-roll
  and never change during a run.
- **Chances:** one weighted draw per eligible tile via
  `random.choices([GRASS, MOUNTAIN, POND, FOREST], weights=[.7,.1,.1,.1])[0]`
  (`tile_map.py:72-91`; values `Balancing_Map.json:26-29` =
  repo `map.json TileConditions.spawn_chances`).
- **Eligibility:** every tile EXCEPT
  1. `state == BACKGROUND` at init (`tile_map.py:86-87`), and
  2. the starting buildable pocket incl. the base
     (`tile.col <= BUILDABLE_COL_MAX and tile.row <= BUILDABLE_ROW_MAX`,
     `tile_map.py:88-90`) — kept GRASS "so the base is always reachable".
- **Consequence (prototype-exact quirk):** tiles that are BACKGROUND at init
  but later become SPAWNING/COMBAT via spawn-band recede stay GRASS forever —
  the roll never revisits them.
- **Buildings snapshot the condition at placement**:
  `b.tile_condition = tile.condition` inside `Game.place_building`
  (`src/core/game.py:690`). The base building is constructed in
  `TileMap.__init__`, never gets the attribute → always behaves as GRASS.
  (Conditions are immutable, so snapshot vs live-read are equivalent.)
- **Enemies track a *current* condition:** `_current_condition` starts GRASS
  at spawn (`src/enemies/enemy.py:111-114`) and updates only when the enemy
  ARRIVES at a path tile's centre (`enemy.py:191-192`) — the spawn tile's own
  condition is never applied.

### 1.2 Stat modifiers — every formula + application site

Values: `Balancing_Map.json:30-39` = repo `map.json TileConditions.modifiers`
(Mountain: `def_range_bonus 1`, `eco_yield_penalty 0.1`, `enemy_dmg_bonus 0.1`,
`enemy_speed_penalty 0.4`; Pond: `def_attack_speed_penalty 0.3`,
`eco_yield_bonus 0.1`; Forest: `def_dmg_penalty 0.1`, `eco_yield_bonus 0.1`,
`enemy_dmg_bonus 0.1`, `enemy_speed_penalty 0.4`). GRASS = no effect anywhere.

**Defence buildings** (building standing ON the condition tile; identical code
in `DefenceBuilding`, `AOEDefenceBuilding`, `SunScorcherBuilding`):

| Stat | Formula (exact order) | Prototype site |
|---|---|---|
| Damage (FOREST) | `dmg = int(base*(1+boost_pct))`; **then** `if forest: dmg = int(dmg*(1-0.1))`; then explosion halving per debuff; `max(1, dmg)` | `defence_building.py:125-147`; AOE `aoe_defence_building.py:163-184`; scorcher inherits |
| Attack interval (POND) | `spd = attack_speed*(1-boost_pct)`; **then** `if pond: spd *= (1+0.3)` (30% SLOWER); then `*=1.5` per speed debuff; floor `max(DEFENCE_MIN_ATTACK_SPEED, spd)` (scorcher floors at its own `_MIN_TICK` instead) | `defence_building.py:149-159`; AOE `:193-201`; scorcher `sun_scorcher_building.py:61-69` |
| Range (MOUNTAIN) | `r = range_tiles; if mountain: r += 1` | `defence_building.py:161-168`; AOE `aoe_defence_building.py:186-191` |

Consumption sites of the *effective* range: target acquisition/validation
(`defence_building.py:264` `_in_range` uses `_effective_range_tiles()`), the
panel's Range stat row (`defence_building.py:111`,
`aoe_defence_building.py:137`), and the selection range highlight
(`game.py:578-581`). **The RAW `range_tiles` (no mountain bonus) is what feeds
defence-range pathfinding coverage (`game.py:601`) and the RANGE overlay
(`game.py:2014`)** — keep that raw/effective split. `boosted_stats()` also
shows the un-modified damage beside a forest-cut value
(`defence_building.py:117-122`).

**Economy** — applies ONLY to `EconomicBuilding` (Musician line). Meditator
overrides `yield_amount` with its streak math and applies NO condition
(`meditator_building.py:52-77`); Painter yield is 0 (`painter_building.py:31`);
boosts/structures have no yield.

| Condition | Formula | Site |
|---|---|---|
| MOUNTAIN | `raw = max(0, int(raw * (1 - 0.1)))` (−10%) | `economic_building.py:26-27` |
| POND | `raw = int(raw * (1 + 0.1))` (+10%) | `:28-29` |
| FOREST | `raw = int(raw * (1 + 0.1))` (+10%) | `:30-31` |

Applied on READ of `yield_amount` — the payday income sweep, the HUD income
line, and the panel Yield row all see the modified value.

**Enemies** (per the tile the enemy last ARRIVED at, §1.1):

| Stat | Formula | Site |
|---|---|---|
| Move speed (MOUNTAIN/FOREST) | `spd = max(0, base − 0.4 tiles/s)` (prototype `− 0.4*32` in px-space, `enemy.py:345-354`) | applied inside `_do_move` step |
| Damage (MOUNTAIN/FOREST) | `dmg = max(1, int(dmg * (1 + 0.1)))` (`enemy.py:356-365`) | consumed when attacking a blocking building (`enemy.py:253`) and edge walls (`:240`, `:324`); NOT for base hits (lives mode costs 1 life flat, `game.py:1285-1291`) |
| POND | **no enemy stat modifier** — pond affects enemies only through its +9 path weight | — |

Note `max(0, …)`: a SiegeCannon (0.5 t/s) on mountain/forest crawls at 0.1;
this is prototype-exact.

### 1.3 Condition path-weight bonuses (already coded — verify only)

`+2` mountain / `+9` pond / `+1` forest added to the base content weight,
gated `0 < base < 999` so the base tile (0) and impassable (999) are exempt
(`src/map/tile.py:66-72`; values `Balancing_Map.json:23-25`). Repo equivalent
already at `game/map/tiles.py:136-140`. Composition order (base → +condition →
+defence-range → ×damage discount) is prototype-exact and MUST NOT be touched.

**⚠️ Doc-vs-code difference (flagged):** `MIGRATION_AGENT_READ_FIRST.md` §5 and
the `balancing_map.py:58` comment say pond is "impassable to enemies". The
CODE says otherwise: pond only adds +9 weight (`tile.py:69-70`), so a pond
tile costs 10 vs 1 — heavily avoided but crossed when it is the only route,
and enemies suffer no penalty standing on it. **Ship the code behavior**
(the behavioral spec is what the prototype *does*). See Open Questions.

### 1.4 Damage-based path-weight reduction

- **Tunables:** `TILE_WEIGHT_DAMAGE_REDUCTION 0.5`, `_TOP_N 3`,
  `_MIN_ROUND 10` (`Balancing_Map.json:19-21` = repo
  `map.json Pathfinding.damage_reduction`).
- **Tracking:** each building accrues `damage_dealt_this_round`; payday
  snapshot rolls this→last (repo `game/core/payday.py:139-146` — already
  live since 10F; the combat sweep writes `dmg_dealt_this_round`).
- **Selection** (`tile_map.py:121-141`, repo port `tile_map.py:347-368`):
  sweep BUILT tiles, reset every flag, collect `(dmg, tile)` for alive,
  non-base occupants with `damage_dealt_last_round > 0`; sort dmg descending;
  flag the top 3.
- **Round gate is STRICT:** `if round_num <= 10 or not candidates: return`
  (`tile_map.py:137`) — the discount first fires in **round 11**, not 10.
- **Multiplier:** flagged tile's composed weight →
  `max(1, int(round(base * 0.5)))`, applied last, gated `0 < base < 999`
  (`tile.py:80-81`; repo `tiles.py:142-144`).
- **Refresh timing:** recomputed at EVERY path query via
  `_apply_damage_weights` (`pathfinder.py:11-23`; repo
  `pathfinder.py:22-31` already calls it). The round number is pushed once
  per wave: `tilemap.set_round(round_num)` in `_begin_enemy_phase`
  (`game.py:818`). 10I wires the repo equivalent in `Session.end_turn`.

### 1.5 Defence-range path weights

- **Tunables:** `DEFENCE_RANGE_AFFECTS_PATHFINDING true`,
  `DEFENCE_RANGE_PATH_WEIGHT_ADD 1` (`Balancing_Buildings.json:646-647`) —
  already migrated as repo `buildings.json
  BuildingsGlobal.defence_range_pathfinding.{enabled, path_weight_add}`.
  They live in the BUILDINGS domain (prototype `balancing_buildings.py:588-589`).
- **Coverage set** (`Game.defence_covered_tiles`, `game.py:583-608`): every
  `(col,row)` within the Chebyshev square (`r = int(range_tiles)`, diagonals
  included, off-map coords harmlessly included) of every **alive** built
  building with `range_tiles > 0`, **EXCLUDING `building_type == 'aoe_defence'`
  (Maw Mortar line)** (`game.py:599-600`). Uses RAW `range_tiles` — a
  mountain-boosted defender covers its base range only (`game.py:601`).
  Returns `∅` when the toggle is off (`game.py:593`), so callers never branch.
- **Wiring:** `tilemap._defence_coverage_fn = game.defence_covered_tiles` once
  at new-game (`game.py:752`); the pathfinder refreshes coverage before every
  query (`pathfinder.py:19-23`; repo hook `pathfinder.py:29-31` +
  `refresh_defence_range_coverage` repo `tile_map.py:370-372`).
- **Effect:** covered tile weight `base += 1`, gated `0 < base < 999`,
  BEFORE the damage discount (`tile.py:76-77`; repo `tiles.py:141-142` +
  `_defence_range_add`, currently 0).

### 1.6 RANGE + HEATMAP overlay toggles

**Toggle UX** (`src/ui/hud.py`): two persistent stone-pill buttons
bottom-left — `RANGE` at `(2, SCREEN_H-38, 48, 36)` and `HEATMAP` at
`(50, …)` (`hud.py:150-156`). Clicking flips `show_range_mode` /
`show_heatmap` independently; the click is consumed, returns no HUD action
(`hud.py:223-228`). Active style: gold 2px border + gold label; inactive:
normal text, hover lightens the pill (`hud.py:383-392`). State persists across
phases/rounds within a run (fields on the HUD object). Overlays draw whenever
toggled and data exists, in ANY phase, below the HUD chrome
(`hud.py:312-317`).

**RANGE overlay** (`hud.py:399-430`):
- Data: `defence_tiles_data = [(col,row,range_tiles,range_plus_only)]` built
  per frame from every BUILT tile with an alive building whose raw
  `range_tiles > 0` (`game.py:2012-2019`) — that INCLUDES the Maw Mortar
  (mortar exclusion is pathfinding-only, §1.5) and includes boost buildings
  (`range_tiles = 1`, `range_plus_only = True`, `boost_building.py:50-51`).
- Coverage: Chebyshev square `r = int(range_tiles)` per building; plus-only
  buildings contribute their 4 cardinal neighbours (`hud.py:411-420`).
  Squares union into one set — no per-building distinction.
- Render: one iso diamond per covered tile, colour `(180,40,40)`
  (`_C_RANGE_OVERLAY`, `hud.py:24`), fill alpha 55, border alpha 130, border
  width `max(1, scale)` (`hud.py:422-425`).

**HEATMAP overlay** (`hud.py:432-470`):
- Data producer: during the ENEMY phase, every frame, each live enemy's
  current tile `(e.col, e.row)` collects `id(e)` into
  `_heatmap_current[(col,row)]: set` (`game.py:1344-1349`). At
  `_begin_round_end` the counts snapshot to
  `_path_heatmap = {tile: len(ids)}` and the accumulator clears
  (`game.py:927-932`) — so the overlay always shows the PREVIOUS round's
  distinct-enemy traffic; it is empty before the first wave.
- Render: per visited tile, normalise `t = min(1, count/max_count)`, then a
  blue→yellow→red ramp (`hud.py:452-464`):
  `t < 0.5`: `r=255*2t, g=100+155*2t, b=200-200*2t`;
  `t ≥ 0.5`: `r=255, g=255-255*(2t-1), b=0`; alpha `50+130t`
  (`hud.py:465`). Filled diamond per tile.

**Repo rendering constraint:** the engine overlay pass draws outline polylines
only (no per-pixel-alpha fills — same limit that made the level-up backdrop
opaque, `game/ui/CLAUDE.md`). 10I renders both overlays as **diamond
OUTLINES** via `submit_tile_diamond` (RANGE: `C_RANGE_HIGHLIGHT` = (180,40,40)
verbatim; HEATMAP: the exact RGB ramp above, alpha dropped). Alpha-filled
parity is deferred to the 10J FX sweep — record as a known divergence in
`game/ui/CLAUDE.md`.

### 1.7 World condition tint (the in-world visibility of conditions)

Prototype draws a per-tile condition overlay on every non-GRASS, non-BACKGROUND
tile, under buildings/highlights: diamond fill alpha 70 + border alpha 140
width 2, colours MOUNTAIN `(130,100,60)`, POND `(50,130,200)`, FOREST
`(30,100,30)` (`tile.py:25-30, 166-173`). Repo: outline-only diamonds (same
alpha limit as §1.6), submitted ONLY for tiles inside the visible window
(large-map invariant — never a full-grid per-frame scan).

### 1.8 Tile badges + tooltips (`src/ui/building_ui.py`)

- Labels/colours (`building_ui.py:23-27`): Grass `(100,180,80)`, Mountain
  `(160,130,90)`, Pond `(80,160,220)`, Forest `(70,160,70)`.
- **Upgrade panel badge** (`:998-1014`): a bordered pill `Terrain: <Label>` in
  the condition colour, below the Level row (y≈90), ALWAYS shown incl. Grass;
  reads the building's snapshot `tile_condition`. Hovering it (rect inflated
  4px) shows the effect tooltip BELOW the badge, drawn last/on top
  (`:1121-1130`).
- **Unlock + construct panel footer badge** (`_draw_tile_cond_footer`,
  `:1457-1477`, called at `:893` and `:969`): same pill centred at panel
  bottom (y=338), reading the TILE's condition; hover shows the tooltip ABOVE.
- **Tooltip content** (`_tile_cond_effect_lines`, `:1418-1438`), values read
  live from balancing: Grass → `"No terrain effect"`; Mountain →
  `"+1 range for defenders"`, `"−10% ♥/round for economy"`; Pond →
  `"−30% atk speed for defenders"`, `"+10% ♥/round for economy"`; Forest →
  `"−10% damage for defenders"`, `"+10% ♥/round for economy"`.
  (Prototype-exact: the enemy dmg/speed effects are deliberately NOT listed.)
- Tooltip chrome (`:1440-1455`): dark `(20,15,35)` panel, 1px border in the
  condition colour, centred horizontally.
- Base-info panel shows NO badge.

## 2. Architecture plan (planner)

The weight-composition pipeline is DONE; 10I builds the **producers** and the
UI surfaces. No `data/` or schema changes — every tunable already exists
(`map.json TileConditions` + `Pathfinding.damage_reduction`,
`buildings.json BuildingsGlobal.defence_range_pathfinding`).

### 2.1 Condition roll — `game/map/tile_map.py` (+ `tiles.py`)

- `TileMap.__init__(doc, balance, rng=None)` gains an optional `rng`
  (default: module `random`) — the deterministic seam for tests
  (`random.Random(seed)` injected). After the grid/base seeding loop, one
  pass: for every tile NOT (`state == BACKGROUND` or initially
  BUILDABLE/BUILT — i.e. the starting pocket + base, the map-driven
  equivalent of the prototype's pocket skip), draw
  `rng.choices(_CONDS, weights=[spawn_chances[k] for k in …])[0]` and assign
  `tile.condition`. Weights read from
  `balance["TileConditions"]["spawn_chances"]` keys
  `grass/mountain/pond/forest`. Receded-into-play tiles stay GRASS
  (prototype-exact, §1.1).
- `game/map/tiles.py`: add `CONDITION_MODIFIER_KEY = {MOUNTAIN: "Mountain",
  POND: "Pond", FOREST: "Forest"}` (GRASS absent → no modifiers) next to the
  existing `_CONDITION_WEIGHT_KEY` so every consumer maps enum→`modifiers`
  subtree key the same way. **Do not touch `pathfinding_weight`.**

### 2.2 Building stat modifiers — snapshot at placement, computed getters

- **Snapshot seam** (`game/buildings/registry.py: place_building`): after
  `tile.occupant = building` set two transients (E-11 underscore attrs, like
  `_balance`): `building._tile_condition = tile.condition` and
  `building._condition_mods =
  tilemap.balance["TileConditions"]["modifiers"]`. `Building.__init__` defaults
  both (`GRASS`, `{}`) so `create()` previews and headless tests see neutral
  stats. Map stays import-free of buildings; buildings→map import direction is
  already established (registry imports `game.map.tiles`).
- **`game/buildings/building.py`**: one helper on `Building` —
  `_condition_mod(key)` → the active condition's modifier value or 0
  (looks up `CONDITION_MODIFIER_KEY[self._tile_condition]` in
  `_condition_mods`; GRASS/missing → 0). Keeps every leaf formula one line.
- **`game/buildings/defence.py`** (`DefenceBuilding` — AOE + Beam inherit):
  - `damage()`: insert `dmg = int(dmg * (1.0 - def_dmg_penalty))` between the
    boost multiply and the debuff halving (prototype order §1.2).
  - `attack_speed()`: insert `spd *= (1.0 + def_attack_speed_penalty)` between
    the boost multiply and the debuff ×1.5.
  - NEW `effective_range_tiles()`: `range_tiles() + def_range_bonus`.
    `range_tiles()` stays RAW (coverage + RANGE overlay read it, §1.5/§1.6).
    `_on_apply_stats` syncs the `RangeSensor` from the effective value.
  - `boosted_stats()`: also emit the pre-forest Damage base when the forest
    cut changes it (prototype `defence_building.py:117-122`).
- **`game/buildings/economy.py`** (`EconomyBuilding.yield_amount` — Musician
  only; Meditator/Painter override and are untouched): apply mountain
  `max(0, int(y*(1-p)))` / pond/forest `int(y*(1+b))` to the tier value.
- **`game/enemies/combat.py`**: the two targeting sites
  (`combat.py:311`, `:346`) switch `defender.range_tiles()` →
  `defender.effective_range_tiles()` (guarded
  `getattr(defender, "effective_range_tiles", defender.range_tiles)()` so
  stubs keep working). Nothing else in the sweep changes — damage/interval
  modifiers ride the existing `damage()` / `attack_speed()` calls.

### 2.3 Enemy modifiers — `game/enemies/components.py`

- `PathAgent` gains transient `_current_condition` (init GRASS in `on_added`)
  + `_condition_speed()` = `max(0.0, _real_speed − enemy_speed_penalty)`.
  In `update`, when `Movement.index` has advanced past a waypoint (track a
  `_last_index` transient), set `_current_condition` from the tile at
  `waypoints[index-1]` (the tile just ARRIVED at — spawn tile never applies,
  §1.1). While unblocked, write `mv.speed = self._condition_speed()` (replaces
  the plain `_real_speed` restore). Modifiers dict read duck-typed from
  `self._tilemap.balance["TileConditions"]["modifiers"]` (guarded `getattr`
  for headless stubs).
- `EnemyCombat` gains `_effective_dmg()` = `max(1, int(dmg * (1 +
  enemy_dmg_bonus)))` reading the owner's `PathAgent._current_condition`;
  used at BOTH damage sites (building `Health.damage`, `tilemap.damage_wall`).
  `RoundStats.dmg_taken_this_round` on the target accrues the modified value
  (prototype passes the effective dmg to `take_damage`).

### 2.4 Defence-range coverage producer — NEW `game/buildings/coverage.py`

- `defence_covered_tiles(tilemap, buildings_balance) -> set[(col,row)]` —
  port of `game.py:583-608`: returns `∅` when
  `BuildingsGlobal.defence_range_pathfinding.enabled` is false; else the
  Chebyshev-square union over alive built occupants with duck-typed
  `range_tiles() > 0`, skipping `building_type == "aoe_defence"`. RAW range.
- `wire_defence_coverage(tilemap, buildings_balance)` — sets
  `tilemap._defence_coverage_fn = lambda: defence_covered_tiles(...)` and
  `tilemap._defence_range_add =
  buildings_balance["BuildingsGlobal"]["defence_range_pathfinding"]["path_weight_add"]`.
  Lives in `game/buildings` (it reads buildings balance + duck-types
  occupants); the map layer only ever sees the injected callable — its
  no-import rule holds.

### 2.5 Round gate — `game/core/session.py` (ONE line)

`Session.end_turn()` calls `self.tilemap.set_round(st.round_num)` immediately
before `spawner.begin_round(...)` — the repo equivalent of
`_begin_enemy_phase`'s `set_round` (`game.py:818`). Damage-weight refresh
itself already runs per path query (repo `pathfinder.py:22-31`).

### 2.6 Overlays + toggles — NEW `game/ui/overlays.py` (avoid `hud.py`)

One pure module (joins the game/ui purity scan) owning ALL of 10I's UI
surfaces, so `game/ui/hud.py` — which 10G (boss HP bar) and 10H (lightning
indicator) both touch — is NOT edited by 10I:

- `class MapOverlays(view_w, view_h)`:
  - Two `widgets.Button`s `RANGE` / `HEATMAP` bottom-left (stacked left of the
    phase banner, e.g. `(12, view_h-72, 74, 26)` and `(90, …)`), fields
    `show_range` / `show_heatmap`. `hit(mx,my)` flips the matching flag and
    returns True (consumed); `over(mx,my)` is the pure containment probe for
    the host's `over_ui` check; `update(dt,mx,my)` drives hover. Active
    style: `btn.submit(renderer, color=C_UI_BTN, text_color=C_GOLD)` + a gold
    `HudRect` border (prototype gold-when-active, §1.6).
  - Heatmap tracker (prototype `game.py:1344-1349, 927-932`):
    `track(phase, prev_phase, scene)` — while `phase == ENEMY`, for each
    alive `"enemy"`-tagged object add `id(e)` to
    `_current[(round(wx), round(wy))]`; on the ENEMY→(anything) edge snapshot
    `self.path_heatmap = {k: len(v)}` and clear. Pure, headless-testable.
  - `submit(renderer, tilemap, scene, window)`:
    1. condition tint diamonds for non-GRASS tiles inside `window`
       (=`cs.visible_tile_window` bounds from the host) — colours
       `(130,100,60)/(50,130,200)/(30,100,30)` (§1.7), outline via
       `submit_tile_diamond`;
    2. if `show_range`: union coverage set from alive built occupants — 
       Chebyshev square per duck-typed `range_tiles() > 0` occupant (mortar
       INCLUDED) plus cardinal plus-shape per `"boost"`-tagged occupant
       (§1.6) — one `(180,40,40)` diamond per covered tile;
    3. if `show_heatmap` and `path_heatmap`: one diamond per visited tile,
       exact prototype RGB ramp (§1.6).
  - `submit_buttons(renderer)` — the HUD-pass pill buttons.
  - Cost profile: O(viewport) + O(defenders·r²) + O(visited tiles); never a
    full-map scan (large-map invariant).
- `game/ui/widgets.py`: add the shared condition label/colour table
  `COND_LABELS = {…}` (§1.8 values) — used by overlays + building_ui.

### 2.7 Badges + tooltips — `game/ui/building_ui.py`

- `_submit_upgrade`: after the Level line, the `Terrain: <Label>` pill for
  the selected building's `_tile_condition` (duck-typed
  `getattr(b, "_tile_condition", GRASS)`); track hover via the panel's
  hover pass and draw the effect-lines tooltip last (§1.8 copy, values read
  from `session.tilemap.balance["TileConditions"]["modifiers"]` — the panel
  already receives `session` in `submit`).
- `_submit_unlock` + `_submit_construct`: the footer badge (panel bottom)
  for `self.tile.condition`, hover tooltip above.
- Range parity: `_building_stats` Range row and `_set_range_highlight` use
  `effective_range_tiles()` when present (prototype §1.2 consumption sites).

### 2.8 Host wiring — `game/main.py`

`_World.__init__` wires coverage; `build_gameplay`/`teardown` own a
`MapOverlays`; the click ladder routes toggle clicks; the render section
submits overlays between the scene items and the panel highlights (conditions
under selection). Exact anchors in §3.

## 3. File scope + shared-file contract (planner → orchestrator reconciles)

### Touchable files (exhaustive)

**Create**
- `game/ui/overlays.py`
- `game/buildings/coverage.py`
- `tools/tests/test_tile_conditions.py`

**Modify (10I-owned, no cross-phase contention expected)**
- `game/map/tiles.py` (add `CONDITION_MODIFIER_KEY` only)
- `game/map/tile_map.py` (`__init__` rng param + condition-roll pass)
- `game/buildings/registry.py` (`place_building` condition snapshot)
- `game/buildings/building.py` (`_condition_mod` helper + transient defaults)
- `game/buildings/defence.py` (damage/attack_speed inserts,
  `effective_range_tiles`, sensor sync, boosted_stats)
- `game/buildings/economy.py` (`yield_amount` condition math)
- `game/enemies/components.py` (PathAgent condition tracking + speed;
  EnemyCombat `_effective_dmg`)
- `game/enemies/combat.py` (two `effective_range_tiles` call sites)
- `game/ui/widgets.py` (append `COND_LABELS` table)
- `game/ui/building_ui.py` (badges/tooltips; effective-range in stats +
  highlight)
- `game/ui/__init__.py` (one line: export `MapOverlays` — orchestrator addition)

> **Orchestrator:** also read `docs/briefs/phase-10g-i-coordination.md` —
> cross-phase file matrix + rulings; it wins over this brief on conflicts.
- Package docs per exit-gate rule 3: `game/map/CLAUDE.md`,
  `game/buildings/CLAUDE.md`, `game/enemies/CLAUDE.md`, `game/ui/CLAUDE.md`
  (+ `MIGRATION_PLAN.md` 10I status line if the orchestrator wants it here)

**Modify (SHARED — 10G and 10H land first; anchor on code, not line numbers)**
- `game/core/session.py` — **one block**
- `game/main.py` — blocks A–F below
- `game/ui/hud.py` — **NOT touched by 10I** (deliberate: 10G boss bar + 10H
  lightning indicator both edit it; the toggles live in `overlays.py`)

### Shared-file insertion points

**`game/core/session.py` — 1 insertion.**
In `end_turn()`, directly ABOVE the line
`self.spawner.begin_round(` (currently session.py:142), insert:
```python
self.tilemap.set_round(st.round_num)  # 10I: damage-weight round gate
```
Nothing else in the file changes.

**`game/main.py` — 6 bounded blocks.**
- **A (import):** extend the existing `from game.ui import (...)` list
  (anchor: the line containing `LevelupWindow, Shell`) with `MapOverlays`;
  add `from game.buildings.coverage import wire_defence_coverage` beside the
  existing `from game.buildings import BaseBuilding, attach_base`.
- **B (world wiring):** in `_World.__init__`, immediately AFTER the
  `self.session = Session.create(...)` statement, one line:
  `wire_defence_coverage(self.tile_map, buildings_bal)`.
- **C (lifecycle):** in `build_gameplay()`, after the `gp["levelup"] = …`
  line: `gp["overlays"] = MapOverlays(view_w, view_h)`; add `"overlays": None`
  to the `gp = {…}` initializer dict and `"overlays"` to the reset tuple in
  `teardown_gameplay()`.
- **D (click ladder):** in `handle_world_click`, between the
  `if hud_action == "end_turn": … return` branch and the
  `if panel.handle_click(` call, insert:
  ```python
  if gp["overlays"].hit(mx, my):   # RANGE/HEATMAP toggles consume the click
      return
  ```
  and in the MOUSEBUTTONDOWN `over_ui = (…)` expression add
  `or gp["overlays"].over(px, py)`.
- **E (update):** in the `_WORLD_STATES` update branch, immediately BEFORE
  the `gp["prev_phase"] = session.state.phase` line:
  `gp["overlays"].track(session.state.phase, gp["prev_phase"], world.scene)`;
  next to `gp["panel"].update(dt)`: `gp["overlays"].update(dt, mx, my)`.
- **F (render):** in the world render branch, AFTER the
  `for item in world.scene.render_items(): renderer.submit(item)` loop and
  BEFORE `gp["floaters"].submit_craters(...)`, insert:
  ```python
  gp["overlays"].submit(renderer, world.tile_map, world.scene,
                        (cmin, cmax, rmin, rmax))
  ```
  (submitted before `gp["panel"].submit` so selection highlights draw over
  condition/overlay diamonds); and beside `gp["hud"].submit(...)`:
  `gp["overlays"].submit_buttons(renderer)`.
  Note: block F needs the `cmin, cmax, rmin, rmax` window already computed a
  few lines above — reuse it, do not recompute.

No `data/**` or `data/schemas/**` edits. No engine edits.

## 4. Exit gate + Quick Test (planner)

### `tools/tests/test_tile_conditions.py` (fixture style = `test_enemies.py`:
synth `TileMapDoc` → `TileMap`, real `load_balance` dicts, injected rng/stubs)

1. **Seeded roll determinism + distribution** — `TileMap(doc, MAPBAL,
   rng=random.Random(42))` twice → identical condition grids; different seed
   → different grid. On a large synth map (e.g. 40×40 all-`c` + pocket),
   per-condition frequencies within tolerance of .7/.1/.1/.1; initial
   BUILDABLE pocket tiles + base tile + BACKGROUND tiles all GRASS.
2. **Path-weight bonuses** — force `tile.condition` per case; assert
   `tilemap.weight(tile)` = base+2 / +9 / +1 (mountain/pond/forest); base
   tile stays 0 and BACKGROUND stays 999 with a condition set (gate check).
3. **Pond routing** — corridor map with a grass lane and a pond lane: path
   takes the grass lane; pond-only corridor: path still crosses (asserts the
   §1.3 code behavior — pond is expensive, NOT impassable).
4. **Defence modifiers vs prototype math** — `place_building` a defender on
   each condition (set `tile.condition` pre-placement): forest
   `damage() == int(base*0.9)`; pond `attack_speed() == base*1.3` (and
   composes with a boost pct in prototype order); mountain
   `effective_range_tiles() == range_tiles()+1` while `range_tiles()` stays
   raw. AOE leaf: same pond/mountain math; Beam leaf: pond interval.
5. **Economy modifiers** — musician on mountain `yield == max(0,int(y*0.9))`,
   pond/forest `int(y*1.1)`; meditator + painter yields UNCHANGED on any
   condition.
6. **Enemy modifiers** — scripted walker whose path crosses a mountain tile:
   after arriving, `Movement.speed == base − 0.4` (and ≥ 0 for a 0.5-speed
   siege); blocked-attack damage into a building/wall = `int(dmg*1.1)`;
   spawn-tile condition NOT applied before first arrival; pond applies
   neither.
7. **Damage-reduction weight math** — four defenders with seeded
   `RoundStats.dmg_dealt_last_round` (distinct values); `set_round(11)` +
   `find_path` → exactly the top-3 tiles flagged and each weight
   `max(1, int(round(w*0.5)))`; `set_round(10)` → none (STRICT gate);
   dead occupant and base excluded; flags recompute (a new top-3 after stats
   change).
8. **Defence-range weight add** — `wire_defence_coverage` on a map with one
   defender (range 3): covered Chebyshev tiles weigh `base+1` after a
   `find_path` (pre-query refresh proof); mortar-only map → no coverage;
   `enabled:false` injected balance → no coverage; base tile exempt.
9. **Overlays logic (headless)** — `MapOverlays.hit` flips flags +consumes;
   `track` accumulates distinct enemies per tile during ENEMY and snapshots
   on the phase edge (two enemies crossing one tile → count 2, next round
   resets); RANGE coverage set includes the mortar square + boost plus-shape;
   heatmap ramp endpoints (t=0 → (0,100,200), t=1 → (255,0,0)).
10. **Purity** — `game/ui/overlays.py` passes the game/ui purity scan (no
    pygame import).

Plus: full suite `py -m unittest discover -s tools/tests -t .` stays green and
`py tools/smoke.py` passes (data unchanged → schema validation trivially
holds; state it in the report).

### Live Quick Test (windowed, `py game/main.py`)

1. New game → coloured condition diamonds visible outside the starting
   pocket; pocket + base plain.
2. Click a mountain COMBAT tile → unlock panel footer shows `Terrain:
   Mountain`; hover → "+1 range for defenders / −10% ♥/round for economy".
3. Unlock it, build a Stone Thrower on the mountain tile → upgrade panel
   badge + Range row shows base+1 and the range highlight extends one ring
   further; build a musician on a pond tile → Yield row +10% and payday pays
   the modified value (HUD income line agrees).
4. Toggle RANGE bottom-left → red diamonds over every defender's square
   (mortar included, plus-shape over a boost); button rims gold; toggle off
   clears.
5. Run a wave; enemies visibly slow crossing forest/mountain and detour
   around pond clusters; after ROUND_END toggle HEATMAP → last round's
   routes ramp blue→red.
6. Reach round 11+ with 3 damage-dealing defenders → subsequent waves bias
   over the top damage-dealers' tiles (watch paths shift).
7. Esc/pause/levelup: overlays persist and never intercept modal clicks.

### Reviewer checklist

- Weight composition order in `tiles.pathfinding_weight` byte-untouched;
  strict `round_num <= min_round` gate preserved.
- Raw vs effective range split matches §1.2/§1.5/§1.6: coverage + RANGE
  overlay = raw; targeting + panel stats + selection highlight = effective;
  mortar excluded from coverage but present in the overlay.
- Modifier insertion ORDER inside `damage()`/`attack_speed()` is
  boost → condition → explosion debuffs (→ floor), prototype-exact.
- Meditator/Painter yields untouched; base building condition-neutral;
  Musician-only economy math with `max(0,…)` on mountain.
- Enemy condition = last ARRIVED tile, GRASS at spawn; dmg modifier applied
  to building AND wall attacks, never base hits; `max(0)` speed / `max(1)`
  dmg clamps.
- Map layer still imports nothing from `game.buildings` (coverage is an
  injected callable); `game/ui` stays pygame-free; `game/ui/hud.py` has NO
  10I diff.
- No full-map per-frame scans: condition tint windowed, coverage
  O(defenders·r²), heatmap O(visited); condition roll is a one-time init
  pass; tile-state writes still via `set_tile_state`.
- All numbers read from `data/balancing/` at runtime (no literals for
  chances/modifiers/weights/gates); no `data/` diffs.
- Shared-file diffs confined to the §3 anchors; session.py = exactly one
  added line.
- Package CLAUDE.md docs updated (map: conditions live; buildings: condition
  snapshot + coverage.py; enemies: condition tracking; ui: overlays.py +
  outline-only divergence note).

### Open questions / risks (for the orchestrator & user)

1. **Pond "impassable" doc drift** — docs/comments promise impassable-to-
   enemies; prototype code ships +9 weight (§1.3). 10I ships code behavior.
   If the USER wants true impassability, that is a one-value change
   (`path_weights.pond` → 999-class) or a rule change — decide outside 10I.
2. **Top-N tie order** — prototype tie-break falls out of row-major
   `all_tiles()` scan order; repo `built_tiles()` iterates a set
   (nondeterministic on exact damage ties). Cosmetic-only; tests avoid ties.
   A deterministic tie-break (sort key `(-dmg, row, col)`) would touch the
   already-landed refresh — flag, don't change, unless reviewer prefers it.
3. **Heatmap tile key** — prototype uses the enemy's last-arrived tile;
   repo uses `round(transform.wx/wy)` per frame (nearest tile while walking).
   Distinct-id sets make the difference invisible in practice.
4. **Outline-only overlays** (no alpha fills) — known engine limit; parity
   fill lands with the 10J FX sweep.
5. **Merge-order dependency** — §3 main.py anchors are stated against the
   umbrella base; 10G/10H land first and both edit `handle_world_click` /
   the render branch. Anchors are code-relative (statement-adjacent), so
   reconcile by anchor text, not line numbers.
