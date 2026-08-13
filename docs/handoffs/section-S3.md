# Section S3 handoff — PARTIAL (1 of 3 phases landed)

**Landed** — `section-S3` @ `e98e5c4`. **B1 only**, reviewed clean:
`phase-B1-colour-state` @ `bf53459`, merged. **B2 NOT LANDED** — branch
`phase-B2-construct-swatches` cut @ `eb2fcce`, coder ran ~6h without one commit
and never returned (**measured**: tip unmoved across 14 polls); nothing in tree.
**B3 NOT DISPATCHED** — it reuses B2's helper, so it was never startable. Wave 1
is complete: all three briefs committed (`docs/briefs/phase-B{1,2,3}-*.md`).

**Interface deltas** — B1 is real code; B2/B3 bullets are settled design only.
- `place_building(tilemap, tile, building_type, love, buildings_balance, scene,
  occupancy, state=None, colour_columns=None, rng=None, column=None)`
  (`game/buildings/registry.py:88`). New params trailing keyword-with-default, so
  all 18 calling test files + `building_ui.py:1928-1930` + `simrun.py:171` stay
  byte-identical; **no rng draw unless a roll happens**.
- Precedence (`registry.py:205-214`): `column is not None` ⇒ verbatim, no draw;
  else `randrange(len(names))`; else leave `-1`. **`0` is a real colour** —
  `is not None`, never a truth test. I added `column=` to reconcile B2's swatch
  pick with B1's roll; B1's brief had reserved it to B2, so the reviewer flagged
  it — authorised by me, not a defect.
- `_derive_colour_columns(registry, manifest, data_dir)` (`game/main.py:127`).
  Capability = sheet declares `columns` **AND** entry
  `column_mode == "building_color"`. E-37: unreadable registry ⇒ one
  `_log.warning` ⇒ `{}`, never raises. Published as `gp["panel"].colour_columns`
  (`game/main.py:897`).
- **B2 must add `self.colour_columns = {}` to `BuildingUI.__init__`** (the
  `self.assets = None` precedent, `building_ui.py:735`) — B1 was fenced out of
  `game/ui/**`. Without it every bare-`BuildingUI` test breaks.
- B3: add `BuildingColors` to `data/balancing/ui.json` + schema but **not** to the
  schema root's `required` — that root is `additionalProperties:false` with 4
  required groups; a 5th reddens `tools/tests/fixtures/data/balancing/ui.json`.

**Open findings**
1. **B2+B3 are unstarted; S3 is NOT complete.** Briefs written and the interface
   settled, so re-dispatch should be cheap. *Owner: top orchestrator.* **measured**
2. **No shipped master sheet declares `columns`** (`slinger_t2_lvl3` has only
   `column_width: 15`) ⇒ live map empty ⇒ **every S3 Quick Test is unrunnable
   in-game until S2/E1 ships the designer field.** B1 is correct but invisible
   in-game today. *Owner: S2 / top.* **verified**
3. D6-vs-D3 conjunction above is a real plan gap; **S4 hits it identically for
   `season`**. *Owner: user / top orchestrator.* **inferred**

**Gate** (mine, on merged `section-S3`) — `py tools/smoke.py` → **OK** (62 data
files schema-valid, 5 headless frames, shell boot OK) — **measured**.
`py -m pytest tools/tests/test_buildings_placement.py` → **DENIED 3× by
`test_guard`** ("a test run is already in flight", sibling worktree
`agent-a423e1e4e6ff2dccb` running `test_editor_viewport.py`). Reported, not
retried further. B1's coder measured that file green in its own worktree:
**12 passed, 4 subtests, 0 failed, 0 skipped**.
