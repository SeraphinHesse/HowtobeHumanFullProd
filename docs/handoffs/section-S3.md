# Section S3 handoff — BLOCKED (Wave 1 only; no phase code landed)

**Landed** — `section-S3` @ `4d67ea9`. **Zero phases implemented**; B1/B2/B3 all
not started in code. Landed content is briefs + this handoff + plan-status only
(**measured**: `git diff --stat umbrella..section-S3` = 5 files, no source).
`phase-B1-colour-state` @ `452a40e` is cut but carries **no coder commit** — its
coder ran ~3h without committing and ignored three probes (tip SHA unmoved across
12 polls). B2/B3 never dispatched: both need B1's merged signature.

**Interface deltas** — DESIGN ONLY, none of it in the tree. Settled input for a
re-run; do not re-derive.
- `place_building(..., state=None, colour_columns=None, rng=None, column=None)`
  (`game/buildings/registry.py:75`). New params trailing keyword-with-default —
  **18 test files** + `game/ui/building_ui.py:1928-1930` + `tools/simrun.py:171`
  call it (**measured**), so defaults must stay byte-identical.
- `column is not None` ⇒ use verbatim (**never a truth test — `0` is a real
  colour**); else one `rng` draw; else leave animator at `-1`. I added `column=`
  to reconcile B2's swatch pick against B1's roll.
- `colour_columns = {slot_key: (name, ...)}` derived once in `game/main.py` beside
  `condition_art` (`main.py:596-620`), published as `BuildingUI.colour_columns` in
  `build_gameplay()` (~`main.py:846`).
- B2 helper `ColorSwatchRow` (module-level in `building_ui.py`, `SIZE=12` = the
  UR-5 floor exactly); colour lookup behind one `_swatch_rgb(name,
  ui_balance=None)` so B3 swaps a single body. Row `y+36..y+47`, abuts the name
  box at `y+48`, nothing below moves (**verified**).
- B3 `BuildingColors` → `data/balancing/ui.json` + schema, **not** added to the
  root `required` list: that root is `additionalProperties:false` with 4 required
  groups, and a 5th reddens `tools/tests/fixtures/data/balancing/ui.json`
  (out of scope).

**Open findings**
1. Section unblockable at this wall-clock rate — planners ~7 min agent time but
   ~1h wall each; coder >3h. S3 is a strict B1→B2→B3 chain (shared files), so it
   cannot be parallelised. *Owner: top orchestrator — re-dispatch or run inline.*
   **measured**
2. **No shipped master sheet declares `columns`** (`slinger_t2_lvl3` has only
   `column_width: 15`), so the live map is empty and **every S3 Quick Test is
   unrunnable in-game until S2/E1 ships the designer field.** *Owner: S2 / top.*
   **verified**
3. Capability = sheet declares `columns` **AND** entry `column_mode ==
   "building_color"`. D6 states only the first; the conjunction is the only
   reading that works. **S4 hits this identically for `season`.** *Owner: user.*
   **inferred**
4. B1's Quick Test is unobservable at B1's gate (sole production caller is B2's
   file). I ruled: B1 must not touch `building_ui.py`; defer to B2. **verified**

**Gate** — **NOT RUN, correctly**: no source file changed, so nothing to gate. No
smoke, no pytest, no `test_guard` deny. Read no PASS into this section.
