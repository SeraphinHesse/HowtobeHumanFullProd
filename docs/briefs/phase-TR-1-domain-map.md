# Phase TR-1 — Domain map (`tools/test_domains.py`)

Source plan: `planning/TestRunnerPLAN.md` §1 (Vision), §2 D1, `## TR-1 — Domain map`
(planning/TestRunnerPLAN.md:116-134). Package: **tools**. Depends on: nothing.
Blocks: TR-3 (`editor/test_runner.py` maps each finished test file to a domain,
planning/TestRunnerPLAN.md:168-174) and TR-5 (one panel row per domain,
planning/TestRunnerPLAN.md:216-221).

---

## 1. Behavioral spec

**What the phase must produce.** A Python table, importable with no Qt and no
pygame, that answers one question: *which area of the game does this test module
belong to?* Nothing in TR-1 runs pytest, launches a process, or reads `data/`.

Contract, restated from the plan:

- The domains are the panel rows named in the Vision — Buildings, Enemies, Map,
  UI, Engine, Editor, Data (planning/TestRunnerPLAN.md:13-14) — exposed as the
  keys of `DOMAINS`, plus a display label per domain and
  `domain_for(module) -> str` (planning/TestRunnerPLAN.md:122-124).
- **Exactly one domain per module. No catch-all.** "zero is a hard error, two is
  a hard error — the `ci_shards` rule" (planning/TestRunnerPLAN.md:127-129); D1
  spells out why a catch-all is forbidden: a new unclaimed test file must be a
  hard error, "not a row that quietly reads `0 tests`"
  (planning/TestRunnerPLAN.md:59-66).
- **A table, not a convention.** D1 rejects deriving the area from the filename
  ("breaks silently the first time a file does not fit the pattern") and rejects
  a `data/` JSON file ("would put build metadata in the game's value store")
  (planning/TestRunnerPLAN.md:63-66).

**The doctrine being copied** is `tools/ci_shards.py`. Read its module docstring
before writing anything: the two rules it keeps are stated at
tools/ci_shards.py:21-28, and rule 2 — "Every test module is selected by EXACTLY
one shard… Zero shards means a module silently stops running" — is the rule TR-1
re-applies one layer over. Its enforcement test is
tools/tests/test_ci_shards.py:45-64, and the on-disk module discovery helper it
uses is tools/tests/test_ci_shards.py:22-24
(`{p.stem for p in TESTS_DIR.glob("test_*.py")}`). Copy that shape.

**Existing facts you can rely on (verified):**

- `tools/` is a package (`tools/__init__.py` exists), and modules there are
  imported as `from tools import ci_shards` (tools/tests/test_ci_shards.py:17).
- `REPO` / `TESTS_DIR` are already computed this way at
  tools/ci_shards.py:34-35; mirror it rather than inventing a new anchor.
- A tuple-of-filenames-with-`.py` table already exists as
  `HEAVY_EDITOR_FILES` (tools/ci_shards.py:43-48). `DOMAINS` values use the same
  spelling (`"test_boss.py"`, not `"test_boss"`), because the plan's Quick Test
  calls `domain_for('test_boss.py')` (planning/TestRunnerPLAN.md:133-134) and
  because TR-3 will be parsing node-IDs that carry the `.py`.
- `conftest.TIERS` (conftest.py:36) is the sibling table mapping module **stem**
  → tier. It is *not* the domain map and TR-1 must not derive from it: tiers say
  *how fast/what harness*, domains say *what area of the game*. It is, however,
  the reason your new test module needs a registration — see §3.
- `pytest.ini:2` sets `testpaths = tools/tests`, so a production module named
  `tools/test_domains.py` is **not** collected by a normal run despite its
  `test_` prefix. Do not rename it; the plan names this path
  (planning/TestRunnerPLAN.md:122). Do give it a module docstring that does not
  read like a test file.
- There are ~130 modules matching `tools/tests/test_*.py` today (**measured**,
  directory listing). Every one of them must appear in `DOMAINS`.

**Behaviour of `domain_for`:**

- Accepts a bare stem (`"test_boss"`), a filename (`"test_boss.py"`), and a
  path-ish string (`"tools/tests/test_boss.py"`), plus `Path` objects. Normalise
  with `Path(module).name` then strip a trailing `.py`.
- Returns the domain key (lowercase, e.g. `"enemies"`).
- **Unknown module raises** (`KeyError`) with a message that names the module and
  says to add it to `DOMAINS` in `tools/test_domains.py`. It must never return a
  default, `None`, or `"other"` — that is D1's whole point.

**Classification rule** (write it into the module docstring so the next person
extending the table applies the same rule). Assign by the code area the test
predominantly exercises, first match wins:

1. imports `editor/**` → `editor`
2. validates/loads `data/**` JSON, schemas or the slot registry → `data`
3. imports only `engine/**` (ECS, tilemap, physics, render primitives) → `engine`
4. otherwise the `game/` balancing domain it exercises — `buildings`, `enemies`,
   `map`, `ui` (the prototype's five domains, named in the root `CLAUDE.md`
   §"Step 1" file-ownership note).

Pinned anchors the tests must hold: `test_boss.py` → `enemies` (the plan's Quick
Test, planning/TestRunnerPLAN.md:133-134); `test_editor_map_mode.py` → `editor`;
`test_tilemap_model.py` → `map`; `test_buildings_placement.py` → `buildings`;
`test_hud_panel.py` → `ui`; `test_components.py` → `engine`;
`test_balancing_data.py` → `data`.

**Deviation from the plan you must implement — read this.** The seven Vision
domains do not cover the ~14 `meta`-tier modules (conftest.py:37-51:
`test_agent_forms`, `test_build_script`, `test_ci_shards`, `test_data_guard`,
`test_fixture_guard`, `test_orient_hook`, `test_qt_harness`,
`test_smoke_pairing`, `test_spawnclaude`, `test_test_guard`, `test_testgate`,
`test_tiers`, and the new `test_test_domains` itself). They test agent
scaffolding, not the game, so forcing them into `data` or `engine` would be a
lie in a panel row. Since D1 forbids a catch-all, add an **eighth** domain:

- key `tooling`, label `"Tooling & Agents"`, holding exactly the meta-tier
  modules by the rule "tests the repo's own scaffolding, not the game".

This is a superset of the plan's list, not a contradiction of it: TR-3/TR-5
render one row per `DOMAINS` key, so the extra row costs nothing downstream. If
the orchestrator overrides this (folding `tooling` into `engine` under the label
`"Engine & Tooling"`), it is a one-line change to the table and the labels — do
not redesign around it.

---

## 2. Architecture plan

`tools/test_domains.py`, ~120 lines including the docstring, no imports beyond
`pathlib` (and `argparse`/`json` only if you add the optional `_main`). Public
surface:

```
REPO, TESTS_DIR              # same derivation as tools/ci_shards.py:34-35
DOMAIN_LABELS: dict[str, str]  # key -> display label, in ROW ORDER
DOMAINS: dict[str, tuple[str, ...]]  # key -> test filenames ("test_boss.py")
domain_for(module) -> str    # stem | filename | path | Path; raises KeyError
modules_for(domain) -> tuple[str, ...]   # thin, for TR-3's per-area re-run
```

- **`DOMAIN_LABELS` defines row order.** `dict` preserves insertion order; TR-5
  iterates it to build rows, so order the keys the way the panel should read
  them (Vision order, `tooling` last). Do not add a separate `DOMAIN_ORDER`.
- **`DOMAINS` keys must equal `DOMAIN_LABELS` keys** — pinned by a test, because
  a label-less domain renders as a blank row and a domain-less label renders as
  an empty one.
- **`domain_for` builds its reverse index once**, at import, into a private
  module-level `_BY_MODULE: dict[str, str]` keyed on the **stem** (so both
  spellings resolve). Build it with an explicit duplicate check that raises
  `ValueError` at import time if a module appears in two domains — the table
  being self-inconsistent should be loud even for a caller that never runs the
  test suite.
- **No disk access at import.** `TESTS_DIR.glob` belongs in the *test*, not in
  the module: the table is the declaration, the disk is the thing checked
  against it. This mirrors tools/ci_shards.py, which declares and never
  discovers.
- Optional (do it only if it costs nothing): a `_main()` behind
  `if __name__ == "__main__":` printing `label  count` per domain, mirroring
  tools/ci_shards.py:90-103. No CLI flags are required by any later phase.

`tools/tests/test_test_domains.py` — plain `unittest`, no fixtures, no Qt, no
`TempDataCase`, does not import pytest or run anything. Structure it after
tools/tests/test_ci_shards.py (same docstring-explains-why-this-is-load-bearing
style). Required cases:

1. **Every module on disk is claimed by exactly one domain.** Discover with
   `{p.stem for p in TESTS_DIR.glob("test_*.py")}` (tools/tests/test_ci_shards.py:22-24),
   count claims, assert the `never` list and the `twice` list are both empty,
   with messages naming the offenders and saying what goes wrong (a new test
   file with no domain would be invisible in the panel).
2. **No stale entry**: every filename in `DOMAINS` exists on disk (mirrors
   tools/tests/test_ci_shards.py:73-78).
3. **Every domain names at least one real file** (planning/TestRunnerPLAN.md:129).
4. **`DOMAINS` keys == `DOMAIN_LABELS` keys**, and every label is a non-empty
   string.
5. **`domain_for` is exhaustive and consistent**: for every module on disk it
   returns a key in `DOMAINS`, and that key's tuple contains the file.
6. **Spelling tolerance**: `domain_for("test_boss")`, `"test_boss.py"`,
   `"tools/tests/test_boss.py"` and `Path(...)` all give the same answer.
7. **No catch-all**: `domain_for("test_not_a_real_module.py")` raises `KeyError`.
8. **The pinned anchors** from §1 (at minimum `test_boss.py` → `enemies`, which
   is the plan's Quick Test).
9. **No duplicate filename inside one domain tuple.**

Keep it to these. Bare-minimum coverage is the house preference; do not add
parametrised sweeps over all ~130 modules beyond case 1 and 5.

---

## 3. File scope + shared-file contract

**You may create/edit exactly these:**

| File | Action |
|---|---|
| `tools/test_domains.py` | new |
| `tools/tests/test_test_domains.py` | new |
| `conftest.py` | **modified — one line, see contract below** |

Nothing else. Do not touch `tools/ci_shards.py`, `tools/testgate.py`,
`.claude/hooks/test_guard.py`, `.github/workflows/tests.yml`, `editor/**`, or
`data/**`.

**Shared file: `conftest.py` (`TIERS`).** Every later phase in this plan adds a
test module and therefore a `TIERS` entry, so this file is touched by TR-1,
TR-2, TR-3, TR-4 and TR-5. It is mandatory, not optional: `test_tiers.py`
(`test_every_module_has_a_tier`, tools/tests/test_tiers.py:25-31) fails hard for
any module missing from `TIERS`, and CI's `meta` shard selects on the marker
(tools/ci_shards.py:79).

Exact insertion point for TR-1: the `meta` block of `TIERS` (conftest.py:37-51),
which is alphabetically ordered. Insert **one** line between the
`"test_test_guard"` entry (conftest.py:48) and `"test_testgate"`
(conftest.py:49):

```python
    "test_test_domains": "meta",   # the test-module -> game-area table
```

Add nothing else to `conftest.py` — no new tier, no helper, no import. Later
phases insert their own single lines elsewhere in the same dict (TR-3/TR-4's
runner and report tests are `core`, TR-5's panel test is `editor`); leaving the
surrounding lines untouched keeps those merges trivial.

**Contract for downstream phases** (do not implement, just do not foreclose):
TR-3 imports `DOMAINS`/`domain_for`/`modules_for` from `tools.test_domains` and
TR-5 iterates `DOMAIN_LABELS` for rows. Keep the module import-cheap and
dependency-free so `editor/test_runner.py` stays Qt-free (D6,
planning/TestRunnerPLAN.md:95-98).

---

## 4. Exit gate + Quick Test

Test policy for this phase is root `CLAUDE.md` §"Test Suite Policy" and nothing
else. You are a subagent: run only the two commands below. Do **not** run the
full suite, `py tools/testgate.py check`, `--affected`, or any tier sweep
(`-m core` / `-m editor` / `-m meta`) — the `test_guard.py` hook denies all four
from a subagent. The single full gate is the main session's step at handoff.

```bash
py tools/smoke.py
py -m pytest tools/tests/test_test_domains.py -q
py -m pytest tools/tests/test_tiers.py -q        # you edited conftest.TIERS
```

`GATE PASS` / all-green on both pytest files, or you are not done. `test_tiers`
is in scope only because §3 requires a `conftest.py` edit; if you somehow did not
touch `conftest.py`, you did §3 wrong.

**Quick Test** (run by the orchestrator or user, not by you):

```bash
py -c "from tools.test_domains import domain_for; print(domain_for('test_boss.py'))"
# expects: enemies
py -c "from tools.test_domains import DOMAINS, DOMAIN_LABELS; print([(DOMAIN_LABELS[k], len(v)) for k, v in DOMAINS.items()])"
# expects: one (label, count) pair per panel row, in row order, counts summing
# to the number of tools/tests/test_*.py files on disk, no count of 0
```

**Report** (per `/report`): the domain counts as **measured**, the two pytest
results as **measured**, and call out explicitly whether you kept the `tooling`
domain or the orchestrator's override — plus any module whose classification you
were not confident about, by name, so a human can correct the table cheaply.
