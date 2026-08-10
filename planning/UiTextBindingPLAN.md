# UiTextBindingPLAN.md — every stat and string a movable, editable widget

Phased, agent-executable plan (same family as `NewEnemyTypesPLAN.md` /
`UI_EDITOR_PLAN.md`). Base branch: `Development`; work lands on
`UiImplementation`. Runnable via
`/execute-plan-phases planning/UiTextBindingPLAN.md UT-1-UT-7` or phase-by-phase.

## 1. Vision

Today the UI is half data-driven. `game/ui/skinning.py`'s `ScreenSkinning.apply()`
lets a designer move, restyle and hide any widget a screen registers in its
`ids: {name: (kind, widget)}` dict, and `tools/export_ui_layouts.py` records those
defaults into `data/ui/screen_defaults.json` for the editor to compose overrides
on. The HUD's readouts already use the pattern properly: `hud.py`'s `_love_text`,
`_lives_text`, `_tiles_text` are id'd label holders whose rect/font/colour come
from data while their *text* comes from `T("hud.lives", count=…)` against
`data/ui/strings.json`.

Everything else is hardcoded. The upgrade panel draws ~40 stat rows as bare
`submit_text(renderer, label, (x, y), …)` with `y += 24`, so not one of them can
be moved, recoloured or hidden from the editor, and their strings ("HP", "Damage",
"DIED LAST ROUND", "click here to change name") exist only as Python literals. The
editor is honest about this — `_screen_rules.label_is_code_owned()` disables the
Label field with *"This text is written by game code at runtime — edit it in game
code, not here."* That tooltip is the problem statement.

The editor's screen preview compounds it: it draws only the named widgets, as flat
rects or skins. A designer laying out the Build/Upgrade screen sees five boxes, not
the panel the player sees.

**Outcome.** Every stat gets two movable widgets — one for its name, one for its
number. Every user-visible string is a `data/ui/strings.json` template the editor
shows and edits. The editor viewport shows the real screen, rendered by real game
code against mock data, instead of placeholder boxes.

## 2. Decisions (with rationale)

- **D1 — Per-stat granularity, label and value as separate widgets.** A single
  "stat block" widget with a row height would be far fewer ids, but the user
  wants each stat's name and its number independently placeable. So each stat key
  registers `stat_<key>_label` and `stat_<key>_value`.
- **D2 — Templates live in `data/ui/strings.json`, globally.** One source of
  truth; editing `hud.lives` changes it everywhere. The alternative (copying the
  template into each screen's override doc) lets the same text drift between
  screens and demotes `strings.json` to a default nobody reads.
- **D3 — The editor edits templates, never invents keys.** `configure_strings()`
  fails loud on any key-set mismatch between the seeded `_STRINGS` dict and the
  JSON; that check is the guarantee that no converted string silently goes
  missing. Adding a key stays a code change. The editor may re-point a widget at
  an existing key (`text_id`) and may rewrite any template's text.
- **D4 — The preview is produced by `tools/`, never by the editor.**
  `editor/` may never import `game/` (design pillar 2), but `tools/` may, and
  `tools/export_ui_layouts.py` already constructs every screen headlessly under
  dummy SDL. It therefore also records a serialized **draw list** the editor
  replays through `engine/render`. ED-22's one-render-path holds; the layering
  rule holds; and un-converted chrome still shows up in the preview, which makes
  the conversion phases incremental instead of all-or-nothing.
- **D5 — Default geometry must not move.** Conversion re-expresses existing draw
  calls; it does not re-lay-out anything. Every phase is checked by diffing
  `data/ui/screen_defaults.json`: additions only, never a changed `rect`.

## 3. Architecture

### 3.1 `text_id` — the widget↔string binding

A label-bearing widget holder gains an optional `text_id` naming a
`data/ui/strings.json` key. Game code stops passing a literal id to `T()` and
reads the holder's instead, so re-pointing a widget at a different string becomes
a data edit. One new helper in `game/ui/widgets.py` collapses the ~90 conversion
sites:

```python
def submit_label(renderer, holder, **fmt):
    """Draw an id'd label holder: text from T(holder.text_id, **fmt),
    geometry/font/colour from the holder (post-skinning.apply), skipped when an
    override has hidden it. The one idiom every converted call site uses."""
```

`ScreenSkinning.apply()` needs no code change — its generic setattr loop already
threads any new key onto the widget, exactly as its docstring says it does for
`tint`. Its docstring's key list does need updating.

Schema work:

- `data/schemas/screen_defaults.schema.json` — widget gains optional `text_id`
  (string) and `sample` (the mock-resolved text, so the editor can show
  *"LIVES 3"* beside the template *"LIVES {count}"*).
- `data/schemas/ui_screen.schema.json` — widget gains optional `text_id`
  override.
- `data/schemas/strings.schema.json` — one property per new key, carrying its
  placeholder documentation (the file's existing convention).

### 3.2 Per-stat widget ids

`building_ui._building_stats(b)` returns `(label_text, value)` pairs today. It
becomes `(stat_key, text_id, value)` triples over a fixed vocabulary — `hp`,
`damage`, `range`, `atk_speed`, `upkeep`, `yield`, `streak`, `progress`,
`payout`, `pays_in`, `wall_hp`, `boost`, plus the `<key>_base` contrast rows
`boosted_stats()` produces. Each key registers two ids:

```
stat_hp_label      kind=label  text_id="building.stat.hp"     rect [14, 116, 0, 0]
stat_hp_value      kind=label  text_id="building.stat.value"  rect [186,116, 0, 0]
stat_damage_label  …
```

Default rects come from the existing stacking loop, so an untouched
`screen_defaults.json` is geometrically identical to today. An override moves
that one row and **does not cascade** — the rows below keep their own default
anchors, matching the convention `hud.py:_layout_readouts` already documents. A
stat the selected building lacks is simply not drawn; its id still exists in the
defaults so a designer can place it.

The exporter must therefore emit the **union** of stat ids, not one mock
building's subset: `_build_bp_upgrade` builds one mock per family (defence /
boost / wall / painter / meditator / musician) and unions their ids first-wins —
the same deterministic-union idiom `_BP_VIEW_ORDER` already uses at
`tools/export_ui_layouts.py:428-450`.

### 3.3 Preview by draw-list replay

- A recording renderer stub in `tools/` captures `submit_hud` /
  `submit_overlay_*` calls into serialized items (`{type: "rect"|"text"|
  "sprite"|"line", …}`), tagging each with the widget id in scope when there is
  one.
- New generated file `data/ui/screen_previews.json` plus
  `data/schemas/screen_previews.schema.json`, keyed `{screen_id: {view:
  {items: [...], mock_note: str}}}`. Generated, committed, deterministic, never
  hand-edited — the contract `screen_defaults.json` already carries in
  `data/CLAUDE.md`.
- `ViewportPanel._submit_screen_items` (`editor/panels/viewport.py:1723`) replays
  the item list first, then draws selection chrome and handles on top.
- **Live editing:** while a widget is dragged or resized, the editor suppresses
  that widget's tagged items and renders it itself at the live rect (today's
  `_submit_screen_widget` path), so drag feedback stays immediate. On release,
  and on Save, the preview is regenerated.
- **Regeneration** reuses the tracked-`QProcess` plumbing behind the existing
  "Refresh Layouts" toolbar button (`editor/run_controls.py:42`,
  `editor/main.py:275`); the exporter grows `--overrides <path> --screen <id>` so
  the editor can render the *unsaved* doc from a temp file. No new
  infrastructure.

### 3.4 Editor form (`editor/panels/screen_details.py`)

- The **Label** row stops being disabled for dynamic labels. When the selected
  widget has a `text_id`, it becomes **Text template**: it edits the
  `strings.json` entry, shows the resolved `sample` beneath it, and warns *"used
  by N widgets"* when the key is shared. Static-label widgets keep today's
  per-widget `label` override unchanged.
- `_screen_rules.label_is_code_owned()` narrows to "no `text_id` and not a pinned
  static title". `TOOLTIP_LABEL_CODE_OWNED` survives for what genuinely stays
  code-owned (a `field`'s user-typed contents).
- A **Text ID** combo re-points a widget at another existing key (D3).
- Template edits are undoable through `UIScreenSession.push_string(text_id, old,
  new)` and saved with the screen. Because strings are global, the panel shows
  the strings doc's dirty state separately from the screen doc's.

## 4. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| UT-1  | Mechanism: `text_id`, `submit_label()`, schemas, `push_string` | **done** |
| UT-2  | Preview pipeline: recording renderer, `screen_previews.json`, editor replay | **done** |
| UT-3  | `building_panel` conversion — all five views, the stat vocabulary | **done** |
| UT-4  | `hud.py` conversion | **done** |
| UT-5  | The remaining 12 screens + `effects.py` | **done**  |
| UT-6  | Editor Text-template form | **done** |
| UT-7  | Eyeball pass, docs | **docs done**, playtest pending |

UT-1 and UT-2 are independent. UT-3/4/5 all depend on UT-1. UT-6 depends on UT-1
and is sequenced after UT-3 so it has real bindings to drive. UT-7 is last by
definition.

### Phase UT-1 — the mechanism

`game/ui/widgets.py` gains `submit_label()`; `Button` gains an optional
`text_id`. `game/ui/skinning.py`'s docstring key list grows `text_id` (no code
change — verify the setattr loop threads it). The three schemas above are
extended. `editor/ui_screen_session.py` gains `push_string`.

No screen is converted; **zero visual change** and `screen_defaults.json` is
byte-identical.

**Tests**: `submit_label` honours `visible`, resolves through `text_id`, and
falls back to a holder's `.label` when it has no `text_id`; `ScreenSkinning.apply`
threads a `text_id` override onto a holder; `push_string` is undoable and prunes
to absent on reset.

**Exit gate**: `py tools/smoke.py`; `py -m pytest tools/tests/test_ui_skinning.py
tools/tests/test_ui_screen_session.py -x -q`; exporter re-run produces no diff.

### Phase UT-2 — the preview pipeline

The recording renderer, `data/ui/screen_previews.json` + its schema, the
exporter's `--overrides`/`--screen` flags, the editor replay in
`_submit_screen_items`, drag suppression, and regenerate-on-release wired to the
existing tracked `QProcess`.

Determinism is the risk: feed the recorder a **fixed `anim_ms`** and never
capture a wall-clock value, or the generated file churns on every run.

**Tests**: the recorder serializes each HUD primitive round-trip; the exporter is
byte-identical on a second run; `--overrides` shifts exactly the widget the
override names; the editor replays a fixture item list without importing `game`
(an import-guard assertion already exists for the layering rule — extend it).

**Exit gate**: `py tools/smoke.py`; exporter run twice, second run a no-op;
`py -m pytest tools/tests/test_export_ui_layouts.py tools/tests/test_viewport*.py
-x -q`; open the editor and confirm a screen renders as its real self.

### Phase UT-3 — `building_panel`

The stat-key vocabulary and `_building_stats` triples; per-stat `*_label` /
`*_value` id pairs registered in `BuildingUI.ids`; the exporter's per-family
union in `_build_bp_upgrade`; and every remaining literal in `building_ui.py` —
`_submit_unlock:1294`, `_submit_construct:1310`, `_submit_upgrade:1359`,
`_submit_base_info:1548`, `_submit_boss_popup:1573`, `ConstructPreview.submit:270`,
`MovePreview.submit:434`. Roughly 40 sites: titles, the name-box placeholder,
"Damage dealt"/"Damage taken", "DIED LAST ROUND", the next-tier card, upgrade
hints, cost/time rows.

The green next-level hover preview must keep working: it compares by stat key
now, not by label text — which is strictly more robust, since a renamed label
used to silently break the match.

**Tests**: every stat key resolves to a registered id pair; a rect override moves
one row and leaves its neighbours' rects untouched; hiding a row's two widgets
removes it without reflow; the hover preview still greens a changed value after
a template rename.

**Exit gate**: `py tools/smoke.py`; `py -m pytest tools/tests/test_building_ui.py
-x -q`; `git diff data/ui/screen_defaults.json` shows additions only.

### Phase UT-4 — `hud.py`

The readouts already bind through `T()`; give each a `text_id` attribute so the
editor can see and re-point it, and convert what remains — the income-breakdown
tooltip rows, the lightning readout, the phase banner. ~20 sites.

**Tests**: each HUD readout's `text_id` matches the key it renders; a `text_id`
override re-points a readout.

**Exit gate**: as UT-3, with `tools/tests/test_hud.py`.

### Phase UT-5 — the remaining screens

`levelup`, `boss_cutscene`, `cheat_menu`, `game_over`, `main_menu`, `pause`,
`settings`, `credits`, `add_name`, `game_log`, `tutorial_message`, `overlays`,
plus `effects.py`'s tooltips and floaters. The three code-only screens
(`highscores`, `player_intro`, `debug_settings`) were left OUT.
**Scope deviation from this plan's own text, on purpose:** widening
`SCREEN_IDS` from 13 to 16 adds three entries to the generated
`screen_previews.json`, which would break UT-5's byte-empty-diff
invariant — the one signal that says the conversion changed nothing the
player sees. Bringing them in is a clean follow-up task of its own: add
them to `SCREEN_IDS`, regenerate BOTH artifacts, and re-baseline.

Dynamic-count content (levelup's option boxes, construct cards, the boss-history
popup) keeps inheriting the screen's `defaults` section — that mechanism is
unchanged; only their *strings* move into `strings.json`.

**Exit gate**: as UT-3, across the affected test modules.

### Phase UT-6 — the editor form

The Text-template row, sample display, Text ID combo, shared-key warning,
`_screen_rules.label_is_code_owned` narrowing, and the separate strings dirty
state.

**Tests** (Qt tier): selecting a widget with a `text_id` shows an enabled Text
template row carrying the template, not the resolved sample; editing it pushes an
undoable command and writes `strings.json` on save; selecting a widget without
one keeps today's disabled-label behaviour and tooltip.

**Exit gate**: `py -m pytest -m editor -x -q` on the affected modules;
`py tools/smoke.py`.

### Phase UT-7 — eyeball pass and docs

Live game + editor pass per §5, then the durable-rule updates:
`game/ui/CLAUDE.md` (the 10L-B widget contract gains `text_id`; the
`submit_label` idiom), `data/CLAUDE.md` (the new generated file and its schema
pairing; `text_id`/`sample` in the widget record), `editor/panels/CLAUDE.md`
(preview replay, drag suppression, the Text-template row).

## 5. Cross-phase verification (once, at the end)

- `py tools/smoke.py` and the **full** `py tools/testgate.py check` — `GATE PASS`,
  no affected-tier shortcut on the final handoff.
- `py tools/export_ui_layouts.py` twice; the second run must produce no diff.
- Live `py game/main.py`: start a run, place a Stone Thrower, open its upgrade
  panel. Every stat row, the tier line, the name box and the hints look exactly
  as they do on `Development`. Hovering the upgrade button still greens the
  next-level values.
- Live `py editor/main.py` → **Screens → building_panel → upgrade**: the viewport
  shows the real panel with mock data, not boxes. Drag `stat_damage_value` 40px
  right — the number moves live and the surrounding preview re-renders on
  release. Edit `stat_hp_label`'s template from `HP` to `Health`, save, and
  confirm the game reads *Health*. Hide `stat_upkeep_label`/`_value` and confirm
  the row vanishes in game with **no reflow** below it.

## 6. Risks / open items

- **`planning/UiResolutionPLAN.md` collides with this plan.** It halves every UI
  rect in the same files. The two must not run concurrently; whichever lands
  second re-derives its constants. Flag at kickoff.
- **`configure_strings`'s fail-loud check makes every phase all-or-nothing per
  key.** A converted literal that reaches `_STRINGS` but not `strings.json`
  (or its schema) fails boot, not a test. Add both in the same edit; `smoke.py`
  catches it immediately.
- **The recorded draw list can double-draw.** If the editor replays a widget's
  tagged items *and* renders the widget itself, the designer sees ghosting. The
  suppression rule (§3.3) is the fix and needs a test, not just care.
- **Preview staleness is a UX cliff, not a correctness bug.** Between an edit and
  a regeneration the preview shows old geometry for everything except the widget
  being dragged. If regenerate-on-release proves too slow in practice, the
  fallback is an explicit "Refresh preview" button rather than a debounce that
  fires mid-drag.
- **Per-stat ids multiply the id namespace fast** (~24 new ids on
  `building_panel` alone, before the other screens). The widget list in
  `screen_details.py` is a flat `QListWidget`; it will need grouping or filtering
  to stay usable. Treated as UT-6 polish, but call it out if it bites earlier.
- **The three code-only screens are new surface.** They have never had override
  docs; giving them one is the right call for consistency but is the least-tested
  part of UT-5.
