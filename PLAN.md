<!-- active-plan: TestFixturePinningPLAN.md | set: 2026-07-14 -->
> **Active plan:** TestFixturePinningPLAN.md (mirror). Source of truth:
> `planning/TestFixturePinningPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: IN PROGRESS — FP-1..FP-5 executing serially on one branch, 2026-07-14 -->

# TestFixturePinningPLAN.md — Pin the suite's data, free the designers

Phased, agent-executable plan (same family as `TestGatePLAN.md` /
`AgentDispatchPLAN.md`). Base branch: `Development`. Executed serially, in the
main tree, on one branch (`test/fixture-pinning`) — the phases are stacked
edits to the same 47 files and parallel worktrees would conflict, exactly the
lesson TestGatePLAN's header records.

## 1. Context — why this plan exists

A designer nudging enemy HP in the editor turns the gate red. Measured on
`Development` @ `669ce08` (2026-07-14):

- **71 test files / 1,191 tests / 18,151 lines.**
- **47 files load live `data/` at module import** (`REPO / "data"`); **39 of
  those also assert numeric literals** (822 tests) — every one a candidate to
  fail when a designer legitimately edits data.
- The suite already contains the cure in two forms: `test_buildings_tier_math`
  **derives** expectations from the JSON (tests the formula, survives any
  rebalance), and `TempDataCase.unassign_slot`'s docstring states the doctrine:
  *"Pin the fixture instead of inheriting it from whatever the artists last
  imported."* This plan applies that doctrine to **readers**, not just writers.

This is TestGatePLAN one layer down: that plan pinned fixtures for the 18 tests
asserting live *content state*; this one pins the **data root itself** so the
class of failure is structurally unwritable.

## 2. Decisions (with rationale)

- **D1 — The fixture is a JSON-only snapshot** at `tools/tests/fixtures/data/`,
  mirroring the `data/` tree. `data/` is 65 MB, of which the designer-editable
  surface is 42 JSON files (~small); the rest is PNG/WAV/MP4 assets that no
  pinned-value test reads. `data/balancing_history/` is excluded — it is a
  runtime-populated log (TempDataCase already deletes it from its copies).
- **D2 — One access point**: `tools/tests/fixture_data.py` exposes
  `FIXTURE_DATA` (the snapshot root) and `fixture_copy()` (tempdir copy for
  tests that write). Tests import that name; nothing else in the suite spells
  the fixture path. Refreshing the snapshot is **deliberate**, never automatic:
  `py tools/tests/fixture_data.py --refresh` re-copies live JSON and prints the
  diff; run it only when a schema/content migration requires it, then re-run
  the suite.
- **D3 — A small allowlist stays on live `data/` on purpose.** Tests whose
  *subject* is the live data are validators, not value-asserters, and must keep
  reading it: `test_balancing_data` (schema/content pairs load fail-loud, D-12
  walks), `test_game_boot` (headless boot of the real game — the "does today's
  data actually boot" smoke), `test_agent_forms` (live form roster is the
  dispatch product surface), `test_data_guard` (tests the tripwire itself),
  `test_smoke_pairing` (schema↔content pairing on the live tree). The final
  list lives in ONE place: the FP-4 guard's allowlist, greppable and enforced.
- **D4 — A meta-tier guard makes regression unwritable**: a test that scans
  `tools/tests/*.py` for live-data tokens (`REPO / "data"` and variants)
  outside the allowlist and fails with a pointed message. Same enforcement
  pattern as `test_tiers.py` (a module missing from TIERS is a hard error).
- **D5 — Literal-assert policy for FP-3**: a literal that mirrors a tunable in
  `data/balancing/*` or content in `data/slots.json`/`data/maps/*` becomes a
  value **derived from the fixture** (the `tier_math` pattern). Geometry,
  indices, counts-of-things-constructed-by-the-test, and engine constants stay
  literal. Pinning (FP-2) already makes every literal designer-proof; FP-3 is
  about surviving future *fixture refreshes*, so it targets the worst files,
  not all 39.

## 3. Build order

| Phase | Title | Files touched | Status |
|-------|-------|---------------|--------|
| FP-1 | Freeze the JSON fixture snapshot + access point | `tools/tests/fixtures/data/**` (new), `tools/tests/fixture_data.py` (new) | done (gate PASS 1193) |
| FP-2 | Flip the 47 live loads to `FIXTURE_DATA`; classify allowlist | 35 files flipped, 12 allowlisted | done (gate PASS 1193) |
| FP-3 | Derive data-mirroring literals in the worst files | `test_levelup`, `test_lightning` converted; audit cleared the rest as correctly-literal (geometry/test-inputs/deliberate tuning pins) | done (gate PASS 1193) |
| FP-4 | Guard meta-test: live `data/` reads outside allowlist are a hard error | `tools/tests/test_fixture_guard.py` (new), `conftest.py` (TIERS row) | done (gate PASS 1196; red-verified on a seeded violation) |
| FP-5 | Top-down headless scenario tests (the rewrite's good idea, stolen) | `tools/tests/test_scenarios.py` (new), `conftest.py` (TIERS row) | not started |

### FP-1 — Freeze the snapshot
- **Goal**: `tools/tests/fixtures/data/` mirrors every `data/**/*.json` except
  `balancing_history/`; `fixture_data.py` exposes `FIXTURE_DATA`,
  `fixture_copy()`, and `--refresh`.
- **Tests**: suite still green (nothing consumes the fixture yet).
- **Exit gate**: `py tools/smoke.py` + `py tools/testgate.py check` → PASS.

### FP-2 — Flip the loads
- **Goal**: no test module outside the D3 allowlist references live `data/`.
  Mechanical per file: `REPO / "data"` → `FIXTURE_DATA` (module-level loads),
  or `fixture_copy()` where the test writes. Editor tests keep `TempDataCase`
  (already isolated) — its `shutil.copytree(REPO/"data")` source is fine
  because the copy is per-test and writes never reach the repo; only *readers*
  anchored to live values move.
- **Tests**: full suite; every conversion is behavior-preserving today because
  fixture == live JSON at snapshot time.
- **Exit gate**: full `testgate check` → PASS; grep for `REPO / "data"` in
  `tools/tests/` returns only the allowlist.

### FP-3 — Derive the mirrors
- **Goal**: in the highest-literal files, replace tunable-mirroring literals
  with values computed from the fixture JSON per D5.
- **Tests**: the edited files, then full suite.
- **Exit gate**: full `testgate check` → PASS.

### FP-4 — The guard
- **Goal**: `test_fixture_guard.py` (meta tier) scans test sources for
  live-data tokens outside the allowlist; failure message names the file and
  says "import FIXTURE_DATA from fixture_data instead, or add to the allowlist
  with a justification comment".
- **Exit gate**: guard passes on the repaired tree; deliberately seeding a
  violation makes it fail (verified once, not committed).

### FP-5 — Scenario layer
- **Goal**: `test_scenarios.py` (core tier): headless boots that RUN — place
  buildings, advance phases/waves, assert invariants (hole survives while
  defended, enemies die to defences, love flows) without asserting any tunable
  value. Extends what `tools/smoke.py`'s 5-frame boot starts.
- **Exit gate**: full `testgate check` → PASS.

## 4. Risks / open items

- **Fixture drift vs schemas**: a future schema migration can invalidate the
  snapshot. Mitigation: `--refresh` + the suite run; the guard test does not
  pin schema versions.
- **Hidden asset reads**: a flipped test may transitively load a PNG via the
  registry. Mitigation: fixture keeps the JSON manifest; any test that truly
  renders from disk assets either stays allowlisted with a comment or copies
  the specific asset in its own setUp.
- **`editor` tier**: `TempDataCase` copies live `data/` per test. That is a
  *write* isolation, not a value pin — editor tests that assert live values
  were already rehabilitated by TestGatePLAN (`unassign_slot`); FP-2 only
  moves the remaining module-level readers. If an editor test still inherits a
  live value, it gets the same treatment, not a new mechanism.
- The old migration-tier reflex ("compare against the prototype") must not
  sneak back in via the fixture: the fixture is a *pin*, not an authority —
  `data/` + schemas remain the source of truth (root `CLAUDE.md`).
