# Section S1 handoff

**Landed** — branch `section-S1` @ `9a1c90a`; all three phases green, zero fix rounds.
C1 `phase-C1-data-layer` @ `be45213` (schemas + registry migration: `slinger_t2_lvl3` →
`column_width: 15`, no `columns`) · C2 `phase-C2-manifest-store` @ `60f0954` (parse, the
cut, cache keys) · C3 `phase-C3-registry-render` @ `f9c2732` (`master_registry.py` + render).

**Interface deltas** — what wave 2 codes against.
- Manifest keys, all OPTIONAL: `column` (0..255, omit⇒0), `column_mode`
  (`manual`|`season`|`building_color`, omit⇒`manual`), `column_width` (1..256,
  omit⇒**0** ⇒ byte-identical). Registry: `column_width` **REQUIRED** (1..256),
  `columns` optional 1..16 unique `^[a-z][a-z0-9_]*$`.
- `ManifestEntry.column=0 / .column_mode="manual" / .column_width=0`
  (`engine/assets/manifest.py:119-121`); const `COLUMN_MODES`; parse RAISES on
  bool/float/str/negative (no coercion).
- `AssetStore.frame(slot_key, animation="idle", anim_time_ms=0, extra_hidden=None,
  column=None)` (`store.py:100`); `AssetStore.hit_opaque(slot_key, animation="idle",
  anim_time_ms=0, dest_size=None, rel_xy=(0,0), column=None)` (`store.py:118`).
- **Cache keys are 4-tuples now** `(slot_key, row, col, block)` for `_frames` AND
  `_hit_masks`, on the CLAMPED block (`store.py:174`, `:246`). Do not simplify back.
- `RenderItem.column: int = 0` (`engine/render/item.py:36`, last field);
  `SpriteAnimator.column: int = 0` (`sprite_animator.py:22`); `renderer.py:204` passes
  `column=item.column` as a KEYWORD. HUD pass gets none (D8).
- `engine/assets/master_registry.py`: `load_registry(data_dir)` fail-loud;
  `columns_for(doc, sheet_ref)->tuple` (`()` if unresolvable); `column_width_for(
  doc, sheet_ref)->int` (`0` if unresolvable). `editor/master_sheet_import.
  load_registry_doc` delegates to it, keeping its E-37 wrapper.

**Shipped surface vs the "Publishes" contract** — everything promised landed. One thing
was ADDED, and S2 must know: `import_master_sheet` now writes
`column_width: max(1, sheet_w // frame_w)` (`editor/master_sheet_import.py:303`).
Unplanned but forced — making `column_width` required breaks every editor import and no
S1 phase owned the fix. One column spanning the sheet ⇒ no art moves.
**S2/E1 must supersede it with the real designer field.** Also added, mechanical:
`tools/test_domains.py`, `tools/tests/test_components.py:23`, `test_hud_items.py:33/:45`.

**Open findings**
1. `RenderItem.column: int = 0` makes C2's `column is None` fallback unreachable on the
   world path: a `season`/`building_color` entry with no live driver resolves to block 0,
   not its stored `column` — contradicts D3. Harmless until columns are driven.
   *Owner: top orchestrator → S3 + S4.* **verified**
2. Schema caps `column_width` at 256, so the stopgap refuses a >256-frame sheet.
   *Owner: S2/E1.* **inferred**
3. `tools/tests/fixtures/data/` has ~13 files of **pre-existing** drift from live `data/`,
   unrelated to S1. *Owner: user / top orchestrator.* **measured**

**Gate** (mine, on the merged branch) — `py tools/smoke.py` **PASS** (62 data files
schema-valid, 5 headless frames, shell boot OK) — **measured**. `py -m pytest` over the 7
touched test files → **204 passed, 49 subtests, 0 failed, 0 skipped** — **measured**.
That run also cleared C2's `test_guard`-denied unverified fix and C3's standalone red
(a `TypeError` only the C2+C3 merge could resolve). Reviews: C1 and whole-section, both
clean, no material findings.
