# Phase TU-3 — Editor: Cutscenes area

Source plan: `planning/TutorialPLAN.md` (D4, build-order row TU-3). Depends on
TU-1 (`data/video/cutscenes.json` + `data/schemas/cutscenes.schema.json` must
exist and validate before this phase's code runs — this brief assumes that
schema shape verbatim and does not create it). Use the **`/add-editor-feature`**
skill as the opening move — this brief is that skill's per-task detail, not a
replacement for it.

## 1. Behavioral spec

**The registry this phase edits** (TU-1, not yet landed, but pinned by D4):
`data/video/cutscenes.json`, entries `id -> {video, audio (nullable), length,
trigger}`, `trigger` enum `intro | first_end_turn` — `planning/TutorialPLAN.md:77-88`.
Seed content per TU-1's file list: `intro -> cutscene.mp4, length 44.2`,
`first_end_turn -> placeholder video, audio null` — `planning/TutorialPLAN.md:136-138`.

**Goal verbatim** (`planning/TutorialPLAN.md:176-181`): a Cutscenes editor
surface — one row per registry entry (including `intro`): import an MP4
(copied under `data/video/`), pick an optional companion audio file (ogg/mp3,
copied beside it), length auto-read via cv2 when available (manual spin-box
fallback), trigger shown read-only. Writes `data/video/cutscenes.json` via
`write_validated`.

**Tests required** (`planning/TutorialPLAN.md:186-188`): import copies the
file and rewrites the registry (validated, deterministic format); missing cv2
path falls back to the manual length field; audio optional (nullable
round-trip).

**Exit gate** (`planning/TutorialPLAN.md:190-192`): smoke + full testgate;
live Quick Test: import a small mp4 into the `first_end_turn` slot, confirm
the file lands in `data/video/` and the registry updates.

**Existing asset-importer pattern to model the import-copy flow on**
(explicitly called out in the plan and in the task):
- `editor/asset_import.py:139-183` (`import_idle_sheet`) — Qt-free, pygame-free
  pure helper: copies the source file to a deterministic destination path keyed
  by the slot/id (`imported/<slot_key>.png`, never the source filename),
  computes derived metadata (frame grid) from the copied file, then
  read-modify-writes the whole manifest doc through ONE
  `write_manifest_doc`/`write_validated` call (`editor/asset_import.py:46-52`).
  This phase's `import_video`/`import_audio` mirror that shape exactly:
  deterministic destination name, one field-write path.
- `editor/panels/details.py:848-855` (`_on_import_clicked`) — the Qt half:
  `QFileDialog.getOpenFileName(self, "<title>", "", "<filter>")`, then calls
  the pure import function directly. Model each row's "Import MP4…"/"Import
  Audio…" buttons on this.
- `editor/panels/game_theme.py:1-282` (`GameThemePanel`, UH-6) is the closest
  full-panel precedent for a **single leaf reached the selection-driven way**
  (not a per-entry Details context): `data_dir=None` injection, load-fresh-on-
  entry (`set_theme()`), one `saved` Signal MainWindow reacts to. This phase's
  panel copies that shell (constructor, `set_registry()` reload-on-entry
  method, a QScrollArea of rows) but writes **immediately per action**
  (import / length commit / audio pick / audio clear), not staged-then-Saved —
  there is no multi-field form to batch here, and `write_validated` failing
  loud on a bad write is preferable to a dirty-dot UI for a 4-field row.
- `engine/video.py:65-85` (`VideoSource.__init__`) — the lazy-cv2-import
  pattern to copy for length probing: `try: import cv2 \n except ImportError:
  cv2 = None`, guard every capture call on `cv2 is not None`. This phase's own
  probe (`cv2.VideoCapture(path).get(cv2.CAP_PROP_FRAME_COUNT) /
  .get(cv2.CAP_PROP_FPS)`) never raises when cv2 is absent or the file is
  unreadable — it returns `None` and the panel's manual spin-box is what ends
  up authoritative (D4's "graceful skip" contract, `planning/TutorialPLAN.md:290-292`,
  extends to the editor: missing cv2 must never block editing).
- `editor/data_io` write path: `engine/data_io.py:33-38` (`write_validated`) —
  the ONE call for both this phase's registry writes and (unrelated) every
  other `data/` write in the repo.

**Existing hardcoded intro asset this registry will eventually replace**
(TU-5, **not this phase** — cited only so the intro row's "why length 44.2"
and "why does `intro` already have a video" make sense to whoever opens this
panel first): `game/main.py:232-236` — `VideoSource(data_dir / "video" /
"cutscene.mp4", ui_balance["Menu"]["cutscene_length"], target_size=(view_w,
view_h))`. TU-1 seeds the registry's `intro` entry with this same file
(likely `video: "cutscene.mp4"`, `length: 44.2`) so this panel's `intro` row
shows a populated video/length on first open — it is **not** a placeholder row
like `first_end_turn`. TU-3 must not move or rename `data/video/cutscene.mp4`;
it only reads/writes the registry pointing at it. (`ui_balance["Menu"]
["cutscene_length"]` itself is untouched by this phase — TU-5 is what retires
it in favor of the registry's `length`.)

## 2. Architecture plan

**New pure helper module** `editor/cutscene_import.py` (Qt-free, pygame-free —
the `editor/asset_import.py` sibling, goes in `TestPurity`):
- `load_registry_doc(data_dir)` / `write_registry_doc(data_dir, doc)` — load
  tolerant of a missing/corrupt file (E-37: degrade to `{}`, mirroring
  `asset_import.load_manifest_doc`), write through
  `engine.data_io.write_validated` against `data/schemas/cutscenes.schema.json`
  (the ONE write path for this file, ED-31).
- `TRIGGER_ORDER = ("intro", "first_end_turn")` — display-order pin, the exact
  reason `editor/ui_screen_session.py`'s `VIEW_ORDER`/`ordered_views()` exists:
  `data_io.dumps_deterministic` sorts keys alphabetically on write
  (`first_end_turn` < `intro`), so iterating `doc` directly would show the
  placeholder row before the seeded intro row. `ordered_entry_ids(doc)` sorts
  by `(TRIGGER_ORDER.index(id) if id in TRIGGER_ORDER else len(TRIGGER_ORDER),
  id)` so a future trigger (the plan's "room to grow — boss etc.",
  `planning/TutorialPLAN.md:88`) still displays, appended after the two known
  ones, without a code change.
- `video_dest(cutscene_id, src_path)` -> `data/video/<cutscene_id><suffix>`
  (suffix from the source file, but the STEM is always the id — deterministic,
  never the source filename, same rule as `imported/<slot_key>.png`).
  `audio_dest(cutscene_id, src_path)` -> `data/video/<cutscene_id>_audio<suffix>`.
- `import_video(data_dir, cutscene_id, src_path)` — copies (via `shutil.copyfile`,
  `pad_to_frame`-style byte-identical-copy guard: skip the copy when source and
  destination already resolve to the same file), probes length with
  `probe_length_seconds(dest)`, returns `(relative_video_path, length_or_None)`.
  Caller (the panel) decides whether to overwrite the length field only when a
  probe succeeded — a `None` probe must never clobber a value the designer
  already typed.
- `probe_length_seconds(path)` — lazy `import cv2` (try/except ImportError ->
  `None`), `cv2.VideoCapture(str(path))`; if `not cap.isOpened()` or `fps <= 0`
  return `None`; else `frame_count / fps`. Every failure mode returns `None`,
  never raises (mirrors `engine/video.py`'s graceful-skip contract).
- `import_audio(data_dir, cutscene_id, src_path)` -> copies to `audio_dest(...)`
  (ogg/mp3 passthrough, no transcoding), returns the relative path.
- `clear_audio(data_dir, cutscene_id, doc)` -> deletes the file at the entry's
  current `audio` path if it exists (no refcount needed, unlike
  `asset_import.py`'s sheet-sharing model — an audio file here is always
  1:1-owned by its `cutscene_id`, never linked from a second entry) and
  returns the doc with `audio: None` for that id. The panel is what actually
  writes the doc back.

**New Qt panel** `editor/panels/cutscenes.py` (`CutscenesPanel(QWidget)`,
`data_dir=None` injection):
- `set_registry()` — (re)load `cutscene_import.load_registry_doc`, rebuild one
  row per `cutscene_import.ordered_entry_ids(doc)` inside a `QScrollArea`
  (the `GameThemePanel._rebuild_form` shape). Missing/invalid registry file
  degrades to a placeholder label (E-37, same as `GameThemePanel._show_unavailable`)
  — this is editor-side grace; TU-1's own smoke-test directory-exception
  validation is what keeps the on-disk file schema-valid in the first place.
- Each row (`QFormLayout` row, id as the label): trigger `QLineEdit` or
  `QLabel` set **read-only / disabled** (never editable — trigger is fixed by
  TU-1's script wiring); video filename `QLabel` (current `video` value, or
  "— none —"); `QPushButton("Import MP4…")` -> `QFileDialog.getOpenFileName`
  filtered to `"Video files (*.mp4)"` -> `cutscene_import.import_video` ->
  updates `doc[id]["video"]`, and if the probe returned a length, also
  `doc[id]["length"]` (and the row's length spin box, `blockSignals` around
  the set so it doesn't re-fire a spurious write) -> one
  `cutscene_import.write_registry_doc`; audio filename `QLabel` + `QPushButton
  ("Import Audio…")` (filter `"Audio files (*.ogg *.mp3)"`) ->
  `cutscene_import.import_audio` -> `doc[id]["audio"] = <relative path>` ->
  write; `QPushButton("Clear Audio")`, **enabled only when `audio` is not
  None** -> `cutscene_import.clear_audio` -> write; length
  `_NoWheelDoubleSpinBox` (imported from `editor.panels.balancing`, never
  copied — the editor-wide convention, `editor/panels/CLAUDE.md:94-101`),
  range from the schema's `length` bounds (`minimum`/`maximum` if TU-1's
  schema declares them, else a sane literal floor of `0.1`), commits on
  `editingFinished` (not `valueChanged` — the `set_slot_frame_size` precedent,
  `editor/panels/CLAUDE.md:306-308`) -> `doc[id]["length"] = value` -> write.
- No add/remove-row affordance: TU-1 owns which ids exist; this phase never
  adds or deletes a registry entry (out of scope — "room to grow" is a data
  shape allowance, not a TU-3 UI feature).
- No `saved` Signal / no dirty-dot state: every action above is already a
  complete, immediate write (see Architecture note above on why this phase
  skips the staged-edit pattern despite `GameThemePanel`'s shape).

**Selector wiring** — a **new single "Cutscenes" leaf**, third child of the
"ui" category node (after "Screens" then "Theme" — the existing UH-6
docstring's ordering invariant, `editor/panels/selector.py:36-41`), following
the `_THEME_ROLE` pattern exactly (this file is **not** listed in the plan's
TU-3 "Files" line, but is required to reach the panel at all — see §3's
shared-file note; flagging for the orchestrator, not skipping it).

## 3. File scope + shared-file contract

### New files (this phase only, no other phase touches these)
- `editor/cutscene_import.py` — pure helper module, described above. Add to
  `TestPurity`'s import list (`tools/tests/test_editor_viewport.py:1374-1394`):
  insert `"editor.cutscene_import, "` alongside the other bare `editor.*`
  pure-helper imports (e.g. right after `"editor.registry_ops,
  editor.balancing_history, "` on `tools/tests/test_editor_viewport.py:1378-1379`).
- `editor/panels/cutscenes.py` — the Qt panel, described above. Add to the
  SAME `TestPurity` import list's `editor.panels.*` group: insert
  `"editor.panels.cutscenes, "` alongside `"editor.panels.game_theme,
  editor.theme_ops, "` (`tools/tests/test_editor_viewport.py:1390`).
- Tests: add a new `TestCutscenesPanel(TempDataCase)` class to
  `tools/tests/test_editor_panels.py`, immediately after `TestGameThemePanel`
  (ends at `tools/tests/test_editor_panels.py:1182`, `TestThemeSwitch` starts
  at `:1185` — insert the new class in the blank line between them). This file
  is already tiered `"editor"` in `conftest.py:54`; a new class inside it
  needs no `conftest.py` change. Mirror `TestGameThemePanel`'s shape
  (`tools/tests/test_editor_panels.py:1122-1182`): `make()` returns
  `self.track(CutscenesPanel(data_dir=self.data_dir))`; one test per required
  behavior (import copies + registry rewrite + deterministic bytes; cv2-absent
  fallback via `mock.patch` on the cv2 import path returning `None` from
  `probe_length_seconds`, or monkeypatching `cutscene_import.probe_length_seconds`
  directly to avoid depending on cv2 being installed in CI; audio import +
  Clear Audio round-trips `audio: None`). Needs a tiny real MP4 fixture or a
  monkeypatched `probe_length_seconds` — **prefer monkeypatching** so the test
  suite never depends on a binary video fixture or on cv2 being installed; a
  zero-byte/garbage "mp4" is enough to exercise the copy-and-registry-write
  path as long as the probe function itself is stubbed.

### Modified files — exact insertion points

**`editor/panels/selector.py`** (not listed in the plan's TU-3 file line —
see the open question below; required to reach the panel at all):
- New role constant, alongside `_THEME_ROLE` at
  `editor/panels/selector.py:91`: add `_CUTSCENES_ROLE = Qt.ItemDataRole.UserRole
  + 6` on the next line.
- New label constant, alongside `_THEME_LABEL` at `:95`: add
  `_CUTSCENES_LABEL = "Cutscenes"`.
- New Signal, alongside `theme_selected` at `:112`: add
  `cutscenes_selected = Signal()        # TU-3: the single Cutscenes leaf`.
- `self._theme_item = None` at `:126` — add `self._cutscenes_item = None`
  on the next line.
- In `__init__`'s `elif category.key == "ui":` block
  (`editor/panels/selector.py:161-175`), immediately after the existing
  `self._theme_item = theme_item` line (`:175`), insert:
  ```python
  # TU-3: a single "Cutscenes" leaf, third child (after Screens, then
  # Theme — the UH-6 ordering invariant above), same shape as Theme:
  # nothing to enumerate here either (the registry's own row list lives
  # inside the panel), so a marker role, not a from-disk id list.
  cutscenes_item = self._make_item(
      _CUTSCENES_LABEL, "ui", (_CUTSCENES_LABEL,))
  cutscenes_item.setData(0, _CUTSCENES_ROLE, True)
  root.insertChild(2, cutscenes_item)
  self._cutscenes_item = cutscenes_item
  ```
- In `_emit_selection` (`editor/panels/selector.py:454-484`), immediately
  after the existing Theme-leaf block (ends `:474`, right before the
  `screen_id = items[0].data(0, _SCREEN_ROLE)` line at `:475`), insert:
  ```python
  if items[0].data(0, _CUTSCENES_ROLE):
      # Cutscenes leaf (TU-3): same never-node_selected rule as
      # Theme/Screens/Maps.
      self.cutscenes_selected.emit()
      if "ui" in self._domains:
          self.domain_selected.emit("ui")
      return
  ```
- No `_context_menu` change needed: the leaf's payload path is non-empty
  (`(_CUTSCENES_LABEL,)`, not `()`), so the existing "only a category ROOT
  gets a menu" gate already suppresses one here — the exact behavior Theme
  and Screens leaves already get for free.

**`editor/main.py`** (shared with TU-4 — see contract below):
- Panel construction block (`editor/main.py:99-118`): immediately after
  `self.game_theme = GameThemePanel(data_dir=data_dir)  # UH-6: Theme leaf`
  (`:109`), insert:
  ```python
  self.cutscenes = CutscenesPanel(data_dir=data_dir)  # TU-3: Cutscenes leaf
  ```
- Import block (top of file, alongside the other `editor.panels.*` imports,
  `editor/main.py:59-67`): insert `from editor.panels.cutscenes import
  CutscenesPanel` in the existing alphabetized block, between
  `from editor.panels.balancing import BalancingPanel` and `from
  editor.panels.details import DetailsPanel` (alphabetical: balancing, THEN
  cutscenes, THEN details).
- Wiring block (`editor/main.py:180-185`, right after the Theme wiring
  comment): immediately after `self.game_theme.saved.connect(self._on_theme_saved)`
  (`:185`), insert:
  ```python

  # Cutscenes wiring (TU-3): the "Cutscenes" leaf -> right_stack; reload on
  # entry mirrors Theme's reload-on-entry convention (registry writes are
  # immediate per-action inside the panel, so there is no saved signal here).
  self.selector.cutscenes_selected.connect(self._on_cutscenes_selected)
  ```
- `right_stack` index list (`editor/main.py:309-313`): immediately after
  `self.right_stack.addWidget(self.game_theme)      # index 3: Theme (UH-6)`
  (`:313`), insert:
  ```python
  self.right_stack.addWidget(self.cutscenes)       # index 4: Cutscenes (TU-3)
  ```
- Handler method: insert a new method block immediately before the
  `# -- frame drive --` comment (`editor/main.py:954`), i.e. right after
  `_on_theme_saved` ends (`:952`):
  ```python

  # -- Cutscenes panel (TU-3) ------------------------------------------------

  def _on_cutscenes_selected(self):
      """The selector's Cutscenes leaf: reload the registry fresh (same
      reload-on-entry convention as Theme) and show the panel."""
      self.cutscenes.set_registry()
      self.right_stack.setCurrentWidget(self.cutscenes)
  ```

**`editor/panels/CLAUDE.md`** (shared with TU-2 and TU-4):
- Append a new top-level section immediately **before** the `## Verify`
  heading (`editor/panels/CLAUDE.md:717`) — i.e. insert after the blank line
  that follows the Theme panel section's last line and before `717:## Verify`.
  New heading: `## Cutscenes panel (\`panels/cutscenes.py\`, \`cutscene_import.py\`; TU-3)`,
  body summarizing: the "Cutscenes" leaf as third child of "ui" (after
  Screens, Theme), one row per registry entry via `TRIGGER_ORDER`
  (display-order pin, the `ordered_views()` precedent), immediate per-action
  writes (no staged/dirty-dot model, unlike `GameThemePanel`), cv2-optional
  length probe with manual spin-box fallback, deterministic
  `<id>.<ext>`/`<id>_audio.<ext>` destination naming (never the source
  filename — the `imported/<slot_key>.png` precedent).

### Shared-file contract with TU-2 / TU-4 (for the orchestrator)

- **`editor/panels/selector.py` is not in the plan's TU-3 "Files" line**
  (`planning/TutorialPLAN.md:183-184` lists only a new panel module + tests,
  modified `editor/main.py` + `editor/panels/CLAUDE.md`) but this brief adds it
  to scope — there is no way to reach a selection-driven panel without a tree
  leaf, and the existing precedent (Theme, UH-6) always pairs a new panel with
  a selector change. **Flagging this as a plan omission**, not silently
  patching around it: TU-4's Tutorial panel will need the exact same kind of
  leaf (its plan row also omits `selector.py`), so TU-4's brief should claim
  `editor/panels/selector.py` too, as a **fourth** "ui"-category child leaf
  (`root.insertChild(3, tutorial_item)`, after this phase's Cutscenes at index
  2) with its own `_TUTORIAL_ROLE`/`tutorial_selected` — mechanically
  identical to this phase's diff, landing after it. Recommend the
  orchestrator sequence TU-3 before TU-4 (or hands TU-4's implementer this
  brief as the copy-paste template) so the two inserts don't collide on the
  same `elif category.key == "ui":` block.
- **`editor/main.py`**: this phase's four edits (construction line 110, import
  line ~62, wiring after 185, right_stack index 4 after 313, handler method
  before line 954) are all **pure insertions at fixed anchors that do not
  move** when TU-4 lands its own panel afterward — TU-4 should insert its
  construction line immediately after this phase's (`self.cutscenes = …`),
  its wiring immediately after this phase's `cutscenes_selected.connect(...)`
  line, its `right_stack.addWidget` immediately after `index 4: Cutscenes`
  as `index 5`, and its handler method immediately after
  `_on_cutscenes_selected`. Landing TU-3 first makes every one of TU-4's
  anchors "immediately after the TU-3 line" rather than a guess at the
  pre-TU-3 line numbers restated here.
- **`editor/panels/CLAUDE.md`**: TU-2's edit is a **bullet inside the existing
  `## Phase 6 — tilemap mode` section** (`editor/panels/CLAUDE.md:331-421`,
  describing the fourth paint mode) — a different anchor from this phase's,
  so no collision. TU-4's edit is a **new top-level section**, same anchor
  family as this phase's (immediately before `## Verify`) — recommend TU-4's
  section land immediately **after** this phase's new "Cutscenes panel"
  section (both still before `## Verify`), so the two inserts stack rather
  than compete for the same line.

## 4. Exit gate + Quick Test

**Automated gate:**
```
py tools/smoke.py
py tools/testgate.py check
```
Both must print their pass line clean (`GATE PASS` for testgate) — this is the
hand-back bar, not a suggestion. Run `py -m pytest -m editor` while iterating
(fast Qt tier); run the full `testgate.py check` once at the end, not
mid-task.

**Live Quick Test** (`py editor/main.py`):
1. In the selector tree, expand the "ui" category node; click "Cutscenes"
   (third child, after "Screens" and "Theme") — confirm the right pane swaps
   to the new panel and shows two rows, `intro` (video/length already
   populated from TU-1's seed) and `first_end_turn` (placeholder).
2. On the `first_end_turn` row, click "Import MP4…", pick a small `.mp4` file
   from disk. Confirm: the file appears at `data/video/first_end_turn.mp4`;
   the row's video filename label updates; if cv2 is installed and the file
   is readable, the length spin box updates to the probed duration; on disk,
   `data/video/cutscenes.json` now has `first_end_turn.video ==
   "first_end_turn.mp4"` (or whatever relative form the panel writes) and
   still validates against `data/schemas/cutscenes.schema.json` (re-open the
   editor, or run `py tools/smoke.py`, to confirm the write didn't corrupt the
   file).
3. Pick a companion `.ogg`/`.mp3` for the same row via "Import Audio…" —
   confirm the file lands beside the video (`data/video/first_end_turn_audio.*`)
   and the registry's `audio` field is no longer `null`. Click "Clear Audio" —
   confirm the field returns to `null` and the button disables again.
4. Confirm the `trigger` field on both rows is visibly read-only (disabled
   widget / no edit affordance) and never changes.

## Open questions for the orchestrator / a human

1. **`editor/panels/selector.py` is outside the plan's stated TU-3 file
   list** — this brief adds it (§3) because there is no other way to reach a
   selection-driven panel. Confirm this is the intended shape (vs., say, a
   toolbar button reached without a tree leaf) before dispatch.
2. **TU-1's exact `cutscenes.schema.json` field bounds** (is `length` bounded
   by `minimum`/`maximum`, or unconstrained?) are not yet known — this brief's
   spin-box range falls back to a literal floor of `0.1` if the schema
   declares none. Whoever executes TU-1 first should confirm the schema shape
   matches D4's `{video, audio (nullable), length, trigger}` exactly so this
   phase's `cutscene_import.py` needs no changes once TU-1 lands.
3. **Sequencing of TU-2/TU-3/TU-4 into `editor/panels/CLAUDE.md` and
   `editor/main.py`**: the plan calls them "mutually independent
   (parallelizable)" (`planning/TutorialPLAN.md:125-127`), but §3 above shows
   TU-3 and TU-4 land adjacent, non-conflicting-but-order-sensitive inserts in
   both shared files. Recommend the orchestrator lands TU-3 before TU-4 (or
   TU-4's brief explicitly anchors "immediately after TU-3's lines") rather
   than truly parallel branches that both diff off the pre-TU-3 file state.
