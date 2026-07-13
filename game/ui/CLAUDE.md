# CLAUDE.md — game/ui (Phases 9G + 9H + 10A + 10G + 10H + 10I + 10J UI)

HUD, building panel, floaters, game over, and the top-level shell/menus. You
reached here from `game/CLAUDE.md`. When you change UI conventions, update THIS
doc.

**Layering rule: `game.ui → game.core` is ONE-WAY** (`hud.py` imports
`game.core.phases`). `game/ui` is **pygame-free** like all UI logic (a source-scan
`TestPurity` guards it — it may import `engine.render.fonts`, a sanctioned pygame
module, so it imports pygame only *transitively*); visuals go out as the engine
HUD layer (G-6). The shell therefore lives in **`game/ui/shell.py`**, NOT
`game/core` (that would be circular).

## In-round UI (9G)
`game/ui/{widgets,hud,building_ui,effects,game_over}.py`: HUD (love panel, round,
base HP, End Turn, phase banner), unlock/construct/upgrade/base-info panel modes,
ConstructPreview (name entry, confirm/cancel per `ui.Timing`), income/upkeep
floaters, not-enough-love flash, building HP bars; input routing + click-consume
priority in `game/main.py`. Every menu screen mirrors the `game_over.py`
construct→layout→update→hit→submit template + `widgets.Button`.

## Overhead HP bars
`effects.py` draws them in TWO passes, both reading live scene state and both
hiding the bar at full HP (the prototype rule):
- **`submit_hp_bars`** — buildings (`scene.by_tag("building")`, base excluded),
  fixed 28×4.
- **`submit_enemy_hp_bars`** — **every** enemy, boss included (the boss carries
  the `"enemy"` tag via `Enemy.EXTRA_TAGS`, so this is the ONLY place an overhead
  enemy bar is drawn). Width/height are the `HP_BAR_W`/`HP_BAR_H` class attrs on
  the enemy classes (walker/raider 14×2, siege 24×2, boss 48×4 — see
  `game/enemies/CLAUDE.md`), read duck-typed with a fallback. Bars from enemies
  sharing a tile **stack upward** 4 px per slot (prototype `game.py:1901-1922`
  `bar_slot`); grouping is a plain `round(wx), round(wy)` because our
  `transform.wx/wy` are already fractional TILE coords, where the prototype had
  to divide pixel coords by the tile half-dims. **Divergence:** the prototype
  gave a slot to every enemy in a group, full-HP ones included (leaving gaps),
  because that index also drove its sprite-spread ellipse; we don't port the
  spread, so slots go out compactly — only a bar-drawing enemy takes one.

Both are fixed screen-pixel sizes (never zoom-scaled), anchored through
`cs.world_to_screen(wx + 0.5, wy + 0.5)` so they track the camera, and emitted on
the HUD pass — i.e. always on top, never depth-sorted (the accepted "HUD on top"
simplification). Covered by `tools/tests/test_enemy_hp_bars.py`.

## Level-up UI (10A)
`game/ui/levelup.py` (`LevelupWindow`, the `game_over.py` template; it lays out on
`open` because hover/hit run before the first `submit`), an XP bar + `LVL N` in
`hud.py` (gold + pulsing when pending), purple XP floaters via
`FloaterManager.spawn_xp_events` (drained every frame, not at a phase edge), and
the gated construct list + five-mode upgrade button in `building_ui.py`. The modal
sits at the TOP of `main.py`'s click ladder and swallows keys. (The pure roll/gate
logic is `game/core` — see that doc.)

## Boss UI (10G)
- **`boss_cutscene.py`** (`BossCutscene`) — the `levelup.py` modal template
  (construct→`open(boss_num, outcome)`→layout-on-open→update→hit→submit): opaque
  near-black backdrop, win/loss headline + "How will we react?", two 180×130
  boxes labeled `WinA/WinB` (or `LossA/LossB`) with descs from
  `game.core.boss_bonuses.BOSS_CHOICES`. `hit` returns `"A"`/`"B"`/None — NO
  dismiss path; it sits above `session.frozen` in `main.py`'s click ladder and
  the frozen key-gate swallows keys. Opened by the host on the BOSS_CUTSCENE
  phase edge from `state.pending_boss_cutscene` (the LEVELUP pattern).
- **`effects.py`** grew three fenced 10G members: `spawn_boss_events(state)`
  drains the `boss_events` announce markers (gated by
  `ui.FX.boss_announce.enabled`); `submit_announce` draws the centred two-line
  "SOMETHING BIG / IS APPROACHING!" banner over the
  `boss_announce.{fade_in,hold,fade_out}` timings (a real text-alpha fade
  since 10J); `submit_boss_bars(renderer, cs, scene, phase, view_w, view_h)`
  finds the live boss via `scene.by_tag("boss")` and draws the bottom-centre
  200×12 HUD bar ("BOSS" + `hp/max`, ENEMY phase only). Its **overhead** bar is
  NOT drawn here — see the enemy HP bars below, which own every overhead bar in
  the game (the boss is tagged `"enemy"` too, so it comes along for free and can
  never double up).
- **`hud.py`**: BOSS_CUTSCENE phase label/color entries, and one fenced block
  in `income_breakdown` adding the boss-bonus story income (slot-3 payouts +
  Boss2A/2B deltas × alive recipients) so the HUD net keeps matching payday.
- **`building_ui.py`** base_info mode: a "BOSS CHOICES" button (10H's lightning
  section sits ABOVE it) opening a centred history popup — one row per
  `state.boss_choices` entry (`"Boss {n}: {Outcome} {option}"`), the hovered
  row's bonus desc as a tooltip line, "None yet" when empty, Close; the popup
  consumes clicks inside itself.
- **`game/main.py`** owns the screen shake: a transient `cs.pan(ox, oy)` /
  `cs.pan(-ox, -oy)` wrap around the world render branch (NO clamp between),
  parameters from `Boss.shake.{interval,strength}`, active only while ENEMY
  phase + a live `"boss"` in the scene.

## Shell + menus (9H)
`game/ui/shell.py` wraps a run — ports the prototype's `GameState` shell
(`src/core/game.py` dispatch):
- **`Shell` is pure** (pygame-free; a source-scan purity test in `test_shell.py`
  guards it). It owns `state` (`GameState`), the five menu screens
  (`main_menu`/`settings`/`credits`/`add_name`/`pause`, each the `game_over.py`
  template), the session-only `SessionSettings`, and `settings_caller` (SETTINGS is
  reused for both entry points — NO `SETTINGS_PAUSED` state). It applies pure
  transitions itself and returns an **intent string** only for host-side
  (pygame/disk) actions: `new_game` / `quit_to_menu` / `quit_app` /
  `set_display_mode` / `add_name_commit`.
- **The host (`main.py`) executes intents + owns the pygame-only concerns** the
  pure shell can't: window (re)creation (`_apply_display_mode` — SCALED keeps the
  logical surface `view_w×view_h` in all three modes so coords/renderer/hit-rects
  never change, E-5), the cutscene raw-surface blit, `engine.audio.play_music` (one
  looping track; windowed runs only), and the `_World` lifecycle
  (`build_gameplay`/`teardown_gameplay` — a fresh `_World` = a fresh run; menus
  hold NO world). The frame loop is three per-`shell.state` switches
  (input / update / render); the 9G in-round click ladder runs only in GAMEPLAY.
  Esc opens PAUSE in gameplay / backs out of menus (was: quit).
- **Cutscene = FULL video** via the 9B `engine.video.VideoSource`
  (`data/video/cutscene.mp4`, length from `ui.json Menu.cutscene_length`);
  graceful-skips to MAIN_MENU when cv2/file absent (headless).
- **ADD_NAME persists** via `game/core/names.py append_random_name` (see
  `game/core/CLAUDE.md`); the host also appends to the in-memory `buildings_balance`
  so it goes live.
- **Headless seam**: `main(autostart=True)` skips the shell straight into GAMEPLAY
  so `tools/smoke.py` + the boot tests still exercise the full `_World`/`Session`
  construction + sim the menu would otherwise defer.
- **Main-menu background (10K)**: `main_menu.py` submits a full-view
  `HudSprite("main_menu_bg", (0, 0), (view_w, view_h))` between the solid fill
  (kept as the missing-art fallback) and the widgets. The art comes from the
  asset-only `backgrounds` slot category through the normal import pipeline —
  no host raw-surface code; SDL `SCALED` letterboxes the logical surface, so
  the full-view sprite is letterbox-safe by construction.
- **No world background art**: the *in-world* background is built from
  `BACKGROUND` tiles + deco props, never a full-map image. 10J's
  `background_master` `GroundCache` underlay was cut before merge (it suppressed
  `BACKGROUND` tiles to show art through); `backgrounds` is a main-menu-only
  slot category. Do not reintroduce a world-art underlay.
- **Deferred**: the settings audio slider is inert (no audio system beyond
  music). (The pause dim landed with 10J's HUD alpha.)

## Defence FX (10B)
`effects.py` `FloaterManager` grew `submit_beams` + `submit_craters`, drawn from
live scene state (like `submit_hp_bars`): a per-tier colored `HudLines` from each
firing Sun Scorcher to the enemy its `BeamAttacker._target` names, and a fading
world-space diamond for each `"crater"` GameObject a mortar shell left (the
`Crater` objects age + self-despawn in the scene; the FX just draws them). This is
the sanctioned `game/ui → game/buildings.components` read (building_ui already
imports it). 10J made the crater an alpha-filled diamond; the beam stays a
plain line (an alpha GLOW under it remains unported — `HudLines` carries no
alpha; accepted).

## Lightning + cheat menu UI (10H)
The pure rules live in `game/core/lightning.py` (see `game/core/CLAUDE.md`);
`game/ui` renders + routes:
- **`cheat_menu.py`** (`CheatMenu`, the `game_over.py` modal template) —
  toggled by **Ctrl+L** (deliberate divergence from the prototype's Ctrl+P:
  bare `P` is this repo's quick-skip key). It NEVER mutates game state: every
  click/key returns an action string (`close` / `add_love` / `skip_round` /
  `trigger_levelup` / `inf_money` / `unlock_all` / `("goto_round", n)`) that
  `main.py _execute_cheat` maps onto `Session` cheat methods; the stays-open
  rule lives in the host (only close / LEVEL UP / a committed goto close it).
  Gameplay-only, works over the LEVELUP modal, not on GAME_OVER/pause/menus;
  while open it consumes ALL input (top of the click ladder, directly under
  GAME_OVER) and renders topmost. Click-to-focus round field: digits only,
  max 4, Enter commits (n ≥ 1).
- **`building_ui.py` base_info** grew the ⚡ LIGHTNING STRIKE section: level +
  DMG/Radius/Atk-Spd rows from `core_balance["LightningStrike"]`, an
  UNLOCK/UPGRADE button (not-enough-love flash) that disappears at max level
  behind a gold MAX LEVEL line. Reads via `game.core.lightning` (the
  sanctioned ui→core direction).
- **`hud.py _submit_lightning`** — ENEMY-phase-only bottom-left readout
  (`⚡ CLICK TO STRIKE` / countdown) + a 22×3 cursor-attached progress bar
  (`Hud.update` now stores `_mx/_my`).
- **`effects.py submit_lightning`** — draws each `"lightning_fx"` scene object
  (the `submit_craters` pattern): a jagged screen-space `HudLines` bolt from
  y=0 to the impact (±6 px jitter per frame, white→yellow over 0.5 s) + a
  fading yellow world-space diamond sized to the real blast radius (projects
  to the prototype's 2:1 ground ellipse). 10J added the alpha fill, an
  expanding impact-flash polygon, and the alpha marker fade.

## Map overlays + terrain badges (10I)
`game/ui/overlays.py` (`MapOverlays`, pure — covered by the purity scan) owns
ALL of 10I's UI so `hud.py` (10G boss bar + 10H lightning both edit it) carries
no 10I diff: two persistent bottom-left toggle pills (`RANGE`/`HEATMAP`, gold
rim + gold label when active; clicks consumed in `main.py`'s ladder between the
End-Turn branch and the panel, `over()` feeds the pan-arming `over_ui` check),
the world condition tint (windowed — never a full-grid scan), the RANGE overlay
(union Chebyshev squares from RAW `range_tiles()`, mortar INCLUDED — its
exclusion is pathfinding-only — plus a cardinal plus-shape per `"boost"`
occupant), and the HEATMAP overlay (previous round's distinct-enemy traffic:
`track()` accumulates `id(e)` per tile during ENEMY and snapshots counts on the
phase edge; blue→yellow→red ramp in `heat_color`). `widgets.COND_LABELS`
(condition label + colour, keyed by `TileCondition.name`) is shared with
`building_ui`'s new terrain badges: a `Terrain: <Label>` pill in the upgrade
panel (below Level, reads the building's `_tile_condition` snapshot) and at the
unlock/construct panel foot (reads the tile), each with a hover tooltip whose
effect lines read LIVE from `TileConditions.modifiers` (enemy effects
deliberately unlisted, prototype-exact); the tooltip draws last/on top.
`base_info` shows NO badge. The panel Range row + selection range highlight use
`effective_range_tiles()` when present (mountain +1); the RANGE overlay stays
raw.

## QOL + FX sweep (10J)
The engine grew per-pixel alpha (RGBA `HudRect`/`HudText` + the filled
`submit_overlay_polys` — see `engine/render/CLAUDE.md`), which unblocked the
parked visuals; everything below reads its trigger state live off the
scene/state (the watcher / drained-ledger house patterns), no new core→ui
imports:
- **Shift multi-select batches** — selection state (`gp["sel"]`/`gp["sel_cat"]`,
  category `built|buildable|combat`) lives in `main.py`'s BUILDING click branch
  (prototype `game.py:440-563`): same-category shift-clicks toggle, mixed
  categories are ignored silently, plain click restarts. `BuildingUI
  .open_for_tile(..., selected_tiles=[primary, …])` batches: **unlock**
  dedups 2×2 chunks (`_unlock_chunks` frozenset key, summed cost, "UNLOCK n
  AREAS"), **construct** = cost×count with the chosen name on the FIRST tile
  only, **in-tier upgrade** sums `_batch_upgrade_targets`; tier ADVANCE stays
  primary-only. Range diamond only when the selection is a single tile. The
  base never batches.
- **Name dice + rename row** — "⚄" beside the ConstructPreview name box and in
  the upgrade panel's new rename row (both fill the edit buffer from
  `BuildingsGlobal.random_names`); the upgrade title is now the DISPLAY name
  (custom + rebirth ordinals visible); `_commit_rename` skips a no-op rename so
  it can't reset the rebirth chain. `BuildingUI.name_editing` gates the host's
  key routing.
- **Next-tier preview** — hover-gated green in-tier stat values
  (`_next_level_rows`, a throwaway `create()` clone copying tier cursor +
  boost/condition/streak context) + the `_next_tier_card` (divider, "Next:
  <name>", sprite thumb, first 3 stats) in `tier_upgrade`/`tier_locked` modes;
  plus the red **DIED LAST ROUND** tag when `RoundStats.dmg_taken_last_round >=
  max_hp()`.
- **Income tooltip** — `hud.income_sources(session)` is the ordered per-source
  list (Base/Musicians/Meditators/Story/−Upkeep); `income_breakdown` sums it so
  pill and tooltip can't drift; hovering the income line shows the prototype's
  coloured breakdown.
- **Game log** (`game_log.py`) — 4 s lifetime / fade from 3 s / max 5, stacked
  above the phase banner; fed by direct `post()` calls (unlock refusal,
  building kills via the death watcher) and `drain(state)` over the new
  `RunState.log_events` ledger.
- **FX** (`effects.py`) — `spawn_building_vfx` (spark presets place/level1/
  level2/tier + gold tile highlight, wired as `panel.on_build_vfx`),
  `watch_buildings` (death burst + kill log; alive-flip watcher),
  `watch_enemies` (muzzle/slash on an `EnemyCombat.cooldown` reset while
  blocked — no core hook needed), `submit_projectiles` (stone/shell dots —
  9E's invisible projectiles), blood splatters (`RunState.enemy_death_events`
  ledger; double-gated `ui.FX.gore_enabled` AND the settings toggle; cleared
  on the ENEMY-phase edge), and alpha versions of the crater / lightning
  marker / boss-announce / floater fades + an expanding lightning impact
  flash.
- **Modal dims** are the prototype's real alphas now: levelup 185, boss
  cutscene 210, cheat menu 150, pause 150 (the 9H deferral).

## Known divergences (deliberate)
The XP bar/floaters drop the prototype's mascot face + `xp_icon`, which has no
slot in `data/slots.json` (revisit at the 10L UI-editor phase / 11 parity
audit). Lightning FX are NOT force-cleared at `_begin_round_end` (the prototype
clears `_lightning_effects` there, `game.py:943`): like the mortar craters, the
`"lightning_fx"` objects simply age out in the scene (`MARKER_LIFE` 1.0s ≈ the
crater's `CRATER_LIFE`), so a strike landed in the final combat instant lingers
≤0.4s into REBUILDING — the same accepted behavior craters already have (10H).
10J's remaining approximations: the enemy low-HP sprite blood-blotches
(`_apply_gore`) are approximated by the engine tint path rather than per-pixel
sprite mutation; splatters/craters draw in the overlay pass, i.e. OVER sprites
(the prototype drew them under buildings); particle velocities are eyeballed
around the prototype's presets (life/count/colours are exact); overlay diamond
BORDERS are opaque lines (`OverlayLines` carries no alpha — fills are exact).

## Verify
Live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game
over screen; cold `py game/main.py`: cutscene → menu → rounds → pause/settings →
add name → credits. Purity test in the suite:
`py -m unittest discover -s tools/tests -t .`.
