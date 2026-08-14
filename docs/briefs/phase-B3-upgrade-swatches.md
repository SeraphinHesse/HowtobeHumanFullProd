# Phase B3 — Upgrade-panel swatches + the colour palette

Plan: `planning/MasterSheetColumnsPLAN.md` §Section S3, `#### Phase B3` (line 689).
Section branch: `section-S3`. **B1 and B2 land before you and are merged into
`section-S3` when you start** — read the merged code, not this brief, for what
they actually named things (§3 states the contract this brief assumed).

Open with the **`/add-balancing-value`** skill for the `BuildingColors` group
(§2 step 1). Do not hand-edit `data/balancing/ui.json` or its schema.

---

## 1. Behavioral spec

**Goal.** The upgrade panel grows the same colour-swatch row `ConstructPreview`
got in B2, and every swatch's RGB comes from `data/balancing/ui.json` instead of
B2's hardcoded table.

### 1.1 When the row exists (D6, plan line 74-78)

- The row is drawn **only in upgrade mode**, and only when the host's capability
  map has colour names for the selected building's current slot. A building on
  placeholder or single-column art shows **nothing** — no row, no gap, no
  placeholder. Degrade quietly; never raise.
- The capability map is the boot-time `{slot_key: (colour_name, ...)}` B1 builds
  in `game/main.py` — the HOST does the art lookup, `game/ui` never touches the
  asset layer (D6, E-37; the `condition_art` precedent). **`game/ui/building_ui.py`
  must not import anything from `engine.assets` or read the manifest.**
- No map wired at all (headless, tests, `tools/screen_mocks.build_bp_view`) reads
  as "no colours" and draws nothing — the same rule `self.assets = None` already
  follows (`game/ui/building_ui.py:731-735`).
- Multi-selection: the row follows `move_btn`'s rule — **single selection only**
  (`building_ui.py:1405`). Recolouring a batch is not a feature this phase adds.

### 1.2 What a swatch does

- Swatch **index `i` IS the column index `i`** (D5, plan line 69-73): the order
  is the sheet's own `columns` tuple order, and clicking swatch `i` writes `i`
  onto the live building's `BuildingSprite.column`. There is no name→index
  lookup anywhere on this path; names are used *only* to pick a fill colour.
- **`0` is a real colour, never "unset"** — `SpriteAnimator.column: int = -1` is
  the "no driver" sentinel and `-1` is what maps to `RenderItem.column=None`
  (`engine/core/sprite_animator.py:22-28`, `:49` — **verified on this branch**;
  note the S1 handoff's older `= 0` line is stale). So never test a column for
  truthiness, never use `0` to mean "no colour", and never write `-1` from a
  click.
- The change is **live**: the world sprite recolours on the next frame with no
  confirm step, because the column the renderer reads is the same field the
  click writes. Nothing is spent and nothing is logged.
- It **survives an upgrade for free** — `Building.apply_tier_stats`
  (`game/buildings/building.py:182-192`) rewrites only `anim.slot_key`. This
  phase adds no re-stamp code; the Quick Test is what proves it.
- The currently-selected swatch is ringed (the sanctioned "draw the active
  highlight after its own button" exception, `game/ui/CLAUDE.md` HUD submission
  order section). Every other swatch draws plain.

### 1.3 Where the row sits — the arithmetic

The panel is 130 wide at `panel_x = view_w - 130 = 510`, inner content
`x = panel_x + 6 = 516`, `w = panel_w - 12 = 118` (`building_ui.py:668-671`,
`:1345-1346`).

Vertically there is exactly one free band in upgrade mode:

```
stat column worst case bottom .................. y = 268   (building_ui.py:2199-2208,
                                                            the comment's own worked case)
action_btn top = view_h - 60 ................... y = 300   (building_ui.py:1345-1346)
move_btn = action_btn.bottom + 4, h 15 ......... y = 322..337  (building_ui.py:1403-1404)
upgrade hint = move_btn.bottom + 3 ............. y = 340   (building_ui.py:2271-2277)
```

So the band is **y 268 → 300, 32 px tall**, and it is the ONLY place the row can
go: below `move_btn` is y 340+, which is off the 360-tall surface once the hint
is showing. Two worked cases, both honouring the **≥12 logical px min-target
floor (UR-5)**:

```
N <= 8   one row, size 14, gap 4, top y = 274
         width = 14N + 4(N-1) = 18N - 4  ->  N=4: 68, N=6: 104, N=8: 140 > 118 (!)
         so at size 14 the single row holds N <= 6 (104 <= 118); bottom 288, 12px
         clear of the action button.
N > 6    size 12, gap 2, two rows at y = 272 and y = 286
         width = 14N' - 2 per row -> 8 per row fits (110 <= 118); registry caps
         `columns` at 16, so two rows cover the maximum. Bottom 286 + 12 = 298,
         2 px clear of the action button.
```

**The row must not move anything.** `action_btn`, `move_btn`, the stat rows and
the hint keep the exact rects they have today; the swatches occupy dead space.
That is what makes the `screen_defaults.json` regeneration in §2 step 4 a no-op,
and it is the single easiest thing to get wrong.

Layout happens in `_build_upgrade` / `_layout_upgrade_rows`
(`building_ui.py:1317-1392`), which run **before** any `submit()` and therefore
before `skinning.apply` — that ordering is what lets a designer's rect override
win (`_layout_upgrade_rows`' own docstring, `:1354-1366`). Do not lay out from
`submit()`.

### 1.4 The colours come from data

- New **`BuildingColors`** group in `data/balancing/ui.json`, name → `[r, g, b]`.
  It exists because the shared `widgets.C_*` palette has no pink:
  `game/ui/overlays.py:75-83` records reusing `C_PURPLE` as "closest to pink"
  and the POND tint as the only blue.
- Read by **direct indexing** of the group (`ui_balance["BuildingColors"]`, D-2
  fail-loud — the schema requires it), then a per-NAME lookup that tolerates a
  miss: **a `columns` name with no entry degrades to a neutral swatch, never
  raises** (plan line 710). Neutral = `widgets.C_UI_TEXT_DIM` unless B2 already
  chose one, in which case reuse B2's.
- Shared-palette colours are read as **`widgets.<NAME>` attribute access**, never
  `from .widgets import <NAME>` — `configure_palette` rebinds module attributes
  at boot (`game/ui/widgets.py:84-106`).

### 1.5 Non-goals

No engine change, no editor change (the balancing panel picks the new group up
by recursing the schema), no `game/main.py` change, no second colour component,
no re-roll button, no batch recolour, no change to B2's `ConstructPreview`
behaviour beyond re-pointing its colour lookup at `ui.json`.

---

## 2. Architecture plan — ordered

### Step 1 — `BuildingColors`, via `/add-balancing-value`

**Open with the skill.** It is the canonical pattern (JSON + schema entry with a
description and bounds, written through the validating writer, deterministic
formatting: sorted keys, 2-space indent). `data/CLAUDE.md` is the authority for
the writer and the ×10 combat scale caveat (irrelevant here — these are colours).

Shape to specify to the skill — `data/schemas/ui.schema.json` today has root
`required: ["Debug", "FX", "Menu", "Timing"]` and `additionalProperties: false`
(**measured**), so the group must be added to `properties` AND to `required`:

```jsonc
"BuildingColors": {
  "type": "object",
  "additionalProperties": false,
  "description": "Swatch fill RGB per master-sheet colour-column NAME (data/sprites/master_sheets.json `columns`). A name with no entry here degrades to a neutral swatch rather than raising, so this map need not be exhaustive.",
  "properties": {
    "pink":   { "type": "array", "minItems": 3, "maxItems": 3,
                "items": { "type": "integer", "minimum": 0, "maximum": 255 },
                "description": "RGB of the 'pink' colour column's swatch." },
    "purple": { ...same... },
    "red":    { ...same... },
    "yellow": { ...same... }
  },
  "required": ["pink", "purple", "red", "yellow"]
}
```

Fixed named properties, **not** an open `additionalProperties` map: the editor's
balancing panel renders by recursing declared schema properties, and a free-form
map would not be editable there (which is the whole "no editor code" claim in the
plan). Growing the palette later is a one-line schema edit through the same skill.

Shipped values — three reuse the existing house palette so the swatch matches
what the rest of the UI already means by that word, and only pink is new:

| name | value | source |
|---|---|---|
| `pink` | `[255, 105, 180]` | new — no pink exists (`overlays.py:75-83`) |
| `purple` | `[168, 105, 222]` | `widgets.C_PURPLE` (`game/ui/widgets.py:79`) |
| `red` | `[210, 55, 55]` | `widgets.C_RED` (`widgets.py:52`) |
| `yellow` | `[255, 200, 50]` | `widgets.C_GOLD` (`widgets.py:51`) |

**Open item, do not silently resolve:** the NAME SET comes from D4's example
list (plan line 66-68) because **no shipped master sheet declares `columns` yet**
(S1 handoff: the migration gave `slinger_t2_lvl3` a `column_width: 15` and no
`columns`). The exact RGBs are a designer call and are tunable in the editor's
balancing panel the moment this lands. If the reviewer or the orchestrator has a
different four names, that is a one-file change — flag it, do not guess a fifth.

### Step 2 — the swatch row in `BuildingUI`

**Reuse B2's helper. Do not duplicate the layout / hit-test / draw code.** B2's
brief factors the row into a reusable helper plus one colour-lookup function;
§3 states the exact contract this brief assumed and what to do if B2 named it
differently.

New private method `_build_colour_row()` on `BuildingUI`, called as the last line
of `_build_upgrade` after `_build_move_btn()` (`building_ui.py:1352`):

1. Resolve the selected building's slot key the same way B2 resolves the pending
   building's, then `names = self.colour_map.get(slot_key, ())`.
2. `names` empty, or `len(self.selected_tiles) != 1`, or `self._selected is None`
   → clear the row (empty button list, drop the ids, §3) and return.
3. Otherwise build one unlabelled `widgets.Button(rect, "")` per name through
   B2's layout helper, fed the band `(x=516, y=272, w=118, max_h=26)` and the
   two size cases from §1.3.
4. Register each as `self.ids[f"upgrade_swatch_{i}"] = ("button", btn)`.

**Stale ids must be dropped**, exactly as `_clear_card_ids` does for the `card_`
family (`building_ui.py:1265-1279`) and for the same reason: the buttons are
rebuilt per selection, so an id left pointing at a dead Button makes
`skinning.apply` write overrides onto an object nothing draws. Sweep by the
`upgrade_swatch_` prefix at the top of `_build_colour_row` and in `close()`.

Wiring, all inside `building_ui.py` (insertion points in §3): hover beside the
`move_btn` hover, `update(dt)` beside `self.move_btn.update(dt)`, the click branch
in `_upgrade_click`, the draw in `_submit_upgrade`'s BUTTON block.

The click writes `i` onto the live building's `BuildingSprite.column` — the
sanctioned `game/ui → game.buildings.components` read (`game/ui/CLAUDE.md` Defence
FX section; `building_ui.py` already imports `RoundStats`/`TierState` from there).
Return `True` so the click is consumed.

### Step 3 — swap the colour lookup's source

B2's colour-lookup function is the ONE place a name becomes an RGB. Change its
body from B2's hardcoded table to `ui_balance["BuildingColors"]` + the neutral
fallback, and update **both** call sites (B2's `ConstructPreview` one and B3's
new one) to pass the balance dict they each already hold — `ConstructPreview`
takes `ui_balance` (`building_ui.py:300`) and `BuildingUI` stores
`self._ui_balance` (`:666`). One function, two callers, no second table.

### Step 4 — regenerate `data/ui/screen_defaults.json` (REQUIRED, in this order)

Run it **after** steps 1-3 are complete and before you touch any test:

```
py tools/export_ui_layouts.py
git diff --stat data/ui/screen_defaults.json
```

**Expected result: no diff.** The exporter's `upgrade` view builds a real
`defence` building (`tools/screen_mocks.py:258-267`) but wires no capability map,
so §1.1's "no map ⇒ no colours ⇒ no row" path runs and no `upgrade_swatch_*` id is
produced. The run is still required — it is what proves the row did not move
`action_btn`/`move_btn`/the stat rows, and that `_build_upgrade` still constructs
headless (the exporter re-raises any construction failure with context,
`tools/export_ui_layouts.py:720-725`).

- Diff empty → done, and **`_BASELINE["building_panel"]` in
  `tools/tests/test_ui_skinning.py` needs NO edit**: it is `[]` today
  (`test_ui_skinning.py:400-401`) because that capture harness never selects a
  building (`game/ui/CLAUDE.md`'s "the pin does not protect this module" note).
- Diff NON-empty → **stop and report**. An existing rect moving means the row
  pushed something and §1.3's "must not move anything" was violated.

### Decision — no mock builder. Do not add colours to `tools/screen_mocks.py`.

The plan offers "add a mock builder in `tools/screen_mocks.py` if the swatches
must be covered". **They must not, this phase.** Three reasons:

1. `screen_mocks.py` is the ONE mock state shared by two generated artifacts —
   `screen_defaults.json` *and* `screen_previews.json`, which the editor replays
   (`tools/screen_mocks.py:1-18`). Faking a capability map there churns both, and
   `screen_previews.json` is **outside this phase's file scope**. The module's own
   docstring exists to stop the two artifacts being built from different states.
2. The map is host-derived from the asset layer (D6/E-37). Inventing colour names
   for `defence` in `screen_mocks` asserts art facts the shipped art does not
   have, and no shipped master sheet declares `columns` at all yet.
3. The swatch family is **dynamic-count** content (1..16 per sheet), which is the
   exact category the house convention styles through
   `ScreenSkinning.defaults()` rather than per-id overrides
   (`game/ui/skinning.py:162-170`; the construct cards / boss popup rows /
   levelup option boxes precedent). An id absent from `screen_defaults.json` is
   harmless — `_validate_ids` fails loud only on an id in the OVERRIDE that code
   does not know, never the reverse (`game/ui/skinning.py:214-219`).

So: regenerate (step 4) and expect a no-op; leave `screen_mocks.py` untouched.
It stays in the file scope only as the escape hatch if step 4 surprises you, and
touching it is a report-first decision, not a silent one.

### Step 5 — docs

Append a short **Building colour swatches** subsection to `game/ui/CLAUDE.md`
under the Move Building section: the D6 gate, the band arithmetic from §1.3, the
`BuildingColors` + neutral-degrade rule, and the "the exporter's mock has no
capability map, so the swatches are not in `screen_defaults.json` and the golden
pin does not cover them" fact — that last one is exactly the kind of gap that doc
already tracks for this module.

---

## 3. File scope + shared-file contract

**Modified — nothing else:**

| File | What |
|---|---|
| `game/ui/building_ui.py` | the upgrade-mode swatch row + the colour-lookup source swap |
| `data/balancing/ui.json` | `BuildingColors` group (via `/add-balancing-value`) |
| `data/schemas/ui.schema.json` | its schema entry + root `required` |
| `data/ui/screen_defaults.json` | REGENERATED by `py tools/export_ui_layouts.py`, **never hand-edited** (expected: no diff) |
| `game/ui/CLAUDE.md` | §2 step 5 |
| `tools/tests/test_hud_panel.py` | APPEND the four tests in §4 |
| `tools/tests/test_ui_skinning.py` | only if step 4 produced a real diff (expected: untouched) |
| `tools/screen_mocks.py` | **only** if step 4 surprises you — see the decision above; report before editing |

**Out of scope, hard:** `engine/**`, `editor/**`, `game/buildings/**`,
`game/main.py`, `tools/tests/fixtures/**`, `data/ui/screen_previews.json`.
`tools/tests/test_building_ui.py` **does not exist** — the plan doc names it, but
`BuildingUI`'s real test home is `tools/tests/test_hud_panel.py` (measured by the
section orchestrator on this branch). Do not create it. B2's tests are already in
`test_hud_panel.py` when you land: **append**, never restructure what B2 wrote.

### The contract this brief assumes from B2 (reconcile against the merged code FIRST)

B2's brief did not exist when this was written, so these are REQUIREMENTS, not
observations. Read the merged `building_ui.py`; where B2 chose a different name,
**use B2's name and note the substitution in your report** — never add a second
helper alongside it.

1. **A reusable swatch-row helper** — layout + hit-test + draw, module-level in
   `building_ui.py`, not a `ConstructPreview` method. Layout must take a BAND
   (`x, y, w, max_h`) and a count and return rects, so B3 can hand it
   `(516, 272, 118, 26)` and get §1.3's one-or-two-row result. If B2's helper is
   single-row only, extend it (both callers benefit) rather than forking it —
   and say so in your report.
2. **One colour-lookup function**, name → `(r, g, b)`, hardcoded by B2 against
   the shared palette. B3 re-points its body at `ui.json` and adds the balance
   argument (§2 step 3). This is the only edit B3 makes inside B2's code.
3. **A host-wired capability map on `BuildingUI`** — a plain attribute
   defaulting to empty, in `__init__` beside `self.assets = None`
   (`building_ui.py:731-735`), set by `game/main.py`. `BuildingUI` constructs
   `ConstructPreview`, so B2 must already have put it here; if B2 instead passed
   it straight into the preview, add the attribute and read it — one map, one
   owner. *(UNVERIFIED: the attribute's name. Use whatever B2 shipped.)*
4. **The slot-key accessor for a building** — B3 uses the same expression B2 uses
   for the pending building, applied to the live `self._selected`.
   *(UNVERIFIED: `BuildingSprite` is assumed to live in
   `game/buildings/components.py` and to expose `.slot_key` and a writable
   `.column`. If B1 published a setter instead, use it.)*

### Insertion points B3 claims in `game/ui/building_ui.py` (disjoint from B2's)

B2 owns `ConstructPreview` — `__init__` (`:356-372`), `handle_click`
(`:406-430`), `submit` (`:441-519`) — plus the module-level helpers. B3 owns:

| Site | Line today | Edit |
|---|---|---|
| `__init__` | `:719-735` | the swatch button list beside `self._card_parts` (and the capability-map attribute only if B2 did not add it) |
| `_build_upgrade` tail | `:1352` | one call to `_build_colour_row()` after `_build_move_btn()` |
| new method | after `:1414` | `_build_colour_row()`, next to `_build_move_btn` |
| `_clear_*` sweep | mirror `:1265-1279` | drop the `upgrade_swatch_` ids; also call it from `close()` (`:883`) |
| `_upgrade_click` | between `:1753` and `:1758` | swatch hit test — AFTER the rename defocus/commit, BEFORE the `move_btn` branch, so a swatch click commits an in-progress rename exactly like a move click does |
| `hover` | `:1578-1580` | hover the swatch buttons beside `move_btn`, with the same `is_visible` guard |
| `update` | `:1969` | `update(dt)` on each swatch button beside `self.move_btn.update(dt)` |
| `_submit_upgrade` | between `:2270` and `:2271` | draw the row in the BUTTON block — after `move_btn`, before the hint text. Panel → buttons → text is the house order (`game/ui/CLAUDE.md`); the selected-swatch ring draws immediately after its own button (the sanctioned exception) |

---

## 4. Exit gate + Quick Test

### Tests to write — the minimum that pins the behaviour, and no more

All four go in `tools/tests/test_hud_panel.py`, appended after B2's.
**Tests must never write into `data/`** — copy to a tempdir (`TempDataCase`) if
you need a data root at all, and **never assert against live `data/` content**:
test 3 builds its own `ui_balance` dict literal rather than reading the shipped
`ui.json`.

1. **D6 gate** — a `BuildingUI` driven into upgrade mode on a single selection
   with a capability map naming colours for that slot has one visible swatch
   button per name; with an empty map it has none, and no `upgrade_swatch_*` id.
2. **The click** — clicking swatch `i` sets the live building's
   `BuildingSprite.column` to `i` (assert an `i > 0` case AND `i == 0`, since `0`
   is a real colour), and the click is consumed.
3. **The palette** — the lookup returns the RGB from a hand-built
   `{"BuildingColors": {"pink": [1, 2, 3], ...}}` dict, and an unknown name
   returns the neutral rather than raising.
4. **The band** — the swatch row's bottom is above `action_btn.rect[1]`, every
   swatch's smaller dimension is `>= 12` (UR-5), and `action_btn.rect` /
   `move_btn.rect` are byte-identical to what they are with no colour map. This
   is what makes step 4's no-op diff a guarantee rather than a hope.

The golden pin is `test_ui_skinning.py::TestGoldenParity` — it must stay green
with **no baseline edit** (§2 step 4).

### Exit gate — run exactly this, nothing wider

```
py tools/smoke.py
py -m pytest tools/tests/test_hud_panel.py tools/tests/test_ui_skinning.py -x -q
```

**No full suite, no `py tools/testgate.py check`, no `--affected`, no tier sweep
(`-m core` / `-m editor` / `-m meta`).** You are a subagent; the `test_guard.py`
hook DENIES all four, and the single full `check` is the main session's at
handoff (root `CLAUDE.md` §"Test Suite Policy"). The gate is **ZERO** — `GATE
PASS` or you are not done.

**If `test_guard` denies a command: do NOT re-issue it and do not vary the flags**
(the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints
identically), and do not reach for its escape hatch. Report the deny text and the
result it quotes back, and stop testing.

If a fixture-validation test goes red because `tools/tests/fixtures/data/` carries
its own `balancing/ui.json` (it does) and the new required key is missing there —
**stop and report**. `tools/tests/fixtures/**` is outside this phase's scope, and
S1 already reported ~13 files of pre-existing fixture drift (S1 handoff, finding 3).

### Quick Test (in game — the orchestrator or the user runs this, not you)

`py game/main.py` → place a colour-capable building → upgrade it one tier →
open its upgrade panel → the swatch row is there under the stats, above the
action button → click a different colour and the building on the board recolours
immediately → upgrade it again and **the colour holds**. Then select a building
with no colour-capable art: the panel shows no swatch row and nothing else has
moved.
