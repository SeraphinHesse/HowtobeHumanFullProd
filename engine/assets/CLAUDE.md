# CLAUDE.md — engine/assets

Data-driven slot registry, manifest v2 loader, `playback_order` row semantics
(rows = animations, row 0 = idle), grey-X placeholder (E-33..E-38). You reached
here from `engine/CLAUDE.md`. **Missing/corrupt art logs and falls back — never
crashes boot.** When you change asset conventions, update THIS doc.

## Import boundary
`engine.assets` package `__init__` + `types` + `manifest` + `registry` +
`master_registry` + `nine_slice` are **pure**; pygame lives only in
`engine.assets.placeholder` and
`engine.assets.store` (import those by full path).

## Phase 5 conventions
- **Module split**: `manifest.py` (pure) holds `playback_order`/`parse_loop` —
  PROTOTYPE-EXACT semantics (rows = animations, row 0 = idle required,
  fps→`max(1, round(1000/fps))` ms, loop = pre-roll + range×count + post-roll,
  hidden dropped AFTER expansion) — plus `Track`/`ManifestEntry`/`Manifest`/
  `entry_from_dict`/`load_manifest`. `registry.py` (pure) loads `data/slots.json`
  into `SlotRegistry` (E-34). `store.py` (pygame) does sheet loading + subsurface
  slicing.
- **E-36**: `Manifest.current_frame(slot, animation, time_ms, phase_ms=0)` is a
  pure function of time → `(sheet_row, sheet_col)` or the `PLACEHOLDER` sentinel
  (`types.py`; compare with `is`). Missing animation falls back to the idle row;
  missing slot / no usable idle → PLACEHOLDER. Note `SpriteAnimator` sums
  `phase_ms` into `anim_time_ms` at emit, so the store's `frame(slot, animation,
  anim_time_ms)` takes ONE summed time.
- **`Manifest.current_frame(..., extra_hidden=None)` (feature-enemy-intro-dialogue)**
  — an optional caller-supplied set/iterable of frame-COLUMN indices to skip
  IN ADDITION to whatever the resolved track's own `hidden` list already
  dropped at parse time. It is a per-CALL narrowing, never a widening: a
  column the manifest row already hid stays hidden regardless of
  `extra_hidden`. If filtering would drop every remaining frame, the
  UNFILTERED timeline is used instead (never resolves to nothing — the same
  degrade-don't-crash contract every other engine seam here uses).
  `AssetStore.frame(..., extra_hidden=None)` passes it straight through.
  Threaded end-to-end for `HudSprite.hidden_frames` only (`engine/render/
  CLAUDE.md`) — not for `RenderItem`/world sprites, which carry no matching
  field.
- **`Manifest.animation_ms(slot, name)`** (+ `AssetStore.animation_total_ms`
  delegating) returns a named track's `total_ms`, or `None` when the slot or that
  animation is absent — **no idle fallback** (unlike `current_frame`), because the
  caller uses absence as a signal (the game's death animation: no `death` row ⇒
  no corpse, despawn instantly). See `game/enemies/CLAUDE.md` "Corpse".
- **Tolerance split (E-37)**: `load_manifest` NEVER raises — absent file → empty
  manifest (normal pre-import state); corrupt file → warn + empty; corrupt entry →
  warn + skip that entry. `load_registry` fails LOUD (the registry is
  infrastructure, like geometry.json). `tools/smoke.py` still fails loud on an
  invalid COMMITTED manifest — separate concern.
- **Per-slot frame size (ER-1, D1)**: a `data/slots.json` group's `slots[]` entry
  is EITHER a bare key string (inherits the category's `frame_w`/`frame_h`) or an
  object `{key, frame_w, frame_h}` that overrides it. `SlotRegistry.frame_size`
  returns the override when present, else the category size. **Slicing is not
  drawing**: this says how the SHEET is cut into frames — how big the thing draws
  is the renderer's `fit_tiles`/`scale` (see `engine/render/CLAUDE.md`).
  - The object form is **normalised away at parse time**: `GroupNode.slots` stays
    a tuple of key STRINGS everywhere downstream (editor tree, palette, the game's
    variant roll). It must never leak.
  - **Fail-loud cross-check** the schema cannot express (`uniqueItems` compares
    whole values, so a bare `"foo"` and a `{"key": "foo", …}` are two distinct
    items): a key repeated across groups of one category must AGREE on its frame
    size — two different overrides, or once bare and once overridden, raises
    `ValueError` at load (same pattern as the "slot in two categories" check).
- **Optional `slice` (A2)**: a manifest entry may carry
  `slice: [left, top, right, bottom]` — nine-slice margins in FRAME pixels (same
  convention as `offset_x`/`offset_y`), ints ≥ 0. `entry_from_dict` parses it to a
  4-tuple and **raises** on anything else (wrong length, negative, non-numeric, a
  bare string) — `load_manifest` is the E-37 layer that turns that into warn+skip.
  It rides `ManifestEntry → Frame → DrawCall` uninterpreted; only
  `engine/render/backend.py` gives it geometry, and only for **HUD sprites**
  (world sprites keep uniform zoom scaling). Omitted ⇒ plain scale. The grey-X
  placeholder deliberately never carries one. See `engine/render/CLAUDE.md`.
- **Optional `anchors` (ESV-1)**: the SECOND optional per-entry key, beside
  `slice`. A manifest entry may carry `anchors: {muzzle?, impact?, hp_bar?,
  floater_origin?, status_icon?, beam_endpoint?}` — six declared names, all
  optional, each a `[x, y]` frame-px point relative to the sprite anchor (same
  convention as `offset_x`/`offset_y`: `+x` right, `-y` up), measured on the
  sheet frame at frame resolution, never at draw resolution or a zoom (D2).
  `entry_from_dict` parses it to a `ManifestEntry.anchors` tuple of
  `(name, (x, y))` pairs (never a mutable dict on the frozen dataclass) and
  **raises** on a bare string, a non-2-length value, a non-integer, or an
  undeclared name — same defensive shape as `slice`, and `load_manifest` is
  again the E-37 layer turning that into warn-and-skip-this-entry.
  `ManifestEntry.anchor(name)` / `AssetStore.anchor(slot_key, name)` are the
  read accessors (never index the raw structure). Unlike `slice`, anchors are
  **metadata, not frame geometry** — they never touch `Frame`/`frame()`/the
  blit path; `muzzle` (`game/enemies/combat.py` firing points,
  `game/ui/effects.py watch_enemies`), `impact` (`game/ui/effects.py
  watch_buildings`/`spawn_projectile_hit_events`) and `hp_bar`
  (`game/ui/effects.py` overhead bars, "anchor wins outright") are wired to
  a read-site today, all through `game/anchors.py`'s single resolver,
  `anchor_world_point` (below). `floater_origin`/`status_icon`/
  `beam_endpoint` remain declared and parse-ready but inert (no read-site) —
  shipped now so their future wiring needs no schema migration.
  - **`AssetStore.offset(slot_key)`** (the anchor/offset composition fix,
    `docs/briefs/fix-anchor-offset-and-bullet-sprites.md`) mirrors `anchor()`
    exactly: `(x, y)` ints from the manifest entry's `offset_x`/`offset_y`, or
    `(0, 0)` when the slot or its entry is absent — same degrade-never-raise
    contract. **fix-anchor-origin-parity** replaced the old
    `screen_offset`/`world_offset` delta pair with ONE absolute-world-point
    resolver, `game/anchors.py`'s `anchor_world_point` — it composes this
    `offset()` and `anchor()` through `engine.render.sprite_anchor_screen`,
    the exact placement math `Renderer.flush` draws with (`block_center_
    offset` + `fit_factor` + the tile-diamond-centre convention), so the
    resolved point IS the sprite's drawn anchor, never a delta added to a
    base point that could disagree with it. `editor/panels/viewport.py`'s
    `_anchor_draw_params` calls the SAME `sprite_anchor_screen` for the
    editor's handle, so the two consumers of "where is this sprite's anchor
    point" cannot drift apart again.
- **Optional `tint_overlay` (bool)**: the THIRD optional per-entry key (after
  `slice` and `anchors`), added the same way as `slice` and equally
  uninterpreted here — a render HINT for the
  consumer, meaning "keep drawing your own flat colour overlay UNDER this art
  instead of letting the sprite stand alone". `entry_from_dict` parses it
  (non-bool raises → `load_manifest`'s E-37 warn+skip); omitted ⇒ `False` ⇒ the
  entry is byte-identical to a pre-feature one. Its ONE consumer today is the
  game's tile-condition art (`data/slots.json` `conditions` category): a
  condition slot with **no entry at all** always draws the overlay, because
  there is no sprite to draw instead. See `game/map/CLAUDE.md`.
- **Optional `row_start` (M2, GpuAndMasterSheetsPLAN)**: the FOURTH optional
  per-entry key — a 0-based index of the first SHEET row this entry's `rows[]`
  maps onto, so many slots can each claim their own band of one shared MASTER
  spritesheet (`master/<sheet_id>.png`, registered in
  `data/sprites/master_sheets.json`). `entry_from_dict` parses it with the same
  defensive shape as `slice`/`anchors` — **no `int()` coercion**, so a bool, a
  float, a numeric string or a negative all RAISE (`load_manifest` is the E-37
  layer that turns that into warn-and-skip-this-entry); omitted ⇒ `0` ⇒ the
  entry is byte-identical to a pre-feature one.
  - **It is a SLICING concern, never a playback one.** `AssetStore.
    _frame_surface` is the ONE place the window is applied (`sheet_row = row +
    entry.row_start`); `Track.row`, `playback_order` and `current_frame` keep
    meaning "row *i* of THIS entry's `rows[]`". Leaking the offset upward would
    touch the prototype-exact animation semantics for nothing.
  - A window running past the sheet's real rows degrades to the grey-X
    placeholder with a warning naming the resolved sheet row — never raises
    (E-37), the same path an off-sheet column already took.
- **Optional `column` / `column_mode` / `column_width` (D1/D2/D3/D12,
  MasterSheetColumnsPLAN)**: the FIFTH-through-SEVENTH optional per-entry
  keys, the horizontal twin of `row_start`. `column` is the 0-based master
  COLUMN this entry cuts from; `column_width` is how many frame-columns one
  master column spans, **measured in FRAMES, not pixels** (D1) — a raw pixel
  width can disagree with `frame_w` and produce a column boundary mid-frame;
  `column_mode` declares WHO picks the live column (`"manual"`, or a key
  absent, means the stored `column` wins; any other value means a caller-
  supplied column wins, falling back to the stored `column` when the caller
  supplies none). Columns are **master-sheet-only** (D2) — a plain
  `imported/<slot>.png` entry has no column concept, exactly the scope rule
  `row_start` already follows. `entry_from_dict` parses all three with the
  same defensive shape as `row_start` — no `int()` coercion, so a bool, a
  float, a numeric string or a negative all RAISE for `column`; `column_mode`
  raises on anything outside its enum — and `load_manifest` is again the E-37
  layer turning any of those raises into warn-and-skip-this-entry. Omitted
  `column`/`column_mode` ⇒ `0`/`"manual"`; omitted `column_width` ⇒ `0` ⇒
  `block * 0 + col == col` ⇒ the entry is **byte-identical** to a
  pre-column entry, the same "optional by omission" convention `slice`,
  `tint_overlay` and `row_start` already follow.
  - **D12 — the engine never learns what a season or a colour is.** It only
    ever distinguishes `manual` from not-manual; the enum's values live in
    `data/schemas/asset_manifest.schema.json` and their MEANING lives in
    `game/` and `editor/` — the same line `engine/vfx/` holds against
    balancing key names.
  - **It is a SLICING concern, never a playback one**, same as `row_start`:
    `AssetStore._frame_surface`'s rect is the ONE place the column window is
    applied (alongside the row window); `Track.row`, `playback_order` and
    `current_frame` keep meaning "row *i* / frame *j* of THIS entry's own
    `rows[]`".
  - **The clamp is per-sheet and never wraps (D7).** The resolved block
    clamps to the sheet's real column count (`sheet.get_width() //
    (column_width * frame_w)`); a rect that still lands off the sheet after
    the clamp degrades to the grey-X placeholder with a warning naming the
    resolved block, never raises (E-37) — the same path an off-sheet row
    already takes.
  - **A ROW MAY NOT OUT-RUN ITS COLUMN, and `_frame_surface` enforces it.**
    A master column spans exactly `column_width` frame-columns (D1), so a
    column-sliced entry's frame index must satisfy `col < column_width`;
    `col >= column_width` degrades to the grey X with one warning, exactly
    like an off-sheet row. It cannot fire for a pre-column entry
    (`column_width` is 0 there, and the guard is gated on `> 0`).
    **Without it the rect simply walked into the NEXT column** and returned
    another colour's/season's pixels as if they were this one — the same
    "silently wrong pixels" class the 4-tuple cache key guards on the other
    axis, and a real shipped bug: the editor derived a row's `frames` from the
    whole sheet width, so a 68-frame idle row sat in a 17-frame column,
    rotated through all four colours and then ran off the sheet. The authoring
    half of that fix is in `editor/panels/CLAUDE.md`; this guard is the net
    under it, and it is why a mis-authored `frames` count now announces itself
    instead of looking like a carousel.
  - **`_frames`/`_hit_masks` gain the resolved block in their cache key**
    (`(slot_key, row, col, block)`, up from `(slot_key, row, col)`): two
    different columns of one slot must resolve to two DIFFERENT surfaces, or
    the cache would silently hand column 2 the pixels of column 0 forever —
    the same collision class D10 already guards against for sheet-keyed
    frames. There is a comment in `AssetStore.__init__` saying so; do not
    "simplify" it back to a 3-tuple.
- **Store**: `AssetStore(manifest, registry, frame_sizes, default_frame_size,
  sprites_dir)`; frame-size precedence manifest entry > registry (**per-slot
  override, then category**) > frame_sizes > default. Sheets load via `pygame.image.load` with NO
  `convert()`/`convert_alpha()` (they need a display; the editor runs SDL dummy).
  **`_sheets` is keyed by the entry's `sheet` PATH, not by slot key (M2)** — one
  PNG decodes exactly once into exactly one Surface however many slots name it
  (linked sheets and master sheets both). `_frames`/`_hit_masks` stay
  SLOT-keyed on purpose (**D10**): a shared sheet's slots resolve different
  pixels for the same `(row, col)`, because each applies its own `row_start`
  **and** may declare its own `frame_w`/`frame_h`. Only the raw Surface is safe
  to share; deduping frames too would mean folding the grid and the window into
  the key, which is a noted follow-up and deliberately not done. There is a
  comment in `__init__` saying so; do not "fix" it. **The key is now a 4-tuple
  carrying the RESOLVED column block** (MasterSheetColumnsPLAN): the slot stays
  in it for the reason above, and the block joins it because a live column can
  make ONE slot resolve different pixels for the same `(row, col)` — two
  columns of the same slot are two different surfaces, so the block has to be
  part of what identifies a cached frame. A failing shared sheet is
  also logged once, naming only the first slot that asked for it — accepted, the
  resolved path is the actionable half.
  Sliced frames are SUBSURFACES — the parent sheet must stay cached. There is no
  cache invalidation: when the manifest changes, build a new AssetStore (the
  editor's `reload_assets()` does exactly that).
- **`AssetStore.registry` (VfxAuthoringPLAN VA-2)** — a read-only property
  exposing the `SlotRegistry` the store already holds for frame sizes, `None`
  when constructed without one (test dummies). Added because a caller holding
  a store to ask "does this slot have art?" (`animation_total_ms`) often also
  needs "which slots are interchangeable with it?", which is registry
  structure — `game/ui/effects.py`'s trigger dispatch is the first. The
  alternative was every such caller reaching into `_registry`, or the host
  wiring the registry a second time alongside the store it is already inside.
  Callers that duck-type a stub store must still read it with `getattr(...,
  "registry", None)`: `FloaterManager.assets` is a host-wired handle tests
  stub with far less than a real store.
- **Pixel hit-mask (A8, R2 design)**: `engine/assets/nine_slice.py` (NEW, pure —
  no pygame, no engine imports) holds `clamp_pair(a, b, limit)` — moved here
  from `engine/render/backend.py`, which now imports it (`from
  engine.assets.nine_slice import clamp_pair as _clamp_pair`) rather than
  redefining it, so the forward 9-patch composite and the inverse below share
  ONE clamp — plus `dest_to_source(rel_xy, dest_size, src_size, margins)`, the
  exact piecewise inverse of `_nine_patch`'s band layout. EVERY band —
  corners, edges, and the centre — inverts the exact same nearest-neighbour
  sampler `_nine_patch` used to paint it (`_scale_index`, a bit-for-bit
  match of `pygame.transform.scale`'s software stretch, not an
  approximation); a corner only degenerates to a 1:1 identity map in the
  common case where the dest isn't narrower/shorter than the (already
  source-clamped) margin it came from — when the dest shrinks a margin
  below its source size, `_nine_patch` resamples that corner too, and
  `dest_to_source` inverts that resample the same way. A margin pair that
  clamps to exactly fill the SOURCE dimension while the dest still has a
  centre band on that axis (source band vanishes, dest band doesn't) is a
  MISS, not a boundary-pixel read — `_nine_patch` paints nothing there, so
  `dest_to_source` returns an out-of-frame coordinate for that axis
  (`hit_opaque`'s existing bounds check reads it as a miss). `margins=None`
  or all-zero degenerates to plain proportional scaling. `AssetStore.hit_opaque(slot_key,
  animation="idle", anim_time_ms=0, dest_size=None, rel_xy=(0, 0))` resolves
  the frame exactly like `frame()`, then maps `rel_xy` through
  `dest_to_source` and reads a `pygame.mask.from_surface(surface,
  threshold=0)` (alpha > 0 counts as opaque) cached in `self._hit_masks`,
  keyed `(slot_key, row, col, column_block)` — the SAME key space as
  `_frames`, resolved column block and all (see **Store** above). Tolerance
  (E-37): a placeholder or a corrupt/missing sheet degrades to `True` (opaque
  everywhere — a partially-imported build stays fully clickable); a `rel_xy`
  that maps outside the source frame bounds degrades to `False` rather than
  raising. The CALLER (a skinned button) must clamp `rel_xy` to
  `[0, dest_size[0]) x [0, dest_size[1])` — `hit_opaque`/`dest_to_source`
  never validate against `dest_size`, only against the resolved source frame.
- **E-38 is RETIRED — the migration tool is deleted.** `tools/
  migrate_prototype_assets.py` ran once, converting the prototype's v1 manifest +
  `imported/` PNGs to manifest v2 + copied sheets (and baking the 9 procedurally-
  generated map tiles to static PNGs, since this codebase does not generate art at
  runtime, D-1/D-2). **Its output is committed and is now simply the content** —
  `data/sprites/imported/*.png` + `asset_manifest.json`. The tool and its tests
  are gone with the migration; the editor's importer is the only way art enters
  the repo. Two leftovers of that history are worth knowing: sheets are flattened
  to `imported/<slot>.png` (D-31) whatever the prototype's subfolders were, and
  the procedural `enemy`/`enemy_t*` entries are unreferenced strays in the
  manifest (the enemies registry points at the real `enemy_stage_N`/
  `raider_stage_N` sheets).
- **`master_registry.py` (MasterSheetColumnsPLAN C3)** — the pure reader of
  `data/sprites/master_sheets.json`, sibling of `registry.py`: fail-loud via
  `data_io.load_validated` (the registry is infrastructure, the E-37 split
  above). `columns_for(doc, ref)` / `column_width_for(doc, ref)` resolve a
  `master/<id>.png` ref **against each entry's STORED `file`, never a
  re-derived path**, and are total — an `imported/` ref, an unknown sheet or a
  malformed entry returns `()` / `0` rather than raising. It lives in `engine/`
  because `game/` and `editor/` both need it and may not import each other
  (the `era_math.py` argument). The editor's
  `master_sheet_import.load_registry_doc` delegates its READ here and keeps its
  own E-37 degrade-to-empty-doc wrapper; `write_registry_doc` is still the ONE
  write path.

## Verify
`playback_order` + tolerance unit tests; the headless smoke test fails loud on an
invalid committed manifest: `py -m pytest tools/tests/test_<area>.py -q` +
`py tools/smoke.py`.

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
