# Phase UH-6 — Engine + data + editor + game: theme data (fonts / palette / tint)

Plan: `planning/UiEditorHonestyPLAN.md` §4 UH-6 (decisions **D5**, **D6** and the
"UH-6 parity risk" item in §5 are binding). Branch: `phase-UH-1-UH-6-umbrella`.
Packages: **engine + data + editor + game** — the plan sanctioned the span; read
`engine/CLAUDE.md`, `data/CLAUDE.md`, `game/ui/CLAUDE.md`, `editor/CLAUDE.md` +
`editor/panels/CLAUDE.md`. The editor half MUST be executed by opening the
`/add-editor-feature` skill (`.claude/commands/add-editor-feature.md`) — it is a
skill-table row, not optional.

**Merge-order check before you write a line of code.** UH-6 merges AFTER UH-3
(both edit `editor/panels/screen_details.py`; §3). If UH-3's honest-controls
change (Color disabled + tooltip on skinned widgets) is not on your base, STOP
and say so — do not re-implement its disable logic here.

---

## 1. Behavioral spec

### 1.1 Fonts become data (`data/ui/fonts.json`)

Today the 7 font presets are hardcoded: `engine/render/fonts.py:17-25`
(`_FONT_SPECS`: `sm 9 / md 11 / lg 13 bold / xl 18 bold / xxl 26 bold /
hud_phase 14 / hud_lvl 12`). After UH-6:

- **NEW** `data/ui/fonts.json` — exactly those 7 keys, each
  `{"size": <int>, "bold": <bool>}`, values verbatim from `_FONT_SPECS`
  (D5: "current hardcoded values as schema-checked committed content").
- **NEW** `data/schemas/fonts.schema.json` — draft 2020-12, `$id`,
  `additionalProperties: false`, **all 7 keys required** (game code names them;
  a deletable key would be a silent break). `size` bounds 4–72, `description`
  per key (D-12). New preset keys are a schema change and are deliberately out
  of scope (v1: the fixed set).
- Stem pairing is automatic: `tools/smoke.py:61` resolves
  `schemas/<stem>.schema.json` regardless of subdirectory (verified —
  `data/ui/screen_defaults.json` already pairs this way, `tools/smoke.py:34-38`).
  No new directory exception.
- The game **loads and applies it at boot** (§2.2). A missing/invalid file
  fails LOUD (D-2 — this is data, not art; E-37 does not apply).
- **`layout_h` stays authoritative and untouched** — the pinned `_LAYOUT_H`
  table at `engine/render/fonts.py:43-51` and `layout_h()` at `:54-67` are the
  W3-4 cross-platform invariant (`tools/tests/test_layout_h_invariant.py:1-19`).
  `fonts.json` carries **no** layout heights. Consequence, stated honestly: a
  designer who enlarges `lg` changes drawn glyphs but NOT stored layout rects —
  text can overflow its widget. That is the pinned-layout contract, not a bug;
  the Theme panel says so in a tooltip (§2.4).

### 1.2 The UI palette becomes data (`data/ui/palette.json`)

Today the palette is ~17 module constants at `game/ui/widgets.py:37-54`
(`C_GOLD (255,200,50)`, `C_RED`, `C_HP_GREEN`, `C_HP_RED`, `C_GREEN_STAT`,
`C_UI_PANEL`, `C_UI_BORDER`, `C_UI_BTN`, `C_UI_BTN_HOVER`, `C_UI_BTN_ACTIVE`,
`C_UI_BTN_DISABLED`, `C_UI_TEXT`, `C_UI_TEXT_DIM`, `C_HIGHLIGHT`,
`C_RANGE_HIGHLIGHT`, `C_PANEL_STONE`, `C_PANEL_INSET` — executor: enumerate the
block exactly; the count here is from a grep of `^[A-Z_]+ *= *\(` and may miss
an oddly-formatted line). Consumers: 14 `game/` files, 125 occurrences
(measured), all importing early-bound via `from .widgets import C_…`
(e.g. `game/ui/pause.py:18`, `main_menu.py:24`, `hud.py:27`).

After UH-6:

- **NEW** `data/ui/palette.json` — one key per constant, snake_case with the
  `C_` prefix dropped (`gold`, `ui_panel`, `panel_stone`, …), each an RGB
  3-int array 0–255, values verbatim from `widgets.py:37-54`.
- **NEW** `data/schemas/palette.schema.json` — all keys required,
  `additionalProperties: false`, D-12 descriptions ("what does this color
  paint").
- The game loads it at boot and re-binds the constants (§2.3). **`widgets.
  COND_LABELS` colors and every other inline color literal stay code** —
  deliberately out of scope (the palette IS the `C_*` block, nothing more).
- **Parity is pinned**: with the stock files (or with no `configure_*` call at
  all — the unconfigured defaults ARE today's values), every screen emits the
  byte-identical HUD-primitive stream, i.e.
  `tools/tests/test_ui_skinning.py::_BASELINE` (`:183`) still matches
  (`TestGoldenParity`, `:405-412`). Plan §5: "if either goes red, the phase is
  wrong, not the pin."

### 1.3 Optional per-widget `tint` for skinned widgets (D6)

- `data/schemas/ui_screen.schema.json` widget properties (`:70-110`) gain one
  OPTIONAL key `tint` (3–4 ints 0–255, same shape as `color` at `:71-80`).
- Game: a skinned widget with a `tint` override multiplies its sheet at draw
  time. The whole draw path **already exists in the engine** (verified):
  `HudSprite.tint` (`engine/render/hud.py:52`) → copied onto the `DrawCall`
  (`engine/render/renderer.py:168`) → `surface.fill(call.tint,
  special_flags=pygame.BLEND_RGBA_MULT)` (`engine/render/backend.py:185-187`).
  UH-6 only wires the JSON key into the `HudSprite` submissions
  (`game/ui/widgets.py` `Button.submit` skinned branch `:253-256` and
  `submit_panel` skinned branch `:115-118`). `tint` reaches the widget object
  for free — `ScreenSkinning.apply` is a generic setattr loop
  (`game/ui/skinning.py:136-141`, lists → tuples via `_as_tuple`).
- **Omitted `tint` = today's rendering, pinned**: `HudSprite.tint` defaults to
  `None`, so an un-tinted submission is field-for-field equal to the current
  one — the existing `test_button_skin.py` / `test_ui_skinning.py` pins hold
  by construction.
- Tint applies to **any widget that resolves to a skin** (per-widget `skin`
  override or a kind-matched `defaults.button_skin`/`panel_skin`), buttons AND
  panel-kind holders — because the editor already draws every skinned widget
  with a tint and restricting the game to buttons only would create a new
  silent no-op (D3).
- **This fixes an existing editor lie** (part of the honesty story): the
  editor's screen mode currently renders a skinned widget's `color` override
  AS a tint (`editor/panels/viewport.py:933-935`) while the game ignores
  `color` on skinned widgets entirely (`skinning.py:59-66` `button_kwargs`
  docstring). After UH-6 the editor tints from `tint` and never from `color`
  (§2.5) — what the editor shows is what the game draws.

### 1.4 A NEW editor Theme panel (built with `/add-editor-feature`)

- A **"Theme" leaf under the selector's "ui" category node**, sibling of the
  "Screens" branch (`editor/panels/CLAUDE.md` §B4 selection pattern) — the
  selection-driven way to reach a global-ish document (ED-3).
- The panel edits `data/ui/fonts.json` (per-key size spinbox, schema-bounded
  4–72, + bold checkbox) and `data/ui/palette.json` (per-key color swatch
  button → `QColorDialog`). Edits are STAGED with dirty dots + one **Save**
  button through `engine.data_io.write_validated` — the `balancing.py` staged
  pattern (`editor/panels/CLAUDE.md` Phase 4), not the screen-session undo
  pattern.
- **The font combo is sourced from data**: `screen_details.py`'s hardcoded
  `_FONT_KEYS` tuple (`editor/panels/screen_details.py:53-56`, comment admits
  the duplication) is replaced by keys read from `data/ui/fonts.json` (§2.6).

### 1.5 Honest repurposing of the details-panel Color control (ties to UH-3)

UH-3 (D3) disables the Color picker on skinned widgets with tooltip "colors
come from the sprite sheet". UH-6 upgrades that disabled state into **tint
mode**: on a widget that resolves to a skin the same control is ENABLED,
relabelled **"Tint"**, writes the `tint` key (undoable `push_field`), tooltip
"multiplies the sprite sheet — white = unchanged". Unskinned widgets keep the
plain Color behavior (writes `color`, `screen_details.py:130-134`,
`_on_color_clicked` `:489-497`). The disabled-never-lying rule (D3) is
preserved: no control silently writes a key the game ignores.

---

## 2. Architecture plan

Order of implementation: 2.1 → 2.2/2.3 (parity pin green here) → 2.4–2.6
(editor) → docs. Run the named test modules (§4) after each stage.

### 2.1 Data + schemas first

Author `fonts.schema.json` / `palette.schema.json` via `dumps_deterministic`,
then the two content files via `write_validated` (never hand-format — house
rule). `py tools/smoke.py` proves stem pairing picked them up.

### 2.2 Engine: `engine/render/fonts.py` boot-time configuration

- Add `configure_fonts(doc)`: takes the LOADED `fonts.json` dict
  (`{key: {size, bold}}`), replaces the entries of `_FONT_SPECS` **in place**
  (same 7 keys — validate the key set, fail loud on drift) and clears
  `_cache` (`:70`) so stale `SysFont` objects are rebuilt. Pure-Python + the
  already-sanctioned pygame import; no `data_io` call inside the engine module
  — the HOST loads and passes the dict (mirrors how `engine.tilemap` consumes
  docs; keeps fonts.py data-dir-free for bare test construction).
- The current `_FONT_SPECS` literals remain as the **unconfigured defaults** —
  the `ScreenSkinning.empty()` precedent (`game/ui/skinning.py:113-122`): bare
  test/tool construction stays deterministic and byte-identical. A pin test
  (§4, `test_theme_data.py`) asserts defaults == the stock fixture doc, so the
  fallback can never drift from the committed content silently (this is the
  answer to the "no py+json dual store" pillar: one value set, committed as
  data, mirrored as a fallback that a test proves equal).
- **Do NOT touch `_LAYOUT_H` / `layout_h`** (`:43-67`). Do NOT call
  `configure_fonts` from `tools/export_ui_layouts.py` — the exporter's output
  must not depend on theme data (layout is pinned).

### 2.3 Game: palette load + consumer re-pointing

- `game/ui/widgets.py` gains `configure_palette(doc)`: maps `gold` →
  module attribute `C_GOLD` etc. (mechanical `"C_" + key.upper()`), rebinds
  the module globals, fails loud on an unknown/missing key. Current literals
  stay as unconfigured defaults (same argument as 2.2).
- **Re-pointing strategy** (the "wide but mechanical" move, plan §5): every
  consumer switches from early binding (`from .widgets import C_GOLD`) to
  attribute access (`from . import widgets` … `widgets.C_GOLD`) so a boot-time
  rebind is seen everywhere. 14 files / 125 occurrences (measured). Inside
  `widgets.py` itself, function-body references already late-bind via module
  globals — but **default arguments do not**: `submit_panel(..., fill=
  C_UI_PANEL, border=C_UI_BORDER)` (`:109`) binds at def time and MUST become
  `fill=None, border=None` resolved in the body. Executor: grep for `=C_` in
  def lines across `game/ui/` — every one is this trap.
- `game/main.py` boot (after `data_dir` is known, before the `Shell`/screens
  are built): `data_io.load_validated` both files against their schemas, call
  `fonts.configure_fonts(...)` + `widgets.configure_palette(...)`. Fail loud.
- Tint wiring: `Button.submit` skinned branch (`widgets.py:253-256`) passes
  `tint=getattr(self, "tint", None)` (the override setattrs it;
  `_as_tuple` already made it a tuple); `submit_panel` grows `tint=None`
  passed into its `HudSprite` (`:115-118`); the id'd skinned-holder call
  sites that already thread `skin=holder.skin` add
  `tint=getattr(holder, "tint", None)` — same mechanical sweep B2 used for
  `skin`. No change to `skinning.py` logic (generic apply covers `tint`);
  update its module docstring only.

### 2.4 Editor: Theme panel (via `/add-editor-feature`, all six skill steps)

- **NEW** `editor/panels/game_theme.py` (`GameThemePanel`) — named to avoid
  colliding with `editor/theme.py`, the Qt chrome theme (which this phase must
  NOT touch — that file is light/dark chrome only, `editor/CLAUDE.md`).
  `data_dir=None` injection; loads both docs + schemas fresh on
  `set_theme()`/entry; spin ranges from schema `minimum`/`maximum` (ED-30);
  staged edits + dirty dots + Save → `write_validated` (ED-31); a per-key
  reuse of `_NoWheelSpinBox`/`_NoWheelComboBox` IMPORTED from
  `editor.panels.balancing` (never copied). A static tooltip/label notes the
  §1.1 limitation: "font size changes drawn text only; stored layouts are
  pinned (`layout_h`)".
- **NEW pure helper** `editor/theme_ops.py` (Qt-free, pygame-free): load /
  validate / write round-trip + the `fonts.json`-keys reader the font combos
  use. Goes in `test_editor_viewport.TestPurity`'s import list (as does
  `game_theme`).
- `editor/panels/selector.py`: "Theme" leaf under the "ui" category, mirroring
  the Screens branch structurally (`theme_selected()` signal, never
  `node_selected`). `editor/main.py` `MainWindow`: `_on_theme_selected` →
  `right_stack` → `GameThemePanel`; on panel Save, reconfigure
  `engine.render.fonts` in-process and repaint the viewport so previews track
  the new theme (chrome theme untouched).
- Editor boot: `MainWindow` loads `data/ui/fonts.json` (graceful `{}` degrade
  here — the editor must open on a broken tree) and calls `configure_fonts`
  so screen-mode preview text matches the game.

### 2.5 Editor: honest tint in screen mode

- `editor/panels/viewport.py:933`: `tint = tuple(override["tint"]) if "tint"
  in override else None` — `color` no longer leaks into the skinned draw
  (§1.3; this is the WYSIWYG half of D6).
- `editor/panels/screen_details.py` (AFTER UH-3 — §3): reuse UH-3's
  skin-resolution predicate (whatever name its brief lands; the same
  resolution the viewport uses at `viewport.py:924-929` — per-widget `skin`
  else kind-matched default). In `_populate_widget_form` and at UH-3's
  recompute points (skin assigned/cleared): skinned → row label "Tint",
  button writes/resets the `tint` key (`push_field(widget_id, "tint", …)`),
  enabled, multiply tooltip; unskinned → today's "Color" behavior verbatim.
  The reset "↺" (`_field_row` pattern, `:132-134`, enablement `:395`)
  targets whichever key is active.
- `editor/panels/screen_details.py:53-56`: delete `_FONT_KEYS`; both font
  combos (`_populate_font_combo`, `:267-271`) populate from
  `theme_ops.font_keys(data_dir)` with the literal 7-tuple as fallback when
  the file is unreadable (editor-side graceful degrade).
- **Optional-but-specced** (small, in the honesty spirit — cut it FIRST if
  the phase runs long, and say so): `editor/panels/_screen_primitives.py`
  takes an injectable palette dict (fed from `data/ui/palette.json` at
  screen-mode entry) for its fallback-widget colors, so a palette edit shows
  in unskinned previews too. Its "aligned by eye" drift note in
  `editor/CLAUDE.md` shrinks accordingly.

### 2.6 Docs

`data/CLAUDE.md` (two new files + schemas), `engine/render/CLAUDE.md`
(`configure_fonts`, layout_h unchanged), `game/ui/CLAUDE.md` (palette
re-point + tint), `editor/panels/CLAUDE.md` (Theme panel + tint mode). Router
untouched.

---

## 3. File scope + shared-file contract (binding)

**NEW**: `data/ui/fonts.json` · `data/ui/palette.json` ·
`data/schemas/fonts.schema.json` · `data/schemas/palette.schema.json` ·
`editor/panels/game_theme.py` · `editor/theme_ops.py` ·
`tools/tests/test_theme_data.py`.

**MOD**: `engine/render/fonts.py` (add `configure_fonts` below `_LAYOUT_H`,
above `_cache = {}` at `:70`; nothing else) · `data/schemas/ui_screen.schema.json`
(one `tint` property inside `patternProperties` widget object, alphabetical
between `skin` `:95-97` and `text_color` `:98`) · `game/ui/widgets.py` ·
the 13 `game/ui/*.py` palette consumers + `game/ui/effects.py` (import-style
sweep only; no behavior) · `game/main.py` (boot load/configure block) ·
`editor/panels/viewport.py` (`:933` only) · `editor/panels/screen_details.py`
(§2.5 regions) · `editor/panels/selector.py` · `editor/main.py` ·
`conftest.py` (ONE line: `"test_theme_data": "core"` in TIERS —
`test_tiers.py` fails without it) · `tools/tests/test_button_skin.py`,
`test_editor_panels.py`, `test_editor_viewport.py` (added tests) · the four
CLAUDE.md docs (§2.6).

**SHARED-FILE WARNING — `editor/panels/screen_details.py`:**
- **UH-3 modifies it first** (disables Color on skinned widgets + tooltip;
  adds the skin-resolution helper). **UH-6 merges after UH-3** and REPURPOSES
  that exact disabled state: skinned no longer means "Color disabled", it
  means "the control is Tint" (§1.5, §2.5). Do not duplicate UH-3's
  resolution helper — import/reuse it; keep its tooltip text for the inert
  `color` key semantics. If UH-3's diff is absent from your base, STOP.
- UH-2 (view-filtered widget list) and UH-4 (display names) also touch this
  file in DIFFERENT regions (list population / labels). Rebase over whatever
  has landed; conflicts should be disjoint hunks. UH-6 touches only: the
  Color/Tint row + its handlers/reset, `_FONT_KEYS`/`_populate_font_combo`,
  and `_populate_widget_form`'s recompute.
- No other UH phase touches `ui_screen.schema.json`, `fonts.py`, `widgets.py`,
  `viewport.py:933`, or the new files (verified against the plan's per-phase
  file lists).

**Must NOT touch**: `editor/theme.py` (Qt chrome) · `tools/export_ui_layouts.py`
· `data/ui/screen_defaults.json` (UH-1/UH-4 own its regeneration) ·
`engine/render/fonts.py`'s `_LAYOUT_H`/`layout_h` · `tools/tests/
test_ui_skinning.py`'s `_BASELINE` (if you feel the need to edit the baseline,
the phase is wrong — plan §5).

---

## 4. Exit gate + Quick Test

### Commands

```bash
py tools/smoke.py
# Explicit modules — REQUIRED because of the testgate --affected vacuous-pass
# bug (tools/testgate.py:222-238, plan §5): the Graphify narrowing is known to
# under-select editor-tier modules, so an editor-heavy phase can "pass" a gate
# that ran none of its tests. Run these by name while iterating:
py -m pytest tools/tests/test_theme_data.py tools/tests/test_ui_skinning.py \
    tools/tests/test_layout_h_invariant.py tools/tests/test_button_skin.py \
    tools/tests/test_ui_layout_export.py tools/tests/test_editor_panels.py \
    tools/tests/test_editor_viewport.py tools/tests/test_details_panel.py -q
py tools/testgate.py check          # ONCE, at handback. GATE PASS = zero.
```

### Tests (NEW `tools/tests/test_theme_data.py`, tier `core`, unless noted)

Every test that calls `configure_fonts`/`configure_palette` MUST
`addCleanup`-restore the module defaults — these mutate module state, and a
leaked configure poisons every later parity test in the process. Never read
live `data/ui/*.json` in an assertion — pin fixture docs (house rule).

1. **Stock parity pin (the crux)**: `configure_fonts` + `configure_palette`
   with fixture docs equal to today's literals → `_screen_captures()` (import
   from `test_ui_skinning`, the `test_layout_h_invariant.py:27` precedent)
   `==` `_BASELINE`, every screen. Byte-identical stream, D5 delivered.
2. **Fallback-equals-stock pin**: the unconfigured module defaults equal the
   fixture stock docs (kills silent dual-store drift, §2.2).
3. **`layout_h` authority**: `configure_fonts` with every size +6 → exporter
   output into a tempdir is byte-identical to an unconfigured run (mirror
   `test_layout_h_invariant.py:57`); existing
   `test_layout_h_invariant.py` stays green untouched.
4. **Tint applied / omitted**: skinned `Button` with `tint` attr → `HudSprite`
   carries the tuple; without → `tint is None` and the emitted items equal
   today's (extend `test_button_skin.py`); `submit_panel(skin=…, tint=…)`
   likewise; `ScreenSkinning.apply` flows a `tint` list override onto the
   widget as a tuple; schema accepts `tint` and rejects a 2-int one.
5. **Palette rebind reaches consumers**: after `configure_palette`, a screen
   submit emits the new color (proves the attribute-access re-point + the
   default-arg sentinel fix; pick one button + `submit_panel`).
6. **Editor** (in `test_editor_panels.py` / `test_editor_viewport.py`, tier
   `editor`): Theme panel round-trips via `write_validated` against a
   `TempDataCase` copy (edit gold → Save → file validates, value persisted,
   dirty clears); font combo lists the temp tree's `fonts.json` keys; on a
   skinned widget the control is Tint and `push_field` writes/undoes `tint`;
   on an unskinned widget it still writes `color`; viewport screen mode tints
   from `tint` and NOT from `color` (regression on `viewport.py:933`);
   `TestPurity` imports `game_theme` + `theme_ops`.

Smoke green proves both new data files validate through stem pairing.

### Quick Test (human, in editor + game)

1. `py editor/main.py` → selector → ui → **Theme** → set `gold` to e.g. bright
   cyan → Save. Play (subprocess): the main menu title, HUD gold accents and
   panel headers render cyan — **menus recolor in-game from the Theme panel**.
2. Theme → restore gold → Save → Play: stock look, pixel-identical to before
   this phase.
3. Selector → ui → Screens → `building_panel` → select a skinned button
   (e.g. `action_btn`, skin `ui_button_panel`) → the details row reads
   **Tint** → pick blue → the editor preview multiplies blue immediately →
   Save → Play → open the building panel: the same button is blue in-game;
   reset ↺ → stock sheet colors return.
4. Select an unskinned label → the row still reads **Color** and behaves as
   before (UH-3's honesty intact).
