# Phase B1 — Colour state, the roll, and the render

Plan: `planning/MasterSheetColumnsPLAN.md` §"Section S3 — Building colour",
`#### Phase B1` (line 619). Section S1 is LANDED; its published surface is
`docs/handoffs/section-S1.md` and the plan's **Post-integration fixes** block
(`planning/MasterSheetColumnsPLAN.md:193-218`), which SUPERSEDES parts of the
S1 phase blocks. Read those two, not S1's briefs or diffs.

> **The one thing you must not get wrong.** The B1 phase block says *"A building
> whose slot offers no colours keeps `column = 0` and is untouched."* That
> sentence predates the post-integration fix that changed the default from `0`
> to the `-1` sentinel (`planning/MasterSheetColumnsPLAN.md:197-206`). The
> governing clause is **"and is untouched"**: a slot with no colours LEAVES
> `BuildingSprite.column` at its inherited `-1`. **Never write `0` to mean
> "no colour"** — `0` is a real colour index (colour 0 is pink in a
> `["pink", "red", …]` sheet), and `-1` is the only "no driver" value
> (`engine/core/sprite_animator.py:22-28`).

---

## 1. Behavioral spec

**Goal.** A placed building has a colour column and renders at it.

### What exists today (verified on this branch)

- `BuildingSprite` is a `SpriteAnimator` subclass with no fields of its own
  (`game/buildings/components.py:16-41`); it is attached to every building in
  `Building.__init__` (`game/buildings/building.py:50`).
- `SpriteAnimator.column: int = -1` — a **sentinel**, JSON-safe because a
  Component field must be (`engine/core/sprite_animator.py:22-28`).
  `render_items` maps it: `column=self.column if self.column >= 0 else None`
  (`engine/core/sprite_animator.py:49`).
- `BuildingSprite.render_items` delegates with
  `yield from super().render_items(transform)`
  (`game/buildings/components.py:37-41`), so the column reaches `RenderItem`
  **for free**. `game/buildings/components.py` needs NO change and is out of
  scope (verified by the section orchestrator).
- `RenderItem.column: int | None = None` (`engine/render/item.py:42`), and the
  renderer passes it as a keyword down to the store
  (`docs/handoffs/section-S1.md:22-23`).
- `registry.place_building` is the ONE legal placement path
  (`game/buildings/registry.py:75-173`). Its tail already: creates the building
  (`:145-146`), writes the tile content (`:150`), stamps `_tile_condition` +
  `_condition_mods` (`:155-157`), re-derives stats via `apply_tier_stats()`
  (`:161`), sets the tile state (`:163`), spawns into the scene (`:164`), sets
  occupancy (`:167`) and runs `on_placed` (`:172`).
- `Building.apply_tier_stats` rewrites `Health.max_hp` / `.hp` and
  `anim.slot_key`, and **nothing else**
  (`game/buildings/building.py:182-192`); `slot_key()` is
  `f"{TIER_SPRITES[t]}_t{t+1}_lvl{level}"` (`:173-178`).
- `GameObject.get_component(cls)` matches by `isinstance`
  (`engine/core/gameobject.py:53-58`), so `get_component(SpriteAnimator)`
  returns the `BuildingSprite` — that is exactly what `apply_tier_stats` already
  does (`game/buildings/building.py:189`).
- The host already derives three art-capability maps once at boot from
  `registry` + `manifest` (`game/main.py:583-584`): `condition_art` (`:596-600`),
  `tree_slots` (`:605-607`), `wall_art` (`:613-615`), `moving_sign_art` (`:620`).
  Each is passed down so `game/ui` and `game/map` never touch the asset layer;
  `game/map/conditions.py:26-33,67-79` documents the contract from the consumer
  side. This is the precedent B1 copies (D6, E-37).
- `engine/assets/master_registry.py` gives `load_registry(data_dir)`
  (fail-loud, `:44-50`), `columns_for(doc, sheet_ref) -> tuple` (`()` when
  unresolvable, `:72-79`) and `column_width_for` (`:82-95`). Column names only
  exist for `master/` refs (`:31`, D2).
- `Manifest.entry(slot_key)` (`engine/assets/manifest.py:287`) returns a
  `ManifestEntry` whose `.sheet` is the stored relative sheet ref
  (parsed at `engine/assets/manifest.py:139`).
- `SlotRegistry.group_slots(category_key)` returns every slot key in a category
  (`engine/assets/registry.py:126-135`); `"buildings"` is a live category key in
  `data/slots.json` (**measured**: categories are `buildings, enemies, map, ui,
  core, vfx, deco, conditions, backgrounds, walls`).
- Injected-rng rule: `engine/vfx/emitters.py:1-3` ("Every emitter takes an
  injected `rng`"). The **shape to copy** is the spawner's:
  `def begin_round(..., rng=None, ...)` then
  `self._rng = rng if rng is not None else random`
  (`game/enemies/spawner.py:140,146`, with `import random` at `:38`).

### Required behaviour after B1

1. **The roll.** On a successful `place_building`, if the host's capability map
   has a non-empty colour tuple for the placed building's CURRENT slot key, the
   building's `BuildingSprite.column` is set to a single `rng` draw in
   `range(len(colours))`. Exactly one draw, only when a roll actually happens.
2. **No colours ⇒ untouched.** If the map is absent/empty, or has no entry for
   that slot key, or the entry is an empty tuple, `column` is **left at `-1`**.
   No write at all. (Not `0`.)
3. **Byte-identical for every existing caller.** `place_building` today is
   `place_building(tilemap, tile, building_type, love, buildings_balance,
   scene, occupancy, state=None)` (`game/buildings/registry.py:75-76`) and is
   called by 18 test files (**measured** by the section orchestrator),
   `game/ui/building_ui.py:1928-1930` and `tools/simrun.py:171`. Every parameter
   B1 adds is **trailing and keyword-with-default**, and the defaults produce
   today's behaviour exactly: no roll, no rng draw, nothing written.
4. **The colour survives an upgrade for free.** A level-up or a tier advance
   re-runs `apply_tier_stats`, which rewrites only `anim.slot_key`
   (`game/buildings/building.py:182-192`) — `anim.column` is untouched. B1 adds
   no code for this; it adds the test that PINS it (D5's accepted consequence:
   the same index may be a different colour on a sheet that authored its columns
   in a different order — nothing enforces sheet-order consistency).
5. **The submitted `RenderItem` carries the column** — via the existing
   delegation chain in 1's bullets 2-4. No engine or component change.
6. **The host builds the capability map once at boot** from the master-sheet
   registry + the manifest, and a missing/unreadable registry degrades to an
   EMPTY map with ONE logged warning — never a raise (E-37). `smoke.py` boots
   `main()` headlessly, so a raise here fails the gate.

---

## 2. Architecture plan

### 2.1 `game/buildings/registry.py` — the signature and the roll

Append TWO trailing keyword parameters, after `state=None`:

```python
def place_building(tilemap, tile, building_type, love, buildings_balance,
                   scene, occupancy, state=None, colour_columns=None,
                   rng=None):
```

- **`colour_columns=None`** — the host's `{slot_key: (colour_name, ...)}`
  capability map, or `None`. `None` is read as "no map" ⇒ no slot has colours ⇒
  no roll ⇒ nothing written. Do not coerce it into a mutable default (`{}` as a
  default argument is the classic shared-mutable bug); read it as
  `(colour_columns or {})`.
- **`rng=None`** ⇒ the stdlib `random` MODULE, per the spawner shape
  (`game/enemies/spawner.py:146`): `import random  # stdlib — pure` at the top of
  `registry.py` (the same comment style as `game/ui/building_ui.py:43`), then at
  the roll site `draw = rng if rng is not None else random`. This is why B2 does
  **not** have to thread an rng through the UI — production works with the
  module default, and a test injects `random.Random(seed)`.
  **The module is never touched unless a roll happens**, so no existing seeded
  test's global draw sequence moves.

**Where the roll goes.** Immediately after the `# -- /10I --` marker
(`game/buildings/registry.py:162`), i.e. **after** `building.apply_tier_stats()`
(`:161`) and **before** `tilemap.set_tile_state(...)` (`:163`) /
`scene.spawn(building)` (`:164`):

- after `apply_tier_stats`, because that is what writes the CURRENT
  `anim.slot_key` the map is keyed by;
- before `scene.spawn`, so the sprite is already at its colour on the first
  frame it is live (no one-frame flash of column 0).

Shape (write it in the file's own commenting register — cite D3/D5/D6 and the
`-1` sentinel, the way `:152-157` cites 10I):

```python
anim = building.get_component(SpriteAnimator)
names = (colour_columns or {}).get(anim.slot_key) if anim is not None else None
if names:
    anim.column = (rng if rng is not None else random).randrange(len(names))
# else: LEAVE anim.column at its -1 "no driver" sentinel. Never write 0 —
# colour index 0 is a real colour.
```

`SpriteAnimator` is imported from `engine.core`, mirroring
`game/buildings/building.py:21,189` (one idiom in the package; `get_component`
matches the `BuildingSprite` subclass by `isinstance`).

### 2.2 `game/main.py` — the capability map

**Name it `colour_columns`** (British spelling, matching the plan's prose and
the `BuildingColors` data group B3 adds — do not rename it in B2/B3).

**Where:** in `main()`, in the boot-time derived-art block, immediately after
`moving_sign_art` (`game/main.py:620`) and before
`widgets.set_skin_hit_test(...)` (`:621`). `registry` and `manifest` are already
in scope (`:583-584`), as is `data_dir`.

```python
# Building colour capability: {slot_key: (colour name, ...)} over the
# BUILDING slots whose linked master sheet declares `columns` (D4/D6).
# Derived ONCE at boot exactly like `condition_art`/`tree_slots`/`wall_art`
# above — art cannot change mid-run — so `game/buildings` and `game/ui` never
# touch the asset layer. A slot absent from the map simply has no colours.
try:
    sheets_doc = master_registry.load_registry(data_dir)
except Exception as exc:      # E-37: this is ART CONFIG, never fatal
    <one warning, then>  sheets_doc = {}
colour_columns = {}
for _slot in registry.group_slots("buildings"):
    _entry = manifest.entry(_slot)
    if _entry is None:
        continue
    _names = master_registry.columns_for(sheets_doc, _entry.sheet)
    if _names:
        colour_columns[_slot] = _names
```

- Import: `from engine.assets import master_registry` (module import, so
  `load_registry` does not collide with the slot-registry `load_registry`
  already imported at `game/main.py:63`).
- `master_registry.load_registry` is **fail-loud by design**
  (`engine/assets/master_registry.py:44-50`) — the E-37 degrade is the HOST's
  job, which is why the `try` lives here and not in the engine. Catch broadly
  (missing file ⇒ `OSError`; invalid ⇒ `jsonschema.ValidationError`), warn
  ONCE, continue with an empty doc ⇒ an empty map ⇒ no building ever rolls.
  **UNVERIFIED —** the exact warning mechanism `game/main.py` uses for its other
  E-37 degrades was not confirmed in this brief's exploration budget: match the
  nearest existing warn in `game/main.py` / `engine/assets/manifest.py`'s
  `load_manifest`; if there is genuinely none, a single `print("[assets] …")` is
  acceptable. Do not add a logging dependency for this.
- `columns_for` already returns `()` for a non-master ref, an unresolvable ref
  or an unnamed sheet (`engine/assets/master_registry.py:59-79`), so no
  `master/`-prefix check belongs here.

**Handing it down.** In `build_gameplay()`, beside the existing host-derived
panel attributes (`gp["panel"].log` / `.on_build_vfx` / `.assets`,
`game/main.py:840-846`), add:

```python
# MasterSheetColumnsPLAN B1/B2: the host-derived colour capability map
# ({slot_key: (colour name, ...)}). B1 only publishes it here; the swatch
# UI and the `place_building(colour_columns=…)` hand-off are phase B2.
gp["panel"].colour_columns = colour_columns
```

This is an instance-attribute assignment onto the `BuildingUI` built at
`game/main.py:779` — the same pattern as `.assets` (`:846`) — so it needs **no
edit to `game/ui/building_ui.py`** and is inert until B2 reads it.

**Accepted consequence, state it in your report:** B1 does NOT change the
production call site (`game/ui/building_ui.py:1928-1930` — B2's file), so a
building placed in-game still rolls nothing until B2 passes
`colour_columns=self.colour_columns` there. See §4 for what that means for the
Quick Test.

**Rejected alternative** (do not implement): stamping the map onto the
`TileMap` instance and having `place_building` read it via
`getattr(tilemap, "colour_columns", None)`. It would make the roll live in B1
without touching `game/ui`, but it hides a second, undeclared input channel in a
pure-logic seam and gives B2 two places to look. The explicit parameter is the
published contract.

### 2.3 What B1 deliberately does NOT do

- No picked-colour override parameter on `place_building`. B2 owns how a player
  choice reaches the building. *Guidance for B2, not a B1 deliverable:* if B2
  wants one, add `column=None` as the NEXT trailing keyword under the same
  rule, with the precedence "an explicit `column` wins and suppresses the rng
  draw entirely".
- No change to `game/buildings/components.py` (verified: the field is inherited
  and `render_items` already delegates).
- No engine, editor, data or `game/ui` change.

---

## 3. File scope + shared-file contract

### Modified (exactly these four)

| File | Change |
|---|---|
| `game/buildings/registry.py` | `import random`; `SpriteAnimator` import; two trailing kwargs on `place_building`; the roll at `:162` |
| `game/main.py` | the `colour_columns` boot block after `:620`; `gp["panel"].colour_columns = colour_columns` beside `:846` |
| `game/buildings/CLAUDE.md` | a short "Building colour (master column)" subsection: the two new params + defaults, the `-1` sentinel rule, where the map comes from, why an upgrade preserves it |
| `tools/tests/test_buildings_placement.py` | the four tests in §3.3 |

**Do not touch:** `game/buildings/components.py`, anything under `engine/**`,
`editor/**`, `game/ui/**` (B2's file), `data/**`, `tools/simrun.py`, or any of
the other 17 test files that call `place_building` — the default-argument rule
exists precisely so none of them needs an edit. Deliberate deviation from the
router's "update the package CLAUDE.md" step: the `game/main.py` host bullet is
documented in `game/buildings/CLAUDE.md` alongside the seam rather than in
`game/CLAUDE.md`, because the plan fences B1 to the buildings doc; flag it in
your report so the section handoff can carry it.

### 3.1 Published interface — B2 codes against THIS

```python
# game/buildings/registry.py
place_building(tilemap, tile, building_type, love, buildings_balance, scene,
               occupancy, state=None, colour_columns=None, rng=None)
#   colour_columns : {slot_key: (colour_name, ...)} | None
#                    None ⇒ no map ⇒ no roll ⇒ column stays -1
#   rng            : random.Random-compatible | None  (None ⇒ stdlib `random`)
#   returns        : (building, cost)   — UNCHANGED
```

```python
# set by game/main.py in build_gameplay(), beside gp["panel"].assets
BuildingUI.colour_columns : dict[str, tuple[str, ...]]
#   host-owned, never None (may be empty), read-only for consumers,
#   keyed by the slot key `Building.slot_key()` returns for the CURRENT
#   tier/level (e.g. "stone_thrower_t1_lvl1"), values in the sheet's STORED
#   column order (index i == master column i, D4/D5).
```

**Colour state:** `building.get_component(SpriteAnimator).column` — an int,
`-1` = no colour driver, `>= 0` = the master column index. Never `0` for
"unset".

### 3.2 Shared-file insertion points

- `game/buildings/registry.py` — only B1 touches it in S3. Insert the roll
  between the `# -- /10I --` marker (`:162`) and `tilemap.set_tile_state`
  (`:163`); leave every guard above `:145` alone.
- `game/main.py` — only B1 touches it in S3. Two insertion points, both named
  above (`:620` and `:846`). Do not reorder the existing derived-art block.
- `game/ui/building_ui.py` — **B2 only.** Its edit is at `_do_place`
  (`:1928-1930`), adding `colour_columns=self.colour_columns` to the existing
  `place_building(...)` call.

### 3.3 Tests — BARE MINIMUM, four of them

All in **`tools/tests/test_buildings_placement.py`** (the file the plan doc
names, `test_buildings.py`, does not exist — **measured** by the section
orchestrator). Reuse that file's existing `synth()` helper, `BAL` and
`Scene()/TileOccupancy()` setup (`tools/tests/test_buildings_placement.py:31-47`).
**Seed the RNG in any test whose outcome depends on it** — `random.Random(1234)`,
never the bare module. Write no more than these four; do not broaden coverage.

1. **`test_colour_roll_lands_inside_the_slot_colour_count`** — place a
   `"defence"` on a synth map with
   `colour_columns={"stone_thrower_t1_lvl1": ("pink", "red", "purple", "yellow")}`
   and `rng=random.Random(1234)`. First assert the placed building's
   `slot_key()` really is `"stone_thrower_t1_lvl1"` (so a `TIER_SPRITES` rename
   fails loudly here rather than silently disabling the test), then assert
   `0 <= anim.column < 4`.
2. **`test_slot_without_colours_leaves_the_sentinel`** — place with a map that
   holds colours for a DIFFERENT slot key (and, in a subtest or a second
   assertion, with the default `colour_columns=None`). Assert
   `anim.column == -1` — **the sentinel, untouched**. Assert it is `-1`, not
   `0`, and not merely `<= 0`.
3. **`test_colour_survives_tier_and_level_change`** — place, set
   `anim.column = 2` by hand, then (a) bump `TierState.current_level_in_tier`
   and call `building.apply_tier_stats()`, (b) bump `TierState.current_tier` and
   call it again. After each: assert `anim.slot_key` actually CHANGED (the test
   is worthless if the slot key stood still) and `anim.column == 2`.
4. **`test_render_item_carries_the_column`** — with a rolled column on a placed,
   alive building, take the `RenderItem` off its existing render path (mirror how
   `tools/tests/test_components.py` / `test_hud_items.py` drive `render_items`)
   and assert `item.column == anim.column`; and that a building placed with no
   colours yields `item.column is None` (the `-1 ⇒ None` mapping at
   `engine/core/sprite_animator.py:49`).

---

## 4. Exit gate + Quick Test

### Exit gate (run exactly this, nothing wider)

```bash
py tools/smoke.py
py -m pytest tools/tests/test_buildings_placement.py -x -q
```

`GATE PASS` / green is the bar — the gate is ZERO. `smoke.py` matters here
specifically: it boots `main()` headlessly, so it is what proves the new
boot-time `colour_columns` block degrades instead of raising on live `data/`.

**You are a subagent. Do NOT run** the full suite, `py tools/testgate.py check`,
`--affected`, or any tier sweep (`-m core` / `-m editor` / `-m meta`) — the
`test_guard.py` `PreToolUse` hook DENIES all four, and the single full `check`
belongs to the main session at handoff (root `CLAUDE.md` §"Test Suite Policy" is
the authority).

**If `test_guard` denies a command:** do not re-issue it, do not vary the flags
(the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints
identically), and do not reach for the guard's escape hatch. Report the deny
text and the result it quotes back to the orchestrator and stop testing.
Retrying is the loop the guard exists to stop.

### Quick Test (in-game — run by the orchestrator/user, not by you)

> Place a colour-capable building twice and see two different colours.

Two prerequisites, both outside B1's diff — state in your report which of them
held when the Quick Test was (or was not) run:

1. **A sheet must declare `columns`.** Today `data/sprites/master_sheets.json`
   has one entry, `slinger_t2_lvl3`, with `column_width: 15` and **no**
   `columns` (`docs/handoffs/section-S1.md:6,10-12`), so the live capability map
   is legitimately EMPTY and every building correctly stays at `-1`. The
   designer field that authors `columns` is S2/E1; until then a schema-valid
   agent edit to that registry is the only way to author one.
2. **The call site must pass the map.** B1 does not edit
   `game/ui/building_ui.py:1928-1930` (B2's file), so the roll is not reachable
   from a real placement until B2 lands. Until then the observable B1 evidence
   is the four tests plus `smoke.py`.

If both prerequisites hold, the run is: `py game/main.py` → place the
colour-capable building type on two tiles → the two placed sprites show
different colours; upgrade one (level and tier) → its colour does not change.
