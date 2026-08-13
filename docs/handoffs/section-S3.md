# Section S3 handoff — LANDED (3 of 3 phases)

**Landed** — `section-S3` @ `b8a6459`; all three phases green, **zero fix rounds**.
B1 `phase-B1-colour-state` @ `bf53459` · B2 `phase-B2-construct-swatches` @
`b99d589` · B3 `phase-B3-upgrade-swatches` @ `353d5d1`. Four reviews (per-phase ×3
+ whole-section): **no blocking, no should-fix**. The section reviewer traced the
host→modal→placement→render chain hop by hop and confirmed it is really connected.

**Interface deltas**
- `place_building(tilemap, tile, building_type, love, buildings_balance, scene,
  occupancy, state=None, colour_columns=None, rng=None, column=None)`
  (`game/buildings/registry.py:87`). New params trailing keyword-with-default;
  the 19 existing callers (18 test files + `tools/simrun.py:171`) pass none, so
  `colour_columns=None` ⇒ `()` ⇒ **no `rng.randrange` call at all** and no seeded
  test's draw sequence moves.
- Precedence (`registry.py:205-214`): `column is not None` ⇒ verbatim, no draw;
  else `randrange(len(names))`; else leave the `-1` sentinel. **`0` is a real
  colour index** — reviewer swept all three phases: every check is
  `is not None` / `< 0` / `>= 0`, never truthiness.
- `_derive_colour_columns(registry, manifest, data_dir)` → `{slot_key:
  (name, ...)}` (`game/main.py:127`) → `gp["panel"].colour_columns`
  (`main.py:897`). **Capability = sheet declares `columns` AND entry
  `column_mode == "building_color"`** (finding 2). E-37: unreadable registry ⇒
  one warning ⇒ `{}`.
- **`class ColorSwatchRow`** (`game/ui/building_ui.py:332`, `SIZE = 12` = the UR-5
  floor exactly) is shared by BOTH screens; **`_swatch_rgb(name,
  ui_balance=None)`** (`:312`) is the single colour source, reading
  `BuildingColors`. B2's interim hardcoded palette was deleted by B3 so an
  unknown name degrades to neutral `C_PANEL_INSET`, not a plausible-but-wrong hue.
- Key-agreement seam (the one most likely to silently mismatch, verified sound):
  the modal's `temp.slot_key()` and placement's `anim.slot_key` are the same
  method (`game/buildings/building.py:173/191`), and `BuildingSprite` IS the
  `SpriteAnimator`, so both screens share ONE field.
- **NEW data**: `BuildingColors` in `data/balancing/ui.json` +
  `data/schemas/ui.schema.json` — 4 names → `[r,g,b]` 0..255. In `properties`,
  deliberately **NOT** in the schema root's `required` (stays
  `['Debug','FX','Menu','Timing']`); a 5th would redden the test fixture.
- `data/ui/screen_defaults.json` regenerated → **byte-identical**; no golden edit,
  no mock builder. Cosmetic wart, do not "fix":
  `ConstructPreview(building_colors=)` vs `place_building(colour_columns=)`.

**Open findings**
1. **No shipped master sheet declares `columns`** ⇒ live capability map EMPTY ⇒
   **both Quick Tests unrunnable in-game until S2/E1 ships the designer field.**
   Code correct and tested, just invisible. *Owner: S2 / top.* **verified**
2. **D6-vs-D3 gap.** D6 alone (sheet declares `columns`) yields dead UI, since a
   `manual` entry ignores a live column. I required BOTH. **S4 hits this
   identically for `season`.** *Owner: user / top.* **inferred**
3. Swatch row caps at 8 colours (118px ÷ 14px pitch); registry allows 16 — tail
   silently dropped. No sheet has colours yet. *Owner: user.* **verified**
4. Nit: `group_slots(BUILDINGS_CATEGORY)` sits outside `_derive_colour_columns`'s
   `try/except`, so a vanished `"buildings"` category would crash boot instead of
   degrading. Theoretical (it matches the `condition_art` convention and the
   category exists). *Owner: none.* **inferred**

**Gate** (mine, on merged `section-S3`) — `py tools/smoke.py` → **OK** (62 data
files schema-valid, 5 headless frames, shell boot OK). `py -m pytest` over the 4
touched test files → **60 passed, 20 subtests, 0 failed, 0 skipped**. Both
**measured**.
