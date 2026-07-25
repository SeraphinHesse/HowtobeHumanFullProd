# Phase TU-4 — Editor: Tutorial section

Source plan: `planning/TutorialPLAN.md` §3, "Phase TU-4 — Editor: Tutorial
section" (`planning/TutorialPLAN.md:194-208`). Depends on **TU-1**
(`planning/TutorialPLAN.md:129-153`), which by the time this phase's code runs
has already created `data/tutorial/tutorial.json` +
`data/schemas/tutorial.schema.json`. Use the **`/add-editor-feature`** skill
(`.claude/commands/add-editor-feature.md:1-47`) — this brief follows its
steps (hang off selection, one write path, `data_dir` injection, TestPurity
registration) verbatim.

## 1. Behavioral spec

**Goal (verbatim from the plan, `planning/TutorialPLAN.md:196-199`):** "the
tutorial editor — edit both message texts, `skippable`, and
`first_loss_costs_life`; step structure is fixed (no reordering UI), only
texts/flags are editable. Writes `data/tutorial/tutorial.json` via
`write_validated`."

**In scope:** a new selection leaf ("Tutorial") that shows a small staged-edit
form: two multi-line message texts + two checkboxes. **Out of scope:** any UI
for the step list itself (no add/remove/reorder of steps, no editing
`highlight`/`advance_on`/`allow`/`flags` — those stay exactly as TU-1 wrote
them and must round-trip byte-identical when untouched).

**Assumed on-disk shape (inferred from D3, `planning/TutorialPLAN.md:70-76`,
since TU-1 has not landed in this worktree yet — confirmed: no
`data/tutorial/` or `tutorial.schema.json` exist, checked via `Glob`/`find`
at brief-authoring time):**
```json
{
  "skippable": true,
  "first_loss_costs_life": true,
  "messages": {"message_1": "...", "message_2": "..."},
  "steps": [ {"...": "opaque, TU-1-owned"} ]
}
```
The exact top-level key names (`messages.message_1`/`message_2` vs. some
other naming TU-1 actually ships) are a **placeholder** — the implementer
must read the real `data/tutorial/tutorial.json` +
`data/schemas/tutorial.schema.json` at execution time and bind the panel's
two text fields + two checkboxes to whatever keys TU-1 actually used. The
shape is fixed in kind (2 short strings + 2 booleans), only names may differ,
so this is a small adjustment, not a redesign.

**Pattern to copy exactly** — `editor/panels/game_theme.py:1-282`
(`GameThemePanel`), the "Theme" leaf's panel (UH-6). It is the closest
existing "small JSON doc, text + toggle fields, one Save button, staged
edits" panel in the codebase:
- Staged edits + dirty dots + one enabled-while-dirty Save button, the
  `balancing.py` pattern (`editor/panels/game_theme.py:221-264`,
  `editor/panels/CLAUDE.md:102-120`).
- `_on_save` is the ONE `write_validated` call site
  (`editor/panels/game_theme.py:266-281`).
- Graceful degrade (E-37) on a missing/invalid doc — a placeholder label,
  never a crash out of the constructor (`editor/panels/game_theme.py:78-118`).
- `data_dir=None` injection (`editor/panels/game_theme.py:46-48`).
- A companion **pure** ops module, `editor/theme_ops.py:1-71` (load/write/
  path helpers, Qt-free, in `TestPurity`) — this phase's analogue is
  `editor/tutorial_ops.py`.
- The selector leaf that drives it: a single LEAF (not a branch — "one
  document, nothing to enumerate"), `editor/panels/selector.py:36-41` (design
  note) and `:161-175` (construction), `:454,468-474` (`_emit_selection`
  dispatch) — never `node_selected`, exactly like Maps/Screens/Theme leaves.
- `MainWindow` wiring for that leaf: construction
  (`editor/main.py:109`), `right_stack` registration (`editor/main.py:313`),
  signal connect (`editor/main.py:180-185`), handler methods
  (`editor/main.py:931-952`).

**Tests to mirror**: `tools/tests/test_editor_panels.py:1122-1182`
(`TestGameThemePanel`, a `TempDataCase`) and the selector leaf test at
`tools/tests/test_editor_panels.py:443-452` (asserts the leaf exists as a
child of the right root and clicking it emits the panel's `_selected` signal
+ `domain_selected("ui")`).

## 2. Architecture plan

**New pure helper `editor/tutorial_ops.py`** (mirrors `editor/theme_ops.py`
exactly): `tutorial_path(data_dir)`, `tutorial_schema_path(data_dir)`,
`load_tutorial(data_dir)` (raises on missing/invalid — the panel only opens
this after TU-1 has landed the file, so a broken tree should be loud here,
same argument as `theme_ops.load_fonts`), `write_tutorial(doc, data_dir)`
(`engine.data_io.write_validated`). Qt-free, pygame-free, added to
`TestPurity`.

**New panel `editor/panels/tutorial_panel.py` — `TutorialPanel(QWidget)`**:
- `__init__(self, data_dir=None, parent=None)`, `set_tutorial()` (fresh
  load + rebuild — called by `__init__` and by `MainWindow`'s selection
  handler on every entry, the "reload on entry" convention every other
  selection-driven panel follows).
- Two `QPlainTextEdit` fields (message texts run a full sentence/paragraph —
  a `QLineEdit` would clip message 2's ~250 characters; `QPlainTextEdit` is
  the first multi-line text field in the editor, a small deliberate
  departure from `balancing.py`'s `QLineEdit` convention, justified by
  content length). Commit on `focusOutEvent`/`editingFinished`-equivalent:
  `QPlainTextEdit` has no `editingFinished`, so wire `textChanged` with a
  debounce-free direct staging (every keystroke updates the in-memory doc +
  dirty dot — acceptable here since there is no expensive rebuild per
  keystroke, unlike balancing's schema-walk rebuild) OR wire on focus-out via
  an event filter — **implementer's call, pick whichever the test suite
  exercises more simply**; either way the field must never write to disk
  until Save.
- Two `QCheckBox` (`skippable`, `first_loss_costs_life`), `toggled` → stage +
  dirty dot, the exact `_on_font_bold_changed` pattern
  (`editor/panels/game_theme.py:227-229`).
- **Empty-text guard (ED-30, "invalid text blocked")**: client-side, always —
  regardless of whether TU-1's schema declares `minLength`, the panel
  refuses to stage an all-whitespace message: on the commit path, if the
  stripped text is empty, restore the field to its last staged value instead
  of committing (the exact "text shorter than minLength restored, not
  written" rule already documented at
  `editor/panels/CLAUDE.md:83` for `QLineEdit`, applied here to
  `QPlainTextEdit`). This makes invalid text unrepresentable in the UI
  regardless of what TU-1's schema turns out to enforce, and the schema
  validation in `write_validated` is the loud backstop if this guard is ever
  bypassed.
- `steps` (and any other TU-1-owned keys) are loaded into `self._doc` and
  **round-tripped untouched** — the panel never reads or renders them; Save
  writes the whole `self._doc` (steps included) back via
  `tutorial_ops.write_tutorial`, so an edit to texts/flags never perturbs the
  step list, and a doc that was never touched saves byte-identical (same
  argument as `game_theme.py`'s per-file dirty gating, simplified to one
  file here).
- `saved = Signal()` for test observability and symmetry with every other
  staged-edit panel, even though (unlike Theme) nothing in `MainWindow` needs
  to react to it in-process — no engine reconfiguration is needed for text/
  flags, so `MainWindow` may simply not connect anything to it. State this
  explicitly in the panel's docstring so a future phase doesn't go looking
  for a missing consumer.

**Selector**: a single "Tutorial" leaf under the "ui" category (mirrors
"Theme" exactly — see §3 for exact insertion points and the TU-3 ordering
assumption).

**MainWindow wiring**: construct the panel, register it in `right_stack`,
connect `selector.tutorial_selected` → `_on_tutorial_selected` (calls
`self.tutorial_panel.set_tutorial()` then `right_stack.setCurrentWidget`,
the exact `_on_theme_selected` shape).

## 3. File scope + shared-file contract

### New files
- `editor/tutorial_ops.py` — pure load/write/path helpers (mirrors
  `editor/theme_ops.py`).
- `editor/panels/tutorial_panel.py` — `TutorialPanel`.
- Tests: new class `TestTutorialPanel(TempDataCase)` appended to
  `tools/tests/test_editor_panels.py` (after `TestGameThemePanel`, which ends
  at `tools/tests/test_editor_panels.py:1182`, i.e. immediately before
  `class TestThemeSwitch(TempDataCase):` at
  `tools/tests/test_editor_panels.py:1185` — insert the new class between
  the two). Also append ONE new test to the existing selector-leaf test
  group near `tools/tests/test_editor_panels.py:443-452`
  (`test_tutorial_leaf_exists_under_ui_and_emits_tutorial_selected` — assert
  `selector._tutorial_item is not None`, its parent is the "ui" root, and
  triggering selection emits `tutorial_selected` + `domain_selected("ui")`;
  **do not** hardcode its child index, since TU-3's Cutscenes leaf may or may
  not have landed first — see the open question below).

### Modified: `editor/main.py` (ALSO touched by TU-3 — reconcile in this
order: TU-3 lands first per the task's instruction)
1. **Import** (alphabetical block, `editor/main.py:59-67`): add
   `from editor.panels.tutorial_panel import TutorialPanel` between
   `from editor.panels.selector import SelectorPanel` (`:66`) and
   `from editor.panels.viewport import ViewportPanel` (`:67`). This line is
   **independent of TU-3's own import** — TU-3's `cutscenes_panel` import
   sorts alphabetically between `balancing` (`:59`) and `details` (`:60`), a
   different line entirely, so there is no collision here regardless of
   landing order.
2. **Panel construction** (`editor/main.py:109`, currently the last line in
   this block: `self.game_theme = GameThemePanel(data_dir=data_dir)  # UH-6:
   Theme leaf`): append
   `self.tutorial_panel = TutorialPanel(data_dir=data_dir)  # TU-4: Tutorial leaf`
   immediately after **TU-3's own** appended line (expected to be
   `self.cutscenes = CutscenesPanel(data_dir=data_dir)  # TU-3: Cutscenes leaf`,
   itself appended directly after line 109). If TU-3 has not landed when
   this phase executes, append directly after line 109 instead.
3. **`right_stack` registration** (`editor/main.py:309-313`, ending at
   `self.right_stack.addWidget(self.game_theme)      # index 3: Theme (UH-6)`):
   append `self.right_stack.addWidget(self.tutorial_panel)  # index 5: Tutorial (TU-4)`
   immediately after TU-3's expected
   `self.right_stack.addWidget(self.cutscenes)  # index 4: Cutscenes (TU-3)`
   line (or directly after line 313 if TU-3 hasn't landed — renumber the
   trailing index comment to whatever is actually next, the comment is
   documentation only, not read by code).
4. **Selector wiring** (`editor/main.py:180-185`, the "Theme wiring" block):
   append a new block, `# Tutorial wiring (TU-4): the "Tutorial" leaf ->
   right_stack; reload on entry, the same convention as every other
   selection-driven panel.` followed by
   `self.selector.tutorial_selected.connect(self._on_tutorial_selected)`,
   immediately after TU-3's expected "Cutscenes wiring" block (or directly
   after line 185 if TU-3 hasn't landed).
5. **Handler method** (`editor/main.py:931-952`, the "Theme panel" section,
   ending right before `# -- frame drive` at `:954`): append a new
   `# -- Tutorial panel (TU-4) --` section with
   ```python
   def _on_tutorial_selected(self):
       """The selector's Tutorial leaf: reload fresh from disk (a designer
       may have hand-edited nothing, but this mirrors every other
       selection-driven panel's reload-on-entry convention) and show the
       panel."""
       self.tutorial_panel.set_tutorial()
       self.right_stack.setCurrentWidget(self.tutorial_panel)
   ```
   immediately after TU-3's expected `_on_cutscenes_selected` method (or
   directly after line 952 if TU-3 hasn't landed), still before the
   `# -- frame drive --` section.

### Modified: `editor/panels/selector.py` — **NOT listed in the plan
doc's terse per-phase Files line, but required by this phase's goal** (a
selection leaf is how every other small-document panel is reached — Theme,
Screens; see `editor/CLAUDE.md:47-51`, "new editor features should hang off
selection, not add parallel state"). **This file is also required by TU-3**
for its own Cutscenes leaf, for the identical reason — flagging it here
since the task's shared-file note only named `main.py` and
`panels/CLAUDE.md`. Exact insertion points (all "append after TU-3's
expected line, or after the cited existing line if TU-3 hasn't landed"):
1. **Role marker constant** (`editor/panels/selector.py:86-91`, ending
   `_THEME_ROLE = Qt.ItemDataRole.UserRole + 5`): append
   `_TUTORIAL_ROLE = Qt.ItemDataRole.UserRole + 7  # True on the single Tutorial leaf (TU-4)`
   immediately after TU-3's expected `_CUTSCENES_ROLE = Qt.ItemDataRole.UserRole + 6`.
   **Numbering collision risk — see open questions.**
2. **Label constant** (`editor/panels/selector.py:93-95`, ending
   `_THEME_LABEL = "Theme"`): append `_TUTORIAL_LABEL = "Tutorial"` after
   TU-3's expected `_CUTSCENES_LABEL = "Cutscenes"`.
3. **Signal** (`editor/panels/selector.py:107-113`, ending
   `theme_selected = Signal()`): append `tutorial_selected = Signal()`
   after TU-3's expected `cutscenes_selected = Signal()`.
4. **Instance state** (`editor/panels/selector.py:126`,
   `self._theme_item = None`): append `self._tutorial_item = None` after
   TU-3's expected `self._cutscenes_item = None`.
5. **Tree construction**, inside `elif category.key == "ui":`
   (`editor/panels/selector.py:161-175`, ending
   `root.insertChild(1, theme_item); self._theme_item = theme_item`): append
   the Tutorial leaf immediately after TU-3's expected Cutscenes-leaf block
   (`root.insertChild(2, cutscenes_item)`):
   ```python
   tutorial_item = self._make_item(
       _TUTORIAL_LABEL, "ui", (_TUTORIAL_LABEL,))
   tutorial_item.setData(0, _TUTORIAL_ROLE, True)
   root.insertChild(3, tutorial_item)
   self._tutorial_item = tutorial_item
   ```
   (indices 2/3 assume TU-3 takes 2; if TU-3 hasn't landed, use
   `insertChild(2, tutorial_item)`).
6. **`_emit_selection` dispatch** (`editor/panels/selector.py:454,468-474`,
   the `_THEME_ROLE` check-and-return): append a `_TUTORIAL_ROLE`
   check-and-return immediately after TU-3's expected `_CUTSCENES_ROLE`
   branch, before the `_SCREEN_ROLE` check at `:475`:
   ```python
   if items[0].data(0, _TUTORIAL_ROLE):
       self.tutorial_selected.emit()
       if "ui" in self._domains:
           self.domain_selected.emit("ui")
       return
   ```

### Modified: `editor/panels/CLAUDE.md` (ALSO touched by TU-2 and TU-3)
Append a new `## Tutorial panel (panels/tutorial_panel.py; TU-4)` subsection
**immediately before the final `## Verify` heading**
(`editor/panels/CLAUDE.md:717`) — the same slot every prior phase used
(compare `## Theme panel` at `:636`, itself right before `## Verify`).
Concretely: whatever subsection TU-2 and/or TU-3 land first will already sit
immediately before `## Verify`; TU-4's subsection is inserted **between the
last of those and `## Verify`**, never after `## Verify`. Content: the
staged-edit pattern, the "Tutorial" leaf under "ui" (mirrors Theme), the
empty-text guard, and the "steps round-trip untouched" invariant.

### Also update `tools/tests/test_editor_viewport.py:1371-1398`
(`TestPurity`'s import list): append `editor.panels.tutorial_panel,
editor.tutorial_ops` to the code string, after whatever TU-3 appended (or
directly after `editor.panels.game_theme, editor.theme_ops,` at `:1390` if
TU-3 hasn't landed).

### Open questions for the orchestrator
1. **`selector.py` numbering collision**: TU-3 and TU-4 are marked mutually
   parallelizable in the plan (`planning/TutorialPLAN.md:125-127`), but both
   need a new `UserRole + N` marker in the same file — a real merge/semantic
   collision if executed concurrently on separate branches. Recommend either
   (a) serializing `selector.py` edits specifically (TU-3 lands, THEN TU-4
   rebases and picks the next free `UserRole` offset), or (b) the
   orchestrator reconciling the two diffs by hand at merge time. This brief
   assumes (a).
2. **TU-1's actual `tutorial.json` key names** are unknown at brief-authoring
   time (TU-1 hasn't landed in this worktree). The phase-executor must read
   the real file/schema first and bind the panel's fields to whatever keys
   exist — the placeholder names in §1 (`messages.message_1`/`message_2`)
   are illustrative only.
3. **Where exactly TU-3 places its Cutscenes leaf** (this brief assumes "ui"
   category, third child, mirroring Theme) is TU-3's own design call, not
   fixed by its one-line Files entry in the plan. If TU-3's actual
   implementation puts Cutscenes somewhere else (its own top-level node, a
   different category), the `insertChild` indices above need renumbering but
   the Tutorial leaf's OWN position (append after whatever TU-3 did) still
   holds.

## 4. Exit gate + Quick Test

**Tests** (offscreen Qt, temp data dir — `TempDataCase`, per
`editor/CLAUDE.md:239-260`):
- `TestTutorialPanel`: loading a temp-tree `tutorial.json` populates both
  text fields + both checkboxes; editing a text field or toggling a
  checkbox shows the dirty dot + enables Save; `_on_save` (or the Save
  button via `QTest.mouseClick`) writes through `write_validated` and the
  reloaded on-disk doc matches; the `steps` array is byte-identical before
  and after a text-only edit + save; an all-whitespace text commit is
  rejected (the field reverts, no dirty dot, Save stays disabled — or, if
  the implementer instead lets it through client-side and relies on the
  schema, assert `write_validated` raises and nothing lands on disk — either
  is acceptable per the plan's "blocked or schema-rejected loudly" wording,
  but pick ONE and test it).
- Selector test: the "Tutorial" leaf exists under "ui", clicking it emits
  `tutorial_selected` + `domain_selected("ui")`.
- `TestPurity` still passes with the two new modules imported.

**Exit gate**:
```bash
py tools/smoke.py
py tools/testgate.py check
```
`GATE PASS` required — zero tolerance, per root `CLAUDE.md`'s "Universal
exit gate".

**Live Quick Test** (verbatim from the plan,
`planning/TutorialPLAN.md:207-208`): `py editor/main.py` → select the
"Tutorial" leaf (selector ▸ ui ▸ Tutorial) → flip `first_loss_costs_life` →
click "Save Tutorial Changes" → close the editor → reopen `py
editor/main.py` → select the Tutorial leaf again → the toggle is still in
its flipped state (proves the write round-tripped through
`data/tutorial/tutorial.json` on disk, not just in-memory).
