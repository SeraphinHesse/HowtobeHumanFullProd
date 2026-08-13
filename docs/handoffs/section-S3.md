# Section S3 handoff — BLOCKED (Wave 1 complete, no phase code landed)

**Landed** — `section-S3` @ `d8d1d45`. **Zero phases implemented.** B1/B2/B3 are
all *not started* in code. What landed is Wave 1 only: three phase briefs,
committed, plus my cross-phase reconciliation. `phase-B1-colour-state` @ `452a40e`
is cut but carries **no coder commit** — its coder ran ~3h without committing and
did not answer three `SendMessage` probes (**measured**: tip SHA unmoved across 12
polls). B2/B3 were never dispatched — both depend on B1's merged signature.

**Interface deltas** — DESIGN ONLY, none of this is in the tree yet. It is the
reconciled contract; a re-run should treat it as settled input, not re-derive it.
- `place_building(tilemap, tile, building_type, love, buildings_balance, scene,
  occupancy, state=None, colour_columns=None, rng=None, column=None)` —
  `game/buildings/registry.py:75`. All new params trailing keyword-with-default;
  **18 test files** plus `game/ui/building_ui.py:1928-1930` and
  `tools/simrun.py:171` call it (**measured**), so defaults must be byte-identical.
- `column is not None` ⇒ use verbatim (never a truth test — **`0` is a real
  colour**); else roll one `rng` draw; else leave the animator at `-1`.
  I added `column=` to reconcile B2's swatch pick with B1's roll.
- Capability map `colour_columns = {slot_key: (name, ...)}`, derived once in
  `game/main.py` beside `condition_art` (`main.py:596-620`), published as
  `BuildingUI.colour_columns` in `build_gameplay()` (~`main.py:846`). Membership =
  sheet declares `columns` **AND** entry `column_mode == "building_color"` — D6
  states only the first; the conjunction is the only reading where the feature
  works (**inferred**, flagged below).
- B2 helper `ColorSwatchRow` (module-level in `building_ui.py`, `SIZE=12` = the
  UR-5 floor exactly), colour lookup behind the single `_swatch_rgb(name,
  ui_balance=None)` so B3 swaps one body. Row at `y+36..y+47`, abutting the name
  box at `y+48`; nothing below moves (**verified** by B2's planner).
- B3 `BuildingColors` in `data/balancing/ui.json` + schema. **Do NOT add it to the
  root `required` list** — `data/schemas/ui.schema.json` root is
  `additionalProperties:false` with 4 required groups, and a 5th required key
  reddens `tools/tests/fixtures/data/balancing/ui.json`, which is out of scope.

**Open findings**
1. **The section is unblockable-as-dispatched at this wall-clock rate.** Planners
   took ~7 min agent time but ~1h wall each; the coder exceeded 3h. S3 is a
   strictly sequential chain (B1→B2→B3 all touch shared files), so it cannot be
   parallelised away. *Owner: top orchestrator — re-dispatch, or run S3 inline.*
   **measured**
2. **No shipped master sheet declares `columns`** (`slinger_t2_lvl3` has
   `column_width: 15`, none). So the live capability map is EMPTY and **every S3
   Quick Test is unrunnable in-game until S2/E1 ships the designer field.**
   *Owner: top orchestrator / S2.* **verified**
3. D6 vs D3 conjunction (above) is a genuine plan gap, and **S4 hits the identical
   question for `season`**. *Owner: user / top orchestrator.* **inferred**
4. B1's Quick Test is not observable at B1's own gate — the only production caller
   is B2's file. I ruled: B1 must NOT touch `building_ui.py`; Quick Test defers to
   B2. *Owner: next S3 run.* **verified**

**Gate** — **NOT RUN, and correctly so**: no source file changed on `section-S3`
(briefs only), so there was nothing to gate. No smoke run, no pytest run, no
`test_guard` deny. Do not read any PASS into this section.
