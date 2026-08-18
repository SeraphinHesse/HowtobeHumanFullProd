# CLAUDE.md — editor/panels

The PySide6 panels: viewport, selector (tree), balancing form, details/import,
palette, map-details. You reached here from `editor/CLAUDE.md`. Requirements:
SPEC.md §7 (`ED-*`). When you change a panel's conventions, update THIS doc.

**Two invariants govern every panel** (also in the router): everything is
**selection-driven** (hang new features off the single selected node, not parallel
state), and there is **one render path** — the viewport draws through
`engine/render` into an embedded surface; QPainter never draws tiles (ED-22).
**Every new editor module MUST be added to `test_editor_viewport.TestPurity`'s
import list.**

## Phase 3 — Qt viewport spike (`panels/viewport.py`, ED-2/22/23)
- **Embed = QImage-copy fallback, ACCEPTED.** The viewport renders the full engine
  pipeline (`RenderItem` → `Renderer` → offscreen `pygame.Surface` sized to the
  widget) then converts to a `QImage` (`surface_to_qimage`, pure/testable —
  `pygame.image.tobytes` + `QImage(..., Format_RGB888).copy()`) and paints it in
  `paintEvent` via `QPainter.drawImage`. No second render path, no QPainter-drawn
  tiles (ED-22) — QPainter only blits the converted frame.
- Measured live (1280x720, 20x20 grid): ~62.5 fps, ~8.5–11 ms/frame combined —
  clears the 60fps bar (ED-2); no lower-level embed needed at this scope.
  Re-measure if the grid grows much larger or many animated sprites are added.
- **SDL dummy-driver rule**: `viewport.py` sets `SDL_VIDEODRIVER=dummy` /
  `SDL_AUDIODRIVER=dummy` at **module level, before `import pygame`** — the
  editor's pygame surface is always an offscreen target; the editor never opens a
  real SDL window. Must stay first in the module. **NOTE this is a real
  `os.environ` mutation that every editor subprocess inherits** — the reason
  `run_controls` strips those vars before launching Play/Playbuild (see router).
- **Headless-drive**: `editor/main.py` exposes `main(max_frames=None)`; run under
  `QT_QPA_PLATFORM=offscreen` for CI/agent verification. Frames driven by a
  `QTimer` (`FRAME_INTERVAL_MS = 16`), never a busy loop. FPS measured over real
  wall-clock, logged to stdout + title ~1×/sec.
- **Input**: drag pan + wheel zoom call only `engine.coords` methods (no iso math).
  Pan accepts **either right-click-drag (ED-23 game "same feel") or
  left-click-drag** — left is an editor-only addition for input devices without a
  right button; `game/main.py` stays right-click-only. Zoom anchors on viewport
  centre. Panning is a no-op whenever the map's pixel extent fits inside the
  viewport on that axis (`CoordinateSystem.clamp` centers — expected, not a bug).
- One `QApplication` per test process (`QApplication.instance() or
  QApplication(sys.argv)`); Qt allows only one.

## Phase 4 — selector / balancing / domains (ED-3/30/31)
- **Shell layout** (`main.py`): plain `QSplitter`s — selector (left) | viewport
  (center) over balancing (bottom). Full docking + `.editor_prefs.json`
  persistence (ED-1) deferred. `MainWindow(max_frames=None, data_dir=None)`; first
  listed domain selected on startup.
- **`data_dir` injection**: every editor module takes `data_dir=None` (defaults to
  `<repo>/data`) — lets tests run against a tempfile copy and never mutate the repo.
- **`panels/selector.py`**: flat/merged `QTreeWidget` (Phase 5 extends it). Emits
  `domain_selected(str)` — the coupling to the shell.
- **`panels/balancing.py`** (recursive since Phase 9A): `set_domain(d)` re-reads
  data + schema fresh from disk and rebuilds the form inside a `QScrollArea`,
  recursing the 9A nested tree: object → `CollapsibleSection` (QToolButton arrow
  header; depth-1 groups start expanded, deeper collapsed), array of objects → one
  collapsed sub-section per index titled `[i] — <name>` when the item has a `name`
  field, array of scalars → one row per index (**fixed length** — no add/remove
  rows; `random_names` grows via the game's 9H add-name menu).
  - **Arrays of OBJECTS get `+ Row` / `− Row` (ER-5), gated ENTIRELY by the
    schema**: `can_add = "maxItems" not in node or len(items) < maxItems`,
    `can_remove = len(items) > minItems`. Every array that predates ER-5
    (`tiers`, `scale_tiers`, `round_counts`) has `minItems == maxItems`, so it
    shows **no buttons and is byte-identical** — that gate is the whole
    compatibility argument. `death_spawn.spawns` (`minItems: 1`, no `maxItems`)
    is the first genuinely resizable array: a per-era spawn table for a type that
    ships with one row. **Add COPIES THE LAST ROW** (the doc validated on load, so
    a copy is schema-valid by construction — no default-instance synthesis, no
    guessing at `pattern`/`minLength`); **remove pops the LAST row**, never a
    middle one, because these arrays are era-INDEXED and removing `[1]` would
    silently renumber every era after it. Both stage into `self._doc` like any
    other edit and re-dirty on the ARRAY path — `_refresh_dirty` compares whole
    subtrees, so add-then-remove cleans itself back up, and `_dots.get()` is
    None-safe for a path with no dot widget. Then the form REBUILDS, which is why
    `_rebuild_form` re-shows the dots of everything still in `self._dirty`: fresh
    widgets start with the dot hidden, and a rebuild that is not a domain switch
    would otherwise drop the pending marks of every other staged edit. The buttons
    carry `objectName` `rowadd:<path>` / `rowremove:<path>` so a test can assert
    WHICH arrays are resizable.
  - **Arrays of SCALARS can get the same `+ Row`/`− Row` gate
    (feature-enemy-intro-dialogue, generalizing ER-5) — but only when their
    OWN schema property opts in with `"x-array-editable": true`.**
    `core.json`'s `EnemyIntro.entries[i].hidden_frames` (`minItems: 0`, no
    `maxItems`, carrying the marker) is the first: a designer-resizable
    per-entry list of frame-column indices, shipping empty. Same
    `can_add`/`can_remove` gate as the object-array case, same "remove pops
    the last row" rule; the one real difference is **Add on an EMPTY array**,
    which has no last row to copy — `_default_scalar_value(item_schema)`
    synthesizes a schema-valid starting value instead (an enum's first value,
    `False` for boolean, `""` for string, else the item schema's own
    `minimum`, defaulting to `0`). **The marker is required, not just
    `minItems != maxItems`, because `BuildingsGlobal.random_names`
    (`buildings.schema.json`) already had that exact shape (`minItems: 1`, no
    `maxItems`) and must NOT sprout buttons here — it grows only through the
    game's own 9H add-name menu.** A live regression caught by
    `test_editor_panels.py::TestBalancingPanel::
    test_buildings_form_has_no_row_buttons_at_all` is what forced the opt-in
    marker instead of a blanket `minItems != maxItems` gate. Every other
    scalar array (`Camera.zoom_levels`, `LightningStrike.{damage,radius,
    cooldown}`, every `[$defs/…]`-typed 3/4/5-slot tuple) has `minItems ==
    maxItems` anyway and would show no buttons regardless. Deliberately NOT
    extended to arrays of OBJECTS gaining a schema-derived default — an
    object has no single sensible one (`required`/`pattern`/cross-field
    constraints), which is exactly why the object-array Add still copies a
    row instead.
    Since ES-2 the enemies domain's `eras` arrays (`EnemyScaling/eras` and every
    `EnemyTypes/<Type>/eras`) are the second family of genuinely resizable
    arrays, and they got those buttons with **zero editor edits** — the schema
    said `minItems: 1`, no `maxItems`, and the gate above did the rest.
  - **The greyed previous-era reference (ES-5, EnemyScalingReworkPLAN D9)**: a
    leaf whose path sits inside an `eras/<i>/…` subtree with `i > 0` gets a
    THIRD widget in its row, after the pending dot — a disabled, mid-grey
    `QLabel` (`prev ⌐ 185`) showing what that field resolves to on the LAST
    round of the PREVIOUS era. Era 0 shows nothing (there is nothing to
    reference). Rules that matter:
    - **Detection is PURELY PATH-SHAPE based** — `_era_context` scans the
      leaf's path for the literal segment `eras` followed by an integer index
      (`BalancingPanel.ERA_ARRAY_KEY`), and nothing else. No domain, type or
      field name is hardcoded anywhere in it, so a future type that grows era
      rows (BossReworkPLAN's Commander) inherits the label with no edit here.
      The era LENGTH is found the same way: `_rounds_per_era` picks the one
      top-level block carrying a `rounds_per_era` key (never "EnemyScaling" by
      name), falling back to 10.
    - **The math is `engine.era_math.prev_era_reference`, never a local
      formula.** The panel importing `engine/` is fine (editor consumes engine,
      D7); re-deriving `stats + (rounds_per_era − 1) × per_round` here would be
      the exact drift that module exists to prevent. `start_round` and
      `endgame_scaling` are read off the era array's PARENT object, again by
      key shape.
    - **Values come from the STAGED `self._doc`**, and `_refresh_dirty`
      re-computes EVERY label on every edit — so retuning era 0's
      `per_round.hp` updates era 1's reference before anything is saved.
      A form rebuild (row add/remove, domain switch) regenerates them for free;
      `self._refs` is cleared alongside `self._widgets`/`self._dots`.
    - Anything the era math cannot read (a missing key, a non-numeric leaf, a
      doc shape that raises) degrades to **no label**, never an exception —
      this runs inside a Qt slot, where an unhandled exception can abort the
      process. The label carries `objectName` `prevref:<path>` (same convention
      as the row buttons) so a test can assert which fields have one; its grey
      is a deliberately theme-independent panel-local colour, like the dirty
      dot.
  Scalar leaves:
  integer → `QSpinBox`, number → `QDoubleSpinBox` (4 decimals; ranges from schema
  `minimum`/`maximum` — invalid input unrepresentable, ED-30), `enum` → `QComboBox`
  (typed `itemData`), boolean → `QCheckBox`, string → `QLineEdit` (commit on
  `editingFinished`; text shorter than `minLength` restored, not written). Local
  `#/$defs/` refs resolved by `_deref` (the only `$ref` kind allowed);
  a key present in the schema but absent from the doc is skipped (no such key
  exists in `buildings.schema.json` today — every level's `required` list is
  currently exhaustive — but the walk stays generic for the next domain that
  needs one).
  Widgets register in `self._widgets` keyed by `/`-joined paths
  (`"DefenceBuildings/BasicDefence/tiers/0/base_dmg"`); numeric/enum widgets are
  `_NoWheelSpinBox`/`_NoWheelDoubleSpinBox`/`_NoWheelComboBox` (ignore
  `wheelEvent` so scrolling the panel can never nudge a value by accident — the
  event propagates to the enclosing `QScrollArea` instead).
  **This is an editor-wide convention, not a balancing-only one**: EVERY value
  widget anywhere in the editor — spinboxes/combos in every panel (details,
  viewport's floating animation/state combos, palette's deco-type combo,
  map-details' New Map dims, the launcher's plan picker), not just this form —
  imports `_NoWheelSpinBox`/`_NoWheelDoubleSpinBox`/`_NoWheelComboBox` FROM
  `balancing.py` (their one home) rather than a bare `QSpinBox`/`QComboBox`.
  The mousewheel is navigation-only (scroll the panel/list) everywhere in the
  editor; it never edits a value.
  **Edits are staged, not written immediately**: `_commit(path, value)` walks the
  doc (numeric segment → list index) and mutates `self._doc` in memory only,
  then toggles a small pending-change dot (`self._dots`) next to that field by
  comparing against `self._baseline` (a deep copy taken at `set_domain`/last-save
  time) — signals connected *after* initial values are set, so form population
  never dirties anything. The toolbar's **"Save Balancing Changes"** button
  (enabled only while `self._dirty` is non-empty) is the ONE place that calls
  `engine.data_io.write_validated` (ED-31) — it prompts for a required session
  name + optional description (`_SaveMetaDialog`), then also appends a full-doc
  snapshot to that domain's history via `editor.balancing_history.save_session`
  (`data/balancing_history/<domain>.json`, a per-domain flat newest-first JSON
  array — one file per domain because domains edit independently, unlike
  the old prototype's single combined snapshot). **"Version History"** opens
  `_HistoryDialog`, listing that domain's sessions newest-first; "Load into
  Editor" replays a past snapshot into the live widgets via
  `_apply_snapshot`/`_set_widget_value` (staged only — dirty dots reappear for
  whatever differs from the current baseline, nothing is written until the user
  clicks Save again); "Delete" removes an entry via
  `balancing_history.delete_session`. Undo (ED-24) deferred for balancing.
- **Paired weight/override checkbox (`x-toggle`/`x-paired`)**: a schema-driven
  rendering rule, not a hardcoded path — `map.schema.json`'s
  `Pathfinding.content_weights.*`/`TileConditions.path_weights.*` are the first
  (only) users. A numeric leaf's schema carries `"x-toggle": "<sibling key>"`
  (both are house-style custom JSON Schema keywords: unknown keywords are just
  ignored data to a validator, so `additionalProperties`/`required`/bounds
  validation is unaffected) and `_add_leaf_row` builds a QCheckBox — via the
  exact same construction `_make_widget`'s boolean branch uses — and
  `row_layout.insertWidget(0, checkbox)`s it left of the numeric widget, inside
  the SAME row `QWidget`. **Sibling resolution rule**: the toggle bool is a
  sibling of the LEAF'S PARENT OBJECT, at the same leaf key —
  `Pathfinding/content_weights/defence_building`'s toggle lives at
  `Pathfinding/content_weight_overwrites/defence_building`
  (`path[:-2] + (toggle_key, path[-1])`). `_schema_node_at` resolves the
  sibling's own schema node (for its tooltip `description`) by walking the
  FULL schema from the root — it does not reuse the current recursion's schema
  branch, since the sibling can live anywhere else in the tree. The checkbox
  commits straight to the sibling's own path via the same `_commit` every
  widget uses, so dirty tracking/`save_changes` need no special case, and it
  registers in `self._widgets` under the SIBLING path (not the weight's own
  path) — same lookup convention as every other widget. Missing sibling
  object/key (a domain whose doc doesn't carry the toggle object) degrades to
  a plain row, never raises. The toggle OBJECT itself (e.g.
  `content_weight_overwrites`) carries `"x-paired": true` so `_build_object`
  skips it entirely — it never renders as its own `CollapsibleSection`, only
  inline via its partners' rows.
- **`domains.py`** (in `editor/`, not `panels/`, but governs the form):
  `domains(data_dir)`, `category_keys`/`is_domain_category`,
  `balancing_path`/`schema_path` — read-only derivation helpers.
  - **The domain list is DERIVED, never hardcoded** (AD-6; the `DOMAINS` constant
    is GONE): `domains(data_dir)` = slots.json's category order ∩ the categories
    carrying a `data/balancing/<key>.json` (D-10 order preserved). A new balancing
    domain therefore appears in selector + balancing form with **zero editor
    edits** — that is the whole point; do not re-introduce a list. It is a
    **function, not a module constant**, because every editor module is
    `data_dir`-injectable (tests run against a temp copy of `data/`) and a
    constant derived at import from the repo's `data/` would be silently wrong for
    any other tree.
  - **`is_domain_category(key)` (schema exists) is a DIFFERENT question from
    "is in `domains()`" (balancing file exists)** — keep them apart. A category
    *intended* as a domain (it has a `data/schemas/<key>.schema.json`) whose
    balancing file is missing is omitted from the tree **whole**, not degraded to
    an asset-only node: every leaf under a domain emits `domain_selected`, which
    would drive `BalancingPanel.set_domain` into a missing file. That rule is what
    keeps "no balancing file, no domain node" expressible now that the domain list
    is derived from those very files.

## Phase 5 — merged tree / details / entity preview
- **Merged tree** (`panels/selector.py`): top-level nodes = registry categories in
  `data/slots.json` order (the ones with a balancing file double as balancing
  domains — DERIVED, see `domains.py` above; vfx and `backgrounds` (10K menu art)
  are asset-only; `deco` (Phase 6 follow-up) and `conditions` (tile-condition
  art) are asset-only and nested as CHILDREN of the "map" node —
  `_NESTED_UNDER_MAP` in `selector.py`, a TREE-SHAPE choice only:
  `category_key` stays `"deco"`/`"conditions"` everywhere else, so each keeps
  its own 64×96 frame size). Children come from registry groups; the tree STOPS at the deepest
  group whose children are all leaf groups (a building TYPE like "Defender") —
  tiers/levels never appear in the tree. Signals: `node_selected(category,
  group_path)` on every selection, plus `domain_selected(str)` at ANY depth of a
  domain category, so balancing follows while browsing types. ● markers (ED-11)
  from `refresh_markers()` (pure `load_manifest`; clean label in UserRole+1). A
  domain category with no balancing file is omitted whole. The derived domain list
  is cached as `self._domains` (`_emit_selection` consults it on every click) and
  re-derived in `reload_registry()`.
- **"Add new X…" context menu** (AD-6, `add_requested = Signal(str)` → the form
  spec's `id`): right-clicking a **category ROOT** (payload `path == ()`) pops one
  entry per form spec whose `selector_context` is that category key; right-clicking
  **empty space** offers the single **Add New Category…** entry (`add-category` —
  that spec deliberately carries NO `selector_context`, since it *creates* a
  category and so belongs to no node). Group nodes, the Maps branch and map leaves
  offer **no menu**, and a category with no matching spec shows nothing rather than
  an empty popup. `editor/main.py::_on_add_requested` opens the `AgentFormDialog`
  for that spec — so **adding a form is still just adding a JSON file**; the
  selector hardcodes no form list.
  - Conventions worth keeping: the DEFAULT context-menu policy +
    `contextMenuEvent` (not `CustomContextMenu`); construction (`_context_menu`,
    returns `QMenu | None`) is split from display so tests never `exec()` a modal
    popup (`QAction.trigger()` is the test path); specs load FRESH per menu open
    (same rule as the launcher — a spec an agent just wrote needs no restart); and
    a spec-load failure degrades to **no menu** plus one stderr line, because an
    unhandled exception raised inside a Qt event handler can abort the process — a
    right-click must never be able to kill the editor.
- **Composite selection** (user-confirmed): tree node × Details subcategory
  dropdown (tier — or the concrete slot for flat groups) × LevelBar index resolve
  to ONE slot key via the PURE `editor/selection.py` (`subcategories` /
  `level_slots` / `resolve_slot`; no Qt — test headlessly). `MainWindow` owns the
  composite state and drives `viewport.set_preview_slot` + `details.set_slot`.
  Balancing keeps its last domain while vfx/deco nodes are selected. The level bar
  only resolves the ASSET slot — per-level balancing values stay Phase 9.
- **"+ Variant" / "+ Type" buttons** (sprite variants): the LevelBar carries a
  trailing `+ Variant` + `+ Type` button. WHICH selections offer them is a product
  call in the shell — `MainWindow._VARIANT_TARGETS` (`{"enemies": None, "deco":
  None, "map": {"Background"}, "ui": None, "conditions": None}`; `None` = any
  leaf subcategory) filtered through
  `_variant_target()`; `selection.variant_target` is the game-name-free structural
  half. The `map` entry is a real constraint: `Buildable`/`Combat`/`Spawning` are
  leaf subgroups too, and a `tile_buildable_v2` would silently break the
  checkerboard `_b` pairing. `set_levels(..., can_add=…, can_add_type=…)` forces
  the bar visible even for one level.
  - **enemies / deco** → `registry_ops.add_variant` appends an interchangeable
    `<stem>_v<k>` slot (`next_variant_key`; a bare slot counts as v1 so the first
    add is `_v2`).
  - **map → Background** → `registry_ops.add_background_slot`: a background needs
    its OWN legend code, so "another variant" IS another numbered
    `tile_background_<n>` type. `_bind_background_code` claims that code in the open
    map (undoable). No map open → registry-only (paintable once some map's `+ Level`
    claims a code).
  - **`+ Type` (deco, and ui → Buttons)** → for deco, `registry_ops.add_deco_prop`
    appends a whole leaf CHILD group (`Prop <n>` holding `deco_prop_<n>`) under
    `Props` — same handler as the palette's `+ Add Prop`. For ui → Buttons,
    `MainWindow._on_add_type` dispatches instead to `_on_add_button_type` →
    `registry_ops.add_button_family`, which appends a new leaf child group
    (`{label, slots: [ui_button_<slug>]}`, a naming-dialog-derived slug via
    `registry_ops.button_family_slot`) under Buttons — a brand-new button FAMILY,
    the ui-category analogue of a deco prop type. `_BUTTON_TYPE_NODE = ("ui",
    ("Buttons",))` gates both `can_add_type` and the dispatch. Only leaf-group
    families ("+ Type") get the new-KIND affordance; making a widget of a new
    *behavior* kind stays a dispatched game-code task.
  - All are pure `write_validated` calls in `editor/registry_ops.py` (`TestPurity`).
    After the write MainWindow reloads every cached registry
    (`selector`/`details`/`viewport`/`palette`/`screen_details` `.reload_registry()`)
    and `select_last()`s the new slot. `screen_details.reload_registry()` is what
    makes a fresh ui slot (a new button family, or any existing "+ Variant")
    appear in every skin dropdown (`skin_combo`/`button_skin_combo`/
    `panel_skin_combo`) **without restarting the editor** — before this wire it
    was the one reload `MainWindow._reload_registries` skipped. No game change
    needed otherwise: `enemy.py:variant_slot` already rolls a random variant per
    spawn across an era's slots, and a deco placement stores its CONCRETE slot in
    the map file.
- **DetailsPanel** (`panels/details.py`, right pane): prototype-importer parity
  (ED-40/41). A *file* import copies the PNG to `data/sprites/imported/<slot>.png`
  AT IMPORT TIME; Save writes the manifest entry through `write_validated`; Clear
  (confirm dialog in UI; `clear_entry(confirm=False)` for tests) removes the entry
  + any PNG it leaves unreferenced. Row 0's animation combo is locked to `["idle"]`
  — the E-35 rule is UNREPRESENTABLE in the UI, not a save-time error. Frame sizes +
  animation vocabularies come from the registry per slot. No pygame here; Pillow
  reads sheet dimensions.
  - **Nine-slice margins (10L-A)**: 4 spinboxes (L/T/R/B), **ui category only**
    (gated on `self._context[0]`, `_slice_applies`), bounded by the slot's frame
    size (`registry.frame_size`, L/R capped at `frame_w`, T/B at `frame_h`),
    writing the optional manifest `slice` field. **All-zero ⇒ the key is
    omitted** — a slot with no nine-slice keeps a byte-identical entry, and
    zeroing the four spins and re-saving un-slices a previously-sliced slot
    (`save()` replaces the whole entry). Nine-slice is drawn on the HUD path
    only — the entity preview (`RenderItem`) deliberately ignores it; a
    `slice`-carrying draft still parses and previews as a plain scaled sprite.
  - **Condition tint checkbox (`conditions` category only)**: "Show condition
    tint under this art", gated by `_tint_applies()` (the exact `_slice_applies`
    mirror, `self._context[0] == "conditions"`), writing the optional manifest
    `tint_overlay`. The game's flat colour diamond per non-grass tile is a
    FALLBACK for a condition with no art, so **a slot with no art forces the box
    checked and disabled** — there is no entry to write it to. The enable gate
    is `bool(self._row_editors)` (the LIVE rows), NOT the on-disk entry, so a
    freshly imported sheet is editable before its first Save; a fresh import
    with no prior entry defaults OFF (the sprite replaces the tint).
    `_refresh_tint_state(entry)` is the ONE place that state is computed —
    called from `set_slot`, `import_sheet`, `use_sheet` and `clear_entry`.
    **Unchecked omits the key**, so an untinted entry is byte-identical and
    unticking + re-saving removes it (same convention as `slice`).
  - **`ui` variants = skins**: the `ui` category's leaves offer "+ Variant"
    (`MainWindow._VARIANT_TARGETS`, added in A3) → `ui_button_v2`, …, i.e. one
    slot per button skin; its 4-row vocab is `idle/hover/pressed/disabled` (row
    0 locked to idle as everywhere).
  - **A slot's sheet is NOT `imported/<slot>.png`.** "Use Spritesheet…"
    (`panels/sheet_picker.py`) LINKS a slot to art already imported: the entry's
    `sheet` points at another slot's PNG and no bytes are copied, so one file backs
    many slots. The engine already resolved `sprites_dir / entry.sheet` verbatim
    (`engine/assets/store.py`) and the schema pattern always allowed it — the only
    thing that ever assumed otherwise was this panel. Read `self._sheet_ref` (from
    the entry); `imported/<slot>.png` is only the fresh-import destination and the
    no-entry fallback. **Clear refcounts before unlinking**
    (`asset_import.sheet_users` / `unreferenced_sheets`) — deleting a shared PNG
    blanks every other slot using it. Sheet-sharing rules live in `data/CLAUDE.md`.
  - **Static rows are DERIVED, never stored.** A row's "Static — don't animate"
    checkbox is a view of the manifest's existing `hidden` array (hide every column
    but one): `playback_order` drops hidden frames AFTER loop expansion, so a
    one-visible-frame row is already a still sprite. No schema key, no editor-only
    state, and a static row built by hand with the old checkboxes re-opens as
    static. `RowEditor.effective_hidden()` is the ONE place the array is computed —
    `to_dict` and the preview both call it, so they cannot disagree. A 1-frame row
    is deliberately not auto-static (nothing to disable). The loop spins grey out
    when static but keep their values: a loop over one visible frame is meaningless,
    not harmful, and rewriting a designer's numbers behind their back is worse.
  - **`panels/sheet_preview.py` draws a raw PNG, and that does NOT break ED-22.**
    The one-render-path rule bans a second Qt-side renderer of GAME CONTENT — the
    animated preview stays in the viewport, through `engine/render`. SheetPreview
    inspects the importer's own input file (no slot, no animation, no time
    resolved), like a thumbnail in a file dialog. `viewport.slot_qimage` can't serve
    here: it only ever yields the resolved idle frame, not an arbitrary frame or the
    sheet. Clicking a cell routes through that row's own `RowEditor`
    (`set_static_frame` / `toggle_hidden`), never a parallel state store, which is
    what keeps the checkboxes and the picture in sync. Each cell is captioned with
    its COLUMN index (white on a dark plate — it lands on arbitrary art, so a plain
    colour would be invisible against some sheet), the same number the hide
    checkboxes, the static radios and the manifest's `hidden`/`loop_start`/
    `loop_end` speak. `labels_visible()` drops them below `LABEL_MIN_CELL` px,
    where the plate would cover the frame it labels.
  - **Per-slot frame size (ER-5) is a TWO-FILE write, and that is not optional.**
    Frame size is a CATEGORY property; ER-1 added an optional per-slot override in
    `data/slots.json` (`{key, frame_w, frame_h}` beside the bare-string form), and
    the `Frame W/H` spinboxes are the only way to author it — `registry_ops
    .set_slot_frame_size` (pure, `write_validated`, `TestPurity`). Writing the
    CATEGORY's own size back removes the override (bare string again): that is how
    "reset to default" is expressed, and it keeps slots.json free of overrides that
    override nothing. **But `AssetStore.frame_size` resolves manifest entry >
    registry**, so a slot that already has an entry carries its own
    `frame_w`/`frame_h` and would keep rendering at the OLD size no matter what
    slots.json says. So the handler writes the override, reloads every cached
    registry (`registry_changed` → `MainWindow._reload_registries`, same path the
    `+ Variant` writes use), **re-cuts the sheet at the new size and re-saves the
    entry**. Leaving the two files disagreeing on disk is the failure mode the
    method exists to prevent. It commits on `editingFinished` (not `valueChanged`
    — typing "128" would otherwise write three times) and works with **no sheet
    imported**, which is the point: declaring the frame size BEFORE the import is
    what the importer slices and pads against.
  - **Clear's confirm dialog only fires because the connect is wrapped**
    (`clicked.connect(lambda: self.clear_entry())`). It was connected directly for
    months, so `clicked(bool checked=False)` landed in the `confirm=True` kwarg and
    Clear deleted the entry + PNG with NO dialog — the exact footgun recorded below
    for map_details' Delete, live in a second panel. Pinned by
    `TestClearAsksFirst`.
- **One render path (ED-22)**: the ONLY animated preview is the viewport. Every
  Details edit emits `draft_changed(slot, entry_dict)` → `viewport.set_preview_draft`
  overrides that slot in an in-memory manifest (never disk) + rebuilds
  AssetStore/Renderer. `entry_saved`/`entry_cleared` → `viewport.reload_assets()`
  (re-read manifest, drop draft — ED-42, no restart) + `selector.refresh_markers()`.
  Camera state lives in `_coords` and survives reloads.
- **Entity preview (ED-21)**: the slot renders at the map centre on the `entities`
  layer over the grid; the camera is parked on that centre tile via
  `CoordinateSystem.center_on` (`clamp` alone would anchor, not centre, when the
  grid overflows the viewport); the animation dropdown is a floating QComboBox
  pinned top-left, visible only when the effective entry has animations; the anim
  clock is wall-clock and resets on slot/animation/draft change. No asset → grey X
  (E-37). New modules go in `test_editor_viewport.TestPurity`'s import list
  (`details`, `level_bar`, `selection` are in). Measured ~57 fps.
- **Anchor handles (ESV-2)**: hangs off the entity preview, not a new mode —
  handles are visible exactly when `preview_slot` is set and absent by
  construction in map/screen mode (those branches never call the submitter).
  Three pieces: **`editor/anchor_ops.py`** (pure — `screen_point`/`frame_px`
  frame-px↔screen-delta conversions plus `set_anchor`/`clear_anchor`,
  `write_validated` through `asset_import.load_manifest_doc`/
  `write_manifest_doc`, modelled on `registry_ops.py`, `TestPurity`);
  **`editor/panels/anchors_panel.py`** (`AnchorsPanel`, Qt — one row per
  `engine.assets.manifest.ANCHOR_NAMES` name, NEVER a literal name list, so a
  seventh declared name needs zero editor edits; owns the SOLE authoritative
  `{name: (x, y)}` mapping, seeded fresh from disk on every `set_slot`/
  `reload()`); **`viewport.py`** (submit + hit-test + drag — a VIEW of the
  panel's mapping via `set_anchors`/`set_selected_anchor`, never reading or
  writing the manifest itself).
  - **Handle geometry is ED-22 clean**: a fixed-SCREEN-size closed outline +
    crosshair through `Renderer.submit_overlay_lines` (WORLD points, so the
    two-sample `screen_to_world` trick cancels zoom/pan — `game/anchors.py`'s
    proven pattern, ESV-2 brief §2.3c), plus an optional name label via
    `submit_hud(HudText(...))`. Never QPainter.
  - **Handle origin COMPOSES `offset_x`/`offset_y`** (reverses ESV-2 brief
    §1.4 — see `docs/briefs/fix-anchor-offset-and-bullet-sprites.md` Fix 1):
    `_anchor_draw_params` folds the entry's offset into the anchor origin so
    the handle sits on the art exactly like the renderer draws it.
    **fix-anchor-origin-parity**: `_anchor_draw_params` now computes that
    origin by calling `engine.render.sprite_anchor_screen` directly (never a
    hand-rolled `world_to_screen` + offset expression) — the SAME shared
    helper `game/anchors.py`'s `anchor_world_point` calls for the game side,
    so the editor's handle and the game's resolved anchor point cannot drift
    apart again (the bug this fix shipped for: they used to resolve from two
    different bases, `screen_offset`/`world_offset`'s ESV-1 delta model,
    since deleted). `editor/anchor_ops.py`'s `screen_point`/`frame_px` are
    untouched — they are pure algebra over a caller-supplied origin and exact
    inverses of each other, so shifting the origin fixes the draw AND the
    drag in one move. **RESOLVED (fix-editor-preview-footprint)**: the
    preview used to always resolve at `fit_tiles=0.0`/`scale=1.0` (the
    RenderItem's dataclass defaults) regardless of what the entity actually
    was, while a real game entity draws at its own footprint fit
    (`fit_tiles=EnemyTypes.<Type>.footprint`,
    `scale=EnemyTypes.<Type>.sprite_scale`, `game/enemies/enemy.py`) — the
    one slot in `data/` where those disagreed, `formation_stage_1`
    (`frame_w: 128`, 1-tile footprint -> game `s = 0.5` vs editor `s = 1.0`),
    resolved its anchor at HALF its intended distance in game, and drew at
    twice its real in-game size (an ED-22 WYSIWYG violation independent of
    anchors). Fixed by a new pure resolver, `editor/sprite_fit.py`'s
    `slot_draw_fit(data_dir, category_key, slot_key)`: it degrades to
    `(0.0, 1.0)` for every non-enemy category and for anything unresolvable
    (E-37), and for `enemies` resolves the slot -> its top-level
    `data/slots.json` "enemies" group label -> the `EnemyTypes` entry whose
    NEW required `registry_group` string (`data/balancing/enemies.json` +
    `enemies.schema.json`) matches that label -> `(footprint, sprite_scale)`.
    `registry_group` exists because the editor may never import `game/`
    (D5) and the link was otherwise expressible only in
    `game/enemies/enemy.py`'s `REGISTRY_GROUP` Python class constants, two
    of which do NOT match their `EnemyTypes` key by string
    (`Standard`->`"Walker"`, `SiegeCannon`->`"Siege Cannon"`) — matching by
    convention instead of this field would have violated "schemas over
    convention". A NEW `ViewportPanel._preview_draw_fit()` is the ONE call
    both the entity-preview `RenderItem` submission and
    `_anchor_draw_params` read their `fit_tiles`/`scale` from, so the
    preview's drawn size and the handle's resolved scale cannot drift
    apart again — the same one-shared-formula argument
    fix-anchor-origin-parity made for the handle's ORIGIN, now made for its
    SCALE. `game/enemies/enemy.py`'s `REGISTRY_GROUP` constants remain a
    SECOND home for the same link (deliberately not refactored to read
    `data/` in this fix) — `tools/tests/test_enemies.py`'s
    `TestRegistryGroupDrift` pins the two together so a future drift turns
    red instead of silently breaking the editor preview.
    - **PER-ERA fits (BR-5)**: `slot_draw_fit` read `footprint`/
      `sprite_scale` FLAT off the `EnemyTypes` block, but BossRework BR-1
      moved the Boss's pair into its per-era `stats[]` rows — so for the Boss
      it raised `KeyError`, the surrounding **bare `except Exception`**
      swallowed it, and every `boss_era_*` preview silently drew at
      `(0.0, 1.0)` for four phases. Two changes: `_type_fit` resolves either
      shape (`stats[]` when present, clamped), with the era index coming from
      `_era_index` — the slot's POSITION among its top group's child groups
      ("Era 0" is child 0), the same index alignment `slots.json` and
      `stats[]` already share; and the E-37 net now wraps **the two data
      LOADS only**, with the resolution below written to be total (explicit
      membership tests, no indexing that can raise) so the next such
      regression is loud instead of silent. It still does NOT import
      `game/enemies/enemy.py`'s `Enemy.resolve_fit` seam — `editor/` may
      never import `game/` (D5), the whole reason `registry_group` is data.
      Pinned by `tools/tests/test_editor_preview_footprint.py`'s
      `TestBossPreviewFitIsPerEra` against a WRITTEN per-era fixture.
  - **Drag**: LEFT-press hit-tests handles first (`HANDLE_HIT_PX = 10`,
    reverse submission order, the `_hit_widget` rule) and suppresses the pan
    on a hit; RIGHT never grabs a handle. Move recomputes frame-px live
    (`anchor_dragged`, spinboxes follow with signals blocked — nothing
    written); release commits ONE write (`anchor_drag_finished`) only when
    the value actually moved — a click alone only selects. No undo: the
    panel writes immediately, like `details.py`'s Save/Clear.
  - **`DetailsPanel.draft_entry()` preserves an existing entry's `anchors`
    value verbatim** — that panel never authors anchors, so a Save/Clear
    there must not erase what `AnchorsPanel` wrote; `MainWindow.
    _on_manifest_changed` re-seeds `AnchorsPanel` via `reload()` so panel and
    handle stay in step with any manifest write, not only its own.

## Phase 6 — tilemap mode (`panels/palette.py`, `panels/map_details.py`; ED-10/20/23/24)
- **Selection**: the Maps branch is the FIRST child of the "map" category node; one
  leaf per `data/maps/*.json` (pointer excluded), ● prefix = ACTIVE map. A map leaf
  emits `map_selected(map_id)` + `domain_selected("map")` and NEVER `node_selected`.
  MainWindow: map node → tilemap mode (palette shown, right stack →
  MapDetailsPanel); any other node → `_leave_map_mode()` (entity preview as Phase 5).
- **`editor/map_session.py`** owns the open doc (ONE map at a time, D-22) and THE
  global `QUndoStack` (ED-24). Phase-6 undo scope: paint strokes (ONE command per
  stroke — press→release coalesced, incl. line/rect/bucket), base move, deco
  place/remove, display-name edit. Ctrl+Z / Ctrl+Y are window-level QActions. Dirty
  = `not undo_stack.isClean()`; save → `setClean()`. Opening a DIFFERENT map while
  dirty goes through `MainWindow._resolve_dirty()` (`dirty_policy`:
  "ask"|"save"|"discard"). Browsing away to an entity node keeps the dirty doc in
  memory.
- **Painting is pure-model first**: `editor/tilemap_ops.py` (no Qt) mutates the doc
  in place and returns `[(col,row,old,new), ...]` change lists; `line_cells`/
  `rect_cells` exported separately for ghosts. The viewport only translates mouse
  events: ALL cell picking is `screen_to_world` → floor (E-3). Strokes
  Bresenham-interpolate between move events so fast drags don't gap.
- **Viewport map mode** (`set_map_mode(session)`): coords rebuilt with the map's
  dims; camera opens (and re-frames on window resize, `_resize_surface`) centred
  on the map's own `camera_start` via `_center_on_camera_start` — the same view
  `game/main.py:frame_camera()` opens on at boot — falling back to `clamp` (which
  centres if the map fits the viewport, else anchors) when no startpoint has been
  painted yet. LEFT = armed tool, RIGHT = pan (entity preview keeps either-button pan).
  Under the "none" tool a LEFT-drag that didn't grab the base pans too (inspect
  mode — `_drag_pos` set after `_tool_press` when `_tool == "none" and not
  _base_drag`). `_drag_pos` set ⇒ pan; a live brush stroke leaves it None. Ghosts
  are tinted engine sprites on the `overlay` layer; zone tints are per-code
  multipliers (ZONE_TINTS); grid lines go through `Renderer.submit_overlay_lines`
  (E-24) — QPainter never draws tiles. A press on the base's cell starts a base
  drag regardless of tool; hide the base eye to paint under it. `cursor_world` feeds
  the status-bar readout.
- **Palette** (`panels/palette.py`): brush icons are STATIC engine-resolved frames
  via the injected `viewport.slot_qimage` provider (not a second render path). Tile
  buttons rebuild from the open map's legend (`set_legend`), zone kinds first; deco
  slots from the registry. Picker → `viewport.code_picked` → `palette.arm_code`.
  **Decoration mode is two-level**: a `Type:` `QComboBox` lists the `Props` group's
  child labels; the brushes below are ONLY that type's variants (`Var 1`, `Var 2`,
  … — one brush per variant, so a specific variant lands in the map file). `+
  Variant` extends the shown type, `+ Add Prop` adds a new type. Because only the
  shown type has buttons, **`arm_deco(slot)` switches the combo to that slot's own
  type first**. Follow-up: a "Base" section (registry `core` category, always
  `base_hole`) sits in the SAME exclusive brush group — arming it (`arm_base`) is
  import-target-only (`_armed_slot()` priority: deco, then base, then armed code's
  slot) since the base is never painted, only dragged.
  **Mirror Flip** (a "Mirror Flip" `QCheckBox`, `self._deco_flip_box`, on the
  Decoration page below `+ Add Prop`): an ORTHOGONAL placement modifier, not
  tied to which prop/variant is armed — arming a new deco type/slot does NOT
  reset it. State lives in `ViewportPanel._deco_flip_armed`
  (`set_deco_flip(on)`, wired from `palette.deco_flip_toggled`); `_tool_press`'s
  deco-place branch passes it to `MapSession.push_deco_place(..., flip=...)`,
  which threads through `tilemap_ops.place_deco` into the map file's per-entry
  `"flip"` bool (optional, omitted when False — `data/CLAUDE.md`'s
  optional-key convention). The ghost preview passes the same flag into its
  `RenderItem(..., flip=...)` so the cursor preview mirrors before placement.
  Rendering is plumbing already in `engine/render` (`RenderItem.flip` →
  `DrawCall.flip` → `pygame.transform.flip`); the deco layer just threads
  `d.get("flip", False)` through in both `engine/tilemap.py` emitters. Has its
  own editable keybind (`editor/keybinds.py`'s `"deco_flip"`, default `X`),
  settings-dialog row, and `MainWindow.deco_flip_action` (triggers
  `palette.toggle_deco_flip()`) — same pattern as the tool/brush keybinds.
- **Lifecycle** (`panels/map_details.py`): New/Duplicate (schema-bounded dialog, id
  re-checked) / Save / Set Active / Delete — Set Active is the ONLY writer of
  `data/maps/active_map.json` (D-21). Create/duplicate write to disk immediately
  (all-forest fill for new maps). **Delete map** (`MapSession.delete`,
  `engine.tilemap.delete_map`) is confirm-dialog gated (mirrors
  `details.py:clear_entry` / `balancing.py:_HistoryDialog._delete_selected`) and
  refuses the ACTIVE map (button disabled + tooltip; would leave the D-21
  pointer dangling) — deleting always targets the currently-open doc, which
  `_on_delete` releases from the session (`doc = None`, undo stack cleared)
  before the file unlink, then emits `map_deleted` so MainWindow leaves map
  mode and the selector's Maps branch refreshes. **Do not connect a
  `clicked`-driven confirm method directly** — `QPushButton.clicked` emits
  `clicked(bool checked)`, which silently overrides a `confirm=True` kwarg
  default to `False` on connect; wrap in a lambda (`clicked.connect(lambda:
  self._on_delete())`) so a real click always shows the dialog.
- **Starting Area (2×2 marker)**: a third single-object brush in gametiles mode
  (registry `core`/`Start Area`, slot `start_area`) mirroring the Hole/Camera
  Start pattern end-to-end — `palette.arm_start_area`/`start_area_armed` →
  `viewport.arm_start_area`; paint = place/move (the clicked cell is the 2×2's
  MIN corner, `MapSession.push_start_area_place` clamps it to
  `[0, cols−2]×[0, rows−2]`), erase = remove; a press on ANY of its 4 covered
  cells (eye on, no single-object brush armed) starts a drag whose release cell
  becomes the new min corner. **It renders as a closed 2×2 OUTLINE through
  `submit_overlay_lines` (E-24), never a sprite** — the engine emitters
  deliberately don't emit it, and the ghost is the same outline at the clamped
  hover cell (`_submit_start_area_outline`); ED-22-clean, same primitive as
  grid lines. Own `start_area` layer eye. `map_requirement_warnings` adds two
  warnings: `"starting area"` when the marker is missing and `"buildable tiles
  under starting area"` when any covered cell isn't a `tile_buildable`-slot
  code (the marker anchors the game's unlock grid but never forces tile
  states — painted terrain wins).
- **Camera Limit Center (a single-tile brush)**: the Camera Start brush's
  TWIN, sitting immediately after it in `_gametiles_brush_order()` — the same
  gametiles page, the same exclusive `_brush_group`, the same
  `palette.arm_camera_limit_center`/`camera_limit_center_armed` →
  `viewport.arm_camera_limit_center` wiring, the same paint = place/move,
  erase = remove, press-on-the-marker = drag semantics (single tile, NO clamp
  — the tutorial-marker shape, not Start Area's 2×2). It marks the CENTRE of
  the camera's play area: `core` balancing's `Camera.max_offset_tiles_x/_y`
  travel limit is measured from it and the camera never starts on it, which is
  why it is a second marker rather than a reuse of `camera_start`.
  **It renders as a single-tile closed BLUE outline through
  `submit_overlay_lines` (E-24) plus a `HudText` caption — never a sprite**
  (`_submit_camera_limit_center_outline`; `engine/tilemap.py`'s emitters
  deliberately never touch the field, unlike `camera_start`, which IS emitted).
  `LIMIT_CENTER_COLOR` `(60,90,255)` is a deeper, less cyan blue than the
  `pond` tile condition's `(80,140,255)` so a cell carrying both stays
  readable. **It has NO eye of its own — it shares the `camera` eye with
  Camera Start** (a designer hiding "the camera markers" wants both gone,
  the same call the two tutorial markers' shared eye makes).
  `map_requirement_warnings` gains a `"camera limit center"` label when the
  marker is absent.
- **Tutorial markers (4 single-tile brushes)**: a FOURTH mode page
  (`palette.MODES` gains `"tutorial"`, registry `core`/`Tutorial Flute`,
  `core`/`Tutorial Stone`, `core`/`Tutorial Unlock`, `core`/`Tutorial Stone 2`,
  slots `tutorial_flute`/`tutorial_stone`/`tutorial_unlock`/
  `tutorial_stone_2`) with four exclusive sub-brushes, "First Flute",
  "First Stone", "Unlock Tile" and "Second Stone" (the tile-buying tutorial
  topic's two markers, added after the round-1/round-2 pair), in the SAME
  exclusive brush group as every other mode's brushes — arming one disarms
  every sibling marker and everything else. Paint/move/erase mirrors the
  Camera Start pattern exactly (single tile, no clamp, unlike Start Area's
  2×2): paint places the marker if absent or moves it to the clicked cell
  (one undoable command either way), erase clears it from any cell, and a
  press on the marker's own painted cell (eye on, no brush armed) grabs it
  into a drag whose release cell re-places it. **Renders as a labeled white
  diamond OUTLINE through `submit_overlay_lines` (E-24) — never a sprite**,
  the same ED-22-clean idiom as Starting Area's 2×2 outline but a single-tile
  square, plus a `HudText` caption (its brush label) above it via
  `world_to_screen(col + 0.5, row + 0.5)` (the screen-mode selection-caption
  idiom). ONE `tutorial` layer eye gates all four markers together (an
  implementer's call — a designer hiding tutorial markers wants them all gone
  at once, unlike Start Area/Camera which are independent features with
  independent eyes).
- **Spawnable Background / spawn reserve (1 brush + a number)**: a FIFTH mode
  page (`palette.MODES`/`EYES` gain `"spawn_reserve"`, labelled "Spawnable
  Background" via `MODE_LABELS` — which the layer-eye loop now consults too, so
  a mode and its eye can't be labelled two different ways). **A mark is an
  INVISIBLE OVERLAY, not a legend tile code**: it lives in
  `TileMapDoc.spawnable_background` (`{(col,row): stage}`), the underlying
  background art keeps drawing, and the game never sees it as a tile kind — the
  runtime flips every cell numbered n to SPAWNING when the run's STAGE counter
  reaches n (advanced only by the stage-zone brush below — see it for why the
  on-disk key is `stage`, not the `purchase` this shipped as).
  - The page holds ONE **plain-TEXT** brush button (no sprite, no icon — there
    is nothing to import; like the tutorial markers it draws as an outline) in
    the SAME exclusive `_brush_group`, so arming it disarms every other brush.
    It is deliberately NOT in `self._brush_buttons`: that dict drives
    `refresh_icons()` and `_armed_slot()`, both of which need a real registry
    SLOT, which this brush has not got. `armed_spawn_reserve()` therefore
    returns a BOOL, not a slot (the one departure from the
    `armed_tutorial_stone` shape).
  - Under it a `_NoWheelSpinBox` (imported from `balancing.py`, ED-30) for the
    stage number, ranged from `map_file.schema.json`'s own
    `spawnable_background.items.stage` `minimum`/`maximum`
    (`_reserve_number_bounds`) — the bounds have exactly one home. All three
    overlays' bounds now go through ONE `_stage_bounds(property_key)` helper,
    because all three read the same `stage` item key from their own property.
  - **Pure ops mirror the terrain ones one-for-one** in `tilemap_ops.py`
    (`set_reserve`/`reserve_line`/`reserve_rect`/`reserve_bucket`/
    `apply_reserve_changes`/`pick_reserve`), same `(col,row,old,new)` change
    tuple with old/new the stage number or `None`; `map_session.
    _ReserveStrokeCommand`/`push_reserve_stroke` are the exact twins of
    `_StrokeCommand`/`push_stroke`. **`reserve_bucket` floods the region
    sharing the underlying TERRAIN code, not the region sharing a mark** —
    "mark this whole background patch" is the gesture, and it needs its own
    `seen` set since (unlike `bucket_fill`) it never mutates what it walks.
  - The viewport's reserve branch in `_tool_press` sits **before the
    terrain-code branches** (paint/erase/line/rect/bucket/picker), accumulates
    into `_reserve_stroke` and pushes ONE `push_reserve_stroke` on release.
    The picker returns its value through `viewport.reserve_number_picked` →
    `palette.set_reserve_number`, mirroring `code_picked` → `arm_code`.
  - **Rendering is `_submit_spawn_reserve`: an overlay-lines diamond + a
    `HudText` of the NUMBER per mark (E-24/ED-22 — never QPainter, never a
    sprite), and BOTH are window-culled** against the same
    `visible_tile_window` the rest of `_submit_map_items` uses. A map may carry
    hundreds of marks; drawing them all would reintroduce a full-map overlay
    pass into a renderer that windows everything else. `_ghost_items` returns
    nothing for this brush (the outline IS the ghost), like start-area/tutorial.
  - `map_requirement_warnings` gains two NON-BLOCKING labels: `"spawnable
    background tiles"` (no marks painted) and `"spawnable background on
    non-background tiles"` (a mark on a legend code with `checker: true`, i.e.
    a ZONE code — the runtime only flips BACKGROUND tiles, so such a mark is a
    silent no-op).
- **Despawnable Spawn (1 brush + a number)**: a SIXTH mode page
  (`palette.MODES`/`EYES` gain `"despawnable_spawn"`, labelled "Despawnable
  Spawn" via `MODE_LABELS`) — an **exact structural sibling of the spawn-reserve
  page above**, deliberately copied rather than generalised. It paints
  `TileMapDoc.despawnable_spawn` (`{(col,row): stage}`, phase 1); the runtime
  flips every cell numbered n from SPAWNING to COMBAT when the run's STAGE
  counter reaches n. Everything the reserve bullet says applies verbatim with
  the names swapped: plain-TEXT brush button in the same exclusive
  `_brush_group` and deliberately NOT in `self._brush_buttons` (no slot to
  resolve, so `armed_despawn()` returns a **bool**); a `_NoWheelSpinBox` bounded
  by `map_file.schema.json`'s own `despawnable_spawn.items.stage`
  (`_despawn_number_bounds`); pure ops `set_despawn`/`despawn_line`/
  `despawn_rect`/`despawn_bucket`/`apply_despawn_changes`/`pick_despawn` with
  the same `(col,row,old,new)` tuples, `despawn_bucket` flooding the underlying
  TERRAIN region; `map_session._DespawnStrokeCommand`/`push_despawn_stroke`; a
  `_tool_press` branch beside the reserve one and likewise BEFORE the
  terrain-code branches; `_submit_despawn`, a window-culled overlay diamond +
  `HudText` number.
  - **Two deliberate divergences from the reserve twin.** (1) The overlay draws
    in `DESPAWN_COLOR` **magenta** against the reserve's cyan `RESERVE_COLOR`,
    and its number sits *below* the tile centre rather than above — a cell can
    legitimately carry BOTH marks and the designer must tell them apart at a
    glance. (2) The "wrong tile" warning predicate is **narrower**:
    `map_requirement_warnings` compares against the `tile_spawning` SLOT's
    legend codes (`"despawnable spawn on non-spawn tiles"`), not the reserve's
    `checker` zone test — flipping SPAWNING → COMBAT is meaningless anywhere but
    a spawn tile. The empty-overlay label is `"despawnable spawn tiles"`.
- **Stage Zones (1 brush + a number)**: a SEVENTH mode page
  (`palette.MODES`/`EYES` gain `"stage_zones"`, labelled "Stage Zones" via
  `MODE_LABELS`) — the **third exact structural sibling** of the two pages
  above, again deliberately copied rather than generalised. It paints
  `TileMapDoc.stage_zones` (`{(col,row): stage}`, phase 1) on COMBAT tiles, and
  it is **the ONLY thing that advances the run's stage counter**: buying a 2×2
  that intersects the painted set advances the stage to the MAXIMUM number
  among those four tiles, which in turn is what fires the two batches above.
  Nothing else moves it — which is why phase 1 renamed the on-disk key of all
  three overlays from `purchase` to `stage` (`n` is no longer a purchase
  count), and why the whole editor now says "stage" in every label, signal
  comment and docstring for this feature.
  Everything the despawn bullet says applies verbatim with the names swapped:
  plain-TEXT brush button in the same exclusive `_brush_group` and deliberately
  NOT in `self._brush_buttons` (no slot to resolve, so `armed_stage()` returns a
  **bool**); a `_NoWheelSpinBox` bounded by `map_file.schema.json`'s own
  `stage_zones.items.stage` (`_stage_number_bounds`); pure ops `set_stage`/
  `stage_line`/`stage_rect`/`stage_bucket`/`apply_stage_changes`/`pick_stage`
  with the same `(col,row,old,new)` tuples, `stage_bucket` flooding the
  underlying TERRAIN region; `map_session._StageStrokeCommand`/
  `push_stage_stroke`; a `_tool_press` branch beside the other two and likewise
  BEFORE the terrain-code branches; `_submit_stage_zones`, a window-culled
  overlay diamond + `HudText` number; `stage_number_picked` for the eyedropper.
  - **Its two divergences, by the same logic as the despawn twin's.** (1)
    `STAGE_COLOR` is **lime** `(150,255,90)` — a third hue clearly distinct
    from the reserve's cyan and the despawn's magenta — and its number sits
    lower still than the despawn's (reserve `sy-6`, despawn `sy+4`, stage
    `sy+14`), so a cell carrying all THREE marks stays readable. (2) The
    "wrong tile" warning predicate is the despawn's with the slot swapped:
    `map_requirement_warnings` compares against the `tile_combat` SLOT's legend
    codes (`"stage zones on non-combat tiles"`), NOT the reserve's `checker`
    zone test — the stage only ever advances on a combat-tile purchase. The
    empty-overlay label is `"stage zone tiles"`.
- **Tile Conditions (4 name brushes)**: an EIGHTH mode page
  (`palette.MODES`/`EYES` gain `"tile_conditions"`, labelled "Tile Conditions"
  via `MODE_LABELS`) — the **fourth** per-cell overlay, painting
  `TileMapDoc.tile_conditions` (`{(col, row): "mountain"}`); the runtime gives
  a marked cell exactly that condition and excludes it from the random
  condition roll. Structurally the stage-zones twin, again copied rather than
  generalised: pure ops `set_condition`/`condition_line`/`condition_rect`/
  `condition_bucket`/`apply_condition_changes`/`pick_condition` with the same
  `(col, row, old, new)` tuples, `condition_bucket` flooding the underlying
  TERRAIN region; `map_session._TileConditionStrokeCommand`/
  `push_condition_stroke`; a `_tool_press` branch beside the other three and
  likewise BEFORE the terrain-code branches; `_submit_tile_conditions`, a
  window-culled overlay diamond + `HudText`; no ghost (the outline IS the
  ghost).
  - **It is the FIRST paint mode whose brush value is a NAME, not a number** —
    so instead of a `_NoWheelSpinBox` the page carries ONE plain-text brush
    button PER condition, all in the SAME exclusive `_brush_group` (the
    gametiles/background code-brush idiom), which is what makes the
    eyedropper's return path (`viewport.condition_picked` →
    `palette.arm_tile_condition`) a plain re-check of the matching button,
    exactly like `code_picked` → `arm_code`. `armed_tile_condition()` therefore
    returns the NAME (or None), not the bool the three number overlays return.
    The buttons live in their own `self._condition_buttons` dict, NOT in
    `self._brush_buttons`, for the same reason those three brushes don't: that
    dict drives `refresh_icons()`/`_armed_slot()`, which need a registry SLOT.
  - **The four names come from the schema, never from editor code**:
    `palette._condition_names()` → `engine.tilemap.condition_codes_from_schema`
    → `map_file.schema.json`'s `tile_conditions.items.condition.enum`, the
    single source of that vocabulary (the same "schemas over convention"
    argument as `_stage_bounds`). Adding a fifth condition is a schema edit and
    nothing else: the brush, its label and its tooltip all follow, and
    `viewport.CONDITION_COLORS` degrades an unknown name to
    `CONDITION_DEFAULT_COLOR` rather than raising (E-37).
  - **Its divergences, by the same logic as the other twins'**: one outline hue
    per condition (`CONDITION_COLORS` — pale yellow / slate / blue / green
    against the reserve's cyan, despawn's magenta, stage's lime) and the label
    sits lower than all three numbers (reserve `sy-6`, despawn `sy+4`, stage
    `sy+14`, condition `sy+24`) so a cell carrying all four marks stays
    readable. No `map_requirement_warnings` entry: an unmarked map is the
    normal case (the runtime rolls conditions randomly), so there is nothing to
    warn about.
- **"None" tool**: `PalettePanel.TOOLS` starts with `"none"`, default-armed. It
  structurally cannot paint/erase/place deco but the base-cell check runs BEFORE
  tool dispatch, so dragging the base still works; a LEFT-drag under "none" (off the
  base) PANS. `viewport._ghost_items` returns nothing for `"none"`.
- **Palette import** (`editor/asset_import.py`): while a map is open the palette
  replaces `DetailsPanel`, so the normal importer is unreachable. The palette's
  "Import Spritesheet…" targets whichever brush is armed (deco → base → armed
  code's slot) and calls `editor.asset_import.import_idle_sheet(data_dir, registry,
  slot_key, png_path)` — a Qt-free, pygame-free helper (in `TestPurity`) that writes
  exactly ONE `idle` row (map/deco slots' `animations` vocab is `["idle"]` only).
  Emits `manifest_changed(slot)`, wired to `MainWindow._on_manifest_changed` (same
  handler as `DetailsPanel.entry_saved`/`entry_cleared`, which now ALSO calls
  `palette.refresh_icons()`).

## Phase B4 — screen mode (`ui_screen_session.py`, `panels/screen_details.py`, `panels/_screen_primitives.py`; R3)
- **Selection** (`panels/selector.py`): the "Screens" branch is the FIRST
  child of the "ui" category node (mirrors the Maps branch under "map"), one
  leaf per `data/ui/screens/*.json`, labelled by the filename stem (screen
  docs carry no display-name field, unlike maps). A screen leaf emits
  `screen_selected(screen_id)` + `domain_selected("ui")` and NEVER
  `node_selected` — the `_MAP_ROLE`/`_SCREEN_ROLE` branches in `_emit_selection`
  are structurally identical. `screen_ids()`/`select_screen()`/
  `refresh_screens()` mirror `map_ids()`/`select_map()`/`refresh_maps()`
  exactly (selection-preserving rebuild).
- **`ViewportPanel.set_screen_mode(session, defaults)`** (mirrors
  `set_map_mode`): a FIXED logical canvas at **`data/display.json`'s
  resolution** — never a literal size. `viewport.logical_resolution(data_dir=
  None)` loads it at import and fills `SCREEN_W`/`SCREEN_H`; there is
  deliberately **no numeric fallback** (a fallback would be a second source of
  truth, so a missing/invalid `display.json` raises). The canvas is
  scaled-to-fit the widget (`_screen_scale_offset`) —
  no viewport-driven zoom, the whole canvas is always visible, like the
  entity preview's parked camera.
  - **UR-3 — the preview renders through the canvas, not through scaled
    geometry** (`_render_screen_frame`): the screen's CONTENT is submitted at
    the identity triple `(1.0, 0, 0)` into a cached `SCREEN_W x SCREEN_H`
    `pygame.Surface`, flushed into it, then blitted to the widget surface with
    ONE `pygame.transform.scale` (never `smoothscale` — pixel art) at
    `_screen_scale_offset`'s letterbox offset. This mirrors the game's own
    `pygame.SCALED` pipeline, and it is the only parity-true option: `HudText`
    carries a font key and no scale, so the old scale-the-geometry path drew
    labels at absolute pixel size inside scaled boxes and the label/box ratio
    was wrong by exactly `1/scale`. **Editor chrome is deliberately NOT
    scaled** — selection outline/handles/caption, the E-37 placeholder and the
    canvas-edge frame (`_submit_screen_chrome`) are submitted in SCREEN pixels
    after the blit and ride `render_frame`'s own flush. Two flushes, one
    `Renderer` (ED-22): `flush` clears the queue.
  - **The fit scale snaps to a whole multiple at or above 1.0**
    (`math.floor` inside `_screen_scale_offset`; offsets floored too). Below
    1.0 the fractional downscale is unchanged. The snap lives in that ONE
    helper, never at the blit, so hit-testing, dragging and the drawn image
    cannot disagree. `NUDGE_STEP` stays 1 LOGICAL px.

  `defaults` is the FULL loaded
  `data/ui/screen_defaults.json` mapping (`{screen_id: {widgets, mock_note}}`),
  not a single screen's sub-dict — `_current_screen_defaults()` is the ONE
  place that indexes it by the open session's `screen_id`.
  - **Graceful degrade (E-37) is the LIVE state until B3 lands**: an empty/
    missing `defaults` (or a screen id absent from it) renders a red
    "no layout defaults yet — click Refresh Layouts" `HudText` and every
    widget interaction (`_screen_press`/`_screen_move`/`_nudge_selected`) is a
    no-op by construction — each checks `_current_screen_defaults()` first, so
    there is nothing to iterate over a missing key.
  - **ALL submission goes through `Renderer.submit_hud`** (ED-22 one render
    path): background (`{slot}` → whole-screen `HudSprite`, `{color}` →
    `HudRect`) first, then each widget. A widget with a `skin` override, or a
    kind-matched default (`doc["defaults"]["button_skin"]`/`"panel_skin"` for
    `kind in ("button", "panel")`), renders as `HudSprite(skin, dest, size,
    tint, animation=state, anim_time_ms=screen_anim_clock)`; the label rides
    alongside as a centred `HudText`. An UNSKINNED widget renders through
    `editor.panels._screen_primitives.fallback_hud_items` — flat rect(s) +
    centred label, keyed off the `kind` enum (`button|panel|label|backdrop|
    bar|field`, pinned by `screen_defaults.schema.json`); `label` draws text
    only, no box. `_screen_primitives` is pure (HUD dataclasses +
    `engine.render.fonts.TextMetrics` for vertical centring only — `HudText`'s
    own `align="center"` only shifts x) and NEVER imports `game/ui` — an
    accepted drift (layering rule), kept aligned to the real skinned look by
    eye + the B2 parity pin, not by shared code.
  - **Interaction**: click hit-tests widgets in REVERSE submission order
    (topmost = last-drawn); a selected widget gets a `HudLines` outline +
    4 `HudRect` corner handles. Drag-move/resize LIVE-mutates
    `session.doc["widgets"][id]["rect"]` directly (exactly like a tilemap
    paint stroke) and commits ONE `push_move`/`push_resize` on release —
    idempotent by the same argument as `map_session`'s stroke commands
    (pushing after the doc is already mutated just re-applies the same
    value). Arrow keys nudge 1 logical px per undoable `push_move` (no
    live-drag needed — `QUndoStack.push()` calls `redo()` itself).
    `ViewportPanel.setFocusPolicy(StrongFocus)` + `setFocus()` on select is
    what lets arrow keys reach it in the real app.
  - **State dropdown** (idle/hover/pressed/disabled): a floating `QComboBox`
    like the entity-preview animation combo, populated from
    `registry.category("ui").animations` (data-driven, not a literal list) —
    drives every skinned widget's `HudSprite.animation` for the frame.
  - **`refresh_screen_defaults(defaults)`** / **`set_selected_widget(id)`**:
    the "Refresh Layouts" re-render path and the screen_details↔viewport
    selection sync, respectively — neither touches mode/session state.
- **`ScreenDetailsPanel`** (`panels/screen_details.py`, right pane,
  `right_stack` index 2): widget list (from the current screen's defaults) →
  per-widget form (rect spinboxes + skin/font combos + Color/Text Color
  `QColorDialog` buttons + label edit + visible checkbox — the `_NoWheel*`
  widgets are IMPORTED from `editor.panels.balancing`, never copied).
  **Reset is per-FIELD, not per-widget**: every override-capable control
  carries its OWN compact "↺" `QToolButton` (`_field_row`/`_make_reset_button`)
  firing `push_field(widget_id, <key>, old, None)` for THAT key only — reset
  the rect while keeping an assigned skin, or vice versa. Rect is ONE button
  for the whole X/Y/W/H group (`_field_row` wraps all four spinboxes + one
  reset — it's stored as a single `rect` key, not four). Each reset button's
  enabled state (`_refresh_reset_buttons`) is "does THIS key currently have
  an override" — computed every `_populate_widget_form`, which also runs
  after every undo/redo (`indexChanged`), so a button never invites a no-op
  click. A separate **"Reset ALL to default"** button below the form still
  clears every override on the widget at once (one `push_field(..., None)`
  per key — `_DocFieldCommand`'s pruning drops the widget entry once it's
  empty either way) → screen-level Background picker (slot combo + color
  button + its OWN reset via `push_background(None)`, since background is a
  single key regardless of whether it's currently `{slot}` or `{color}`) → a
  `Defaults` `CollapsibleSection` (button_skin/panel_skin/font/text_color,
  each its own combo/button + `push_default_field(..., None)` reset) → Save
  (greyed out `not session.dirty`). Every edit AND every reset is an
  IMMEDIATE undoable push_* — NOT staged like `balancing.py`. Skin/background
  combos list `registry.
  group_slots("ui")`/`group_slots("ui", ("Backgrounds",))` (registry-driven,
  never hardcoded); font combo keys mirror `engine/render/fonts.py`'s private
  `_FONT_SPECS` (duplicated as a local tuple rather than importing a
  leading-underscore cross-module name). `session.undo_stack.indexChanged`
  refreshes the visible form/background/defaults section after Ctrl+Z/Y so
  nothing goes stale.
  - **Widget list is display-named, selection is UserRole-keyed (UH-4, D4)**:
    each `QListWidgetItem`'s TEXT is `widget_display_name(widget_id, spec)` —
    `spec.get("display_name") or widget_id` (`editor.panels._screen_primitives.
    widget_display_name`, the ONE resolution rule shared with the viewport
    caption below) — and its TOOLTIP is always the raw code id (the id's
    secondary surface). The selection contract itself never reads item text:
    `item.setData(Qt.ItemDataRole.UserRole, widget_id)` at construction, the
    list's `currentItemChanged` connect (not `currentTextChanged` — display
    names aren't guaranteed unique, the id is) reads `item.data(UserRole)` in
    `_on_widget_list_selected` and still emits the CODE id on
    `widget_selected`; `select_widget(widget_id)` scans rows for
    `item.data(UserRole) == widget_id` instead of `findItems(text, …)`.
    `display_name` is a cosmetic, editor-only field (`screen_defaults.json`,
    OPTIONAL per widget, authored by `tools/export_ui_layouts.py`'s
    `_DISPLAY_NAMES` mapping) — it never appears in an override doc, and
    `_populate_widget_form`/every `push_*` call is unchanged, still keyed by
    the code id via `self._current_widget`. The viewport's selection outline
    (`viewport._submit_screen_selection`) gains a matching `HudText` caption
    above the outline using the SAME `widget_display_name` helper, so the
    list and the canvas can never show two different names for one widget.
- **`MainWindow`**: `_on_screen_selected` → `_resolve_dirty(session=None)`
  (generalized to take ANY session — every pre-B4 call site passes none and
  gets `map_session`; screen mode passes `self.screen_session`) →
  `session.open` → `_enter_screen_mode()` (loads
  `data/ui/screen_defaults.json`, wires viewport + screen_details, switches
  `right_stack`) / `_leave_screen_mode()`. Ctrl+Z/Y route through
  `_active_undo_stack()` (screen session while `viewport.in_screen_mode()`,
  else map session). **"Refresh Layouts"** toolbar action →
  `RunControls.export_layouts()` (same tracked-`QProcess` + console-streaming
  path as Build, distinguished by the `which` string on the shared
  `started`/`finished` signals) → on exit 0, reloads defaults into viewport +
  screen_details + `selector.refresh_screens()`.
- **`_enter_screen_mode()` reloads the asset manifest on EVERY entry**
  (`viewport.reload_assets()`, ED-42, called first thing — before
  `_load_screen_defaults()`/`set_screen_mode`): the viewport's `AssetStore`
  is built once at `ViewportPanel.__init__` and otherwise only rebuilt by an
  explicit `reload_assets()`/`reload_registry()` call (`engine/assets/
  CLAUDE.md` "no cache invalidation") — without this, an editor left running
  while `data/sprites/asset_manifest.json` changed on disk (a fresh import,
  a branch switch, another process's write) kept showing grey-X/flat-rect
  skins in screen mode until restart, even though the doc's `skin`
  override/`defaults.button_skin` resolved fine (a `HudSprite` is emitted
  either way — `skin` comes from the screen doc, not the manifest; only the
  RESOLVED FRAME was stale). `_on_export_layouts_finished` (the "Refresh
  Layouts" completion handler) reloads too, for the same reason. Both calls
  are cheap: `AssetStore` loads sheet PNGs lazily, so a reload is a fresh
  manifest-JSON read plus a fresh (empty-cache) `AssetStore`/`Renderer`, not
  a bulk re-decode. Regression coverage:
  `test_editor_viewport.TestScreenModeReloadOnEntry` (fails red without the
  `reload_assets()` call — proven by reverting it) and
  `TestScreenModeRealSkinRenderPath` (the real on-disk-doc + real-manifest
  render path — every earlier skin test only exercised
  `push_skin_assign` on an in-memory session, never a populated screen
  JSON, so a manifest-resolution regression here had no test that could
  have caught it).

### The details panel scrolls; the dirty label and Save do not

`ScreenDetailsPanel`'s body (outliner → per-widget form → Layers box → the
per-layer/per-state inspector → Background → Defaults) is roughly 2k lines of
controls deep and used to be a bare `QVBoxLayout`, so on any normal right-pane
height the bottom of it simply fell off the panel. The body now lives in a
`QScrollArea` — `balancing.py`'s pattern verbatim (`setWidgetResizable(True)`,
`NoFrame`), with everything that used to be added to the panel layout going
into one inner `QWidget` handed to `setWidget`.

- **The dirty label stays pinned at the top and Save at the bottom, OUTSIDE
  the scroll area.** A Save you have to scroll to find is the original
  complaint in a new place.
- **Every value control in this panel is a `_NoWheel*` from
  `editor.panels.balancing`** — and that is not a style rule here, it is what
  makes the scroll area usable: they ignore `wheelEvent`, so a scroll over a
  spinbox reaches the scroll area instead of silently nudging a rect. A plain
  `QSpinBox`/`QComboBox` added to this panel is a bug.
- `widget_list` carries a minimum height (`_OUTLINER_MIN_HEIGHT`): under
  `setWidgetResizable(True)` a tree with no floor collapses to nothing.

### Screen-mode ZOOM (`_zoom_combo`) + middle-drag pan

A fourth floating combo in `viewport.py`, built/placed/shown exactly like
`_state_combo`/`_anim_combo`/`_column_combo` and the **inverse** of the last
two: it is visible ONLY in screen mode (they hide there). Entries are the
literal `_SCREEN_ZOOM_LEVELS` — `Fit`, `100%`, `200%`, `300%`, `400%` — and
screen-mode entry always re-parks it on `Fit` (`_refresh_zoom_combo`).

- **The zoom feeds `_screen_scale_offset()` and NOTHING else.** That helper is
  the one `(scale, ox, oy)` triple the blit, the hit-test and every drag read;
  applying a zoom at the blit in `_render_screen_frame` instead is precisely
  the disagreement the UR-3 snap was moved into that helper to prevent.
  `Fit` is the old behaviour unchanged (`min(w/SCREEN_W, h/SCREEN_H)`, floored
  to a whole multiple at or above 1.0); an explicit percentage is used verbatim
  as the scale. Offsets stay floored and centred.
- **`wheelEvent` still early-returns in screen mode** — the picker is the
  chosen affordance, deliberately not the wheel.
- **Middle-drag pans** (map mode's gesture, on a button screen editing never
  uses). The pan is folded into the same `(ox, oy)`, so hit-testing follows for
  free, and it is CLAMPED by `_screen_offset_bounds`: a canvas bigger than the
  widget can never show a gap at an edge, a smaller one stays wholly inside —
  either way it cannot be dragged off-screen. It resets to centred on every
  zoom change and every screen-mode entry.
- Unchanged: chrome (selection outline, handles, caption, the E-37 placeholder,
  the canvas-edge frame in `_submit_screen_chrome`) is submitted in SCREEN
  pixels AFTER the blit and stays UNSCALED; `NUDGE_STEP` is still 1 LOGICAL px;
  the blit is still `pygame.transform.scale`, never `smoothscale`.

## Editable buy options + reachable text anchors (editable-ui-widgets)

The complaint this answers: "the UI editor can't replace many pieces of info
which should be replaceable; all individual pieces of information need to be
editable widgets, and so should everything that gets added in, like the buying
options."

**The HUD readouts were already individual ids** (`love_text`, `income_text`,
`lvl_label`, `xp_bar`, `round_label`, … — since 10L-B). What was missing was
any way to *reach* them:

- **A position-only text anchor stores `(x, y, 0, 0)`** — the anchor-rect
  convention (`game/ui/CLAUDE.md`). Eight of `hud`'s twenty widgets, the phase
  banner, `boss_cutscene`'s headline and ~40 `building_panel` stat cells are
  shaped that way. A zero-AREA rect is unclickable, undraggable and invisible
  when selected, so those widgets existed on disk and nowhere else.
- **`_screen_primitives.interaction_rect(rect, text=, font_key=, align=)`**
  (pure) is the fix: it grows a zero-extent axis to the MEASURED size of the
  widget's live text, floored at a grabbable minimum, and shifts x per
  `align`. `viewport._interaction_rect` is the ONE place it is called from
  the panel side, and `_hit_widget` / `_submit_screen_selection` /
  `_submit_screen_widget`'s label fallback all read it — the outline a
  designer sees is exactly the box they can click, by construction.
- **The stored rect is never widened.** A drag/nudge on an anchor still
  writes x/y and leaves w/h at `0`, so the game's own layout is untouched.
  `is_anchor_rect` suppresses the four resize handles for such a widget
  (there is no stored size for a resize to write) and `_submit_screen_selection`
  draws a single marker on the stored ANCHOR POINT instead — for a
  centre-aligned label that point is not the outline's corner, and the X/Y
  fields address the point, not the box.
- **Two new OPTIONAL `screen_defaults.json` widget keys feed the measurement**:
  `font_key` and `align` (`data/CLAUDE.md`). Recorded only when the widget
  carries them, so every button/panel entry stays byte-identical.
- **Hit-testing picks the SMALLEST candidate, not the last-submitted one.**
  The editor submits widgets in key (alphabetical) order, which is NOT the
  game's panel->button->text order, so "topmost" was meaningless here: live
  example, `hud.income_text` sits inside `hud.love_panel`'s overridden rect
  and the panel swallowed every click on the Love-per-round readout. Smallest
  wins is also simply what a designer expects. Ties fall back to the later key.

**Dynamic-count content is individually overridable now** — this REVERSES the
old "levelup's option boxes / building_ui's construct cards get no id" rule
that the UI screen customization section still describes for its own history.
The rule's real constraint was never "the count varies", it was "there is no
stable id to attach an override to", and both cases have one: an INDEX
(`option_box_0..2`, the roll's three slots) and a BUILDING TYPE
(`card_<building_type>`). See `game/ui/CLAUDE.md` for the game side.
- The exporter records them from the SAME `tools/screen_mocks.py` state the
  preview generator draws from: `LEVELUP_OPTIONS` grew to three cards (the
  roll's maximum, so every slot is recorded) and the `construct` view unlocks
  every RESEARCH type before building its cards (so every card is recorded,
  by sweeping the RESEARCH table — a new `/add-building` type is covered with
  no edit).
- `screen_mocks.BP_VIEW_ID_PREFIXES` generalizes UT-3's single `stat_` prefix
  rule into `{view: (prefix, ...)}` so `construct` picks up `card_*` the same
  way `upgrade` picks up `stat_*`.

## Live placement — the rect spinboxes move the widget as you type

`ScreenDetailsPanel`'s X/Y/W/H spinboxes work like a viewport drag rather than
a form field: `valueChanged` mutates `session.doc[...]["rect"]` in place (the
16 ms frame timer repaints, no signal needed) and ONE undoable `push_move` is
committed at the END of the gesture. Previously the widget only jumped once
Enter or focus-out landed, so a designer nudging a coordinate was typing blind.
- **End of gesture** = whichever comes first: `editingFinished` (Enter /
  focus-out) or `_LIVE_COMMIT_MS` (400 ms) of quiet. The timer is what covers
  arrow-button clicks and press-and-hold, neither of which ever emits
  `editingFinished`.
- **`_rect_baseline` is captured at the START of the burst and NOT advanced by
  the live mutation**, which is what makes 30 arrow clicks one undo step.
- **`_flush_live_rect()` commits before the form re-points** at another widget
  (`_populate_widget_form`, `select_widget(None)`) — `_on_rect_edited` reads
  `self._current_widget`, so it must run while that is still the widget being
  edited. `_refresh_after_undo` instead STOPS the timer without committing:
  the undo has just redefined the doc, and pushing from inside the undo
  stack's own `indexChanged` would be re-entrant. It swallows `RuntimeError`
  for the same window-teardown race `_refresh_dirty` already guards.
- **W/H spin minimums went 1 -> 0**, so an anchor widget's real `0` round-trips
  instead of being clamped to `1` and written back as a bogus size.

## Widget parenting (UiEditorParentingPLAN P-1..P-5)

The screen-mode widgets are a HIERARCHY, not a flat list: `hud.love_text` is a
child of `hud.love_panel` because `hud.py`'s `_layout_readouts()` computes it
off that panel's rect, and the editor now says so. The relationship is DATA —
an optional `parent` per widget in `data/ui/screen_defaults.json` (authored by
`tools/export_ui_layouts.py`'s `_PARENTS`/`_PARENT_CONTAINERS`) plus an
optional `parent` override per widget in the open screen doc. The cross-cutting
shape (including the `NO_PARENT` sentinel `push_field` needs for D3's explicit
`null` re-root) is in `editor/CLAUDE.md`; the resolver is the pure
`editor/widget_tree.py`. **Nothing in `game/` reads any of it** — parenting is
an AUTHORING relationship, and the tooltip on both the tree and the Parent
combo says so, because the game's own `layout()` still recomputes every
default each frame with no cascade.

- **The outliner REPLACES the flat widget list; it does not sit beside it**
  (D6 — a second parallel widget selector would violate the
  single-selection-model invariant). `ScreenDetailsPanel.widget_list` is a
  `WidgetTreeWidget(QTreeWidget)` with the **SAME `Qt.ItemDataRole.UserRole` =
  code id contract**, so `widget_selected`/`select_widget` and every `push_*`
  call site are unchanged. Display name as item text, raw id as tooltip
  (`widget_display_name` stays the ONE naming rule), expanded by default.
  `self._tree_items` maps id -> item so `select_widget` stays O(1) — a tree
  has no `setCurrentRow`.
- **`_refresh_widget_list` is the ONE thing that draws the tree.** The drop
  handler deliberately does NOT call `super().dropEvent()`: letting Qt move
  the item would reshuffle the view behind the data's back. It emits
  `reparent_requested`, the panel writes `push_field(widget_id, "parent",
  old, new)` — the existing per-key undoable path, so the "↺" button and
  "Reset ALL" cover a re-parent with **no new code** — and the rebuild
  follows from the doc.
- **The drag copies `panels/timeline.py`'s shape** (the repo's other
  `QDrag`/`QMimeData` user): one custom MIME type carrying the code id, plus
  its testing note — **a real OS drag cannot be synthesized offscreen, so
  drive `dropEvent` directly.**
- **A cycle is unrepresentable, not an error to recover from** (D5, ED-30).
  `WidgetTreeWidget.can_reparent` is injected by the panel and consulted in
  `dragMoveEvent` (so the drop is refused before it happens) AND again in
  `dropEvent`; the Parent combo offers exactly `widget_tree.legal_parents`, so
  the keyboard path and the drag refuse the same set. The resolver
  additionally roots any cyclic or dangling chain instead of raising — a
  hand-edited `screen_defaults.json` must never hang a Qt paint handler.
- **The override is written only when it DIFFERS from the exporter's default
  parent** (the same "no redundant override" rule the rect and label rows
  follow). Choosing the default clears the key; choosing "(none)" on a widget
  whose default parent is not already root writes an explicit JSON `null`,
  because clearing would restore the default instead of re-rooting.
- **Moving cascades; resizing does NOT** (designer's call). `_begin_drag`
  captures the subtree only for `mode == "move"`; `_screen_move` applies the
  same delta to each descendant **from ITS OWN rect at press**, never from
  the rect the previous move event wrote, so rounding cannot accumulate over
  a long drag; `_screen_release` commits ONE `push_move_subtree` (a
  `_DocFieldsCommand` — full old/new per widget, never a delta, the
  `map_session` stroke-command contract). The arrow-key nudge cascades
  identically, since it shares `push_move`'s contract. A dimmer
  `SUBTREE_COLOR` outline is drawn around every widget that will come along,
  under the selection's own bright outline.
- **Visibility inherits in the PREVIEW only** (D4). `_hidden_subtrees` is
  resolved ONCE per frame and once per hit-test (both callers loop over every
  id; a per-widget ancestor walk would rebuild the parent map ~85 times on
  `building_panel`, and the common case — nothing hidden — exits before
  building a tree at all). `_submit_screen_widget` and `_hit_widget` both skip
  the set; the saved `visible` override stays per-widget and the game keeps
  resolving each widget's own flag. The details panel's Visible row reads
  `Visible  (hidden by parent "<name>")` rather than the preview silently
  drawing nothing, with the checkbox still enabled.
  - **KNOWN GAP:** the skip lives in the per-widget FALLBACK draw path. When
    the UT-2 recorded preview is in sync the editor replays the recorded draw
    list instead, and that recording knows nothing about parenting — a child
    of a hidden parent can still appear there. Closing it would mean teaching
    the recorder the hierarchy, i.e. giving the exporter a runtime notion of
    parenting, which is exactly what D2/D4 keep out.

## Widget layers in the outliner (UiLayeredWidgetsPLAN UL-6)

A LAYER is extra art/text drawn under or over one widget, stored as an entry in
that widget's `layers` ARRAY in the open screen doc (schema + pure resolver
landed in UL-3/UL-4/UL-5: `engine/ui_layers.py`'s `resolve`/`ordered`/
`validate_offsets`). UL-6 is the authoring half — the outliner shows them and
`ScreenDetailsPanel`'s Layers section adds/removes/reorders them.

- **`layers` is an ARRAY, so a layer op cannot use a per-layer command path.**
  `_DocFieldCommand`'s `_set_at` walks DICTS: a path ending in a layer id
  (`widgets/<id>/layers/<layer_id>`) would silently write an OBJECT where the
  schema demands an array, and the next `save()` would fail validation. Every
  op therefore pushes ONE command at `("widgets", <id>, "layers")` carrying the
  FULL old and FULL new array — the same "never a delta" contract as
  `push_move`, and still exactly one undo step per op. An emptied array is
  pushed as `None`, so the "None = absent" pruning removes the key (and
  `widgets/<id>` when it was the only override) rather than leaving `[]`.
- **The session owns all five entry points** (`editor/ui_screen_session.py`):
  `layers(widget_id)` (a deep COPY — reading cannot mutate the doc),
  `add_layer`, `remove_layer`, `set_layer_field(..., old, new, text=None)` and
  `reorder_layer(..., new_z)`, which is `set_layer_field` on `z` alone. The
  panel never touches the array itself, exactly as it never writes a rect.
- **A layer id is the only handle** remove/reorder/inspect have, and
  `ordered()` silently DROPS a duplicate non-empty id — so `add_layer` refuses
  an empty or already-used id rather than creating a layer that draws but
  cannot be edited. The panel generates `layer_1`, `layer_2`, … (first free
  index — deterministic and readable, not a uuid), so that guard is a backstop.
- **A layer node's `UserRole` is a `(widget_id, layer_id)` TUPLE**; widget nodes
  keep the bare-id-string contract unchanged. `isinstance(role, tuple)` is what
  tells them apart in `_on_widget_list_selected`, `startDrag` and
  `_drop_parent`. `self._layer_items[(widget_id, layer_id)] -> item` is the
  layer twin of `_tree_items`.
- **Selecting a layer still selects its OWNER widget everywhere else** — the
  form keeps showing the widget's controls and `widget_selected` still emits
  the widget id (per-layer inspection is UL-8). Only the Layers buttons and the
  read-only "Selected layer:" line change. Layers are NOT re-parentable: a drag
  from a layer node is refused, and a drop ON one targets its owner widget.
- **Listed in PAINT order** — `ordered(layers, "under")` then
  `ordered(layers, "over")`, i.e. the game's own order, so the outliner cannot
  claim a stacking the screen does not have. Up/Down set `z` to the
  neighbour's z ∓ 1, never the neighbour's z itself: `ordered` sorts STABLY, so
  an equal z would leave the pair in source order and the button would appear
  to do nothing.

## Layers in the viewport (UiLayeredWidgetsPLAN UL-7)

UL-6 authors layers in the outliner; UL-7 is the direct-manipulation half —
`panels/viewport.py` draws every layer where the game will draw it, hit-tests
it and drags/resizes it, through `panels/_screen_primitives.
layer_interaction_rect`.

- **Selection has TWO LEVELS, not two selections.** `_selected_widget` is
  ALWAYS the owner widget; `_selected_layer` is the layer id within it, or
  `None`. So the caption, the P-3 subtree outline, the details form and the
  existing `widget_selected` signal keep working untouched while the mouse is
  actually holding a layer. The new `layer_selected(widget_id, layer_id|None)`
  signal is emitted ALONGSIDE (never instead of) `widget_selected` — UL-8's
  per-layer inspector is its intended consumer.
- **Hit-test order: the selected widget's layers, then every other widget's
  layers, then the widgets** (`_hit_layer`, falling through to `_hit_widget`).
  Within a tier the SMALLEST candidate wins — `_hit_widget`'s own rule for its
  own reason — and an area tie goes to the highest `z`, i.e. the one painted
  last. Consequence, deliberate: a widget fully covered by its own `over` layer
  is only selectable from the outliner.
- **All geometry goes through `engine.ui_layers` (D3).** `resolve` is the only
  place `owner + dx` happens, and `layer_interaction_rect` therefore takes the
  RESOLVED rect rather than the raw offset + owner rect. It adds exactly one
  thing: the zero-extent growth `interaction_rect` already gives a widget
  anchor (a layer inherits its owner's w/h from a `0`, so it is zero-extent
  precisely when its owner is an anchor).
- **Release restores the pre-drag offset BEFORE pushing.** The drag
  live-mutates `doc[...]["layers"][i]["offset"]` (the layer twin of a widget
  drag writing `rect`), but UL-6's `set_layer_field` builds its command's OLD
  value from the array AS IT IS AT PUSH TIME — so without the restore, undo
  would "restore" the dragged value. A widget drag dodges the same trap by
  handing `push_move` an explicitly captured `old_rect`.
- **Handles are exclusive**: a layer selection owns them, and
  `_hit_resize_handle` refuses the widget's while `_selected_layer` is set —
  two handle sets on one corner would be a coin flip. A zero-extent layer gets
  a single anchor-point marker and no handles, like an anchor widget.
- **`screen_previews.json` is override-free by design**, so a layer can never
  be in the replay: on the preview path both bands composite ON TOP of it
  (`under` still before `over`, so their relative order is honest even though
  neither can get behind a recorded widget). Only the no-preview path can put
  `under` genuinely behind its widget. Never bake layers into that file.

### UL-8 — the per-layer, per-state inspector

Sits BELOW the Layers buttons, in the same box: a state selector plus one row
per layer key, on B4's per-field immediate-undoable-push convention
(`_field_row` + `_make_reset_button`), never `balancing.py`'s staged edits.

- **The state selector decides the SCOPE of every row.** `Idle` writes the
  layer entry itself (`layers[i][key]`); `Hover`/`Pressed`/`Disabled` write
  `layers[i].states[<state>][key]` and leave every other state's patch alone.
  Both go out through the ONE `session.set_layer_field` call — for a state the
  key written is `states` and the value is the whole rebuilt object, so it is
  still exactly one undo step per edit.
- **An emptied state patch is REMOVED, not left as `{}`.** `{}` is PRESENT and
  therefore means "this state looks like the base"
  (`engine.ui_layers._state_patch` — presence drives the fallback, not
  truthiness), which is not what a reset was asked for.
- **`z` and `band` are not state-patch keys**, so those two rows always write
  the base entry whatever the selector says.
- **Ruling 1 — hover/pressed/disabled are greyed on a NON-Button holder**, with
  `TOOLTIP_STATE_BUTTON_ONLY`, and the rows stay pinned to Idle:
  `ScreenSkinning.state_of` resolves anything that is not a `Button` to `idle`
  forever, so per-state values on a label/panel/backdrop holder are schema-valid
  and permanently unreachable (ED-30).
- **Ruling 2 does NOT apply to layers.** S2's "a Button's `color`/`tint`/`font`/
  `label` per-state keys are inert" is about the WIDGET-level `states` patch
  (`widgets.py Button.submit` wires only `text_color`/`offset`). A LAYER's state
  patch goes through `engine.ui_layers.resolve`, which merges every appearance
  key, so nothing is hidden here.
- **What IS honest-controlled is PRECEDENCE, and it is the whole chain.**
  `skinning._submit_one_layer` draws ONE primitive and returns: `slot` →
  `HudSprite` (reads `tint`, nothing else), else `text_id`/`label` → `HudText`
  (reads `font`/`align`/`text_color`), else `color` → `HudRect`. So, computed
  from the SELECTED state's effective values in `_refresh_layer_inspector`:
  Tint is live only with a slot; Text dies behind a slot (and stays editable
  otherwise — typing in it is how the text branch is created); Text Color is
  live only with no slot AND some text; Color is live only with no slot AND no
  text. Each dead row carries its own reason (`TOOLTIP_LAYER_*`). Disabling
  only the Color-behind-a-slot case was a HIGH review finding on this phase —
  the other three rows silently accepted values the game never reads.
- **`TOOLTIP_LAYER_BAND` (D4) is on BOTH band controls** — the add-picker and
  the per-layer row: `under` is behind the whole SCREEN, not behind the owner
  widget, and that has to be met in the editor rather than in a bug report.
- The inspector's state selector is the PANEL's own combo. **UL-10 LINKED it
  to `viewport.py`'s floating preview-state dropdown** (the cross-panel wiring
  UL-8 deferred): both directions are connected in `editor/main.py` beside the
  `widget_selected` cross-connect, and both are loop-guarded — the viewport's
  `set_screen_state` early-returns on an unchanged name, and the panel's new
  `sync_layer_state(name)` sets the combo with `blockSignals` before calling
  `_refresh_layer_inspector()`. A name the panel's combo does not carry is
  ignored rather than snapping the selector to Idle. `viewport.layer_selected`
  (UL-7's signal, unconsumed until now) is connected to
  `screen_details.select_layer` there too — one direction only, since the
  panel has no matching signal to send back.

### UL-10 — Clickable + Target rows

Two more BASE-ONLY rows at the bottom of the layer inspector (the `Z`/`Band`
pattern — neither is a state-patch key, and "clickable on hover only" is not
something the resolver expresses), plus an inline warning label.

- **Clickable** is a checkbox; `False` is the schema default, so only an
  explicit `True` is stored (`visible`'s idle-scope convention).
- **Target** is an EDITABLE `_NoWheelComboBox` pre-filled with the open
  screen's widget ids (`_current_screen_defaults()["widgets"]`, the same
  source `_refresh_parent_combo` reads) plus the three reserved tokens
  `close_window`/`back`/`noop`. It is a convenience list, never a closed enum:
  **D7 as amended lets an id-shaped target naming neither still SAVE.** Free
  text commits on the line edit's `editingFinished` (the `label_edit` rule) or
  on `activated`.
- **`RESERVED_TARGETS` is restated in this module, not imported from
  `game.ui.skinning`** — `editor/` may never import `game/` (D5). The game
  module's docstring names this file as its twin.
- **The warning is required, and it never gates the write.** Every value
  change recomputes routability (a widget id in THIS screen, or a reserved
  token) and sets `layer_target_warning` — amber, word-wrapped — saying the
  click will be SWALLOWED, not passed through. That wording matters: the game
  side's Ruling 1 makes a dead target stop the click, so "does nothing" is the
  honest description, not "falls through".
- Both write through `session.set_layer_field` (S3's path) via
  `_push_layer_base_field`, so undo/dirty need no special case, and both join
  `_layer_inspector_controls()`/`_layer_reset_buttons()` so they enable,
  disable and reset with every other row.

### UL-12 — the designer-facing half

`docs/ui-layers-for-designers.md` is the walkthrough a DESIGNER reads: add a
layer, give it a hover colour, the Under/Over gotcha, and what the amber target
warning means. It is deliberately written without schema key names, file:line
citations or decision IDs — it is the only layers document that assumes no
knowledge of this repo. **If you change the layer inspector's controls,
wording or gating, change that file too**; it describes the same UI in the same
order (outliner → state selector → band → clickable/target), so a rename here
silently makes it wrong. The agent-facing counterparts stay where they are:
this file for the editor, `game/ui/CLAUDE.md` for the runtime, `data/CLAUDE.md`
for the schema.

## Phase UT-2/UT-6 — the real screen preview + the Text-template row

- **`ViewportPanel` REPLAYS a recorded draw list** (`data/ui/screen_previews
  .json`, `data/CLAUDE.md`) instead of drawing only the named widgets as flat
  boxes. `refresh_screen_previews(previews, recorded_doc=None)` installs it
  (deserializing ONCE, cached per `(screen, view)` — a list runs to dozens of
  primitives and `_submit_screen_items` runs every 16 ms);
  `_current_screen_preview()` resolves the active view the same way
  `_current_screen_defaults()` does. Missing/corrupt/absent-for-this-screen
  degrades to the pre-UT-2 flat-box rendering (E-37), never a raise. Still
  ED-22-clean: every replayed item goes out through `Renderer.submit_hud`.
- **`_preview_in_sync()` is the whole correctness argument.** A recording is a
  picture of ONE exact doc. In sync (the live doc equals `recorded_doc`), the
  recording IS the screen and the editor draws nothing but selection chrome
  over it — plus the widget under an in-flight drag, whose live rect no
  recording can know. **Out of sync** (an edit just landed, or a saved doc
  carries overrides and no re-record has finished), the editor ALSO draws
  every id'd widget from defaults+overrides on top: they briefly ghost against
  their recorded selves, which is strictly better than a stale picture that
  HIDES your edit. Do not "simplify" this by always replaying — that made an
  assigned skin invisible and turned `TestScreenModeReloadOnEntry` red.
- **`MainWindow` re-records on every screen-doc change**, debounced
  (`_PREVIEW_DEBOUNCE_MS`, driven off `screen_session.undo_stack.indexChanged`
  so it covers undo/redo too) and once more on screen-mode entry when the
  saved doc is non-empty. It writes `{screen_id: doc}` to a temp file and runs
  `RunControls.render_preview`, which is deliberately its OWN QProcess slot,
  NOT `_launch`'s: this fires after every nudge, so queueing it behind Build
  (or having Build refuse because a preview render is in flight) would make
  both feel broken. A render already in flight is KILLED, not queued — only
  the newest doc is worth drawing — and it streams nothing to the console.
  `preview_renders` is injectable and DEFAULTS TO FOLLOWING
  `auto_refresh_layouts`, so the test suite never spawns a real render.
- **`ScreenDetailsPanel`'s Label row becomes "Text template"** when the
  selected widget has a `text_id` (its own override, else the exporter's).
  It then edits `data/ui/strings.json` through
  `UIScreenSession.push_string` — the same undo stack, a different doc — and
  the grey line beneath shows the resolved `sample` plus a **"used by N
  widgets"** warning, because the table is GLOBAL and that is not obvious from
  the row. An unbound widget keeps the per-widget `label` override verbatim.
  A **Text ID** combo re-points a widget at another EXISTING id; the editor
  never invents one (the table is a closed set — adding a key is a schema
  change, i.e. a code change).
- **`_screen_rules.label_is_code_owned` gained a `text_id` argument** and
  returns False for anything bound — that rule's reach is now small
  (`TOOLTIP_LABEL_CODE_OWNED` survives for what genuinely stays code-owned,
  e.g. a `field`'s user-typed contents).

## Phase ESV-4 — vfx preview (`panels/vfx_preview.py`, `editor/vfx_params.py`)
- **A DEDICATED panel, not a fourth `ViewportPanel` mode.** ESV-2 owns
  `viewport.py` concurrently (anchor handles + drag); a `set_vfx_mode`
  branch there would collide with that diff for no architectural gain, so
  `VfxPreviewPanel` builds its own `Renderer`/`AssetStore`/coordinate system
  (structurally copying `ViewportPanel.__init__`/`_build_store`/
  `render_frame`) — the router's ED-22 section explains why a second
  `Renderer` instance is still one render path. **ESV-5 changed how it's
  hosted**: it is no longer its own `right_stack` page — it is a THIRD child
  (beside `self.details`/`self.anchors`) of a `QSplitter` inside
  `self.details_pane` (`right_stack` index 0), because it turned out
  `MainWindow._leave_vfx_mode` had targeted `self.details` since ESV-2 — a
  widget that was never a stack page at all (only `self.details_pane` was
  ever `addWidget`-ed) — so selecting a vfx node once permanently stranded
  the asset importer for the rest of the session. `_enter_vfx_mode`/
  `_leave_vfx_mode` now just toggle `self.vfx_preview.setVisible(...)`;
  frames advance on the SAME 16 ms `QTimer` as the viewport, gated on
  `self.vfx_preview.isVisible()` (true only when BOTH its own explicit flag
  is set AND `details_pane` is the current stack page — Qt's ancestor-chain
  visibility rule does the second half for free) so an inactive preview
  costs nothing. `right_stack.count() == 3` now (asset import / map / screen
  — the vfx preview no longer has its own page).
- **Composes with the generic balancing form, never duplicates it.** `vfx`
  is a real balancing domain (ESV-3a) and already gets the recursive form
  for free (`domains.py`'s derivation). The preview adds only what the
  generic form structurally cannot: a picture, colour-picker swatches for
  the named-stop ramps, and a curated 2-3-number lever strip for the family
  currently playing — every other tunable stays in the generic tree,
  reachable exactly as before.
- **One staging store, no second writer (§2.3).** The panel holds no copy of
  `vfx.json` and never calls `write_validated`: `BalancingPanel.staged_value(path)`
  / `.stage_value(path, value)` are the ONLY read/write seam, and
  `BalancingPanel.value_staged(path, value)` (emitted from `_commit`, so it
  fires for a generic-form edit OR a preview-driven `stage_value` alike) is
  what lets a lever here and its twin row in the generic form never
  disagree. Save stays the balancing panel's one existing button; there is
  exactly one dirty state in the app. A `stage_value(path, value)` whose
  `path` addresses a whole ARRAY (a named-stop colour: `.../ramp/stop_0`,
  a 3-int RGB list) falls back to the PER-INDEX widgets `_build_array`'s
  array-of-scalars branch actually registers (`.../stop_0/0`, `/1`, `/2`) —
  there is no single widget at the array's own path to push into.
- **Family list is data-driven** (the keys under `procedural` in the loaded
  doc, sorted — never a hardcoded literal list), so ESV-3b's
  `beam`/`crater`/`lightning`/`announce` show up with zero panel edits. A
  family with no emitter binding (`floaters` today) degrades to a
  placeholder message (E-37) — never an exception, never a crash from a
  combo-box selection change.
- **Determinism (§2.6): `self._rng` is reseeded to the SAME fixed seed on
  every `_emit()` call**, and `_emit()` builds a brand-new `VfxSystem` from
  scratch every time (never mutated in place) — which is also how "any
  lever edit clears the currently-live particles first" (§1.4) falls out
  for free, with no separate clear-then-rebuild step. Tests assert the
  PARAMS `_emit()` handed to `VfxSystem`'s constructor (a spy swapped in
  for `vfx_preview.VfxSystem`), never a rendered pixel.
- **`editor/vfx_params.py`** is the editor's own local mirror of
  `game/ui/effects.py`'s `_color`/`_ramp`/`_params_from_balance` — pure
  (stdlib + `engine.vfx` only), because `editor/` may never import `game/`
  (D5's layering argument lives in the router). This is a KNOWN, reported
  duplication, not an oversight — do not "fix" it by importing `game.ui`.

### feat-projectile-anchored-flight — the `projectile` family + the entity-preview muzzle draw
Two editor additions, both driven by `procedural.projectile`
(`engine.vfx.ProjectileParams`, via the SAME `editor/vfx_params.py
projectile_params` every other family's `VfxParams` construction already
calls):
- **`vfx_preview.py`'s `projectile` family is NOT a `VfxSystem` emitter** —
  a projectile is a continuous flying object the game draws itself (like a
  beam), never an `emit_*` burst — so it is deliberately kept OUT of
  `_EMIT_FAMILIES` (a separate `_PROJECTILE_FAMILY` constant marks it
  "supported" for the degrade-label check) and given its own small preview
  path, `_submit_projectile_preview`: a dot/sprite interpolated between two
  fixed world points over `self._loop_clock % self._loop_interval`, using
  `vfx_projectile`/`vfx_shell` art when imported (the same `assets.
  animation_total_ms(slot, "idle") is not None` "has art" signal the game
  reads) else the coloured dot. A `_shell_check` box (the `_strong_check`/
  `_large_check` precedent) toggles stone<->shell. No RNG involved (a
  straight interpolation), so nothing here needs reseeding — only the
  flight clock resets on a family switch (`_set_family`), mirroring
  `_emit()`'s own `self._loop_clock = 0.0`.
- **`viewport.py`'s entity preview draws the projectile at the `muzzle`
  handle** (`_submit_muzzle_projectile`, called from `render_frame` right
  before `_submit_anchor_handles()` so the crosshair stays on top): gated on
  `"muzzle" in self._anchors`, it resolves the handle's screen point through
  `_anchor_draw_params()`/`anchor_ops.screen_point` — the SAME call the
  handle marker itself uses, never a second computation — and submits a
  `HudSprite`/`HudRect` at the handle's exact point and real (`stone_size`)
  size.
  - **PERF (the `slot_draw_fit` lesson, re-learned once already this
    plan): `data/balancing/vfx.json` is memoized, never read inside
    `render_frame`/`_anchor_draw_params`/`_hit_anchor_handle`/
    `_anchor_move`.** `ViewportPanel._load_projectile_params()` (a
    `data_io.load_validated` + `vfx_params.projectile_params` call) runs
    ONCE in `__init__` and again in `reload_registry()` (mirroring
    `_resolve_draw_fit`'s two call sites) — unlike `_draw_fit` it does NOT
    depend on `preview_slot` at all, so `set_preview_slot` does not
    re-resolve it. Measured (`stone_thrower_t1_lvl1` previewed, a `muzzle`
    handle set, 1280×720): `render_frame` ~6.4ms/frame avg (vs ~5.5ms/frame
    with no muzzle anchor at all, i.e. the projectile draw itself costs
    under 1ms); 2000 `_hit_anchor_handle`+`_anchor_move` calls (a synthetic
    drag) totalled ~12.8ms, ~6.4 MICROseconds each — proof there is no
    per-call JSON re-read.

## Phase UH-2 — per-mode screen views + auto Refresh Layouts on entry
- **`building_panel` gets five views, exported by UH-1's per-mode snapshot
  exporter** (`unlock`/`construct`/`upgrade`/`base_info`/`preview`) instead of
  one superimposed pile of every mode's widgets. `data/ui/screen_defaults.json`
  per-screen shape is unchanged for every OTHER screen; `building_panel` gains
  an optional `views` key: `{view_id: {widgets, mock_note}}` — the SAME shape
  as a per-screen entry, so the resolver below returns either interchangeably.
  Top-level `widgets` stays the required first-wins union (back-compat: the
  game's known-id check and any pre-UH-2 reader still work); the editor
  ignores it whenever `views` is present.
- **`VIEW_ORDER`/`ordered_views()`** (`editor/ui_screen_session.py`, module
  level, one authority) pin the game-mode display order
  (`unlock, construct, upgrade, base_info, preview`) — needed because D-3's
  sorted-keys JSON alphabetizes the `views` object (`base_info` first).
  Selector and `MainWindow` both import it from here.
- **`UIScreenSession.view`** (non-doc, non-undoable) is the active view, or
  `None` for a screen's single implicit view (every screen but
  building_panel). `open()` resets it to `None`; `set_view(view_id)` sets it
  and emits `view_changed` — the session does NOT validate view names (it
  holds only the override doc, not defaults); validity is the caller's job.
- **One resolution point per consumer, no per-call-site changes.**
  `ViewportPanel._current_screen_defaults()` and
  `ScreenDetailsPanel._current_screen_defaults()` both: get the screen's
  entry, and if it carries `views` and the session's `view` names one, return
  `entry["views"][view]` instead of `entry`. Because every render/hit-test/
  nudge path and the widget list already funnel through these two functions,
  this single change IS the per-view filtering — `_refresh_widget_list` needs
  no code change, it just iterates whichever dict comes back.
  `ViewportPanel._effective_rect` layers the session doc's override on top of
  whichever `defaults` came back, so an id present in several views (`panel`,
  `close_btn`) carries ONE override applying in every view (D2) with zero
  extra plumbing.
- **Selector**: the "Screens" branch (B4) gains a child leaf per view under
  any screen whose `screen_defaults.json` entry carries `views` — a NEW
  `_screen_views_from_disk()` helper (a fresh degrade-to-`{}` read mirroring
  `MainWindow._load_screen_defaults`, approved over adding a MainWindow
  injection path) reads the file itself. View leaves carry `_VIEW_ROLE`
  (`(screen_id, view_id)`) and emit `screen_view_selected(screen_id,
  view_id)` + `domain_selected("ui")` — never `screen_selected`/
  `node_selected` (the exact `_SCREEN_ROLE` pattern, one level deeper).
  `select_screen_view()` mirrors `select_screen()`; `refresh_screens()`'s
  selection-preserving rebuild also preserves a selected VIEW leaf, falling
  back to the screen leaf if the view vanished.
- **`MainWindow` wiring**: `_on_screen_selected` (a bare screen-leaf pick)
  sets the DEFAULT view — `ordered_views(views)[0]` if the screen has views
  (`"unlock"` for building_panel), else `None` — then calls
  `_enter_screen_mode()`. New `_on_screen_view_selected(screen_id, view_id)`
  is the identical flow (same-doc fast path; `_resolve_dirty` only when
  opening a DIFFERENT screen) but sets the CHOSEN view. **View switching
  re-runs `_enter_screen_mode()` in full** — `viewport.set_screen_mode`
  already resets widget selection/drag state and `screen_details.set_defaults`
  → `_on_screen_opened` rebuilds the list/form, so no stale-selection handling
  is needed; the repeated `reload_assets()` is cheap by design (above).
  Switching views on the SAME open doc never triggers the dirty prompt and
  never clears the undo stack (only `_resolve_dirty` does that, and it's
  skipped on the same-doc path).
- **Auto Refresh Layouts on screen-mode entry**: `MainWindow(...,
  auto_refresh_layouts=True)` (injectable, the `prefs_path=` precedent) plus
  `self._screen_mode_entered` gate `_enter_screen_mode()`: immediately after
  `reload_assets()`, if `auto_refresh_layouts` and not yet entered this
  session, call `self.run_controls.export_layouts()` (the SAME tracked-
  QProcess path "Refresh Layouts" the toolbar button uses — its own
  completion handler already refreshes defaults/status bar; a run already in
  flight silently refuses the auto-call, run_controls' one-tracked-process
  rule). Set the flag true; `_leave_screen_mode()` resets it, so re-entering
  screen mode later fires again exactly once. Switching views or screens
  WHILE already in screen mode does NOT re-fire it. Every test-suite
  `MainWindow(...)` construction passes `auto_refresh_layouts=False` except
  the dedicated auto-refresh tests (which stub `run_controls.export_layouts`
  with a recorder — never a real subprocess in tests).
## Theme panel (`panels/game_theme.py`, `theme_ops.py`; UH-6, D5/D6)
- **Selection**: a single "Theme" LEAF (not a branch — one document pair,
  nothing to enumerate) is the SECOND child of the "ui" category node,
  right after "Screens" (which stays FIRST, the B4 invariant above) —
  `panels/selector.py`'s `_THEME_ROLE` marker + `theme_selected()` signal,
  never `node_selected` (the same never-node_selected rule as Maps/Screens
  leaves). `MainWindow._on_theme_selected` → `right_stack` →
  `GameThemePanel`.
- **`GameThemePanel`** edits `data/ui/fonts.json` (per-key size spinbox,
  schema-bounded 4-72, + bold checkbox) and `data/ui/palette.json` (per-key
  color swatch → `QColorDialog`) in ONE form, two `CollapsibleSection`s.
  Edits are STAGED (the `balancing.py` pattern, not the screen-session undo
  pattern): every change updates an in-memory doc + a dirty dot; ONE "Save
  Theme Changes" button (enabled only while dirty) is the sole
  `write_validated` call site for both files, saving only whichever doc
  actually changed. `data_dir=None` injection, `_NoWheelSpinBox` imported
  from `editor.panels.balancing` (never copied). Missing/invalid data
  degrades to a placeholder message (editor-side E-37 grace — the panel
  must not crash `MainWindow` construction; the GAME's own boot load fails
  loud instead, D-2).
- **`editor/theme_ops.py`** (Qt-free, pygame-free, in `TestPurity`) — load/
  write helpers for both files plus `font_keys(data_dir)`, which
  `screen_details.py`'s font combos now source from (replacing the old
  hardcoded `_FONT_KEYS` tuple) with a literal 7-tuple fallback if the file
  is unreadable.
- **Save reconfigures the engine in-process**: `GameThemePanel.saved` →
  `MainWindow._on_theme_saved` → reloads `data/ui/fonts.json` and calls
  `engine.render.fonts.configure_fonts` + repaints the viewport
  (`render_frame()`), so screen-mode preview TEXT tracks the new sizes
  without an editor restart. `editor/theme.py` (Qt chrome light/dark) is
  untouched by any of this — a completely different "theme". Palette edits
  have no separate editor-side consumer to reconfigure (`game/ui/widgets`
  is game-only, off limits to the editor); the game re-reads
  `palette.json` at its own next boot.
- **Honest Tint control (ties to UH-3, D6)**: UH-3 disables the
  `screen_details.py` Color picker on a skinned widget with a "colors come
  from the sprite sheet" tooltip (D3 — the control cannot take effect, so
  it must not silently accept input). UH-6 REPURPOSES that exact state
  instead of leaving it disabled: `tint` DOES reach the game
  (`widgets.Button.submit`/`submit_panel` thread it into the `HudSprite`),
  so on a widget that resolves to a skin (`_screen_rules.resolved_skin` —
  imported, never duplicated) the SAME control is ENABLED, relabelled
  "Tint" (both the `QFormLayout` row label and the button text), writes/
  resets the `tint` key (`push_field`/`_on_reset_field("tint")`), tooltip
  "multiplies the sprite sheet — white = unchanged". An UNSKINNED widget
  keeps the plain Color behavior verbatim (writes `color`). `self.
  _color_is_tint` (set by `_refresh_honest_controls`, which now runs
  BEFORE `_refresh_reset_buttons` in `_populate_widget_form` — the one
  genuine UH-3/UH-6 coupling point) is the single source of truth
  `_active_color_key()` reads, so the button handler and the reset button
  can never disagree about which doc key is live. **Reconciled rule
  (UH-3 ∩ UH-6, integration).** UH-3 landed a refinement after UH-6 branched
  (code-owned fills), so `_refresh_honest_controls` composes both. Tint is
  offered for the kinds whose draw path actually threads `tint` to the sheet —
  **`button` and `panel`**:
  - **skinned `button` or `panel`** → Tint (enabled, relabelled,
    `TOOLTIP_TINT_SKINNED`). `Button.submit` always forwards `tint`; every
    *id'd* panel widget forwards it at its `submit_panel` site
    (`building_ui.py:238,932`, `cheat_menu.py:217`, `add_name.py:134`,
    `boss_cutscene.py:162`, `hud.py:321,354,448`). The two `submit_panel`
    sites that DROP `tint` (`building_ui.py:1252` boss popup, `levelup.py:128`
    boxes) draw dynamic, NON-id'd content never present in
    `screen_defaults.json`, so they are never selectable here.
  - **code-owned-fill kind** (`panel`/`field`/`label`,
    `_screen_rules.color_is_code_owned`) when UNskinned → Color DISABLED with
    `TOOLTIP_COLOR_CODE_OWNED` (the game hardcodes the fill). `field`/`label`
    never resolve to a skin, so they always land here.
  - **otherwise** → plain Color enabled — an unskinned button, or a
    `backdrop`/`bar` whose `.color` the game genuinely reads.
  **Known residual (deferred, viewport finding 3):** `hud.love_panel` is kind
  `panel` but draws via `HudRect` (hardcoded fill, no sheet), so a `skin`
  forced onto it would show a Tint that no-ops — the same
  skin-on-a-non-skinnable-widget quirk that affects `backdrop`/`bar`; tracked
  separately, not solved here. `TOOLTIP_COLOR_SKINNED` stays exported from
  `_screen_rules.py` (stable name) but `screen_details.py` no longer uses it.
- **Viewport honesty fix (`panels/viewport.py:933`)**: screen mode now
  tints a skinned widget's preview from its `tint` key, never `color` — the
  pre-UH-6 editor lie (the game has always ignored `color` on a skinned
  widget; `game/ui/skinning.py`'s `button_kwargs` docstring). What the
  editor shows is what the game draws (ED-22's promise, extended to color).
- **Font Family (UH-Font-A)**: a THIRD `CollapsibleSection`, "Font Family",
  after Fonts and Palette — a game-wide custom font, ORTHOGONAL to the
  7-preset size/bold system above (`data/ui/fonts.json` is completely
  unchanged by this). Edits `data/ui/active_font.json`
  (`{"font_id": "default" | <font_manifest entry id>}`) with the SAME
  staged/dirty-dot/one-Save-button pattern as Fonts/Palette — the dirty key
  is the single string `"active_font"` (not per-field, since there's only
  one field). "Import Font…" (`QFileDialog.getOpenFileName`, filter
  `Fonts (*.ttf *.otf)`) is the ONE exception to "staged": like
  `DetailsPanel`'s sprite import, `editor.font_import.import_font_file`
  copies the file into `data/fonts/imported/<font_id>.<ext>` and writes the
  `data/fonts/font_manifest.json` entry to disk IMMEDIATELY, through
  `write_validated` — only the CHOICE of which imported font is *active* is
  staged. The combo lists "Default (System Monospace)" (`font_id:
  "default"`) plus every manifest entry's `display_name`
  (`theme_ops.imported_fonts`), sourced fresh on every import so a newly
  imported font appears without a panel rebuild.
  - **Live preview, no restart**: below the combo, one `QLabel` per font-key
    preset (`"The quick brown fox…"`) rendered via
    `QFontDatabase.addApplicationFont(path)` + `QFont(family, pointSize,
    bold=…)` — reflecting the CURRENTLY SELECTED (not-yet-saved) combo
    choice AND the (possibly also staged) Fonts-section size/bold values, so
    a designer previews both edits together before committing either.
    Family lookups are cached per font id (`_loaded_font_families`) so
    switching back and forth in the combo doesn't reload the same file
    twice; the cache is cleared on `set_theme()` (a fresh entry into the
    Theme leaf re-reads from disk).
    - **Register from BYTES — `addApplicationFontFromData`, never
      `addApplicationFont(<path>)`.** The path form looks harmless (it does
      not lock on its own), but the first time Qt's font engine actually
      loads a GLYPH from that family it opens the file and holds it for as
      long as the family stays registered — on Windows a hard lock, and
      `MainWindow` construction alone is enough to trigger it. That left the
      editor sitting on the designer's font file for its whole run and broke
      every `TempDataCase` teardown (`shutil.rmtree` -> `PermissionError`)
      the moment a non-`"default"` font was active. This is the SAME trap
      and the SAME fix as `engine/render/fonts.py`'s `_FONT_BYTES` on the
      pygame side (`engine/render/CLAUDE.md`) — two font stacks, one rule:
      **the font file is read once into memory and never held open.** An
      unreadable file caches `None` and degrades to the default family
      (E-37), never raises into a Qt handler.
  - **`editor/font_import.py`** (Qt-free, pygame-used, in `TestPurity`):
    `import_font_file(data_dir, ttf_path, display_name=None) -> font_id`
    validates the file loads via a short `pygame.font.Font(path, 12)` probe
    BEFORE anything touches disk (raises `ValueError` on a bad file — a
    FORMAT check, not a second render path; it mirrors what
    `engine/render/fonts.py` itself does to load a font, so it does not
    violate ED-22) — mirrors `editor/asset_import.py`'s "copy a file in,
    write a manifest entry" shape, slugifying the display name/filename
    stem into the font id instead of any sprite-specific concept
    (frame_w/h, rows, animations — none of that applies to a font file).
  - **Save reconfigures the engine in-process** the same way the Fonts
    section does: `MainWindow._on_theme_saved` additionally resolves the
    active font id to an absolute path via
    `theme_ops.resolve_active_font_path` and passes it to
    `engine.render.fonts.configure_fonts`'s new `font_path=` kwarg — `None`
    for `"default"`/a missing manifest entry/a missing file on disk
    (editor-side E-37 grace; `game/main.py`'s own boot loader performs the
    identical cross-check but fails LOUD instead, D-2).

## Strings panel (`panels/strings_panel.py`, `strings_ops.py`; Phase C)
- **Selection**: a single "Strings" LEAF (not a branch — one flat document,
  nothing to enumerate) is the THIRD child of the "ui" category node, right
  after "Theme" (which stays SECOND, the UH-6 invariant above) —
  `panels/selector.py`'s `_STRINGS_ROLE` marker + `strings_selected()`
  signal, the exact `_THEME_ROLE` pattern one leaf over (never
  `node_selected`). `MainWindow._on_strings_selected` → `right_stack` →
  `StringsPanel`.
- **`StringsPanel`** edits `data/ui/strings.json` (`game/ui/CLAUDE.md`
  "Global UI string table") — a FLAT `{string_id: template}` map, one row
  per id, grouped into a `CollapsibleSection` (imported from `balancing.py`,
  never copied, the `game_theme.py` precedent) per source-module prefix
  (`hud`, `widgets`, `levelup`, `boss_cutscene`, …, derived by splitting each
  id on its first `.`), plus a filter `QLineEdit` at the top (matches
  against the id or the row's current text, case-insensitive) since the set
  runs to dozens of rows — filtering hides non-matching rows and collapses
  a section whole once none of its rows match. Each row is a `QLineEdit`
  (commit on `editingFinished`, the `balancing.py` string-field convention)
  plus a read-only placeholder-hint `QLabel` recomputed from the row's OWN
  live text on every edit (`strings_ops.placeholders`, a `string.Formatter`
  parse — no `str.format()` correctness check, just a hint so a designer
  editing a templated row can see what it still needs to fill; a bad edit
  fails at the GAME's next render/boot like any other data typo).
- Edits are STAGED (the `balancing.py`/`game_theme.py` pattern, not the
  screen-session undo pattern): every change updates an in-memory doc + a
  dirty dot next to that row (compared against a baseline captured at
  load/last-save time); ONE "Save Strings" button (enabled only while
  dirty) is the sole `write_validated` call site. `data_dir=None`
  injection; missing/invalid data degrades to a placeholder message
  (editor-side E-37 grace, same as `game_theme.py`) — the GAME's own boot
  load fails loud instead (D-2).
- **`editor/strings_ops.py`** (Qt-free, pygame-free, in `TestPurity`) —
  `load_strings`/`write_strings` (both through `write_validated`) plus
  `placeholders(template)`. A SEPARATE module from `theme_ops.py` on
  purpose: that module is scoped to fonts/palette/font_manifest/
  active_font (the font+color THEME), a different document shape from
  `strings.json`'s flat map — one file per concern, the same split
  `asset_import.py`/`font_import.py` already keep (`data/CLAUDE.md`'s
  precedent for this call).
- **Save does NOT reconfigure anything in-process, and has no `saved`
  signal consumer.** Unlike `GameThemePanel.saved` → `MainWindow.
  _on_theme_saved` (which reconfigures `engine.render.fonts` because the
  VIEWPORT renders through it, ED-22's one render path), `strings.json` is
  consumed ONLY by `game/ui/strings.py` — a game-package module the editor
  may never import (`editor/` never imports `game/**`). This is the exact
  case `data/CLAUDE.md`'s theme-data section already documents for
  `palette.json` ("`game/ui/widgets` is game-only... the game re-reads
  `palette.json` at its own next boot") — `strings.json` follows the SAME
  rule, not the fonts.json one, because there is no editor-side consumer to
  reconfigure, not because reconfiguring would be wrong in principle. The
  Strings panel's `saved` signal is still emitted (symmetry with
  `GameThemePanel.saved`, kept for a future consumer) but `MainWindow`
  connects nothing to it today.

## Cutscenes panel (`panels/cutscenes.py`, `cutscene_import.py`; TU-3)
- **Selection**: a single "Cutscenes" LEAF (not a branch — the registry's own
  row list lives inside the panel, nothing to enumerate in the tree) is the
  THIRD child of the "ui" category node, after "Screens" then "Theme" (the
  UH-6 ordering invariant above) — `panels/selector.py`'s `_CUTSCENES_ROLE`
  marker + `cutscenes_selected()` signal, same never-node_selected rule as
  Maps/Screens/Theme leaves. `MainWindow._on_cutscenes_selected` →
  `right_stack` → `CutscenesPanel`.
- **`CutscenesPanel`** edits `data/video/cutscenes.json` (TU-1's registry, `id
  -> {video, audio (nullable), length, trigger}`): one row per entry, built
  via `cutscene_import.ordered_entry_ids(doc)` — a `TRIGGER_ORDER` display
  pin (`("intro", "first_end_turn")`, the `ordered_views()`/`VIEW_ORDER`
  precedent) so the alphabetically-first `first_end_turn` placeholder never
  displays above the seeded `intro` row just because
  `data_io.dumps_deterministic` sorts keys. Each row: `trigger` shown
  read-only/disabled (fixed by TU-1's script wiring, never editable here);
  video/audio filename labels + "Import MP4…"/"Import Audio…" buttons
  (`QFileDialog.getOpenFileName`, filtered to `*.mp4` / `*.ogg *.mp3`); a
  "Clear Audio" button enabled only while `audio` is not null; a length
  `_NoWheelDoubleSpinBox` (imported from `editor.panels.balancing`, never
  copied) ranged from the schema's `length` `minimum`/`maximum` (0..3600
  today) via `cutscene_import.length_bounds`, committing on
  `editingFinished`.
- **Immediate per-action writes, NOT staged** (unlike `GameThemePanel`'s
  dirty-dot pattern): import video/audio, Clear Audio, and a committed
  length edit each call `cutscene_import.write_registry_doc` on the spot —
  there is no multi-field form to batch here, and a loud
  `write_validated` failure beats a dirty-dot UI for a 4-field row. No
  add/remove-row affordance: TU-1 owns which ids exist.
- **`editor/cutscene_import.py`** (Qt-free, pygame-free, in `TestPurity`):
  `load_registry_doc`/`write_registry_doc` (load degrades to `{}` on a
  missing/corrupt file, E-37, mirroring `asset_import.load_manifest_doc`;
  write is the ONE `write_validated` call site for this file);
  `video_dest`/`audio_dest` name the destination deterministically off the
  cutscene id — `data/video/<id><suffix>` /
  `data/video/<id>_audio<suffix>`, never the source filename (the
  `imported/<slot_key>.png` rule); `import_video`/`import_audio` copy (skip
  when source and destination already resolve to the same file) and return
  the bare destination filename; `probe_length_seconds` lazily imports cv2
  and returns `None` on every failure mode (absent cv2, unopenable capture,
  zero/invalid fps) — never raises, mirroring `engine/video.py`'s
  graceful-skip contract, so a missing cv2 install never blocks editing and
  the panel's manual spin-box stays authoritative; `clear_audio` deletes the
  entry's current audio file (no refcount needed — a cutscene's audio is
  always 1:1-owned by its id, unlike `asset_import`'s shared-sheet model)
  and returns the doc with `audio: None`, leaving the actual write to the
  caller.

## Tutorial panel (`panels/tutorial_panel.py`; TU-4, generalized TU-8)
- **Selection**: a single "Tutorial" LEAF (not a branch — one document,
  nothing to enumerate) is the FOURTH child of the "ui" category node, after
  "Screens", "Theme", then "Cutscenes" (the ordering invariant above) —
  `panels/selector.py`'s `_TUTORIAL_ROLE` marker + `tutorial_selected()`
  signal, same never-node_selected rule as Maps/Screens/Theme/Cutscenes
  leaves. `MainWindow._on_tutorial_selected` → `right_stack` →
  `TutorialPanel`.
- **`TutorialPanel`** edits `data/tutorial/tutorial.json` (TU-1): one row
  per key in the **`messages`** object, DATA-DRIVEN off
  `sorted(self._doc["messages"])` (not a hardcoded key tuple — TU-8 added a
  third key, `close_panel_hint`, the flute chain's non-modal close-panel
  banner text, with zero panel code change beyond this generalization; a
  future fourth key needs only a schema/content change again), each a
  `QPlainTextEdit` — the first multi-line text field in the editor, a
  deliberate departure from `balancing.py`'s `QLineEdit` convention,
  justified by message length. `_message_label(key)` resolves a friendly
  row label from a small curated table (`_MESSAGE_LABELS`) and falls back to
  a mechanical title-case of the key for one the table doesn't know, so an
  unrecognized new key still renders sensibly. Plus the two behavioral flags
  (`skippable`, `first_loss_costs_life`, `QCheckBox`). Edits are STAGED (the
  `game_theme.py` pattern): every change updates an in-memory doc + a dirty
  dot; ONE "Save Tutorial Changes" button (enabled only while dirty) is the
  sole `write_validated` call site. `data_dir=None` injection. Missing/
  invalid data degrades to a placeholder message (editor-side E-37 grace).
- **Empty-text guard (ED-30)**: since `QPlainTextEdit` has no
  `editingFinished`, this panel commits on focus-out instead (`_MessageEdit`,
  a thin subclass overriding `focusOutEvent`, calling back into the panel).
  On that commit path, an all-whitespace message is never staged — the
  field is restored to its last staged value instead, regardless of what
  TU-1's schema `minLength` would also catch; this makes invalid text
  unrepresentable in the UI rather than relying solely on the schema
  backstop.
- **`steps` (and any other TU-1-owned key) round-trips untouched**: the
  whole loaded doc is kept in `self._doc` and written back whole on Save, so
  an edit to texts/flags never perturbs the step list, and a doc that was
  never touched saves byte-identical.
- **`editor/tutorial_ops.py`** (Qt-free, pygame-free, in `TestPurity`) —
  load/write/path helpers for the one file, mirroring `editor/theme_ops.py`.
- **`saved = Signal()`** exists for test observability and symmetry with
  every other staged-edit panel, but has no in-process `MainWindow`
  consumer (unlike Theme) — no engine reconfiguration follows a text/flag
  edit. Documented in the panel's own docstring so a future phase does not
  go looking for a missing connection.

## Timeline panel (`panels/timeline.py`, `timeline_ops.py`, `timeline_curve.py`; TimelinePLAN T5)
- **Selection**: a single "Timeline" LEAF (one document, `data/balancing/
  progression.json`, nothing to enumerate) is the FIRST child of the
  "buildings" category node — the exact Theme/Cutscenes/Tutorial/Strings
  shape (one category over), chosen over a toolbar button after re-reading
  this doc mid-implementation: those four are the real precedent for a
  single-document panel, not `run_controls`/`spawnclaude` (actions, not
  `right_stack` pages). `progression` is deliberately not itself a
  `slots.json` category (TimelinePLAN D1 — it needs a bespoke drag-and-drop
  widget, never the generic recursive balancing form), so there was no
  existing tree node to hang it off; "buildings" was picked because
  `progression.json` schedules building unlocks. `panels/selector.py`'s
  `_TIMELINE_ROLE` marker + `timeline_selected()` signal, never
  `node_selected`. `MainWindow._on_timeline_selected` → `right_stack` (index
  7, the newest page).
- **Staged edits, the `tutorial_panel.py` pattern**: every drag/clear/add/
  remove mutates an in-memory doc through the pure `editor/timeline_ops.py`
  helper + a dirty flag; ONE "Save Timeline" button is the sole
  `timeline_ops.save_progression` (`write_validated`) call site, which
  cross-checks the two invariants JSON Schema can't express (`village_level`
  uniqueness, `(building_type, tier_index)` uniqueness) before writing.
- **First drag-and-drop in this editor** — no prior `QDrag`/`QMimeData` usage
  existed anywhere in `editor/` before this. A custom MIME type
  (`application/x-htbh-timeline-card`) carries `"<kind>|<building_type>|
  <tier_index>"`; `_BrowseCard.mouseMoveEvent` starts the drag once past a
  4px threshold, `_SlotWidget.dropEvent` accepts only that MIME type.
  **Dropping onto an occupied slot replaces it unconditionally** — no
  confirm dialog, the palette's "click a new brush, it replaces the armed
  one" precedent. An already-placed browse card is **disabled**
  (`setEnabled(False)`) rather than left draggable — Qt cannot start a drag
  from a disabled widget, which is what keeps a duplicate placement from
  ever being staged (the alternative, catching it only at Save time via
  `validate_uniqueness`, was rejected as worse UX).
- **Icons are real engine frames** via the SAME injected `viewport.
  slot_qimage` provider `editor/panels/palette.py` uses
  (`editor/main.py`: `self.timeline.set_icon_provider(self.viewport.
  slot_qimage)`) — never hand-drawn art (ED-22).
- **The graph is a hand-rolled `QPainter` strip** (`_TimelineGraph`), which
  does NOT violate ED-22 — the `sheet_preview.py` precedent already
  established that QPainter drawing non-game-content editor chrome (there, a
  raw imported PNG; here, a schedule/curve visualization) is a different
  thing from a second renderer of GAME content. It draws the round axis, the
  raw cumulative-XP curve line, and a tick + label per `village_level` at its
  computed best-case round (`editor/timeline_curve.py::best_case_curve`),
  plus an always-visible "best-case / upper-bound" caption. A "View max
  round" spinbox (default 50) is the zoom control — not full mouse-wheel/
  drag pan, a deliberate scope simplification.
- **The curve is computed ONCE per panel load/view-max change, not on every
  Timeline edit** — a correction made mid-implementation to an earlier
  planning assumption: the best-case curve depends only on `core.json`/
  `enemies.json` (which this panel never writes), never on
  `progression.json`'s own slot assignments, so recomputing it after every
  drag would just repeat the same result.
- **`editor/timeline_ops.py`'s `load_building_catalog`** is the browse
  list's data source — reads `data/balancing/buildings.json`'s
  `building_type`/`card_slots` fields (TimelinePLAN T1), walking whatever
  groups carry a `building_type` key rather than a hardcoded family list, so
  a new `/add-building` type needs no editor change here. Tier index 0 is
  always the `"unlock"` card; indices 1/2 are `"tier"` cards.
- **Two toolbar checkboxes flip what the whole panel MEANS** (designer-scripted
  leveling), each with an `_InfoButton` in the house style, both staged like
  every other edit and both defaulting OFF — with both off the panel looks and
  behaves exactly as the bullets above describe. They are seeded from the
  loaded doc with `blockSignals(True)` around `setChecked`, the
  `balancing.py` "populate, then connect" rule: filling the form must never
  dirty it. The tutorial panel's root-level `skippable`/
  `first_loss_costs_life` booleans are the shape being copied.
  - **Scripted leveling** (`Timeline.scripted_leveling`) — the designer
    authors WHEN each level is reached. `_LevelRow.set_level` swaps its
    read-only `"Level N — best-case round ~R"` header for an editable
    `_NoWheelSpinBox` (0–1000) bound to that row's `round`, **hidden for level
    1** (the run starts there, so its round is never read); `_TimelineGraph`
    ticks the AUTHORED schedule instead of the computed crossings (a new
    `set_ticks`, separate from `set_curve` — the curve depends only on
    core/enemies balancing and still never recomputes on a Timeline edit,
    but the ticks move on every round edit); and the caption swaps to
    "authored schedule" wording. The spinbox is built ONCE in
    `_LevelRow.__init__` and only shown/hidden, and `set_level_round`
    deliberately does NOT rebuild the row — rebuilding would destroy the
    widget the designer is typing into, which is why this one staged edit
    breaks the panel's otherwise-universal "the row rebuilds" convention.
  - **Exact offer slots** (`Timeline.exact_offer_slots`) — a row becomes the
    literal card set, so duplicate placements are intended and
    `_refresh_placed_state` **stops greying placed browse cards**. That
    greying only ever existed to prevent a duplicate that
    `validate_uniqueness` would reject at Save, and that check is off in this
    mode — the two must be turned off together or the panel would forbid
    through the UI what the writer happily accepts.
- **Round-schedule problems WARN, they never block** (user decision).
  `timeline_ops.round_warnings(doc)` returns human-readable strings for
  duplicate rounds, a level not scheduled after the one before it, and rows
  wider than `MAX_SLOTS_PER_LEVEL` (4 — above that the game's level-up window
  overflows its 640px view); `village_level` 1 is skipped in the round checks
  since its round is unused. They surface in a non-blocking label under the
  toolbar, refreshed by `_refresh_mode_labels` after every mutation, and
  `save_progression` deliberately does NOT consult them — Save stays enabled.
  This is the opposite stance from `validate_uniqueness`, which still RAISES:
  a duplicate `village_level` is ambiguous, a clumsy schedule is just clumsy.
- **Testing note**: a real OS-level drag gesture cannot be reliably
  synthesized under an offscreen `QApplication`. `test_timeline_panel.py`
  drives the panel's own mutation methods directly for most coverage, plus
  ONE test constructing a real `QMimeData` and calling `_SlotWidget.
  dropEvent` directly — the standard Qt-test workaround, exercising the
  actual drop-handling code path rather than only the method it delegates to.
  Its cases **pin the fixture by emptying `_doc["Timeline"]["levels"]`**
  before authoring: they count rows and slots, and reading whatever schedule
  ships today is the exact "never assert against live `data/` content" trap
  the Testing section above describes (two of them had already gone red that
  way).

## Boss Upgrade Timeline panel (`panels/boss_upgrades.py`, `boss_upgrades_ops.py`; BossUpgradeTimelinePLAN BU-5)
The Timeline panel's sibling one document over (`data/balancing/
boss_upgrades.json`): a browse list of the 12 boss-upgrade cards on the left,
a 4×3 milestone grid on the right, staged edits through the pure
`editor/boss_upgrades_ops.py`, ONE "Save Boss Upgrades" button as the sole
`write_validated` call site. The Timeline bullets above describe the DROP side
verbatim (a custom MIME type — here `application/x-htbh-boss-upgrade` carrying
the bare upgrade id — `_SlotWidget.dropEvent` accepting only that type, and a
drop onto an occupied slot replacing it with no confirmation, D10); the drag
SOURCE differs, and so do five other things:
- **Selection is a TOP-LEVEL "Bosses" branch (D11)**, not a leaf under a
  category — `boss_upgrades` is deliberately not a `slots.json` category (the
  `progression` precedent), and a boss upgrade is not a building. So its
  single leaf emits `boss_upgrades_selected()` **alone**: never
  `node_selected` (the single-document-leaf rule) and, unlike Timeline's
  `domain_selected("buildings")`, never `domain_selected` either — there is
  no `bosses` domain to gate one on (the Master Sheets argument). Its payload
  `category_key` is the placeholder `"bosses"`, which matches no registry
  category, so `domains()`/`refresh_markers()` skip it with no special case.
  It is added outside the category loop, immediately BEFORE the Master Sheets
  item, which stays the LAST top-level item. `right_stack` index 9.
- **The CATALOG is inline-editable — this panel's one new capability.** A
  building card's title comes from `buildings.json`; a boss upgrade's `name`/
  `description`/`params` are this document's own designer content, so each
  browse card carries a `QLineEdit` per text field (commit on
  `editingFinished`) and one spin per param (commit on `valueChanged`) — the
  `balancing.py` signal convention, and its `_NoWheel*` widgets, imported not
  copied. **Which spin, and its range, come from the SCHEMA** via
  `boss_upgrades_ops.catalog_param_specs` (ED-30): an `integer` param gets a
  `_NoWheelSpinBox`, a `number` one a `_NoWheelDoubleSpinBox`, and
  `set_catalog_field` additionally coerces to the type already in the doc, so
  an int param can never be staged as a float that fails the schema at Save.
  A card edit deliberately does NOT rebuild the card (that would destroy the
  widget being typed into — `set_level_round`'s rule); only the milestone
  slots, which display the name, refresh.
- **The drag source is a dedicated `_DragHandle` widget, not the card** — a
  fixed-width `⠿⠿⠿` grip to the LEFT of every browse card, whose OWN
  `mousePressEvent`/`mouseMoveEvent` start the `QDrag`. The Timeline panel
  starts its drag from `_BrowseCard`'s own `mousePressEvent` and gets away
  with it only because an icon plus a read-only caption cover a small
  fraction of that card; here inline-editable `QLineEdit`s and spins cover
  nearly all of it. **A child widget does NOT forward an unhandled mouse
  press to its parent** — Qt auto-propagates only a handful of event types
  that way (wheel, context-menu), and mouse press/move are not among them.
  This panel originally shipped a "drag the header `QLabel`" design built on
  that false assumption, with a doc comment asserting the propagation; it
  silently never worked, and the fix was a widget that IS the drag source
  rather than one relying on bubbling. Do not "simplify" it back.
- **A placed card stays draggable.** Timeline DISABLES an already-placed
  browse card because a duplicate there is a Save-time `ValueError`. Here the
  roster is a fixed 12 and moving an upgrade between milestones is the normal
  gesture, so a placed card is MARKED ("in milestone 2 · slot 1") instead, and
  a real double-placement surfaces in the warning label under the toolbar.
- **`validate_uniqueness` WARNS, it never blocks** — it returns the list of
  double-placed ids and `save_boss_upgrades` deliberately ignores it (D3, the
  `round_warnings` stance, the opposite of `timeline_ops.validate_uniqueness`).
  Blocking Save would trap a designer halfway through moving a card between
  two milestones, which is exactly the state silent overwrite exists to allow.
- **Text-only, no icons (D9)**: no `set_icon_provider`, no `slot_qimage`, no
  art path anywhere in this panel — do not add one.

## Master-sheet dialog (`panels/master_sheet_dialog.py`, `master_sheet_import.py`; GpuAndMasterSheetsPLAN M3)
- **What a master sheet is**: ONE committed PNG under `data/sprites/master/`
  holding many characters' rows stacked in one grid, registered in
  `data/sprites/master_sheets.json`. It is NOT a `slots.json` slot — never
  previewed, animated or rendered on its own. A manifest entry links to one by
  pointing its `sheet` at `master/<id>.png` plus a `row_start` window.
- **The REGISTRY owns the grid (D3)**, so `MasterSheet.grid()` takes no frame
  size and there is no `fits()` filter: a linking slot inherits `frame_w`/
  `frame_h` and may not override them. This is the one real divergence from
  `asset_import.ImportedSheet`.
- **Two branches, one dialog**: "Import new master spritesheet…" (file chooser +
  display name + frame size, all collected BEFORE any write; the spin ranges are
  READ FROM `master_sheets.schema.json` via `master_sheet_import.frame_bounds`,
  never retyped — ED-30) and "Use existing…" (the whole registry, filtered, with
  a read-only `SheetPreview` at each sheet's own declared frame size).
  `chosen()` is the selected sheet ID, not the dataclass.
- **Construction is split from display** — the `sheet_picker.py` rule.
  `__init__` builds and fills; `visible_sheets()`/`chosen()`/`select_sheet()`/
  `set_import_source()`/`perform_import()` are the model, so no test `exec()`s a
  modal and `QFileDialog` is confined to `_on_browse_clicked`.
- **The dialog never writes** — `editor/master_sheet_import.py` owns the one
  `write_validated` path for this file (ED-31), and its `sheet_users` refcount is
  `asset_import`'s, not a second one.
- **`DetailsPanel` constructs it since M4 and `VfxPreviewPanel` since M5**
  (both `_on_master_clicked`, D5). Construction split from display still holds
  — tests drive `DetailsPanel.use_master_sheet` /
  `VfxPreviewPanel.use_master_sheet` directly. The vfx panel's variant is
  single-row (one spin, no Save button); its rules live in the VFX-preview
  section of `editor/CLAUDE.md`.
- **Import is uniquify-never-overwrite**: a colliding display name yields
  `<slug>_2`, because overwriting `master/characters.png` would silently
  re-point every slot already cutting it. Re-importing the SAME bytes reuses the
  id, leaves the PNG untouched and rewrites the entry (so a wrong grid is
  correctable) — **the byte-identity check scans the whole slug FAMILY**
  (`slug`, `slug_2`, `slug_3`, … in id order), so re-importing `characters_2`'s
  own bytes returns `characters_2` instead of minting a third identical
  `characters_3`. Deliberately scoped to the family, not the whole registry: a
  registry-wide scan would also collapse the same PNG imported under an
  unrelated display name, a different behaviour change.
- **M4 answered "must a re-import refuse a changed grid once the sheet has
  users?" — YES.** `master_sheet_import.GridInUseError` (a **`ValueError`
  subclass**, so `master_sheet_dialog._on_import_clicked`'s existing
  `except (OSError, ValueError)` shows it as a warning with no dialog edit) is
  raised when the resolved id already exists with a different `frame_w`/
  `frame_h` AND `asset_import.sheet_users` is non-empty; the message names the
  users. It is raised **before the PNG copy and before the registry write**, so
  a refused import leaves disk byte-identical. **Zero users still rewrites** —
  nothing can be mis-cut when nothing links, and that is the "correct a wrong
  frame_w" flow M3 documented.

### DetailsPanel ▸ master sheets (M4: the button, the row window, the narrowing)
- **A third button, "Use Master Spritesheet…"**, beside Import / Use / Save /
  Clear, `clicked.connect`-**wrapped in a lambda** like `_use_btn`/`_clear_btn`
  (the `clicked(bool checked)` footgun). Construction is split from display;
  `use_master_sheet(sheet, row_start=None, row_count=None)` is the model half
  and takes a `MasterSheet`, its id, or its stored ref.
- **The entry's `sheet` is the registry entry's STORED `file`, verbatim** —
  never a re-derived `master/<id>.png` (`master_sheet_import.master_ref`'s
  docstring). Nothing is copied, exactly like "Use Spritesheet…".
- **The sheet owns the grid (D3)**: `frame_w`/`frame_h` are inherited into
  `_row_frame_size` and the saved entry, and the Frame W/H spins go **disabled
  with a tooltip**. This **bypasses `_on_frame_size_changed` on purpose** —
  that method writes a per-slot `slots.json` override and re-saves, and a
  master sheet's grid is not a per-slot override. `slots.json` must not be
  touched on this path. `_effective_frame_size()` is the ONE place the
  master-vs-registry choice is made.
- **`_master_applies()`** is the `_slice_applies()`/`_tint_applies()` idiom with
  one difference: it tests the current **`_sheet_ref`** (does it start with
  `master/`), not the category — any category may cut a master sheet.
- **The `Using rows [a] til [b]` row** is built exactly like the Frame W/H row
  (`_NoWheelSpinBox` imported from `balancing.py`, commit on `editingFinished`)
  and is visible only while `_master_applies()`. `a > b` is unrepresentable
  (ED-30): `_row_from.valueChanged` drives `_row_to.setMinimum`. **`til` is
  derived, never stored** — the saved window is `row_start` + `len(rows)` (D2).
- **`_load_sheet` builds one RowEditor per row IN THE WINDOW**; row 0 of the
  WINDOW stays idle-locked, so E-35 stays unrepresentable rather than becoming
  a save-time error. Changing the window re-cuts and rebuilds but **writes
  nothing** (unlike `_on_frame_size_changed`'s two-file write) — it is entry
  state, saved by Save.
- **`row_start` is optional-key-shaped like `slice`/`tint_overlay`**: omitted at
  0, so every non-master entry stays byte-identical; and `draft_entry()`
  PRESERVES an existing `row_start` on any path that does not author a window —
  the `anchors` argument in reverse.
- **Clear never unlinks a `master/` ref.** The existing refcount
  (`asset_import.unreferenced_sheets`) already protects a master sheet other
  slots still use — that part needed no change — but the last user going away
  would have deleted committed library art and stranded its registry entry
  pointing at a vanished PNG. **Orphans are legal (§9)**, so `clear_entry`
  skips the `master/` prefix outright.

- **`sheet_preview.SheetPreview`'s row window is OPT-IN and defaults to the
  whole sheet**: `set_sheet(png, fw, fh, row_start=0, row_count=None)`, so
  every three-argument caller paints byte-identically to before (and a
  three-argument call RESETS a previously set window). Everything the widget
  emits and paints is **ENTRY-RELATIVE** — the first visible row is `0` for
  `frame_clicked`, `set_rows` and the grid — and the window is applied in
  exactly ONE place, the source rectangle in `paintEvent`, mirroring the
  engine's rule that `AssetStore._frame_surface` is the only place `row_start`
  is applied. That is why `DetailsPanel._on_frame_clicked` needs no offset.

- **The column window is the row window's twin (E2)**: `set_sheet(png, fw, fh,
  row_start=0, row_count=None, col_start=0, col_count=None)` — same
  opt-in/reset/clamp rules, applied in the SAME source-rectangle line in
  `paintEvent`, and `column_window()` sits beside `row_window()`. Cell captions
  and `frame_clicked(row, col)` stay WINDOW-RELATIVE on BOTH axes now, not just
  rows — the preview and the RowEditors below it must not be able to disagree
  about what "frame 1" means on either axis.

### E1 — import path: column width + column names (MasterSheetColumnsPLAN)
- **The import form collects the real designer-supplied `column_width`** plus an
  optional comma-separated **Colours** field, replacing S1/C3's stopgap
  derivation from the PNG's pixel width (deleted, not left as a second path):
  `import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h,
  column_width, columns=())`. `columns` is OMITTED from the entry when empty
  (the `slice`/`tint_overlay`/`row_start` convention) and is NOT preserved
  across a re-import that omits it — the same way `frame_w`/`frame_h` are never
  seeded from the existing entry either.
- **`GridInUseError`'s comparison tuple is `(frame_w, frame_h, column_width)`**
  (D10): a re-import changing only `column_width` on a sheet with users is
  refused exactly like a frame-size change, with the same ordering (before the
  PNG copy, before the registry write), and it still subclasses `ValueError` so
  the dialog's existing `except (OSError, ValueError)` shows it.
- **`master_sheet_import.parse_columns(text, data_dir)`** is the pure
  slugify+validate step the Colours field runs through BEFORE any write: each
  entry is slugified with the same `_slugify` sheet ids use (so the schema's
  `^[a-z][a-z0-9_]*$` item pattern holds by construction, ED-30), blanks are
  dropped, and a duplicate slug / over-length slug / over-cap count raises
  `ValueError` there rather than as an opaque `ValidationError` after the copy.
  Its bounds come from `columns_bounds()`, read off the schema.
- **`MasterSheet.column_count()` is a NEW method, not a third `grid()` return
  value** — `grid()` stays a 2-tuple because `panels/vfx_preview.py` and this
  dialog already unpack it as exactly two. `column_count()` is
  `width // (column_width * frame_w)`, matching `engine/assets/store.py`'s own
  column arithmetic.

### E3 — DetailsPanel column controls (MasterSheetColumnsPLAN)
- **The `Column [n] mode [combo] width: [n]` row** sits under the row-window row
  and is built the same way (`_NoWheelSpinBox`/`_NoWheelComboBox` from
  `balancing.py`, spin commits on `editingFinished`, combo on a **lambda-wrapped**
  `currentIndexChanged`). Its visibility gate is the SAME `_master_applies()` —
  the `master/` prefix on `_sheet_ref`, not the category (D2).
- **`_on_column_changed` writes NOTHING** — the column is entry state, saved by
  Save like every other row edit, and `slots.json` is never touched from here.
  It is `_on_row_window_changed`'s twin, not `_on_frame_size_changed`'s. One
  deliberate difference from the row window: it calls `_refresh_preview()` and
  **does not rebuild the RowEditors**, because a column changes which horizontal
  SLICE of the same rows is shown, not which rows exist.
- **`column_width` is INHERITED, displayed disabled with a tooltip** — the exact
  treatment Frame W/H get while a master sheet is linked (a disabled spin, not a
  `QLabel`, so focus order and styling stay uniform). It is read through
  **`engine.assets.master_registry.column_width_for(doc, ref)`**, never off a
  `MasterSheet` attribute: the registry owns the value (D1) and the panel has no
  business reaching into the import module's dataclass for it.
- **The column spin's CEILING is `sheet_cols // column_width - 1`**, recomputed
  per sheet in `_refresh_column_state` from `_sheet_cols` (stored by
  `_load_sheet` beside `_sheet_rows`). An off-sheet column is unrepresentable
  (ED-30) rather than a save-time error — the horizontal twin of `_row_to`'s
  minimum tracking `_row_from`. The clamp is applied to the STATE too, since
  `draft_entry()` reads `_column`.
- **A RowEditor is as wide as the master COLUMN, not as the sheet** (the
  live-testing fix). `_load_sheet` keeps `_sheet_cols` = the sheet's full
  frame-column count (the column spin's ceiling derives from it) but builds
  each `RowEditor` with `min(column_width, cols)` whenever `_master_applies()`
  and `column_width > 0` — so the `frames` count a row SAVES, its hide
  checkboxes and its loop spins all stop at the column boundary. Deriving them
  from the sheet width instead is what wrote a 68-frame idle row against a
  17-frame-wide column: the animation walked out of its colour into the next
  one and, past the last column, off the sheet into the grey X. The info line
  says `… — N/column` when the two differ. `engine/assets/CLAUDE.md` documents
  the engine-side net that now refuses such a frame rather than borrowing the
  neighbour's pixels.
- **`column`/`column_mode`/`column_width` are optional-key-shaped** like
  `slice`/`tint_overlay`/`row_start`: omitted at `0`/`"manual"`/`0`, and
  `draft_entry()` **preserves** all three on any path that does not author them
  (a plain `imported/<slot>.png` entry never shows the row and must not erase a
  saved column). `0` for the width is only the absent-key in-memory default —
  the schema floors an authored width at 1.
- **An entry saved before this phase has no `column_width` key**, so `set_slot`'s
  reload falls back to `column_width_for` rather than leaving the spin with a
  `0..0` ceiling. `_effective_column()` is the one place the preview's column
  origin is derived; the STORED column always wins there, because a non-manual
  `column_mode` names a RENDER-time override the editor has no live value for.

## Master Sheets panel (`panels/master_sheets.py`, MasterSheetColumnsPLAN E5)

- **Shape**: a `right_stack` PAGE (index 8), not a `QDialog` — the
  Timeline/Theme family's shape with the master-sheet dialog's layout: a
  `QListWidget` of every registry entry, an embedded read-only
  `SheetPreview(interactive=False)` showing the WHOLE sheet (the raw registry
  entry, so the three-argument `set_sheet` that resets any row/column window,
  never one slot's window), and a word-wrapped detail label reporting the
  real pixel size, the grid, `column_width`, the column count, the colour names
  and the users by key.
- **Construction is split from display**, the `sheet_picker`/
  `master_sheet_dialog` rule: the model is `sheets`/`selected_sheet`/
  `select_sheet`/`reload_sheets`/`save_selected`/`reimport_selected`, so no
  test `exec()`s anything. `QFileDialog` is confined to
  `_on_reimport_browse_clicked`; `set_reimport_source()` is the same seam
  without the modal.
- **D10 locks the SLICING FORM, not Re-import — and NOT the colour names.**
  With users, the frame_w/frame_h/column_width spins are disabled and a label
  names the linking slots ("Clear them first"); `save_selected()` keeps those
  three stored values verbatim, defense in depth. **`_colours` and Save stay
  ENABLED**, and `save_selected` still writes `columns`: naming a column maps
  an index the art already has to a label, moving no window and re-cutting no
  frame, so D10's argument does not reach it. Locking it with the slicing
  values made a colour-capable sheet undeclarable the moment its first slot
  linked — and since D6 gates the building-colour swatches on a non-empty
  `columns`, that made the swatches unreachable in both screens with no
  recovery but clearing every linking slot. `_slicing_widgets()` is therefore
  the three spins ONLY; do not put the colours field or Save back into it. Re-import stays enabled at all times on purpose:
  the ENFORCEMENT is `GridInUseError` inside `import_master_sheet`, which
  refuses a grid change on a linked sheet with a message naming the slots
  before touching the PNG or the registry — a UI lock there would hide the
  reason instead of stating it. `GridInUseError` subclasses `ValueError`, so
  `_on_reimport_clicked`'s `except (OSError, ValueError)` → `QMessageBox`
  shows it (the `master_sheet_dialog._on_import_clicked` precedent).
- **Re-import passes `sheet_id=` and that is deliberate.** Going through
  `resolve_sheet_id` — as the picker's import branch does, correctly — would
  mint `<slug>_2` the moment the new art's bytes differ, leaving every manifest
  entry pointed at the stale sheet: the exact opposite of this panel's promise
  ("keeps the id and every link"). The explicit id is safe because the designer
  selected that sheet and asked for the replacement, and the slicing hazard is
  still covered by the untouched D10 guard.
- **One refcount.** `MasterSheet.users` (`asset_import.sheet_users`) is it —
  the panel never counts users a second way.

## TestRunnerPLAN TR-5 — `panels/test_run_panel.py` (the test-run window)

- **A POPUP WINDOW, not a dock** (reconciliation R3): `TestRunPanel` copies
  `editor/thats_my_producer.py`'s shape — parented to the `MainWindow` (so it
  dies with it), given `Qt.WindowType.Window` so it floats as its own non-modal
  top-level window, with the shell holding the one reference
  (`MainWindow.test_run_panel`). The editor stays usable while a run goes. Its
  launch control is the "Run tests" toolbar button right after "thats my prod".
- **A PURE VIEW. All threading lives in `main.py`** (see `editor/CLAUDE.md` —
  this is the package's first `QThread`). The panel has no subprocess, no
  stream parsing, no pytest vocabulary: it renders the `(domain, done, total,
  state)` tuples TR-3 hands it and emits `run_requested(domain|None)`. That is
  what lets its tests drive it synchronously from canned tuples — **no test in
  the suite may launch a real test run.**
- **The row list is DERIVED, never hardcoded**: `tools.test_domains.
  DOMAIN_LABELS` in insertion order IS the row order (eight rows, "Tooling &
  Agents" last). Same doctrine that killed the editor's `DOMAINS` constant. A
  domain key with no row is **appended**, never dropped — a stray test module
  that vanishes from the panel looks exactly like success.
- **`total` may be `None`** (a full run has no up-front count), so the count
  label counts UP — `"N run"`, not a fraction. It says "run", not "passed",
  because TR-3's `done` is passed+failed+subfailed+skipped.
- **Row buttons carry `objectName` `rerun:<domain>`**, the panel's existing
  row-button convention, so a test asserts *which* rows are re-runnable without
  walking the layout by index. Disabled while a run is in flight.
- **A per-area re-run NEVER prints a gate line** (plan D2). `RunResult.
  gate_line` is already `None` for one; the panel shows the neutral
  `"<label>: n passed, m failed (re-run, not a gate)"` and never writes the
  token `GATE` itself.
- **Injection seams, each so a test touches nothing real**: `repo` (where
  `.claude/testruns/` is), `state_dir` (the guard's directory — a test writes a
  FAKE `inflight.json` into a tempdir), `detach` (so *Open report folder* is
  captured as argv and no explorer opens; `plans.reveal_command` stays the ONE
  folder-open path), `copy_fn` (so *Copy agent prompt* needs no clipboard),
  `confirm` (so the in-flight warning never `exec()`s a modal).
- **D5 — the in-flight warning WARNS AND ALLOWS.** `inflight_lock()` reads
  `testguard_ledger.state_dir()/"inflight.json"` (resolved lazily, never
  re-derived, and the hook is never imported — `.claude/hooks/` is not a
  package). Missing, corrupt or past `LOCK_STALE_SECONDS` → "nothing running".
  The dialog names what is running, when the guard's block clears and the
  memory contention; Yes still starts the run. **The panel takes no lock and
  deletes nothing under that directory.** One test asserts the lock file is
  byte-identical afterwards, another that the filename constant still appears
  in the hook's text.
- ED-22: stock widgets only — no `paintEvent`, no `QPainter`, no
  `pygame.Surface`, no `Renderer`. It draws no game content, so it needs
  neither the `sheet_preview`/`vfx_preview` exception nor its argument.

## Verify
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it. State
exactly what you exercised (live editor run vs static read). Live runs are driven
by synthetic `QTest` events.
