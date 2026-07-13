<!-- active-plan: MIGRATION_PLAN.md | set: 2026-07-13 -->
> **Active plan:** MIGRATION_PLAN.md (mirror). Source of truth:
> `planning/MIGRATION_PLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

# Phase 9+ Migration Plan — Full Gameplay Port from Prototype

## Context

Phases 0–8 built the clean-architecture shell: `engine/` (coords, GameObject/Component/Scene, render pipeline, asset manifest v2, validating data writer, tilemap format) minus physics; a complete PySide6 `editor/`; `data/` schemas + placeholder balancing; `game/` is an empty skeleton (window host rendering the active map + dummies). Phase 9+ ports the entire gameplay from the prototype at `../HowToBeHuman/ClaudePrototype/HowToBeHuman` so the rebuild plays **exactly** like the prototype — not a single QOL feature missing — but on clean architecture: balancing per BALANCING_REPLAN.md's feature tree, parent classes for buildings with thin per-building leaves, all state in components, all tunables in `data/balancing/`.

Both repos were swept exhaustively (all docs, all `src/` modules, all `Balancing_*.json`, `.claude/` commands, asset pipeline). The prototype's live JSON values are authoritative (BALANCING_REPLAN.md tables match them; the `.py` defaults have drifted and are ignored).

## User decisions (binding)

1. **Balancing first**, REPLAN nested tree **inside the existing 5 lockable domain files** (`data/balancing/{buildings,enemies,map,ui,core}.json`); schemas mirror the tree.
2. **Clean migration**: drop dead keys; one canonical flag per feature, actually wired. Runtime behavior identical to what the prototype *does*.
3. **First playable = minimal core loop** (Stone Thrower + Flute Player lines, standard enemy, unlock/recede, pathfinding, round loop, HUD + build/upgrade panel, game over) **plus the shell** (main menu, settings, credits, add-name, cutscene, music) — user chose shell "with first playable".
4. Everything else layers in afterwards, phase by phase, until full parity.

## Standing architecture decisions

### Buildings — component/subclass line
```
Building(GameObject)                    game/buildings/building.py
├─ EconomyBuilding                      Musician, Meditator, Painter
├─ DefenceBuilding                      Defender, AOEDefence, SunScorcher
├─ BoostBuilding                        ONE class × 3 data lines (speed/damage/hp)
└─ StructureBuilding                    Blocker, WallBuilder
```
- **Components own ALL authoritative state** (`game/buildings/components.py`): `TierState` (building_type, current_tier, current_level_in_tier), `Nameplate` (custom_name, rebirth_base, rebirth_gen), `RoundStats` (dmg dealt/taken this/last round), `BoostReceiver` (boost pcts + explosion debuffs), `Attacker` (cooldown, target, ramp — its presence + a `"combat"` tag replaces the prototype's `IS_COMBAT` class flag per SPEC G-3), `YieldEconomy` (streak), `PainterProgress`, `BoostEmitter`, `WallBuilderState`; plus engine `Health`, `SpriteAnimator`, `RangeSensor`.
- **Anything derivable from TierState + balancing data is a computed method on the parents** (max_hp, upgrade_cost, upkeep, yield, dmg, at_tier_max, upgrade(), advance_tier(), rebuild()/rebirth, boosted_stats()). **Leaf classes ≤ ~30 lines**: balancing subtree path, slot-key prefix, tags, component wiring only.

### Enemies
`Enemy(GameObject)` wiring `Health` + `Movement` + `SpriteAnimator` + game components `EnemyCombat` and `PathAgent`. Thin subclasses `Raider`/`SiegeCannon`/`Boss` (+ `BossState`). Scale-tier stats resolved **at spawn** into component fields. Dijkstra stays in `game/map/pathfinder.py`; enemies consume waypoints via `Movement`.

### UI without pygame
Engine grows a **screen-space HUD pass** (`HudRect/HudText/HudSprite/HudLines`, fonts in the render backend, `TextMetrics` for layout). `game/ui/` is pure logic emitting HUD items; world-anchored UI (range diamonds, floaters, HP bars) uses the existing `overlay` layer via `engine/coords`.

### Engine additions (all in 9B)
`engine/physics/` (E-30/31/32) + `Movement`/`RangeSensor`; HUD pass + fonts; RenderItem horizontal flip + tint flash; `engine/audio.py` (mixer wrapper, no-op headless); `engine/video.py` (OpenCV frame source, graceful skip if cv2/file missing — prototype-exact). Screen shake = host camera-pan jitter, no engine change.

### Balancing resolutions
- **ui stays its own domain; no vfx domain** — FX tunables fold into `ui.json` `FX` subtree (matches REPLAN "UI / Timing + FX & Art"). Resolves SPEC §9 open question.
- **Features file dissolved**: `FEATURE_*` flags are never read by prototype `src/` (verified). Each concept keeps ONE canonical wired flag in its owning domain: gore → `ui.FX.gore_enabled`, revive → `core.TheHole.building_revive`, bg art → `ui.FX.bg_art.*`, income floaters / boss announcement → `ui.FX`, xp-from-buildings → `core.XP`.
- **Painter**: per-tier `rounds_to_payout`/`goneforgood` win (verified `painter_building.py:50-54` — global is a dead fallback). Migrate per-tier; keep `PAINTER_UNLOCK_MIN_VILLAGE_LEVEL` (read at `game.py:1609`) and per-category `xp_on_death`. **Drop**: loose PAINTER_* seed globals, `PAINTER_MAX_ACTIVE` (never read), legacy `WALL_BUILDING_TIERS` (no class exists).

---

## Phases to first playable

### 9A — Balancing migration (data + schemas + editor + parity gate)
No game code. All five `data/balancing/*.json` restructured to the REPLAN tree with the prototype's live values verbatim (×10 scale; `base_hp: 10` exception; per-key `description` + min/max in schemas):
- `buildings.json`: EconomyBuildings{Musicians, Painters, Meditators} / DefenceBuildings{globals, BasicDefence, AOEDefence, BeamDefence} / BoostBuildings{globals, Speed, Damage, HP} / StructureBuildings{Blocker, WallBuilder} / BuildingsGlobal{defence_range_pathfinding, xp_on_death, random_names}.
- `enemies.json`: EnemyTypes{Standard, Raider, SiegeCannon, Boss{stats, shake, death_spawns, era_sizes, round_counts}} / EnemyScaling / MortarTargeting. (ENEMY_SCALE_TIERS, BOSS_ERA_SIZES, BOSS_ROUND_COUNTS are struct-lists — keep their shape.)
- `map.json`: TileUnlocking / Pathfinding{content_weights, damage_reduction} / TileConditions{path_weights, spawn_chances, modifiers}.
- `core.json`: General / PhaseLoop / XP / TheHole / LightningStrike (arrays as real JSON arrays, not the prototype's stringified lists).
- `ui.json`: Timing / FX (incl. bg_art block, boss announce timings, gore).
- Rewrite `data/schemas/{buildings,enemies,map,ui,core}.schema.json` to mirror (draft 2020-12, additionalProperties:false, all required).
- **Editor**: extend `editor/panels/balancing.py` `_rebuild_form` to recurse — nested objects → collapsible group boxes, tier arrays → per-tier sub-sections, scalar arrays → per-index spinboxes. Writes stay whole-doc via `write_validated`.
- **Parity gate**: `tools/tests/test_balancing_parity.py` + committed mapping table — every prototype live-JSON key → new path | DROPPED:reason | MERGED:target; asserts value equality (skip-if-prototype-absent).
- Locks: all five domains touched — run as a coordinated batch.
- **Quick Test**: editor shows the nested tree; tweak Stone Thrower base_dmg, JSON validates + nests, undo; `py tools/smoke.py` OK; parity test green.

### 9B — Engine completion (parallel-safe with 9A)
`engine/physics/{grid,occupancy,movement}.py`; `Movement`+`RangeSensor` components; `Scene.query_area` wired; HUD pass + fonts + flip/tint; `engine/audio.py`; `engine/video.py`; requirements + `tools/build.py` gain opencv; commit music/video assets (decide `data/audio|video/` location). Chebyshev range semantics identical to prototype targeting.
**Quick Test**: unit tests for grid/occupancy/waypoints/HUD items; `tools/render_demo.py` shows text + a waypoint-following dummy; smoke OK.

### 9C — game/map: tile runtime + pathfinder
`game/map/{tiles.py, tile_map.py, pathfinder.py, picking.py}`: runtime TileState over the map doc; 2×2 chunk unlock, adjacent-only rule, exact cost formula, spawn-zone recede; **full** Dijkstra port (all five find_path variants, wall-block hook, damage/defence-range/condition weight inputs ported now, fed neutral values until 10x). Occupancy syncs to engine physics.
**Quick Test**: unlock-chunk fixture asserts receded tiles + costs match prototype; spawn→base path matches prototype on identical grid.

### 9D — game/buildings: hierarchy + Defender + Musician
`game/buildings/{components,building,economy,defence,base_building,defender,musician,registry}.py` + `game/core/balance.py` (the single validated balancing loader). Placement, upgrade/tier math (exact level property + cost formulas, full-heal on upgrade), per-tier slot keys, upkeep/yield, death/rebirth.
**Quick Test**: headless test upgrades both lines to tier max asserting hp/dmg/yield per REPLAN tables at every step; live: both animate on tiles.

### 9E — game/enemies: standard walker + spawner + combat
`game/enemies/{enemy,spawner,combat}.py`: full prototype spawn-queue logic (counts, ramp, 0.4–1.6× jitter; raider/siege/boss branches present but zeroed), targeting via RangeSensor, enemy↔building↔base combat, `DEFENCE_MIN_ATTACK_SPEED` clamp.
**Quick Test**: scripted round asserts HP ledger matches hand-computed prototype values.

### 9F — game/core: phase machine + payday ordering + game over
`game/core/{phases,payday,game_state,session}.py`. Payday = **ordered step list mirroring prototype `_begin_income_phase` exactly**: snapshot → (boss-bonus slots) → base income + yield sweep → upkeep sweep (clamp 0) → (painter slot) → (boost slot) → (wall-teardown slot) → revive → (rebuild-walls slot) → round++. Later phases fill reserved slots at their exact positions. Ordering is sacrosanct.
**Quick Test**: phase-machine unit tests; headless 3-round currency ledger matches prototype-computed values.

### 9G — game/ui: HUD + building panel + floaters + game over
`game/ui/{widgets,hud,building_ui,effects,game_over}.py`: HUD (love panel, round, base HP, End Turn, phase banner), unlock/construct/upgrade/base-info panel modes, ConstructPreview (name entry, confirm/cancel per ui.Timing), income/upkeep floaters, not-enough-love flash, building HP bars; input routing + click-consume priority in `game/main.py`.
**Quick Test**: live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game over screen.

### 9H — Shell → **FIRST PLAYABLE**
`game/ui/{main_menu,pause_menu,settings_menu,credits_menu,add_name_menu,cutscene}.py` + outer state machine (CUTSCENE→MAIN_MENU→GAMEPLAY/PAUSED/…): cutscene (44.2 s, skippable, graceful-skip), looping music, settings (display mode, gore toggle, volume), credits, add-name (writes `random_names` via write_validated — the one runtime data write).
**Quick Test**: cold `py game/main.py`: cutscene → menu → 10+ rounds with both tier lines → pause/settings → menu → add name → credits. Then Build → same flow in the frozen exe.

## Layering phases (each independently shippable)

- **10A — XP / village levelup / research + era gates**: XP per kill + floaters, LEVELUP phase (ROUND_END→[LEVELUP]→INCOME), option roll port (tier research, type unlocks, fallbacks, era gates), levelup love reward, base income +2/level.
- **10B — AOE Mortar + Sun Scorcher**: splash + predictive lead targeting + crater; scorcher ramp/reset, target-death cooldown, beam FX.
- **10C — Painter + Meditator**: payout cycle in the payday painter slot, tile freed + permanently barred, gone-for-good + "painting lost!"; meditator compounding streak + reset on damage.
- **10D — Boost buildings**: cardinal adjacency, per-turn vs flat mode, explosion debuff on death, adjacency placement block, boost highlights + boosted_stats in panel.
- **10E — Blocker + WallBuilder + edge walls**: wall-edge registry, perimeter place/teardown/rebuild, enemy wall-attack mode, find_path_ignoring_walls live.
- **10F — Raider + Siege + scale tiers + combat speed** *(LANDED)*: spawner raider/siege branches enabled (Boss still gated to 10G), ENEMY_SCALE_TIERS + per-era sprite stages (Standard + Siege scale, Raider deliberately does not), combat-speed mechanic (`COMBAT_SPEEDS` + round-gated selector on `Session`, ENEMY-phase-only dt scaling) with `1`/`2`/`3` keys + bare-`P` quick-skip.
  - **Deferred to 10L**: the lives-**faces** indicator and the 1×/1.5×/2×/pause **buttons** — both are HUD surfaces that hook into the UI editor. 10F ships the mechanic they will drive (`Session.set_combat_speed` / `toggle_pause`); lives stays a `LIVES {n}` text readout until then.
  - **Deferred (needs re-path support)**: the prototype's differentiated targeting — raiders hunting economy buildings, siege hunting defence. Raiders/siege currently seek the base and eat whatever blocks them. See `game/enemies/CLAUDE.md` for why (a path ending on a targeted building fires a phantom base hit when that building dies).
- **10G — Boss** *(LANDED)*: era stats/sizes, boss-round queue composition, announcement, screen shake, death-swarm, boss HP bar, boss cutscene A/B + boss_bonuses port (payday hooks into reserved slots), boss history panel.
- **10H — Lightning strike + cheat menu** *(LANDED)*: unlock/upgrade at base-info, click-to-strike + effect + cooldown HUD; full cheat menu (Ctrl+L — deliberate divergence from the prototype's Ctrl+P; bare `P` is the quick-skip key).
- **10I — Map depth** *(LANDED)*: tile conditions (spawn chances, stat modifiers, tooltips, badges), damage-based path-weight reduction, defence-range path weights, RANGE + HEATMAP overlay toggles.
- **10J — QOL & FX sweep** *(LANDED)*: shift multi-select batches, name dice + rebirth ordinals, next-tier preview, income tooltip breakdown, game log, all remaining floaters/FX (spark bursts, gold highlights, death bursts, muzzle/slash, projectile dots), gore/blood splatters, DIED LAST ROUND tag, hover cost preview. Also landed here: engine per-pixel alpha (RGBA HudRect/HudText + filled `OverlayPolys`) and the alpha retro-fixes parked by 9H/10B/10G/10H/10I (modal dims, filled tint/RANGE/HEATMAP overlays, announce/floater fades, crater/lightning fills + impact flash).
  - **World background art: CUT (design decision).** 10J originally shipped a `background_master` world-art underlay painted into the `GroundCache`, which suppressed every `BACKGROUND`-zone tile so the art could show through. The world background is instead built from **background tiles + deco props**, so the underlay, its slot/manifest entries, the 4096 schema cap raise, and the tile-skip were all dropped before merge. `BACKGROUND` tiles are authoritative and always render.
  - **Accepted divergences**: enemy low-HP sprite blood-blotches approximated by the engine tint path (no per-pixel sprite mutation); splatters/craters draw in the overlay pass, i.e. over sprites; particle velocities eyeballed around the prototype presets (life/count/colour exact); overlay diamond borders are opaque lines; the beam's alpha glow stays a plain line. The XP mascot face / `xp_icon` still has no slot → 10L/11.
- **10K — Main menu background image** *(LANDED)*: the prototype's 480×270 `MainMenuBackground.png` imported through the asset pipeline (new asset-only `backgrounds` category / `main_menu_bg` slot in `data/slots.json`, sheet + manifest entry via `editor.asset_import.import_idle_sheet` → `write_validated`); `game/ui/main_menu.py` submits a full-view `HudSprite("main_menu_bg", (0, 0), (view_w, view_h))` between the solid fill and the widgets.
  - **Editor control = the existing import flow**: the selector tree auto-surfaces the new category and the DetailsPanel "Import Spritesheet…" picks/swaps the PNG (manifest written via `write_validated`) — deliberately NO new picker widget and NO configurable slot reference in balancing; the game hardcodes the slot key (fixed-slot decision).
  - The solid `_BG` fill stays beneath the sprite as the missing-art fallback (grey-X tolerance, E-37).
  - Letterboxing is the host's SDL `SCALED` concern: the sprite fills the 1280×720 logical view (480×270 source, same 16:9 aspect — uniform stretch, prototype-exact behavior).
- **10L — UI editor + deferred HUD surfaces**: the designer-facing UI editor, plus the HUD readouts held back for it — the **lives-faces indicator** (`life_face_*` slots + escalating expression by village level; needs `slots.json` entries, which do not exist yet) and the **1×/1.5×/2×/pause speed buttons** (round-gated; call the `Session` combat-speed API that 10F already ships). *Scope is a placeholder — 10F's deferrals are parked here.*
- **11 — Full parity audit + editor alignment**: committed `PARITY.md` (prototype module → new home, every feature checked), editor per-tier balancing focus + entity-preview range from new paths, PLAN.md phase table update, playtest to round 30+ (two boss cycles) + frozen-exe playtest. **Exit rule: nothing from the prototype inventory missing.**

## Verification (every phase)

1. `py tools/smoke.py` (data validation + 5-frame headless boot) — report what was verified.
2. `py -m unittest discover -s tools/tests -t .` — existing 336 tests stay green + new per-phase tests.
3. The phase's concrete Quick Test scenario, live, before commit/PR.
4. 9A additionally: balancing parity test against the prototype's live JSON.
5. Branch + lock protocol per domain throughout; PLAN.md phase table updated as phases complete.
