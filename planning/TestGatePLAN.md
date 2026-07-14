# TestGatePLAN.md — Fix the suite, then fix the gate

> ## ✅ EXECUTED 2026-07-14 — all six phases landed. See §0.
>
> Do **not** run `/execute-plan-phases` on this doc. That was the header's
> original advice and it was wrong: its default fans coders into parallel
> worktrees, which §4 forbids for TG-1..TG-3 *and* which hides TG-2's entire
> deliverable (in a worktree `test_balancing_parity` used to silently SKIP).
> It was executed serially, in the main tree, as four stacked branches.

## 0. Outcome (measured on `Development` @ `104ac71` → four stacked branches)

| | Before | After |
|---|---|---|
| Wall-clock | **17m 15s** (1035s) | **2m 31s** (152s, `pytest -n auto`) — **6.8×** |
| Failures | **18** | **0** |
| Tests | 1107 | 1123 |
| Repo corruption | suite wrote into `data/` | **none** — guarded |
| The gate | a prose diff, drifted 3 ways | `GATE PASS` — one line |

**The 18 red tests were not editor bugs.** Every one had the same root cause:
they asserted against **live repo content** instead of pinning a fixture. An
artist importing sheets (`2512a84` gave painter/slinger/pistoleer art) or a
designer hitting "set active" on a map (`active_map.json` → `summertest2`)
turned them red. They were testing today's `data/`, not the code. So they were
fixed by pinning the fixtures, not by updating the expectations — which also
restored two tests that were passing while testing nothing.

**Three defects were found that this plan did not know about:**
1. **The suite CORRUPTED the repo.** A full run painted two `deco_rock` tiles
   into `data/maps/summertest2.json`, invented `data/maps/uitestexample.json`,
   and appended `ui_button_v2` to `data/slots.json` — which then made
   `test_ui_skin_variant` compute `_v3` and fail. Leaked Qt widgets outliving
   their tests were writing to disk. TG-1's `destroy()` stopped it;
   `tools/data_guard.py` + a session-scoped conftest fixture are the tripwire.
2. **`pump_until()` timed out in silence**, so a failure read as `[] != [True]`
   — which looks like a bad payload and actually meant "nothing was ever
   emitted". Its 5s budget was really an assumption about machine load; the test
   genuinely takes **14.1s** under a loaded run (`--durations` proved it).
3. **`test_2x_spawns_the_wave_faster_than_1x` used the spawner's UNSEEDED rng**,
   so it failed roughly one run in ten for reasons unconnected to combat speed.

## 1. Context — what was measured

> **The numbers below are the ORIGINAL audit and are STALE.** They were taken on
> `phase-A1-A6-umbrella` @ `7d6819a`, before the lock-removal work deleted
> `test_scope_guard` (14 tests). Re-measured on `Development` @ `104ac71`:
> **1107 tests / 1035.1s / 18 failures / 1 skip** — not 1086/1162s/16/1. This is
> exactly why TG-5 keys the baseline on node-ID *sets* and not counts.

An audit on `phase-A1-A6-umbrella` @ `7d6819a` (Windows 11, Python 3.13.2,
pygame-ce 2.5.7) measured the following.

```
py -m unittest discover -s tools/tests -t .
  → Ran 1086 tests in 1162.100s     (19m 22s)
  → FAILED (failures=16, skipped=1)
```

Three facts drive this entire plan:

1. **The suite is quadratic.** Every editor test's `setUp` builds a
   `MainWindow` and cleans up with `self.addCleanup(self.window.close)`. In Qt,
   `close()` hides a window — it does not destroy it. Each `MainWindow` leaks
   exactly **2,972 widgets**; construction cost then climbs linearly with the
   number already leaked (0.61s → 1.27s over 12 iterations), so total cost is
   quadratic. A full run builds ~134 of them in one process.
   Evidence: sum of all 70 modules timed **separately** = **406s**; the single
   combined `discover` run = **1162s**. The ~756s gap is pure leak overhead.

2. **21% of the tests are 86% of the runtime.** All of it Qt:

   | Module | Tests | Time | Per test |
   |---|---|---|---|
   | `test_editor_map_mode`   | 46 | 197.8s | 4.299s |
   | `test_editor_panels`     | 56 | 109.9s | 1.963s |
   | `test_spawnclaude`       | 70 |  15.5s | 0.222s |
   | `test_game_boot`         |  8 |  13.1s | 1.638s |
   | `test_editor_run_controls` | 5 | 7.7s  | 1.541s |
   | `test_details_panel`     | 17 |   7.7s | 0.453s |
   | `test_editor_asset_import` | 8 |  5.7s | 0.718s |
   | `test_editor_viewport`   | 10 |   4.3s | 0.427s |
   | *the other ~62 modules*  | 862 | ~44s  | ~0.05s |

   The 862 engine/sim/data tests run in ~44s combined. They were never the
   problem.

3. **The gate can never be green, so it has to be a diff — and the diff's
   reference value is prose.** 16 permanently-red tests mean every command file
   (`dispatch`, `execute-phase`, `execute-plan-phases`, `smalltweak`,
   `processtodo`, `finish-domain`) tells agents "no NEW failures — the gate is a
   DIFF, not zero" and then hardcodes the baseline in markdown. That baseline is
   environment-dependent (16 failures / 1 skip in the main tree; **10 / 4** in a
   worktree, because `test_balancing_parity` silently *skips* when it can't
   resolve the prototype path) and has already drifted three ways. Agents
   re-derive it by re-running the whole suite in a clean worktree — which is the
   only rational response to a reference value they cannot trust.

**The load-bearing insight:** the baseline-diffing machinery is a *workaround*
for 16 broken tests. Drive the baseline to zero (TG-2) and the gate collapses
back into a boolean. That is why TG-1 and TG-2 come before the tooling.

## 2. The 16 red tests

They fail deterministically, identically, every run. They are not flaky.

**Six are `test_balancing_parity` — structurally doomed.** The test compares
live `data/balancing/*.json` against the prototype repo forever. The migration
is *done* and the game now deliberately diverges:

| Key | Live | Prototype |
|---|---|---|
| `map:BASE_UNLOCK_COST` | 10 | 5 |
| `core:INCOME_PHASE_DURATION` | 1.505 | 2.0 |
| `core:ROUND_END_DELAY` | 0.6 | 1.0 |
| `enemies:BASE_ENEMY_COUNT` | 4 | 3 |
| `enemies:ENEMY_SCALE_EVERY_N_LEVELS` | 9 | 10 |
| `enemies:SPAWN_RAMP_RANGE` | 0.6 | 0.5 |

These are intentional rebalances. A parity gate against a frozen ancestor gets
redder every time the game is tuned.

**Ten are editor/Qt behavioural drift** — assertions nobody updated after a
behaviour change:

`test_build_finished_reemits_build_state`, `test_context_populates_dropdown_with_markers`,
`test_draft_override_never_touches_disk`, `test_import_save_clear_update_preview_without_restart`,
`test_layer_eyes_filter_submitted_items`, `test_maps_branch_lists_files_with_active_marker`,
`test_markers_reflect_migrated_manifest`, `test_preview_animations_and_dropdown_follow_the_slot`,
`test_reload_assets_sees_disk_change_and_keeps_camera`, `test_unusable_draft_falls_back_instead_of_raising`

Two signatures dominate: `preview_animations()` returns `('idle',)` where the
test expects `()`, and `●` active-markers appear on rows that shouldn't carry
them. **Determine which side is wrong (code or test) before editing** — do not
reflexively update assertions to match current behaviour; one of these may be a
real bug the test caught and nobody read.

## 3. Build order

| Phase | Goal | Status |
|---|---|---|
| **TG-1** | Destroy the Qt window in cleanup — remove the quadratic | ✅ **DONE** `823ca4c` — 17m15s → 5m34s, failure set byte-identical. **7** Qt modules, not the 5 listed below |
| **TG-2** | Drive the baseline to zero — fix/retire the 16 red tests | ✅ **DONE** `4047c01` — **18** red (not 16) → **0**. Parity now runs in a worktree |
| **TG-3** | Adopt pytest + xdist + tier markers (zero test rewrites) | ✅ **DONE** `e4c27df` — 5m34s → **2m31s**; serial == parallel |
| **TG-4** | CI on PR — move the full-suite cost off the agent budget | ✅ **DONE** `e4c27df` — first workflow this repo has ever had |
| **TG-5** | `tools/testgate.py` + `/testgate` — baseline as artifact, not prose | ✅ **DONE** `993c7ab` |
| **TG-6** | `/testgate affected` — Graphify-driven blast-radius selection | ✅ **DONE** `993c7ab` — a tilemap change skips the whole editor tier |

## 4. Execution constraint — read before dispatching

**TG-1 → TG-2 → TG-3 must run in series.** They touch the same five Qt test
files and each one changes the exit gate the next one is measured against:

- TG-1's exit gate is *"no new failures vs the 16-failure baseline"*.
- TG-2's exit gate is *"zero failures"* — and TG-2 is what makes that true.
- TG-3 onwards can assume a green suite, which is the whole point.

Do **not** fan TG-1..TG-3 out as a parallel wave. TG-4, TG-5 and TG-6 may run in
parallel with each other once TG-3 has landed.

**Baseline while working:** until TG-2 lands, the gate is a diff. Measure the
baseline *in the same kind of tree the gate will run in* — a worktree reports
10 failures / 4 skips, the main tree reports 16 / 1. Also check `git status`
first: an uncommitted `data/balancing/` edit adds failures of its own.

---

## TG-1 — Destroy the Qt window in cleanup

**Goal.** Remove the widget leak so suite cost stops being quadratic. Expected:
**19m 22s → ~7m**, with no change in test semantics.

**The fix**, verified in isolation — widget count stays at 0 and construction
time goes flat (0.55s, no growth):

```python
import shiboken6   # ships with PySide6

def setUp(self):
    ...
    self.window = MainWindow(data_dir=self.data_dir)
    self.addCleanup(self._destroy_window)

def _destroy_window(self):
    self.window.close()
    shiboken6.delete(self.window)   # <- close() only hides; this frees
    _APP.processEvents()            # <- let Qt actually reap it
```

**Files (modified).** The five files that construct a `MainWindow`/panel per
test and clean up with a bare `.close()`:
- `tools/tests/test_editor_map_mode.py`
- `tools/tests/test_editor_panels.py`
- `tools/tests/test_editor_run_controls.py`
- `tools/tests/test_editor_viewport.py`
- `tools/tests/test_details_panel.py`

Also audit `test_spawnclaude.py` and `test_editor_asset_import.py` — they
construct Qt dialogs; apply the same treatment where a widget outlives its test.

**Tests.** No new tests. This is a pure test-infrastructure change: the same
1,086 tests must produce the same results, only faster.

**Exit gate.**
1. `py tools/smoke.py` green.
2. `py -m unittest discover -s tools/tests -t .` → **exactly the same
   pass/fail set as the baseline** (16 failures / 1 skip in the main tree, 10 / 4
   in a worktree). This phase must not fix or break a single test.
3. Report the **before and after wall-clock**. Anything under ~9 minutes
   confirms the leak is gone; if it's still ~19m, the widgets are not actually
   being reaped — verify with `len(QApplication.instance().allWidgets())` in a
   loop before claiming success.

---

## TG-2 — Drive the baseline to zero

**Goal.** Zero failures, zero unexpected skips. This is the phase that makes the
exit gate a boolean and retires the whole "which failures were already there?"
problem.

**Files (modified).**
- The 10 editor tests listed in §2 (or the editor code they cover — decide per
  test which side is wrong, and say which you chose and why).
- `tools/tests/balancing_parity_map.json` **or** `tools/tests/test_balancing_parity.py`.

**The parity decision — pick one and state it in the PR:**
- **(a) Record the divergences.** The mapping table already has a vocabulary
  (migrated / `MERGED` / `DROPPED` + reason). Add an `OVERRIDDEN` category
  carrying the new value and the reason it diverges. Keeps the coverage: any
  *unintentional* future drift is still caught. **Recommended.**
- **(b) Retire the test to an on-demand `migration` tier** (see TG-3) that is not
  part of the default gate. Cheaper, but loses the guard entirely.

Whichever you pick, **fix the silent-skip**: `test_balancing_parity` locates the
prototype relative to the checkout, so inside a worktree it skips and proves
nothing. Make the prototype path explicit (env var / config) and make an
unfindable prototype **fail loudly or skip visibly** — never silently green.

**Tests.** The 16 tests themselves are the deliverable. Do not delete a test to
make it pass; fix it or formally retire it with a stated reason.

**Exit gate.**
1. `py tools/smoke.py` green.
2. `py -m unittest discover -s tools/tests -t .` → **0 failures, 0 errors**, and
   the only skips are ones you can name and justify.
3. Verify **in both a worktree and the main tree** — the two must now agree.
4. Delete the stale baseline prose: the "10 failures / 4 skips … 16 / 1"
   paragraph in `.claude/commands/dispatch.md` and the equivalent in every other
   command file that hardcodes it. Replace with "the gate is zero".

---

## TG-3 — pytest + xdist + tier markers

**Goal.** A real runner. **~7m → ~2–3m**, plus timing, selection, and
machine-readable output — none of which `unittest discover` can give you.

**pytest collects `unittest.TestCase` natively — this rewrites zero tests.**

**Files (new).**
- `pytest.ini` (or a `[tool.pytest.ini_options]` block) — testpaths, markers,
  and the default addopts (`-n auto --dist loadfile`).

**Files (modified).**
- `requirements.txt` — add `pytest`, `pytest-xdist`. (Note: pytest is currently
  **not installed and not a declared dependency**, despite 1,086 tests.)
- The command files' `allowed-tools:` — `Bash(py -m unittest*)` becomes the
  pytest/testgate invocation.

**`--dist loadfile` is not optional.** Each test *file* must land in one worker
process: the Qt suites share a module-level `_APP = QApplication.instance()`,
and per-test distribution would fight over it. Grouping by file also quarantines
any residual leak inside a single worker.

**Tier markers** — four tiers, so agents can run the right slice:

| Marker | Tests | Cost | Run when |
|---|---|---|---|
| `core` | ~790 | ~40s | every gate |
| `editor` | ~142 | ~333s (pre-TG-1) | editor changes; full gate |
| `meta` | ~143 | ~19s | `.claude/` or `tools/` changes |
| `migration` | ~12 | ~5s | on demand only |

`meta` is the agent scaffolding — `test_spawnclaude` (70), `test_agent_forms`
(40), `test_scope_guard` (14), `test_build_script` (8), `test_smoke_pairing` (6),
`test_orient_hook` (5). It tests the dispatch rig, not the game. It is a tier,
not a gate.

**Exit gate.**
1. `py -m pytest` → same 1,086 tests collected, **0 failures** (TG-2 landed).
2. Same result serially (`-p no:xdist`) and in parallel — if they disagree, a
   test has hidden shared state; fix it, don't paper over it.
3. `py -m pytest --durations=25` — paste the top 25 into the PR. This is the
   first time this repo has ever been able to see that list.
4. Report wall-clock, serial vs `-n auto`.

---

## TG-4 — CI on PR

**Goal.** There are currently **zero** workflows in `.github/`. Every test run in
this project's history has been paid for out of an agent's token budget and an
agent's wall-clock. Move the redundant "is the whole world still green" check
onto a runner.

**Files (new).** `.github/workflows/tests.yml` — on PR to `Development`:
checkout, Python 3.11+, `pip install -r requirements.txt`,
`py tools/smoke.py`, `py -m pytest -m "not migration" -n auto --dist loadfile`.

**Two constraints that fall straight out of the audit:**
- Qt needs `QT_QPA_PLATFORM=offscreen` and SDL needs the dummy drivers — already
  this repo's headless convention, set them in the workflow `env:`.
- The `migration` tier needs the prototype repo, which won't exist on a runner.
  Exclude it (`-m "not migration"`). This is exactly the argument for TG-3's
  tiering.

**Exit gate.** A deliberately-broken PR goes red; a clean PR goes green. Report
the runner wall-clock.

---

## TG-5 — `tools/testgate.py` + `/testgate`

**Goal.** Make the baseline a machine-readable artifact instead of a paragraph,
and collapse per-gate agent output from **~3.3k tokens of tracebacks to ~40**.

> Even with a zero baseline (TG-2), this earns its keep: it turns the gate into
> one line an agent can read without reasoning, and it makes any *future*
> tolerated failure impossible to lose track of.

**Files (new).**
- `tools/testgate.py`
- `.claude/commands/testgate.md`
- `.gitignore` — add `.test-baseline.json` *unless* you commit it to the umbrella
  branch (see below; committing it is the recommendation).

**Interface.**
```
py tools/testgate.py snapshot   # run once, write .test-baseline.json
py tools/testgate.py check      # run, diff vs baseline, print ONLY the delta
py tools/testgate.py check --affected   # TG-6
```

Output — the only thing an agent ever reads:
```
GATE PASS  1086 ran · 0 known · 0 new · 0 fixed · 0 unexpected skips
```
```
GATE FAIL  1 NEW failure
  test_boss.TestBoss.test_dead_goal_repaths — AssertionError: 4 != 3
  (0 known baseline failures suppressed · 1 newly FIXED: test_markers_reflect_migrated_manifest)
```

**Four design requirements. These are the plan; do not simplify them away:**
1. **Key on the set of test node-IDs, not counts.** Counts are exactly what
   drifted (a memory note recorded 980 tests; the real number is 1,086). A set is
   exact and survives adding tests.
2. **Stamp the baseline with the git SHA and whether it was taken in a
   worktree.** A stale baseline must announce itself rather than quietly lie.
3. **Report newly-FIXED tests, not just new failures.** Today, if an agent
   accidentally repairs a tolerated failure, nobody notices and the next baseline
   is silently wrong.
4. **An unexpected skip counts as a failure.** This is what permanently kills the
   `test_balancing_parity` worktree trap.

**Wiring — this is the part that saves the tokens.** The orchestrator runs
`snapshot` **once** at umbrella creation (step 1 of `/execute-plan-phases`
already records a baseline — this replaces that prose step) and **commits
`.test-baseline.json` to the umbrella branch**. Every coder and reviewer subagent
then *inherits* it instead of re-deriving it in a fresh worktree. That single
change is the direct fix for the "run the suite, then run it again to find out
what was already broken" waste.

**Files (modified).** Every command file that currently says "run the suite; the
gate is a DIFF": `dispatch.md`, `execute-phase.md`, `execute-plan-phases.md`,
`smalltweak.md`, `processtodo.md`, `finish-domain.md`, and the `add-*` skills.
They all collapse to a single `py tools/testgate.py check` line.

**Tests.** `tools/tests/test_testgate.py` — fixture-driven, no real suite run:
a synthetic baseline + synthetic result set, asserting new/fixed/unexpected-skip
detection, node-ID-set semantics, and the stale-SHA warning.

**Exit gate.** `snapshot` then `check` on an unchanged tree → `GATE PASS`.
Deliberately break one test → `check` names exactly that test and nothing else.
Delete a test that was in the baseline → reported, not crashed.

---

## TG-6 — `/testgate affected`

**Goal.** Stop running 1,086 tests to validate a change that touched one package.

**This repo already has the hard part built.** Graphify is extracted, gitignored,
and rebuilt on every commit by a `post-commit` hook. `graphify affected "X"`
already answers "what is the blast radius of this change".

**Files (modified).** `tools/testgate.py` — add `--affected`:
`git diff --name-only <base>` → changed symbols → `graphify affected` → the test
modules in the radius → run only those (always union'd with the `core` tier,
which costs ~40s and is cheap insurance).

**Wiring.** Coders in worktrees run `check --affected` (seconds). The
orchestrator runs the full `check` **once**, on the merged umbrella. Six coders
each running the full suite means six agents testing code five of them never
touched.

**Exit gate.** For a change confined to `engine/tilemap.py`, `--affected` selects
the tilemap/coords/render tests and skips the entire editor tier — and its
verdict agrees with a full run. Report the selected set and the time saved.

## 5. Risks / open items

- **TG-1 may not be a clean win in every file.** If a test *relies* on a leaked
  widget surviving (e.g. asserting on a previous window's state), destroying it
  will surface that as a new failure. That's a real bug being exposed, not a
  regression — report it, don't work around it.
- **TG-2's ten editor tests may not all be test bugs.** At least one may be a
  genuine defect the test caught and nobody read. Decide per test; do not
  bulk-update assertions to match current behaviour.
- **xdist can expose hidden shared state** (module-level caches, the `data/`
  temp-copy pattern, pygame globals). If serial and parallel disagree, that is a
  real isolation bug — fix it rather than pinning to serial.
- ~~**The lock protocol contradiction is unresolved.**~~ **RESOLVED before this
  plan ran** — commits `5adbfb9`, `2da8587`, `d8beba8` deleted
  `.claude/hooks/scope_guard.py`, `tools/tests/test_scope_guard.py` (14 tests),
  `editor/locks.py`, the `start`/`finish`/`resume`/`merge-domain` commands, and
  the `PreToolUse` wiring. `settings.json` now hooks only `orient.py`. The
  `meta` tier shrank accordingly (143, not the 143-with-scope_guard implied).
- ~~**Housekeeping: 17 stale agent worktrees.**~~ There are **2**
  (`phase-A5-skinned-button`, `phase-A4-slice-editor`), and **do NOT delete
  them**: each holds *uncommitted* Python work (a `HudSprite` import, an
  `anim_ms` helper — live 10L-A code). They are not stale, they are parked.
  Whoever cleans up must land or discard that work first.
- **`data/` in the working tree is dirty and it is the USER's**, not the suite's:
  `slots.json` (+`ui_button_v2`), `maps/summertest2.json` (+2 deco), and an
  untracked `maps/uitestexample.json` are the damage the pre-TG-1 suite did, left
  in place at the user's request. The suite no longer causes this
  (`DATA CLEAN 167 file(s)`), but those three files still need a human decision.
