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

## Dismissing the panel
`BuildingUI.dismiss()` is the ONE staged dismiss ladder, shared by Esc and
right-click: it peels a single sub-overlay per call (construct preview → the
card list; boss popup → base_info) and only closes a bare panel outright,
returning True when it consumed. New sub-overlays belong in that ladder, not in
a second close path. The host turns a right-press into it (`main.py`
`handle_world_right_click` — right-click dismisses from ANYWHERE, panel and HUD
included; a right-DRAG past the 4px threshold pans instead and never dismisses).
Covered by `tools/tests/test_right_click_dismiss.py`.

## Overhead HP bars
`effects.py` draws them in TWO passes, both reading live scene state and both
hiding the bar at full HP (the prototype rule):
- **`submit_hp_bars`** — buildings (`scene.by_tag("building")`, base excluded),
  fixed 28×4.
- **`submit_enemy_hp_bars`** — **every** enemy, boss included (the boss carries
  the `"enemy"` tag via `Enemy.EXTRA_TAGS`, so this is the ONLY place an overhead
  enemy bar is drawn). Width/height are the `HP_BAR_W`/`HP_BAR_H` class attrs on
  the enemy classes (walker/raider 14×2, siege 24×2, boss 48×4 — see
  `game/enemies/CLAUDE.md`), read duck-typed with a fallback.
  **The LIFT is computed, not a constant (ER-1).** Since a sprite's on-screen
  size derives from its tile footprint rather than its sheet
  (`engine/render/CLAUDE.md`), a lift baked from sheet pixels floats: the boss's
  124×96 era-4 sheet now DRAWS ~50px tall, half its old height. `_sprite_top`
  therefore measures the sprite's real drawn top edge — `cy − drawn_h/2`, where
  `cy` (`world_to_screen(wx+.5, wy+.5)`) IS the renderer's centre anchor and
  `drawn_h` comes from `renderer.assets.frame_size(slot)` through the engine's
  own `fit_factor` (imported, never restated — one source of truth for the fit).
  `HP_BAR_PAD` (4px, base class) is only the gap above the head. A 2-tile
  Formation gets a correct bar for free. Bars from enemies
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
  DMG/Radius/Atk-Spd rows from `core_balance["LightningStrike"]`, an UPGRADE
  button (not-enough-love flash) shown from L1 up to below max, behind a gold
  MAX LEVEL line at max. **No love-buyable UNLOCK button any more** (Storm
  Priest wiring): while `lightning_level <= 0` the panel shows NO button at
  all (`_build_base_info` returns early, mirroring the max-level branch) plus
  a "LOCKED — place a Storm Priest" line — placing a `"lightning_source"`-
  tagged building (`game.core.lightning.unlock_from_placement`, called from
  `_do_place`) is the ONLY way to reach L1. Reads via `game.core.lightning`
  (the sanctioned ui→core direction).
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
  - **ESV-3a**: the spark/death-shard/muzzle/slash/gold-highlight/splatter
    emitters + their tunables moved to `engine/vfx/` (pure, injected-RNG
    emitters + a `VfxSystem`) and `data/balancing/vfx.json` (a new balancing
    domain, D-10). `FloaterManager` now takes a required third constructor
    arg, `vfx_balance`, and owns a `VfxSystem` (`self._vfx`) it delegates
    every FX method's body to; every public method name is unchanged.
    `_params_from_balance` in `effects.py` is the ONE place a JSON key name
    meets an `engine.vfx` dataclass field. Craters/beams/lightning/
    boss-announce (10B/10G/10H) stay module-constant HUD chrome — ESV-3b's
    scope, not ported here.
- **Modal dims** are the prototype's real alphas now: levelup 185, boss
  cutscene 210, cheat menu 150, pause 150 (the 9H deferral).

## Skinnable widgets (10L-A)
`widgets.Button`/`submit_panel` take an optional `skin` slot key → one animated
nine-sliced `HudSprite` instead of flat rects, label overlay unchanged,
**unskinned output byte-identical** (pinned by `tools/tests/test_button_skin.py`).

`hover(mx, my, mouse_down)` → `pressed` (the host reads
`pygame.mouse.get_pressed()[0]`; press-origin is not tracked — accepted v1
simplification); state→row map: flash/pressed→`"pressed"`, disabled→`"disabled"`,
hover→`"hover"`, else `"idle"`, missing rows fall back to idle via the manifest.

**One anim clock per screen** (`self._clock` seconds → `widgets.anim_ms()`), no
per-widget phase; skins are assigned by 10L-B's screen JSON (see "UI screen
customization" below). `levelup.py`/`boss_cutscene.py` own no `widgets.Button`
(plain option-box rects), so they accept `mouse_down` on `update()` only for
main.py's uniform threading call. `levelup.py` still carries no clock/anim_ms
(its boxes stay unconditionally raw); `boss_cutscene.py` gained one in B2 —
its `box_a`/`box_b` route through the skinned `submit_panel` (with a real
`anim_ms`) the moment a skin override is present, and stay raw otherwise.

**R2 pixel-perfect clickable surface:** skinned buttons hover AND click only over
drawn pixels (alpha > 0), via a host-injected seam (`widgets.set_skin_hit_test(fn)`).
The seam queries the `("idle", 0)` canonical silhouette — cursor over a hole in the
hover row oscillates. The seam is unset by default; host wires it once at startup
(`game/main.py`: `widgets.set_skin_hit_test(assets.hit_opaque)` right after `AssetStore`
is built, A8 phase). Unset seam or `skin=None` = rect-only. Panels are not click
targets — no hit-test wiring on `submit_panel`.

## UI screen customization (10L-B phase B2; wave-3 population Phase 3)
Every one of the original 12 live screens (main_menu, pause, settings,
credits, add_name, game_over, levelup, hud, building_panel, cheat_menu,
game_log, boss_cutscene) — plus Phase 3's 13th, `overlays` — names its fixed
widgets in an `ids` dict: `{name: (kind,
widget)}`, `kind` one of `button | panel | label | backdrop | bar | field`
(the pinned six-value enum `data/schemas/screen_defaults.schema.json` and
B3's exporter share — never change this shape). A screen's `layout()` (or, for
`building_ui.py`/`cheat_menu.py`, the point in `submit()` that recomputes
geometry every frame) rebuilds `self.ids` from the DEFAULT geometry and then
calls `self.skinning.apply(self.screen_id, self.ids)` **last** — the override
(if any) wins, since it runs after the default is (re)computed. `game/ui/
skinning.py` (`ScreenSkinning`) loads every `data/ui/screens/*.json` ONCE, at
construction; `apply()` is a pure in-memory setattr loop — **no override, no
mutation** (the golden parity pin: a screen with an absent/empty override
file emits the exact HUD-primitive stream it emitted before B2,
`tools/tests/test_ui_skinning.py::test_all_screens_parity`). `screen_
background(screen_id)` / `submit_background(...)` add an OPTIONAL full-view
background layer (slot or flat color) — a no-op today (no shipped screen JSON
sets one).

- **Non-`Button` widgets get a `types.SimpleNamespace` holder** (`rect`,
  `skin`, `font_key`, `text_color`, `label`, `visible` as needed) that
  `submit()` reads from instead of a hardcoded literal — every screen's
  `backdrop` + static `title`/`subtitle` (`main_menu`'s title AND subtitle;
  every other simple screen's single `title`), `hud.py`'s `love_panel`/
  `love_text`/`lvl_label`/`xp_bar`/`xp_text`/`income_text`/`lives_text`/
  `tiles_text`/`phase_label`/`round_label`, `cheat_menu.py`'s `panel`/
  `title`/`round_field`/`jump_label`, `boss_cutscene.py`'s `backdrop`/
  `headline`/`subtitle`/`box_a`/`box_b`, `game_log.py`'s `log`
  (`get_style_holder()` exposes the same object). Existing plain-tuple
  attributes some tests read directly (`CheatMenu.field_rect`,
  `LevelupWindow.rects`, `BuildingUI.panel_rect`) are kept as real,
  independently-readable attributes, synced from/to the shadow holder each
  layout — never renamed.
- **Every ids target MUST carry a stored, readable `.rect`** (B3's exporter
  contract — a widget with no stored rect exports `[0, 0, 0, 0]` and
  degenerately renders at the origin in the editor's screen mode; a review
  fix caught five that computed their position inline at `submit()` time and
  never stored it: `hud.py`'s `phase_label`, `cheat_menu.py`'s `title`/
  `jump_label`, `boss_cutscene.py`'s `headline`/`subtitle`). **The
  convention**: for a plain text label drawn via `submit_text`/
  `submit_centered` (no fill, no box), `rect` is the `(x, y, 0, 0)` anchor
  point the draw call reads its position from — W/H are nominal `0` (there is
  no implied box size); every text-only label id in this file (the HUD
  readouts, the static titles, these five) follows this same shape. The
  anchor is computed and stored in `layout()` (or, where the position derives
  from a SIBLING widget's default geometry computed moments earlier in the
  same `layout()` call — `boss_cutscene`'s `headline`/`subtitle` sit above
  `box_a`'s pre-override default top — the "no cascade" convention above
  applies: a `box_a` rect override does not retarget them, they'd need their
  own override too), never inline at `submit()` time, so (a) a rect override
  actually moves the text on screen and (b) the exporter reads a real
  position. `submit()` then reads `holder.rect[:2]` (or `.rect[0]`/`.rect[1]`
  for `submit_centered`'s two positional args) instead of recomputing.
- **`boss_cutscene.py`'s `box_a`/`box_b` are the one CONDITIONAL-skin case**:
  with no `skin` override they still draw their original two raw
  hover-tinted `HudRect`s (byte-identical to pre-B2); a skin present routes
  that ONE box through the already-live skinned `submit_panel` instead. This
  screen gained an anim clock (`self._clock`) for that path — 10L-A's "no
  clock" note for levelup/boss_cutscene held only until a skinned path
  existed. `levelup.py` still has no clock (its option boxes stay
  unconditionally raw — a dynamic 1-3 count, "skip dynamic content").
- **Dynamic-count content is NOT individually overridable in v1**: `levelup`'s
  option boxes, `building_ui`'s construct cards / the boss-history popup body,
  `credits`' role/name rows. They inherit a screen's `defaults` section via
  **`ScreenSkinning.defaults(screen_id)`** (Phase 3) — `{}` when unset, else
  the screen JSON's `defaults` dict (`button_skin`/`panel_skin`/…), read
  fresh at the point the dynamic content is built/drawn (no caching, no id
  validation — `defaults` values are never id-checked, only `widgets` keys
  are). Consumers today: `building_ui._build_construct` passes
  `defaults.button_skin` into each card `Button(..., skin=…)` at
  construction; `building_ui._submit_boss_popup` passes
  `defaults.panel_skin` into `submit_panel`; `levelup.py`'s option boxes
  mirror `boss_cutscene`'s `box_a`/`box_b` CONDITIONAL-skin pattern off
  `defaults.panel_skin` (see below). Only STABLE, always-present widgets
  (buttons, the panel body, fixed labels) get an id.
- **`levelup.py`'s option boxes gained a conditional skin path (Phase 3)**,
  mirroring `boss_cutscene`: with no screen `defaults.panel_skin` set, every
  box keeps drawing its two raw hover-tinted rects, byte-identical to
  pre-Phase-3 (the golden parity pin — `ScreenSkinning.empty()` always
  resolves `defaults()` to `{}`, so the pin never sees the skinned path);
  `defaults.panel_skin` present routes EVERY box through the skinned
  `submit_panel` instead. This screen gained an anim clock (`self._clock`)
  for that path too — 10L-A's "no clock" note held only until a skinned path
  existed, same as `boss_cutscene`'s B2 history.
- **`ScreenSkinning.empty()`** is the disk-free default every screen/`Shell`
  falls back to when constructed without an explicit `skinning=` (existing
  tests that build a screen bare, e.g. `test_shell.py`, `test_lightning.py`,
  keep working unchanged — behaves exactly like "no override file"). The real
  instance is built ONCE in `main.py` (`ScreenSkinning(data_dir)`), handed to
  `Shell` (which shares it with its five menu screens) and read back
  (`shell.skinning`) to thread into the seven gameplay screens `main.py`
  builds itself in `build_gameplay()` (`Shell` owns no world).
- **Id validation is silent until `data/ui/screen_defaults.json` exists**
  (B3's exporter output) — an override naming an id absent from that file
  raises `ValueError` (catches a renamed/typo'd id) ONLY once the defaults
  file names that screen; its absence (true for the whole of B2) is not an
  error.
- **Every static title/header is an id too** (review fix, not just buttons/
  panels/backdrops): `main_menu`'s `title`/`subtitle`, `pause`'s/`settings`'s/
  `credits`'/`game_over`'s/`add_name`'s `title`. Their copy is NOT game-state,
  so — unlike the HUD readouts below — `label` (the text itself) is a
  legitimate override field for these, same shape as any other widget
  (`rect`/`font_key`/`text_color`/`label`/`visible`).
- **`hud.py`'s ~12 stable readouts all carry ids now**: `love_panel`,
  `love_text`, `lvl_label`, `xp_bar` (kind `bar` — background/fill as ONE
  widget, the schema's `color` key maps to the track color; the fill ratio +
  levelup-pending pulse stay code-owned), `xp_text`, `income_text`,
  `lives_text`, `tiles_text`, `phase_label`, `round_label`, `btn_end_turn`,
  `btn_pause` — plus (wave-3 phase 4) three baked icon slots, `icon_love`,
  `icon_xp`, `icon_lives`: `panel`-kind holders (`rect`/`skin`/`visible`)
  routed through the skinned `submit_panel()` path with a CODE-default skin
  (`ui_icon_love`/`ui_icon_xp`/`ui_icon_lives`) — unlike `love_panel` (whose
  `skin` stays `None` by default), these draw through the `HudSprite` branch
  even with no override, so the baked art is part of the real HUD, not an
  opt-in. Positioned in `_layout_readouts()` beside their readout (love icon
  inside the pill, left of the count; xp icon left of the bar; lives icon
  left of the lives text), each keeping its readout's OLD anchor x while the
  text/bar it displaces moves right by `ICON_SIZE + GAP` (18 + 4px). For every one of these the displayed TEXT is a live game-state
  value (love count, round number, xp fraction, …) and stays code-owned —
  the override surface is `rect`/`font_key`/`text_color`/`visible` only, the
  same principle as `boss_cutscene`'s headline colour staying win/loss-owned.
  `love_text`/`xp_bar`'s pulse colour fall back to the computed value when
  `text_color`/`color` is left unset (`None`) and to the override otherwise —
  the same "`None` means compute" convention `boss_cutscene`'s `box.text_color`
  already used. Because `love_text`/`lvl_label`/etc.'s DEFAULT rects are
  relative to the now-finalized `love_panel`/`end_turn` rects (themselves
  overridable), `hud.py`'s `layout()` handles only `btn_end_turn`/`btn_pause`/
  `love_panel`/`phase_label`; a second pass, `_layout_readouts()` (called from
  `submit()`, after `layout()`), computes and applies the rest — two
  `skinning.apply()` calls per frame, still zero disk I/O either way.
- **Button `color`/`text_color`/`visible` forwarding**: every id'd `Button`'s
  `submit()` call now forwards `color=`/`text_color=` via
  `skinning.button_kwargs(btn)` (`getattr(btn, "color"/"text_color", None)` —
  `None` unless an override actually set one, in which case the button's own
  hover/flash/disabled colour logic is overridden). **Precedence**: a `skin`
  present ignores `color` entirely (the long-standing `Button.submit`
  contract — the sprite has nothing to fill), but `text_color` still applies
  to the label overlay either way. `visible=False` (via `skinning.is_visible`)
  skips BOTH the button's `submit()` AND its hover/hit: every screen's
  hover/update loop forces `btn.hovered = btn.hovered and is_visible(btn)`
  (never skips `hover()` outright — a stale `True` from before an override
  toggled visibility off cannot linger) and every click handler gates with
  `is_visible(btn) and btn.hit(mx, my)`. **Scope**: this applies to every
  Button that has an id — every button in every screen, INCLUDING (Phase 3
  closed this gap) `building_ui.py`'s three previously-un-id'd STABLE
  buttons: `rename_dice_btn` (the upgrade panel's `⚄` rename row, `self.
  _dice_up`), `lightning_btn` (the ⚡ UPGRADE LIGHTNING button) and
  `boss_close_btn` (the boss-history popup's CLOSE). `rename_dice_btn`/
  `boss_close_btn` are created once in `__init__` and join the same
  mode-independent `self.ids` dict as `panel`/`close_btn`/`action_btn`/
  `boss_btn`. `lightning_btn` is the one exception: it is REBUILT (a fresh
  `Button`) every time `_build_base_info` runs (level change, cost change),
  so it cannot live in a static ids dict — `_build_base_info` calls
  `self.skinning.apply(self.screen_id, {"lightning_btn": (...)})` standalone
  the moment the new instance exists (id validation runs once per screen on
  whichever `apply()` call happens first, using the override's OWN declared
  widget names — never the local `ids` argument — so a partial standalone
  call still catches every bad id in the file, not just this one).
  `tools/export_ui_layouts.py`'s `_build_building_panel` forces
  `_build_base_info` once with a minimal stand-in "session" so
  `screen_defaults.json` records `lightning_btn`'s default rect too (skip
  this and a real override naming it raises `ValueError` at load). The
  construct cards remain the one un-id'd case (genuinely dynamic-count —
  see `defaults.button_skin` above).
- **Carry-over fix: panel-kind holders now read their own `visible`
  override** (Phase 3) — `is_visible` gating was button-scoped through B2;
  `add_name.panel`, `cheat_menu.panel`, `building_panel.panel`,
  `building_panel.preview_panel` and `boss_cutscene.box_a`/`box_b` now wrap
  their `submit_panel`/box-draw call in `if is_visible(...)` (and
  `boss_cutscene.hit`/`update` gate the same way, so a hidden box is never
  hovered or clickable either). `hud.love_panel` already checked its own
  `.visible` attribute directly (equivalent to `is_visible`) since B2 and
  needed no change.
- **A 13th screen: `overlays`** (Phase 3) — `game/ui/overlays.py`
  (`MapOverlays`, the RANGE/HEATMAP toggle pills) gained its own
  `data/ui/screens/overlays.json` + `ids` (`btn_range`, `btn_heatmap`) the
  sanctioned way this section always supported: "drop in a file + ids", not
  limited to the original 12. Since one `MapOverlays` is built per run and
  never re-laid-out (`view_w`/`view_h` fixed for its whole lifetime),
  `apply()` runs once in `__init__` — the `BuildingUI` mode-independent-ids
  pattern, not a per-frame `layout()`. `main.py` threads `shell.skinning`
  into it in `build_gameplay()` exactly like the other seven gameplay
  screens. `tools/export_ui_layouts.py` gained a matching `_build_overlays`
  builder and an `"overlays"` entry in `SCREEN_IDS`.

## Layout heights: `layout_h`, never a live font measurement
Any layout computation whose result lands in a stored holder `.rect`/anchor,
an id'd widget, the `test_ui_skinning.py` golden parity stream, or
`data/ui/screen_defaults.json` (the exporter) MUST read
`engine.render.fonts.layout_h(font_key)` — a pinned constant table — never
`widgets.text_h`/`TextMetrics.size` directly. Windows and Linux (CI)
measure `pygame.font.SysFont(...).size()` text heights ±1px apart, so a live
measurement baked into a stored rect makes the committed artifacts (captured
on Windows) diverge from what Linux regenerates. `text_h`/`text_size` remain
correct for genuinely draw-time-only metrics that never reach a stored rect
or a captured stream (e.g. `hud.py`'s hover-only income tooltip / lightning
readout, `building_ui.py`'s terrain badge/tooltip — none of those are id'd or
exercised by the golden capture/exporter today; re-check this if either ever
starts pinning them). Pinned by `tools/tests/test_layout_h_invariant.py`
(monkeypatches the measurement +1px and asserts both artifacts are
unaffected).

## Known divergences (deliberate)
The XP bar/floaters still drop the prototype's mascot face (never ported); the
prototype's `xp_icon` gap itself is closed — wave-3 phase 4 wired a baked
`ui_icon_xp` slot next to the bar (`hud.py`'s `icon_xp` id, alongside
`icon_love`/`icon_lives`). Lightning FX are NOT force-cleared at `_begin_round_end` (the prototype
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

**ESV-3a note**: none of the above changed — the port from module constants +
inline `random.uniform(...)` to `data/balancing/vfx.json` + `engine/vfx/`'s
injected-RNG emitters is a landing-condition no-op (byte-identical output);
these approximations are pre-existing and untouched by it.

## Verify
Live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game
over screen; cold `py game/main.py`: cutscene → menu → rounds → pause/settings →
add name → credits. Purity test in the suite:
`py -m unittest discover -s tools/tests -t .`.
