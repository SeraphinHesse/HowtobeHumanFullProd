# Phase B1 — Colour state, the roll, and the render

Section S3 of `planning/MasterSheetColumnsPLAN.md`. Branch `phase-B1-colour-state`
off `section-S3`. Written by the S3 section-orchestrator (the Wave-1 planner
stalled); every `file:line` below is **verified on `section-S3`**.

## 1. Behavioral spec

A placed building rolls a random colour column, keeps it across upgrades, and
renders at it. Colour IS `BuildingSprite.column`.

**The S1 surface you build on (verified, not inferred):**
- `engine/core/sprite_animator.py:28` — `SpriteAnimator.column: int = -1`, a
  **sentinel** meaning "no driver". `:49` emits
  `column=self.column if self.column >= 0 else None`.
- `engine/render/item.py:42` — `RenderItem.column: int | None = None`.
- **`0` is a real colour index, never "unset".** Never write `0` to mean "no
  colour". The phase block's sentence *"a building whose slot offers no colours
  keeps `column = 0`"* predates the post-integration fix that changed the default
  from `0` to `-1`; its governing clause is **"and is untouched"**. Leave the
  field at `-1`.
- `game/buildings/components.py:41` — `BuildingSprite.render_items` is
  `yield from super().render_items(transform)`, so the column reaches
  `RenderItem` for free. **`components.py` needs no change.**
- `engine/assets/master_registry.py` — `load_registry(data_dir)` (fail-loud),
  `columns_for(doc, sheet_ref) -> tuple` (`()` if unresolvable),
  `column_width_for(doc, sheet_ref) -> int`.
- Manifest entries carry `.column`, `.column_mode`
  (`manual`|`season`|`building_color`), `.column_width`.

**Why the colour survives an upgrade for free:** `game/buildings/building.py:190-191`
— `apply_tier_stats` rewrites only `anim.slot_key`; `anim.column` is untouched.
Note `slot_key()` (`:173-179`) is `f"{TIER_SPRITES[t]}_t{t+1}_lvl{lvl}"`, so the
slot key **changes** on tier/level change while the column index persists. That is
D5's accepted consequence (chains must author colours in the same order).

## 2. Architecture plan

### 2a. Capability map — built in the HOST, once at boot
`game/main.py`, in the derived-art block beside `condition_art` (`:596-620`),
which is the precedent to copy verbatim in style and comment density:

```python
building_colors = { slot_key: (colour_name, ...) }
```

Derived once per boot from `engine.assets.master_registry` + the manifest — art
cannot change mid-run. `game/ui` and `game/buildings` must NEVER reach into the
asset layer themselves (D6, E-37); the host does the lookup and passes the map
down. Mirror `condition_art`'s filter shape (`registry.group_slots(<buildings
category>)`; if there is no clean buildings-category accessor, iterate the
manifest's own entries instead — say which you did and why in a comment).

**Membership rule — a slot is colour-capable iff BOTH hold:**
1. its master sheet declares `columns` — `columns_for(doc, entry.sheet)` is
   non-empty (D6), **and**
2. its manifest entry has `column_mode == "building_color"`.

Condition 2 is required by D3: with `column_mode == "manual"` the entry's stored
`column` wins and a live column is ignored, so a manual slot would show swatches
that do nothing. D6 states only condition 1; the conjunction is the only reading
under which the feature works. **Put this reasoning in a comment** — I am
recording it as an open finding for the top orchestrator, and S4 will face the
same question for `season`.

**E-37:** a missing or unreadable registry degrades to an EMPTY map with ONE
logged warning — never raises. An empty map simply means no building has
colours, exactly the escape hatch `condition_art`/`tree_slots`/`wall_art` use.

### 2b. The roll — in `registry.place_building`
`game/buildings/registry.py:75-76`, current signature:
```python
def place_building(tilemap, tile, building_type, love, buildings_balance,
                   scene, occupancy, state=None):
```
Add **keyword parameters with defaults that leave every existing caller
byte-identical**: `rng=None`, `building_colors=None`.
`place_building` is called from **18 test files** (measured:
`grep -rln "place_building" tools/tests/` → 18) plus production sites. A required
parameter here breaks the tree; this is the single most likely way B1 goes wrong.

- `rng=None` ⇒ use the stdlib `random` module, exactly the spawner's pattern
  (`game/enemies/spawner.py:98`, `:146` — `self._rng = rng if rng is not None
  else random`). **Never call the `random` module directly** when an rng was
  injected — the rule `engine/vfx/emitters.py:1-6` already holds.
- `building_colors=None` ⇒ treat as `{}` ⇒ no building has colours ⇒ every
  animator keeps `column == -1`. This is what keeps all 18 test files identical.

**Placement of the roll:** after `building.apply_tier_stats()` (`:161`) and
before/around `scene.spawn(building)` (`:165`) — it must be after
`apply_tier_stats`, because that is what sets `anim.slot_key`, and the lookup is
keyed on the slot key. Put it beside the `_tile_condition` stamp block
(`:154-158`), which is the existing "stamp placement-time state" site.

```python
names = (building_colors or {}).get(anim.slot_key, ())
if names:
    anim.column = (rng or random).randrange(len(names))
# else: leave anim.column at its -1 sentinel — NOT 0.
```
Reach the animator via `building.get_component(SpriteAnimator)` (the accessor
`apply_tier_stats` itself uses at `:189`); guard `is not None` the same way.

### 2c. Rendering
Nothing to do — §1 established `BuildingSprite.render_items` delegates to
`super()`, which already maps the sentinel. Pin it with a test, do not add code.

## 3. File scope + shared-file contract

**May edit, and nothing else:**
- `game/buildings/registry.py`
- `game/main.py`
- `game/buildings/CLAUDE.md` (architectural note: the capability map + the roll)
- `tools/tests/test_buildings_placement.py`

**Explicitly OUT of scope:** `engine/**`, `editor/**`, `data/**`,
`game/ui/**` (phase B2 owns `game/ui/building_ui.py`),
`game/buildings/components.py` (needs no change — see §1),
`game/buildings/building.py`.

> `tools/tests/test_buildings.py` — named by the plan doc — **does not exist**
> (measured: `ls tools/tests/`). Use `tools/tests/test_buildings_placement.py`,
> where `place_building` is already tested. Do not create the missing file.

**Published to phase B2 — state these exactly in your final report:**
1. The final signature of `place_building`.
2. The capability map's variable name in `game/main.py`, its exact shape, and
   **how a UI object gets hold of it** (which constructor/attribute you route it
   through). B2 codes the swatch UI against this and cannot proceed without it.
3. The name/location of any helper you factor out of the membership rule.

## 4. Exit gate + Quick Test

```bash
py tools/smoke.py
py -m pytest tools/tests/test_buildings_placement.py -x -q
```
**Nothing wider.** No full suite, no `py tools/testgate.py check`, no
`--affected`, no tier sweep (`-m core` / `-m editor` / `-m meta`) — you are a
subagent and `test_guard.py` denies all four.

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and stop
> testing. Retrying is the loop the guard exists to stop.

**Tests — BARE MINIMUM.** Four, in `tools/tests/test_buildings_placement.py`:
1. A seeded rng rolls a column inside the slot's colour count.
2. A slot with no colours leaves `column` at `-1` (assert the sentinel, **not**
   `0`).
3. The column survives `apply_tier_stats()` across a tier change **and** a level
   change.
4. The submitted `RenderItem` carries the column.

Seed the RNG in any test whose outcome depends on it (`game/CLAUDE.md`'s closing
rule — a test on the bare `random` module failed ~1 run in 10).

**Quick Test:** place a colour-capable building twice and see two different
colours.
