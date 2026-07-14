# UI_EDITOR_PLAN.md — Phase 10L: UI Asset Pipeline + Screen Editing

Status: **10L-A in progress** (designed 2026-07-11, user-approved direction).
Two independently shippable slices, each its own branch per the migration-era
branch rule: **10L-A** (import animated UI spritesheets) and **10L-B** (edit
every UI screen from the editor). 10L-A has no dependency on any 10x phase;
10L-B depends on 10L-A. Both slot in alongside the remaining 10x phases —
screens that don't exist yet (boss history, cheat menu, game log) join the
system when their phase lands.

## Phase table (10L-A)

| Phase | What | Status |
|-------|------|--------|
| A1 | Engine — animated `HudSprite` | **done** (2026-07-14) |
| A2 | Engine + data — nine-slice | **done** (2026-07-14) |
| A3 | Data — `ui` category expansion | **done** (2026-07-14) |
| A4 | Editor — slice-margins editor | **not started** |
| A5 | Game — skinned `widgets.Button` / `submit_panel` | **not started** |
| A6 | Exit gate — live Quick Test + docs | **blocked** on A4+A5 |

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

### Known follow-up surfaced during A3 (not a blocker)

"+ Variant" on `Backgrounds → Main Menu` yields a **64×64** slot, not 480×270 —
the per-slot frame-size override does not propagate to variants (documented
`add_variant` behavior). Harmless today because nothing consumes the slot, but
it becomes a live footgun once 10L-B exposes a background picker: importing a
second 480×270 menu background onto the variant would grid-slice it into a 7×4
frame grid. Either propagate the override in `registry_ops.add_variant`, or have
10L-B's picker source the `backgrounds` category instead of carrying the
duplicate `ui_bg_main_menu` slot.

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
  `schemas/ui_screen_defaults.schema.json` by stem as normal.

---

## Slice 10L-A — animated UI asset pipeline

Branch: `phase-10L-ui-assets`. Packages: engine + data + editor + a thin
game hook. Goal: import a multi-state animated button sheet in the editor,
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

### A5. Game — skinned `widgets.Button` / `submit_panel` (hook only)
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

---

## Slice 10L-B — edit UI screens from the editor

Branch: `phase-10L-ui-screens`. Packages: data + game + editor + tools.
Goal: select "Main Menu" in the editor tree, see the real screen rendered
through the engine HUD pass, drag a button, assign a skin, save; the game
picks it up on next Play.

### B1. Data — screen override format
- `data/ui/screens/<screen_id>.json`, one per screen. Screen ids (v1):
  `main_menu, pause, settings, credits, add_name, game_over, levelup, hud,
  building_panel`. (Later phases add `boss_history`, `cheat_menu`,
  `game_log` by dropping in a file + ids — no format change.)
- `schemas/ui_screen.schema.json`: everything optional —
  `background: {slot} | {color}`, `defaults: {button_skin?, panel_skin?,
  font?, text_color?}` (kind-level styling for dynamic items),
  `widgets: {<id>: {rect?, skin?, font?, color?, text_color?, label?,
  visible?}}`. `additionalProperties:false` inside entries; widget ids
  validated against `screen_defaults.json` at load (fail loud in dev on an
  unknown id — catches renames).
- `schemas/ui_screen_defaults.schema.json` for the generated defaults file:
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
