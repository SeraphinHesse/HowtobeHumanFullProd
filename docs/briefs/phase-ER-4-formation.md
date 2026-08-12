> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase ER-4 — the `Formation` enemy type

**Plan**: `planning/EnemyReworkPLAN.md` § "Phase ER-4 — The `Formation` enemy type"
(lines 308–338). **Branch**: `phase-ER-4-formation`, off the umbrella
`phase-ER-1-ER-4-umbrella`. **Packages**: `game` (`enemies` only) + `data`.

> **This is the INTEGRATION phase.** ER-1 (render sizing), ER-2 (footprint
> clearance pathing) and ER-3 (generalised `death_spawn`) are all merged into the
> umbrella by the time you run. Every mechanism the Formation needs already
> exists. **Your job is to add ONE enemy type that consumes them — you should not
> be building machinery.** If you find yourself editing
> `game/map/pathfinder.py`, `game/enemies/components.py`, `game/enemies/combat.py`
> or `game/core/session.py`, **STOP and report** — that means something in ER-2 or
> ER-3 was under-built, and quietly widening scope hides the real bug.

---

## 1. Behavioral spec

### What the Formation is (plan, `EnemyReworkPLAN.md:310–333`)

> "the new large unit — 128×128 art, footprint 2, more HP and damage than a
> regular, which **dies at 50% HP and breaks into regular units at 80% HP each**,
> simulating the formation scattering."

Requirement IDs in play: **G-7** (every tunable from `data/balancing/`, no
code-side default), **D-1** (`data/` JSON is the only value store), **D-2**
(schema-first, all writes validate), **D-3** (deterministic formatting), **D-12**
(every leaf carries a `description`; every numeric leaf carries `minimum` +
`maximum`), **E-11** (all state in components), **E-23 / E-37** (missing art →
grey-X placeholder, never a crash), **E-34** (registry-group driven slots).
Design decisions **D1/D2** (ER-1 slicing≠drawing, downscale-only fit), **D4**
(breaking formation IS dying), **D5** (footprints are pathing-only, never
`TileOccupancy`), **D6** (one flow field per footprint).

### D4 — there is NO "break" state. Breaking IS dying.

This is the single most important thing to internalise, and it is already
implemented. On the umbrella, `Enemy.alive` reads
(`game/enemies/enemy.py`, ER-3 `Enemy.alive`):

```python
@property
def alive(self):
    h = self.get_component(Health)
    ds = self.get_component(DeathSpawn)
    return h.hp > h.max_hp * ds.at_hp_fraction
```

So a Formation with `at_hp_fraction: 0.5` becomes `alive == False` the moment its
HP touches half. From there the *existing* pipeline runs, unchanged:

1. `resolve_combat` sees `alive == False` → calls `on_enemy_death(enemy)` and
   despawns it (`game/enemies/combat.py`).
2. `Session.on_enemy_death` (`game/core/session.py`, ER-3) duck-types
   `enemy.death_spawn_plan`; non-`None` and not already spawned →
   `enemy.mark_death_spawned()` + stash `(col, row, plan)` in
   `self._death_spawns_pending`. The `DeathSpawn.death_spawned` flag is the
   one-shot guard.
3. `Session.post_sim` flushes every pending burst through
   `Spawner.spawn_death_swarm(scene, col, row, plan)` **before** the wave-clear
   check.
4. `Spawner.spawn_death_swarm` (`game/enemies/spawner.py`, ER-3) constructs each
   child at the current scale tier and, because `spawn_hp_fraction < 1.0`, seeds
   `health.hp = max(1, int(health.max_hp * frac))`.

**You write none of that.** You supply the data that drives it. Do not add a
"break" state machine, a `Formation.on_death`, or a second code path.

### ER-1 gives you (do not re-implement)

- `data/slots.json` `slots[]` entries accept an **object form**
  `{"key": …, "frame_w": …, "frame_h": …}` overriding the category frame size
  (`data/schemas/slots.schema.json` `$defs/slot_entry`; the `enemies` category is
  64×96 at `data/slots.json:300-301`). `SlotRegistry.frame_size()` honours it, and
  the object form is normalised away at parse time — `GroupNode.slots` stays a
  tuple of key strings downstream (`engine/assets/CLAUDE.md`).
- **Downscale-only width fit** (`engine/render/renderer.py:108-110`):
  `s = fit_factor(frame_w, tile_w, fit_tiles) * scale`, where
  `fit = min(1.0, fit_tiles*tile_w / frame_w)`. A **128×128 sheet at
  `footprint: 2` lands at exactly 2×2 tiles, scale 1.0** (`tile_w` = 64) — that is
  the whole reason the art spec is 128×128.
- `footprint` (int 1..8) and `sprite_scale` (0.1..8) are **required** keys on every
  `EnemyTypes` block; `Enemy.__init__` already threads them into
  `SpriteAnimator(fit_tiles=…, scale=…)`.
- **The grey-X placeholder path already reads the per-slot override.**
  `AssetStore._placeholder` (`engine/assets/store.py:71-73`) calls
  `self.frame_size(slot_key)`, whose precedence is manifest entry > **registry
  override** > category (`store.py:44-54`). So a `formation_stage_1` slot with a
  128×128 override and no manifest entry renders a **128×128 grey X**, fitted to
  2×2 tiles. **ER-1 deliberately shipped no object-form entry, so you are its
  first consumer — prove this end to end with a test (§4).**
- HP bars derive their lift from the **drawn** sprite (`game/ui/effects.py:109-124`,
  `_sprite_top` → `fit_factor`). A 2-tile Formation gets a correct bar with **no
  new constant**. You only declare `HP_BAR_W`.

### ER-2 gives you (do not re-implement)

ER-2's coder, verbatim: *"ER-4's Formation needs almost nothing here. Set
`footprint: 2` in `enemies.json` and it flows automatically."* Concretely:

- **Anchor convention**: the block's **MIN corner**. A footprint-N unit at
  `(c, r)` occupies `{(c+i, r+j) | 0 <= i, j < N}` (`block_tiles` in
  `game/map/pathfinder.py`). A unit reaches a goal when its block **covers** it
  (`block_covers`, `_expand_goals`).
- `Enemy.__init__` → `PathAgent(footprint=int(block["footprint"]))`.
- `Enemy.on_spawn` reads the footprint back off the component and threads it into
  `find_path(..., footprint=fp)` / `find_path_ignoring_walls(..., footprint=fp)`.
- `PathAgent._blocker_ahead` scans the whole destination block; `_wall_edge_ahead`
  scans face + internal edges.
- The combat sweep measures from the block **centre** (`_enemy_center_world`,
  `_fp_offset` in `game/enemies/combat.py`).
- `Spawner._pick_spawn_tile` / `_clear_spawn_tiles` filter spawn anchors so a
  footprint-N unit only spawns where its whole N×N block is spawn zone, cached
  once per round per footprint, **consuming zero rng**. Resolution goes through
  `_footprint_of(balance, etype)`, which walks `ENEMY_CLASSES[etype].STAT_SUBTREE`
  — **so a new type needs no change there**, provided you register the class and
  give it a `STAT_SUBTREE`.
- ER-2 verified the shipped active map admits 2×2 units (clear spawn anchors that
  reach the base). The Formation will not be dead on arrival.

### ER-3 gives you (do not re-implement)

`death_spawn` is a **required** block on every enemy type
(`data/schemas/enemies.schema.json` `$defs/death_spawn`):

```json
"death_spawn": {
  "enabled": <bool>,
  "at_hp_fraction": <number 0..1>,
  "spawn_hp_fraction": <number 0..1>,
  "spawns": [ <spawn_counts row>, … ]   // minItems 1, ONE ROW PER ERA
}
```

- `spawns` is **always an array of per-era rows** — never a flat map, never a
  `oneOf` (a `oneOf` crashes the editor's balancing panel). The row shape is
  `$defs/spawn_counts`: `{"raiders": int, "regular": int, "siege": int}` — **all
  three required**, prototype vocabulary (`regular`, NOT `standard`).
- Resolver: `Enemy.__init__` does
  `spawn_row = rows[min(max(era, 0), len(rows) - 1)]` where
  `era = self._resolve_era(balance, tier)`.
- `Enemy._resolve_era` returns **`0`** on the base class ("Types with no era table
  are always row 0"). Only `Boss` overrides it. **The Formation must NOT override
  `_resolve_era`** — it is not era-indexed, so it inherits row 0 and ships a
  **1-row** `spawns` array; the clamp does the rest. Confirmed against ER-3's
  actual source.
- `Spawner._SWARM_TYPES` maps `spawn_counts` keys → etypes in the fixed order
  `standard → raider → siege` (load-bearing: it fixes rng draw counts).
  **`formation` is deliberately NOT a `spawn_counts` key** — see §2, "Hard
  constraint: do not touch `$defs/spawn_counts`".

---

## 2. Architecture plan

### 2.1 `game/enemies/enemy.py` — the `Formation` subclass

Insert **after `class SiegeCannon`, before `class Boss`** (difficulty order, matching
the file's existing narrative). Model it on `SiegeCannon` — it is the closest
analogue (a heavy that *does* take the scale-tier bonuses).

```python
class Formation(Enemy):
    """A marching column — many soldiers moving as one body (ER-4). Two tiles
    square (``footprint: 2``, ER-2 clearance pathing: it only stands where all
    four tiles are clear, so it cannot thread a one-tile gap a walker slips
    through). It takes the scale-tier bonuses exactly like Standard/Siege.

    It has NO break state: ``death_spawn.at_hp_fraction`` 0.5 makes ``alive``
    False at half HP (D4 — breaking formation IS dying), and the ER-3 pipeline
    bursts its ``spawns`` row of regulars at 80% of their own max HP. One code
    path, one editor form."""

    ETYPE = "formation"
    REGISTRY_GROUP = "Formation"
    DEFAULT_SLOT = "formation_stage_1"
    STAT_SUBTREE = ("Formation",)
    HP_BAR_W = 32                # a 2-tile body; siege 24, boss 48

    def _resolve_stats(self, balance, tier):
        # Scales with the tiers exactly like Standard and SiegeCannon.
        return tier_scaled_stats(
            balance["EnemyTypes"]["Formation"], balance, tier)
```

**Non-negotiables:**

- **You MUST override `_resolve_stats`.** The base `Enemy._resolve_stats` reads
  `balance["EnemyTypes"]["Standard"]` *literally* — inheriting it would silently
  give the Formation walker stats. `STAT_SUBTREE` is used for the *balancing
  block* lookup in `__init__` (and by `_footprint_of` in the spawner), **not** by
  `_resolve_stats`.
- **Do NOT override `_resolve_era`** (see §1) and do NOT add `__init__`,
  `on_spawn`, `EXTRA_TAGS`, `death_spawn_plan`, `mark_death_spawned`, or any
  component wiring. Everything is inherited.
- Register in `ENEMY_CLASSES`: `"formation": Formation`.
- Update the module docstring's one-line type roll-call.

### 2.2 `game/enemies/__init__.py`

Add `Formation` to the `from .enemy import …` line and to `__all__` (both are
alphabetically sorted — `Formation` goes after `EnemyCombat`, before `PathAgent`).

### 2.3 `game/enemies/spawner.py` — the flag + composition rule

Mirror the siege rule (a slowly-accreting heavy), **not** the raider rule (a
linearly-growing swarm).

```python
ENABLE_FORMATION = True     # ER-4
```

```python
    def _formation_group(self, round_num, balance, spawn_tiles):
        """Formations from ``Formation.start_round``, one more every
        ``rounds_per_formation`` rounds (the SiegeCannon accretion formula — a
        heavy, not a swarm). Mixed into the shuffled body: unlike siege they do
        not lead the queue, because a 2×2 body at the head of the wave would
        wall the choke point before anything else arrived."""
        if not ENABLE_FORMATION:
            return []
        f = balance["EnemyTypes"]["Formation"]
        if round_num < f["start_round"]:
            return []
        n = (f["base_count"]
             + (round_num - f["start_round"]) // f["rounds_per_formation"])
        return [(self._pick_spawn_tile(spawn_tiles, "formation"), "formation")
                for _ in range(n)]
```

Wire it into `_compose`, **after** the siege call and **before** the shuffle:

```python
        raiders = self._raider_group(round_num, balance, spawn_tiles)
        siege_front, siege_mixed = self._siege_groups(
            round_num, balance, spawn_tiles)
        formations = self._formation_group(round_num, balance, spawn_tiles)   # ER-4

        rest = regular + raiders + siege_mixed + formations
        self._rng.shuffle(rest)
        return siege_front + rest
```

**Determinism rules you must honour:**

- **Every spawn-tile pick goes through `self._pick_spawn_tile(spawn_tiles,
  etype)`** (ER-2's single choke point), never a bare `self._rng.choice`. For
  `footprint: 2` it filters to clear anchors, falling back to the unfiltered list
  when nothing qualifies — so a Formation is never silently dropped from a wave.
- **Call `_formation_group` LAST** among the composition groups. Every earlier
  group's rng draw sequence then stays byte-identical, so the existing
  `TestSpawnComposition` fixtures for rounds below `start_round` are untouched and
  the standard/raider/siege draw counts are unchanged at every round.
- The `rest` shuffle *does* change for rounds ≥ `start_round` (a longer list).
  That is expected. Check `tools/tests/test_enemies.py::TestSpawnComposition` for
  any fixture asserting an exact queue at a round ≥ 16 and update it in the same
  change if so.

**Boss rounds: the Formation does NOT appear.** `_compose` routes every
`round % Boss.round_interval == 0` round to `_boss_round`, whose composition comes
from `Boss.round_counts` (a `$defs/spawn_counts` table with exactly
`regular`/`raiders`/`siege`). This is **deliberate** and you must not "fix" it:

> ### Hard constraint: do NOT touch `$defs/spawn_counts`
> `spawn_counts` is shared by `Boss.round_counts` **and** every
> `death_spawn.spawns` row. `tools/tests/balancing_parity_map.json` maps
> `BOSS_ROUND_COUNTS → enemies:EnemyTypes/Boss/round_counts` and
> `test_migrated_values_equal_prototype_values` asserts **whole-value equality**
> against the prototype's list of dicts. Adding a `"formation"` key to
> `spawn_counts` would change every one of those dicts and **fail the parity gate
> loudly**. It would also make `Spawner._SWARM_TYPES` and every death-spawn row in
> the file need a formation count they have no business carrying.
>
> Therefore: no formation key in `spawn_counts`, no formation branch in
> `_boss_round`. A formation-free boss round is the documented behaviour. If the
> user later wants formations on boss rounds, that is a one-line
> `+ self._formation_group(...)` into `_boss_round`'s `rest` — computed from the
> formula, never from the table. Note it in the PR as a known, deliberate gap.

### 2.4 `data/balancing/enemies.json` — the `EnemyTypes.Formation` block

`EnemyTypes` keys are sorted (D-3), so `Formation` lands between `Boss` and
`Raider`.

**Derive the numbers — do not invent them.** The existing tiers, all ×10 combat
scale (`data/balancing/enemies.json`):

| type | hp | dmg | move_speed | attack_speed | range | scales? |
|---|---|---|---|---|---|---|
| Standard | 55 | 10 | 1.2 | 1.0 | 1 | yes |
| Raider | 32 | 20 | 2.7 | 0.8 | 1 | **no** |
| SiegeCannon | 280 | 100 | 1.0 | 1.9 | 2 | yes |
| Boss (era 0) | 2000 | 200 | 0.3 | 1.5 | 2 | no (era table) |

**The proposed starting shape — a column of eight men.** Land these unless you
have a better-justified derivation; either way, **state the final numbers and the
derivation in your report so they reach the PR** (the plan's open item:
*"the mechanic lands first, the numbers get tuned in the editor"*).

```json
"Formation": {
  "attack_range_tiles": 1,
  "attack_speed": 1.4,
  "base_count": 1,
  "death_spawn": {
    "at_hp_fraction": 0.5,
    "enabled": true,
    "spawn_hp_fraction": 0.8,
    "spawns": [
      {
        "raiders": 0,
        "regular": 4,
        "siege": 0
      }
    ]
  },
  "dmg": 30,
  "footprint": 2,
  "hp": 440,
  "move_speed": 0.9,
  "rounds_per_formation": 3,
  "sprite_scale": 1.0,
  "start_round": 16
}
```

Derivation to carry into the PR:

- **`hp: 440` = 8 × Standard (55).** The unit *is* eight walkers marching as one.
  It breaks at 50% → 220 HP absorbed as one body, then four survivors at 80% × 55
  = **44 HP each** (176 HP) scatter — "half the column falls, the rest break and
  run, bloodied". Total pool ≈ 396 HP, between a siege cannon (280) and two.
- **`dmg: 30` = 3 × Standard.** More than a regular (plan requirement); nowhere
  near siege's 100 — siege stays the anti-building king.
- **`move_speed: 0.9`** — slower than a lone walker (1.2) and slower than siege
  (1.0): massed men march slowest. Still far above the boss's 0.3.
- **`attack_speed: 1.4`** — between Standard (1.0) and siege (1.9).
- **`attack_range_tiles: 1`** — infantry, melee. (Reminder: ER-2 measures Chebyshev
  range from the block *centre*, so a 2×2 already engages fairly.)
- **`footprint: 2`, `sprite_scale: 1.0`** — a 128×128 sheet at footprint 2 fits
  exactly (fit = min(1, 2×64/128) = 1.0). Do not touch `sprite_scale` unless the
  art you ship is not 128×128.
- **`start_round: 16`, `base_count: 1`, `rounds_per_formation: 3`** — siege lands
  at round 14; the plan asks for "after siege units are established". Round 16 is
  two rounds later and sits between the round-10 and round-20 boss beats. Accretion:
  r16→1, r19→2, r22→3, r25→4.
- **Scaling: `Formation` takes the scale-tier bonuses** (like Standard and Siege,
  unlike Raider) — a line unit that must stay relevant late. This is what
  `_resolve_stats` → `tier_scaled_stats` buys you.

Sanity check the coder must run before landing: `spawn_hp_fraction` (0.8) must stay
**above** every child type's own `at_hp_fraction` (Standard's is 0.0) or the
children die on the frame they appear — the schema's own description says so.

### 2.5 `data/schemas/enemies.schema.json` — the `EnemyTypes.Formation` subschema

Add under `properties.EnemyTypes.properties` (sorted: after `Boss`, before
`Raider`) and add `"Formation"` to `EnemyTypes.required`. `additionalProperties:
false`, every key `required`. **D-12: every leaf carries a `description`; every
numeric leaf carries `minimum` AND `maximum`** — `test_balancing_data`
(`test_every_leaf_documents_units_in_description`,
`test_every_numeric_leaf_declares_bounds`) enforces both.

Reuse the existing bounds policy stated in the schema's top-level `description`
(fractions 0–1, HP/DMG 0–100000, counts 0–10000, rounds 0–1000, seconds 0–60,
footprint 1–8, sprite_scale 0.1–8) — copy the `description` text for
`footprint`/`sprite_scale`/`hp`/`dmg`/`move_speed`/`attack_speed`/`attack_range_tiles`
**verbatim from the `SiegeCannon` block** so the vocabulary stays uniform.

```json
"Formation": {
  "additionalProperties": false,
  "description": "A marching column of soldiers that moves as one 2x2 body (ER-4). It breaks at half health - death_spawn.at_hp_fraction 0.5 means it DIES at 50% HP (D4: breaking formation is dying) and scatters its spawns row of regulars at spawn_hp_fraction of their own max HP.",
  "properties": {
    "attack_range_tiles": { …verbatim from SiegeCannon… },
    "attack_speed":       { …verbatim from SiegeCannon… },
    "base_count": {
      "description": "Formations in the first formation round.",
      "maximum": 10000, "minimum": 0, "type": "integer"
    },
    "death_spawn": { "$ref": "#/$defs/death_spawn" },
    "dmg":         { …verbatim from SiegeCannon… },
    "footprint":   { …verbatim from SiegeCannon… },
    "hp":          { …verbatim from SiegeCannon… },
    "move_speed":  { …verbatim from SiegeCannon… },
    "rounds_per_formation": {
      "description": "Rounds between each additional formation added to the wave.",
      "maximum": 1000, "minimum": 1, "type": "integer"
    },
    "sprite_scale": { …verbatim from SiegeCannon… },
    "start_round": {
      "description": "First round formations appear.",
      "maximum": 1000, "minimum": 0, "type": "integer"
    }
  },
  "required": ["attack_range_tiles", "attack_speed", "base_count",
               "death_spawn", "dmg", "footprint", "hp", "move_speed",
               "rounds_per_formation", "sprite_scale", "start_round"],
  "type": "object"
}
```

`rounds_per_formation` has `minimum: 1` (it is a divisor — `minimum: 0` would let
the editor write a ZeroDivisionError into the wave composition; note that
`SiegeCannon.rounds_per_cannon` has `minimum: 0`, an existing latent bug — do not
copy it, and do not fix it here either).

**No parity-map entry is needed.** `Formation` is a brand-new type with no
prototype counterpart. `tools/tests/test_balancing_parity.py:66-72`
(`test_mapping_covers_every_prototype_key_exactly`) asserts coverage between the
**prototype file's** keys and the mapping table's keys — it never walks the new
tree — so a new leaf in `enemies.json` demands nothing. Confirmed by reading the
test. **Do not add one; do not edit `balancing_parity_map.json` at all.**

### 2.6 `data/slots.json` — the `Formation` group (the 128×128 override)

Into the `enemies` category's `groups[]` (`data/slots.json:302-427`), inserted
**after `Siege Cannon` and before `Boss`** — `groups` is an ARRAY, its order IS the
editor tree order and survives D-3 sorted-key dumps.

Four eras (matching Walker/Raider/Siege; `variant_slot` clamps `tier` into them).
Every slot uses **ER-1's object form** with the 128×128 override — you are the
first committed consumer of it:

```json
{
  "children": [
    {
      "label": "Era 1",
      "slots": [
        { "frame_h": 128, "frame_w": 128, "key": "formation_stage_1" }
      ]
    },
    {
      "label": "Era 2",
      "slots": [
        { "frame_h": 128, "frame_w": 128, "key": "formation_stage_2" }
      ]
    },
    {
      "label": "Era 3",
      "slots": [
        { "frame_h": 128, "frame_w": 128, "key": "formation_stage_3" }
      ]
    },
    {
      "label": "Era 4",
      "slots": [
        { "frame_h": 128, "frame_w": 128, "key": "formation_stage_4" }
      ]
    }
  ],
  "label": "Formation"
}
```

- Object keys are dumped sorted (`frame_h`, `frame_w`, `key`) — write through
  `engine.data_io.write_validated` / `dumps_deterministic`, never by hand (D-3).
- **Placeholder art is acceptable** (plan, `EnemyReworkPLAN.md:328`). Ship **no**
  `data/sprites/imported/formation_stage_*.png` and **no** manifest entries. Each
  slot renders as a 128×128 grey X, fitted to exactly 2×2 tiles. E-23/E-37: this
  must never crash — and it demonstrably does not, because
  `AssetStore._placeholder` sizes itself off `frame_size()`, which resolves the
  registry override.
- The `SlotRegistry` fail-loud cross-check (a key repeated in one category must
  AGREE on its frame size) is satisfied trivially: these four keys are new and
  appear once each.

### 2.7 The even-footprint sprite offset — **ER-4 INHERITS IT. Do not fix it.**

ER-2 flagged this and deliberately left it. **The decision for ER-4 is: inherit,
document, do not touch the render layer.**

**What it is, precisely.** `Renderer.flush` centres a frame on the *anchor tile's*
diamond centre: `dest = (px − w/2, py + (tile_h/2)·zoom − h/2)` where
`px, py = world_to_screen(wx, wy)` and `(wx, wy)` is the block's MIN corner
(`engine/render/renderer.py:107-117`). The logical 2×2 block's centre is at
`(wx+0.5, wy+0.5)`. In iso screen space that delta is
`dx = (0.5−0.5)·half_w = 0`, `dy = (0.5+0.5)·half_h = +16px` at zoom 1. **So the
Formation's sprite draws exactly half a tile-height (16px) ABOVE its logical
block's centre, with zero horizontal error.** The HP bar rides the sprite
(`_sprite_top`), so it stays visually consistent; combat/splash measure from the
block centre (ER-2), so shells land ~16px "in front of" the drawn feet.

**Why ER-4 does not fix it:**

1. The plan scopes ER-4 to **data + game** (`EnemyReworkPLAN.md:310`). The fix is
   in `engine/render/renderer.py` — root `CLAUDE.md`: *"Engine changes are a
   cross-package task — tell the user."*
2. It is a **render-anchor change**, which is exactly what ER-1 spent a whole phase
   pixel-pinning (`test_render.TestAnchoring`,
   `test_non_enemy_world_frames_are_pixel_identical_to_the_old_rule`). It deserves
   its own phase with its own pins, not a rider on a gameplay phase.
3. It is **cosmetic only**. Pathing uses the anchor correctly; combat uses the
   centre correctly. Nothing is mis-simulated.

**The fix, spelled out for whoever does take it** (put this in the PR body so the
user can dispatch it as a follow-up): in `Renderer.flush`, when `fit_tiles > 0`,
centre on the block centre instead of the anchor —
`px, py = coords.world_to_screen(wx + (fit_tiles−1)/2, wy + (fit_tiles−1)/2)`.
This is engine-generic (it derives purely from `fit_tiles`; no game vocabulary) and
is a **provable no-op** for every existing sprite: `fit_tiles == 0` (buildings,
tiles, deco, HUD) and `fit_tiles == 1` (every current enemy) both give offset 0. I
checked `tools/tests/test_render.py:178-237`: **no existing pin asserts the `dest`
of a `fit_tiles > 1` item**, so the change breaks nothing that ships today. It
would also need `game/ui/effects.py::_sprite_top` (which currently reads
`world_to_screen(wx+0.5, wy+0.5)`) re-derived in the same change, and new pins for
`fit_tiles=2`.

**In this phase: say it in the PR as a known caveat, and move on.** Do not open
`engine/`.

---

## 3. File scope — exhaustive

**May touch (6 source/data files + tests + 1 doc):**

| File | Change | Insertion point |
|---|---|---|
| `game/enemies/enemy.py` | `class Formation(Enemy)` + `ENEMY_CLASSES["formation"]` + docstring roll-call | class between `SiegeCannon` and `Boss`; dict entry after `"siege"` |
| `game/enemies/__init__.py` | import + `__all__` | both sorted; `Formation` after `EnemyCombat` |
| `game/enemies/spawner.py` | `ENABLE_FORMATION = True`; `_formation_group()`; one line in `_compose`; docstring | flag beside `ENABLE_BOSS`; method after `_siege_groups`; call after the `_siege_groups` call in `_compose` |
| `data/balancing/enemies.json` | `EnemyTypes.Formation` block | sorted → between `Boss` and `Raider` |
| `data/schemas/enemies.schema.json` | `EnemyTypes.properties.Formation` + `"Formation"` in `EnemyTypes.required` | sorted → between `Boss` and `Raider` |
| `data/slots.json` | `Formation` group in the `enemies` category's `groups[]`, 4 eras, 128×128 object-form slots | array order → after `Siege Cannon`, before `Boss` |
| `tools/tests/test_enemies.py` | new cases (§4) | new `TestFormation` class; extend `TestSpawnComposition` |
| `game/enemies/CLAUDE.md` | a `## Formation (ER-4)` section + the known-caveat note | after the `## Boss (10G)` section |

**Must NOT touch** (all four are already complete; needing one means ER-2/ER-3 was
under-built — **STOP and report**):

- `game/map/pathfinder.py`
- `game/enemies/components.py`
- `game/enemies/combat.py`
- `game/core/session.py`
- `engine/**` (see §2.7)
- `tools/tests/balancing_parity_map.json` (see §2.5)
- `data/sprites/**` (placeholder art is the deliverable)

ER-4 runs alone in its wave, so there is no concurrent sibling — but stay inside
this list anyway.

---

## 4. Exit gate + Quick Test

### Gate commands

```
py tools/smoke.py
py -m unittest discover -s tools/tests -t .
```

**ZERO NEW failures vs the umbrella baseline.** Post-ER-1 the umbrella was
**930 tests, 16 failures, 1 skip** — 6 balancing-parity divergences + 10
editor/Qt-environment failures. ER-2 adds ~23 tests and ER-3 ~8, so the post-merge
baseline is **~961 tests / 16 failures / 1 skip**. **Measure the real baseline on the
merged umbrella before you change anything** and diff against that number, not
against this estimate.

### ⚠️ The parity gate SKIPS SILENTLY in a worktree — you must defeat that

`tools/tests/test_balancing_parity.py:20-21,43`:

```python
REPO  = Path(__file__).resolve().parents[2]
PROTO = REPO.parent / "HowToBeHuman" / "ClaudePrototype" / "HowToBeHuman" / "balancing"
@unittest.skipUnless(PROTO.is_dir(), "prototype checkout not present")
```

It derives the prototype path from the **repo's parent directory**. Inside a git
worktree parked somewhere else, `PROTO` does not exist and the **entire parity
class skips without a word**. ER-4 changes balancing data, so you must verify parity
for real:

1. Place a scratch worktree as a **SIBLING of the repo**:
   `git worktree add C:/Users/serap/OneDrive/Documents/GitHub/_er4_parity <your-branch>`
2. Run the suite from there and **assert the parity tests RAN** (e.g.
   `py -m unittest tools.tests.test_balancing_parity -v` and confirm you see test
   names, not `skipped`).
3. Remove the scratch worktree when done.

`Formation` is a new type with **no prototype counterpart**, so it needs no
parity-map entries — and the coverage assertions do not demand one (§2.5). The
6 known parity divergences in the baseline must not become 7.

### Required tests (plan, `EnemyReworkPLAN.md:335-337`)

In `tools/tests/test_enemies.py`:

1. **Construction** — `create_enemy("formation", …)` builds; `ETYPE`,
   `REGISTRY_GROUP`, `STAT_SUBTREE` are as declared; `PathAgent.footprint == 2`;
   `SpriteAnimator.fit_tiles == 2.0` and `.scale == 1.0`.
2. **Stat resolution** — tier 0 = the raw `EnemyTypes.Formation` block; tier N =
   base + the cumulative `scale_tiers[0..N)` sum (i.e. it scales like
   Standard/Siege, and does **not** silently read the `Standard` block — assert
   `hp != Standard.hp` at tier 0, which is the exact bug an un-overridden
   `_resolve_stats` would produce).
3. **The 50% break fires exactly ONCE** — damage a Formation to `max_hp * 0.5`;
   assert `alive is False`; run `resolve_combat` with a Session (or the same
   duck-typed stash the ER-3 tests use); assert one burst of `regular: 4` children
   at `int(child.max_hp * 0.8)` HP; report the death **twice** and assert the
   `death_spawned` guard makes the second a no-op (no second burst).
4. **The 2×2 clearance path** — on a map with a one-tile gap in a wall of
   buildings, a `standard` threads it and a `formation` does not (mirror ER-2's
   `test_footprint_path.py` fixture; here it is the *type*, not a raw
   `footprint=2` argument, that must produce it — i.e. it proves the balancing →
   `PathAgent` → pathfinder thread is wired).
5. **Spawner composition, deterministic under an injected `rng`** — with the
   existing `FakeRng`: no formations before `start_round`; exactly
   `base_count + (round − start_round) // rounds_per_formation` at rounds
   16/19/22; formations appear in the shuffled body, never in `siege_front`;
   none on a boss round; and the standard/raider/siege counts at rounds
   *below* `start_round` are **unchanged** from the existing fixtures.
6. **The 128×128 override end-to-end (ER-1's first consumer)** — load the real
   `data/slots.json` registry; assert
   `SlotRegistry.frame_size("formation_stage_1") == (128, 128)` while
   `frame_size("enemy_stage_1_v1") == (64, 96)` (the category default); and,
   through an `AssetStore` with **no manifest entry**, assert
   `store.frame("formation_stage_1").frame_w == 128` (the grey-X placeholder is
   sized off the override) and that it **does not raise** (E-23/E-37). This is the
   proof ER-1 never got to run.

### Quick Test (restated verbatim from the plan, `EnemyReworkPLAN.md:337-338`)

> **Quick Test**: reach the round the Formation first appears — it covers 2×2 tiles,
> walks around single-tile gaps, and at half HP bursts into a cluster of walkers at
> 80% HP.

With the proposed numbers that is **round 16**. Run `py game/main.py`, use the cheat
menu / round skip to reach it, and confirm: the grey-X placeholder body spans 2×2
tiles; it refuses a one-tile gap a walker threads; its HP bar appears as soon as it
takes a scratch and **vanishes at 50%**, at which point four walkers at 44 HP burst
out of it. Report exactly what you verified — live run vs smoke test vs static read.

### Docs

`game/enemies/CLAUDE.md` — a `## Formation (ER-4)` section covering: the subclass
line (thin, `_resolve_stats` overridden because the base one hardcodes `Standard`);
the composition rule + why it is siege-shaped and body-mixed rather than
queue-leading; **why formations do not spawn on boss rounds** (the
`$defs/spawn_counts` / parity constraint); **D4 — there is no break state, breaking
IS dying**; and the inherited even-footprint sprite offset as a known cosmetic
caveat with a pointer to the fix in §2.7. Do not update the root router or another
package's doc.

### PR must state

- The final stat line **and its derivation** (the user retunes in the editor
  afterwards — the plan's open item).
- The known even-footprint sprite offset (inherited, not fixed) + the one-line fix.
- The formation-free boss round (deliberate).
- The Quick Test scenario above.
