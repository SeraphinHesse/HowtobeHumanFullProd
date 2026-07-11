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
- **Store**: `AssetStore(manifest, registry, frame_sizes, default_frame_size,
  sprites_dir)`; frame-size precedence manifest entry > registry > frame_sizes >
  default. Sheets load via `pygame.image.load` with NO
  `convert()`/`convert_alpha()` (they need a display; the editor runs SDL dummy).
  Sliced frames are SUBSURFACES — the parent sheet must stay cached. There is no
  cache invalidation: when the manifest changes, build a new AssetStore (the
  editor's `reload_assets()` does exactly that).
- **E-38**: `tools/migrate_prototype_assets.py` converts the prototype's v1
  manifest + imported/ PNGs (read-only) to manifest v2 + copied sheets;
  idempotent; already run — its output is committed. Each source sheet is resolved
  from its own v1 `sheet` path (the prototype filed most under
  `imported/{buildings,enemies/*,hole}/` subfolders; dst still flattens to
  `imported/<slot>.png`, D-31). It imports every prototype sheet 1:1 — no
  synthetic/alias slots (the enemies registry references the real
  `enemy_stage_N`/`raider_stage_N` sheets directly; the procedural `enemy`/
  `enemy_t*` sheets stay in the manifest but are unreferenced leftovers).
  Follow-up (Phase 6): the same script's `migrate_tiles()` bakes the 9 map tile
  slots the prototype generated procedurally (never stored in its v1 manifest) to
  static PNGs + manifest entries via `editor.asset_import.import_idle_sheet` — 7
  are direct file copies, `tile_combat[_b]` are a one-time Pillow grayscale+tint
  reproduction of `sprite_gen.py`'s runtime tinting (this codebase does not
  generate art at runtime, D-1/D-2). Also already run; output committed.

## Verify
`playback_order` + tolerance unit tests; the headless smoke test fails loud on an
invalid committed manifest: `py -m unittest discover -s tools/tests -t .` +
`py tools/smoke.py`.
