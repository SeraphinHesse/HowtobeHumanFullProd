# Section S3 handoff — LANDED (3 of 3 phases)

**Landed** — `section-S3` @ `b8a6459`; all three phases green, **zero fix rounds**.
B1 `phase-B1-colour-state` @ `bf53459` (colour state, the roll, the render) ·
B2 `phase-B2-construct-swatches` @ `b99d589` (ConstructPreview swatches) ·
B3 `phase-B3-upgrade-swatches` @ `353d5d1` (upgrade-panel row + `BuildingColors`).
Reviews: per-phase ×3 + whole-section, **no blocking findings**; the section
reviewer confirmed the host→modal→placement→render chain actually connects.

**Interface deltas**
- `place_building(tilemap, tile, building_type, love, buildings_balance, scene,
  occupancy, state=None, colour_columns=None, rng=None, column=None)`
  (`game/buildings/registry.py:87`). New params trailing keyword-with-default, so
  all 18 calling test files + `tools/simrun.py:171` stay byte-identical; **no rng
  draw unless a roll happens**.
- Precedence (`registry.py:205-214`): `column is not None` ⇒ verbatim, no draw;
  else `randrange(len(names))`; else leave the `-1` sentinel. **`0` is a real
  colour index** — every comparison across all three phases is `is not None`,
  never a truth test (reviewer-swept).
- `_derive_colour_columns(registry, manifest, data_dir)` → `{slot_key:
  (name, ...)}` (`game/main.py:127`), assigned to `gp["panel"].colour_columns`
  (`main.py:897`). **Capability = sheet declares `columns` AND entry
  `column_mode == "building_color"`** (see finding 2). E-37: unreadable registry
  ⇒ one warning ⇒ `{}`, never raises.
- **`class ColorSwatchRow`** (`game/ui/building_ui.py:332`, module-level,
  `SIZE = 12` = the UR-5 floor exactly) is shared by BOTH screens;
  **`_swatch_rgb(name, ui_balance=None)`** (`:312`) is the single colour source
  and reads `BuildingColors` from `ui.json`. B2's interim hardcoded palette map
  was deleted by B3 so an unknown name degrades to neutral `C_PANEL_INSET`
  rather than to a wrong-but-plausible shared colour.
- **NEW data**: `BuildingColors` group in `data/balancing/ui.json` +
  `data/schemas/ui.schema.json` — 4 fixed names → `[r,g,b]` (0..255). **Declared
  in `properties`, deliberately NOT in the schema root's `required`** (root stays
  `['Debug','FX','Menu','Timing']`): a 5th required key would redden
  `tools/tests/fixtures/data/balancing/ui.json`. Read via `.get(...)`.
- `data/ui/screen_defaults.json` regenerated → **byte-identical**, so the
  `test_ui_skinning.py` golden needed no edit and no mock builder was added.
- Cosmetic wart, do not "fix": `ConstructPreview(building_colors=)` vs
  `place_building(colour_columns=)`.

**Open findings**
1. **No shipped master sheet declares `columns`** (`slinger_t2_lvl3` has only
   `column_width: 15`) ⇒ the live capability map is EMPTY ⇒ **both S3 Quick Tests
   are unrunnable in-game until S2/E1 ships the designer field.** The code is
   correct and fully tested; it is simply invisible today. *Owner: S2 / top.*
   **verified**
2. **D6 vs D3 gap.** D6 says swatches appear when a sheet declares `columns`; D3
   means a `manual` entry ignores a live column, so that alone yields dead UI. I
   required BOTH. **S4 hits this identically for `season`.** *Owner: user / top
   orchestrator.* **inferred**
3. Swatch row caps at 8 colours (118px panel ÷ 14px pitch); registry allows 16.
   Silently drops the tail. No sheet has any colours yet. *Owner: user.* **verified**

**Gate** (mine, on merged `section-S3`) — `py tools/smoke.py` → **OK** (62 data
files schema-valid, 5 headless frames, shell boot OK). `py -m pytest` over the 4
touched test files (`test_buildings_placement`, `test_hud_panel`,
`test_ui_min_targets`, `test_ui_skinning`) → **60 passed, 20 subtests, 0 failed,
0 skipped**. Both **measured**.
