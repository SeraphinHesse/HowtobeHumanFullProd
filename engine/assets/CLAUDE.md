# CLAUDE.md — engine/assets

Data-driven slot registry, manifest v2 loader, `playback_order` row semantics
(rows = animations, row 0 = idle), grey-X placeholder (E-33..E-38). You reached
here from `engine/CLAUDE.md`. **Missing/corrupt art logs and falls back — never
crashes boot.** When you change asset conventions, update THIS doc.

## Import boundary
`engine.assets` package `__init__` + `types` + `manifest` + `registry` +
`nine_slice` are **pure**; pygame lives only in `engine.assets.placeholder` and
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
  blit path; only `muzzle` (`game/enemies/combat.py`, world-offset via
  `game/anchors.py`) and `hp_bar` (`game/ui/effects.py`, screen-offset) are
  wired to a read-site today. `impact`/`floater_origin`/`status_icon`/
  `beam_endpoint` are declared and parse-ready but inert (no read-site) —
  shipped now so their future wiring needs no schema migration.
  - **`AssetStore.offset(slot_key)`** (the anchor/offset composition fix,
    `docs/briefs/fix-anchor-offset-and-bullet-sprites.md`) mirrors `anchor()`
    exactly: `(x, y)` ints from the manifest entry's `offset_x`/`offset_y`, or
    `(0, 0)` when the slot or its entry is absent — same degrade-never-raise
    contract. It is what lets `game/anchors.py`'s `screen_offset`/
    `world_offset` and `editor/panels/viewport.py`'s `_anchor_draw_params`
    compose the renderer's draw nudge (`engine/render/renderer.py`'s
    `frame.offset_x`/`offset_y`) into the anchor origin, so all three
    consumers of "where is this sprite's anchor point" agree.
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
- **Store**: `AssetStore(manifest, registry, frame_sizes, default_frame_size,
  sprites_dir)`; frame-size precedence manifest entry > registry (**per-slot
  override, then category**) > frame_sizes > default. Sheets load via `pygame.image.load` with NO
  `convert()`/`convert_alpha()` (they need a display; the editor runs SDL dummy).
  Sliced frames are SUBSURFACES — the parent sheet must stay cached. There is no
  cache invalidation: when the manifest changes, build a new AssetStore (the
  editor's `reload_assets()` does exactly that).
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
  keyed `(slot_key, row, col)` — the SAME key space as `_frames`. Tolerance
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

## Verify
`playback_order` + tolerance unit tests; the headless smoke test fails loud on an
invalid committed manifest: `py -m unittest discover -s tools/tests -t .` +
`py tools/smoke.py`.
