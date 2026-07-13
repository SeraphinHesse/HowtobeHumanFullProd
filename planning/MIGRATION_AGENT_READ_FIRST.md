# MIGRATION_AGENT_READ_FIRST.md

**You are here to rebuild _How To Be Human_ in a different engine.** Read this file
first, end to end. It does two things:

1. **Maps every document and source file** so you know where the truth lives.
2. **Outlines the entire game's functionality** engine-agnostically, so you can
   reimplement mechanics without reading pygame plumbing line by line.

The original is built in **pygame-ce (Python 3)**. Nothing below assumes pygame —
projection formulas, state machines, and numbers are all portable. Where a value
matters for a faithful rebuild, the citing `file.py:line` is given so you can
confirm against source. **The `balancing/Balancing_*.json` files are the live
source of truth for any tunable number** (they override the Python defaults at
runtime); when a designer changes balance, they change the JSON.

> ⚠️ **Doc drift warning.** `AI_REFERENCE.md` and `README.md` predate a
> restructure. They describe a single `balancing.py`, a 20×8 grid, and a base at
> (0,6). The **current** truth is the split `balancing/` domain pairs, a **20×20**
> grid, base at **(1,1)**, and a fuller roster. Trust the per-domain
> `src/<domain>/CLAUDE.md` files, `BALANCING_REPLAN.md`, and this doc over the two
> legacy narratives.

---

## 0. What the game is (one paragraph)

Isometric tower-defence. You spend a currency called **love** to unlock map tiles
and place **musicians** (economy) and **defenders** (combat) that protect **"the
Hole"** (your base at grid `(1,1)`) from waves of enemies that path toward it. Play
alternates between a **build phase** (untimed, player-driven) and an **enemy phase**
(waves spawn and march). Surviving a round pays income and can trigger a **levelup**
(pick 1 of 3 upgrades). It is an **endless survival run** — there is no win state;
you push as deep as possible. You **lose** when enemies drain your lives (default) or
the Hole's HP.

---

## 1. Where everything lives (doc & file map)

### Suggested reading order for a rebuild
1. **This file** — orientation + full mechanics outline.
2. **`BALANCING_REPLAN.md`** — every gameplay number in one organised place.
3. **`AI_REFERENCE.md`** — narrative architecture/systems (allow for drift).
4. The five **`src/<domain>/CLAUDE.md`** — the most up-to-date per-system truth.
5. **`src/core/game.py`** — the actual loop/state authority (the "god object").

### Documentation
| Path | What it covers |
|---|---|
| `CLAUDE.md` (root) | Thin router: run/build commands, smoke test, domain table, balance-override rule, dev branch/lock protocol. |
| `AI_REFERENCE.md` | Big legacy technical reference (~725 lines): architecture, loops, iso/coordinate systems, all systems, flat balance table. Partly pre-restructure. |
| `README.md` | Player/dev facing: run, controls, structure, feature checklist. Pre-restructure. |
| `BALANCING_REPLAN.md` | **Single organised map of every balancing value**, grouped by feature. Most valuable balance doc. |
| `src/buildings/CLAUDE.md` | Buildings domain: full building-key list, tier/level model, ×10 scale, unlock gates, render/pathfinding hooks. |
| `src/enemies/CLAUDE.md` | Enemies domain: enemy conventions, scaling/tier system, enemy types & behaviours. |
| `src/map/CLAUDE.md` | Map domain: coordinate system, zone rings, unlock recede, pathfinding + weights, edge walls, camera. |
| `src/ui/CLAUDE.md` | UI domain: construct/upgrade panel, HUD, levelup, floaters, settings, the standalone Balancing Editor. |
| `src/core/CLAUDE.md` | Core domain: geometry/constants, phase loop, combat speed, XP/levelup, procedural sprites, imported-asset pipeline. |
| `docs/legacy/CLAUDE_original.md` | Pre-restructure monolithic reference (archived). |
| `docs/legacy/balancing_original.{py,json}` | Archived monolithic balancing module + overrides. |
| `.claude/SKILLS.md` | Dev workflow: domain→doc→balancing map, start/resume/finish/merge-domain commands. |

### Source layout (`src/`)
```
src/
  resource_path.py     path resolver (handles PyInstaller-frozen builds)
  cutscene.py          opening video playback (OpenCV)
  effects.py           world-space floaters (income/XP/painter msgs) — UI domain
  core/
    game.py            THE Game god-object: state machine, phase loop, placement,
                       spawning, income/payday, levelup, combat sweep, render, win/loss
    constants.py       enums (GameState/GamePhase/TileState) + all geometry & colors
    sprite_gen.py      procedural pixel-art sprite generation + GIF/background loading
    sprite_manifest.py imported-spritesheet system (reads assets/sprites/sprite_manifest.json)
    boss_bonuses.py    boss story-choice bonus logic
  buildings/
    building.py            abstract Building base (tier/level, upkeep, render dispatch)
    base_building.py       BaseBuilding = "The Hole" (pathfinder goal, win/loss)
    economic_building.py   Flute Player → Harp → Trio (yield)
    defence_building.py    Stone Thrower → Slinger → Pistoleer (+ Projectile)
    aoe_defence_building.py Maw Mortar line (arcing splash)
    sun_scorcher_building.py Sun Scorcher (ramping beam; subclass of DefenceBuilding)
    painter_building.py    Painter (risky lump-sum economy, self-removes)
    meditator_building.py  Meditator (compounding-streak economy, era-gated)
    boost_building.py      boost_speed/damage/hp (buff adjacent defenders)
    blocker_building.py    high-HP path soak
    wall_builder_building.py erects perimeter edge-walls
  enemies/
    enemy.py           base Enemy (path-at-spawn, movement, attack, scaling, render)
    raider.py          fast/fragile, targets economy buildings
    siege_cannon.py    slow/tanky, targets defence buildings
    boss.py            massive; spawns companions on death; per-era sizes
  map/
    tile.py            Tile: state, zone assignment, pathfinding weight, render
    tile_map.py        TileMap: grid, mouse picking, unlock + zone recede, edge walls
    pathfinder.py      weighted Dijkstra/A*; variants targeting nearest eco/def/any building
    camera.py          centring/pan; world-locked background offset
  ui/
    building_ui.py     construct/upgrade/unlock panel (DEFENCE/BOOST/ECONOMY tabs)
    hud.py             currency/round/lives, End-Turn, speed buttons, XP bar
    levelup_window.py  modal 1-of-3 upgrade picker
    main_menu.py pause_menu.py settings_menu.py credits_menu.py add_name_menu.py cheat_menu.py
    boss_cutscene.py game_log.py game_over_screen.py fonts.py
```

### Balancing (`balancing/`) — the py ↔ json override model
Each domain has a **`.py` (defaults)** and a **`Balancing_*.json` (runtime override)**.
At load, the JSON overrides keys **already defined** in the `.py`; JSON wins live.
`import balancing as B` is a frozen aggregator exposing every name.

| Defaults (.py) | Live override (.json) | Holds |
|---|---|---|
| `balancing_core.py` | `Balancing_Core.json` | starting currency, base/Hole, phase timers, combat-speed gates, zoom, XP/leveling, Lightning ability |
| `balancing_map.py` | `Balancing_Map.json` | unlock cost, pathfinding weights, damage-weight reduction, tile conditions |
| `balancing_enemies.py` | `Balancing_Enemies.json` | enemy/raider/siege/boss stats, spawn cadence, scale tiers |
| `balancing_buildings.py` | `Balancing_Buildings.json` | all `*_BUILDING_TIERS`, costs, random names, XP-on-death |
| `balancing_ui.py` | `Balancing_UI.json` | FX/render toggles, panel/HUD timing |
| `balancing_features.py` | `Balancing_Features.json` | global `FEATURE_*` boolean toggles |

Support: `balancing_loader.py` (JSON machinery, ignores `_lock`/`_section_*` marker keys),
`balancing_gui.py` + `BalancingGUI.exe` (standalone Tk editor, not runtime),
`balancing_tooltips.json`, `balancing_sessions.json`.

### Top-level & assets
- `main.py` — entry: resolve ROOT, chdir, `from src.core.game import Game; Game().run()`.
- `requirements.txt` — `pygame-ce`, `Pillow`, `opencv-python`, `pyinstaller`.
- `build.bat` + `HowToBeHuman.spec` — PyInstaller build → `dist/`.
- `assets/sprites/` — tile PNGs, backgrounds, unit GIFs, spritesheets;
  `ui/` subfolder for HUD chrome; `imported/` real spritesheets consumed via
  `sprite_manifest.json` (subfolders `buildings/`, `hole/`, `enemies/`).
- `assets/Music/Bass_and_drum_Duo.wav`, `assets/video/cutscene.mp4`.
- `tools/asset_importer.py` (slice sheets → manifest), `tools/bake_placeholders.py`
  (render procedural sprites into importer-format sheets).

---

## 2. Runtime & entry point

- Engine **pygame-ce**, Python 3. Run `py main.py` from the game dir.
- Internal resolution **640×360**; gameplay surface **320×180** rendered at **2×**
  zoom early game, dropping to **1×** at round 15 (`GAME_SCALE_ROUNDS`)
  (`constants.py:5-6`, `game.py:1872`).
- **60 FPS**; per-frame `dt` clamped to **0.05s** to avoid spiral-of-death
  (`game.py:204-205`). Main loop: `tick(60)` → handle events → `_update(dt)` →
  `_render` (`game.py:202-208`).

---

## 3. Core loop & phases

**Top-level states** (`GameState`, `constants.py:112-121`):
CUTSCENE → MAIN_MENU → (GAMEPLAY / SETTINGS / CREDITS / ADD_NAME / PAUSED /
SETTINGS_PAUSED / GAME_OVER). Boot plays a cutscene then main menu; "New Game" →
`_start_new_game` (`game.py:747`).

**Gameplay phases** (`GamePhase`, `constants.py:103-109`; driven by
`_update_gameplay`, `game.py:1192`):

| Phase | What happens |
|---|---|
| **BUILDING** | Player-driven, **no timer**. Click tiles to build / upgrade / unlock. Ends when player presses HUD **End Turn** → `_begin_enemy_phase` (`game.py:349,812`). |
| **ENEMY** | `_update_enemy_phase` (`game.py:1243`): drains the spawn queue, moves enemies, runs combat-building `update`, awards XP per kill. Ends when queue **and** enemies are both empty → `_begin_round_end`. |
| **ROUND_END** | Short delay `ROUND_END_DELAY = 1.2s`. Boss round → queue boss cutscene; else pending levelup → LEVELUP; else → INCOME. |
| **BOSS_CUTSCENE** | Modal A/B story choice after every boss round (see §7). |
| **LEVELUP** | Fully modal, pauses all updates (`game.py:1195`). Pick 1 of 3 cards; apply, `village_level++`, then → INCOME. |
| **INCOME ("PAYDAY")** | `_begin_income_phase` (`game.py:965`), duration `INCOME_PHASE_DURATION = 2.0s`. Strict order: snapshot per-building damage → base income + each yield → upkeep → painters → boosts → wall-builder cleanup → **revive/heal all non-base buildings** → clear splatters → `round_num++`. Back to BUILDING. |

**Combat speed control** (`game.py:47,1213`): `COMBAT_SPEEDS = (1.0, 1.5, 2.0, 0.0)`
indexed by `combat_speed_idx` (index 3 = in-combat pause). Only scales the
ENEMY-phase `dt`. 1.5× gated to round ≥10, 2× to round ≥20.

**Debug keys:** `Ctrl+P` cheat menu (add love, skip/goto round, force levelup);
`P` during ENEMY quick-skips the wave; `1/2/3` set combat speed.

**Win/lose.** No win — endless; game-over reports round reached, buildings placed,
enemies killed (`game.py:1822-1825`). Two lose modes via `BASE_LIVES_MODE`
(default **True**):
- **Lives mode**: each enemy that reaches the Hole costs **one life**, instantly
  kills all remaining enemies + clears the queue and ends the round.
  `BASE_LIVES = 3`; game over at 0.
- **HP mode**: Hole takes `enemy.dmg`; game over at HP 0. `BASE_KILLS_ENEMIES=True`
  → the attacking enemy dies on contact.

---

## 4. Economy — "love"

- **Start:** `STARTING_CURRENCY = 25` (`balancing_core.py:17`). Currency clamps ≥0.
- **Earned each INCOME phase** (`game.py:1010-1028`):
  - Base income = `BASE_INCOME + (village_level−1)×2` → base **5** love, +2 per
    village level above 1.
  - Each alive building with positive `yield_amount` (musicians, meditators).
  - Painter lump-sum payouts + meditator streak payouts + boss story bonuses.
- **Spent on:** building construction (`build_cost`); in-tier upgrades
  (`upgrade_cost_base + (level−1)×upgrade_cost_increment`); tier advancement
  (`tier_unlock_cost`); tile unlocking (§5); Lightning Strike; and **upkeep**
  drained each income phase (unpaid upkeep is logged, never goes negative).
- **Lightning Strike** active ability (`balancing_core.py:55-61`, `game.py:502-526`):
  unlock 20 love; upgrades cost [25, 35] for levels 2,3. Per level — damage
  [30, 350, 500] (×10 scale), radius [2,3,4] tiles, cooldown [1.0, 15.0, 10.0]s.
  During ENEMY phase, click the map to damage all enemies in radius.

---

## 5. The map

**Grid** `MAP_COLS × MAP_ROWS = 20×20`, one `(col,row)` coordinate system used for
arrays, pathfinding, spawning, render, and picking (`constants.py:21-22`). Base at
`(1,1)`; col0/row0 are BACKGROUND border; playfield is cols/rows 1..19.

**Isometric projection** (`TILE_W/H = 64/32`, half = `32/16`):
```
world_center(col,row) = ( (col+row)*32 + 32,  (col-row)*16 + 16 )
```
Inverse in `DefenceBuilding._world_to_tile` (`defence_building.py:250-259`).

**Zones** = nested square rings by Chebyshev ring `max(col,row)`
(`constants.py:34-46`, `tile.initial_tile_state`):
- **BUILDABLE** starting pocket cols 1–2 / rows 1–2 (base is BUILT).
- **COMBAT** = ring ≤ `COMBAT_RING_MAX = 9` minus the pocket.
- **SPAWNING** = 4-deep band `9 < ring ≤ SPAWN_RING_MAX = 13`.
- **BACKGROUND** = ring > 13 (impassable).

**Tile unlocking** (`tile_map.do_unlock`): a clicked **2×2 COMBAT chunk → BUILDABLE**,
then the spawn band recedes one 2×2 outward (SPAWNING→COMBAT, BACKGROUND→SPAWNING).
Cost = `BASE_UNLOCK_COST 10 + (col_section + row_section) × UNLOCK_COST_DISTANCE_MOD 5`,
where sections = Manhattan distance in 2×2 blocks from base pocket (0,0)
(`balancing_map.py:13-14`). `ADJACENT_UNLOCK_ONLY=False` by default.

**Pathfinding weights** (`balancing_map.py:18-27`, lower = preferred): economic 1,
defence 2, aoe_defence 2, painter 1, base 0 (goal), combat/spawning 1, buildable 2,
impassable 999. **Damage-based reduction** (round ≥10): the top 3 buildings by
`damage_dealt_last_round` get tile weight ×0.5, so enemies route toward whoever hurt
them most.

**Tile terrain conditions** roll on generation: grass 70%, mountain/pond/forest 10%
each. Pathweight bonus: mountain +2, pond +9, forest +1. Effects — **mountain**:
+defence range, −10% eco yield, +10% enemy dmg, enemy −0.4 speed; **pond**: +30%
defence atk interval, +10% eco yield, **impassable to enemies**; **forest**: −10%
defence dmg, +10% eco yield, +10% enemy dmg, enemy −0.4 speed.

**Edge walls** live on grid edges (`wall_edges` dict), erected by a Wall Builder on
every perimeter edge of player territory; the pathfinder treats a live-HP wall edge
as impassable and can fully enclose the base (enemies then switch to wall-attack).

**Camera** (`camera.py`): centres on the base; mouse-drag pans (>3px threshold).
Coordinates divided by zoom `scale` (2 while round ≤ 15, else 1).

---

## 6. Buildings

Base class `Building` (`building.py:18`). Each type has **tiers** (usually 3), each
tier has **levels** (usually 3). `current_tier` 0-indexed; `current_level_in_tier`
1..levels; global `level` = sum of prior tiers' levels + in-tier level.

**⚠️ The "×10 combat scale" convention.** All building/enemy **HP & DMG** in
balancing are stored ×10 (a "1 HP" unit reads as 10). Yields, costs, upkeep, speeds,
ranges, radii, timers are **NOT** scaled. The Hole's `BASE_HP = 10` is the deliberate
exception, never scaled (`balancing_core.py:7-9,42-43`).

**Stat formulas** (per level index `i = current_level_in_tier − 1`):
- HP = `base_hp + i*hp_per_level`, then ×(1+boost_hp_pct) − explosion penalties.
- Defence DMG = `base_dmg + i*dmg_per_level` (`defence_building.py:80`).
- Economic yield = `base_yield + i*yield_per_level` (`economic_building.py:52`).
- Upkeep = `base_upkeep + i*upkeep_per_level`.
- In-tier upgrade cost = `upgrade_cost_base + i*upgrade_cost_increment`.
- Tier advance cost = that tier's `tier_unlock_cost`.

**Placement** goes only through `Game.place_building(tile, btype)` (`game.py:628`),
which enforces type-unlock gating. Rules: locked types refused; boosts can't be
within Chebyshev-1 of another boost; painters can't be placed on a tile that already
completed a payout. On placement: set `tile.building`, `tile.state=BUILT`,
`buildings_placed++`, spawn VFX.

**Combat sweep** is capability-based on the `IS_COMBAT` class flag (not the type
string). Range highlighting uses **Chebyshev distance** (diagonal-inclusive square).

**On round end**, all non-base buildings `rebuild()` to full HP (revive if
destroyed); named buildings that die and revive are renamed "…the 2nd/3rd".

### Building catalogue (`balancing_buildings.py`)
| Type | Tiers I→II→III | Role / key stats |
|---|---|---|
| **base** | The Hole | Goal tile; HP 10 or 3 lives; not buildable. |
| **economic** (musicians) | Flute Player → Harp Player → Trio | Yield each income phase. T1 build 10♥, yield 5(+3/lvl); Trio yield 36(+8/lvl). HP 200→300→450. No upkeep. |
| **defence** | Stone Thrower → Slinger → Pistoleer | Direct-fire projectile, `IS_COMBAT`. StoneThrower HP150(+130/lvl), dmg50(+30/lvl), range 3, atk 0.5s, upkeep1(+1/lvl), build10♥. Pistoleer dmg120(+80/lvl). Projectile 120px/s. Targets nearest enemy in range. |
| **aoe_defence** | Maw Mortar → Catapult → Cannon | **Locked** (levelup unlock). Arcing shell to a ground point, splash `aoe_radius` (T1 1.2+0.15/lvl), range 3.5, atk 1.4s, dmg20(+10/lvl), build15♥. Predictive lead-aim. Excluded from defence-range pathfinding. |
| **painter** | Cave Painter → Maestro → Art Factory | **Locked**. Risky economy: yield 0; accrues each surviving round, pays lump sum after `rounds_to_payout` (3/4/5), then **removes itself** and bars its tile. Dying before payout = nothing. Payout T1 45(+15/lvl) → Factory 140(+40/lvl). Max 1 active. |
| **meditator** | Meditator → Shaman → Sun Priest | Economy with **compounding streak**: `yield = base_yield * streak_growth^streak`, capped at `streak_max`; **any damage resets streak to 0**. T1 growth 1.25/cap 5; SunPriest 1.35/cap 7. Era-gated round ≥10. |
| **blocker** | Blocker → Bulwark → Bastion | **Locked** (levelup). Pure HP sponge, no attack/yield/upkeep. HP 500(+250/lvl) → Bastion 3500(+1000/lvl). Cheap (build 8♥). |
| **wall_builder** | Bush → Wooden → Stone | Era-gated (r≥5), T1 needs research. On placement erects perimeter **edge walls** (wall_hp 50/120/250, NOT ×10). Upkeep 3×level. On death its walls are torn down. |
| **sun_scorcher** | Sun Scorcher → Radiant Beam → Laser Beam | **Locked + era-gated r≥15**. Subclass of DefenceBuilding. Ramping instant-damage beam: tick 0.1s, each consecutive tick on the SAME target adds `dmg_ramp_per_tick=2` up to `dmg_ramp_max` (60/60/80); target change resets ramp. Targets highest-HP enemy in range. |
| **boost_speed / boost_damage / boost_hp** | Supporting Fan → Cheerleader → Drill Sergeant | **Locked trio** (levelup, r≥8). Buff adjacent (cardinal plus-shape) defenders `boost_per_turn` 1%→2%→3% of stat per income phase. On death applies an **explosion debuff** to neighbours until a new boost is built on the tile (speed +50% interval, damage −50%, hp −50% max). Can't place within Chebyshev-1 of another boost. |
| **wall** | Wall (single tier) | Legacy standalone barrier, high pathweight, HP 500, build 5♥. |

**Three stacking content gates** (buildings CLAUDE.md): (1) **type-unlock**
(`unlocked_buildings`, flipped by a levelup reward); (2) **era gate** — tier-1
`era_unlock_round` keeps the whole type out of the levelup pool until that round;
(3) per-tier `unlock_min_round` hides individual tiers. Tier research is also
global-per-type. Enemies bias pathing away from defence-covered tiles when
`DEFENCE_RANGE_AFFECTS_PATHFINDING=True` (weight +1 per covered tile; mortars
excluded).

---

## 7. Enemies

Base class `Enemy` (`enemy.py:73`). Each enemy computes its path **once at spawn**
via weighted Dijkstra, reading tile weights live (no global cache). Movement in
camera-independent world coords; attacks blocking buildings en route, then the base.

**Scaling** (`enemy.py:88-100`): `tier = (round_num−1) // ENEMY_SCALE_EVERY_N_LEVELS`
(= 8). Bonuses are cumulative flat deltas from `ENEMY_SCALE_TIERS` (5 entries,
`balancing_enemies.py:52-62`); stats cap at the last tier but the sprite stage keeps
advancing.

**Base stats** (HP/DMG ×10):
| Type | HP | DMG | Move (tiles/s) | Atk | Starts | Count formula |
|---|---|---|---|---|---|---|
| standard `Enemy` | 70 | 10 | 1.8 | 1.0s | R1 | `5 + (round−1)*(2 + tier)` |
| `Raider` (targets economy first) | 40 | 30 | 3.5 | 1.2s | R5 | `2 + (round−5)*1` |
| `SiegeCannon` (targets defence first) | 250 | 60 | 0.5 | 3.0s | R10 | `1 + (round−10)//2`; first 5 lead queue |
| `Boss` | per-era table | — | — | every 15 | 1 per boss round |

**Spawning** (`_begin_enemy_phase`, `game.py:812`): `ENEMY_SPAWN_INTERVAL = 0.6s`,
reduced by tier, floored 0.1s. Non-boss round: build (spawn_tile, etype) lists,
shuffle the "rest", prepend leading siege. Spawn tiles read live from the SPAWNING
band each wave.

**Pathing** (`enemy.py:170-215`): Dijkstra to goal `(1,1)`. Variants target a
building before the base — raiders `find_path_to_nearest_economic`, siege
`find_path_to_nearest_defence`, boss `find_path_to_nearest_building` (any alive). If
the next tile has a living non-base building, the enemy stops and attacks it at its
`attack_speed` cadence. If walls fully block, it switches to wall-attack mode.
Terrain modifies traversal (see §5).

**Bosses** (`balancing_enemies.py:67-91`, `game.py:1262-1334`): every
`BOSS_ROUND_INTERVAL = 15`. Five eras: Bandit Chieftain (hp2000/dmg200) → Cannon
Fortress → Wrecking Ball → Iron Drill → Siege Tank (hp15000/dmg1000). Each boss
round spawns a large companion swarm (`BOSS_ROUND_COUNTS`); boss leads the queue,
then siege, then shuffled rest. On death the boss spawns a burst of enemies at its
position. Boss does **not** scale with tier. Screen shakes while a boss is alive.
After each boss round, a modal **BOSS_CUTSCENE** offers an **A/B story choice**
(`boss_bonuses.apply_choice`) granting persistent bonuses (e.g. Boss1A +dmg per empty
buildable tile; Boss1B +love per building level>2; Boss2A +love per defence; Boss3A
+dmg per 10 love).

**XP** (`balancing_core.py:31-39`): standard 1, raider 2, siege 3, boss 150. Awarded
on kill (incl. base-damage kills if `XP_ON_BASE_DAMAGE_KILL=True`) and for buildings
destroyed (1 each). Enemies cleared by a base hit still grant their XP.

---

## 8. UI & interaction

Immediate-mode panels drawn each frame on the full-res screen; floaters drawn on the
zoomable game surface.

**HUD** (`hud.py`): currency (love), round, phase; **End Turn** (BUILDING only); four
`SpeedButton`s (ENEMY only); top-left base display — in lives mode the HP bar is
replaced by `BASE_LIVES` life-faces whose mood reflects village level. Also: net
income breakdown (Base / Musicians / Meditators / Story − Upkeep), built/unlocked
tile counts, village level + XP bar, boss HP bar, defence-range/heatmap overlay, and
a Lightning cooldown indicator during combat.

**Interaction model** — tile click in BUILDING phase (`_handle_tile_click`,
`game.py:440`): classify tile as built / buildable / combat and open the
corresponding panel. **Shift+click** adds same-category tiles to a multi-selection
(batch build/upgrade/unlock). Clicking background/spawning closes the panel. Camera
drag (>3px) suppresses the click.

**Build/upgrade panel** (`building_ui.py`): construct menu has three category tabs
**DEFENCE / BOOST / ECONOMY** (`_CONSTRUCT_SPECS`). `_construct_availability` returns
(enabled, tag, hint) per gate; era-gated buildings are hidden until their round, then
shown locked/enabled. Upgrade modes (`_upgrade_state`): `in_tier` / `tier_upgrade` /
`tier_locked` / `tier_hidden` / `max_tier`. A confirm-preview shows cost +
`stats_preview()` before committing. Base tile opens an info panel.

**Levelup window** (`levelup_window.py`): fully modal, 3 option cards. Options draw
from the locked-tier research pool + one-time type-unlock rewards (Maw Mortar,
Painter, Sun Scorcher, Boost trio, Blocker), padded with repeatable fallbacks
(**+50 Love** = `LEVELUP_LOVE_REWARD`; **+1 Base HP** only in HP mode). Selecting a
research card unlocks that tier globally and deducts its cost.

**XP / village leveling** (`game.py:1501-1517`): `VILLAGE_XP_BASE_THRESHOLD = 10` to
reach level 2; each levelup raises the threshold by `VILLAGE_XP_THRESHOLD_INC = 1`
(that increment grows by `..._INC_GROWTH = 0`, flat by default). XP carries the
remainder over. Crossing the threshold sets `levelup_pending`, firing at the next
ROUND_END.

**Other menus:** main, pause (Esc), settings (display mode + Gore toggle), credits,
add-name (append to `RANDOM_NAMES`), game-over, fading game-log. Music loops from
`assets/Music/Bass_and_drum_Duo.wav`.

**Effects/floaters** (`effects.py`): `IncomeFloater` (+N♥ / −N♥ upkeep),
`XPFloater` (+N✦), `PainterMessageFloater`, plus lightning/muzzle/slash/spark/death
VFX — all store world coords and add the camera offset at render time so they scale
with zoom.

---

## 9. Rebuild-critical numbers at a glance

Start love **25** · Base income **5** (+2/village level) · Base HP **10** / **3
lives** · Round-end **1.2s**, Income **2.0s** · Enemy spawn interval **0.6s** ·
Standard enemy **70hp / 10dmg / 1.8 tiles-s** · Boss every **15** rounds · Enemy tier
every **8** rounds · Zoom **2×→1×** at round 15 · Speed gates 1.5× @ r10, 2× @ r20 ·
Unlock cost **10 + 5×(section-Manhattan)** · Grid **20×20**, base **(1,1)** · Iso
tile **64×32** · **×10 combat scale** on all HP/DMG except the Hole (`BASE_HP=10`).

**Remember:** treat `balancing/Balancing_*.json` as the runtime source of truth for
every tunable value — a designer may have changed it since the `.py` default was
written.
