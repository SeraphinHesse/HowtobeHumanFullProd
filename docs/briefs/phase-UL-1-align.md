# Phase UL-1 — Text alignment becomes editable

Plan: `planning/UiLayeredWidgetsPLAN.md` §3 Section S1 / Phase UL-1 (build-order
line 158-192), decision **D5 binding** (golden parity is the landing condition
of every runtime phase — `test_ui_skinning.py`'s baselines and
`data/ui/screen_previews.json` must stay byte-identical). Branch:
`ul-section-S1` (already checked out). Package docs: `game/ui/CLAUDE.md` (UT-1
`text_id`/`submit_label` section, "UI screen customization", "`hud.round_label`
carries its own alignment"), `data/CLAUDE.md` "UI screen data", `editor/panels/
CLAUDE.md` §"Phase B4 — screen mode".

---

## 1. Behavioral spec (with citations)

**The gap being closed.** `align` exists in the game and the editor today, but
in two disconnected, incomplete forms — neither lets a designer pick it:

- **Game-side, `align` is already a real per-holder attribute `submit_label`
  reads**, just never settable from the override doc. `widgets.submit_label`
  resolves alignment via `align = getattr(holder, "align", "left") or "left"`
  when the call site does not pass its own (`game/ui/widgets.py:276-277`), and
  `widgets.label_holder(...)` seeds every id'd label holder with
  `align="left"` by default (`game/ui/widgets.py:218-219,238`). One holder
  already varies it in code: `hud.round_label` sets `align="center"` directly
  on the holder rather than at the call site (`game/ui/CLAUDE.md:1635-1644`,
  "If you add a label whose alignment never varies, declare it on the
  holder"). `ScreenSkinning.apply`'s generic setattr loop already threads ANY
  override key onto a widget for free — `tint`/`text_id` ride this way with no
  `_SPEC_TO_ATTR` entry (`game/ui/skinning.py:38-46,143-160`) — so once
  `align` is a legal override key, `submit_label` picks it up with **zero
  `game/ui/skinning.py` or `game/ui/widgets.py` behavior change**; `_as_tuple`
  passes a plain string through unchanged (`game/ui/skinning.py:49-53`).
- **`data/schemas/ui_screen.schema.json`'s per-widget override object has no
  `align` key at all** (`data/schemas/ui_screen.schema.json:77-142` — the
  `additionalProperties: false` object under `widgets.patternProperties`
  lists `color/font/label/parent/rect/skin/text_color/text_id/tint/visible`,
  alphabetically sorted, no `align`). This is the actual gap: a designer has
  no way to author alignment at all today.
- **`align` DOES already exist elsewhere, but only as an editor MEASURING
  HINT on the GENERATED `screen_defaults.json`** (a different file, a
  different schema): `data/CLAUDE.md:774-789` — "`widget.font_key` /
  `widget.align` (editable-ui-widgets): two more OPTIONAL keys on a
  `screen_defaults.json` widget record, both pure DRAW HINTS for the editor —
  **nothing in the game reads them back**... `align` is `left|center|right`,
  which way the glyphs spread from the stored x." This is what the plan's
  goal text means by "editor-only measuring hint" — it is written by
  `tools/export_ui_layouts.py::_widget_entry` from whatever the CODE holder's
  `align` is at mock time, and only used to size the editor's hit box for a
  position-only text anchor (`(x, y, 0, 0)` rects — every HUD readout, the
  phase banner, `boss_cutscene`'s headline, ~40 `building_panel` stat cells,
  `game/ui/CLAUDE.md:1157-1176`). It is NOT designer-editable and does not
  affect the game's draw.
- **The editor's interaction-rect box only ever reads the DEFAULT's `align`,
  never a designer's OVERRIDE.** `editor/panels/viewport.py`'s
  `_interaction_rect` calls `_screen_primitives.interaction_rect(...,
  align=spec.get("align", "left"))` where `spec` is exclusively
  `defaults.get("widgets", {}).get(widget_id)` — the `screen_defaults.json`
  entry (`editor/panels/viewport.py:713-724`). It never consults
  `self._screen_session.doc.get("widgets", {}).get(widget_id, {})` (the
  override doc) the way its sibling `_widget_font_key` two methods below it
  does (`override.get("font") or spec.get("font_key") or style.get("font") or
  "md"`, `editor/panels/viewport.py:726-734`). So once a designer sets
  `align` in the override, the editor's own hit/outline box for a
  position-only anchor would still measure against the OLD default alignment
  — the box would land beside the glyphs, not on them, exactly the bug
  `game/ui/CLAUDE.md:1635-1644`'s `hud.round_label` story describes for the
  pre-fix state. `_screen_primitives.interaction_rect` itself is already
  correct and needs no signature change — it takes `align` as a plain kwarg
  and shifts `x` for `"center"`/`"right"` (`editor/panels/
  _screen_primitives.py:93-120`); only the CALLER's align *source* is wrong.
- **`editor/panels/screen_details.py`'s widget form has no Alignment
  control.** The X/Y/W/H rect row, Parent, Skin and Font rows are built in
  `__init__` via the shared `_field_row(...)` + `form.addRow(...)` +
  reset-button pattern (`editor/panels/screen_details.py:255-299`); nothing
  after the Font row (`:295-299`) offers `align`.

## 2. Architecture plan

**Schema (`data/schemas/ui_screen.schema.json`)** — add exactly one property
to the per-widget override object (the `patternProperties` sub-schema at
`:77-141`): `"align": {"type": "string", "enum": ["left", "center",
"right"]}`, inserted alphabetically **immediately after the opening
`"properties": {` (`:78`) and before `"color"` (`:79`)** — `align` sorts
before every existing key in this object, matching the file's existing
alphabetical-key convention. No `required` change (optional,
absent = "left", matching `submit_label`'s own fallback). **Do not touch any
other key, do not reformat/re-sort/re-indent anything else in the file** — S2
is concurrently adding a `layers` key to the SAME per-widget object (it sorts
between `"label"` and `"parent"`, nowhere near `align`'s insertion point), and
a wider diff here creates exactly the surgical-merge risk the plan calls out.

**`game/ui/widgets.py`** — no behavior change expected; this is a
**verification + regression-test task**, not a rewrite. Confirm (via the new
test file, §below) that:
1. every id'd label-kind widget already routes its text through
   `submit_label(renderer, holder, ...)` rather than a raw `submit_text(...)`
   call (scouted: every `hud.py`, `building_ui.py` (`txt[...]` holders),
   `add_name.py`, `boss_cutscene.py`, `cheat_menu.py`, `game_over.py`,
   `levelup.py`, `settings.py` id'd label already does — see the call-site
   sweep below);
2. the ~25 remaining bare `submit_text(...)` call sites in `game/ui/*.py` are
   ALL either (a) a live-typed text buffer with no stored id
   (`add_name.py:179`'s name field, `cheat_menu.py:278`'s round field — both
   explicitly commented as deliberately un-id'd, `add_name.py:174-176`), (b)
   dynamic-count content with no stable id by the "dynamic content gets no
   id" rule (`building_ui.py`'s construct-preview stat rows/cost lines, boss
   popup rows, credits/highscores table rows, tutorial message lines,
   game_log lines — `game/ui/CLAUDE.md:1185-1198`), or (c) an explicitly
   documented hover-only/non-stored draw (`hud.py:664`'s income tooltip,
   `hud.py:746`'s lightning readout — both cited by name in `game/ui/
   CLAUDE.md:1308-1323`, "Layout heights", as never reaching a stored rect or
   the golden capture). **None of these are a designer-facing id'd widget a
   designer would expect to align via the editor** — if the executor finds
   one that IS (an id'd widget whose text draws via a raw `submit_text` call
   instead of `submit_label`), convert that ONE call site to `submit_label`
   using its existing holder; do not touch (a)/(b)/(c).

**`editor/panels/_screen_primitives.py`** — add one small pure helper next to
`interaction_rect` (this module already hosts pure, Qt-free resolution logic
for the interaction box; `editor/panels/_screen_rules.py` is the sibling for
the Color/Label "honest controls" resolution domain, a different concern —
align resolution belongs beside the function that consumes it):

```python
def resolve_align(spec, override):
    """The alignment `interaction_rect` should measure against: the
    designer's OVERRIDE `align` if set, else the recorded DEFAULT `align`
    (`screen_defaults.json`'s editor-only measuring hint), else "left".
    `spec` is the widget's `screen_defaults.json` entry, `override` is the
    screen doc's per-widget override dict — the same two args
    `viewport._interaction_rect` already has in scope."""
    return override.get("align") or spec.get("align", "left")
```

Wire it into the ONE caller that currently reads only the default:
`editor/panels/viewport.py`'s `_interaction_rect` (`:713-724`) — change

```python
            align=spec.get("align", "left"))
```
to
```python
            align=_screen_primitives.resolve_align(spec, override))
```

where `override = self._screen_session.doc.get("widgets", {}).get(widget_id,
{})` (the exact expression `_widget_text` two methods above already computes
at `:703` — either reuse that local or recompute it inline, executor's
choice, but do not change `_widget_text`'s own body). **`viewport.py` is not
in the plan's Files list, but this one-line call-site change is required for
the file the plan DOES list (`_screen_primitives.py`) to have any effect** —
`interaction_rect` itself needs no change, only its align INPUT does, and
that input is computed in `viewport.py`. Section S2 does not touch
`viewport.py` at all (confirmed: S2's phases are UL-3/4/5, the layer
model/engine/draw-path phases — no shared-file conflict). UL-2 (this
section's other phase) does not touch `viewport.py` either (it touches
`screen_details.py`'s `_populate_font_combo` and `editor/theme_ops.py`/
`editor/panels/game_theme.py`).

**`editor/panels/screen_details.py`** — new **Alignment** combo, the exact
shape of the Skin/Font rows immediately above it (`:289-299`):

```python
        self.align_combo = _NoWheelComboBox(self)
        self.align_combo.addItem("Left", "left")
        self.align_combo.addItem("Center", "center")
        self.align_combo.addItem("Right", "right")
        self.align_combo.activated.connect(self._on_align_changed)
        align_row, self.align_reset_button = self._field_row(
            (self.align_combo,), "align", lambda: self._on_reset_field("align"))
        form.addRow("Align", align_row)
```

inserted **immediately after `form.addRow("Font", font_row)` (`:299`) and
before the `# UH-6/D6: this ONE control is Color...` comment (`:301`)** — the
same reconciled insertion point named in this brief's dispatch. Unlike
Skin/Font (which are open-ended registry-driven combos, `_populate_skin_combo`
/`_populate_font_combo`), Align is a fixed 3-item enum, so it needs no
population method and no `_populate_*` call in `_enter_screen_mode`/
`__init__` — it is filled once, in `__init__`, exactly like the pattern
above.

`_on_align_changed` mirrors `_on_font_changed` (`:1018-1026`) exactly (no
`_refresh_widget_form()` call needed — same reasoning: a combo tied to one
key with no dependent UI, unlike skin which flips the honest-controls Color
row):

```python
    def _on_align_changed(self, index):
        if self._current_widget is None:
            return
        new_align = self.align_combo.itemData(index)
        old_align = self._align_baseline
        if new_align == old_align:
            return
        self._session.push_field(self._current_widget, "align", old_align, new_align)
        self._align_baseline = new_align
```

`_populate_widget_form` gains one baseline block, mirroring `font`'s
(`:884-886`) — insert immediately after it, before the color baselines
(`:888`):

```python
        align = override.get("align")
        self._align_baseline = align
        self.align_combo.setCurrentIndex(
            max(0, self.align_combo.findData(align or "left")))
```

`_refresh_reset_buttons` (`:721-739`) gains one line, same shape as
`font_reset_button` (`:734`):

```python
        self.align_reset_button.setEnabled("align" in override)
```

`push_field` is fully generic by `field_key` (`editor/ui_screen_session.py:320`)
— `align` needs **no session-side change**, exactly like `font`/`text_color`
before it.

## 3. File scope + shared-file contract

| File | Change |
|---|---|
| `data/schemas/ui_screen.schema.json` | **MOD, minimal** — one new `align` enum property in the per-widget override object, inserted alphabetically before `color`. Nothing else in the file moves. |
| `game/ui/widgets.py` | **Verification only** — confirm `submit_label`'s `getattr(holder, "align", "left")` path covers every id'd label; convert at most one stray `submit_text` call IF an id'd widget is found bypassing `submit_label` (scouted: none found — see §2). |
| `editor/panels/_screen_primitives.py` | **MOD** — new pure `resolve_align(spec, override)` helper beside `interaction_rect`. |
| `editor/panels/viewport.py` | **MOD, one line** — `_interaction_rect` (`:713-724`) calls `_screen_primitives.resolve_align(spec, override)` instead of `spec.get("align", "left")`. Not in the plan's Files list but required to complete the fix `_screen_primitives.py` alone cannot: see §2. |
| `editor/panels/screen_details.py` | **MOD, shared with UL-2 — see the binding split below.** |
| `tools/tests/test_ui_align.py` | **NEW** — override applies; each of the three values measures its anchor box the right way; an absent key is `left`. |

**BINDING SHARED-FILE CONTRACT — `editor/panels/screen_details.py`.**
UL-1's own phase-sibling **UL-2** (same section S1, different coder, running
concurrently in its own worktree, merging back into `ul-section-S1` in order
UL-1 then UL-2) ALSO modifies this file:

- **UL-1 owns `screen_details.py`'s `__init__` widget-form construction
  region** (the new Alignment combo, inserted after the Font row at `:299`
  and before the Color/tint block comment at `:301`) **plus
  `_populate_widget_form` / `_refresh_widget_form` / any new
  `_on_align_changed` handler / the `_align_baseline` field / the
  `align_reset_button` line in `_refresh_reset_buttons`.**
- **UL-1 does NOT touch `_populate_font_combo`** (`:462-468`).
- **UL-2 owns `_populate_font_combo` only** — it lists custom font presets
  there; it does not touch the widget-form construction code in `__init__`.

Do not touch `_populate_font_combo`, `theme_ops.font_keys`, or anything in
`editor/theme_ops.py`/`editor/panels/game_theme.py` — those are UL-2's.
`data/schemas/fonts.schema.json` is untouched by UL-1.

**Section S2 shared-file note (`data/schemas/ui_screen.schema.json` only).**
S2 (phases UL-3/4/5, concurrent wave with this whole section per the plan's
§3 "Waves") adds an optional `layers` key to the SAME per-widget override
object in the SAME file. `layers` sorts alphabetically between `"label"` and
`"parent"`; `align` sorts before `"color"`. The two insertions land in
different parts of the object and do not touch the same lines — keep it that
way: **do not reformat, re-sort, or touch `required`/`additionalProperties`**
beyond the one `align` property, and never add, stub, or reference a
`layers` key yourself.

## 4. Exit gate + Quick Test

```bash
py tools/smoke.py
py -m pytest tools/tests/test_ui_align.py tools/tests/test_ui_skinning.py -q
```

Both must be green — `test_ui_skinning.py` is the D5 golden-parity pin: with
no screen doc authoring `align`, nothing in `test_all_screens_parity`'s
recorded primitive stream may move (an absent `align` key resolves to
`"left"`, `submit_label`'s pre-existing default, so the shipped screens —
none of which author `align` yet — draw byte-identical to today).

`test_ui_align.py` should cover, cheaply (the `ScreenSkinning.from_overrides`
pattern already used by `tools/tests/test_construct_card.py:244-249` needs no
tempdir `data/` at all):
- a `widgets.label_holder(...)` + `ScreenSkinning.from_overrides({"screen":
  {"widgets": {"w": {"align": "right"}}}})` + `sk.apply("screen", {"w":
  ("label", holder)})` + `widgets.submit_label(fake_renderer, holder)` records
  a `HudText` with `align="right"` — repeat for `"center"`/`"left"`;
  no `align` key in the override → `align="left"` (the absent-key case);
- `editor.panels._screen_primitives.resolve_align(spec, override)` for the
  matrix: override set (wins over spec), override absent + spec set (falls
  back to spec), both absent (`"left"`) — each of the three values, then feed
  it into the existing pure `interaction_rect(rect, text=..., font_key=...,
  align=...)` to confirm the anchor box's `x` shifts the documented way
  (`center` moves left by `w/2`, `right` moves left by `w`,
  `editor/panels/_screen_primitives.py:116-119`).

**Quick Test (in game):** set `hud.love_text`'s `align` to `right` in
`data/ui/screens/hud.json`, run `py game/main.py`, confirm the love number
spreads leftward from its stored x and the icon does not move.
