# 10G–10I Batch Coordination — Orchestrator Rulings

Binding for all coder + reviewer agents in this batch. Read AFTER your phase
brief. Where a brief and this doc disagree, THIS doc wins.

## Merge order (fixed)

`phase-10g-boss` → `phase-10h-lightning-cheats` → `phase-10i-map-depth`,
sequentially into `phase-10g-i-umbrella`. 10H and 10I: anchor insertions on
CODE (function-relative), never absolute line numbers — earlier phases shift
lines. Every shared-file insertion is ONE fenced block:
`# -- 10X: <topic> --` … `# -- /10X --`.

## Cross-phase file matrix (beyond the shared trio)

The shared trio (`game/main.py`, `game/ui/hud.py`, `game/core/session.py`)
contracts in each brief §3 stand as written, with these additions:

| file | 10G | 10H | 10I | ruling |
|---|---|---|---|---|
| `game/ui/__init__.py` | +`BossCutscene` | +`CheatMenu` | +`MapOverlays` | one export line each; scope ADDED to 10H + 10I (brief omission) |
| `game/ui/building_ui.py` | base_info: BOSS CHOICES button + popup | base_info: lightning section | badges/tooltips + effective-range rows | in base_info, 10H's lightning block sits ABOVE 10G's boss-choices block; all fenced; 10I stays out of base_info except the range row swap |
| `game/ui/effects.py` | announcement + `submit_boss_bars` | `submit_lightning` (+ FX class) | — | new methods appended at class/file bottom, fenced |
| `game/core/game_state.py` | RunState boss fields | RunState 2 lightning fields | — | each a fenced field block inside RunState |
| `game/enemies/components.py` | `PathAgent.goal_is_base`/`repath_on_kill` | — | PathAgent condition tracking/speed; `EnemyCombat._effective_dmg` | different methods; 10I anchors on code |
| `game/enemies/combat.py` | `dmg_bonus=0` threading | — | two `effective_range_tiles` call sites | different regions |
| `game/main.py` click ladder order | boss-cutscene modal before `if session.frozen:` | cheat branch directly under GAME_OVER (above boss-cutscene); strike `elif ENEMY` at ladder bottom | overlay-toggle hit between end_turn branch and `panel.handle_click` | final order top→bottom: GAME_OVER → cheat → boss-cutscene → frozen/levelup → preview → hud → overlays → panel → tile-pick/strike |
| `game/main.py` render order | shake wrap; boss bars/announce near floaters; cutscene after levelup submit | cheat submit LAST (topmost) | overlays before `submit_craters`; buttons beside hud submit | keep this order at merge |

## Rulings on planner open questions

1. **`EnemyScaling.scale_every_n_levels` 9 vs prototype 10** — pre-existing
   deliberate drift (already in the baseline parity-failure set). Spec tests
   against REPO data. No change; noted in the PR.
2. **Boss `era_sizes`/`sprite_w/h`** — parity data only; slot art owns render
   sizes. Do NOT wire at runtime.
3. **Lightning starts at level 1** (prototype-live; the 20♥ unlock branch kept
   as reachable code) — implement as briefed.
4. **Cheat hotkey = Ctrl+L** (MIGRATION_PLAN.md is binding; prototype's Ctrl+P
   conflicts with repo quick-skip `P`) — documented divergence.
5. **Pond is EXPENSIVE (+9), not impassable** — ship prototype CODE behavior;
   the "impassable" line in MIGRATION_AGENT_READ_FIRST.md §5 is doc drift.
   Noted in the PR for a user ruling later.
6. **Cheat "unlock all" covers meditator + blocker** (prototype omits them —
   bug) — accept the clean-migration fix; documented divergence.

## Exit gate (every coder, every reviewer fix pass)

1. `py tools/smoke.py` green.
2. `py -m unittest discover -s tools/tests -t .` — **no failures beyond the
   18-entry baseline below**, and your phase's new tests green.
3. Commit to YOUR phase branch only. Never push. Never touch files outside
   your brief §3 + this doc's matrix.

### Baseline failure set (recorded on umbrella base, 2026-07-12)

```
test_balancing_parity (×6): INCOME_PHASE_DURATION, ROUND_END_DELAY,
  BASE_ENEMY_COUNT, ENEMY_SCALE_EVERY_N_LEVELS, SPAWN_RAMP_RANGE,
  BASE_UNLOCK_COST
test_combat_speed: test_2x_spawns_the_wave_faster_than_1x
test_details_panel: test_too_small_sheet_rejected,
  test_context_populates_dropdown_with_markers
test_editor_map_mode: test_maps_branch_lists_files_with_active_marker,
  test_layer_eyes_filter_submitted_items
test_editor_panels: test_import_save_clear_update_preview_without_restart,
  test_markers_reflect_migrated_manifest
test_editor_viewport: test_draft_override_never_touches_disk,
  test_preview_animations_and_dropdown_follow_the_slot,
  test_reload_assets_sees_disk_change_and_keeps_camera,
  test_unusable_draft_falls_back_instead_of_raising
test_run_controls: test_build_finished_reemits_build_state
```
