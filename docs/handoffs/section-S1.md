# Section S1 handoff

**Landed** — branch `section-S1` @ `a3b9dd2` (+1 doc commit); all three phases green.
- **C1** `phase-C1-data-layer` @ `be45213` — both schemas learn columns; the one
  registry entry migrated (`slinger_t2_lvl3` → `column_width: 15`, no `columns`).
- **C2** `phase-C2-manifest-store` @ `60f0954` — manifest parse + the frame cut + cache keys.
- **C3** `phase-C3-registry-render` @ `f9c2732` — `master_registry.py` + render column threading.

**Interface deltas** — the surface wave 2 codes against.
- Manifest entry keys, all OPTIONAL (`data/schemas/asset_manifest.schema.json`):
  `column` (0..255, omit⇒0), `column_mode` (`manual`|`season`|`building_color`,
  omit⇒`"manual"`), `column_width` (1..256, omit⇒**0** ⇒ byte-identical resolution).
- Registry keys (`data/schemas/master_sheets.schema.json`): `column_width`
  **REQUIRED** (1..256); `columns` optional, 1..16 unique `^[a-z][a-z0-9_]*$`.
- `ManifestEntry.column: int = 0`, `.column_mode: str = "manual"`,
  `.column_width: int = 0` (`engine/assets/manifest.py:119-121`).
  Module const `COLUMN_MODES`. Parse RAISES on bool/float/str/negative (no coercion).
- `AssetStore.frame(slot_key, animation="idle", anim_time_ms=0, extra_hidden=None,
  column=None)` and `AssetStore.hit_opaque(slot_key, animation="idle",
  anim_time_ms=0, dest_size=None, rel_xy=(0,0), column=None)`
  (`engine/assets/store.py:100`, `:118`). `column` is LAST keyword in both.
- **Cache keys are now 4-tuples** `(slot_key, row, col, block)` for `_frames` AND
  `_hit_masks`, keyed on the CLAMPED block (`store.py:174`, `:246`). Do not simplify back.
- `RenderItem.column: int = 0` (`engine/render/item.py:36`, appended last);
  `SpriteAnimator.column: int = 0` (`engine/core/sprite_animator.py:22`);
  `renderer.py:204` passes `column=item.column` as a KEYWORD. HUD pass gets none (D8).
- `engine/assets/master_registry.py`: `load_registry(data_dir)` (fail-loud),
  `columns_for(doc, sheet_ref) -> tuple` (`()` when unresolvable/unnamed),
  `column_width_for(doc, sheet_ref) -> int` (`0` when unresolvable).
  `editor/master_sheet_import.load_registry_doc` delegates to it, keeping its E-37 wrapper.

**Deviations from what S1 "Publishes" promised** — one, and it is scope ADDED, not dropped:
- `editor/master_sheet_import.import_master_sheet` now writes
  `column_width: max(1, sheet_w // frame_w)` (`:303`). **Unplanned but forced**: making
  `column_width` required breaks every editor import (validating write path), and no
  phase in S1 owned the fix. One column spanning the whole sheet ⇒ no art moves.
  **S2/E1 must supersede this with the real designer field** (comment says so in place).
- Also outside the plan's file lists, mechanical and forced: `tools/test_domains.py`
  (new module needs a domain), `tools/tests/test_components.py:23`,
  `tools/tests/test_hud_items.py:33/:45` (fake `frame()` signatures).

**Open findings**
1. **`RenderItem.column: int = 0` makes the `column is None` fallback unreachable on the
   world path** — a `season`/`building_color` entry with NO live driver resolves to block
   0, not its stored `column`, contradicting D3's "falling back to the stored column".
   Harmless until S3/S4 drive columns. *Owner: top orchestrator → S3 + S4.* **verified**
2. Schema caps `column_width` at 256, so the stopgap refuses a sheet wider than 256
   frames. *Owner: S2/E1.* **inferred**
3. `tools/tests/fixtures/data/` carries ~13 files of **pre-existing** drift from live
   `data/` (unrelated to this section; a blanket `--refresh` would have swept them in).
   *Owner: user / top orchestrator.* **measured**

**Gate** (on the merged `section-S1`, by me, not a coder) — `py tools/smoke.py` **PASS**
(`OK`, 62 data files schema-valid, 5 headless frames, shell boot OK) — **measured**.
`py -m pytest` over the 7 touched test files (`test_assets_manifest`, `test_asset_store`,
`test_master_registry`, `test_render`, `test_master_sheet_import`, `test_components`,
`test_hud_items`) → **204 passed, 49 subtests passed, 0 failed, 0 skipped** — **measured**.
This run also cleared C2's `test_guard`-denied unverified fix and C3's standalone red
(a `TypeError` that only the C2+C3 merge could resolve). Reviews: C1 clean, whole-section
clean, no material findings, zero fix rounds used.
