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

### A text run has TWO font axes (UH-Font-B)

`font_key` picks a size/bold preset; `font_family` picks the face those
glyphs come from. They are independent, and both are designer-ownable off
the screen doc — `ScreenSkinning.apply`'s generic setattr loop threads
`font_family` onto a widget for free (it needs no `_SPEC_TO_ATTR` entry,
unlike `font` → `font_key`).

Every text run in this package reaches `HudText` through
`widgets.submit_text` / `submit_centered` / `submit_label` / `Button.submit`
or `skinning`'s two draw paths, so those are the only places that thread the
family — no screen module does it itself. A holder carries it as
`font_family` (see `label_holder`), `None` meaning "inherit".

**`layout_h` takes no family, on purpose.** Positioning stays keyed by the
preset alone, so a family swap changes drawn glyphs and never a stored rect.
`text_size`/`text_h`/`wrap_text` DO take one — they are draw-time-only
measurements (word wrap, a hover hint's width) whose output is never stored
or captured, which is exactly the line the `layout_h` rule above draws.

**That test measures the font the game actually SHIPS**, not whatever font
state the process happens to be in. `data/ui/active_font.json` boots
`pixel_emulator`, which is wider per glyph than the `SysFont("monospace")`
metrics every pixel constant in this package was authored against, so the two
disagree — and while the test measured the fallback, twelve static labels
overhung their buttons in game with the suite green. It now resolves the
active face exactly as `game/main.py` does and installs it in `setUpModule`,
restoring `engine.render.fonts`'s globals in `tearDownModule` (the
`test_theme_data.py` no-leak rule). **So the rule for new UI copy is: measure
it at the shipped face.** The two fixes that pass this check are (1) shorter
copy and (2) a smaller font for that ONE widget — never a change to
`data/ui/fonts.json`, whose presets are global and must not move. The twelve
were fixed that way: copy for nine (e.g. `RETURN TO MENU`/`QUIT TO MENU` ->
`MAIN MENU`, `HEATMAP` -> `HEAT`, `TIER OVERVIEW` -> `TIERS`, `DRAG SEL` ->
`DRAG`), a per-widget `lg` -> `md` for the three with no words left to cut
(`hud.btn_end_turn`, `main_menu`'s SET gear, and the preview modals'
CONFIRM/CANCEL row via `building_ui._PREVIEW_BTN_FONT`). No rect grew.

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

## Payout-phase sequencing + animated love counter (feature)
The payout no longer fires every boost/economy/upkeep floater in one frame.
`FloaterManager.begin_payout(state)` (`effects.py`) — called ONCE on the
`INCOME` phase edge from `main.py`, replacing the old three separate
`spawn_income_events`/`spawn_painter_events`/`spawn_boost_events` calls —
builds three ordered BEATS (boost, economy [income-kind `income_events`
entries + Painter's finish/lost message], upkeep) and queues them for
staggered release by `update(dt, state)`, `core.PhaseLoop.
payout_stagger_interval` apart — the `game/enemies/spawner.py` timed
`_queue`/`_timer` pattern. A beat's presence in the queue mirrors
`payday.py` step 12's `phase_timer` formula exactly (`game/core/CLAUDE.md`),
so the phase always stays open exactly as long as the queued beats need.
Floater LIFETIME for these three beats is `vfx.json procedural.
floaters.income_life`, decoupled from `core.PhaseLoop.
income_phase_duration` (now the phase's post-last-beat hold time, not a
floater life) — Painter's own entries keep their existing, separate
`painter_life`. `ui.FX.income_floaters_enabled` gates only the income/
upkeep-derived floaters within a beat (unchanged from before this
feature) — never whether the beat/pause/counter-checkpoint happens; boost
and Painter floaters were never gated by it.

**The HUD love counter animates instead of snapping**, for every love
change anywhere in the game, not just payout — spending, cheats, boss
bonuses, the works. `FloaterManager` owns it: `love_display` (a property,
`round()`ed) is what `Hud.submit` draws outside a hover preview
(`main.py` threads `love_display=gp["floaters"].love_display`); the ramp
is LINEAR, fixed-duration (`ui.json FX.love_counter_anim_duration`,
independent of how big the change is), and a retarget mid-flight starts
from the counter's CURRENT displayed position, never from its old target
— so it can never visibly jump. Two drivers into the same ramp state:
`begin_payout`'s beat releases arm an explicit segment each (the economy
beat's release targets `state.payout_love_after_economy`, the upkeep
beat's targets the real final `state.love` — see `game/core/CLAUDE.md`'s
payout-sequencing bullet for where those two checkpoints come from); a
generic per-frame watcher in `update(dt, state)` handles every OTHER
change, but stays quiet while a payout sequence is still queued (its
segments already account for that round's pending change) — this is what
lets a single synchronous `run_payday()` call's one big `state.love` jump
still read as two separate, correctly-timed ramps instead of one.
**Tuning note**: with the shipped defaults (`payout_stagger_interval`
0.42s < `love_counter_anim_duration` 1.2s) the upkeep beat's retarget
fires before the economy ramp finishes, so the counter curves toward the
lower total mid-climb rather than fully arriving first — smooth, not a
jump (the same mid-flight mechanic), but not two fully sequential ramps
either. If a designer wants the ramps to fully complete before the next
beat fires, raise `payout_stagger_interval` to >= the counter duration.

**The hover-cost preview shows the arithmetic, not the remainder — in two
colours.** `Hud.submit`'s `hover_cost` branch used to show
`state.love - hover_cost` (what you'd be left with, all one colour); it now
draws `"current - price"` as TWO separately-coloured `HudText` runs via the
new `Hud._submit_love_hover_cost` — the current-love half stays the plain
love colour (`widgets.C_GOLD`, or a designer's `love_text` `text_color`
override), only the `" - price"` half reads `widgets.C_RED` — for both an
affordable and an unaffordable hover alike. Two string-table ids, not one
combined template split in code: `hud.love_hover_cost_current` (`"{current}"`)
and `hud.love_hover_cost_price` (`" - {price}"`), each independently
designer-editable; the second is drawn immediately after the first via a
live `widgets.text_size` measurement (the income-tooltip/lightning-readout
precedent for hover-only text with no stored rect). Falls back to a single
combined (red) draw if `love_text`'s alignment is ever not `"left"` — the
two-segment math assumes left alignment, and today it always is. Always
reads the REAL `state.love`/`hover_cost`, never the animated `love_display`
— affordability is a correctness question, not a payout-flavor display.

**Floaters sharing one anchor point stack vertically.** Boost floaters are
anchored at the RECEIVING building's tile, not the booster's own tile
(`game/buildings/boost.py`'s `apply_per_turn`) — so several boost buildings
buffing the same defender all land a floater on that ONE tile in the same
beat, which used to draw them directly on top of each other. `FloaterManager
.submit` now groups `self._floaters` by exact `(wx, wy)` every frame (spawn
order preserved — the list is append-only until culled) and gives each
floater in a group its own vertical slot, `_FLOATER_STACK_STEP` (14px, fixed
code chrome, not balancing) apart — the exact `submit_enemy_hp_bars`
per-tile-group precedent (`game/ui/CLAUDE.md`'s "Overhead HP bars" section)
applied to floater text instead of bars. Generic by anchor point, not
boost-specific — any floater kind sharing a point stacks the same way, at no
extra cost (the grouping already has to walk every active floater to draw
it).

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

## Phase readout (`phase_label`) — bottom-RIGHT, two states
The phase banner is no longer the bottom-left six-way phase name. Same holder,
same `phase_label` id, same `label` kind, same `hud_phase` font and same
`_phase_color(phase, …)` tint — three things changed:
- **Position**: it moved out of `layout()`'s fixed `(6, view_h - 13)` into
  `_layout_readouts()`, stacked one `layout_h("hud_phase") + 4` above
  `round_label` and left-aligned on the End Turn button's own left edge (i.e.
  the bottom-right cluster). It HAD to move passes: the anchor is now relative
  to the post-override `end_turn` rect, exactly like `round_label` — which is
  also why `__init__` seeds it with a `(0, 0, 0, 0)` placeholder rect and
  `tools/export_ui_layouts.py`'s `_build_hud` (which already calls
  `_layout_readouts()`) still exports a real position.
- **Copy**: `_phase_panel_text(phase)` — `"Building Phase"` for
  `GamePhase.BUILDING`, `"Defending Phase"` for every other phase. The six-way
  `_PHASE_LABEL_ID` map and `_phase_label_text` are DELETED; the two strings
  are code constants (the `effects.py` `_ANNOUNCE_L*` precedent) rather than
  new string-table ids, because `configure_strings` fails loud on a key-set
  mismatch and two literals do not justify a coupled `strings.json` +
  `strings.py` + `test_strings_data.py` change. **The six `hud.phase.*` ids
  are therefore live in the string table but referenced by no code** — a
  string-table follow-up pass owns cleaning that up.
- **It is drawn inside the `if not self._panel_open` right-edge cluster**, not
  unconditionally: the building panel is a full-height 260px right sidebar and
  the HUD submits AFTER it, so an unconditional draw at this position would
  paint over an open panel. Same rule and same reason as `round_label`.
- **Golden pin**: exactly one primitive in `test_ui_skinning.py`'s `hud`
  baseline changed (text + pos, same index) and `data/ui/screen_defaults.json`'s
  `hud.phase_label.rect` was patched to match — the sanctioned "a screen's
  default geometry changed on purpose" path.

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

## Boost aura (feature: an always-on VFX at every boost building)
**`submit_boost_auras`** (`game/ui/effects.py`, beside `submit_drummer_auras`;
called from `game/main.py` right after it) — a continuous, looping sprite drawn
BEHIND every live boost building, bound by
`data/balancing/vfx.json`'s `triggers_by_type.<building_type>.boost_aura`
(`data/CLAUDE.md` has the data half, including why that open registry exists).

It is the third member of the CONTINUOUS-effect family, and the first one that
is both entity-attached AND swappable art:
- Unlike `_play`/`PlayOnceVfx` it re-submits a plain `RenderItem` every frame.
  A despawn clock is the wrong mechanism for an always-on effect — it would
  respawn the object each frame (the same VA-5 / `triggers.projectile`
  reasoning `submit_highlight` carries).
- Unlike `submit_highlight` (`widgets.py`) it walks the scene —
  `scene.by_tag("boost")`, never `isinstance` — instead of being handed tiles.
- Unlike `submit_drummer_auras` it is ART, not a procedural ring: its rows
  ship `procedural: ""`, so with nothing imported it draws NOTHING (E-37).

Four gates, each a `continue`, never a raise: no row / no slot; the building's
`BuildingSprite.hidden`; no art on the RESOLVED variant; and `draw_in_front`
→ `rank ∓1`.

Three things worth knowing before touching it:
- **`BuildingSprite.hidden` is now a SHARED predicate**
  (`game/buildings/components.py`) — the dead-owner + `reveal_delay` pair the
  sprite's own `render_items` early-returns on, factored out precisely so an
  effect drawn alongside the building cannot drift from it. Read it; never
  restate the condition. Kidnapped buildings are the dead case.
- **The art gate tests the RESOLVED variant, not the family stem.**
  `variant_select.mode "level"` means variant N is the booster's GLOBAL level
  N, and a level whose art is not imported yet draws nothing rather than
  falling back to a lower one (user decision — a half-imported family should
  look half-imported).
- **`fit_tiles` stays 0 even though the art is cut 192×96 to cover the 3×3
  boost range.** With `fit_tiles == 0` the renderer centres the frame on the
  tile diamond's centre, and a 3×3 iso block's bounding diamond is exactly
  192×96 about that same point — the coverage lands with zero offset.
  `fit_tiles=3` would instead trigger `block_center_offset` and shift the blit
  by a tile, because the aura is addressed by its CENTRE tile, not a block
  min-corner.

The animation phase is offset per building by `_aura_phase_ms(col, row, total)`
— a pure hash of the TILE, deliberately not an rng draw: `self._rng` is the
shared global `random` stream, and drawing from it once per booster per FRAME
would desync every downstream roll (the argument `vfx_variants.resolve`'s
<2-variant short-circuit makes). It rides a monotonic `self._aura_clock_ms`
(the `_beam_clock_ms` shape) that never resets, because
`Manifest.current_frame` wraps modulo the track total — a forever-growing
`anim_time_ms` is exactly what loops an idle track.

## Drummer buff-range telegraph + buffed-enemy arrow (feature, very-simple placeholders)
Two new `FloaterManager` methods (`game/ui/effects.py`), both wired in
`game/main.py` beside their closest existing analog:
- **`submit_drummer_auras`** (world-overlay pass, beside `submit_craters`) — a
  pulsing ring around every ALIVE Drummer enemy, sized to its own live
  `DrummerAura.support_range` (`game/enemies/components.py`) — always
  visible while the Drummer lives, no click/toggle. Same `_polygon_ring`
  world-unit N-gon technique the mortar crater uses, but re-derives the
  radius from the live component every frame instead of a spawned
  GameObject's own fade clock — there is no separate `Crater`-style
  GameObject here, and no fade: the ring simply stops the frame the Drummer
  dies. Colour/alpha bounds/segment count are balancing (`procedural.
  drummer_aura`, `data/CLAUDE.md`), and it is deliberately NOT swappable art
  — there is no scaling-sprite-to-a-live-radius mechanism anywhere in the
  engine to reuse, so this stays procedural like the mortar crater it
  mirrors. The alpha breathes on a `pulse_period_s`-second sine cycle off a
  NEW `FloaterManager.self._clock` (seconds, accumulated in `update(dt)`) —
  the `hud.py` XP-bar level-up pulse shape, generalised to a per-manager
  clock rather than a per-screen one.
- **`submit_buff_arrows`** (HUD pass, beside `submit_enemy_hp_bars`) — a
  little golden arrow above any ALIVE enemy carrying at least one source with
  a POSITIVE `move_speed` contribution (today always a Drummer's aura, but
  keyed off the STAT, never the source type; it was gated on "`BuffState
  .sources` non-empty" until D20 gave the slows their own red twin — see the
  debuff-arrow section below for the gate that replaced it). Shown
  independently of the HP bar's own "hide at full HP" rule. Anchors off the
  SAME `hp_bar` point (or `_sprite_top` fallback) the HP bars use, offset
  above it — a deliberately SIMPLER placeholder than the HP-bar pass: it
  does not implement per-tile stacking for multiple buffed enemies sharing a
  tile, since the arrow is a status flag, not a competing bar. IS swappable
  art (E-37): a new `vfx` category slot, `vfx_buff_arrow` — imported art
  draws as a `HudSprite`; with none imported it draws a small procedural
  golden triangle outline instead (`_BUFF_ARROW_GOLD`, a code chrome
  constant beside `HP_BAR_W`/`HP_BAR_H`, not balancing — only the swappable
  ART is a designer lever here, not the placeholder's own shape/colour).

## The RED debuff arrow, and the independently-gated gold one (BossUpgradeTimelinePLAN D20)
`submit_debuff_arrows` (`effects.py`, wired in `game/main.py` immediately after
`submit_buff_arrows`) is the gold arrow's twin in `_DEBUFF_ARROW_RED`, over any
ALIVE enemy carrying an active SLOW. Same geometry constants, same
swappable-art rule (E-37) — a new `vfx` slot, `vfx_debuff_arrow`, drawing as a
`HudSprite` once imported and a small procedural red triangle until then — but
a DIFFERENT anchor from the gold arrow's (see below).
- **Gated on `buff_signs(enemy, "move_speed")`, not `buff_total`'s netted
  sign** (follow-up fix, live-tested): gold fires when ANY source contributes
  positive `move_speed`, red when ANY source contributes negative — read
  independently, not as the two signs of one summed number. An enemy
  simultaneously buffed by a Drummer AND slowed by a mortar is a real state
  and shows BOTH arrows at once; the earlier "netted aggregate, so at most
  one can ever fire" design silently hid whichever effect lost the sum (and
  hid both on an exact cancel). Keyed on the STAT, never the source — today's
  slows come from the boss upgrades `mortar_slow`/`stormpriest_slow` via
  `game.enemies.components.apply_slow` (D19), but anything that ever slows
  an enemy gets the indicator for free.
- **`submit_buff_arrows` stays NARROWED to a positive `move_speed`
  contribution** (unchanged from D20's original call): a Drummer aura that
  only lifts dmg/hp/attack_speed still shows no gold arrow.
- **The two arrows sit in genuinely different spots, not just different
  colours at one point.** `_hp_bar_rect` resolves the hp bar's own on-screen
  rectangle once; `_buff_arrow_anchor` centres the gold badge above it
  (unchanged position); `_debuff_arrow_anchor` places the red badge to its
  LEFT, vertically centred on the bar. Two independent booleans can both be
  true on one enemy now, so "no stacking offset needed — the two can't both
  fire" stopped being true; two anchors, not an offset, is what keeps them
  from overlapping each other AND the bar itself.
- **`_submit_arrow`'s procedural (no-art) triangle used to straddle its own
  anchor point** — it drew from `y` down to `y + _BUFF_ARROW_H`, while the
  anchor itself sits only `_BUFF_ARROW_GAP` (3px) clear of the bar's edge, so
  the triangle's far end landed *inside* the bar. Fixed to draw `y - H` to
  `y` (matching the sprite branch's own span) so the badge is always
  entirely on the far side of `y` from the bar, never overlapping it.
- Three small private helpers hold the shared geometry so the two arrows
  cannot drift apart: `_hp_bar_rect` (the bar's own rectangle),
  `_buff_arrow_anchor`/`_debuff_arrow_anchor` (each arrow's position off
  that rectangle), and `_submit_arrow` (the art/no-art draw branch, shared).

## Digger underground telegraph (digger-hop-rework)
The player-feedback fix that came with the Digger's stand-and-erupt-in-place +
knight-hop rework (`game/enemies/CLAUDE.md`'s Digger section): while the
Digger is submerged its sprite is fully hidden, so the existing dirt-pile
decal (`game/enemies/dirt_pile.py`) is joined by two placeholder arrows —
**both**, never a replacement for the pile. One new `FloaterManager` method,
`submit_digger_telegraphs` (`game/ui/effects.py`), wired in `game/main.py`
right after `submit_buff_arrows`, the SAME `vfx_buff_arrow`
swappable-sprite-with-procedural-fallback pattern applied to a raw WORLD
point instead of a live enemy's own screen anchor (a submerged Digger has no
sprite silhouette to anchor against, unlike a buffed enemy):
- **The entry-tile marker** (`vfx_digger_marker`) hovers over
  `BurrowAgent.start_wx`/`start_wy` — the CURRENT dig's entry point, which
  `_submerge` re-sets on every new hop, so the marker moves with the Digger
  and never stays pinned to the original spawn dig. No art imported → a small
  downward-pointing triangle (`_DIGGER_MARKER_COLOR`, a code-chrome constant
  like `_BUFF_ARROW_GOLD` — not balancing; only the swappable ART is a
  designer lever here).
- **The direction arrow** (`vfx_digger_direction`) sits just above the
  marker, rotated toward `BurrowAgent.dest_col`/`dest_row` — the segment
  currently being dug — so the player reads WHICH WAY the hidden Digger is
  heading, not just where it went under. No art imported → a triangle
  rotated via `atan2` on the projected screen-space delta between the two
  points (world → `cs.world_to_screen`, angled there — never in world space,
  since the iso projection is not angle-preserving). WITH art imported it
  draws unrotated at the anchor point — the `submit_beams` sprite-toggle's
  own accepted limitation (`HudSprite` carries no rotation support).
- Both draw ONLY while `BurrowAgent.state == BURROW_SUBMERGED` and the owner
  is alive — gone the instant it emerges, exactly like the dirt pile's own
  lifetime. Tests: `tools/tests/test_digger_telegraphs.py` (a `Digger` built
  directly with its `BurrowAgent` hand-set to the scenario under test, the
  `test_enemy_hp_bars.py`/`test_projectile_sprites.py` headless pattern — no
  Scene/TileMap simulation needed).

## Level-up UI (10A)
`game/ui/levelup.py` (`LevelupWindow`, the `game_over.py` template; it lays out on
`open` because hover/hit run before the first `submit`), an XP bar + `LVL N` in
`hud.py` (gold + pulsing when pending), purple XP floaters via
`FloaterManager.spawn_xp_events` (drained every frame, not at a phase edge), and
the gated construct list + five-mode upgrade button in `building_ui.py`. The modal
sits at the TOP of `main.py`'s click ladder and swallows keys. (The pure roll/gate
logic is `game/core` — see that doc.)
- **Designer-scripted leveling suppresses the XP readout, not the level one.**
  `Hud._submit_xp` submits `lvl_label` first, then returns early when
  `RunState.scripted_leveling` — before the `icon_xp` / `xp_bar` / `xp_text`
  submits, mirroring the `is_visible(...)` / `.visible` guards already on those
  three holders. `LVL N` stays (the village level is still a real thing); the
  bar, its icon and the `40/60` text go, because XP is not a mechanic in that
  mode. **The floaters need no change here at all** — `award_xp` no-ops
  upstream, so `xp_events` never fills and `FloaterManager.spawn_xp_events`
  drains an empty ledger. The window itself is untouched: it lays out any card
  count, which is what makes `exact_offer_slots` work — but only 4 boxes fit
  the 640px view at `_BOX_W = 130`, so the editor warns above 4 slots per row
  rather than the game clamping. Mode detail → `game/core/CLAUDE.md`.

## Boss UI (10G)
- **`boss_cutscene.py`** (`BossCutscene`) — the `levelup.py` modal template
  (construct→`open(boss_num, outcome)`→layout-on-open→update→hit→submit): opaque
  near-black backdrop, win/loss headline + "How will we react?", and — since
  **BossUpgradeTimelinePLAN BU-4** — **THREE 200×104 upgrade cards** (`box_a`/
  `box_b`/`box_c`, ids appended, the two old ones keeping their names and
  meaning) instead of 10G's two `WinA`/`WinB` narrative boxes. A card's copy is
  the catalog's own `name` + `description` for that slot
  (`boss_upgrades.milestone_slots(balance, boss_num)`), the description
  `.format()`ed with its live `params` and WRAPPED to the box (`wrap_text`,
  clamped to the height — designer prose, not a pre-broken two-liner). So the
  constructor gained a `boss_upgrades_balance` (5th param, `None`-tolerant);
  its third positional `core_balance` is UNCHANGED but no longer read, kept so
  no call site can silently mis-fill the position. `hit` returns the picked
  **upgrade id string** (or None) — NO dismiss path; it sits above
  `session.frozen` in `main.py`'s click ladder and the frozen key-gate
  swallows keys. Opened by the host on the BOSS_CUTSCENE phase edge from
  `state.pending_boss_cutscene` (the LEVELUP pattern); **a LOSS shows the
  retaliation-love headline AND the same 3 cards** (D7).
  - **An EMPTY slot draws its frame and nothing else**, and is neither
    hoverable nor clickable. That is what `screen_defaults.json` /
    `screen_previews.json` / the golden pin record, because neither
    `tools/export_ui_layouts.py` nor `tools/screen_preview.py` loads the
    `boss_upgrades` balance: which milestone a bossfight offers is RUN state,
    not screen state, and the rects a designer skins are identical either way.
- **`effects.py`** grew three fenced 10G members: `spawn_boss_events(state)`
  drains the `boss_events` announce markers (gated by
  `ui.FX.boss_announce.enabled`); `submit_announce` draws the centred two-line
  "SOMETHING BIG / IS APPROACHING!" banner over the
  `boss_announce.{fade_in,hold,fade_out}` timings (a real text-alpha fade
  since 10J; **ESV-3b**: the colour + max alpha are now
  `data/balancing/vfx.json procedural.announce`, read off
  `FloaterManager._vfx_params.announce` — the two copy strings and the
  timings stay put, screen-skinning/`ui.json` territory respectively);
  **The "YOU / LOST 1 LIFE" banner rides both of those two members** (added
  after ESV-6): `spawn_life_lost_events(state)` drains the new
  `RunState.life_lost_events` ledger (`Session.on_base_hit` appends the round
  number inside its `charge` branch, so a TU-7 waived tutorial loss announces
  nothing) into its own independent clock, `self._life_lost_age`, and
  `submit_announce` draws it as a second centred two-line banner beneath the
  boss one, in `widgets.C_HP_RED` (attribute-read, never import-bound). It
  SHARES the `ui.FX.boss_announce` fade/hold/fade timings (factored out into
  `_announce_k(age)`) but deliberately NOT the `enabled` flag — that is a
  boss-FX toggle, and a lost life must always be signposted. **Neither the
  drain nor the draw needed a new host wiring line**: `spawn_boss_events` is
  already the frame's "drain the announce ledgers" hook and calls
  `spawn_life_lost_events` itself, and `submit_announce` is already the
  frame's announce draw. No coalescing exists or is needed — `_wipe_pending`/
  `_wipe_round` end the round on the first base hit, so the ledger can hold
  at most one entry per round by construction. Covered by
  `tools/tests/test_10j_qol.py::TestLifeLostBanner`.
  `submit_boss_bars(renderer, cs, scene, phase, view_w, view_h)`
  finds the live boss via `scene.by_tag("boss")` and draws the bottom-centre
  200×12 HUD bar ("BOSS" + `hp/max`, ENEMY phase only). Its **overhead** bar is
  NOT drawn here — see the enemy HP bars below, which own every overhead bar in
  the game (the boss is tagged `"enemy"` too, so it comes along for free and can
  never double up).
- **`hud.py`**: BOSS_CUTSCENE phase label/color entries. **The "Story" income
  row is GONE (BU-4/D6)** — `income_sources` no longer calls
  `love_bonus_income` (payday's slot 3 pays nothing to mirror), and the
  tooltip's gold `Story upgrades: +N` branch went with it. Its two string ids
  (`hud.income.story` / `hud.tooltip_story`) are still in the table and
  referenced by no code, like the `hud.phase.*` ids — a string-table cleanup
  pass owns both.
- **`building_ui.py`** base_info mode: a "BOSS CHOICES" button (10H's lightning
  section sits ABOVE it) opening a centred history popup — one row per
  `state.boss_upgrade_choices` entry, `"Boss {n}: {Outcome} {name}"` with the
  picked upgrade's CATALOG NAME (BU-4; `_boss_upgrade_copy` does the same
  lookup+`params` format the cards do), the hovered row's wrapped description
  as the tooltip, "None yet" when empty, Close; the popup consumes clicks
  inside itself. It grew 170×158 → 260×182 for that copy — the height budget
  is written against `_BOSS_TIP_LINES`, so the two move together.
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
  - **`GameState.LOADING` (feature: loading screen) is the second state added
    since 9H, and it BREAKS the "full screen ⇒ `Shell`-driven" half of that
    line on purpose.** It is a real full screen (the `ui_bg_loading`
    background + a white progress ring, `game/ui/loading_screen.py`'s
    `LoadingScreen`, the `debug_settings.py` code-only-screen shape — no
    `data/ui/screens/loading.json`, no `screen_defaults.json` entry), but
    `Shell` never constructs or dispatches it: `main.py` owns `loading_screen`
    directly and drives it from the frame loop, exactly like
    `GAMEPLAY`/`GAME_OVER` (which are also full screens `Shell` doesn't own).
    The reason is that driving it needs host-only things `Shell` structurally
    cannot have — `assets` (the E-37 "is `ui_bg_loading` imported yet" check)
    and the queued `build_gameplay()` checkpoints only `main.py` knows about.
    `main.py`'s "new_game"/"new_game_debug" intents no longer call
    `build_gameplay()` synchronously; they set `shell.state =
    GameState.LOADING` and arm the checkpoint queue (`_build_gameplay_steps()`
    — `build_gameplay()` itself is now a thin wrapper that just runs every
    step in one shot, kept for the headless autostart seam and any other
    direct caller). The frame loop's `LOADING` branch runs one queued step
    per frame, submits `loading_screen` at `completed/total` progress, and —
    once the queue drains AND a minimum-duration timer (accumulated real
    frame `dt`, never `time.time()`; `ui.json LoadingScreen
    .min_display_seconds`) has also elapsed — calls `shell.enter_gameplay()`.
    Both gates matter: `build_gameplay()`'s work is genuinely fast today (no
    asset I/O happens there — everything is already loaded at boot), so
    without the duration floor the screen would flicker for a frame or two;
    without the real-checkpoint half it would be a fake spinner, not a
    progress indicator. The PRE-BOOT loading screen (`main.py`'s
    `_submit_loading_frame`, shown before the `Shell` even exists — see
    `game/CLAUDE.md`'s Host conventions section) shares the exact same
    background slot and ring style by importing them from
    `game/ui/loading_screen.py` rather than re-declaring them, so the two
    screens cannot visually drift apart; it is a SEPARATE mechanism (its own
    throwaway presenter/renderer pair, since no real window exists yet) and
    was also given more, smaller real checkpoints (15 instead of 5) so its
    ring's motion reads as smooth rather than jumpy — not an eased/faked
    animation, just finer-grained real boot sub-steps.
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
- **Controls screen (feature: rebindable hotkeys)** — `game/ui/keybinds_screen.py`
  (`KeybindsScreen`), the `debug_settings.py` code-only-screen shape: no
  `data/ui/screens/keybinds.json`, no `screen_defaults.json` entry, not in
  `tools/export_ui_layouts.py`'s `SCREEN_IDS`, row labels are plain code text.
  Reached via a new CONTROLS button on `SettingsScreen`; opened as
  `Shell.controls_open`, an overlay flag on `GameState.SETTINGS` (the
  `debug_settings_open`-on-`MAIN_MENU` pattern — reachable from exactly one
  place, so no new `GameState` member). Lists 16 of the 18
  `data/balancing/ui.json Keybindings` actions in TWO columns (16 rows in one
  column overflows the 640x360 logical surface — `_ROWS_PER_COL`)
  (`toggle_cheat_menu`/`quick_skip_combat` deliberately excluded — see
  `game/CLAUDE.md`'s Rebindable hotkeys section) with a REBIND button per row.
  `KeybindsScreen.bindings` is a plain shared dict the HOST owns (the
  `SessionSettings` precedent) — `Shell(key_bindings=...)` threads it in, and
  the screen only tracks WHICH row is armed (`capturing`); resolving a
  captured keypress (Esc cancels, a collision flashes red via
  `flash_conflict`, otherwise the binding is written + persisted to
  `scores/keybindings.json`) is `main.py`'s job, since a disk write and a raw
  `pygame.KEYDOWN` are both out of bounds for pygame-free `game/ui`.
  `main.py`'s menu `KEYDOWN` routing special-cases capture mode BEFORE
  `shell.handle_key(...)` — see `_handle_capture_key`. **A key with no
  representable binding (an arrow key, Tab, Shift, an F-key, …) flashes red
  via a sibling method, `flash_unbindable`, instead of the previous silent
  no-op** — the bug that made rebinding a WASD row to an arrow key look
  permanently stuck on "PRESS A KEY". Both flash methods share one private
  `_flash_armed_row(message)` helper; the label the flash overwrites is the
  armed row's `REBIND` button text via `start_flash`, not a separate widget.
- **Save Files screen + main-menu CONTINUE/SAVE FILES rows (SaveGamePLAN
  SG-6)** — a third menu screen joins HIGHSCORES: `GameState.SAVE_FILES`
  (`game/core/phases.py`, appended LAST, no existing ordinal moves) and
  `game/ui/save_files.py` (`SaveFilesScreen`), mirroring `highscores.py`'s
  construct -> `set_index()` -> `layout()` -> `update()` -> `hit()` shape
  exactly (scroll offset, header pinned above the viewport). It is
  CODE-ONLY like `debug_settings`/`keybinds_screen` — no
  `data/ui/screens/save_files.json`, no `screen_defaults.json` entry, not in
  `export_ui_layouts.py`'s `SCREEN_IDS`. Each row shows the save's
  timestamp and round reached, a PIN toggle, and a DELETE button. **No
  minimap** — the original design drew a live 2-color locked/unlocked grid
  off `unlocked_tiles`, but it was cut after a live-testing report (both the
  UI element and the underlying `unlocked_tiles` field, all the way back
  through the save assembly and schema — `game/CLAUDE.md`'s autosave
  section, `game/map/CLAUDE.md`'s `save_state()` section). **The timestamp
  label is reformatted for DISPLAY (user decisions — day-month-year date
  order, seconds dropped but hour:minute kept)**: `_format_timestamp`
  rewrites `created_at`'s stored `YYYY-MM-DDTHH:MM:SS` into
  `DD-MM-YYYY HH:MM` — the stored value keeps its full ISO-8601
  `timespec="seconds"` form (`game/core/savegame.py`), nothing about the
  save doc itself changed. `hit()` returns
  `"back"`, `("pin", slot_id)`, `("delete", slot_id)`, or
  `("load", slot_id)` — the `Shell` intent-string convention, executed by
  `main.py`'s `execute()` via a new `isinstance(intent, tuple)` branch.
  `Shell.set_save_index(doc)` hands down the index doc the host loaded at
  boot (and reloads after every save/delete), the `set_highscores`
  precedent.
  - **`MainMenu` gains two rows**: SAVE FILES (opens the new screen,
    unconditionally visible, the HIGHSCORES precedent) and CONTINUE (loads
    the most-recent slot directly via a new `("load_save", slot_id)`-style
    dispatch, `savegame.most_recent_slot`). **CONTINUE is HIDDEN ENTIRELY,
    never disabled, when no save exists** (explicit user decision) — a new
    `has_saves` constructor param / `set_has_saves(value)` method sets
    `visible["continue"]` in `_availability()`, on the SAME "every row's
    `visible` is set every `layout()` call, never only in a hiding branch"
    rule the debug-mode matrix already follows, so a stale `True`/`False`
    can never linger across a `set_has_saves` flip. `main.py` calls
    `set_has_saves` at boot (from the loaded save index) and again after
    every autosave and every manual delete.
  - **`layout()` was rewritten to compute the stack height from the
    VISIBLE row count, not a fixed 7-row offset.** Growing the menu to up
    to 9 possible rows (CONTINUE + SAVE FILES) would have overflowed the
    360px logical surface under the old fixed `y = view_h // 2 - 30` /
    `_GAP=4` arithmetic (tuned for exactly 7 rows). `layout()` now sums
    `stack_h` from the actually-visible rows, centers via `y = (view_h -
    stack_h) // 2`, and repositions the title/subtitle relative to the
    computed `stack_top` (`max(10, stack_top - 40)` /
    `max(28, stack_top - 20)`) instead of the old fixed offsets — so a
    7-row menu (CONTINUE hidden) and a 9-row menu (CONTINUE visible) both
    center correctly with no per-row-count special-casing.
  - **`data/ui/screens/main_menu.json`'s stale per-button `rect` overrides
    were REMOVED (live-testing bugfix — this is what "the main menu looks
    really weird" turned out to be).** That designer skinning file (10L-B)
    predates this row-count rework — its row spacing (~33-34px) matches the
    layout from before even the HIGHSCORES row existed — and
    `ScreenSkinning.apply()` reapplies its fixed positions every frame
    AFTER `layout()` computes the new dynamic centered stack. CONTINUE and
    SAVE FILES carried no override (the file predates both), so they used
    the correct dynamic position while every OTHER button froze at its
    stale spot — which is what produced the overlap (SAVE FILES landing on
    top of ADD A NAME/HIGHSCORES) and the misplacement (CONTINUE off to the
    side near the title). The fix removed every stale `rect` from that
    file's `widgets` table (keeping `backdrop`'s deliberate 4px offset and
    `subtitle`/`title`'s non-geometry keys, `skin`/`text_color`/`visible`)
    so every row — old and new — now goes through the SAME live `layout()`
    call with nothing left to disagree with it. **This file is NOT touched
    by `test_ui_skinning.py`'s golden pin** (that captures through
    `ScreenSkinning.empty()`, never the real override file), so nothing
    caught this drift automatically — a live `py game/main.py` look is what
    a screen's REAL on-disk override needs, the golden pin only covers the
    CODE-computed defaults.
  - **`data/ui/screen_defaults.json`/`screen_previews.json` and
    `test_ui_skinning.py`'s `main_menu` golden entry were regenerated on
    purpose** — the same sanctioned "geometry changed on purpose" path the
    HIGHSCORES row used. Only `main_menu` moved; every other screen's
    baseline entry is byte-identical.

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

## Building-colour swatches (MasterSheetColumnsPLAN B2)

The build-confirm modal picks the master-sheet COLOUR COLUMN a building is
placed in. Two new module-level members in `building_ui.py`, both deliberately
reusable — the upgrade panel gets the same row in B3 and **must not
re-implement either**:
- **`ColorSwatchRow(colors, left, right, top, id_prefix, ui_balance=None)`** —
  layout + hit-test + draw over `widgets.Button`, right-aligned to `right` and
  clamped to the first `(avail + GAP) // (SIZE + GAP)` colours (the registry
  schema allows 16 names; only ~8 12px swatches fit the modal's band, and
  shipped sheets declare 4). It owns **no state**: `hit(mx, my)` returns an
  INDEX or `None` and `submit(renderer, selected, anim_ms=0)` takes the
  caller's selection as an argument, which is what lets one screen point it at
  a pending int and another at a live `SpriteAnimator.column`. `ids` merges
  into the owning screen's dict BEFORE `skinning.apply`; `__bool__` is False
  when inert. `SIZE = 12` is the UR-5 click-target floor exactly.
- **`_swatch_rgb(name, ui_balance=None)`** — the ONE colour lookup, now (B3) a
  read of `data/balancing/ui.json`'s `BuildingColors` group (`name -> [r, g,
  b]`). Both screens pass the balance dict they already hold; there is no
  second table. A miss of ANY kind — no balance, no group, or a `columns` name
  the palette does not know — degrades to the neutral `widgets.C_PANEL_INSET`
  rather than raising (E-37): the swatch still exists and still picks its
  column, it just isn't tinted. The neutral is read as `widgets.<NAME>`
  attribute access, never import-bound (`configure_palette` rebinds the `C_*`
  constants at boot).
  - **`BuildingColors` is deliberately NOT in `ui.schema.json`'s root
    `required`** (it is the only optional group there). The root is
    `additionalProperties: false` with four required groups, and a fifth
    required key would redden `tools/tests/fixtures/data/balancing/ui.json`,
    which no UI change may touch. So the read is `.get("BuildingColors", {})`
    and absence is a supported state — which is exactly what the fixture
    exercises. Its four names (`pink`/`purple`/`red`/`yellow`) are fixed schema
    properties, not an open map, so the editor's balancing panel renders them
    by recursing the schema with no editor code at all; growing the palette is
    a one-line schema edit through `/add-balancing-value`.

## Upgrade-panel colour swatches (MasterSheetColumnsPLAN B3)

The upgrade panel grows the SAME `ColorSwatchRow`, pointed at the live
building instead of a pending int — `BuildingUI.colour_row`, built by
`_build_colour_row()` at the tail of `_build_upgrade` (after `_build_move_btn`)
and swept by `_clear_colour_ids()` (the `_clear_card_ids` prefix rule, also
called from `close()`), ids `upgrade_swatch_0…`.

- **The D6 gate**: upgrade mode, SINGLE selection (the `move_btn` rule — a
  batch recolour is not a feature), a host-wired `colour_columns` map, and
  `>= 2` colours for the building's LIVE `BuildingSprite.slot_key` (the key the
  host's map is built on, and `None` on the base, which has no animator).
  Anything else leaves the row inert: no row, no gap, no placeholder, no ids,
  never a raise. **A fifth, unconditional gate (feature: boost buildings
  excluded from colour): `"boost" in b.tags` returns before any of the above
  are even checked** — a booster never gets a row, whatever its sheet
  declares, matching `ConstructPreview`'s identical tag check and
  `registry.place_building`'s guard on the roll itself
  (`game/buildings/CLAUDE.md`).
- **Clicking swatch `i` writes `i` onto `BuildingSprite.column`** — the field
  the renderer reads, so the board recolours next frame with no confirm step,
  nothing spent, nothing logged; it survives later upgrades for free because
  `apply_tier_stats` rewrites only `slot_key`. The hit test sits after the
  rename defocus (a swatch click commits an in-progress rename, like a move
  click) and before `move_btn`. `-1` is the "no driver" sentinel and `0` is a
  REAL colour, so the ring test is `_selected_column()`'s `>= 0`, never
  truthiness.
- **The band is dead space, so nothing moves.** All of it derives from
  `action_btn.rect`: the row is `y 282..293` (12px, the UR-5 floor exactly),
  6px above the action button's `y = 300` top and 14px below the stat column's
  268 worst case; `action_btn`, `move_btn`, the stat rows and the hint keep
  their exact rects. That is why `py tools/export_ui_layouts.py` was a **no-op
  diff** and `test_ui_skinning.py`'s `building_panel` baseline needed no edit.
- **The swatches are not in `screen_defaults.json` at all**, and the golden pin
  does not cover them: the exporter's mock builds a real building but wires no
  capability map, so the "no map ⇒ no colours ⇒ no row" path runs there. That
  is deliberate — dynamic-count content is styled through
  `ScreenSkinning.defaults()`, and an id absent from the defaults file is
  harmless (`_validate_ids` only fails on an override naming an id the code
  does not know). `tools/screen_mocks.py` is untouched on purpose: it is the
  ONE mock state shared by `screen_defaults.json` and `screen_previews.json`.

Rules this section fixes:
- **`0` is a real colour index; `-1` is the "no driver" sentinel.** Nothing
  here may truth-test a column — `is not None`, always. A slot with fewer than
  2 colours builds no widgets at all, registers no ids, draws nothing, and
  leaves `chosen_column = None` so `place_building` keeps the sentinel.
- **The preview may not lie.** `ConstructPreview.__init__` ROLLS the initial
  index (`random.randrange`, the same stdlib module the name dice already
  uses — no rng seam threaded through the UI) and `_do_place` always passes it
  as `place_building(..., column=)`, so confirming without touching a swatch
  places exactly the colour shown.
- **The capability map is the HOST's.** `game/main.py`'s
  `_derive_colour_columns` builds `{slot_key: (colour_name, …)}` once at boot
  and assigns `panel.colour_columns` — the `panel.assets` /
  `overlays.condition_art` precedent. `BuildingUI.__init__` defaults it to
  `{}`, so a bare panel in a test or tool has no colours and is unchanged.
  `game/ui` never reaches into the asset layer (D6/E-37).
- **Nothing already on the modal moved.** The row is `y+36..y+47`: 1px under
  the cost line, exactly abutting the `y+48` name box, entirely above the
  `y+69` stat list — so `data/ui/screen_defaults.json` needs no regeneration
  and the stat list's 2px slack is untouched. It is hit-tested BEFORE
  `handle_click`'s `name_rect` branch (a plain containment test, the broadest
  one) and drawn inside `submit`'s BUTTON block, its selection ring right
  after its own swatch (the sanctioned "ring after its own button" exception).
- **Booster buildings are excluded from colour entirely** (feature: boost
  buildings excluded from colour). `ConstructPreview.__init__` skips the
  `building_colors` lookup outright when `"boost" in temp.tags` (a booster,
  `game/buildings/boost.py`'s `EXTRA_TAGS`) — `colors` is forced to `()`
  regardless of what the building's master sheet declares, so no swatch row is
  ever built, `chosen_column` stays `None`, and `place_building` never sees an
  explicit `column` for one (`game/buildings/CLAUDE.md`'s matching guard on
  the roll side is the actual enforcement; this is what keeps a player from
  ever seeing a swatch that would do nothing).

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
  relocates): display name, ONE `Cost` line quoting ROUNDS (`Instant` at
  zero — feature: move-building-time-only-cost merged the old separate
  Cost-in-love/Time-in-rounds pair into this single line, since moving a
  building spends no love any more), destination coords, CONFIRM/CANCEL.
  `self.cost` (the love figure, always 0) is still carried and still what
  `total_cost`/`_do_move`'s affordability check reads — only the SEPARATE
  love-cost text line is gone. **The Cost line draws in `C_MOVE_HIGHLIGHT`
  (the same cyan the destination path-line preview uses), never the
  love-gold `C_GOLD` every OTHER preview's cost line uses** — the deliberate
  visual signal that this number is a round count, not a currency figure. It
  reuses the SAME `ui.Timing.construct_show_cancel`/`confirm_on_right_side`
  chrome keys and the SAME `preview_*` id namespace, and mirrors
  `ConstructPreview`'s public surface (`hover`/`confirm_hovered`/`update`/
  `handle_click`/`handle_key`/`submit` + `confirm_btn`) closely enough that
  `main.py`'s existing `panel.preview is not None` modal branch drives it
  with **no preview-class-specific code**. Two places in THIS module branch
  on `isinstance(self.preview, MovePreview)`: `_preview_click` (routes
  CONFIRM to `_do_move` instead of `_do_place`), and `BuildingUI.hover` —
  every other preview's hovered CONFIRM sets `self._hover_cost` to preview a
  love spend on the HUD's top-left pill (`hud.py`'s `submit(...,
  hover_cost=)`); a `MovePreview`'s CONFIRM is explicitly excluded from that,
  since its cost is rounds, not love, and the pill must draw exactly as if
  nothing were hovered.
  - **The "will miss combat" warning (feature: move-building-time-only-cost)**
    — a red `BuildingsGlobal.Movement.warning_text` line below the
    destination coords, present only when `rounds > 0` (an instant, 0-round
    move skips it — nothing is missed) and the balancing string is non-blank.
    Wrapped at CONSTRUCT time via `wrap_text(..., "sm", pw - 16,
    max_lines=3)` into `self._warning_lines`, which is what the panel's
    height (`ph`) grows to fit — geometry is still fixed for the instance's
    whole lifetime (10L-B), just computed from the actual wrapped line count
    instead of a bare literal. It is dynamic designer content with no stored
    id (the `ConstructPreview` stat-list/`levelup` explanation precedent), so
    it is wrapped at construct time rather than draw time without tripping
    the "layout_h, never a live font measurement" rule above — that rule
    guards content the golden `screen_defaults.json`/`screen_previews.json`
    capture, and this line is captured by neither.
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
- **The path line (building-move-manhattan-distance fix)**: once a
  destination tile is picked (i.e. `self.preview` is a `MovePreview`),
  `BuildingUI.submit()` draws an L-shaped cyan (`widgets.C_MOVE_HIGHLIGHT`)
  world-space line from the building's tile centre to the destination's —
  column-first, then row, matching the straight-line-only tiles
  `move_distance()` counts (`game/buildings/CLAUDE.md`). It is NOT a live
  mouse-hover trace: nothing is drawn during plain `move_select` picking,
  only once a destination has actually been chosen and the confirm modal is
  open. It sits beside `_highlight_tiles`/`_highlight_edges`, before the
  `self.visible` guard, and reads `self.preview.building`/`.dest_tile`
  straight off the live preview object every frame rather than caching
  separate state — it disappears for free the instant `self.preview` is
  cleared (confirm, cancel, or close all already do that).

## Map overlays + terrain badges (10I)
`game/ui/overlays.py` (`MapOverlays`, pure — covered by the purity scan) owns
ALL of 10I's UI so `hud.py` (10G boss bar + 10H lightning both edit it) carries
no 10I diff: **three** persistent bottom-left toggle pills
(`RANGE`/`HEATMAP`/`TIER OVERVIEW` — the third added later, see its own section
below; gold rim + gold label when active; clicks consumed in `main.py`'s ladder
between the End-Turn branch and the panel, `over()` feeds the pan-arming
`over_ui` check),
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
`building_ui`'s terrain CARDS. There is no `Terrain: <Label>` badge any more
and no hover anywhere on this panel: unlock, construct and upgrade each draw
terrain cards (below), whose effect rows read LIVE from
`TileConditions.modifiers` (enemy effects deliberately unlisted,
prototype-exact). `base_info` names no terrain at all. The panel Range row + selection range highlight use
`effective_range_tiles()` when present (mountain +1); the RANGE overlay stays
raw.

### Terrain cards + the terrain box as WIDGETS (unlock-screen rework)

**Unlock mode lists the terrain the purchase covers.** `_build_cond_cards`
emits one card per **distinct** `TileCondition` across every 2x2 chunk in the
selection — not just the primary tile's chunk, because a shift multi-select
buys them all — each carrying the condition's own terrain art, its name, how
many bought tiles have it, and its effect lines. `_cond_card_rows` does the
dedupe in `TileCondition` declaration order (never scan order) and keeps the
first NON-`None` `condition_slot` it sees: a chunk straddling BACKGROUND or
SPAWNING has tiles with no art at all, and the card should show the art of a
sibling that has it rather than nothing.

This is the SECOND dynamic-count family on this panel, and it follows the
construct card's contract exactly (see "A construct card is a widget TREE"):
COUNT is dynamic, KEY is stable, so every part of every card is individually
overridable — `cond_card_<condition>` plus `_sprite`, `_name`, `_count` and
`_effect_<i>`. `_clear_cond_card_ids` sweeps the one prefix. `screen_mocks.
_all_conditions_chunk` forces all four conditions onto the exporter's mock
chunk for the same reason `_unlock_every_type` unlocks every building type:
a card with no `screen_defaults.json` record is invisible to the editor.

**Construct and upgrade mode show a terrain CARD too** (feature:
construct-terrain-card). Both used to end in the badge pill plus an effect box
that only appeared while the cursor was over it; both draw the same card
unlock mode draws, at the panel foot, with nothing hover-gated — the effect
rows are part of the card, so the info is simply on screen. Each mode builder
calls its `_build_*_cond_cards` where it used to call `_layout_cond_box`, and
each `_submit_*` draws the card where it drew the badge.

`_layout_cond_card_list` is the ONE card layout all three share; they differ
only in their GROUP and their id PREFIX:

| mode | group | card ids | rows from |
|---|---|---|---|
| unlock | `terrain_card_list` | `cond_card_<condition>` | `_cond_card_rows` (every 2x2 chunk bought) |
| construct | `build_terrain_card_list` | `build_cond_card_<condition>` | `_construct_cond_rows` (the SELECTED tiles) |
| upgrade | `upgrade_terrain_card_list` | `upgrade_cond_card_<condition>` | `_upgrade_cond_rows` (the building's `_tile_condition` snapshot) |

Three id families rather than one, because **an override is per-ID, not
per-view** — `skinning.apply` walks a single `widgets` table for the whole
screen. Sharing the ids would pin every mode's card to wherever the unlock
LIST put it and make them impossible to place apart. The trees are otherwise
identical, so art authored for one reads the same in the others. Each family
has its own `_clear_*_cond_card_ids` sweep; `screen_mocks` re-drives the
construct and upgrade builders with all four condition rows (rather than
SELECTING four tiles, which would quadruple the batch price every recorded
construct id is derived from) so every tree reaches `screen_defaults.json`,
and `export_ui_layouts._CARD_TREE_ROOTS` maps each prefix to its group so the
editor shows one movable branch per mode.

**The badge is DELETED, not merely unused.** `cond_badge` /
`cond_badge_text` / `cond_effect_box` / `cond_effect_line_<i>`,
`_layout_cond_box`, `_submit_cond_badge`, `_submit_cond_tooltip` and the
`_cond_hover` / `_cond_badge_rect` / `_cond_tooltip` state are all gone, along
with the panel's ONLY hover probe. Leaving them as widgets no mode draws is
not free: an id in no view gets no `screen_defaults.json` record, and the
override validator then rejects any authored override that names it.

**The two effect rows are a PAIR: a name and a number.** `_COND_EFFECT_LINES`
is **2**, and the two rows are not a list — row 0 names the effect (`Range`),
row 1 carries its value (`+1`). Each is its own widget
(`cond_effect_line_0`/`_1`, `cond_card_<condition>_effect_0`/`_1`) so a
designer can place the name and the number independently, side by side or
stacked; that is the same split the per-stat `stat_<key>_label`/`_value`
widgets use. `_tile_cond_effect_lines` returns exactly that pair, and
`_cond_effect_rows` only pads/caps it to the reserved count.

**Nothing wraps any more, and there is no row budget.** This replaces five
rows of full sentences (`+1 range for defenders`) written for a tooltip that
grew to fit them — 188px of copy against 112px of box, so they wrapped at
DRAW while the HEIGHT had to be budgeted at 2 rows per line to stay off a live
font measurement. Both halves are short by construction now, so the same list
drives the build-time row count and the drawn text with no measurement between
them. Only the FIRST effect a condition carries is reported; every condition
has exactly one today, and `map.json` ships modifiers for two conditions at
all. A second effect on one condition needs a second PAIR of rows, not a
longer list.

**A card is sized to its sprite, never the sprite to the card.** `HudSprite`
STRETCHES a frame to whatever box it is given, so any box that is not the
frame's own size distorts the art. `_cond_sprite_size` asks the asset store
for `frame_size(slot)` and the card is built around the answer: 64x96 for a
condition, 64x32 for the plain ground tile grass falls back to, making a card
138px or 74px tall. A frame
size is committed DATA (`asset_manifest.json`), not a font metric — platform-
deterministic, so it may reach a stored rect. **The exporter therefore needs
an asset store too** (`screen_mocks.build_asset_store`, metadata-only — no PNG
is ever opened and `sprites_dir` is deliberately unset), or its recorded rects
would use the fallback and the editor's boxes would disagree with the game.

*Consequence:* four full-size cards are ~500px of content in a 242px list, so
the terrain list REALLY scrolls (`handle_scroll` serves unlock mode too, by
list INDEX since the cards have variable height). Its clamp reads
`_cond_row_count`, the full row count — **not** `len(self._cond_cards)`, which
holds only the cards from the current offset down, so clamping against it
shrank the limit as you scrolled and a scroll past the end walked backwards.

**A card draws exactly ONE sprite, at the `_sprite` id.** There is no ground
composite: a card used to blit `_CARD_GROUND_SLOT` (`tile_buildable`) and then
its condition art over it, in the same order the board draws its `ground` and
`terrain` layers — but that gave grass a full-size ground tile where every
other card showed a condition thumbnail, and a designer's per-card size/position
override reached only the overlay. The `_ground` sibling widget is **deleted**;
`_cond_tile_rect` places the one sprite at its own frame size, centred in the
card's inner width.

`_CARD_GROUND_SLOT` survives as the FALLBACK PREVIEW, resolved in `_cond_slot`
rather than drawn as a second layer. GRASS always answers it — grass is the
absence of a condition and its `cond_grass_*` slot ships without art anyway
(the world's own emitter skips it for the same reason) — and so does an
UN-IMPORTED condition slot, rather than blitting the engine's grey X (E-37).
`_has_art` uses the same `animation_total_ms(..., "idle") is not None` probe
`_card_portrait_slot` does, so the two cannot disagree about what "imported"
means; that is the card's analogue of the map falling back to its colour
diamond. `_cond_card_rows` keeps scanning a chunk past a ground answer, so a
chunk straddling a BACKGROUND/SPAWNING tile still shows a sibling's real
terrain.

Consequence for `skinning`: `cond_card_grass_sprite` and
`cond_card_mountain_sprite` are now the same KIND of widget showing the same
kind of art, so one authored box downsizes and positions every card's preview
identically.

Because the export mock's `TileMap` has no registry, `screen_mocks.
_all_conditions_chunk` resolves the four slots itself — at COMBAT for every
tile, not at the tile's own state, since a 2x2 chunk on the pinned map
straddles BACKGROUND (no condition art by rule) and two of the four cards
would otherwise be recorded as bare ground and understate their height.

### The two card GROUPS are containers (`construct_card_list`, `terrain_card_list`)

Both dynamic-count families hang off an id'd container of their own rather
than off `panel`, so a designer can shift or resize a whole list in one drag —
and the exporter records the container as each card's PARENT, so the editor's
widget tree shows one movable branch instead of N roots beside `panel`.

`_list_rect(list_id, holder)` is the single read: the authored rect if there
is one, else the holder's code default. It goes through `skinning.widget_rect`
rather than the holder, because a list builder runs BEFORE `skinning.apply`
has written the override onto it — the same reason `_card_column` used to read
`panel` that way. `_card_column` / `_card_list_viewport` (construct) and
`_cond_card_column` / `_cond_card_viewport` (terrain) all derive from it, so
shrinking a group re-windows its list instead of letting cards spill out.

A container **draws only once it carries a `skin`** (`_submit_list_group`).
Unskinned it is pure layout, which keeps the shipped screen byte-identical to
before the groups existed — the golden-parity contract — while letting a
designer give a list a real backdrop, drawn behind its cards because it is
submitted first.

## TIERS pill (`btn_tier_overview`)
The third `MapOverlays` toggle pill, added after 10I, sitting beside RANGE
(x=6) and HEAT (x=51) at **x=96** on the same `view_h - 36` row. **All three
pills are 41 wide**, same 4px gap, which is what makes them read as one
control group. Its label was `"TIER OVERVIEW"` in a specially-widened 69→76px
pill until the label-fit check started measuring the shipped face (above):
that copy needs 89px there, so it became `"TIERS"` (36px) and the pill came
back down to the shared 41. The **widget id is unchanged** —
`btn_tier_overview` is the on-disk contract in
`data/ui/screens/overlays.json`. Active ⇒ every PLAYER-BUILT building's tile gets one
alpha-filled diamond tinted by its current IN-TIER level.
- **No mutual exclusion, anywhere.** `show_tier_overview` is a plain third
  flag beside `show_range`/`show_heatmap`, and `submit()` runs its pass as an
  independent `if` after the heatmap's. It composes with Heatmap, Range, the
  selection/drag-select highlights and the Upgrade UI by construction — there
  is no "active overlay" concept in this class to be exclusive about. Its pass
  is drawn LAST of the three, so a tier tint reads on top of a range square.
- **Keyed by LEVEL WITHIN THE CURRENT TIER, not by the tier itself** — a
  designer decision made after live playtesting (an earlier per-TIER colour
  design, one colour per `TierState.current_tier`, was rejected: the
  playtester's expectation was that the 3-colour cycle should RESET at every
  tier advance, so a level-1 Slinger, tier 2, reads identically to a level-1
  Stone Thrower, tier 1 — both gold — rather than getting its own "tier 2"
  colour). Resolved by the module-private `_level_color(level_in_tier)` off
  `TierState.current_level_in_tier` (1-indexed) — a FUNCTION, not a
  module-level tuple, because every `widgets.C_*` must be a fresh attribute
  read (see "Fonts + palette are DATA now"). It clamps to the last entry, so
  a future 4th level renders rather than raising. **Colours are
  designer-picked yellow / pink / blue** (level 1/2/3) — two same-hue ramps
  were tried and rejected first (a purple shade ramp read as
  indistinguishable grey; a red/gold/green ramp still wasn't distinct
  enough), so the final trio is three maximally-different hues instead of a
  ramp. Neither pink nor blue exists in the shared `widgets.C_*` palette:
  level 1 is `C_GOLD` (a real yellow), level 2 reuses `C_PURPLE` (the closest
  existing colour to pink), level 3 reuses the POND entry of this same
  file's `_COND_TINT` dict (the only blue anywhere here) rather than
  inventing new, unreused colours. `_COND_TINT` is a plain
  prototype-verbatim module dict, never rebound by `configure_palette` —
  indexing it directly carries none of the early-binding risk a
  `widgets.C_*` copy would. `_TIER_OVERVIEW_ALPHA` (110) is a plain int and
  is therefore safe as a module constant.
- **The base is tag-gated out, not component-gated out.** `BaseBuilding` DOES
  carry a `TierState` (`base_building.py`), and its tile is BUILT, so
  `get_component(TierState) is None` would NOT skip it — the pass skips any
  occupant carrying the `"base"` tag (G-3 tag discipline, never a
  `building_type == "base"` string test). The `None`-occupant and
  `None`-component guards stay as well, so an odd occupant can never raise.
- **`game.ui -> game.buildings.components` is the sanctioned read**
  (`building_ui.py`/`effects.py` already import it; `game.buildings` imports
  no `game.ui`, so there is no cycle).
- **Cost profile**: `tilemap.built_tiles()` is the `_by_state` index, i.e.
  O(built tiles) — never a full-map per-frame scan (the large-map invariant).
- **Label**: `"TIER OVERVIEW"` is the code-owned default exactly like
  `"RANGE"`/`"HEATMAP"`; giving the button the `btn_tier_overview` id is what
  makes it JSON-overridable, through the generic per-widget `label` override
  (no schema change — `ui_screen.schema.json`'s `widgets.<id>.label` is
  already free-form).
- **Artifacts**: `data/ui/screen_defaults.json` was regenerated (`py
  tools/export_ui_layouts.py`) — ONLY the `overlays` entry moved (a new
  `btn_tier_overview` row + its `mock_note`), which is what says the change
  was contained; `data/ui/screens/overlays.json` gained the matching
  `ui_button_pill` skin. `test_ui_skinning.py`'s golden `_BASELINE` needed NO
  change — it pins the original 12 screens and has never covered `overlays`.
  Tests: `tools/tests/test_map_overlays.py`.

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
  **fix/batch-tier-advance, reworked into a two-stage catch-up-then-advance
  flow: a multi-selection's UPGRADE/ADVANCE button is now ONE unified path**,
  replacing what used to be two separate behaviors (a plain in-tier batch,
  and a separate combined advance batch that won outright the moment any
  selected building was advance-eligible). Priority in both
  `_build_upgrade` and `_upgrade_click`: **Stage A** —
  `_batch_upgrade_targets` sweeps the WHOLE selection (not gated on the
  primary tile's own mode, unlike before) for every building below level 3
  of its current tier; whenever that set is non-empty the button shows
  `"UPGRADE ×n  <cost>"` and a click levels each of them up one step, one
  combined cost. **Stage B** only runs once Stage A's sweep is empty — i.e.
  every selected building has already reached level 3 — and is exactly the
  old advance-batch logic: `_batch_advance_targets`
  (`game.core.levelup.advance_batch_plan`) sweeps for every building whose
  next tier is reachable right now, and `_build_upgrade` shows ONE combined
  `"ADVANCE ×n  <cost>"` button. Clicking it, for each target: pays and
  applies any remaining in-tier `upgrade()` calls needed to reach this
  tier's max level (always 0 by the time Stage B runs, since Stage A already
  drained them), then one `advance_tier()`, then
  `lightning.sync_level_from_tier` — all gated by ONE all-or-nothing total
  (no partial batch, same "NOT ENOUGH LOVE" flash the in-tier batch uses). A
  building that can never reach its next tier right now (already at the
  final tier, next tier unresearched, or round-gated) is excluded from
  Stage B's batch/cost entirely and left sitting at level 3, untouched — it
  never blocks the rest of the selection. **This closes the old grey-out
  bug**: previously, the plain in-tier batch only fired when the *primary*
  selected tile's own mode was `"in_tier"`, so a primary that was itself
  blocked (tier maxed but unresearched, or at its final tier) disabled the
  whole button even when other selected buildings still needed and could
  take a plain upgrade; Stage A's whole-selection sweep fixes that by
  construction. **A single selection is unaffected**: both
  `_batch_upgrade_targets` and `_batch_advance_targets` are only consulted
  when `len(selected_tiles) > 1`, so one selected building still
  upgrades/advances one step at a time via the original primary-only
  branches in `_build_upgrade`/`_upgrade_click`, byte-identical to before
  this rework.
- **The name field is a WIDGET on both screens** (rename-box-widgets). The
  upgrade panel's rename box is `upgrade_name_box` and the construct modal's
  is `preview_name_box` — `panel`-kind holders drawn through `submit_panel`,
  so a designer can move, resize, skin, tint or hide either. Skinless they
  emit the same fill + 1px border pair they always did (golden parity), and
  the border COLOUR stays code-owned: it is the focus ring
  (`highlight_color("tile_selected")` while typing), not decoration.
  **The rect drives the hit test, not just the draw**: `BuildingUI
  ._name_box_rect` is a property reading the holder, and `ConstructPreview`
  reads `self.name_rect` back off it after `apply()` (beside the existing
  `self.rect = self._panel.rect`), so a moved box is typed into where it is
  drawn. A hidden box refuses focus (`is_visible` gates the click too).
  The modal's four texts became id'd labels in the same pass —
  `preview_title` (the master name, `text=`: a live tier/batch name),
  `preview_cost`, `preview_name_label` and `preview_name` (placeholder
  `text_id`, typed buffer via `text=`) — the last un-id'd copy on that
  screen. `screen_defaults.json` gained six records and NOTHING moved;
  `screen_previews.json` is byte-identical, which is what says the
  conversion was a rendering no-op.
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
  plus the last-round outcome tag on the `died_last_round` widget: red **DIED
  LAST ROUND** when `RoundStats.dmg_taken_last_round >= max_hp()`, green
  **SURVIVED LAST ROUND** otherwise (one holder, two string ids, chosen with
  `submit_label(text=…)`; the row is always drawn, so the layout never gates
  its height on the outcome).
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
  about "imported". **feat-projectile-variant-select gave it a `triggers.
  projectile` row after all** — but a CONTINUOUS one, the seven VA-5 tile
  highlights' shape rather than `_play`'s: the row contributes ONLY
  `variant_select`, so `sprite_slot` (the stone/shell choice is the shot's
  own kind, and those two slots are independent by design), `procedural`
  (the fallback is the `procedural.projectile` dot right here, not a
  one-shot kind) and `draw_in_front` (this function emits on the HUD pass,
  which has no depth sort) are all INERT on it and say so in the schema.
  A row was the right home anyway because the VFX panel's Binding strip is
  generated from `vfx.schema.json`'s `triggers` properties
  (`editor/panels/vfx_preview.py::_trigger_events`), so a schema property
  buys the whole Event/Pick-mode/misc-key UI with zero editor code.
  **The resolve is CACHED on the projectile GameObject** (`p._vfx_slot`, an
  E-11 underscore transient) by `_projectile_slot`, because this function
  runs every frame for every live shot: resolving inline would re-roll
  `"random"` per frame (a bullet flickering through its flight) and draw
  from the shared `self._rng` once per projectile per frame. `"level"` mode
  needs no new plumbing — both projectile components already retain the
  firing building as `_shooter`, and `vfx_variants.source_level` reads that
  building's GLOBAL `Building.level`, so variant N is level N straight
  across the tier boundary.
  **Imported bullet art draws at `assets.frame_size(slot)`, NOT at
  `stone_size`/`shell_size`.** Those two tunables describe the procedural
  FALLBACK DOT and were tuned for it; the sprite path reused them and so
  silently halved every imported 64×64 bullet to 32 px (found live). This is
  the same `assets.frame_size` sizing `submit_beams` uses for an imported
  `vfx_beam`, for the same reason — no new balancing key for a size the
  manifest already states. The dot keeps its own tunables.
  Honouring `draw_in_front` would mean moving every bullet off
  the HUD pass onto `submit_world_fill`; that changes how every shot in the
  game depth-sorts against buildings and is deliberately NOT done here.
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
    `spawn_painter_events`/`spawn_boost_events` — the first, third and
    fourth are since SUPERSEDED by `begin_payout`, the payout-phase-
    sequencing feature above; `spawn_xp_events` is untouched) now read
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
customization" below).

**…except a `Button`, which runs its OWN state clock** (fix: hover/pressed
rows never played). Every shipped `ui_button*` sheet's `hover`/`pressed` rows
are `loop_count: 1`, i.e. play-once, and a free-running screen clock hands
them a time long past their end — so the row was only ever seen on its LAST
frame and the animation looked like it never fired. `Button.update(dt)` now
keeps `_anim_t`, RESTARTED whenever `_state()` changes, and `submit` feeds
that to the `HudSprite` instead of the caller's `anim_ms=` — which is still
the fallback for a button nothing ticks (a bare test/tool one), so no call
site changed. **A button must therefore be `update(dt)`-ed to animate**;
`enemy_intro`'s close X was the one that never was, and now is.

**A refused click plays its press first.** `start_flash` (NOT ENOUGH LOVE /
CANNOT MOVE THERE) used to cut straight to red mid-`pressed`-row, so the
button read as flashing out of `idle`. It now holds the flash for whatever is
LEFT of that row — `_state()` still resolves to `pressed` during the hold,
`flash_showing` (not `flash > 0`) is what turns the fill red and swaps in the
flash label, and the flash's own duration starts only afterward. The row's
LENGTH comes from `widgets.set_skin_anim_length(fn)`, the `set_skin_hit_test`
seam's sibling wired in `game/main.py` to `AssetStore.animation_total_ms`
(`game/ui` may not reach the asset layer itself). Unskinned buttons, skins
with no `pressed` row and an un-wired seam all answer 0 and flash
immediately, exactly as before. `levelup.py`/`boss_cutscene.py` own no `widgets.Button`
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

- **Per-widget `layers` (UL-4)**: a widget's override may carry a `layers`
  array (`data/ui/screens/<id>.json` ONLY — never `screen_defaults.json`), each
  entry an OFFSET `[dx, dy, w, h]` from its owner's post-override rect (`0`
  w/h inherits the owner's), resolved by the pure `engine/ui_layers.py`. Every
  screen's `submit()` calls `self.skinning.submit_layers(renderer,
  self.screen_id, self.ids, band, self.skinning.state_of)` **exactly twice** —
  `"under"` as early as possible (right after `submit_background`, but after
  any `ids`-building or nothing-to-draw guard) and `"over"` as the LAST
  statement. The HUD pass has no depth sort, so an `under` layer sits behind
  EVERYTHING on that screen, not just behind its own owner: that is the
  documented trade-off of two bands per screen, not a bug — the editor says so
  in plain English on both band controls: *"Under layers sit behind EVERYTHING
  on this screen, not just behind their owner widget. Use Over for backgrounds
  between stacked panels."* `z` orders layers within a band. A layer picks ONE role, first match wins: `slot` → `HudSprite`,
  else `text_id`/`label` → `HudText` (through `strings.T`, empty string draws
  nothing), else `color` → `HudRect`, else nothing. **No `layers` authored ⇒
  ZERO primitives**, which is what keeps the golden parity pin byte-identical.
  `state_of(widget)` is the per-widget draw state passed BY REFERENCE (a bound
  method, never a hardcoded `"idle"` at a call site): a `Button` answers
  through its own `_state()`; every other widget (a plain `SimpleNamespace`/
  label holder with no state machine) always resolves to `"idle"`.

- **Per-state appearance, layer and owner (UL-5)**: a `layers` entry, and a
  widget's own override object, may each carry a `states` object keyed
  `idle`/`hover`/`pressed`/`disabled` (D9's existing four-state vocabulary —
  no new one), each value a PARTIAL PATCH of the same appearance keys as its
  owner, plus its own `offset`. Fallback: `states[state]` if that KEY IS
  PRESENT (even an empty `{}` patch counts — "this state looks like the
  base"), else `states["idle"]` if present, else no patch at all — presence
  drives the fallback, not truthiness. A patch's `offset` REPLACES the base
  offset for that resolution when 4 elements are given; a 2-element `[dx, dy]`
  form moves without resizing (keeps the base offset's w/h). `engine/
  ui_layers.py::resolve(layer_spec, owner_rect, state)` applies this for a
  LAYER; `game/ui/widgets.py`'s own `_state_patch`/`_state_offset` apply the
  identical ladder for the OWNER — `Button.submit` patches `text_color` and
  nudges the DRAW position only (never mutates `self.rect`, so next-frame
  hit-testing is untouched), and an explicit `text_color=`/`color=` kwarg at
  the call site still wins over the patch (a caller passing one is more
  specific than the screen doc). `submit_label` mirrors this for a non-Button
  holder, but since `state_of` always resolves such a holder to `"idle"`, only
  `states.idle` is ever reachable there today — `hover`/`pressed`/`disabled`
  on a label/panel/backdrop are validated by the schema but dead code (no
  hover/press tracking exists for non-Button widgets). **No `states` key ⇒
  identical output for every state**, preserving the golden parity pin.

- **Clickable layers (UL-10)**: a `layers` entry may carry `clickable: bool`
  and `target: str`, which turn that layer into a real click target.
  `game/ui/skinning.py::hit_layer(ids, widgets_spec, mx, my, state_of,
  actions)` is the click-path twin of `submit_layers`: it asks the pure
  `engine.ui_layers.hit` which clickable layer a point lands on and maps its
  `target` onto an ACTION VALUE. **It is PURE** — that is load-bearing, not
  style: `main.py` calls `Hud.hit()` twice per click (the MOUSEBUTTONDOWN
  pan-arming probe, then MOUSEBUTTONUP), the same reason the drag-select
  toggle is a pure read.
  - **Resolution, in order**: `target` is one of the three reserved tokens
    `close_window`/`back`/`noop` → returned verbatim for the caller to route;
    `target` names another widget id in the SAME screen → that widget's own
    action (a **retarget**); anything else, missing target included →
    `"noop"`. A layer with `clickable` falsy is transparent — the click falls
    through to the widget under it, which is every shipped screen today (D5).
  - **A dead target SWALLOWS the click; it never falls through.** A
    fall-through would make a typo'd target behave exactly as if the layer
    were never clickable, silently unmaking what the designer configured. A
    swallowed click reads honestly as "this decal does nothing" — the same
    thing `noop` means.
  - **The retarget table is each screen's OWN action table, reversed** —
    `hud.Hud._LAYER_ACTIONS`, `pause._ACTION_IDS`, `main_menu`'s
    `_SLOT_IDS`/`self.actions`, `cheat_menu._ACTION_IDS`. Never hand-roll a
    second copy: the whole point is that a layer targeting `btn_end_turn`
    cannot disagree with what clicking End Turn does.
  - **Which screens are wired.** `Hud.hit` (after the `_panel_open` guard),
    `BuildingUI.handle_click` (after the explicit close, before the mode
    dispatch — reserved tokens only there, since its contract is
    bool-consumed and it has no flat action table across its three classes),
    and the eleven `hit()`-returns-an-action-string menu screens. **Three are
    deliberately NOT wired**: `levelup.py` returns an option DICT,
    `enemy_intro.py` a BOOL, and `boss_cutscene.py`'s `"A"`/`"B"` goes
    straight into `session.resolve_boss_cutscene` — an action STRING from any
    of the three would be a type/contract violation at the host, not a
    routed click. Wiring one means giving it a safe host branch first.
  - Where a branch MUTATES inside `hit()` (`settings.py`'s display-mode
    arrows and FX toggles, `cheat_menu`'s round-field commit), that widget is
    left OUT of the retarget table on purpose — returning its action string
    from `hit_layer` would report a change that never happened, so a layer
    aimed at it swallows instead.
  - **`engine.ui_layers.hit(layers, owner_rect, mx, my, state="idle")` is the
    pure resolver underneath** (UL-9, D8). It searches TOPMOST-FIRST, i.e. the
    reverse of the paint order: the `over` band z-descending, then the owner
    rect itself, then the `under` band z-descending. It returns
    `{"kind": "layer", "id", "target"}` (raw authored values, never resolved or
    validated here), `{"kind": "owner"}`, or `None` for a miss — an
    `"owner"`/`None` answer means "no clickable layer claimed this point", and
    `hit_layer` keeps scanning the other widgets before falling through to the
    screen's normal hit path. A layer that resolves to `visible: False` in the
    OWNING widget's current state is not hit, and the `state` argument is the
    same one `resolve()` takes, so a state-patched offset moves the hit rect
    exactly as it moves the paint rect. It mutates nothing — `layers`,
    `owner_rect` and module state are all read-only — which is what makes the
    double call per click (arm on DOWN, fire on UP) safe.
  - **Min-target lint**: clickable layers join
    `test_ui_min_targets.py`'s NON-BLOCKING under-16px lint only, never the
    hard ≥12px floor. A clickable layer is usually decorative art retargeted
    onto an already-floor-checked button, and the "do not mass-resize
    controls to silence the lint" rule above forbids the only fix a hard
    failure would pressure a designer into.

- **Designer-authored custom widgets (UL-13)**: a screen doc may carry a
  top-level `custom_widgets` table beside `widgets`/`background`/`defaults` —
  decoration a designer wants and NO CODE OWNS. An entry is that widget's
  DEFAULT GEOMETRY ONLY (`kind`, `rect`, optional `band`/`z`/`display_name`):
  a hand-written twin of ONE `screen_defaults.json` record. Everything
  paintable — `skin`, `color`, `label`, `text_id`, `font`, `text_color`,
  `tint`, `align`, `visible`, `parent`, `layers`, `states` — is an ORDINARY
  override under `widgets/<the same id>`, exactly as for a code-owned widget.
  There is no second styling vocabulary, and no screen learns a new key.
  - **They ride the TWO `submit_layers` calls every screen already makes**,
    drawn at the tail of the matching band's pass. No `submit()` gains a third
    call and no new call site exists anywhere, which is what keeps the golden
    parity pin byte-identical BY CONSTRUCTION: no `custom_widgets` key ⇒ zero
    extra primitives. `apply()` and the real-widget loops need no change —
    both iterate `ids` (the game's own widget objects), so a custom id is
    simply never matched there.
  - **`view` scopes an entry to ONE of the screen's views** — the keys of
    `screen_defaults.json`'s `views` (`construct`, `unlock`, `upgrade`,
    `base_info`, `preview` on `building_panel`). **Absent = every view**,
    which is the single-view screen and what every entry authored before the
    key meant. It exists because a screen ID is not a screen: `building_panel`
    is five `BuildingUI.mode`s plus `ConstructPreview`/`MovePreview`, all
    declaring the same id, so an unscoped custom widget is drawn by every one
    of them — a plate authored for the build list also landing on the unlock
    and upgrade panels, and again on top of an open preview. `submit_layers`
    takes a `view=` and drops entries naming a different one; a screen that
    passes none filters nothing. `BuildingUI` passes `self.mode` (its view ids
    ARE its mode names) and the two modals pass `_PREVIEW_VIEW`. `move_select`
    is a mode the exporter records no view for, so a scoped widget simply
    never draws there. Only CUSTOM widgets need this — a code-owned widget is
    already view-scoped by construction, because a mode only puts the widgets
    it built into `ids`.
  - **`hidden_customs=` is the LIVE-STATE gate**, the caller's counterpart to
    the doc-authored `view`: a set of custom ids `submit_layers` drops for
    this frame only. `view` answers "does this decoration belong to this
    mode"; this answers "does it have anything to decorate right now", which
    the doc cannot express. Today's only user is `BuildingUI`, whose
    `_hidden_stat_backdrops()` drops the plates in
    `_STAT_BACKDROP_MIN_ROWS` — the nested stack behind the stat block
    (`custom_panel_17` parents `16` parents `19`) peeling off as the block
    shrinks: 5+ stat rows shows all three, 4 drops `19`, 3 drops `16` too, 2
    or fewer leaves none. The block is as tall as the selected building has
    stats, so on a Blocker or an economy building a plate cut for five rows
    would hang below the text it backs. The ids are the
    designer's (whatever the editor generated), the THRESHOLD is code. The
    default is empty, so every other screen is unchanged, and hiding a plate
    never moves its `parent`-anchored children — `apply()` resolves parents
    and is untouched by this gate.
  - **Order**: band first — **absent = `under`**, so by default a custom
    widget goes behind EVERYTHING on the screen (the same no-depth-sort
    trade-off as a layer). Note this is the OPPOSITE of an undecorated LAYER
    entry, which `engine/ui_layers.ordered` still defaults to `over`, and the
    difference is deliberate: a custom widget is decoration a designer
    invented, and a decorative box defaulting on top of the screen's own
    readouts, counters and buttons hides the information the player needs.
    `over` is still authorable per widget. Then ascending `z` (absent = 0)
    among the custom widgets of that band, ties
    keeping the file's own authoring order. `z` never orders a custom widget
    against a code-owned one; the band alone decides that.
  - **Kind → primitives.** `panel`: `skin` (falling back to this screen's
    `defaults.panel_skin`) → `HudSprite`, else `color` → `HudRect`; THEN a
    CENTRED `HudText` when it carries `label`/`text_id`. That is TWO
    primitives, which is exactly why this is a NEW `_submit_custom_widget`
    method and not an overload of `_submit_one_layer` — that method's "one
    role, FIRST MATCH WINS" precedence is a design decision, not iteration
    order. `backdrop`: the same box, no text, and NO kind-matched default skin
    (its own `skin` only — the existing code has no backdrop default).
    `label`: `HudText` only, through `strings.T` exactly as a layer does, with
    an empty resolved string drawing NOTHING rather than a blank `HudText`.
    Then its own `layers` array, from that same `widgets/<id>` override,
    resolved against the custom widget's rect and filtered to the band we were
    called for. Semantics matched by eye against `editor/panels/
    _screen_primitives.fallback_hud_items` — never imported, the same accepted
    editor/game drift that module's own docstring records.
  - **State is always `"idle"`.** A custom widget has no state machine, the
    same answer `state_of` gives any non-`Button` holder, so only `states.idle`
    is ever reachable on one.
  - **They are NEVER click targets** (a user decision, not an oversight):
    neither the widget nor its layers are hit-tested, `hit_layer` does not see
    them, and a click passes straight through to the real UI underneath.
  - **`_validate_ids` must know them.** It fails loud on an override naming a
    widget absent from `screen_defaults.json`, and a custom widget has no
    record there by construction — so ids present in `custom_widgets` join the
    `known` set. Without that, every screen carrying one raises at load.

- **The three life counters (UL-11, D10)**: `life_1`/`life_2`/`life_3` are
  THREE id'd `panel`-kind holders in `hud.py`'s `ids` (not one repeated draw),
  each positionable, skinnable and layerable on its own. They are ADDED beside
  `lives_text`/`icon_lives`, which are unchanged and stay — removing an id
  would break the on-disk contract. Default skin is the existing
  `ui_icon_lives` art (so an unauthored screen still shows something
  recognisable) and the default rects — a row to the right of the lives icon +
  numeric readout, on the same `_ICON_SIZE`/`_ICON_GAP` grid — are baked into
  `screen_defaults.json`; a designer moves them wherever they like.
  - **Per-state art arrives as a `layers` override, on the PINNED four-token
    vocabulary** (UL-11 changed no schema): `alive → idle` (loops),
    `dying → pressed` (plays once), `dead → disabled` (static). `hover` is
    never produced for a life counter — a designer may author it, but nothing
    selects it. Each holder carries its own `_state` callable, which is the
    SAME seam `ScreenSkinning.state_of`/`submit_layers` already dispatch
    through for a `Button`, so `skinning.py` needed no change.
  - **State is driven off `session.state.base_lives` DELTAS, not the
    `life_lost_events` ledger.** `main.py` runs the floaters' effects step
    (which DRAINS `life_lost_events`) BEFORE `Hud.update()` every frame, so on
    the exact frame of the loss the ledger is already empty — a second
    consumer would race it. `base_lives` detects the same event with no race
    and adds no second ledger, keeping `effects.py` the ledger's sole consumer
    (`Hud._update_life_states`).
  - **The `pressed` transition is time-boxed**: `_LIFE_TRANSITION_MS = 600`.
    The life that died (index `base_lives + 1`) reads `pressed` for that long,
    then reverts to `disabled`. The FIRST `update()` only SEEDS the tracker, so
    a run that starts below full lives shows dead-and-static counters rather
    than replaying a transition that already happened.
  - **Only ONE transition is tracked at a time** (`_life_transition_idx` is a
    scalar, not a queue). Two lives lost inside the same 600 ms window means
    the first one's `pressed` frame is CUT SHORT — the second loss overwrites
    the index and the first counter goes straight to `disabled`. Accepted as
    cosmetic (S4 section review, LOW): the resolved STATE is never wrong,
    because `_life_state_token`'s `idx <= lives` test settles every
    non-transitioning life correctly on its own; only the death animation is
    truncated. Queue the indices if a designer ever asks for overlapping
    death animations — nothing else depends on the scalar.
  - Lives GAINED are handled by the same `idx <= lives` test with no special
    case: a restored life snaps back to `idle` on the next frame and no
    transition fires (the delta check is `<` only). Deliberate — the
    transition art is a DEATH animation; there is no revival animation to play.

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
  `lives_text`, `tiles_text`, `phase_label` (see below), `round_label`, `btn_end_turn`,
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
  (`MapOverlays`, the toggle pills) gained its own
  `data/ui/screens/overlays.json` + `ids` (`btn_range`, `btn_heatmap`, and
  since the tier-overview feature `btn_tier_overview`) the
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

**Since UL-2 the table is not wholly hardcoded**: the 7 shipped keys still are,
but a DESIGNER-DEFINED preset's entry is measured once inside `configure_fonts`
and stored (`engine/render/CLAUDE.md`). `layout_h` is still a table read and
never a live measurement, so the rule above is unchanged — but the cross-
platform guarantee covers only the 7 pinned keys, because only those were
measured by a human on one machine and frozen. Nothing in CODE lays out
against a custom preset today (the exporter and the golden capture both run
the shipped screens, which name only the 7), and that is what keeps the
committed artifacts reproducible. If code ever DOES lay out against a custom
`font_key`, that stored rect becomes machine-dependent — pin the value first.

## The seven tile highlights are EFFECTS now (VfxAuthoringPLAN VA-5)
`tile_selected`, `section_2x2`, `attack_range`, `move_target`, `wall_edge`,
`upgrade_batch` and `tutorial_highlight` are `data/balancing/vfx.json` entries:
a `procedural.highlights.<name>` param block (colour / outline width / fill
alpha) plus a `triggers.<name>` row, so each can be retuned, replaced by an
imported `vfx_<name>` spritesheet, and put in front of or behind a same-tile
building — like every other effect.
- **`widgets.submit_highlight(renderer, event, col, row, assets=…)` is the ONE
  draw path**, and `_highlight_tiles` carries the EVENT NAME where it used to
  carry a colour. Resolution mirrors `FloaterManager._play`: a bound
  `sprite_slot` with imported art wins (the same
  `animation_total_ms(slot, "idle") is not None` signal every art-tolerant
  site uses), else the procedural diamond; `draw_in_front` becomes the VA-3
  depth rank.
- **They are CONTINUOUS, so they do NOT go through `_play`** (D7). A selection
  outline is drawn every frame for as long as the tile stays selected;
  `PlayOnceVfx`'s despawn clock would respawn the object every frame. That is
  also why the resolver lives in `widgets.py` rather than behind
  `FloaterManager`: `BuildingUI.submit` and the host both draw highlights and
  neither holds the FX manager, while this module already owned
  `submit_tile_diamond` — the one place a tile highlight has ever been drawn.
- **`configure_highlights(vfx_doc)` is `configure_palette`'s twin**, called at
  the same boot slot, with the same loaded-doc contract, the same
  UNCONFIGURED-FALLBACK literals and the same fail-loud-on-key-mismatch rule.
  Deliberately so: three of these five values WERE palette keys until this
  phase. Read colours through `highlight_color(event)` at CALL time — the
  early-binding trap the `C_*` block already warns about.
- **Five constants are DELETED**: `C_HIGHLIGHT`, `C_HIGHLIGHT2`,
  `C_RANGE_HIGHLIGHT` (palette keys, also removed from `palette.json` and
  `_PALETTE_KEYS`) plus `C_MOVE_HIGHLIGHT` and `C_TUTORIAL_HIGHLIGHT` (bare
  code constants). One home per value (G-7/D8) — leaving them in the palette
  as well would be the dead-data gap `procedural.floaters` opened and ESV-6
  had to close.
- **Their non-tile consumers re-point at the same params rather than keeping a
  second copy**: the RANGE overlay pill (`overlays.py`) and a wall builder's
  walled TILES read `attack_range`; the move instruction text and the L-shaped
  path line read `move_target`; the drag-select rectangle's fill and the two
  name-field focus rings read `tile_selected`. Each of those IS the highlight's
  colour seen somewhere else, which is why sharing is correct here and a
  second key would not be. **One consumer was missed by this migration and
  shipped a live `AttributeError`** (found the hard way, live-testing the
  tile-buying tutorial topic below): `ColorSwatchRow.submit`'s selection ring
  (`building_ui.py`, the construct-preview building-colour picker) still read
  the deleted `widgets.C_HIGHLIGHT` directly. Fixed the same way as the other
  four — `highlight_color("tile_selected")`, the same "ring around the
  selected thing" reading the two name-field focus rings already use.
- `wall_edge` draws a LINE, not a diamond, so its `border_width` is the line
  width and its `fill_alpha` is unused — the one non-uniform member of an
  otherwise uniform block, documented in the schema.
- Pinned by `tools/tests/test_highlight_data.py`, in `test_theme_data.py`'s
  shape (stock table, fallback-equals-data, rebind-reaches-consumers).

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
- **`configure_fonts`/`configure_palette` fail loud on a MISSING key** — a
  renamed or dropped preset/color would otherwise leave some `font_key`/`C_*`
  silently un-rebound. They differ on an UNKNOWN key: `configure_palette`
  still rejects one, but since UL-2/D6 `configure_fonts` ACCEPTS extras,
  because a designer-defined preset is exactly an extra key (see below).
- **The 7 PINNED `layout_h`/`_LAYOUT_H` entries are untouched by
  `configure_fonts`** (see the section above) — a designer enlarging a
  shipped preset changes drawn glyphs only; stored layout rects don't move, so
  text can overflow its widget. That is the pinned-layout contract, not a bug
  (the editor's Theme panel says so in a tooltip).
  - **A DESIGNER-DEFINED preset key does get a `_LAYOUT_H` entry** (UL-2/D6):
    it has no pinned value to protect, so `configure_fonts` derives one at the
    end of the call and stores it. Derived ONCE at config time, never measured
    live at a layout call site — which is what keeps it compatible with the
    "`layout_h`, never a live font measurement" rule above rather than an
    exception to it. Details in `engine/render/CLAUDE.md`.
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
- **Optional per-widget `align` (UL-1)** — `data/ui/screens/<id>.json`'s
  `widgets.<id>.align`, `left|center|right`, the designer-facing twin of the
  holder attribute the section "`hud.round_label` carries its own alignment"
  describes. **Zero game-side code changed to enable it**: `submit_label`
  already resolves `getattr(holder, "align", "left")`, and `apply`'s generic
  setattr loop threads any override key onto the widget (same as
  `skin`/`tint`/`text_id` — no `_SPEC_TO_ATTR` entry). All that was missing
  was the schema key. **Absent = `"left"` = today's rendering, pinned** — no
  shipped screen doc authors it, so `test_ui_skinning.py`'s golden stream is
  unmoved. Do not confuse this with `screen_defaults.json`'s `align`: that is
  a GENERATED editor-only measuring hint the exporter reads off the code
  holder, on a different file and a different schema, which the game never
  reads back. The editor prefers the override over that hint when it sizes an
  anchor's hit box (`_screen_primitives.resolve_align`).
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

## Dynamic-count content IS individually overridable now (editable-ui-widgets)

**This reverses the "Dynamic-count content is NOT individually overridable in
v1" bullet above** (kept there as history — read this section for what is
true). A designer asked for the buy options to be real editable widgets, and
the old rule's actual constraint was never "the count varies": it was "there
is no stable id to attach an override to". Both cases turn out to have one.

- **`levelup.py`'s option boxes** — the roll offers 1-3, but there have always
  been exactly THREE slots, so each gets an index id: `option_box_0..2`.
  `self._boxes` holds one `SimpleNamespace(rect, skin, color, visible)` per
  slot; `layout()` computes the default centred row as before, stores it into
  the holders, ids only the slots this roll filled, calls `skinning.apply`,
  and **then** rebuilds `self.rects` FROM the holders — so an overridden rect
  drives `hover`/`hit` as well as the draw, and `self.rects` (which
  `test_levelup.py` reads directly) can never disagree with what is on screen.
  Per-box `skin` beats the screen-level `defaults.panel_skin`; `color` follows
  the "`None` means compute" convention, so an un-overridden box draws its two
  raw hover-tinted rects exactly as before.
  - **ANTI-SOFTLOCK**: this modal has no dismiss path — the player MUST pick
    one — so `_box_visible` ignores `visible: false` WHOLESALE if it would
    hide every offered box. Hiding one or two does what you asked; hiding all
    of them gets you a playable game instead of a frozen one.
- **`building_ui.py`'s construct cards** — id'd `card_<building_type>`
  (`_CARD_ID_PREFIX`), the type being the stable key. Because a card is
  REBUILT on every `_build_construct` (it carries a live price),
  `_clear_card_ids()` sweeps the previous build's entries out of `self.ids`
  first — otherwise `skinning.apply` would keep writing onto dead widgets and
  a type that stopped being buildable would linger forever. The cards follow
  every other id'd button's rules: `is_visible` gates submit AND
  hit, `hover()` is called then `hovered and= is_visible` (never skipped
  outright), and `button_kwargs` forwards `color`/`text_color`.
  `defaults.button_skin` remains the fallback for a card with no `skin` of
  its own. **A card is a widget TREE, not one button — see the next
  section.**
- **Recording them is a `tools/screen_mocks.py` change**, not an exporter
  special case: `LEVELUP_OPTIONS` grew to three cards and the `construct` view
  unlocks every RESEARCH type first, so every slot and every card lands in
  `screen_defaults.json`. Details → `editor/panels/CLAUDE.md`.
- **Still un-id'd, and still for the stated reason**: the boss-history popup
  body and `credits`' role/name rows — genuinely unbounded lists with no
  stable key per row. `defaults` remains their styling seam.

**Golden-parity note**: all of the above is a rendering NO-OP. Capturing with
`LEVELUP_OPTIONS` truncated back to its original two reproduces the previous
`test_ui_skinning.py` baseline byte-for-byte on every screen — the pin's
`levelup` entry was regenerated only because its INPUT (three mock cards
instead of two) changed, not its code.

## A construct card is a widget TREE (construct-card-widget-tree)

**This supersedes the "a card is one `Button` with one centred label" shape
above.** A card used to bake the building's name and its price into a single
string; it is now a parent holding a creature portrait, a two-row name block
and a price pill with the baked love icon — each part independently id'd,
placeable and skinnable in the UI editor. NINE ids per buildable type, all
sharing the ONE `card_` prefix, so `_clear_card_ids()` needed no change:

The card SLOT is 140×77 (`_CARD_W` × `_CARD_H`), positioned off
`construct_card_list`'s box. Offsets below are from the slot's top-left.

The list pitch is `_CARD_PITCH`, its OWN number and deliberately not
`_CARD_H + gap`: the plate and the frame are 64 tall inside the 77-tall slot,
so what the eye reads as the gap between two cards is `pitch - 64`, not
`pitch - 77`. At the shipped 72 that is an 8px gap, and a slot overlaps its
neighbour's by 5px — harmless, since the frame's bottom band and the next
plate's top band share exactly one column of x. Spelling it as a negative
`_CARD_GAP` would be a name that lies about what it measures.

| id | kind | rect (relative to the slot at `(cx, y)`) |
|---|---|---|
| `card_<btype>_plate` | panel | `(+63, +0, 77, 64)`, `skin` = `ui_panel_v11` |
| `card_<btype>` | button | `(+10, +24, 44, 45)` — the click target |
| `card_<btype>_portrait` | panel | `(+14, +28, 34, 34)`, `skin` = the sprite slot |
| `card_<btype>_frame` | panel | `(+0, +13, 64, 64)`, `skin` = `ui_panel_v7` |
| `card_<btype>_name` | label | `(+69, +26, 0, 0)`, `sm` |
| `card_<btype>_name2` | label | `(+69, +26 + step, 0, 0)`, `sm` |
| `card_<btype>_price` | button | `(+62, +46, 74, 23)` |
| `card_<btype>_price_icon` | panel | price `+14, +8`, `10×10`, `ui_icon_love` |
| `card_<btype>_price_text` | label | price `+28, +7`, `sm`, `building.stat.value` |

- **The BODY is not the card.** It is a 44×45 portrait backing that happens to
  be the only click target; the card's visual extent is the plate+frame union,
  i.e. the slot. Anything asking "is this inside the card" — `_card_in_viewport`
  above all — must ask about the SLOT, which it recovers from the body by
  subtracting `_CARD_BODY`'s offset. Windowing on the body instead lets a
  card's plate and frame spill out of the group.
- **The plate and the frame are ordinary code-owned parts, and must stay
  that way.** They were authored as CUSTOM widgets first, which put them on
  every mode of this screen — `unlock`, `upgrade`, `base_info`,
  `move_select` — and on top of `ConstructPreview`/`MovePreview` as well,
  because a custom widget is drawn by `ScreenSkinning.submit_layers` off the
  SCREEN id and all of those share `building_panel`. A custom widget is the
  wrong tool for anything that belongs to one mode's content.

- **Rects are ABSOLUTE, as everywhere else here.** `parent` is editor
  authoring metadata nothing in `game/` reads (`editor/widget_tree.py`);
  `_build_construct` lays its own children out and there is no runtime
  cascade. The exporter derives the pairs from the id prefix
  (`_derived_parent`, `tools/export_ui_layouts.py`) because the card ids are
  dynamic — `_PARENTS` cannot spell out one per building type.
- **`_name2`, never `_name_2`.** That derived rule takes the longest matching
  card id, so `card_x_name_2` would nest under `card_x_name` instead of
  sitting beside it. The price icon and text DO nest under `card_x_price`,
  which is correct — they ride inside the pill.
- **The name is wrapped at DRAW time, never at build time.** `wrap_text`
  measures the live font, and a card's name reaches
  `data/ui/screen_defaults.json`'s `label` — a committed artifact, which the
  "`layout_h`, never a live font measurement" rule above forbids from
  depending on a measurement. So `card_<btype>_name` STORES the whole name
  (a `label` override on it drives both rows) and `_submit_construct` splits
  it; `_name2`'s stored label is always `""` and it lends only position,
  font and colour. A `test_theme_data` pin catches this exact regression —
  bumping every font preset 6px re-broke "Maw Mortar" across two rows and
  changed the committed file.
- **The love icon is a sprite, not a glyph** (`ui_icon_love`, the `hud.py`
  idiom) — `widgets.HEART` stays deleted.
- **The stack is plate → body → portrait → frame → price → icon → text.**
  `Renderer.submit_hud` appends and nothing sorts it, so submission order IS
  z-order. The plate is the backdrop the name and price sit on and the frame
  is a border in FRONT of the portrait — which is exactly what those two meant
  as custom widgets banded `"under"` and `"over"`. The body before the
  portrait for the older reason: the portrait sits wholly inside the body's
  rect, so submit it first and a skinned body hides it outright. Latent while
  `defaults.button_skin` is unset (the body draws as a flat rect and the
  portrait survives), a screen-breaker the moment a designer skins the card —
  so the whole order is pinned by `TestCardDrawOrder`, not left to the eye.
- **The card column FOLLOWS the `panel` container** (`_card_column()`, reading
  `ScreenSkinning.widget_rect(screen_id, "panel")`), so `cx`/`cw` above are the
  authored panel inset by `_CARD_INSET`, not the ctor's `panel_x`/`panel_w`.
  This is what a designer resizing the panel in the editor needs: static
  widgets can be dragged one by one, but cards are DYNAMIC-count content laid
  out in code and carry no authorable position, so without this they stay
  stranded in the old panel's footprint. Note `self.panel_x`/`panel_w` are
  ctor CODE defaults that never see the override — only `panel_rect` is
  refreshed, and only at submit, i.e. AFTER `_build_construct` has run — which
  is why the authored rect is read directly. **No override falls back to the
  code defaults**, so `screen_defaults.json` (recorded with the disk-free
  `ScreenSkinning.empty()`) is byte-unchanged by any of this.
  - **Hand-pinning the 12 `card_<btype>` rects is NOT the way to move the
    column, and actively breaks it** — three ways, all of which have shipped:
    (1) an authored rect reaches only the card BODY while that card's
    portrait/name/price children stay on the code layout, so the parts of
    every card drift apart down the list; (2) `BuildingUI.submit` runs
    `skinning.apply` EVERY FRAME, so the pin overwrites the scroll-adjusted
    rect `_build_construct` just computed — the wheel moves `scroll_offset`
    and nothing on screen moves; (3) a card pinned outside
    `construct_card_list`'s window is culled at draw AND at hit, i.e. that
    building type is unbuyable. Twelve pins once did all three at once, with
    five types unclickable. `TestCardColumnFollowsThePanel` guards the first
    and `TestNoPinnedCardRects` the other two.
- **The price pill, the plate and the frame name their own skins**
  (`_CARD_PRICE_SKIN` = `ui_button_panel`, `_CARD_PLATE_SKIN` =
  `ui_panel_v11`, `_CARD_FRAME_SKIN` = `ui_panel_v7`) instead of inheriting
  `defaults.button_skin` / `defaults.panel_skin`: the body art is a small
  portrait backing and stretching it through a 74×23 pill reads as a squashed
  card, while `panel_skin` is shared with the panel body, the terrain badge
  and the effect box, so inheriting it would tie a card's chrome to theirs.
  Baked for the same reason `_CARD_LOVE_ICON` is — each names one specific
  piece of art; a designer wanting another overrides
  `card_<btype>_price`/`_plate`/`_frame`'s `skin` per card, leaving the body
  alone.
- **Two screen-level bools**, both in `data/ui/screens/building_panel.json`'s
  `defaults` (read fresh via `_card_defaults()`, the `defaults.button_skin`
  precedent — `defaults` values are never id-validated, so `ScreenSkinning`
  needed no change), both defaulting **false**:
  - `price_is_click_target` — on, ONLY the price pill opens the construct
    preview and the body goes inert. Off (the default), **both** the pill and
    the body open it: the pill is the obvious "press me" on a card, and the
    body is a 44px portrait backing that is not. It did not always work this
    way — off used to mean the pill was drawn but never hit-tested, which
    made the one part of the card that looks like a button do nothing.
    Nothing downstream of the hit changes. The NOT-ENOUGH-LOVE flash lands on
    the PILL either way: it is a sentence, and since the body shrank the 74px
    pill is the widest `Button` in the tree.
  - `use_card_portrait_slot` — on, the portrait draws
    `card_portrait_<btype>` (`data/slots.json`'s `ui` → "Card Portraits"),
    falling back to the building's own tier sprite whenever that slot has no
    imported art. Off, it is always the tier sprite —
    `create(...).slot_key()`, the `_next_tier_card` idiom. The "has art"
    probe is `assets.animation_total_ms(slot, "idle") is not None`, the same
    signal `engine.vfx.spawn_play_once` uses. `BuildingUI.assets` is
    host-wired in `build_gameplay()` (the `FloaterManager.assets`
    precedent) and `None`-safe.
- **The list SCROLLS.** Twelve 44px-pitch cards do not fit a 130×360 panel, so
  `scroll_offset` (first visible index) and `handle_scroll(dy)` clamp against
  `_cards_visible()`, itself derived from `_card_list_viewport()` — never a
  literal count. Sign follows `HighscoresScreen.scroll` (positive `dy` moves
  DOWN), and `game/main.py`'s gameplay MOUSEWHEEL branch negates pygame's `y`
  and routes to the panel only while the cursor is over it in construct mode
  with no preview open; everywhere else the wheel still zooms the camera.
  `close()` resets the offset.
- **An off-window card is skipped at draw and at hit via
  `_card_in_viewport`, NOT by setting `visible = False`.** `visible` is the
  designer's override key and forcing it would fight an override; every card
  is built at its absolute rect every frame, so `self.ids` — and therefore
  `skinning.apply` and the exporter — always sees the full id set.
- `card_rect(building_type)` (the tutorial's TU-6 highlight) still returns the
  WHOLE card, both bools regardless.


## `hud.round_label` carries its own alignment
`align="center"` moved from the `submit_label` CALL SITE onto the holder. It
is a constant property of that label (it is centred on the End Turn button),
and `tools/export_ui_layouts.py` reads alignment off the holder to tell the
editor which way the text spreads from its stored anchor — left as a call-site
override it recorded as `"left"` and the editor put the Round counter's hit box
half a label to the right of the glyphs. Every other centred label in `game/ui`
already declared it on the holder; this was the one that did not. **If you add
a label whose alignment never varies, declare it on the holder**; reserve the
`align=` argument for a call site that genuinely varies it.

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
- **The players outlive the RUN; the video sources do not (replay fix).**
  `main.py` builds ONE `CutscenePlayer` per registry id at boot, but a
  `VideoSource` is one-shot: `release()` frees the cv2 capture and `done`
  latches True. So `first_end_turn` played on the FIRST run only — quit to
  the main menu, start a new run, and the fresh `RunState` requested it
  again, the host accepted it (`enabled` still reads True) and it ended on
  the frame it was requested, showing nothing. `CutscenePlayer.start()` now
  opens a FRESH source on every playback (unconditionally, since a
  quit-to-menu mid-cutscene leaves a released-but-not-done capture that
  would raise on the next `update()`) and resets `_skip_hold` (a hold-skip
  leaves it past the threshold, which would insta-skip the next playback).
  `teardown_gameplay()` releases an in-flight `gp["cutscene"]` before
  dropping it, so quitting mid-video hands the capture and the music track
  back. The `intro` entry is unaffected — it plays once per process launch,
  from the pre-menu shell state, and never calls `start()`.
- **Only one `pygame.mixer.music` channel exists.** Starting a cutscene's
  companion track replaces whatever background music was already playing;
  nothing restores it afterward (no drift/resume correction in scope).
- **Skip is a 2-second HOLD, not a single click/key (cutscene-hold-to-skip).**
  `SKIP_HOLD_SECONDS` (`cutscene_player.py`) plus `CutscenePlayer._skip_hold`/
  `update_skip_hold(dt, held)`/`skip_progress` live on the class itself, not
  at either `main.py` call site — so both `intro` and `first_end_turn`, and
  any future registry entry built through the same `CutscenePlayer`, get the
  hold behavior for free. `held` is a single host-computed bool (left mouse
  button OR spacebar OR escape currently down, polled every frame via
  `pygame.mouse.get_pressed()`/`pygame.key.get_pressed()` — **every other
  input is inert** during a cutscene, not just non-skipping); the event loop
  no longer calls `.skip()` on a discrete `KEYDOWN`/`MOUSEBUTTONDOWN` at all,
  it only swallows events (`continue`) so nothing leaks to menu/world
  handling. `update_skip_hold` resets the accumulator to 0 the instant
  `held` goes false (an early release costs the whole progress, not a
  partial credit) and no-ops once `done` (never double-fires `skip()` the
  same frame the video ends naturally). `widgets.submit_progress_ring`
  (`widgets.py`, composed from `HudLines` — no arc/pie HUD primitive exists)
  draws the ring; identical whether the hold is mouse or keyboard.
  **fix: cutscene skip UI polish** moved both call sites (`main.py`'s
  `_submit_cutscene_skip`) from the old fixed bottom-center point to the
  bottom-right corner (8px margin, matching the End Turn button
  convention), stacked with the ring above the "hold to skip" text so a
  bigger ring never overflows the row this close to the bottom edge. It
  also fades the whole prompt out after `_SKIP_FADE_DELAY` (2.5s) of no
  mouse movement, over `_SKIP_FADE_DURATION` (0.5s) — reappearing
  instantly on the next movement — tracked via a `main.py`-local
  `mouse_idle_t`/`last_mouse_pos` pair (host-only state, since `game/ui`
  stays pygame-free). `HudLines` carries no per-pixel alpha, so the ring's
  fade is a colour lerp toward black by the same fraction the text's real
  alpha is fading by, not a true alpha fade.
  **The same fix also reworked `submit_progress_ring`'s arc-point
  generation** (a real bug fix, not just the reposition): the old version
  re-subdivided the WHOLE arc every frame at `round(segments * ratio)`
  steps, so every already-drawn point's angle shifted slightly as `ratio`
  grew, not just the tip — the entire curve visibly "re-flowed" frame to
  frame, which read as jitter no matter how high `segments` was set.
  Points now sit on a FIXED angular grid (`i * (2*pi/segments)`,
  independent of `ratio`), so a point's screen position is identical every
  frame from the moment it first appears — only one trailing fractional
  point (the exact tip) is recomputed each call.

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
- **`widgets.highlight_color("tutorial_highlight")`** (white; VA-5 moved this
  off the old `C_TUTORIAL_HIGHLIGHT` bare constant into
  `procedural.highlights.tutorial_highlight` data — see this file's "seven
  tile highlights are EFFECTS" section) + **`submit_ui_box_highlight
  (renderer, rect, color=None, width=3)`** (a highlight ring around a card /
  Confirm / End Turn / Unlock button, plain HUD-space `HudRect`) are the two
  D8 primitives the guided chain draws with; no new render-backend work.
  **Feature addition**: every guided-chain highlight (this ring AND the world
  tile diamond, `submit_highlight("tutorial_highlight", …)`) now pulses/glows
  — alpha and border width both breathe on a sine cycle, off a new sibling
  `procedural.tutorial_highlight_pulse` block and `widgets.
  tutorial_pulse_style(clock_ms)`. The two `main.py` call sites compute it
  once per frame off the existing `deco_clock_ms` wall clock and pass it as
  `pulse_color`/`pulse_width` (tile diamond) or `color`/`width` (UI box ring)
  — no new per-frame state, no change to either primitive's default
  behaviour for its six other, still-static, callers.
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
  isn't open — same additive shape). The tile-buying tutorial topic added a
  FIFTH pair: `action_rect()` (mirrors `close_rect()`, gated on `self.mode
  == "unlock"` since `action_btn` is reused across unlock/construct-advance/
  upgrade modes) and `self.last_unlocked` (the `last_placed_type` shape
  exactly — set `True` in `_unlock_click` on a real `tm.do_unlock` success,
  read/cleared once by `main.py` right after a successful
  `panel.handle_click()`, never reset by `close()`).
- **TU-8 added a second widgets primitive, `submit_tutorial_banner(renderer,
  text, view_w, view_h)`** — the `submit_ui_box_highlight` sibling for a
  full-text hint rather than a ring: a big
  `highlight_color("tutorial_highlight")`-filled, screen-centred box sized to
  the text, drawn with **no hit-test and no input consumption** (unlike
  `TutorialMessageScreen`, which must never be used for a hint instructing a
  right-click — that modal swallows every click while visible, `main.py`
  `handle_world_click`'s top branch). Reads its text from
  `TutorialDirector.banner_text()`, submitted independently of (and
  alongside) `ui_highlight_rects`'s Close-button ring — see
  `game/CLAUDE.md`'s "Un-stick on panel close + close-panel hint" section.
  **Deliberately excluded from the pulse above** — an instructional text box,
  not a click-target border; pulsing a filled banner would read as
  distracting rather than clarifying.
- **Detail on the director/host wiring** (the three choke points, the event
  feed, the D6 zero-overhead contract, TU-8's revert/close-panel-hint
  additions) → `game/CLAUDE.md`'s Tutorial director section.

## Verify
Live mouse-only loop — unlock, build both types, upgrade to tier 2, lose → game
over screen; cold `py game/main.py`: cutscene → menu → rounds → pause/settings →
add name → credits. Purity test in the suite:
`py -m pytest tools/tests/test_<area>.py -q`.

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
