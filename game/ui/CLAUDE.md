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

## The logical surface is 640x360 (UR-2)

Every pixel constant in `game/ui` is authored against a **640x360 logical
surface** — `data/display.json`'s `window_w`/`window_h`, the ONE place the
resolution is stated. SDL `SCALED` upscales it to the monitor and remaps mouse
coordinates back down, so hit-testing and every widget rect work unchanged;
nothing in `game/ui` should ever restate the resolution as a literal.

Phase UR-2 halved every 1280-scale constant here: positions, container
dimensions (panel/button/popup/modal), and the paddings/gaps internal to a
container that itself halved. What deliberately did **not** halve:

- **`data/ui/fonts.json`'s seven presets.** They were always the prototype's
  640-scale values and became correct the moment the surface flipped —
  halving them is precisely the double-scale bug UR-2 existed to delete. Zero
  edits to that file or `engine/render/fonts.py`. If a screen's text now
  overflows a halved container, the fix is the container, not the preset.
- **Colours, alphas, `border_radius`, `width=` line widths, `max_lines`
  counts, and timings** — all scale-free.
- **Sub-4px nudges** (`+3`, `+2`, 1px hairlines) — halving them rounds to
  invisible.

`hud.py`'s `_ICON_SIZE`/`_ICON_GAP` carry an explicit **UR-5 review** note at
the change site: they were halved against the plan's own worked example,
because they are sized against the HUD rows they sit inside. UR-5 **kept** them
at 9/2 — measured, an 18px icon does not fit the 17px love pill.

### A text ROW STEP is font-scale — never halve it (UR-5)

The corollary of "fonts.json did not halve", and the single defect class UR-5
found most of. **The vertical step between two stacked text rows, and the
height of any box sized to hold text, are 640-scale already** — they are
functions of `layout_h(font_key)`, not of the surface. UR-2 halved several of
them with the containers around them, and the rows landed on top of each other:
`hud.py`'s income/lives/tiles column stepped 8px against a 13px `md` line,
`game_log.py`'s `_LINE_STEP` 6px against an 11px `sm` line, and `levelup.py`'s
option box ended up smaller than its own contents (and narrow enough to
silently truncate 5 of the 41 shipped explanations at `max_lines=4`).

So, when you write one: **derive it from `layout_h`, do not spell it as a
literal** — `hud._readout_step()` / `_readout_bottom()` are the pattern, and
anything anchored *below* a text stack (the speed-button row) derives from that
stack's bottom rather than restating a y. Call it, never a module constant: a
constant evaluated at import freezes the pre-`configure_fonts` fallback
metrics. The same rule governs a button's height — `Button.submit` centres its
label on `layout_h(font_key)`, so a button shorter than that overhangs top and
bottom.

**The follow-up sweep** caught the sites UR-5 itself missed:
`tutorial_message.py`'s wrapped message lines (11 vs `md` 13 — the shipped
`lives_intro` modal every new player sees) and seven steps in
`building_ui.py`, which now derives all of them through one local
**`_row_step(font_key, leading=1)`** (the `hud._readout_step()` shape). Two
things that sweep established and the next one should keep:
- **`leading=0` is a real answer for a height-constrained stack.** The
  `ConstructPreview` stat list uses it because a leading pixel per row would
  push its 5-row worst case onto the CONFIRM/CANCEL row of a 170×150 modal.
  Each such call site states the fit arithmetic inline; every other step takes
  the default 1px.
- **A step and the hit test that divides by it are ONE number.** The boss
  history popup's row step is read by `_submit_boss_popup` *and* by `hover()`'s
  `(my - top) // step` row probe — they call the same `_row_step("md")`.
- The boss popup **grew 130 → 158px** so the corrected 14/12 steps keep the six
  choice rows the old layout held and stop the 2-line hover tooltip overhanging
  CLOSE. That moved `boss_close_btn`, so `data/ui/screen_defaults.json` was
  regenerated (`py tools/export_ui_layouts.py`) — one rect, `building_panel`
  only. `test_ui_skinning.py`'s `building_panel` baseline is `[]` (the harness
  never selects a building), so **the pin does not protect this module** —
  arithmetic in the call-site comments is the check.

### Click-target floor + static-label fit (UR-5)

`tools/tests/test_ui_min_targets.py` walks every screen's `ids` (captured from
`tools/export_ui_layouts.py`'s own builders, so a new screen is covered for
free) and asserts three things about every `kind == "button"`: its smaller
dimension is **>= 12 logical px**, its static label fits in `w - 4`, and the
button is at least `layout_h(font_key)` tall. Filter on the `kind` from the ids
PAIR, never on `type(widget)` — panels/labels/bars are not click targets.

Controls between 12 and 16px are **printed as a non-blocking lint, never
asserted.** `SCALED` preserves physical screen area (12 logical px == 24
physical px at the 2x reference monitor), so a small control does not actually
shrink under the pointer; the real risk is sub-pixel mouse remapping at
non-integer monitor scales, which is `planning/UiResolutionPLAN.md` §5's
acknowledged out-of-scope caveat. **Do not mass-resize controls to silence the
lint** — it is a playtest worklist.

**Known deferred item — the world renders too close.** The surface halved but
`data/geometry.json`'s `zoom_levels` and the 64x32 iso tile pitch did not, so
less of the board is visible at a given zoom step. That is deliberate and out
of `game/ui`'s hands (`planning/UiResolutionPLAN.md` §3, a separate future
plan covering `zoom_levels`, the camera clamp and `visible_tile_window`
culling). **Never compensate for it from a UI file.**

## In-round UI (9G)
`game/ui/{widgets,hud,building_ui,effects,game_over}.py`: HUD (love panel, round,
base HP, End Turn, phase banner), unlock/construct/upgrade/base-info panel modes,
ConstructPreview (name entry, confirm/cancel per `ui.Timing`), income/upkeep
floaters, not-enough-love flash, building HP bars; input routing + click-consume
priority in `game/main.py`. Every menu screen mirrors the `game_over.py`
construct→layout→update→hit→submit template + `widgets.Button`.

## HUD submission order: panel -> button -> text
`engine/render/CLAUDE.md` "HUD pass": the HUD layer has **no depth sort** —
`submit_hud`/`submit_panel`/`submit_text` draw in the order they're called,
first-submitted = furthest back. The house discipline within any one
`draw()`/`submit()` method is **panel/background submissions first, then
buttons, then standalone text** (back to front), so a later decorative rect
never paints over an already-drawn button and text always reads on top.
Deliberate exceptions stay commented at their call site — e.g. `building_ui.py`
`BuildingUI.submit()` draws the hovered terrain tooltip LAST, after every mode
body, on purpose (it must sit on top of everything, panel included); an
active-toggle highlight ring (`overlays.py MapOverlays.submit_buttons`) is
drawn after its own button for the same reason. A third: `hud.py`'s income
breakdown tooltip — `Hud.submit()` only *decides* whether it is showing at the
income line (a local `tooltip` variable) and calls
`_submit_income_tooltip` as the LAST statement of the method, after
`_submit_lightning`, so it stays in front of the `readout_panel` it overlaps.
Those are "always on top" overlays, not this rule's target. The menu screens that mirror the
`game_over.py` template (backdrop → title/body text → action button) are a
**separate, established, golden-pinned convention**
(`tools/tests/test_ui_skinning.py::test_all_screens_parity`) predating this
rule and are not itself a target for reordering — the button/text there never
overlap, so there is nothing to occlude.
Two real violations were fixed here: `ConstructPreview.submit()`
(`building_ui.py`) had text interspersed between panel/button calls instead
of trailing them; `Hud.submit()`'s round-cluster separator drew AFTER the End
Turn button. Regression-pinned by `tools/tests/test_hud_panel.py`
(`TestHudButtonZOrder`, `TestConstructPreviewZOrder`).

## Dismissing the panel
`BuildingUI.dismiss()` is the ONE staged dismiss ladder, shared by Esc and
right-click: it peels a single sub-overlay per call (construct preview → the
card list; boss popup → base_info) and only closes a bare panel outright,
returning True when it consumed. New sub-overlays belong in that ladder, not in
a second close path. The host turns a right-press into it (`main.py`
`handle_world_right_click` — right-click dismisses from ANYWHERE, panel and HUD
included; a right-DRAG past the 4px threshold pans instead and never dismisses).
Covered by `tools/tests/test_right_click_dismiss.py`.
**One conditional exception since the drag-selection toggle** — see the section
below: while `gp["drag_select_enabled"]` is on AND no construct preview is
open, a right-click on a tile that is CURRENTLY in the multi-selection peels
that ONE tile out instead of dismissing. Every other right-click (toggle off,
tile not selected, preview open, anywhere off a selected tile) still reaches
this ladder unchanged.

## Drag-selection toggle (`btn_drag_select`)
A HUD toggle that turns one left-press-drag-release into a rectangle (box)
selection producing the SAME end state Shift+Click multi-select builds one
click at a time — same `_SEL_CATEGORY` filter, same batch UI in
`building_ui.py` (unlock chunks / cost×count construct / summed in-tier
upgrade), which needed NO change for this.
- **The button lives in `hud.py` and mirrors the `speed_1x`/`_1_5x`/`_2x` row
  exactly** (same `widgets.Button`, same construct→layout→ids→update→hit→submit
  shape, same gold-rim-when-active treatment): `self.drag_select_btn`,
  90×28, font `sm`, laid out at `(12, sy + sh + gap)` — its own row directly
  under the speed row — and id'd `btn_drag_select`. Its enable rule is
  `pause`'s (`GAMEPLAY and not self._panel_open`), with **no unlock/round
  gate**, so it is clickable from round 0.
- **`Hud.hit()` stays a PURE READ for it** (returns the string
  `"drag_select"`; the flip happens in `main.py`'s `handle_world_click`, like
  `("speed", idx)`). This is load-bearing, not style: `main.py` calls
  `Hud.hit()` **twice per click** — once from the MOUSEBUTTONDOWN `over_ui`
  pan-arming probe, once for real from `handle_world_click` on MOUSEBUTTONUP —
  so `MapOverlays.hit()`'s self-toggling pattern would double-fire and cancel
  itself here. Do not copy it into `Hud`.
- **The STATE is the host's, not the widget's**: `gp["drag_select_enabled"]`
  (`game/main.py`), threaded into `Hud.submit(..., drag_select_enabled=False)`
  once per frame purely to draw the active rim. It lives in `gp` because the
  event loop reads it when it decides drag-select vs. camera pan. Host wiring
  (arming, the live rectangle, `finish_drag_select`, the right-click deselect)
  → `game/CLAUDE.md`'s matching section.
- **Golden pin**: `test_ui_skinning.py`'s `hud` baseline gained three appended
  primitives and `data/ui/screen_defaults.json` was regenerated (`py
  tools/export_ui_layouts.py`) — the sanctioned "a screen's default geometry
  changed on purpose" path. Nothing already in either artifact moved.

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

**ESV-1 (SUPERSEDED by fix-anchor-origin-parity, below) originally added an
optional manifest `hp_bar` anchor as a composed SCREEN OFFSET** on top of
`_sprite_top`'s baseline (enemies) / the flat `cy - tile_h*zoom` baseline
(buildings) via `game/anchors.py`'s `screen_offset`/`world_offset`, later
taught to compose the entry's `offset_x`/`offset_y` draw nudge too
(**fix-anchor-offset-and-bullet-sprites Fix 1**, reversing ESV-2 §1.4 — see
`docs/briefs/fix-anchor-offset-and-bullet-sprites.md`). Both functions and
this whole "offset on top of a baseline" model are DELETED.

**fix-anchor-origin-parity (current)**: an authored `hp_bar` anchor now
**replaces the baseline outright** rather than nudging it — "anchor wins
outright" (the designer's decision, `docs/briefs/fix-anchor-origin-
parity.md`). `submit_hp_bars`/`submit_enemy_hp_bars` call `game.anchors.
anchor_world_point(assets, cs, obj, "hp_bar")`; when it returns a point, the
bar's screen anchor is `cs.world_to_screen(point)`, full stop — `_sprite_top`
is not consulted at all. `None` (no anchor authored, or the store/cs/
animator is absent) falls back to exactly the pre-ESV-1 baseline expression,
byte-identical. The measured root cause this replaced: the old baseline
(`cs.world_to_screen(obj.transform.world_pos)` for VFX, `_sprite_top` for
enemy bars) was NOT where `engine/render`'s `Renderer.flush` actually draws
the sprite's centre, so an offset composed on top of it still missed by the
same gap (`tile_h/2*zoom`, 16px at zoom 1, plus `block_center_offset` for a
multi-tile footprint) — see `game/anchors.py`'s module docstring and
`engine/render/CLAUDE.md`'s Anchor convention section for the one shared
formula (`engine.render.sprite_anchor_screen`) every anchor consumer now
resolves through.

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
  `game.core.boss_bonuses.choice_desc`. Since the boss-upgrade rework those
  descs quote LIVE `BossBonuses` magnitudes, so the constructor takes a third
  positional `core_balance` (passed from `build_gameplay()`, where it is
  already in scope). `hit` returns `"A"`/`"B"`/None — NO
  dismiss path; it sits above `session.frozen` in `main.py`'s click ladder and
  the frozen key-gate swallows keys. Opened by the host on the BOSS_CUTSCENE
  phase edge from `state.pending_boss_cutscene` (the LEVELUP pattern).
- **`effects.py`** grew three fenced 10G members: `spawn_boss_events(state)`
  drains the `boss_events` announce markers (gated by
  `ui.FX.boss_announce.enabled`); `submit_announce` draws the centred two-line
  "SOMETHING BIG / IS APPROACHING!" banner over the
  `boss_announce.{fade_in,hold,fade_out}` timings (a real text-alpha fade
  since 10J; **ESV-3b**: the colour + max alpha are now
  `data/balancing/vfx.json procedural.announce`, read off
  `FloaterManager._vfx_params.announce` — the two copy strings and the
  timings stay put, screen-skinning/`ui.json` territory respectively);
  `submit_boss_bars(renderer, cs, scene, phase, view_w, view_h)`
  finds the live boss via `scene.by_tag("boss")` and draws the bottom-centre
  200×12 HUD bar ("BOSS" + `hp/max`, ENEMY phase only). Its **overhead** bar is
  NOT drawn here — see the enemy HP bars below, which own every overhead bar in
  the game (the boss is tagged `"enemy"` too, so it comes along for free and can
  never double up).
- **`hud.py`**: BOSS_CUTSCENE phase label/color entries, and — in
  `income_sources` (which `income_breakdown` sums) — ONE
  `love_bonus_income(st, session.tilemap, session.core_balance)` call for the
  "Story" row, the exact same whole-board slot-3 sum payday pays, so the HUD
  net keeps matching payday. (The boss-upgrade rework replaced 10G's fenced
  block: there are no per-recipient boss deltas any more.)
- **`building_ui.py`** base_info mode: a "BOSS CHOICES" button (10H's lightning
  section sits ABOVE it) opening a centred history popup — one row per
  `state.boss_choices` entry (`"Boss {n}: {Outcome} {option}"`), the hovered
  row's bonus desc as a tooltip line, "None yet" when empty, Close; the popup
  consumes clicks inside itself.
- **`game/main.py`** owns the screen shake: a transient `cs.pan(ox, oy)` /
  `cs.pan(-ox, -oy)` wrap around the world render branch (NO clamp between),
  parameters from `Boss.shake.{interval,strength}`, active only while ENEMY
  phase + a live `"boss"` in the scene.

## Enemy intro dialogue sprite/animation controls (feature-enemy-intro-dialogue)
`game/ui/enemy_intro.py`'s `EnemyIntroWindow` (session/phase wiring →
`game/core/CLAUDE.md`'s matching section) plays its sprite as a LOOPING
spritesheet animation, not a static frame, with per-entry crop/offset/flip/
tint/speed/hidden-frame controls — every field on `data/balancing/core.json`'s
`EnemyIntro.entries[i]` beyond `sprite_w`/`sprite_h`.
- **One continuous clock, not the world's `SpriteAnimator` clock.** The
  window owns `self._clock` (float seconds, reset to `0.0` in `open()`,
  incremented by `dt` in `update()` for as long as `visible`) — the
  `boss_cutscene.py` pattern for a UI screen's own independent animation
  time. `submit()` converts it once via `widgets.anim_ms(self._clock *
  entry["anim_speed"])` into the `HudSprite`'s `anim_time_ms`; the animation
  loops for the ENTIRE open+hold+close lifetime (a deliberate simplification
  — no per-entry "loop vs. play-once-then-freeze" mode).
- **`sprite_slot` may be ANY imported sprite**, any category — `game/core/
  CLAUDE.md`'s section covers the generated enum. `animation` names one of
  that slot's manifest rows; a mismatch (e.g. an `enemies`-vocabulary name on
  a `ui` slot) degrades to idle rather than erroring, the manifest's own
  tolerance.
- **`crop_x/y/w/h`**: a source sub-rect (frame-px) drawn instead of the whole
  frame, still stretched to `sprite_w`×`sprite_h` — `crop_w == 0 and crop_h
  == 0` means no crop (the `fit_tiles == 0` sentinel convention). Composed
  into a `HudSprite.crop` tuple; the actual crop-then-scale work is
  `engine/render/backend.py`'s `_cropped` (`engine/render/CLAUDE.md`).
- **`sprite_offset_x/y`** nudge the sprite's dest box off its default
  horizontally-centered position — added directly into the `(cx - sw//2,
  cursor)` dest computation; they do NOT move the panel's text cursor, only
  the sprite's own draw box.
- **`sprite_flip_h`** wires straight to `HudSprite.flip` (a pre-existing
  field — no engine work needed).
- **`background_tint` `[r, g, b, a]`** draws a `HudRect` behind the sprite,
  sized to match its box, submitted immediately before the sprite's
  `HudSprite` (the house "panel/background first" HUD-submission-order rule,
  above). Its alpha COMPOSES with the window's own open/close fade
  (`round(bg_a * window_alpha / 255)`) rather than fighting it. `a == 0`
  (the shipped default) is invisible, so an un-tinted entry looks identical
  to before this feature.
- **`hidden_frames`**: extra frame-column indices to skip for THIS entry,
  passed as `HudSprite.hidden_frames` → `Manifest.current_frame`'s
  `extra_hidden` (`engine/assets/CLAUDE.md`) — UNIONS with, never overrides,
  whatever the manifest row's own `hidden` list already drops.

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
- **Debug-log activation (debug-mode-telemetry)**: `main_menu.py` grew a
  `PLAY DEBUG` row (`play_debug` -> the new `"new_game_debug"` intent, which
  the host executes by building a `DebugRecorder` before `build_gameplay()`)
  and a small `SET` gear beside it (`play_debug_settings`, id
  `btn_play_debug_settings`) opening **`game/ui/debug_settings.py`** — a
  `settings.py`-shaped modal (`< value >` level cycler + four ON/OFF artifact
  toggles + BACK) over a session-only `DebugSettings` dataclass, the
  `SessionSettings` precedent. `cheat_menu.py` grew a matching `Debug Log`
  row (`toggle_debug`, id `btn_toggle_debug`) that arms/disarms the recorder
  mid-run; the panel is 30px taller for it.
  - **The gear's modal is a MAIN_MENU OVERLAY, not a sixth menu state.** The
    `Shell` holds `debug_settings_open`; `_main_menu_click` lets the modal
    consume every click while it is up (so a click cannot fall through and
    start a run), `_active_screen` returns it instead of the menu, and Esc
    closes it. A new `GameState` member would have meant editing
    `game/core/phases.py` for one screen reachable from exactly one place.
  - **`debug_settings` is CODE-ONLY**: no `data/ui/screens/debug_settings.json`
    and no `data/ui/screen_defaults.json` entry, and it is not in
    `tools/export_ui_layouts.py`'s `SCREEN_IDS`. An absent override means
    "code defaults" (`ScreenSkinning.apply` no-ops and id validation stays
    silent until the defaults file names a screen), so it still carries a
    proper `ids` dict and submission order and is a drop-in the day someone
    exports it. The two screens that DID change (`main_menu`, `cheat_menu`)
    required regenerating `data/ui/screen_defaults.json` and their two
    `test_ui_skinning.py` golden entries — the sanctioned "a screen's default
    geometry changed on purpose" path, never relaxing the pin.
- **Player identity + high scores (player-identity)** — two more screens, one
  more menu state, one more scroll seam:
  - **Two new CODE-ONLY screens join `debug_settings` in that category**:
    `game/ui/player_intro.py` (`PlayerIntroScreen`, `add_name.py`'s template
    verbatim — name field + four RADIO options whose selection is just the
    selected button's `text_color` set to gold and every other's to `None`,
    the "`None` means compute" convention, so it invents no draw path) and
    `game/ui/highscores.py` (`HighscoresScreen`, the `credits.py` shape).
    Neither has a `data/ui/screens/*.json`, a `screen_defaults.json` entry, or
    a `tools/export_ui_layouts.py SCREEN_IDS` row — an absent override means
    "code defaults", so both still carry a full `ids` dict and the panel →
    button → text submission order and are drop-ins the day someone exports
    them. **Neither does disk I/O**: the host loads/appends
    `scores/highscores.json` through `game.core.highscores` and hands the
    document down via `Shell.set_highscores` → `set_doc`; both modules import
    that package only for its PURE helpers (`ranked`, `SKILLS`).
  - **`main_menu`'s id/action decoupling — the pattern for any future
    availability matrix.** `self.buttons` pairs each `Button` with a STABLE
    `slot_key` (what `_SLOT_IDS` looks its widget id up by — an id is the
    on-disk contract in `data/ui/screens/main_menu.json` and must NEVER swap),
    while `self.actions` (recomputed in `layout()` from `core.json`'s `Debug`
    flags) maps that slot to the action `hit()` returns. Regular-off therefore
    keeps the `btn_new_game` id and the START NEW GAME position but emits
    `"play_debug"` from it; both-off falls back to regular-only with one
    latched warning. `visible` is set on EVERY row every `layout()` (never only
    in the hiding branch, so a stale `False` cannot linger) and the stack
    cursor advances only for a visible row, so a hidden row leaves no gap.
  - **`GameState.HIGHSCORES` is the first menu state added since 9H.** The two
    modals that came before it (`debug_settings_open`, `player_intro_open`)
    stayed plain MAIN_MENU flags because each is an overlay reachable from
    exactly one place; a full SCREEN off the menu, with its own back
    navigation and its own place in `in_menu`/`_MENU_STATES`, earns the enum
    member instead. That is the line: overlay ⇒ flag, full screen ⇒ state.
  - **`Shell.handle_scroll(dy)` is a duck-typed forwarder, not a generic
    ScrollView.** It calls the active screen's `scroll` attribute when it is
    callable (only the high-score table has one), so every other screen and
    state is a silent no-op, and returns `None` — scrolling is never a host
    intent. One screen does not justify a widget abstraction; the table's own
    "scroll" is a clamped integer row offset (`scroll_offset`) with the header
    pinned above the viewport. **Sign**: positive `dy` moves DOWN the list,
    and pygame's `MOUSEWHEEL.y` is positive scrolling UP, so `main.py`'s menu
    wheel arm negates it.
  - **`data/ui/screen_defaults.json` + `test_ui_skinning.py`'s `main_menu`
    golden entry were REGENERATED on purpose** (the HIGHSCORES row shifts
    every row below it down one 52+14px slot) — the sanctioned "a screen's
    default geometry changed on purpose" path, never relaxing the pin. Only
    `main_menu` moved; every other screen's entry is byte-identical, which is
    what says the change was contained.
- **Deferred**: the settings audio slider is inert (no audio system beyond
  music). (The pause dim landed with 10J's HUD alpha.)

## Defence FX (10B)
`effects.py` `FloaterManager` grew `submit_beams` + `submit_craters`, drawn from
live scene state (like `submit_hp_bars`): a per-tier colored `HudLines` from each
firing Sun Scorcher to the enemy its `BeamAttacker._target` names, and a fading
world-space **polygon ring** for each `"crater"` GameObject a mortar shell left
(the `Crater` objects age + self-despawn in the scene; the FX just draws them).
This is the sanctioned `game/ui → game/buildings.components` read (building_ui
already imports it). 10J made the crater an alpha-filled shape; the beam stays a
plain line (an alpha GLOW under it remains unported — `HudLines` carries no
alpha; accepted). **ESV-3b**: the beam colour ramp/width/origin-lift and the
crater colour/alpha are now `data/balancing/vfx.json` (`procedural.beam`/
`.crater`), read off `FloaterManager._vfx_params`; the crater's fade LIFE is
still on its own `CraterFade` component, now fed from the same domain.
**feature-storm-acolyte-multi-build**: the crater's shape is now a
`cp.segments`-gon (`procedural.crater.segments`, `CraterParams.segments`), not
the old 4-point diamond — drawn through the same `_polygon_ring(cx, cy, r,
segments)` module helper the lightning blast marker uses, generalised from
the lightning impact-flash's own inline 8-point octagon. The mortar's splash
is Euclidean in TILE space, so this ring is the EXACT damage-area shape (a
real fidelity fix, not just cosmetics) — unlike the lightning marker, whose
damage circle is Euclidean in the PROJECTED PIXEL plane, so its ring still
slightly under-covers the true circle vertically (far less than the diamond
did). Neither change touches the damage math (visual only, D4).

## Lightning + cheat menu UI (10H; Storm Priest rework; feature-storm-acolyte-multi-build)
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
- **`building_ui.py` base_info no longer shows a lightning section or button
  at all** (Storm Priest rework — the whole "⚡ LIGHTNING STRIKE" block plus
  `lightning_btn`/`_build_base_info` were removed). Selecting a Storm
  Priest's OWN building panel is the leveling UI now: its existing generic
  tier-upgrade button pays the tier's own advance cost and
  `game.core.lightning.sync_level_from_tier` raises `lightning_level` to
  match. Placing a `"lightning_source"`-tagged building
  (`game.core.lightning.unlock_from_placement`, called from `_do_place`) is
  still the ONLY way to reach L1. Reads via `game.core.lightning` (the
  sanctioned ui→core direction).
  - **Run-singleton grey-out REMOVED (feature-storm-acolyte-multi-build)**:
    `building_ui.py`'s construct panel no longer greys out or disables the
    Storm Priest card — any number may be placed. Its price ESCALATES
    instead: `game/buildings/CLAUDE.md`'s Storm Priest section owns the
    counting seam (`registry.count_tag`/`LIGHTNING_SOURCE_TAG`,
    `build_cost(..., repeat_count=)`); this module's `_build_construct`
    (the card label), `hover` (the hover price) and
    `ConstructPreview.total_cost` (a shift-multi-select batch's up-front
    figure — the ESCALATING sequence `n, n+1, n+2, …`, not a flat
    `cost * count`) all price off that SAME count via the shared
    `_batch_cost` helper, so the label, the hover figure and what
    `place_building` actually charges can never disagree.
- **`hud.py _submit_lightning`** — ENEMY-phase-only bottom-left readout
  (`⚡ CLICK TO STRIKE` / countdown) + a 22×3 cursor-attached progress bar
  (`Hud.update` now stores `_mx/_my`). **feature-storm-acolyte-multi-build**:
  takes a new `scene` argument (threaded through `Hud.submit`, wired from
  `main.py`'s `world.scene`) and walks `scene.by_tag("lightning_source")` for
  the SOONEST-ready alive caster (the smallest `LightningCaster.cooldown`) —
  several acolytes may exist, each on its own clock, and this readout always
  tracks whichever will fire next. No placed caster at all → nothing drawn,
  even if `lightning_level` is latched > 0 from one that died and hasn't
  revived yet.
- **`effects.py submit_lightning`** — draws each `"lightning_fx"` scene object
  (the `submit_craters` pattern): a jagged screen-space `HudLines` bolt from
  y=0 to the impact (±6 px jitter per frame, white→yellow over 0.5 s) + a
  fading yellow world-space **polygon ring** (feature-storm-acolyte-multi-
  build's shared `_polygon_ring(cx, cy, r, segments)` helper — see "Round
  ground markers" below) sized to the real blast radius. 10J added the alpha
  fill, an expanding impact-flash polygon, and the alpha marker fade.
  **ESV-3b**: every colour/width/segment/jitter/flash/marker-alpha number
  here is now `data/balancing/vfx.json procedural.lightning`, read off
  `FloaterManager._vfx_params.lightning`; the bolt's per-frame jitter now
  draws through `self._rng` (shared with `self._vfx`'s injected `random`)
  instead of the bare module-level call. The two fade LIFEs
  (`bolt_life`/`marker_life`) are on `LightningFXFade`, fed from the same
  domain via `lightning.strike`'s new required `vfx` argument. Every firing
  caster in a multi-acolyte click spawns its OWN `"lightning_fx"` object, so
  several rings of differing radius can land at the same point in one frame —
  each is drawn independently, no batching. Since `strike()` fires per
  caster now, `LightningCaster.trigger()` (the "attack"/"idle" sprite flash)
  runs once per FIRING caster, not once per click — a WORLD sprite, not part
  of this overlay FX, driven by its own `SpriteAnimator`, submitted the
  normal `scene.render_items()` way.
- **`effects.py submit_lightning_charge_bars` (feature-storm-acolyte-multi-
  build)** — the `submit_hp_bars` pattern (fixed screen-pixel size, anchored
  through `cs.world_to_screen`): one bar per alive `lightning_source` whose
  caster is STILL CHARGING, hidden once ready (the HP-bar-at-full-HP
  convention). Fill fraction `1 - cooldown/tier_cooldown`; colour lerps from
  a dim slate to the ready-yellow `(255, 240, 80)` as it fills. Bar size +
  ramp endpoints are code constants beside `HP_BAR_W`/`HP_BAR_H`
  (`_CHARGE_BAR_*`, `game/ui/effects.py`). Wired in `main.py` beside
  `submit_lightning`, world-overlay pass (before the panel), not the later
  HP-bar section.

## Move Building (Building Movement)
The upgrade panel's fifth mode + a second preview modal. Rules live in
`game/buildings/movement.py` (`game/buildings/CLAUDE.md`); this module is the
picker and the confirmation.
- **`BuildingUI.move_btn`** — a mode-independent `Button` built once in
  `__init__` (the `boss_btn`/`_dice_up` pattern) with the id `move_btn`, and
  positioned by `_build_move_btn` directly under `action_btn` in upgrade mode.
  **Visible only on a SINGLE selection** — a move is not batchable (unlike
  UPGRADE/ADVANCE, which do batch — see the fix/batch-tier-advance note
  below). A Wall Builder gets the button DISABLED + relabelled
  `CANNOT BE MOVED` with an `_upgrade_hint`, the same mechanism
  `RESEARCH REQUIRED`/`NEXT TIER LOCKED` use; `start_move` is the real
  enforcement.
- **`mode == "move_select"`** — a fifth panel mode. `_build_move_select` fills
  `_highlight_tiles` with every `buildable_tiles()` tile that is not already
  `tilemap.is_moving`, in the new `widgets.C_MOVE_HIGHLIGHT` (cyan; a plain
  code constant NOT in `_PALETTE_KEYS`, the `C_TUTORIAL_HIGHLIGHT`
  precedent). The panel body becomes a short instruction card
  (`_submit_move_select`). **The panel only ever handles panel-space clicks**,
  so `_move_select_click` just cancels back to upgrade; the destination TILE
  pick is `game/main.py`'s (see `game/CLAUDE.md`). `dismiss()` gained one more
  rung — move_select peels back to upgrade before the bare-panel close.
- **`MovePreview`** — the `ConstructPreview` sibling, minus the name field,
  the dice and the stat list (nothing about the building changes, it just
  relocates): display name, `Cost`/`Time` lines (`Free`/`Instant` at zero),
  destination coords, CONFIRM/CANCEL. It reuses the SAME
  `ui.Timing.construct_show_cancel`/`confirm_on_right_side` chrome keys and
  the SAME `preview_*` id namespace, and mirrors `ConstructPreview`'s public
  surface (`hover`/`confirm_hovered`/`update`/`handle_click`/`handle_key`/
  `submit` + `confirm_btn`) closely enough that `main.py`'s existing
  `panel.preview is not None` modal branch drives it with **no
  preview-class-specific code**. `_preview_click` is the one place that
  branches, on `isinstance(self.preview, MovePreview)`.
- **`_do_move`** mirrors `_do_place`: re-check love (a race since the modal
  opened), call `start_move` in a `try/except MoveError` (flash
  `CANNOT MOVE THERE` — the destination got taken), spend, log, close the
  panel outright (the building has vacated its tile, so there is nothing left
  to show). **CANCEL leaves `mode == "move_select"`** so the player picks a
  different tile — nothing has moved yet, the same reading `_construct_click`'s
  cancel has (back to the card list, not to a closed panel).
- **`open_for_tile` refuses to open construct mode on a move endpoint** —
  both endpoints are plain BUILDABLE tiles, so without this the panel would
  offer cards `place_building` then refuses. Convenience only; the bar itself
  is in `place_building`.

## Map overlays + terrain badges (10I)
`game/ui/overlays.py` (`MapOverlays`, pure — covered by the purity scan) owns
ALL of 10I's UI so `hud.py` (10G boss bar + 10H lightning both edit it) carries
no 10I diff: two persistent bottom-left toggle pills (`RANGE`/`HEATMAP`, gold
rim + gold label when active; clicks consumed in `main.py`'s ladder between the
End-Turn branch and the panel, `over()` feeds the pan-arming `over_ui` check),
the world condition tint (windowed — never a full-grid scan; a **FALLBACK**
since condition art landed: `MapOverlays.condition_art` is the host's
`{slot: tint_overlay}` map over the condition slots that have imported art, and
the diamond is drawn only where `game.map.conditions.draws_tint` says so — no
art, or an entry that opts back in. Empty map ⇒ every non-grass tile keeps its
diamond, i.e. the pre-art look. The sprite itself is NOT drawn here: it goes out
on the `terrain` layer from `game/map/conditions.py`), the RANGE overlay
(union of footprints from RAW `range_tiles()`, mortar INCLUDED — its
exclusion is pathfinding-only — shaped per an optional duck-typed
`range_shape()`, `game/buildings/range_shape.py`: Chebyshev square when
absent, or a booster's configurable `"plus"`/`"square"`,
`BoostBuildings.globals.range_shape` — booster-range-config feature), and the
HEATMAP overlay (previous round's distinct-enemy traffic:
`track()` accumulates `id(e)` per tile during ENEMY and snapshots counts on the
phase edge; blue→yellow→red ramp in `heat_color`). `widgets.cond_label(name)`
(condition label + colour, keyed by `TileCondition.name` — the label text is
Phase C string-table content, `widgets.condition.*`; see "Global UI string
table" below) is shared with
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
  only, **in-tier upgrade** sums `_batch_upgrade_targets`. Range diamond only
  when the selection is a single tile. The base never batches.
  **fix/batch-tier-advance: tier ADVANCE now batches too, on a SEPARATE
  path from the plain in-tier batch above.** `_batch_advance_targets`
  (`game.core.levelup.advance_batch_plan`) sweeps a multi-selection for
  every building whose next tier is reachable right now — regardless of its
  own `upgrade_gate` mode — and, when that set is non-empty, `_build_upgrade`
  shows ONE combined `"ADVANCE ×n  <cost>"` button instead of the plain
  UPGRADE batch. Clicking it, for each target: pays and applies any
  remaining in-tier `upgrade()` calls needed to reach this tier's max level,
  then one `advance_tier()`, then `lightning.sync_level_from_tier` — all
  gated by ONE all-or-nothing total (no partial batch, same "NOT ENOUGH
  LOVE" flash the in-tier batch uses). A building that can never reach its
  next tier right now (already at the final tier, next tier unresearched,
  or round-gated) is excluded from the batch/cost entirely — left for the
  player to handle separately once it qualifies. **A single selection is
  unaffected**: `_batch_advance_targets` returns `[]` for `len(selected_
  tiles) <= 1`, so one selected building still upgrades one in-tier level
  per click and advances tier separately, via the original primary-only
  branch in `_upgrade_click`, byte-identical to before this fix.
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
  9E's invisible projectiles; **swappable sprites, fix-anchor-offset-and-
  bullet-sprites Fix 2**: two SHARED slots, `vfx_projectile` for every
  defender's stone and `vfx_shell` for a mortar's shell — never per-building
  art — swap in as a `HudSprite` once imported, colour/size/lift read from
  `data/balancing/vfx.json procedural.projectile` via
  `FloaterManager._vfx_params.projectile`; the "has art" check is the same
  `assets.animation_total_ms(slot, "idle") is not None` signal
  `engine.vfx.spawn_play_once` uses, so the two paths can never disagree
  about "imported". Deliberately NOT a `triggers` row — a projectile is
  continuous, like a beam or a lightning bolt, not a one-shot.
  **feat-projectile-anchored-flight: the lift is gone from this function —
  `submit_projectiles` is now a pure projection of `p.transform.world_pos`,
  no `int(tile_h*zoom*lift_frac)` subtracted at draw time.** It moved into
  the SPAWN POINT (`game/enemies/combat.py`'s `_fire`, via
  `game.anchors.projectile_point`), which is what let it double-count
  against an authored `muzzle` anchor before this fix. Unanchored play is
  unaffected — see `game/enemies/CLAUDE.md`'s matching entry for the
  homing-target half of this fix), blood
  splatters (`RunState.enemy_death_events`
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
    meets an `engine.vfx` dataclass field.
  - **ESV-3b**: craters/beams/lightning/boss-announce (10B/10G/10H) are now
    also ported — colours/alphas/widths/segments/jitter/flash params live in
    `data/balancing/vfx.json` (`procedural.beam/.crater/.lightning/
    .announce`, `engine.vfx.BeamParams`/`CraterParams`/`LightningParams`/
    `AnnounceParams`). Unlike ESV-3a, `submit_beams`/`submit_craters`/
    `submit_lightning`/`submit_announce` **stay in `effects.py`** — they read
    `scene.by_tag(...)` and building components the engine must not learn —
    and read the four new blocks straight off `FloaterManager._vfx_params`
    (held alongside `self._vfx`, not inside it: the scene already owns the
    crater/lightning fade clocks, so `VfxSystem` gained no new state).
    `submit_lightning` is the one draw that consumes random numbers — every
    SUBMITTED frame, not once at emit — and now draws through
    `self._rng` (the same injected `random` module `self._vfx` shares)
    instead of a bare module-level call. The two cosmetic fade lifetimes
    (`crater.life`, `lightning.bolt_life`/`marker_life`) are threaded as
    REQUIRED arguments from `resolve_combat`/`lightning.strike`'s new
    `vfx_balance`/`vfx` parameter (5th/3rd) all the way to the `CraterFade`/
    `LightningFXFade` component fields that own the despawn clock —
    `game/enemies/combat.py`'s `resolve_combat`/`Crater`/`ProjectileAOE` and
    `game/core/lightning.py`'s `strike`/`LightningFX` all gained a required
    argument; `Session.lightning_strike` gained a required 5th
    `vfx_balance` too (not stored on `Session` — passed per call, like
    `scene`/`cs`). The two copy strings (`_ANNOUNCE_L1/L2`) and the
    `ui.json FX.boss_announce` timings stay put — copy is screen-skinning
    territory, timings were already datafied.
  - **ESV-5**: a designer can now bind any of the 8 live cosmetic events
    (`building_placed`/`_level_up`/`_tier_up`, `building_destroyed`,
    `enemy_attack_melee`/`_ranged`, `enemy_death`, `splash_impact` — plus the
    still-inert `defender_fire`) to an imported `vfx_*` sprite sheet via
    `data/balancing/vfx.json`'s top-level `triggers` object (a sibling of
    `procedural`). `_triggers_from_balance` is the ONE place a trigger event
    NAME is read out of the JSON; every call site that used to call
    `self._vfx.emit_*`/`add_splatters` directly now goes through the private
    `_play(event, wx, wy, **kw)` dispatcher instead: a bound `sprite_slot`
    with imported art spawns a one-shot `engine.vfx.PlayOnceVfx`
    (`spawn_play_once` — `None` back means "no art yet", the same E-37
    signal `spawn_corpse` uses); otherwise the named `procedural` kind runs
    through the SAME `self._vfx`; an empty row (or an event absent from the
    table) is a silent no-op. Every shipped row's `procedural` reproduces
    exactly what that call site did before this phase — byte-identical on a
    fresh checkout with no art imported. `_play` needs two NEW host-wired
    attributes, `self.assets`/`self.scene` (the `self.log` precedent,
    wired in `game/main.py build_gameplay` beside `on_build_vfx`/`log`) —
    either being `None` degrades to the procedural branch, never raises.
    `splash_impact` (a mortar shell's landing) has no `FloaterManager` call
    site of its own: `game/enemies/combat.py`'s `ProjectileArc._impact`
    pushes `(wx, wy)` onto a new `RunState.splash_impact_events` ledger
    through `resolve_combat`'s optional `on_splash_impact` callback (the
    `on_enemy_death` layering pattern — `game/enemies` still imports NO
    `game/core`); `spawn_splash_impact_events` (called beside
    `spawn_death_events`) drains it into `_play`. The Crater GameObject's own
    continuous fade mark keeps spawning UNCONDITIONALLY either way — this
    only adds an optional additional one-shot at the same point.
    `enemy_death` fires per DEATH POINT (`_play` called once per point in
    the drained batch, not once for the whole batch) because a batch has no
    single shared spawn point for the sprite-one-shot branch; the
    procedural fallback (`add_splatters([(wx, wy)])` per point) extends the
    same list in the same order a single batched call would have, so the
    landing condition is unaffected.
  - **ESV-6 (the plan's FINAL phase)** re-points a SUBSET of the ESV-5
    dispatch sites at manifest-authored anchors — VISUAL ONLY (D4), never a
    damage/range/splash expression. **The anchor map**: `defender_fire` and
    both `enemy_attack_*` events move to the firing entity's `muzzle`;
    `building_destroyed` and the new `projectile_hit` (below) move to the
    destroyed building's / the target's `impact`. **Two exclusions,
    deliberate**: `enemy_death` (blood splatters) and `splash_impact` (mortar
    crater) stay UNANCHORED — both are GROUND DECALS with an `impact` anchor
    authored at body height (negative `y`, i.e. upward), so applying it would
    lift them off the ground; `splash_impact` additionally has no owning
    sprite to read an anchor from at all (`ProjectileArc._impact` carries a
    bare ground coordinate). `building_placed`/`_level_up`/`_tier_up` ALSO
    stay unanchored — they fire from `(col+0.5, row+0.5)` before any building
    object is reachable, and `spawn_building_vfx` receives no object, only
    coordinates. A new private helper, `_anchored(obj, name, wx, wy)`, wraps
    `game.anchors.anchor_world_point` (fix-anchor-origin-parity renamed this
    from ESV-1's `world_offset` and changed its return contract from a
    zoom/pan-invariant DELTA to an ABSOLUTE WORLD POINT — `_anchored` itself
    stays the ONE site every anchored call goes through) — it returns the
    input UNCHANGED when the store/cs/animator/anchor is absent (ESV-1), so a
    fresh checkout with no `anchors` authored stays byte-identical.
    `FloaterManager` gains a THIRD host-wired handle,
    `self.cs` (the `self.assets`/`self.scene` precedent — wired in
    `game/main.py build_gameplay` beside them; `None` degrades to the
    unanchored point, never raises).
  - **The plan's promised 10th event, `projectile_hit`** (VISUAL ONLY,
    at the TARGET's `impact` anchor): `game/enemies/combat.py`'s
    `ProjectileHoming._impact` pushes the anchored point onto a new
    `RunState.projectile_hit_events` ledger through `resolve_combat`'s
    optional `on_projectile_hit` callback (the `on_splash_impact` layering
    pattern — homing shots only; the mortar keeps its own `splash_impact`
    event); `spawn_projectile_hit_events` drains it into `_play`. Fires
    whether or not the target is still alive that frame (a hit VFX on a
    target that died the same frame is correct) — only a missing target
    guards it. This is what finally consumes the long-orphaned
    `vfx_hit`/`vfx_explosion` slots the plan's opening complaint named.
    `defender_fire` gets its first real call site the same way:
    `_fire`/`_fire_splash` already compute the muzzle-anchored spawn point
    for the projectile itself, and `resolve_combat`'s new optional
    `on_defender_fire` callback fires with that SAME point (never
    recomputed) into a new `RunState.defender_fire_events` ledger, drained by
    `spawn_defender_fire_events`. **Both new rows ship INERT** (`{sprite_
    slot: "", procedural: ""}`), exactly like `defender_fire` shipped in
    ESV-5 — zero visible change on landing.
  - **The floater port (closes the plan's §6 item 1 dead-data gap)**: the
    seven floater colour/lifetime module constants
    (`_UPKEEP_BLUE`/`_XP_PURPLE`/`_XP_LIFE`/`_PAINTER_FINISHED`/`_PAINTER_
    LOST`/`_PAINTER_LIFE`/`_BOOST_WHITE`) are DELETED. `data/balancing/
    vfx.json`'s `procedural.floaters` block existed since ESV-3a but was
    NEVER read (`_params_from_balance` never touched it) — a designer
    editing it in the `vfx` balancing form saw no effect in game. The four
    floater spawn sites (`spawn_income_events`/`spawn_xp_events`/
    `spawn_painter_events`/`spawn_boost_events`) now read
    `self._vfx_params.floaters` (`engine.vfx.FloaterParams`, built by
    `_params_from_balance` like every other family); the JSON already
    shipped values identical to the constants, so this is a visual no-op on
    landing and a live designer lever from here on. **`game/ui/hud.py`'s OWN
    `_XP_PURPLE`** (a different colour, the XP-bar pulse) is HUD chrome, not
    a floater, and was deliberately NOT touched or unified with this.
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
  `credits`'/`game_over`'s/`add_name`'s `title`, `cheat_menu`'s `title`/
  `jump_label`, `boss_cutscene`'s `subtitle`. Their copy is NOT game-state,
  so — unlike the HUD readouts below — `label` (the text itself) is a
  legitimate override field for these, same shape as any other widget
  (`rect`/`font_key`/`text_color`/`label`/`visible`).
- **`hud.py`'s ~13 stable readouts all carry ids now**: `love_panel`,
  `readout_panel` (the second stone pill, behind the income/lives/tiles
  column — same `C_PANEL_STONE` body + `C_PANEL_INSET` inset border as
  `love_panel`, drawn with `HudRect` not a skin, and sized in
  `_layout_readouts()` to wrap those three rows' DEFAULT anchors via
  `layout_h("md")`, per the no-cascade convention),
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
  closed this gap) `building_ui.py`'s previously-un-id'd STABLE buttons:
  `rename_dice_btn` (the upgrade panel's `⚄` rename row, `self._dice_up`) and
  `boss_close_btn` (the boss-history popup's CLOSE), both created once in
  `__init__` and joining the same mode-independent `self.ids` dict as
  `panel`/`close_btn`/`action_btn`/`boss_btn`. (A third, `lightning_btn` — the
  ⚡ UPGRADE LIGHTNING button, REBUILT every time a now-deleted
  `_build_base_info` ran — was the one exception to the static-ids-dict
  pattern; it and its whole base_info lightning section were removed
  entirely by the Storm Priest rework, so `tools/export_ui_layouts.py` no
  longer needs a forced builder call for base_info either.) The construct
  cards remain the one un-id'd case (genuinely dynamic-count —
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

## Fonts + palette are DATA now (UH-6, D5) + optional per-widget tint (D6)
`data/ui/fonts.json` / `data/ui/palette.json` ship the exact 7 font presets /
19 `C_*` colors this file used to hardcode alone (the 19th, `purple` /
`C_PURPLE` = the house purple, is what `main_menu.py`'s `title`/`subtitle`
tint to — its BUTTONS deliberately keep the stock `ui_btn*` colours;
`hud.py`'s own `_XP_PURPLE` stays a private module constant, same
"HUD chrome is not the shared palette" line the floater port drew) — `game/main.py` loads +
schema-validates both at boot (before the `Shell`/screens are built) and
calls `engine.render.fonts.configure_fonts(doc)` / `widgets.
configure_palette(doc)`. The literals in `widgets.py`/`engine/render/
fonts.py` are now the UNCONFIGURED FALLBACK (the `ScreenSkinning.empty()`
precedent — bare test/tool construction stays deterministic); a pin test
(`tools/tests/test_theme_data.py`) proves the fallback equals the committed
data, so the two can never silently drift apart.

- **Every consumer reads the palette via `widgets.C_GOLD` attribute access,
  never `from .widgets import C_GOLD`.** An early-bound import captures the
  tuple at IMPORT time — a later `configure_palette` rebind (a module
  attribute reassignment) can never reach it. All 14 `game/ui/*.py` files
  (13 + `effects.py`) were swept onto `from . import widgets` +
  `widgets.C_*`. **This applies to EVERY reference, not just def-line
  defaults** — a module-level constant copying a color (the old `levelup.py
  _BOX_BG = C_UI_PANEL`, `hud.py _PHASE_COLOR` dict) is the SAME trap at
  module scope: it freezes the value at import time. `levelup.py` inlines
  the attribute read at its one call site instead of a module constant;
  `hud.py`'s `_phase_color(phase, default)` is a FUNCTION, not a dict, for
  the same reason. `widgets.submit_panel`'s `fill`/`border` used to default
  to `C_UI_PANEL`/`C_UI_BORDER` at DEF time (the one place a bare name
  inside `widgets.py` itself still traps, since default-argument
  expressions evaluate once at import) — they now default to `None` and
  resolve inside the function body.
- **`configure_fonts`/`configure_palette` fail loud on a key-set mismatch**
  (missing or unknown key) — a renamed/dropped preset or color would
  otherwise leave some `font_key`/`C_*` silently un-rebound.
- **`layout_h`/`_LAYOUT_H` are UNTOUCHED by `configure_fonts`** (see the
  section above) — a designer enlarging a preset changes drawn glyphs only;
  stored layout rects don't move, so text can overflow its widget. That is
  the pinned-layout contract, not a bug (the editor's Theme panel says so
  in a tooltip).
- **Optional per-widget `tint`** (`data/ui/screens/<id>.json`'s `widgets.
  <id>.tint`, `data/schemas/ui_screen.schema.json`): a sheet-multiply color
  on the DATA/ENGINE side for any widget that resolves to a skin (per-widget
  `skin` OR a kind-matched `defaults.button_skin`/`panel_skin`).
  `ScreenSkinning.apply`'s generic setattr loop threads it onto the widget
  for free (same as `skin` — no `_SPEC_TO_ATTR` entry needed). Wired into
  the engine for free too: `widgets.Button.submit`/`submit_panel` pass
  `tint=getattr(self_or_holder, "tint", None)` into the `HudSprite`; the
  engine's `HudSprite.tint` → `DrawCall.tint` → `BLEND_RGBA_MULT` path
  already existed (`engine/render/CLAUDE.md`). **Omitted = `None` = today's
  rendering, pinned** — every pre-UH-6 skin test holds unchanged.
  **Editor-authoring note (post-reconciliation):** the editor's details panel
  offers a Tint control for the kinds whose draw path threads `tint` —
  **`button` and `panel`**. `Button.submit` always forwards `tint`; every
  *id'd* panel widget forwards it at its `submit_panel` site. The two
  `submit_panel` sites that DROP `tint` (`building_ui.py:1252` boss popup,
  `levelup.py:128` boxes) draw dynamic, non-id'd content that is not
  editor-selectable, so this is honest. `field`/`label` never draw a skin, so
  they get no Tint control. One residual: `hud.love_panel` is kind `panel` but
  drawn via `HudRect` (no sheet), so a `tint` on it no-ops — the same deferred
  skin-on-a-non-skinnable-widget quirk as `backdrop`/`bar`. See
  `editor/panels/CLAUDE.md` "Reconciled rule".
- **The editor's screen-mode preview honesty fix (ties to UH-3)**: the
  editor used to tint a skinned widget's preview from its `color` override
  — a lie, since the game has always ignored `color` on a skinned widget
  (`skinning.py`'s `button_kwargs` docstring). It now tints from `tint`
  only (`editor/panels/viewport.py`), and the details-panel Color control
  is repurposed into Tint (enabled, not disabled) on a skinned widget —
  `editor/panels/CLAUDE.md`.
- **Per-widget `label` override now takes effect at render time (Phase B).**
  The resolution mechanism was already generic and already live — `apply`'s
  setattr loop threads `label` onto any id'd widget for free, same as
  `skin`/`tint` above (no `_SPEC_TO_ATTR` entry, no separate `label_for`
  accessor needed; there is no per-field `tint_for`/`skin_for` split to
  mirror — `apply()`'s one setattr loop IS the shared resolver for every
  override key). Every `Button` already reads `self.label` in `submit()`, so
  a `Button`'s id'd `label` override has worked since 10L-B with zero extra
  wiring (`building_ui.py`'s `action_btn`/`boss_btn`/`close_btn`/
  `rename_dice_btn`/`boss_close_btn`/`preview_*` included — all `Button`
  instances, all id'd, all already overridable). The gap Phase B closed was
  narrower: a handful of non-`Button` `"label"`-kind holders (`SimpleNamespace`
  shadow objects) were never given a `label` attribute at construction, so
  their `submit()` read a hardcoded module-level string literal instead of
  `holder.label` — the override landed on the object (`apply()` doesn't care)
  but nothing ever read it back. Fixed: `cheat_menu.py`'s `title`/
  `jump_label`, `boss_cutscene.py`'s `subtitle` now default `label=` to
  today's literal and their `submit()` reads `self._holder.label` — parity
  preserved (no override ⇒ identical output), override now honored.
  `boss_cutscene.py`'s `headline` is the deliberate exception: its text is a
  2-variant win/loss string built from runtime outcome (`self.outcome`), the
  same "enum-varying, not a fixed title" exclusion HUD's dynamic readouts
  already use — only its font stays overridable via THIS mechanism, and
  color stays logic-owned; the two variant TEXTS themselves are Phase-C
  string-table content instead (`boss_cutscene.headline_win`/`headline_loss`
  — see "Global UI string table" below), not this `label` mechanism. Dynamic
  per-mode content (`building_ui.py`'s `action_btn` label text itself varies
  by mode/afford-ability, "UNLOCK TILE"/"BUILD"/"THE HOLE" mode headers,
  `levelup`'s/`credits`' list rows, HUD's ~12 game-state readouts) stays out
  of scope for `label` specifically for the same reason — a stable id alone
  doesn't put dynamic text in scope, only a FIXED string does; some of it
  (HUD's readouts, `levelup.py`'s heading/cost lines) is Phase-C string-table
  content instead, below.
  `data/ui/screen_defaults.json` was regenerated (`py
  tools/export_ui_layouts.py`) to reflect the three previously-`""` labels.

## Global UI string table (Phase C)
`data/ui/strings.json` ↔ `game/ui/strings.py` covers what the per-widget
`label` override above structurally cannot: text that varies by runtime/enum
state (the HUD phase banner, the boss-cutscene win/loss headline) or is
BUILT FROM A TEMPLATE with live values (`"LIVES {count}"`, `"ROUND {n}"`,
`"{built}/{unlocked} tiles"`) — there is no single fixed string to attach to
a widget id for those. Mirrors `engine/render/fonts.py`'s cache/configure
shape exactly: a module-level `_STRINGS: dict[str, str]` seeded with today's
literal text (so an unconfigured import — bare test/tool construction —
still renders byte-identical output, the same precedent `fonts.py`/
`widgets.configure_palette` set), `configure_strings(doc)` rebinding it in
place (called at boot, `game/main.py`, alongside `fonts.json`/
`palette.json`, same fail-loud-on-key-mismatch D-2 behavior), and
`T(string_id, **kwargs) = _STRINGS[string_id].format(**kwargs)` — the ONE
way any call site reads an entry (never index `_STRINGS` directly, so a
later `configure_strings` rebind always reaches every caller; there is no
C_*-style early-binding trap to guard against, since nothing holds a
reference to a resolved VALUE, only to the `T` function).
- **Dotted ids grouped by source module** (`hud.phase.building`,
  `hud.income.base`, `widgets.condition.grass`, `levelup.heading`,
  `boss_cutscene.headline_win`, …) — the editor's Strings panel groups rows
  by the id's prefix before the first dot.
- **A dict literal built at import time is the SAME early-binding trap
  `configure_palette`'s `C_*` block warns about, one level up**:
  `widgets.cond_label(name)` and `hud.py`'s `_phase_label_text(phase)` are
  FUNCTIONS, not dicts of resolved text, for exactly that reason — each
  resolves fresh via `T()` on every call instead of caching text at module-
  import time (which would freeze the pre-`configure_strings` fallback and
  never see a later rebind). `hud.py`'s `_phase_color` already established
  this "function, not a frozen dict" shape for the palette; Phase C reuses
  it for strings.
- **`hud.py`'s income-tooltip categorization compares against `T(...)`, not
  a hardcoded literal** (`_submit_income_tooltip`): since `income_sources()`
  now returns the RESOLVED `hud.income.upkeep`/`hud.income.story` text as
  each row's label, the tooltip's red/gold/green styling branch re-resolves
  the same ids at comparison time — so a designer renaming those two labels
  in `strings.json` can't desync the comparison from what the label list
  actually contains.
- **No editor-side in-process reconfigure** (the exact `palette.json` case
  `data/CLAUDE.md`'s theme-data section documents): `game/ui/strings` is
  game-only, off limits to the editor (`editor/` never imports `game/**`).
  The editor's Strings panel (`editor/panels/strings_panel.py`,
  `editor/strings_ops.py`) writes `strings.json` and stops there; the game
  re-reads it at its own next boot.
- **Migration status**: Phase C covered `hud.py` in full,
  `widgets.cond_label`, `levelup.py`'s heading/cost/tier-progress lines, and
  `boss_cutscene.py`'s win/loss headline. UT-3 took `building_ui.py`, UT-4
  the rest of `hud.py`, and **UT-5 the remaining screens + `effects.py`** —
  see the UT-5 section below. There is no known un-migrated user-visible
  string left in `game/ui`; what stays a Python literal now does so for a
  stated reason (a static title on the per-widget `label` mechanism, or a
  runtime-authored value), not because nobody got to it.

## `text_id` — a widget's text is DATA now (UT-1 … UT-4)

The 10L-B widget contract gained a fifth override key beside `rect`/`skin`/
`font`/`color`/`text_color`/`visible`/`tint`: **`text_id`**, the
`data/ui/strings.json` key a label-bearing widget resolves its text through.
It needs no `_SPEC_TO_ATTR` entry — `ScreenSkinning.apply`'s one generic
setattr loop threads it onto the holder for free, exactly like `skin`/`tint`.

**`widgets.submit_label(renderer, holder, **fmt)` is THE idiom.** It resolves
`T(holder.text_id, **fmt)`, reads geometry/font/colour/alignment off the
holder (i.e. off whatever `apply()` last wrote), and skips a hidden or empty
one. Build the holder with `widgets.label_holder(...)`, whose defaults encode
the text-label convention (an `(x, y, 0, 0)` ANCHOR, W/H nominal 0, stored in
`layout()` so the exporter reads a real position and a rect override moves the
text). **Never re-implement the resolution inline** — a call site that reads
`holder.text_id` itself is the drift this helper exists to prevent.

Three escape hatches, all deliberate:
- **`text=`** overrides both, for runs whose CONTENT is authored at runtime
  and no template can produce: a building's player-typed name, the rename
  box's live buffer, a phase banner that picks one of six ids by enum. The
  holder still owns position, font and colour — only the characters are not
  the designer's.
- **`color=`** is the code-computed fallback used when no `text_color`
  override is set (the "`None` means compute" convention).
- A holder with no `text_id` falls back to its static `label` — the pre-UT-1
  behaviour, unchanged, and still the right answer for a fixed title.

### Per-stat widgets (`building_ui.py`, UT-3)

`_building_stats(b)` returns `(stat_key, value)` — **not** `(label, value)`.
The label is the widget's own `building.stat.<key>` template. Every key in
`STAT_KEYS` owns TWO id'd widgets, `stat_<key>_label` and `stat_<key>_value`,
so a designer can place a stat's NAME and its NUMBER independently. Rules:

- **`_layout_upgrade_rows()` stacks the SHOWN subset**, and it runs from
  `_build_upgrade` — before any `submit()`, therefore before
  `skinning.apply` — which is what makes a rect override win. Rows below an
  overridden one keep their own defaults (the no-cascade convention).
- A stat the selected building lacks keeps its canonical-order anchor from
  `_build_text_holders`, so the exporter still records a real position for
  its two ids.
- The hover next-level preview matches on the **key**, so renaming a stat in
  `strings.json` can no longer silently break the green highlight — which it
  could when the match was on label text.
- `boosted_stats()` still returns display labels; `_BOOSTED_STAT_KEYS` maps
  them, rather than widening that method's contract for its one consumer.
  `game/buildings/boost.py`'s four classes carry `_boost_stat_key` beside
  `_boost_label` for the same reason.
- **Dynamic-count content keeps the construct-card rule**: the next-tier
  card's three rows and `ConstructPreview`'s stat list get no per-row id, but
  their labels resolve through the SAME `building.stat.*` ids, so a rename
  reaches them too.

### The remaining screens + `effects.py` (UT-5)

The same conversion, screen by screen. The rule that decided **id vs. plain
`T()`** everywhere below is the anchor-rect convention already stated above:
**a widget id needs a STORED rect first.** Copy whose position is computed
inline from another widget's rect at submit time gets its text into
`strings.json` and stops there — giving it an id would mean inventing a
stored anchor for it, which is a layout change, and UT-5 is explicitly not
allowed to move a pixel.

- **New ids (all additive; `screen_defaults.json` gained widgets, nothing
  moved)**: `game_over`'s three run-stat rows
  (`stat_round`/`stat_buildings`/`stat_enemies`), `levelup`'s `heading`,
  `settings`' `dm_label`/`dm_value`/`audio_label`/`audio_note` plus one
  `label_<attr>` per FX toggle row (the sibling of its existing
  `btn_toggle_<attr>` — a row's NAME and its ON/OFF control are
  independently placeable, the per-stat rule), and `add_name`'s
  `hint`/`msg_text`/`pool_count`.
- **`text=` (runtime-authored content, holder still owns everything else)**:
  `boss_cutscene`'s headline (a 2-of-2 enum pick), `settings`' display-mode
  value, `add_name`'s feedback line, `game_over`'s numbers.
- **String ids, no widget id**: `cheat_menu`'s round-field placeholder and
  `add_name`'s name-field placeholder (both positioned off their field's
  rect), `credits`' two row columns (dynamic-count rows, so `credits.role`/
  `credits.name` are `{value}`-shaped templates the way `building.stat.value`
  is), and every string in `effects.py` — the announce banner, the boss HUD
  bar's label + `hp/max`, the four floater texts, and the "<name> has been
  killed" game-log line. **`effects.py` is FX, not a screen**: it has no
  `ids` dict at all and every position is a world point or a view-relative
  centre, so `T()` is the whole of its binding.
- **Deliberately unchanged**: `main_menu`, `pause`, `overlays` and
  `tutorial_message` carry no templated or un-id'd copy — every string on
  them is either a static title/button caption already served by the
  per-widget `label` override (which is documented above as the right answer
  for a fixed string, and which `test_ui_text_binding`'s
  `test_unbound_widget_keeps_the_per_widget_label` pins on `main_menu.title`)
  or runtime script text (`tutorial_message`) with an id'd holder already.
  `game_log`'s lines are posted messages — its one `log` id styles them and
  their text belongs to whoever posted it.
- **The three code-only screens** (`highscores`, `player_intro`,
  `debug_settings`) were NOT added to `tools/export_ui_layouts.py`'s
  `SCREEN_IDS`, nor was `tutorial_message`. The plan floated it as a
  deliberate scope addition; adding a screen there also adds an entry to
  `screen_previews.json`, and UT-5's landing condition is a byte-empty diff
  on that file. It stays a separate change.

### What is still code-owned, and why

Not everything became data. `hud.py`'s income-breakdown tooltip and lightning
readout are hover/phase-gated overlays with no stored rect (they are drawn
from a computed position at submit time), so they carry no id — their TEXT is
already `T()`-bound and editable, only their POSITION is not. The same goes
for `building_ui.py`'s terrain badge/tooltip and the boss-history rows.
Giving one of those an id means giving it a stored rect first (the anchor-rect
convention above), not just wrapping the draw call.

## The love glyph is GONE
`widgets.HEART` (`"♥"`) and every `{heart}` placeholder are DELETED — the
Pixel Emulator game font has no glyph for it, so it rendered as tofu. Four
`strings.json` templates lost the placeholder (`hud.love_display`,
`hud.love_unaffordable`, `hud.income_net`, `levelup.cost_paid` — ids and
every other placeholder unchanged) and `building_ui.py`/`effects.py`'s
f-strings dropped it inline. Costs/payouts now read as bare numbers
(`UNLOCK  40`). Do not reintroduce a currency glyph in text; the love ICON
(`ui_icon_love`, the baked HUD sprite) is where love is signposted.

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

## Cutscenes (Phase TU-5)
`game/ui/cutscene_player.py` — `CutscenePlayer` (wraps `engine.video.VideoSource`
+ an optional companion audio track via `engine.audio.play_music`/`stop_music`)
and `load_cutscene_registry(data_dir)`, which reads `data/video/cutscenes.json`
(TU-1's registry, `id -> {video, audio, length, trigger}`). Two independent
trigger call sites in `main.py`, never unified into one state machine:
- **`intro`** — the pre-menu `GameState.CUTSCENE` shell state, migrated off its
  old hardcoded `data/video/cutscene.mp4` + `ui_balance["Menu"]["cutscene_length"]`
  path onto the registry's `intro` entry.
- **`first_end_turn`** — `Session.end_turn()` sets `state.pending_cutscene` on
  round 1 (before `spawner.begin_round()`); the host consumes it at the top of
  the `_WORLD_STATES` sim branch, freezes the round behind a host-local
  `gp["cutscene"]` flag (not a new `GamePhase`), and paints the video as a
  full-screen overlay after the frozen world's own `renderer.flush(window)`.
  Missing video/cv2 → `CutscenePlayer.enabled` is `False`, `gp["cutscene"]`
  is never set, and the round starts normally the same frame (graceful skip,
  never a new branch).
- **Only one `pygame.mixer.music` channel exists.** Starting a cutscene's
  companion track replaces whatever background music was already playing;
  nothing restores it afterward (no drift/resume correction in scope).

## Tutorial message box + guided-chain highlights (Phase TU-6)
- **`game/ui/tutorial_message.py`** (`TutorialMessageScreen`) — the
  `game_over.py` construct→layout→update→hit→submit template: a centred
  dim-backdrop panel showing the director's (script-driven, NOT
  id-overridable — the text is runtime state, same convention as every other
  dynamic HUD readout) message text, a CONTINUE button, and a SKIP TUTORIAL
  button whose visibility is set from `TutorialDirector.skippable()` each
  `layout()` (a screen-JSON override still wins, applied after). `hit()`
  returns `"continue"`/`"skip"`/`None`; `game/main.py`'s
  `handle_world_click` treats the whole modal as consuming every click while
  `TutorialDirector.message_visible` is true — the highest-priority branch
  bar GAME_OVER. Built once per `build_gameplay()` alongside `gp["panel"]`,
  sharing `shell.skinning` like the other seven gameplay screens;
  `data/ui/screens/tutorial_message.json` is the 14th screen override file,
  started `{}` like every other.
- **`widgets.C_TUTORIAL_HIGHLIGHT`** (white, a plain code constant — NOT
  palette-data-backed, unlike every other `C_*`) + **`submit_ui_box_highlight
  (renderer, rect, color=None, width=3)`** (a highlight ring around a card /
  Confirm / End Turn button, plain HUD-space `HudRect`) are the two new D8
  primitives the guided chain draws with; no new render-backend work.
- **`building_ui.py` gained three small, additive, read-only members** (no
  change to `_construct_click`/`open_for_tile`/any existing control flow):
  `card_rect(building_type)` (the construct-mode card's rect, or `None`),
  `confirm_rect()` (the open `ConstructPreview`'s CONFIRM rect, or `None`) —
  both right after `dismiss()` — and `self.last_placed_type` (a transient set
  to `p.building_type` in `_do_place` only on a REAL placement, `None`
  otherwise; never reset by `close()`, since `_do_place`'s own
  `open_for_tile()` call closes the panel internally before `main.py` gets to
  read it). `game/main.py` reads `last_placed_type` once right after a
  successful `panel.handle_click()` to distinguish "a building was placed"
  from "the preview was merely cancelled" (both clear `panel.preview` the
  same way) and clears it back to `None` itself. TU-8 added a FOURTH:
  `close_rect()` (the panel's own CLOSE/X rect, or `None` when the panel
  isn't open — same additive shape).
- **TU-8 added a second widgets primitive, `submit_tutorial_banner(renderer,
  text, view_w, view_h)`** — the `submit_ui_box_highlight` sibling for a
  full-text hint rather than a ring: a big `C_TUTORIAL_HIGHLIGHT`-filled,
  screen-centred box sized to the text, drawn with **no hit-test and no
  input consumption** (unlike `TutorialMessageScreen`, which must never be
  used for a hint instructing a right-click — that modal swallows every
  click while visible, `main.py` `handle_world_click`'s top branch). Reads
  its text from `TutorialDirector.banner_text()`, submitted independently of
  (and alongside) `ui_highlight_rects`'s Close-button ring — see
  `game/CLAUDE.md`'s "Un-stick on panel close + close-panel hint" section.
- **Detail on the director/host wiring** (the three choke points, the event
  feed, the D6 zero-overhead contract, TU-8's revert/close-panel-hint
  additions) → `game/CLAUDE.md`'s Tutorial director section.

## Verify
Live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game
over screen; cold `py game/main.py`: cutscene → menu → rounds → pause/settings →
add name → credits. Purity test in the suite:
`py -m unittest discover -s tools/tests -t .`.
