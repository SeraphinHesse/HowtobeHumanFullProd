# Fix — the editor preview must draw at the entity's real footprint fit

Follow-up to `fix/anchor-origin-parity` (which closed the anchor-base bug). A
review pass found the last live instance of the same symptom. Branch
`fix/editor-preview-footprint` off `fix/anchor-origin-parity`. Cross-package:
**data + editor** (+ one game-side consistency pin).

**Read**: `editor/CLAUDE.md`, `editor/panels/CLAUDE.md`, `data/CLAUDE.md`,
`engine/render/CLAUDE.md`.

---

## 1. The defect (measured)

`editor/panels/viewport.py:982-988` submits the entity-preview `RenderItem` with
the dataclass defaults — `fit_tiles=0.0`, `scale=1.0` — regardless of what the
entity actually is. The game draws an enemy at
`fit_tiles=float(block["footprint"])`, `scale=float(block["sprite_scale"])`
(`game/enemies/enemy.py:113-116`).

Where those disagree, the editor previews the sprite at the wrong size, and —
because `_anchor_draw_params` resolves the handle through the same `s` — **the
anchor handle still does not match the game**, which is exactly the bug the
designer reported.

**Measured across all 20 enemy slots in `data/` today** (`fit_factor(frame_w,
tile_w=64, footprint) * sprite_scale` vs the editor's `fit_factor(frame_w, 64,
0.0) * 1.0`):

| slot | frame_w | footprint | sprite_scale | game `s` | editor `s` |
|---|---|---|---|---|---|
| `formation_stage_1` | 128 | 1.0 | 1.0 | **0.500** | **1.000** |
| every other enemy/boss slot | — | — | 1.0 | 1.000 | 1.000 |

So **one** slot is affected today: an anchor dragged onto a Formation resolves at
**half** its intended distance in game. `sprite_scale` is 1.0 everywhere, so the
footprint fit is the only live term — but do not hardcode that assumption, it is
a designer-editable balancing value.

This is also an ED-22 WYSIWYG violation independent of anchors: the Formation
currently previews at twice its real in-game size.

---

## 2. The obstacle, and the fix

The editor **cannot import `game/`**, and the slot→footprint chain is currently
expressible only in Python:

- `data/slots.json` enemies groups are labelled `Walker`, `Raider`,
  `Siege Cannon`, `Formation`, `Boss`.
- `data/balancing/enemies.json` `EnemyTypes` keys are `Standard`, `Raider`,
  `SiegeCannon`, `Formation`, `Boss`.
- The link between them lives ONLY in `game/enemies/enemy.py`'s class constants
  (`REGISTRY_GROUP = "Walker"` + `STAT_SUBTREE = ("Standard",)`).

Two of the five names differ, so **matching group label to `EnemyTypes` key by
string is convention, not schema** — precisely what the design pillars forbid
("schemas over convention"). Do not do it.

### 2.1 Make the link DATA (this is the real change)

Add a **required** `registry_group` string to each `EnemyTypes.<Type>` in
`data/balancing/enemies.json` + `data/schemas/enemies.schema.json`: the
`data/slots.json` enemies group label that type's sprites live under.

```
Standard    -> "Walker"
Raider      -> "Raider"
SiegeCannon -> "Siege Cannon"
Formation   -> "Formation"
Boss        -> "Boss"
```

Required, not optional — a new enemy type must not be able to forget it. Use
`/add-balancing-value`. Deterministic validating writer (D-3).

### 2.2 A pure editor resolver

New pure helper (stdlib + `engine` only; Qt-free, pygame-free; **must be added to
`test_editor_viewport.TestPurity`'s import list**) — `editor/sprite_fit.py` or an
addition to `editor/selection.py`, your call:

```python
def slot_draw_fit(data_dir, category_key, slot_key):
    """(fit_tiles, scale) the GAME draws `slot_key` at — the values its
    RenderItem carries. (0.0, 1.0) for any slot with no footprint concept
    (every non-enemy category today) and for an unresolvable slot."""
```

Resolve enemies as: slot → its `data/slots.json` group label → the `EnemyTypes`
entry whose `registry_group` matches → `(footprint, sprite_scale)`. Degrade to
`(0.0, 1.0)` on anything missing (E-37) — never raise; the editor must open on a
broken tree.

### 2.3 Use it in BOTH viewport places — they must agree

`editor/panels/viewport.py`:

- the preview `RenderItem` (`:982-988`) gets `fit_tiles=`/`scale=` from the helper;
- `_anchor_draw_params` passes **the same two values** into
  `sprite_anchor_screen`.

**They must read from one call, not two** — a single local pair used by both, so
they cannot drift. That coupling is the entire point of this fix; if the preview
and the handle ever disagree the bug returns in a new form.

### 2.4 Pin the game/data link so it cannot drift

`game/enemies/enemy.py`'s `REGISTRY_GROUP` constants are now a second home for
`registry_group`. **Do not refactor the game to read the data in this fix** —
just add a test asserting every `Enemy` subclass's `REGISTRY_GROUP` equals the
`registry_group` of the `EnemyTypes` entry its `STAT_SUBTREE` names, for every
subclass. That converts a silent drift into a red test. Note the duplication in
your report as follow-up work.

---

## 3. File scope

**May modify:** `data/balancing/enemies.json`, `data/schemas/enemies.schema.json`,
the fixture mirrors under `tools/tests/fixtures/data/` (**surgical — never a
blanket `--refresh`**; the snapshot has known unrelated staleness), a new/edited
pure editor helper module, `editor/panels/viewport.py`, `tools/tests/**`,
`conftest.py` (TIERS if you add a module), and the docs that describe this
(`editor/panels/CLAUDE.md` — correct its "Known residual (OPEN…)" bullet to
resolved —, `data/CLAUDE.md`, `game/enemies/CLAUDE.md`).

**Must NOT touch:**
- `engine/render/renderer.py`'s `sprite_anchor_screen` / `fit_factor` /
  `block_center_offset` / `flush` — the parity fix is correct; this only feeds it
  better inputs.
- `game/anchors.py`, `game/ui/effects.py`, `game/enemies/combat.py` — no game
  behaviour changes here. The game already draws correctly; the EDITOR was wrong.
- `ProjectileHoming.launch`'s `origin`, `AOE_TRAVEL_TIME`, `BEAM_MIN_TICK`,
  `_predict_lead`, `_chebyshev`, any damage/range/splash expression — **D4**.
- The five deliberately-unanchored trigger events.
- `data/sprites/asset_manifest.json` — **do not touch the designer's authored
  anchors.** Their values were authored against the old broken base and they will
  re-drag them; silently rewriting their data is worse than leaving it odd.

---

## 4. Tests — MINIMAL. A reviewer verifies the rest.

Write **two**, then stop. Do not build out a suite; a `reviewer` pass owns
coverage and edge cases.

1. **The Formation case, end to end.** For `formation_stage_1` with an authored
   anchor, the editor handle's screen point equals the game's resolved screen
   point — the same parity shape as
   `tools/tests/test_anchor_origin_parity.py`. **Run it before the fix and
   confirm it FAILS** (the two should differ by the `s = 0.5` vs `1.0` gap);
   report both numbers.
2. **The drift pin** from §2.4 — every `REGISTRY_GROUP` matches its type's
   `registry_group`.

Fix existing tests only where your change actually breaks them. Use
`TempDataCase`; never write into `data/`; never assert against live `data/`
content.

---

## 5. Exit gate

```bash
py tools/smoke.py
py tools/testgate.py check      # FULL, once, at the end
```

`GATE PASS` or you are not done. The gate is ZERO. `--affected` while iterating;
no manual pytest sanity pass first. A red test clearly outside the blast radius:
note it and stop.

### Quick Test (manual)

1. `py editor/main.py` → select the **Formation** enemy. Its preview is now
   **half the size it was** — that is correct, it now matches the game.
2. Drag its `muzzle` handle onto a recognisable point.
3. `py game/main.py`, reach a Formation: the muzzle VFX fires from that point.
4. Select a **Walker** — unchanged in size and handle position (its `s` was
   already 1.0 on both sides).

---

## 6. Notes for the executor

- **Report LOUDLY**: the pre-fix and post-fix numbers for test 1; any public
  signature change; the `REGISTRY_GROUP` duplication (§2.4) as follow-up.
- **Report, do not fix**: the designer's authored anchors on
  `enemy_stage_1_v1`; the stale `tools/tests/fixtures/data/` snapshot.
- **Leave a short list of what you did NOT verify** — the reviewer picks it up.
- Tag every claim **measured** / **verified** / **inferred** (`/report`).
