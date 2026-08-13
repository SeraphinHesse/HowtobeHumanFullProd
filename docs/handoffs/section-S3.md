# Section S3 handoff — PARTIAL (2 of 3 phases landed, gated green)

**Landed** — `section-S3` @ `9db1f0f`; both phases reviewed clean, zero fix rounds.
- **B1** `phase-B1-colour-state` @ `bf53459` — colour state, the roll, the render.
- **B2** `phase-B2-construct-swatches` @ `b99d589` — ConstructPreview swatches.
- **B3 NOT LANDED** — `phase-B3-upgrade-swatches` cut @ `f2987a9`, brief written,
  coder ran ~7.5h without a commit and never returned (**measured**: tip unmoved
  across 15 polls). Nothing of B3 is in the tree; `data/balancing/ui.json` and
  `data/schemas/ui.schema.json` are **untouched**.

**Interface deltas** — B1+B2 are real code; the B3 bullet is settled design only.
- `place_building(tilemap, tile, building_type, love, buildings_balance, scene,
  occupancy, state=None, colour_columns=None, rng=None, column=None)`
  (`game/buildings/registry.py:87`). New params trailing keyword-with-default, so
  all 18 calling test files + `simrun.py:171` stay byte-identical; **no rng draw
  unless a roll happens**.
- Precedence (`registry.py:205-214`): `column is not None` ⇒ verbatim, no draw;
  else `randrange(len(names))`; else leave `-1`. **`0` is a real colour** — every
  comparison in both phases is `is not None`, never a truth test (reviewer-verified).
- `_derive_colour_columns(registry, manifest, data_dir)` (`game/main.py:127`).
  Capability = sheet declares `columns` **AND** entry
  `column_mode == "building_color"`. E-37: unreadable registry ⇒ one warning ⇒
  `{}`, never raises. Published as `gp["panel"].colour_columns` (`main.py:897`).
- **`class ColorSwatchRow`** (`game/ui/building_ui.py:332`, module-level,
  `SIZE = 12` = the UR-5 floor exactly) and **`_swatch_rgb(name,
  ui_balance=None)`** (`:312`). **B3 reuses both**: it drops the row into the
  upgrade panel and swaps only `_swatch_rgb`'s body to read `BuildingColors`.
  `ui_balance` is already threaded but unused — that is the seam B3 fills.
- `ConstructPreview` rolls `self.chosen_column` on open (`:496`) and passes it as
  `column=` (`:2133`), so the placed building always matches the preview, and a
  whole batch gets one colour. **My call**, taken because the alternative (open on
  index 0) makes the preview lie; B2's brief had reserved it to me.
- Naming wart: `ConstructPreview(building_colors=...)` (`:435`) vs B1's
  `colour_columns=`. Cosmetic, no wrong call; B3 should not "fix" it.
- **B3 must NOT add `BuildingColors` to the schema root's `required`** — that root
  is `additionalProperties:false` with 4 required groups, and a 5th reddens
  `tools/tests/fixtures/data/balancing/ui.json` (out of scope).

**Open findings**
1. **B3 is unstarted; S3 is NOT complete.** Brief written, interface settled,
   helper already factored — a re-dispatch should be cheap. *Owner: top
   orchestrator.* **measured**
2. **No shipped master sheet declares `columns`** (`slinger_t2_lvl3` has only
   `column_width: 15`) ⇒ live capability map empty ⇒ **both S3 Quick Tests are
   unrunnable in-game until S2/E1 ships the designer field.** B1+B2 are correct
   but invisible in-game today. *Owner: S2 / top.* **verified**
3. D6-vs-D3 conjunction above is a real plan gap; **S4 hits it identically for
   `season`**. *Owner: user / top orchestrator.* **inferred**

**Gate** (mine, on merged `section-S3`) — `py tools/smoke.py` → **OK** (62 data
files schema-valid, 5 headless frames, shell boot OK). Targeted run over the three
touched test files (`test_buildings_placement.py`, `test_hud_panel.py`,
`test_ui_min_targets.py`) → **31 passed, 14 subtests, 0 failed, 0 skipped**.
Both **measured**. Reviews: B1 clean, B2 clean (no blocking findings).
