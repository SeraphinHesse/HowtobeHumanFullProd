# UI_EDITOR_PLAN.md — Phase 10L: UI Asset Pipeline + Screen Editing

Status: **UNFINISHED — run interrupted by user 2026-07-15.** The
`/execute-plan-phases` run on umbrella `phase-10L-finish-umbrella` completed
wave 2a only (A4, A7, A8, B1 — coded, reviewed, gated green, merged) before
being wrapped up early into one PR. **A5′, B2, B3, B4 have reviewed briefs in
`docs/briefs/` but NO code; A6/B5 exit gates not run.** Resume by dispatching
wave 2b per the briefs (A5′ + B4 parallel, then B2, then B3 → B4i). Carry-over
findings for the resume are listed under "Run state" below.
Two slices: **10L-A** (import animated UI spritesheets) and **10L-B** (edit
every UI screen from the editor); 10L-B depends on 10L-A. Three user
requirements were folded in on 2026-07-15 (see "New requirements" below):
per-variant pixel size (→ A7), pixel-perfect clickable surfaces (→ A8 + A5′),
and the 12-screen live-edit scope (cheat_menu, game_log, boss_cutscene join
v1 — they exist in `game/ui` now).

## Phase table

| Phase | What | Status |
|-------|------|--------|
| A1 | Engine — animated `HudSprite` | **done** (2026-07-14) |
| A2 | Engine + data — nine-slice | **done** (2026-07-14) |
| A3 | Data — `ui` category expansion | **done** (2026-07-14) |
| A4 | Editor — slice-margins editor | **done** (2026-07-15, umbrella; reviewed, 1 Medium carry-over below) |
| A5′ | Game — skinned `widgets.Button` / `submit_panel` + R2 hit seam | **not started** (brief ready) |
| A6 | Exit gate — live Quick Test + docs | **blocked** on A5′ |
| A7 | Editor — per-variant pixel size (R1: `add_variant` inherits stem override) | **done** (2026-07-15, umbrella; reviewed clean) |
| A8 | Engine — pixel hit-mask (`nine_slice.dest_to_source` + `AssetStore.hit_opaque`) | **done** (2026-07-15, umbrella; review interrupted) |
| B1 | Data — screen override format (12 screens) | **done** (2026-07-15, umbrella; review findings fixed) |
| B2 | Game — ids + `skinning.py` + golden parity pin | **not started** (brief ready; cut AFTER A5′) |
| B3 | Tools — layout exporter + committed `screen_defaults.json` | **not started** (brief ready; cut AFTER B2) |
| B4 | Editor — screen mode (selector/session/viewport/details) | **not started** (brief ready; parallel-safe with A5′/B2) |
| B5 | Exit gate (10L-B) — live Quick Test + docs | **blocked** on B1–B4 |

### Run state (2026-07-15 wrap-up — read before resuming)

- Landed on the umbrella (each branch full-suite green before merge, ZERO
  failures — 1229–1243 tests depending on branch): A4 `phase-A4-slice-editor-impl`
  0ff8bcd, A7 `phase-A7-variant-frame-size` 4bc19b5, A8 `phase-A8-hit-mask`
  59941ab, B1 `phase-B1-screen-formats` abc244a (+ review-fix commit).
- **Carry-over (Medium, from A4's review)**: `_on_frame_size_changed` in
  `editor/panels/details.py` doesn't re-range/re-clamp the slice spinboxes when
  a per-slot frame-size override SHRINKS — a stale over-sized `slice` can be
  re-saved to the manifest (render clamps at draw time, so no crash). Fix +
  test when A4 is next touched.
- **Tooling bug (measured twice)**: `py tools/testgate.py check --affected`
  vacuously passes ("0 ran") for phases whose tests are all non-`core` tier —
  `affected_modules()` always ANDs `-m core` onto the selected files. Run the
  explicit pytest on your test modules until fixed.
- **Carry-over (High, UNCONFIRMED — from A8's interrupted review)**: in
  `engine/assets/nine_slice.py` + `store.hit_opaque`, when clamped slice
  margins sum EXACTLY to a source dimension but the dest still has a centre
  band, `dest_to_source` maps into a band `_nine_patch` never paints —
  `hit_opaque` may return True over on-screen transparency. Traced in code,
  no live reproducer run. Confirm + fix (return False for the vanished band,
  or paint it) before A5' wires the seam.
- **Contract rulings already baked into the briefs**: screen `ids` map is
  `{name: (kind, widget)}`; `kind` enum = `button|panel|label|backdrop|bar|field`;
  defaults doc is FLAT (`{<screen_id>: {widgets, mock_note}}`) validating
  against `data/schemas/screen_defaults.schema.json` (stem-pairs with
  `data/ui/screen_defaults.json`).
- **Stale worktrees with uncommitted pre-run drafts** (NOT this run's work;
  superseded — user to discard or salvage): `.claude/worktrees/agent-aaae066e177974fe9`
  (branch `phase-A4-slice-editor` @ 8ec6de4, +23 lines details.py draft) and
  `.claude/worktrees/agent-a49ee230114fc0dbc` (branch `phase-A5-skinned-button`
  @ 8ec6de4, +41/-5 widgets.py draft). Wave 2b should use fresh branch names
  (e.g. `phase-A5p-skinned-button`).

A1–A3 shipped on branch `phase-A1-A6-umbrella` (one PR into `Development`).
Per-phase briefs live in `docs/briefs/phase-A[1-5]-*.md`, with the binding
file-scope reconciliation in `docs/briefs/phase-A1-A5-coordination.md` — A4 and
A5 have briefs written and reviewed, so they can be picked up directly.

**A4/A5 are independent of each other** and both depend only on A1–A3, which
have landed. Neither has any code yet. Two carry-over notes for whoever takes
them:

- **A4**: the backend floors a negative slice margin to 0 rather than raising
  (E-37 "rendering degrades, never explodes"), so a bad draft from the slice
  spinboxes cannot crash the render loop. Give the spinboxes `minimum = 0`
  anyway — the engine guard is a safety net, not the UI contract. All-zero
  margins must omit the `slice` key entirely.
- **A5**: `HudSprite`'s `animation` / `anim_time_ms` are appended **after
  `flip`** (the three shipping call sites pass three positional args), so pass
  them by keyword.

### Known follow-up surfaced during A3 — now phase A7

"+ Variant" on `Backgrounds → Main Menu` yields a **64×64** slot, not 480×270 —
the per-slot frame-size override does not propagate to variants (documented
`add_variant` behavior). **Fixed by phase A7** (R1 below): `add_variant`
inherits the family stem's frame-size override, so 10L-B's background picker
can safely source ui `Backgrounds` slots.

## New requirements (2026-07-15, user-approved designs)

- **R1 — manual pixel size per variant of each UI type → phase A7.** The
  per-slot size writer (`registry_ops.set_slot_frame_size`) and DetailsPanel's
  Frame W/H spinboxes already work for any slot, variants included; the only
  gap is creation-time inheritance. `add_variant` now inherits the family
  stem's (`slots[0]`) frame-size override — ALL categories, not ui-only (a
  variant family is interchangeable art for one thing; the schema already
  allows the object form everywhere). Divergence afterwards = the existing
  spinboxes. No schema change.
- **R2 — pixel-perfect clickable surface → phases A8 (engine) + A5′ (game).**
  Skinned buttons hover AND click only over drawn pixels (alpha > 0). New pure
  `engine/assets/nine_slice.py` owns `clamp_pair` (moved from the backend) +
  `dest_to_source` (exact piecewise inverse of `_nine_patch`'s band layout).
  `AssetStore.hit_opaque(slot, animation, anim_time_ms, dest_size, rel_xy)`
  reads a cached `pygame.mask.from_surface(threshold=0)` keyed
  `(slot_key, row, col)`; placeholder/missing sheet → opaque everywhere (E-37
  degrade-to-rect). Game side stays pygame-free via a
  `widgets.set_skin_hit_test(fn)` seam injected by `game/main.py`
  (`assets.hit_opaque`); unset seam or `skin=None` reduces to today's rect
  test. **Canonical-silhouette convention:** widgets always query
  `("idle", 0)` — hit-testing the drawn state row oscillates at silhouette
  holes. Consequence to feel live in B5: clicks on transparent corners fall
  through to the world (including `over_ui` pan-arming).
- **R3 — ALL current live screens editable → widened B1/B2 scope.** v1 covers
  **12** screens: the original 9 plus `cheat_menu`, `game_log`,
  `boss_cutscene` (they exist in `game/ui` now). No "create new screen"
  feature — the editor edits the live roster only. Contracts for the three:
  - **cheat_menu** — full template. Ids: `panel, title, btn_close,
    btn_add_love, btn_skip_round, btn_trigger_levelup, btn_inf_money,
    btn_unlock_all, round_field, btn_goto, jump_label`. Its `submit()` calls
    `layout()` every frame → `skinning.apply` must be a cached-dict setattr
    loop (pinned by a "loads once" test).
  - **game_log** — container-only (decision 4: dynamic lists are styled, not
    positioned). ONE widget `log`: rect (anchor of the newest line), font,
    text_color (age fade keeps multiplying alpha), visible. Line timings stay
    code constants.
  - **boss_cutscene** — an A/B modal, NOT timed (the announce fade lives in
    `effects.py` / `ui.json FX` and stays out of screen JSON). Ids: `backdrop`
    (color), `headline` (font only — color is win/loss logic), `subtitle`
    (font, text_color), `box_a`/`box_b` (rect — moves draw AND hit coherently;
    skin via the skinned `submit_panel`; font; text_color). Gets the standard
    per-screen anim clock. Exporter mock: `open(1, "win")` +
    `layout(1280, 720)`.

## User decisions (binding)

1. **Edit depth = skin + layout overrides.** Screens keep computing their
   prototype-exact default layout in `game/ui` code; a per-screen JSON under
   `data/ui/screens/` can override any *named* widget's rect / skin / font /
   colors / label, plus a screen background. No engine layout-container
   system; the `game_over.py` template stays.
2. **Button states = animation rows.** The `ui` category's animation
   vocabulary becomes `["idle", "hover", "pressed", "disabled"]` (row 0 =
   idle, schema-enforced as everywhere). One sheet per widget skin; each
   state row may itself be multi-frame (manifest v2 `playback_order`
   semantics apply unchanged).
3. **Nine-slice scaling.** Manifest entries gain optional slice margins;
   the backend blits corners fixed / edges axis-stretched / centre
   both-stretched. Applies to HUD sprites only (world sprites keep uniform
   zoom scaling).
4. **Sequencing = own phase now, assets first.** 10L-A ships alone so UI art
   can be imported immediately; 10L-B follows. Within 10L-B: shell menus
   first (static layouts), HUD + building panel last (dynamic layouts).

## Architecture decisions (agent-settled — veto in review)

- **Editor never imports `game/**`** (pillar), so the editor cannot run
  screen `layout()` code. Instead `tools/export_ui_layouts.py` (tools MAY
  import game) constructs every screen headless with canned mock state at
  the logical resolution from `data/display.json` and writes
  **`data/ui/screen_defaults.json`** — a generated-but-committed file,
  written via `write_validated`. The editor renders previews from
  defaults + overrides only. A test re-runs the exporter and diffs, so a
  stale committed export fails the suite; the editor gets a "Refresh
  Layouts" button that runs the exporter as a subprocess (reusing the
  `run_controls` subprocess machinery + SDL-dummy strip is NOT needed —
  the exporter is headless by design).
- **Unskinned = today's flat-rect rendering, byte-identical.** Overrides
  and skins are strictly additive: a screen with no JSON (or an empty one)
  must produce the exact HUD-primitive stream it produces today — pinned by
  a parity test. A skin assigned to a slot with no imported sheet renders
  the grey X (E-37 — the universal "no asset yet" state), same as buildings.
- **Dynamic lists are styled, not positioned.** Widgets with stable
  identities (menu buttons, HUD panels, End Turn, panel headers) get ids and
  full overrides. Per-item dynamic content (construct list entries,
  levelup options, log lines) is NOT individually overridable in v1 — it
  inherits skin/font through screen-level `defaults` (per widget kind).
  Their *container* widget (the panel) is overridable.
- **Pressed state**: `widgets.Button` today tracks hover + flash only. The
  host already owns mouse-down; `Button.hover(mx, my)` grows an optional
  `mouse_down` arg → `pressed` property. State→animation mapping:
  `disabled` → disabled row, flash → pressed row (the not-enough-love red
  flash becomes the pressed art when skinned; label overlay unchanged),
  else pressed/hover/idle rows. Missing rows fall back to idle
  (existing manifest semantics — partial sheets are fine).
- **UI animation clock**: screens accumulate one `anim_ms` in their
  `update(dt)` and pass it to skinned submits (no per-widget phase in v1;
  matches the wall-clock model the editor entity preview uses).
- **Editor screen mode gets a real undo stack** (`editor/ui_screen_session.py`
  mirroring `map_session.py`: one open screen, QUndoStack, dirty =
  `not isClean()`, Ctrl+Z/Y reuse the window-level actions) because
  drag-to-move is the primary interaction. Writes go to disk only on Save,
  via `write_validated`.
- **Backgrounds are whole-sheet single frames**: the importer already
  writes per-entry `frame_w/h` (manifest > registry precedence), so a menu
  background is one slot whose entry's frame size = the sheet size. No
  registry change needed beyond the slots.
- **Smoke pairing**: `data/ui/screens/*.json` all validate against
  `schemas/ui_screen.schema.json` — a directory-rule exception exactly like
  `maps/` and `balancing_history/`; `tools/smoke.py` special-cases the
  directory. `data/ui/screen_defaults.json` pairs with
  `schemas/screen_defaults.schema.json` by stem as normal.

---

## Slice 10L-A — animated UI asset pipeline

Branch: the `phase-10L-finish-umbrella` run (was `phase-10L-ui-assets`).
Packages: engine + data + editor + a thin game hook. Goal: import a multi-state animated button sheet in the editor,
preview it there, and see it drawn (animated, nine-sliced) in game.

### A1. Engine — animated `HudSprite`
- `engine/render/hud.py`: `HudSprite` gains `animation: str = "idle"` and
  `anim_time_ms: int = 0`.
- `engine/render/renderer.py`: HUD resolution becomes
  `assets.frame(hud.slot_key, hud.animation, hud.anim_time_ms)` (the store
  API already takes both — today's call just omits them).
- Tests: a two-row manifest entry submitted as HudSprite at two times
  resolves different frames; default args keep old behavior.

### A2. Engine + data — nine-slice
- `data/schemas/asset_manifest.schema.json`: optional per-entry
  `"slice": [left, top, right, bottom]` (ints ≥ 0; omitted = plain scale).
- `engine/assets/manifest.py`: `ManifestEntry` carries `slice`;
  `entry_from_dict` parses it. `engine/assets/store.py`: `Frame` carries it.
- `engine/render/renderer.py`: HudSprite → DrawCall passes `slice` through
  (DrawCall gains the field, default None; world-sprite path never sets it).
- `engine/render/backend.py`: a DrawCall with slice margins and
  dest size ≠ frame size renders 9-patch (corners fixed, edges stretched on
  one axis, centre on both). Composite once per (surface, size) into the
  existing scaled-frame `WeakKeyDictionary` cache. Degenerate sizes
  (smaller than the summed margins) clamp margins proportionally.
- Tests: pixel assertions on a synthetic 3-color sheet (corner pixels
  unmoved, centre color fills), cache hit test, degenerate-size test.

### A3. Data — `ui` category expansion (`data/slots.json`)
- `animations`: `["idle", "hover", "pressed", "disabled"]`.
- Groups replace the placeholder `HUD` group:
  - **Buttons**: `ui_button` (+ variants via "+ Skin").
  - **Panels**: `ui_panel`, `ui_panel_stone`.
  - **Icons**: `ui_icon_love`, `ui_icon_xp`, `ui_icon_lives` (64×64).
  - **Backgrounds**: `ui_bg_main_menu` (whole-sheet frame; also satisfies
    phase 10K's asset half).
- Editor variant support: add `"ui": None` to
  `MainWindow._VARIANT_TARGETS` so every ui leaf offers "+ Variant"
  (`registry_ops.add_variant`, `<stem>_v<k>`), labeled as the skin-add
  affordance.

### A4. Editor — importer verification (mostly free)
- `DetailsPanel` is registry-driven: with the vocab extended it already
  offers per-row animation dropdowns (idle locked on row 0), fps, hidden,
  loop, offset — verify against a real 4-row button sheet.
- Details gains a **slice-margins editor** (4 spinboxes, ui category only,
  writing the manifest `slice` field) + the viewport entity preview shows
  the slot animating per selected animation (already works via the one
  render path once A1 lands — verify).

### A5′. Game — skinned `widgets.Button` / `submit_panel` + hit seam
- Extends the reviewed A5 brief with the R2 game half: a
  `widgets.set_skin_hit_test(fn)` module seam (default None → rect
  behaviour), `Button._surface_hit` routing both `hover()` and `hit()`
  through the injected `("idle", 0)` canonical-silhouette query, and the one
  `set_skin_hit_test(assets.hit_opaque)` line in `game/main.py`.
- `widgets.Button` gains optional `skin` (slot key) + pressed tracking;
  `submit()` with a skin draws
  `HudSprite(skin, dest=rect, size=rect_size, animation=state,
  anim_time_ms=clock)` + the centred label (flat rects skipped); without a
  skin, unchanged byte-identical output. `submit_panel` gains the same
  optional skin. Nothing assigns skins yet — 10L-B's screen JSON does.
  (Interim manual hook for testing: a temporary hardcoded skin on one menu
  button during the live Quick Test, reverted before commit.)

### A6. Exit gate (10L-A)
- `py -m unittest discover -s tools/tests -t .` + `py tools/smoke.py`.
- **Quick Test**: in the live editor, import a 4-row animated button sheet
  onto `ui_button`, set slice margins, watch hover/pressed rows animate in
  the entity preview; temporary-skin a main-menu button, `py game/main.py`,
  see it nine-sliced at 320×52 animating idle→hover→pressed→disabled.
- Docs: `engine/render/CLAUDE.md` (HudSprite anim + nine-slice),
  `engine/assets/CLAUDE.md` (slice field), `data/CLAUDE.md` (ui slots),
  `editor/panels/CLAUDE.md` (slice editor, ui variants).

### A7. Editor — per-variant pixel size (R1)
- `editor/registry_ops.py::add_variant`: inherit the family stem's
  (`slots[0]`) frame-size override object on creation; bare stems stay bare
  (regression pin for enemies/deco). `tools/tests/test_registry_ops.py` gains
  inherit-on-add / bare-stays-bare / independently-resizable-after tests.
- No schema change; no editor UI change (Frame W/H spinboxes already cover
  every slot). `data/CLAUDE.md` bullet correction ships with B1 (same wave).

### A8. Engine — pixel hit-mask (R2 engine half)
- NEW pure `engine/assets/nine_slice.py`: `clamp_pair` (moved from
  `engine/render/backend.py`, which re-imports it) + `dest_to_source(rel_xy,
  dest_size, src_size, margins)` — piecewise inverse of `_nine_patch`.
- `engine/assets/store.py::AssetStore.hit_opaque(...)` → bool; mask cache
  keyed `(slot_key, row, col)` (same key space as `_frames`);
  placeholder/corrupt → True everywhere. Tests: `test_nine_slice.py`
  (inverse math + composite cross-check), `test_asset_store.py` (hole/
  placeholder/cache).

---

## Slice 10L-B — edit UI screens from the editor

Branch: the `phase-10L-finish-umbrella` run (was `phase-10L-ui-screens`).
Packages: data + game + editor + tools.
Goal: select "Main Menu" in the editor tree, see the real screen rendered
through the engine HUD pass, drag a button, assign a skin, save; the game
picks it up on next Play.

### B1. Data — screen override format
- `data/ui/screens/<screen_id>.json`, one per screen. Screen ids (v1, R3):
  `main_menu, pause, settings, credits, add_name, game_over, levelup, hud,
  building_panel, cheat_menu, game_log, boss_cutscene` — every live screen;
  future screens join by dropping in a file + ids, no format change.
- `schemas/ui_screen.schema.json`: everything optional —
  `background: {slot} | {color}`, `defaults: {button_skin?, panel_skin?,
  font?, text_color?}` (kind-level styling for dynamic items),
  `widgets: {<id>: {rect?, skin?, font?, color?, text_color?, label?,
  visible?}}`. `additionalProperties:false` inside entries; widget ids
  validated against `screen_defaults.json` at load (fail loud in dev on an
  unknown id — catches renames).
- `schemas/screen_defaults.schema.json` for the generated defaults file:
  per screen `{widgets: {<id>: {rect, kind, label}}, mock_note}`.
- `tools/smoke.py`: directory rule for `data/ui/screens/`.

### B2. Game — ids + override application
- `game/ui/skinning.py` (pure, in `TestPurity`): loads + validates all
  screen JSONs once at shell construction; `apply(screen_id, widgets)`
  mutates rects/labels/skins/fonts/colors after a screen's `layout()`;
  `screen_background(screen_id)` for submit-time. Missing file/empty doc →
  no-op.
- Each screen names its fixed widgets (`btn_new_game`, `btn_settings`,
  `title`, `love_panel`, `end_turn`, `phase_banner`, panel-mode headers, …)
  in an `ids` mapping and calls `skinning.apply` at the end of `layout()`;
  `submit()` draws the background first when overridden. HUD/building-panel
  dynamic items pull kind styling from `defaults`.
- **Parity pin**: a test constructs every screen with no override files and
  asserts the submitted HUD-primitive stream is identical to a pre-change
  golden capture.

### B3. Tools — layout exporter
- `tools/export_ui_layouts.py`: builds each screen headless (mock state:
  love=123, round=7, a mid-run building selection for the panel, etc.) at
  the `display.json` logical resolution, dumps every named widget's
  `{rect, kind, label}` to `data/ui/screen_defaults.json` via
  `write_validated`. Idempotent; committed output.
- `tools/tests/test_ui_layout_export.py`: regenerates in a temp dir and
  diffs against the committed file (the staleness gate).

### B4. Editor — screen mode
- **Selector**: the `ui` category gains a `Screens` branch above the slot
  groups — one leaf per `data/ui/screens/*.json`; emits
  `screen_selected(screen_id)` (never `node_selected`), mirroring how map
  leaves work.
- **`editor/ui_screen_session.py`**: open doc + QUndoStack (move/resize/
  field-edit/skin-assign commands), dirty/save/`_resolve_dirty` reusing the
  map-mode policy. In `TestPurity`.
- **Viewport screen mode** (`set_screen_mode(session, defaults)`): renders
  background + every widget from defaults+overrides through
  `Renderer.submit_hud` into the same offscreen surface — buttons as
  skinned HudSprites (or the flat-rect fallback drawn with the SAME
  primitives the game uses — reuse is via primitive-level helpers mirrored
  from `screen_defaults` kinds, NOT by importing `game/ui`), labels via
  HudText. Click = topmost rect hit → selection outline (HudLines); drag =
  move (undoable, arrow keys nudge); handles on corners = resize. A state
  dropdown (idle/hover/pressed/disabled) + running anim clock previews
  skins live.
- **`panels/screen_details.py`** (right pane in screen mode): widget list,
  per-widget form — rect spinboxes, skin combo (ui slots from the
  registry), font combo (`fonts.py` keys), color buttons, label edit,
  per-field "reset to default"; screen background picker; `defaults`
  section. Save writes via `write_validated`. Every new module into
  `TestPurity`.

### B5. Exit gate (10L-B)
- Suite + smoke; exporter-sync test green; parity pin green.
- **Quick Test (live)**: editor → Screens → Main Menu: drag START NEW GAME
  40px up, assign `ui_button` skin to all five buttons, set a background
  slot, Save, Ctrl+Z/Y round-trip; Play → the menu matches the editor
  preview pixel-for-pixel (allowing anim phase); pause/settings/game-over
  each get one edit; HUD: move the love panel to the top-right, verify
  in-round; delete `main_menu.json` → game renders today's stock menu.
- Docs: `game/ui/CLAUDE.md` (ids + skinning), `editor/CLAUDE.md` +
  `editor/panels/CLAUDE.md` (screen mode/session), `data/CLAUDE.md`
  (ui screens + defaults formats), MIGRATION_PLAN.md gets the 10L row,
  PLAN.md phase table on completion.

## Risks / open items

- **Golden parity capture (B2)** must be recorded before any widget refactor
  lands on the branch — first commit of 10L-B.
- **Nine-slice + `pygame.transform` interaction**: edge stretching of
  per-pixel-alpha art needs `smoothscale` vs `scale` choice — decide by eye
  on real art in A2; cache whichever wins.
- **HUD per-pixel alpha** stays out of scope (same limit that deferred the
  pause dim / level-up translucency to 10J) — skins are opaque or
  color-keyed sheets for now.
- **`screen_defaults.json` merge friction**: regenerating on two branches
  will conflict; it's deterministic output, so resolve by re-running the
  exporter, never by hand-merge.
