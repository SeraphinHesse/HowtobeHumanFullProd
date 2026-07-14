# CLAUDE.md — engine/assets

Data-driven slot registry, manifest v2 loader, `playback_order` row semantics
(rows = animations, row 0 = idle), grey-X placeholder (E-33..E-38). You reached
here from `engine/CLAUDE.md`. **Missing/corrupt art logs and falls back — never
crashes boot.** When you change asset conventions, update THIS doc.

## Import boundary
`engine.assets` package `__init__` + `types` + `manifest` + `registry` are
**pure**; pygame lives only in `engine.assets.placeholder` and
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
- **Store**: `AssetStore(manifest, registry, frame_sizes, default_frame_size,
  sprites_dir)`; frame-size precedence manifest entry > registry (**per-slot
  override, then category**) > frame_sizes > default. Sheets load via `pygame.image.load` with NO
  `convert()`/`convert_alpha()` (they need a display; the editor runs SDL dummy).
  Sliced frames are SUBSURFACES — the parent sheet must stay cached. There is no
  cache invalidation: when the manifest changes, build a new AssetStore (the
  editor's `reload_assets()` does exactly that).
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
