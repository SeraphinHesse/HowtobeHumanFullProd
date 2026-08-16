# Phase N2 — The four render paths

Section S4 (Seasons) of `planning/MasterSheetColumnsPLAN.md`. Depends on **N1**
(`RunState.season`), which lands first and is already merged into your base
branch.

**One line:** seasonal slots follow the season; everything else is untouched.

---

## 1. Behavioral spec

### What exists today (verified, with citations)

- **S1 built the whole cut path already.** `AssetStore._column_block(entry,
  sheet, column)` (`engine/assets/store.py:219`) is the ONE place a master
  column is resolved, and `_frame_surface` (`engine/assets/store.py:238`) is the
  ONE place it is applied. Its rule (`engine/assets/store.py:225-228`):

  ```python
  if entry.column_mode == "manual" or column is None:
      block = entry.column          # the designer's stored column wins
  else:
      block = column                # the caller's LIVE column wins
  ```

  followed by the D7 two-sided clamp to the sheet's last column
  (`engine/assets/store.py:229-233`).
- **The renderer already forwards it.** `engine/render/renderer.py:204` calls
  `self._assets.frame(item.slot_key, item.animation, item.anim_time_ms,
  column=item.column)` — as a keyword.
- **`RenderItem` already carries it.** `engine/render/item.py:42` —
  `column: int | None = None`, the LAST field of the dataclass.
- **`SpriteAnimator` already emits it.** `engine/core/sprite_animator.py:28` —
  `column: int = -1` (a `-1` sentinel because a Component field must be
  JSON-safe, so `int | None` was rejected), mapped to `None` at
  `engine/core/sprite_animator.py:49`: `column=self.column if self.column >= 0
  else None`.

So the ENTIRE remaining gap is: **nothing on the tile render paths ever sets
`RenderItem.column`.** Every tile item is emitted with the field left at its
`None` default, so every tile resolves from its stored `entry.column` forever.
N2 closes exactly that gap and nothing else.

### THE ONE RULE — `column=None`, never `column=0`

**`0` is a real season value, not "unset".** Season 0 is the first season (it is
what `era_of_round` returns for rounds 1..N — `engine/era_math.py:46-52`) and
must stay addressable; D7 clamps *to* the last column, so both `0` and the clamp
target are legitimate live values.

Consequences, all binding:

1. `band_render_items` and `visible_render_items` take **`column=None`** as
   their default keyword. **NOT `column=0`.**
2. `spawn_deco_render_items` and `condition_render_items` likewise take
   **`column=None`**.
3. **Any check that treats `0` as falsy/absent is a BUG.** Concretely, all of
   these are wrong and must not appear anywhere in this diff:
   - `if column:` (use `if column is None:` when you must branch at all)
   - `column or entry.column`
   - `column = column or 0`
   - any truthiness test on the column value.

   The correct handling in the four emitters is **no branch at all**: the value
   is passed straight through, opaque, onto every emitted `RenderItem`. The one
   place a `None` check is legitimate already exists and belongs to S1
   (`engine/assets/store.py:225`) — do not add a second one.
4. The plan doc's Phase N2 block (`planning/MasterSheetColumnsPLAN.md:788`)
   literally says `column=0`. **That line is superseded by S1's
   post-integration fixes** (which changed `RenderItem.column` from `int = 0` to
   `int | None = None`, closing open finding #1 in
   `docs/handoffs/section-S1.md:36-39`) and is **wrong**. Write `column=None`.

   Reviewer: a diff containing `column=0` as a default, or any falsy test on a
   column, is a reject — not a nit.

### Behaviour after this phase

| Situation | Result | Why |
|---|---|---|
| Tile slot, `column_mode: "season"`, `column_width: 4`, season 2 | frames cut from master column 2 | caller column wins (`store.py:227`) |
| Same slot at **season 0** | frames cut from master column **0** — NOT from its stored `column` | `0` is a live value; only `None` falls back |
| Tile slot, `column_mode: "manual"` (or key absent) | frames cut from its stored `column`, season ignored | `store.py:225`, D3 |
| Any slot with no `column_width` (omitted ⇒ 0) | **byte-identical** to today's pixels | `block * 0 + col == col` |
| Season 5 on a 2-column sheet | holds at column 1 | D7 clamp, per sheet (`store.py:229-233`) |
| `main_menu_bg` / every enemy / every building | **unchanged** — no column ever passed | D8 scope fence |

**Passing the column everywhere is safe, and NO per-slot opt-in list belongs in
code.** A slot on `column_mode: "manual"` ignores it entirely (D3), and a slot
with no `column_width` resolves byte-identically. **The designer's mode flag IS
the opt-in.** Do not add a category allow-list, a slot-key set, or a
`if slot.startswith("tile_")` filter — any of those is a re-plan and a reject.

---

## 2. Architecture plan

### 2.1 The engine stays ignorant (D12)

`engine/tilemap.py` learns **nothing** about seasons. It gains an **opaque**
`column` keyword that it copies onto every `RenderItem` it emits — exactly the
way it already takes `tint_for_code` (`engine/tilemap.py:322`, `:369`) without
knowing what a terrain code means. No import of anything season-shaped, no
`era_math`, no balancing read, no comment that names a round number as an
authority. The word "season" may appear in the docstring only as an *example* of
what a caller might drive it with, alongside "a building's colour".

Same rule for `game/map/spawn_deco.py` and `game/map/conditions.py`: they are
pure pass-throughs. They do not read `RunState`.

### 2.2 The four emitters

Each gains one keyword-only-style parameter defaulting to `None`, threaded onto
**every** `RenderItem` that function constructs:

| Emitter | File:line (current) | Items to thread |
|---|---|---|
| `visible_render_items` | `engine/tilemap.py:322` | terrain (`:344`), base (`:351`), camera (`:356`), deco (`:363`) |
| `band_render_items` | `engine/tilemap.py:369` | ground (`:400`) |
| `spawn_deco_render_items` | `game/map/spawn_deco.py:56` | tree (`:93`) |
| `condition_render_items` | `game/map/conditions.py:24` | condition art (`:62`) |

Thread it onto **every** item in `visible_render_items`, including base and
camera — they are already gated by their own flags at the call site
(`terrain=False` at `game/main.py:1890`), and a partial thread is a latent
inconsistency for no gain. Base/camera slots are `manual` in practice, so the
value is inert there.

`render_items` (`engine/tilemap.py:285`, the whole-map emitter) is **out of
scope** — the plan names exactly two engine emitters, and its consumers are
tests and the editor, neither of which has a season. Do not touch it.

### 2.3 The four submit sites (all in `game/main.py`)

All four pass `column=session.state.season`. `session` is the in-scope name at
this point in the frame loop (verified: `session.state.phase` at
`game/main.py:1852`); `world.session.state` is the same object.

**Ground cache callback — read the season INSIDE the lambda body**, not as a
bound default argument. `GroundCache.ensure` invokes the callback only on
rebuild (`engine/render/ground_cache.py:91-119`), so a value captured at lambda
construction is fine only because the lambda is rebuilt every frame — reading it
in the body is the version that stays correct if that ever changes.

### 2.4 Dependency on N1 — the ground cache

The ground layer is a **cached surface**. `ensure` repaints only on first
use / resize / zoom / `invalidate` / scroll-past-margin
(`engine/render/ground_cache.py:103-119`). So passing the season through the
callback is necessary but **not sufficient** for gameplay+background tiles to
step: something must call `ground_cache.invalidate()` when the season changes.

**That is N1's work, not N2's** (`planning/MasterSheetColumnsPLAN.md`, Phase N1
design notes: "A season change invalidates the ground cache"). N2 must **not**
add an invalidate call. If the Quick Test shows ground tiles not stepping until
a zoom/resize, that is an N1 defect — report it, do not patch it here.

### 2.5 Scope fence (D8)

Deliberately untouched, and a diff that touches them is a reject:

- the `backgrounds` category / `main_menu_bg`;
- every enemy path;
- every building path (that is S3's `building_color`, a different section);
- the HUD pass (`engine/render/renderer.py` HUD branch — it passes no column by
  design, `docs/handoffs/section-S1.md:23`);
- `engine/assets/store.py` (S1 owns it; it is already correct);
- `engine/render/item.py`, `engine/core/sprite_animator.py`,
  `engine/render/renderer.py` (all already correct — **do not "fix" the `None`
  default or the `-1` sentinel**);
- `engine/tilemap.render_items`;
- the wall-art emitter (`game/main.py:1926`).

---

## 3. File scope + shared-file contract

### 3.1 Files you may modify

| File | Change |
|---|---|
| `engine/tilemap.py` | `column=None` param + thread onto items in `visible_render_items` (`:322`) and `band_render_items` (`:369`) |
| `engine/CLAUDE.md` | the "Three emitters" bullet (`:82-98`) — add the `column` keyword to the two emitter lines, one clause each, D12 framing |
| `game/main.py` | **the four submit sites ONLY** (see 3.3) |
| `game/map/spawn_deco.py` | `column=None` param on `spawn_deco_render_items` (`:56`) + thread onto the item at `:93` |
| `game/map/conditions.py` | `column=None` param on `condition_render_items` (`:24`) + thread onto the item at `:62` |
| `game/map/CLAUDE.md` | the `conditions.py` emitter signature line (`:219-224`) |
| `tools/tests/test_asset_store.py` | 2 new tests in `TestColumnBlock` (`:434`) |
| `tools/tests/test_tilemap_model.py` | propagation tests for the 2 engine emitters |
| `tools/tests/test_spawn_deco.py` | propagation test |
| `tools/tests/test_condition_art.py` | propagation test |

`spawn_deco_render_items` does **not** appear in `game/map/CLAUDE.md`
(**measured** — `grep` returns 0 hits), so no doc edit is required for it. Do not
add a section for it; that is scope creep.

### 3.2 Test homes — corrections you must not "fix" back

Three factual corrections to the plan doc's Phase N2 block, all **measured**:

1. **`tools/tests/test_map_conditions.py` DOES NOT EXIST.** The plan names it;
   the repo does not have it. Do not create it.
2. **`tools/tests/test_tile_conditions.py` does NOT exercise
   `condition_render_items`** (0 occurrences). The file that does is
   **`tools/tests/test_condition_art.py`** (9 occurrences). The condition
   propagation test goes there.
3. `tools/tests/test_tilemap_model.py` exercises **both** engine emitters
   (`band_render_items` ×5, `visible_render_items` ×several). Both propagation
   tests go there.

**Decision on test shape (the orchestrator asked for (a) or (b)):** the two new
resolution tests go into the **existing** `TestColumnBlock` class in
`tools/tests/test_asset_store.py:434`, and the propagation tests go next to
their emitters — because four of the plan's five resolution assertions are
*already pinned* by that class (seasonal-caller-overrides-stored `:462-474`,
manual-ignores-caller `:475-483`, no-`column_width`-byte-identical `:447-460`,
D7-clamp `:484-490`, plus negative-clamp `:491-499`), so a new
`test_season_columns.py` would be a second home for one story and would
duplicate work S1 already did. See the OPEN item below.

### 3.3 Shared-file contract — `game/main.py` is touched by BOTH N1 and N2

`game/main.py` is edited by N1 and by N2. The split is **exact**:

- **N1 owns** the season-clock recompute site: either `game/core/payday.py:277`
  (`state.round_num += 1`) or the host's phase-edge watcher chain near
  `game/main.py:1710-1750` (`gp["prev_phase"]`), plus the
  `ground_cache.invalidate()` call that goes with it (the hook is wired at
  `game/main.py:774`).
- **N2 owns ONLY the four submit sites at `game/main.py:1877-1909`.**
  **N2 must not touch the recompute site, must not touch
  `game/core/payday.py`, and must not add or move an `invalidate()` call.**

Exact insertion points, **verified against the file at time of writing** (the
plan doc's ranges `1877-1886` / `1889-1892` had drifted by a line or two):

**Site 1 — gameplay + background tiles, via the ground cache callback.**
`game/main.py:1877-1881`. Current text:

```python
            ground_cache.ensure(
                view_w, view_h,
                lambda dmn, dmx, smn, smx: tilemap.band_render_items(
                    map_doc, dmn, dmx, smn, smx,
                    code_overrides=world.tile_map.terrain_overrides))
```

Add `column=session.state.season` to the `band_render_items(...)` call inside
the lambda (line 1881), read in the lambda BODY (§2.3). Leave the surrounding
comment block (`:1870-1876`) and `ground_cache.blit` (`:1886`) untouched.

**Site 2 — map-authored deco, via `visible_render_items`.**
`game/main.py:1889-1892`. Current text:

```python
            for item in tilemap.visible_render_items(
                    map_doc, cmin, cmax, rmin, rmax, terrain=False,
                    camera=show_camera_start, anim_time_ms=int(deco_clock_ms)):
                renderer.submit(item)
```

Add `column=session.state.season` to the argument list (line 1891). Do not touch
`cs.visible_tile_window` at `:1888`.

**Site 3 — runtime spawn-band trees.** `game/main.py:1899-1902`:

```python
            for item in spawn_deco_render_items(
                    world.tile_map, cmin, cmax, rmin, rmax, tree_slots,
                    anim_time_ms=int(deco_clock_ms)):
                renderer.submit(item)
```

Add `column=session.state.season` (line 1901).

**Site 4 — tile conditions.** `game/main.py:1906-1909`:

```python
            for item in condition_render_items(
                    world.tile_map, cmin, cmax, rmin, rmax, condition_art,
                    anim_time_ms=int(deco_clock_ms)):
                renderer.submit(item)
```

Add `column=session.state.season` (line 1908).

The next block down (`# Edge-wall art`, `game/main.py:1910+`, the
`wall_render_items` call at `:1926`) is **out of scope** — stop before it.

### 3.4 `state.season` may not be visible in your tree

`RunState.season` is created by N1 (**verified absent** from
`game/core/game_state.py` at the time this brief was written — `grep -n season`
returns nothing). N1 lands first and will be in your base branch. **Write the
code against `session.state.season` regardless.** If it is genuinely absent when
you start, STOP and report the missing dependency to the orchestrator; do not
invent a local season, do not add a `getattr(..., "season", 0)` shim, and do not
re-derive it from the round number.

### 3.5 Tests — the BARE MINIMUM, and no more

Exactly six tests. Do not add coverage beyond this list; a reviewer asking for
more is out of policy.

In `tools/tests/test_asset_store.py`, class `TestColumnBlock` (`:434`) — copy the
`entry(...)` / `make_grid_sheet` / `grid_colour` fixture pattern already in that
file (`:83-127`):

1. **`test_season_zero_uses_column_zero_not_the_stored_column`** — THE
   regression test for the `0`-is-falsy bug. An entry with
   `column_mode="season"`, `column_width=4`, stored `column=2`, resolved with
   `store.frame(..., column=0)` must cut from master column **0**
   (`grid_colour(0, 0)`), not from the stored column 2. A `column or ...`
   anywhere in the chain fails this test — that is the point of it.
2. **`test_live_season_clamps_on_a_two_column_sheet`** — D7 driven by the LIVE
   caller (the existing clamp test at `:484-490` drives it from the *stored*
   column, which is a different branch). A 2-block sheet (`cols=8`,
   `column_width=4`), `column_mode="season"`, resolved with `column=5`, must cut
   from block 1.

Propagation — one test each, asserting the value rides onto **every** emitted
item, and asserting the **default is `None`** (not 0):

3. `tools/tests/test_tilemap_model.py` — `visible_render_items(..., column=2)`
   ⇒ every returned item has `.column == 2`; with no `column=` argument ⇒ every
   item has `.column is None`.
4. `tools/tests/test_tilemap_model.py` — same two assertions for
   `band_render_items`.
5. `tools/tests/test_spawn_deco.py` — same two assertions for
   `spawn_deco_render_items`.
6. `tools/tests/test_condition_art.py` — same two assertions for
   `condition_render_items`.

The `main.py` wiring itself has no unit-test hook (the frame loop is not
unit-testable). It is gated instead by `py tools/smoke.py`, which boots the game
headlessly into GAMEPLAY and runs real frames (`tools/smoke.py:76-80`) — so a
bad keyword at any of the four submit sites raises there. That is deliberate;
do not build a harness for it.

---

## 4. Exit gate + Quick Test

### Exit gate (the coder runs exactly these, nothing wider)

```bash
py tools/smoke.py
py -m pytest tools/tests/test_asset_store.py tools/tests/test_tilemap_model.py tools/tests/test_spawn_deco.py tools/tests/test_condition_art.py -q -n 4
```

- **`-n 4` is mandatory.** `pytest.ini` sets `-n auto`, which spawns 32 xdist
  workers on this box and thrashes it.
- **No full suite. No `py tools/testgate.py check`. No `--affected`. No tier
  sweep (`-m core` / `-m editor` / `-m meta`).** You are a subagent;
  `.claude/hooks/test_guard.py` DENIES all four. The single full `check` belongs
  to the main session at handoff — it is not yours and never becomes yours. The
  authority is §"Test Suite Policy" in the root `CLAUDE.md`.
- The gate is **ZERO**. `GATE PASS` / all-green or you are not done.

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and stop
> testing. Retrying is the loop the guard exists to stop.

Also required in the report:

- confirm by reading the diff that **no `column=0` default** and **no falsy
  column test** exists anywhere in it;
- confirm the scope fence in §2.5 held (no enemy/building/`backgrounds`/HUD
  file touched);
- confirm `game/main.py` changes are confined to lines ~1877-1909 and that the
  N1 recompute site was not touched.

### Quick Test (human, not the coder)

**The coder must NOT attempt this.** A subagent cannot drive an interactive game
window; the plan block's "then a live `py game/main.py`" step is downgraded out
of the coder's exit gate on purpose. The orchestrator or the user runs it.

1. `py editor/main.py` → **Master Sheets** → import a tile sheet with **4**
   master columns (the same art, 4 colourways/seasons).
2. Link a gameplay tile slot (e.g. `tile_buildable`) and a deco slot to it, and
   set each one's `column_mode` to **`season`** in the Details panel.
3. Link a **2-column** sheet to a second tile slot, also `column_mode: "season"`
   — this is the D7 clamp probe.
4. Leave one slot on `column_mode: "manual"` — this is the "untouched" probe.
5. `py game/main.py`, cheat to **round 11**: the seasonal tiles and deco step to
   column 1; the manual slot does not move; `main_menu_bg`, enemies and
   buildings do not move.
6. Cheat to **round 21**: seasonal slots step to column 2, and the 2-column
   sheet **holds at its last column** (column 1) rather than wrapping or turning
   into a grey X.
7. Walk a spawn band and a tile condition into view at each step — trees and
   condition art must step with everything else.
8. State in the report that this was a **live** run, and name the rounds you
   reached.

---

## OPEN — orchestrator must decide

1. **Test-file shape: I deviated from the orchestrator's stated lean, and it may
   override me.** The orchestrator leaned toward one new
   `tools/tests/test_season_columns.py` holding five resolution tests. I put the
   resolution tests in the existing `TestColumnBlock`
   (`tools/tests/test_asset_store.py:434`) and cut the list to **two**, because
   the other four are already pinned there by S1 — **measured**:
   caller-overrides-stored `:462-474`, manual-ignores-caller `:475-483`,
   no-`column_width`-byte-identical `:447-460`, clamp-to-last-column `:484-490`.
   Writing them again in a new file is duplication, and splitting `_column_block`
   across two homes makes the next reader check both. If the orchestrator still
   wants the separate file, say so and §3.5/§4 change to name
   `tools/tests/test_season_columns.py` instead of `test_asset_store.py`;
   nothing else in this brief moves.
2. **Does the `camera_start` marker want the season?** §2.2 threads the column
   onto every item `visible_render_items` emits, including base and
   `camera_start`. Both are inert in practice (their slots are `manual`), so this
   is a consistency call, not a behaviour call — flagged only so it is not read
   as an accident.
