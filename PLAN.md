<!-- active-plan: UiEditorParentingPLAN.md | set: 2026-08-11 -->
> **Active plan:** UiEditorParentingPLAN.md (mirror). Source of truth:
> `planning/UiEditorParentingPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

# UiEditorParentingPLAN.md — widget parenting and the rest of the Unreal-grade UI editor

Phased, agent-executable plan (same family as `UiTextBindingPLAN.md` /
`NewEnemyTypesPLAN.md`). Base branch: `Development`; work lands on
`UiImplementation`. Runnable via
`/execute-plan-phases planning/UiEditorParentingPLAN.md P-1-P-6` or
phase-by-phase.

## 0. What already landed (do NOT redo)

An earlier session on this branch closed the first half of the designer's
complaint. Read this section before planning anything — the uncommitted diff on
`UiImplementation` already contains all of it.

| Landed | Where |
|---|---|
| Position-only text anchors (`rect` = `(x, y, 0, 0)`) are selectable, draggable and visibly outlined | `editor/panels/_screen_primitives.py::interaction_rect`, `viewport._interaction_rect` |
| Hit-testing picks the SMALLEST candidate, so a readout on a panel wins over the panel | `viewport._hit_widget` |
| Resize handles suppressed on anchors; a marker shows the stored anchor point instead | `viewport._submit_screen_selection` |
| X/Y/W/H spinboxes move the widget LIVE (no Enter), one undo step per burst | `editor/panels/screen_details.py` (`_on_rect_changed`, `_LIVE_COMMIT_MS`) |
| `font_key` + `align` recorded as optional `screen_defaults.json` keys, so anchors measure correctly | `data/schemas/screen_defaults.schema.json`, `tools/export_ui_layouts.py::_widget_entry` |
| Every HUD widget has a human display name (Love counter, Love per round, Level counter, Round counter, XP bar, …) | `tools/export_ui_layouts.py::_DISPLAY_NAMES` |
| Level-up option boxes are individually editable widgets (`option_box_0..2`), with an anti-softlock guard | `game/ui/levelup.py` |
| Construct cards ("the buying options") are individually editable widgets (`card_<building_type>`) | `game/ui/building_ui.py` |
| `hud.round_label` declares `align="center"` on its holder rather than at the call site | `game/ui/hud.py` |

Verified live: all 20 `hud` widgets, all 5 `levelup` widgets and all 15
`building_panel/construct` widgets are selectable in a real `MainWindow`;
`py tools/smoke.py` is OK. Golden-parity was measured to be a rendering no-op
(capturing with the pre-change 2-option mock reproduces the old baseline
byte-for-byte on every screen).

## 1. Vision

The designer's remaining ask, verbatim: **"I need the ability to parent widgets
to each other, and all widgets to be parented sensibly."** Plus the standing
frame for all of this: *"the UI editor should be similar to the one in Unreal
Engine."*

Today every widget in `data/ui/screen_defaults.json` is a flat, independent
record. `hud.love_text` sits inside `hud.love_panel` and `hud.round_label` sits
above `hud.btn_end_turn` purely because their numbers happen to agree — nothing
expresses the relationship. So moving the love panel leaves its counter, its
icon and its level readout behind, and a designer restyling the HUD has to
re-derive by hand what the game's own `layout()` already knows.

Unreal's answer is a widget hierarchy: a tree in the outliner, a transform that
composes down it, and visibility/enable state that inherits. That is the target.

**Outcome.** Every screen ships a sensible default parent tree. The editor shows
that tree instead of a flat list, moving a parent carries its children, and a
designer can re-parent by dragging in the tree.

## 2. Decisions (with rationale)

- **D1 — The hierarchy is DATA, authored by the exporter, in
  `screen_defaults.json`.** One optional `parent` key per widget record (a
  sibling of `display_name`/`font_key`/`align`), naming another id in the same
  screen+view. The exporter knows the real structure — `hud.py`'s
  `_layout_readouts()` literally computes the readouts off `love_panel`'s rect —
  so "parented sensibly" is a mapping written once beside `_DISPLAY_NAMES`, not
  a designer chore. Absent `parent` = a root widget, so every screen keeps
  working before its mapping is filled in.
- **D2 — The cascade happens at EDIT time; the saved doc stays ABSOLUTE.**
  Dragging a parent writes an updated absolute `rect` for the parent AND each
  descendant, in one undo command. The alternative (store child rects relative
  to the parent, resolve at `ScreenSkinning.apply` time) would overturn the
  game's documented **"no cascade"** convention (`game/ui/CLAUDE.md`: *"a rect
  override on one of those rows does not retarget this panel"*), impose an
  apply-order dependency the flat setattr loop does not have, and put a
  resolution step between the designer and what the player sees. Edit-time
  cascade gives the full Unreal feel with **zero runtime risk and no
  `ui_screen.schema.json` change for the geometry**.
  - Consequence to accept: the game's own `layout()` still recomputes defaults
    each frame with no cascade. Parenting is an AUTHORING relationship, not a
    runtime one. Say so in the panel's tooltip.
- **D3 — Re-parenting is a designer action and IS persisted**, so it needs the
  one schema change: an optional `parent` key in `ui_screen.schema.json`'s
  per-widget override object (same absent-by-default shape as every other key).
  `null` re-roots a widget whose default parent the designer rejects. Nothing
  in `game/` reads it; it is authoring metadata that rides the existing
  override doc so it lives with the rest of the screen's authored state.
- **D4 — Visibility inherits in the editor PREVIEW only.** A widget whose
  ancestor is hidden is not drawn and not hit-testable in screen mode. The
  saved `visible` override is per-widget and untouched — the game keeps
  resolving each widget's own flag, exactly as now. Same argument as D2: the
  editor models the hierarchy, the data does not smuggle it into the game.
- **D5 — A cycle is unrepresentable, not an error to recover from.** The
  re-parent action refuses a drop that would make a widget its own ancestor
  (the control is disabled/rejected, ED-30's "invalid input unrepresentable"),
  and the resolver additionally treats an unresolvable/cyclic chain as
  "root" rather than raising — a `screen_defaults.json` hand-edit must never
  be able to hang a Qt paint handler.
- **D6 — The tree replaces the flat widget list; it does not sit beside it.**
  A second parallel widget selector would violate the editor's
  single-selection-model invariant. `ScreenDetailsPanel.widget_list`
  (`QListWidget`) becomes a `QTreeWidget` with the SAME `UserRole` = code id
  contract, so `widget_selected`/`select_widget` and every `push_*` call site
  are unchanged.

## 3. Open questions — ANSWERED by the designer (do not re-ask)

All three were answered before implementation began; the plan below stands as
written:

1. **Dragging a parent moves its children BY DEFAULT, no modifier held** —
   Unreal's behaviour. P-3 as written.
2. **Moving cascades; resizing does NOT.** Resize a parent and its children
   stay put.
3. **Real containers only** — exactly P-2's table, parenting only to
   already-id'd widgets whose rects the children's defaults are genuinely
   computed from. No invented GROUP / `CanvasPanel` nodes (that stays parked
   in P-6), and no `screen_defaults.json` shape change beyond the optional
   `parent` key.

## 4. Phases

**Status: P-1 – P-5 LANDED** (branch `claude/ui-editor-parenting-v5mo7h`, off
`UIfixing`). P-6 is untouched and stays parked.

### P-1 — The `parent` key and a pure resolver — **DONE**
- `data/schemas/screen_defaults.schema.json`: optional `parent` (string,
  `minLength: 1`) on the widget `$def`, documented as authoring metadata the
  game never reads.
- `data/schemas/ui_screen.schema.json`: optional `parent` (string **or null**)
  on the per-widget override object, for D3 re-parenting.
- New pure module `editor/widget_tree.py` (Qt-free, pygame-free, in
  `TestPurity`): `resolve_parent(widget_id, spec, override)`, `build_tree(
  defaults_widgets, doc_widgets) -> {root_id: [child_id, ...]}` with a stable
  order, `descendants(tree, widget_id)`, `would_cycle(tree, child, new_parent)`.
  Cycle/dangling-parent chains resolve to root (D5).
- **Landing condition:** no behaviour change anywhere; the resolver is unit-
  exercised and nothing calls it yet.
- **Landed as specified**, with three additions the later phases needed:
  `parent_map()` (the sanitised `{id: parent}` primitive `build_tree` is
  built on), `ancestors()` (P-5's visibility walk) and `legal_parents()`
  (P-4's combo, so the combo and the drop refuse the same set). 20 unit tests
  in `tools/tests/test_widget_tree.py`; the module is in `TestPurity`.

### P-2 — Author the default hierarchy — **DONE**
- A `_PARENTS` mapping in `tools/export_ui_layouts.py`, beside `_DISPLAY_NAMES`
  and applied by the same `_apply_display_names` walk (which already handles
  the flat `widgets` map AND every `views.<name>` level, so this needs no new
  traversal).
- Starting hierarchy, derived from what each screen's `layout()` already
  computes off what:

  | Screen | Parent | Children |
  |---|---|---|
  | `hud` | `love_panel` | `love_text`, `icon_love`, `lvl_label`, `icon_xp`, `xp_bar`, `xp_text` |
  | `hud` | `readout_panel` | `income_text`, `lives_text`, `icon_lives`, `tiles_text` |
  | `hud` | `btn_end_turn` | `round_label` |
  | `levelup` | `backdrop` | `heading`, `option_box_0..2` |
  | `building_panel` | `panel` | `close_btn`, `action_btn`, `move_btn`, `boss_btn`, every `stat_*`/`info_*`, every `card_*`, every mode title/hint |
  | `building_panel` | `preview_panel` | every `preview_*` |
  | `cheat_menu` | `panel` | every `btn_*`, `title`, `jump_label`, `round_field` |
  | `add_name` | `panel` | `title`, `btn_add`, `btn_back`, `hint`, `msg_text`, `pool_count` |
  | `main_menu`/`pause`/`settings`/`credits`/`game_over` | `backdrop` | that screen's title + buttons + labels |
  | `boss_cutscene` | `backdrop` | `headline`, `subtitle`, `box_a`, `box_b` |
  | `overlays`, `game_log`, `enemy_intro` | — | flat (2, 1 and 2 widgets) |

  Every parent above is a real, already-id'd container whose rect the children's
  defaults are genuinely computed from — no invented nodes (see Q3).
- Regenerate `data/ui/screen_defaults.json`.
- **Landing condition:** the file gains `parent` keys and nothing else moves;
  the editor still behaves exactly as it does today (nothing reads the key yet).
- **Landed:** 243 `parent` keys added to `data/ui/screen_defaults.json` and
  **not one other line changed** (measured: `git diff -U0` shows zero
  non-`parent` add/remove lines). The mapping is TWO tables rather than one —
  `_PARENTS` for the explicit pairs (hud's 11, `building_panel`'s four
  `preview_*`) and `_PARENT_CONTAINERS` for the nine screens with one real
  container that owns everything else (`{screen: (parent_id, exempt_ids)}`).
  Spelling `building_panel`'s ~80 stat cells out pair by pair would be noise
  that drifts the moment a stat row is added, and there is no judgement in
  those pairs. A parent is written only when the parent id is present in the
  SAME widgets map, so each of `building_panel`'s five views parents to
  whichever container it actually shows. Resolved roots match the table
  exactly.

### P-3 — The viewport cascade — **DONE**
- `viewport._screen_move`/`_screen_release`: a move drag on a widget with
  descendants applies the same delta to every descendant's rect and commits ONE
  undoable command covering the whole subtree (a new
  `UIScreenSession.push_move_subtree(changes)`, modelled on `map_session`'s
  stroke commands — full old/new per widget, never a delta).
- Arrow-key nudge cascades identically (it shares `push_move`'s contract).
- Resize does NOT cascade (Q2).
- Selection chrome: draw a dimmer secondary outline around the moving subtree so
  the designer sees what is coming along.
- **Landing condition:** dragging `hud.love_panel` carries its counter, icon,
  level label and XP bar; one Ctrl+Z puts all of them back.
- **Landed and exercised in a real headless `ViewportPanel`:** a drag on
  `hud.love_panel` moved it plus all six descendants by the same delta, left
  `round_label` (a different parent) alone, produced exactly ONE undo command,
  and one undo restored all seven. Arrow nudge behaved identically. A resize
  drag captured no subtree and moved no child. Six dim `SUBTREE_COLOR`
  outlines were submitted for the six descendants.
- One implementation note worth keeping: each descendant's new rect is
  computed from ITS OWN rect at press, never from the rect the previous move
  event wrote, so rounding cannot accumulate over a long drag.

### P-4 — The tree in the details panel — **DONE**
- `ScreenDetailsPanel.widget_list` `QListWidget` -> `QTreeWidget` (D6), same
  `UserRole` = code id contract, expanded by default, display names as text and
  the raw id as tooltip (`widget_display_name` stays the ONE naming rule).
- Drag-and-drop re-parent inside the tree writes `parent` through
  `push_field(widget_id, "parent", old, new)` — the existing per-key undoable
  path, so the "↺" reset button and "Reset ALL" cover it with no new code.
  `would_cycle` gates the drop (D5).
  - `editor/panels/timeline.py` is the repo's one prior `QDrag`/`QMimeData`
    user — copy its shape, including the "a real OS drag cannot be synthesized
    offscreen, so drive `dropEvent` directly" testing note.
- A per-widget **Parent** row in the form (a combo of legal parents + `(none)`)
  as the keyboard-accessible equivalent of the drag.
- **Landing condition:** the designer can re-parent `round_label` from
  `btn_end_turn` to `love_panel`, save, reopen, and it stuck.
- **Landed and exercised headlessly against a temp copy of `data/`:** the
  drop (driven straight into `dropEvent`) re-parented `round_label`, wrote one
  undoable command, re-drew the tree, saved, and a freshly opened session
  showed it under `love_panel`. A drop that would make a widget its own
  ancestor writes nothing.
- **`push_field` needed one addition the plan did not foresee.** D3's
  `null` re-root is unreachable through the existing path: `push_field(...,
  None)` means "the key is ABSENT" (restore the default parent), and there was
  no way to write a literal JSON null. `ui_screen_session` therefore gained a
  `NO_PARENT` sentinel plus the `parent_override()` accessor that reads the
  three states apart (absent / null / an id). Everything else — the "↺"
  button, "Reset ALL", undo — rides the unchanged per-key path.

### P-5 — Preview visibility inheritance — **DONE**
- `viewport._submit_screen_widget` and `_hit_widget` skip a widget with a hidden
  ancestor (D4). The details panel notes the reason on the Visible row rather
  than silently drawing nothing ("hidden by parent <name>").
- **Landing condition:** hiding `love_panel` hides its whole cluster in the
  preview; the saved doc still carries exactly one `visible` override.
- **Landed and exercised headlessly:** hiding `love_panel` marked all six
  descendants hidden (and `round_label`, a different parent, not), skipped all
  seven in the draw pass, made none of them hit-testable, and the saved
  `hud.json` carried exactly `{"love_panel": false}`. The Visible row on a
  child reads `Visible  (hidden by parent "Love panel")` with the checkbox
  still enabled and its own flag untouched.
- **KNOWN GAP, deliberate:** the skip is in `_submit_screen_widget`, which is
  the fallback draw path. When the UT-2 recorded preview is IN SYNC the editor
  replays the recorded draw list instead, and that recording knows nothing
  about parenting — a child of a hidden parent can still appear there until
  the next Refresh Layouts. Closing it means teaching the recorder the
  hierarchy, i.e. giving the exporter a runtime notion of parenting, which is
  exactly what D2/D4 keep out. Left as-is and reported.

### P-6 — Parked / candidates (do NOT start without asking)
Named so the next session does not silently expand scope:
- **Group nodes** that are not real widgets (Unreal's `CanvasPanel`) — see Q3.
  Needs a home for a node with no game-side widget, i.e. a real
  `screen_defaults.json` shape change.
- **Anchors/layout slots** (Unreal's anchor medallion — "pin to bottom-right").
  This is the genuinely Unreal-ish feature after parenting, and it WOULD need a
  runtime resolution step, i.e. it overturns D2.
- Multi-select + align/distribute, snapping guides, z-order reordering,
  copy/paste of widget styling.

## 5. Known issues this plan does NOT fix

- **`test_ui_layout_export.TestScreenPreviewExport::
  test_committed_previews_are_fresh` is RED and was left red.** It regenerates
  `data/ui/screen_previews.json` and byte-compares; on a Linux container the
  font stack measures one text height as 14 where the committed (Windows-
  authored) file says 15, in 16 places. **Measured to predate this branch:**
  running the exporter from the UNMODIFIED `UIfixing` tip produces the same
  16-line difference against the same committed file, and this branch's own
  exporter change is a previews NO-OP (its output is byte-identical to the
  baseline's). The committed `screen_previews.json` was therefore left exactly
  as it was rather than "fixed" into a Linux-flavoured version that would
  flip straight back on the designer's machine. The sibling
  `test_committed_defaults_are_fresh` passes.

- **The test suite is broken and needs its own rework** (the user's call this
  session: *"fuck the tests entirely, they're broken and need a rework in
  future"*). What is known concretely: `tools/tests/fixtures/data/ui/
  screen_defaults.json` is a STALE pre-UR-2 mirror (1280x720 rects), and four
  `test_ui_skinning.py` tests asserted E-37 *absence* paths against fixture
  state they never pinned — they were red at `HEAD` before this branch's work
  and were fixed in passing by pinning the absence (`drop_screen_defaults`/
  `drop_screen_overrides`). Treat the suite as untrustworthy until that rework;
  do not let a red test block this plan without checking it against `HEAD`
  first.
- **Construct card labels overhang their card** — a real, pre-existing, in-game
  visual defect, invisible until the cards gained ids. Measured at the shipped
  118px card width, `md` font: `Bush Wall Builder  12` needs 151px (+33),
  `Attack Booster  12` 130px (+12), and five others overflow. It is the exact
  UR-5 defect class (the panel halved at UR-2, the font did not). The fix is a
  design call — narrower copy, a smaller font, or a wider panel column — so it
  is reported as a non-blocking lint
  (`test_ui_min_targets.test_report_dynamic_label_overflow`) rather than
  silently changed. **Ask the designer which they want.**

## 6. Verify

```bash
py tools/smoke.py
py editor/main.py     # screen mode: hud, levelup, building_panel/construct
```
Live-exercise the cascade and the re-parent drag; state what was exercised in a
real editor run versus read statically.
