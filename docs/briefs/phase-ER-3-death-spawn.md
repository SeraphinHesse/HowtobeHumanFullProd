> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase ER-3 Brief — Generalised toggleable `death_spawn`

> Coordination artifact for the ER-1..ER-4 subagent batch. Planner filled §1–§4;
> the coder treats §3 as a HARD boundary and §2 as a contract; the reviewer
> verifies the diff against §1/§2/§4. Source plan: `planning/EnemyReworkPLAN.md`
> (Context item 3; decision **D4** "Breaking formation IS dying"; Phase ER-3;
> Risks). Branch: `phase-ER-3-death-spawn` (under the ER umbrella).
>
> **This brief OVERRIDES the plan doc in one place** (⚠ CORRECTION 1, §2.1 — the
> `spawns` union). Where they conflict, this brief wins.

**Phase goal:** ONE death-spawn mechanic, declared per enemy type in
`data/balancing/enemies.json`, toggleable, with the Boss's 10G swarm re-expressed
through it and **zero behaviour change**. Death threshold becomes data
(`at_hp_fraction`); breaking formation IS dying (D4) — one code path, no second
state machine.

---

## 0. Known repo state — you are building ON TOP OF ER-1 (do NOT re-derive)

ER-1 is complete on branch `phase-ER-1-render-sizing` and is **not yet on the
umbrella**. Read ER-1's version of any file it changed with
`git show phase-ER-1-render-sizing:<path>`. Its brief is at
`docs/briefs/phase-ER-1-render-sizing.md`. **Every line number in this brief is
the POST-ER-1 line number.**

What ER-1 already did that lands in your files:

- **`data/balancing/enemies.json`** — DELETED `Boss/era_sizes` and the
  `sprite_w`/`sprite_h` keys from all five `Boss/stats` rows. ADDED required
  `footprint` + `sprite_scale` to all four `EnemyTypes` blocks.
  **`Boss/death_spawns` (the 5-entry per-era array) is UNTOUCHED and is yours.**
- **`data/schemas/enemies.schema.json`** — deleted `$defs/era_size`,
  `Boss.era_sizes`, and `sprite_w`/`sprite_h` from `$defs/boss_stat`. Added
  `footprint`/`sprite_scale` properties + `required` entries, and extended the
  top-level `description` bounds-policy sentence with
  `footprint tiles 1-8; sprite_scale multiplier 0.1-8`.
  **`$defs/spawn_counts` (raiders/regular/siege, all three required, 0..10000) is
  UNTOUCHED and is the row shape you reuse.**
- **`tools/tests/balancing_parity_map.json`** — `BOSS_ERA_SIZES` retagged
  `"DROPPED:…"` in the main table; the ten `_py_only` `sprite_w`/`sprite_h`
  entries DELETED. **`_py_only` is now 45 entries** (verified) and the 15
  `Boss/death_spawns` paths still resolve.
- **`game/enemies/enemy.py`** — `STAT_SUBTREE` is now REAL on all four classes
  (`Enemy` `("Standard",)` `:86`, `Raider` `:163`, `SiegeCannon` `:176`, `Boss`
  `:200`), and `Enemy.__init__` `:99-101` already resolves its own balance block
  through it:
  ```python
  block = enemies_balance["EnemyTypes"]
  for seg in self.STAT_SUBTREE:
      block = block[seg]
  ```
  **That `block` local is the hook ER-3 reads `block["death_spawn"]` off. Do not
  build a second resolver.**

Current-source facts you may trust (post-ER-1 line numbers, re-read to confirm
exact insertion points before editing):

| Fact | Where |
|---|---|
| `alive` is `not self.get_component(Health).is_dead` | `game/enemies/enemy.py:150-152` |
| The component list `Enemy.__init__` builds | `game/enemies/enemy.py:102-112` |
| `Boss` class body (init → `mark_death_spawned`) | `game/enemies/enemy.py:186-256` |
| `Boss.__init__` computes `self._era`, calls `super()`, then `add_component(BossState(era=…))` | `:206-213` |
| `Boss.era` / `.death_spawned` properties; `mark_death_spawned()` a **METHOD** | `:244-256` |
| `BossState(Component)` — `era: int = 0`, `death_spawned: bool = False` | `game/enemies/components.py:273-279` |
| `Spawner.spawn_death_swarm(self, scene, col, row, era)` | `game/enemies/spawner.py:235-251` |
| `Session._boss_swarm_pending = None` stash init | `game/core/session.py:60` |
| `post_sim` flush, BEFORE the wave-clear check at `:299` | `game/core/session.py:291-298` |
| `on_enemy_death`'s `ETYPE == "boss"` gate | `game/core/session.py:416-436` (gate `:424-425`) |
| `Health.is_dead` is `self.hp <= 0`; `damage()` clamps at 0 | `engine/core/health.py:14-19` |
| **`Health.is_dead` is read by EXACTLY two call sites**: `game/buildings/building.py:227,240` and `game/enemies/enemy.py:152` | verified by repo-wide grep |
| `Component.__init__` deep-ish-copies `list`/`dict` **defaults** per instance (`:61-62`) but stores an **override by reference** (`:68`) | `engine/core/component.py:58-68` |
| `resolve_combat`'s death loop: `for enemy in scene.by_tag("enemy"): if not enemy.alive: on_enemy_death(enemy); scene.despawn(enemy)` | `game/enemies/combat.py:296-303` |
| Its targeting list is pre-filtered `[e for e in scene.by_tag("enemy") if e.alive]` **before** the death loop | `game/enemies/combat.py:289` |
| `xp_for_etype` falls back to `xp_per_standard_enemy` on an unknown etype | `game/core/xp.py:24-27` |
| `game/enemies/__init__.py` exports `BossState` (`:7`, `:13`) | must be renamed with the component |

**Everything that observes enemy death goes through the duck-typed `alive`
property, never `Health.is_dead`.** That is the single fact that makes D4 a
one-line change: `resolve_combat:289`, `:296-303`, `ProjectileHoming._impact:94`,
`ProjectileArc._impact:159`, `_update_beam:367,398`, `Session.post_sim:302-303`
and `game/ui/effects.py:609,686` all read `.alive`. Rewrite `Enemy.alive` and the
whole threshold-death behaviour follows.

---

## 1. Behavioral spec

### 1.1 The mechanic (plan §Phase ER-3 + D4)

An enemy type may declare a `death_spawn` block. The unit **dies** — in the full
existing sense (despawned by `resolve_combat`, XP awarded, splatter queued, kill
counted) — as soon as `hp <= max_hp * at_hp_fraction`. On that death, if
`enabled`, it bursts a table of children at the tile it died on, each child
spawned at `spawn_hp_fraction` of its own max HP.

- **`at_hp_fraction: 0.0`** ⇒ `alive` is `hp > 0` ⇒ **exactly today's die-at-zero**
  (`Health.is_dead` is `hp <= 0`). Every existing type ships `0.0`.
- **`enabled: false`** ⇒ dies normally, spawns nothing.
- **`spawn_hp_fraction: 1.0`** ⇒ children at full HP ⇒ **exactly today's boss
  swarm**.
- There is **no separate "break" state**. The Formation (ER-4) simply dies at 50%.

### 1.2 Requirement IDs in play

- **E-11** — all state in declared component fields; the `GameObject.__setattr__`
  guard intercepts *public* attribute assignment **before a data descriptor would
  run**, which is why `mark_death_spawned()` is a **method, not a property
  setter**. This is documented at `enemy.py:252-256` and in
  `game/enemies/CLAUDE.md`. **Preserve it.**
- **G-3** — behaviour selected by capability (a component / a data block), never
  by class. `ETYPE == "boss"` in `session.py:424` is a G-3 violation ER-3 removes.
- **G-7** — every tunable from `data/balancing/`. **No code-side default for a
  balancing value** (root `CLAUDE.md`: `data/` JSON is the ONLY value store; no
  py+json dual system). This forces `death_spawn` to be a **required** block on
  every type (§2.2), so the resolver can index it directly with no `.get()`.
- **D-2 / D-3** — schema-valid, deterministic writes (sorted keys, 2-space indent,
  trailing newline) via `engine.data_io.write_validated` / `dumps_deterministic`.
  `test_balancing_data.test_files_are_canonical_on_disk` enforces byte-exactness.
- **D-12** — every schema leaf carries a `description`; every `integer`/`number`
  leaf carries **both** a `minimum` and a `maximum`
  (`tools/tests/test_balancing_data.py:107-129` walks them).
- **D-10/D-11** — `enemies.json` keeps its `_lock` shape untouched.

### 1.3 Invariants that MUST survive (the plan is explicit)

1. **Quick-skip and lives-wipe despawns spawn nothing.** Both
   (`session.py:127-139` `quick_skip_combat`, `:464-477` `_wipe_round`,
   `:160-173` `cheat_skip_round`, `:175-189` `cheat_goto_round`) call
   `scene.despawn(e)` directly and never reach `on_enemy_death`. **Do not add a
   death-spawn hook to any of them.** Pinned by
   `test_boss.TestDeathSwarm.test_quick_skip_despawns_boss_without_swarm`.
2. **The flush stays in `post_sim` BEFORE the wave-clear check** (`session.py:294`
   before `:299`) — the round can never end in the gap between a death and its
   burst hitting the field.
3. **XP is awarded per the existing `game/core/xp.py` table**, unchanged. ER-3
   adds no XP key.
4. **`game/enemies` imports NOTHING from `game/core`.** The seam stays the
   duck-typed callback (`resolve_combat(on_enemy_death=…)` → `Session` stashes →
   `Session` hands the payload back to `Spawner`). `game/core` must not import,
   name, or introspect any `game/enemies` symbol.
5. **The one-shot guard holds across a double-death frame** — reporting the same
   enemy twice bursts once.
6. **`test_boss.py` stays green — the 10G swarm is byte-identical through the new
   path.** This is the phase's central proof.

---

## 2. Architecture plan

### 2.1 ⚠ CORRECTION 1 — the `spawns` "union" is an ARRAY, not a `oneOf`

The plan (and the dispatch brief) say `spawns` must accept **either** a flat
`{type: count}` map **or** the Boss's 5-entry per-era array, designed as a schema
`oneOf`. **A `oneOf` here is unimplementable — it breaks the editor and the D-12
gate.** Evidence, not assumption:

- **`editor/panels/balancing.py:295-326` would CRASH the whole enemies domain.**
  `_build_object` does `prop = self._deref(prop)` then `kind = prop.get("type")`.
  A `oneOf` node has **no `type`**, so it falls through to `_add_leaf_row` →
  `_make_widget` → `raise ValueError(f"{self.domain}.{key}: no widget for schema
  …")` (`:406-407`). The balancing panel builds every domain; selecting `enemies`
  (or any test that constructs the panel) raises. The panel dodges the ONE
  existing `oneOf` (`_lock`) only via `if key.startswith("_"): continue` (`:300`).
- **`test_balancing_data.py`'s walkers cannot see through a `oneOf`.**
  `schema_leaves` (`:41-55`) treats a type-less node as a **leaf**; and
  `doc_schema_pairs` (`:58-74`) does `node["properties"][key]` on any dict value —
  a `oneOf` node has no `properties` → `KeyError`. It survives today only because
  the generator is lazy and `test_out_of_range_numeric_rejected` breaks on the
  first numeric leaf (in `EnemyScaling`). Building a second `oneOf` into the tree
  is loading a gun.

**The correct design collapses the union instead of encoding it.** `spawns` is
**always an array of `$defs/spawn_counts` rows — one row per era**, and the
resolver clamps the unit's era into it:

```
row = spawns[min(max(era, 0), len(spawns) - 1)]
```

which is **literally today's expression** at `spawner.py:244`. Consequences:

- The Boss keeps its 5 rows verbatim ⇒ **byte-identical 10G**.
- A non-era unit (the ER-4 Formation) ships a **1-row array**; its era is always
  0, which clamps to row 0. The "flat map" form is exactly the 1-row case — the
  array is strictly more expressive, not less.
- **No `oneOf` anywhere.** Arrays of `$ref`'d objects are the proven house
  pattern (`stats`, `round_counts`, `scale_tiers` all are) and every walker,
  the editor panel included, already renders them.
- The type vocabulary stays the existing `spawn_counts` one
  (`raiders`/`regular`/`siege`) rather than inventing a second one
  (`standard`/`raider`/`siege`). The `spawn_counts` ↔ ETYPE mapping is the tuple
  already at `spawner.py:245-246`. Keeping it means the 15 `_py_only` parity
  entries re-path with **only the prefix changed** (§3.4).

Report this correction in the PR body.

### 2.2 `data/balancing/enemies.json` — the data (ER-3 owns this file outright)

Add a **required** `death_spawn` block to **all four** `EnemyTypes` blocks.
Required, not optional, for three reasons: (a) G-7 / root-`CLAUDE.md` forbid a
code-side default, so the resolver must be able to index it directly; (b) the
house style is `additionalProperties: false` + a full `required` list (ER-1 made
`footprint`/`sprite_scale` required for exactly this reason); (c) the editor's
recursive panel skips schema keys absent from the doc
(`balancing.py:302-303`), so an optional block a type doesn't have would be
**invisible to the designer** — they could never turn it on, breaking the plan's
own Quick Test ("untick `enabled` in the editor's balancing panel").

**`Boss` — `death_spawns` is REPLACED by `death_spawn`** (delete the old key; the
5 rows move under it verbatim, values untouched):

```json
"death_spawn": {
  "at_hp_fraction": 0.0,
  "enabled": true,
  "spawn_hp_fraction": 1.0,
  "spawns": [
    {"raiders": 5,  "regular": 10, "siege": 1},
    {"raiders": 7,  "regular": 14, "siege": 2},
    {"raiders": 10, "regular": 20, "siege": 3},
    {"raiders": 13, "regular": 26, "siege": 4},
    {"raiders": 16, "regular": 34, "siege": 5}
  ]
}
```

**`Standard` / `Raider` / `SiegeCannon`** — the disabled, zeroed block:

```json
"death_spawn": {
  "at_hp_fraction": 0.0,
  "enabled": false,
  "spawn_hp_fraction": 1.0,
  "spawns": [{"raiders": 0, "regular": 0, "siege": 0}]
}
```

(`spawns` has `minItems: 1`, so a disabled block still needs one zeroed row. That
is the price of "no code-side defaults" and it is the right price — the designer
who ticks `enabled` on a walker gets a working, editable table with no JSON
surgery.)

**Do NOT add a `Formation` type.** ER-4 creates it.

Write the file through `engine.data_io.write_validated` (or re-emit with
`dumps_deterministic`): sorted keys, 2-space indent, trailing newline.

### 2.3 `data/schemas/enemies.schema.json` — the schema (ER-3 owns this file)

**New `$defs/death_spawn`** (all four leaves carry a `description`; both numeric
leaves carry `minimum` AND `maximum` — D-12):

```json
"death_spawn": {
  "additionalProperties": false,
  "description": "Optional-mechanic block (ER-3, D4): when this unit's HP falls to or below at_hp_fraction of its max it DIES (one code path — breaking formation is dying) and, if enabled, bursts the spawns row for its era at the tile it died on. at_hp_fraction 0.0 + enabled false is an inert unit that dies at zero HP and leaves nothing.",
  "properties": {
    "at_hp_fraction": {
      "description": "Death threshold as a fraction of max HP: the unit dies when hp <= max_hp * this. 0.0 = the normal die-at-zero rule. 0.5 = a formation that scatters at half health. Values at or above 1.0 kill the unit the instant it spawns - do not.",
      "maximum": 1,
      "minimum": 0,
      "type": "number"
    },
    "enabled": {
      "description": "Toggle: false means this unit dies at its at_hp_fraction threshold but spawns nothing.",
      "type": "boolean"
    },
    "spawn_hp_fraction": {
      "description": "Children spawn at this fraction of their OWN max HP. 1.0 = full health (the Boss's 10G swarm). Keep it above every child type's own at_hp_fraction or the children die on the frame they appear.",
      "maximum": 1,
      "minimum": 0,
      "type": "number"
    },
    "spawns": {
      "description": "What this unit bursts into, ONE ROW PER ERA, index-aligned with the type's era table (the Boss's stats/round_counts). A type with no eras carries a single row; the era index clamps into the array, so row 0 always applies. This is the era table and the flat per-type table in one shape - there is deliberately no union here.",
      "items": {"$ref": "#/$defs/spawn_counts"},
      "minItems": 1,
      "type": "array"
    }
  },
  "required": ["at_hp_fraction", "enabled", "spawn_hp_fraction", "spawns"],
  "type": "object"
}
```

**Per type**: add `"death_spawn": {"$ref": "#/$defs/death_spawn"}` to
`properties` and `"death_spawn"` to `required` on `Boss`, `Raider`,
`SiegeCannon`, `Standard`.

**Delete** from `Boss`: the `death_spawns` property **and** `"death_spawns"` from
`Boss.required`. Reword `Boss`'s description — it currently reads *"Per-era arrays
are index-aligned: era N uses stats[N], death_spawns[N], round_counts[N]"* → make
it `stats[N]`, `death_spawn.spawns[N]`, `round_counts[N]`.

`$defs/spawn_counts` is **unchanged** (it is still referenced by `round_counts`).
`maxItems` is deliberately **not** set on `death_spawn.spawns` (a non-era type has
1 row, the Boss has 5); the Boss's 5-row-ness is pinned by the parity test, not by
the schema.

**Do not touch** the top-level `description` bounds-policy sentence — ER-1 already
extended it, and `fractions 0-1` already covers both new numerics.

### 2.4 `game/enemies/components.py` — `BossState` → `DeathSpawn` (ER-3's ONLY region here)

Replace `BossState` (`:273-279`) **in place** — same file position, ~70 lines below
`PathAgent` (which ER-2 owns and you must not touch).

```python
class DeathSpawn(Component):
    """The generalised death-spawn mechanic (ER-3, plan D4) — absorbs 10G's
    ``BossState``. Balancing (``EnemyTypes/<type>/death_spawn``) is resolved
    into these fields at construction, exactly like ``Health.max_hp`` /
    ``EnemyCombat.dmg``.

    * ``at_hp_fraction`` — the unit is dead once ``hp <= max_hp * this``.
      ``Enemy.alive`` is the ONE evaluation site (``enemy.py``). 0.0 restores
      the plain ``Health.is_dead`` rule byte-for-byte.
    * ``counts`` — the RESOLVED spawn row for THIS unit's era, already clamped
      at construction ({"raiders": n, "regular": n, "siege": n}).
    * ``era`` — the era index the unit resolved (the Boss's; 0 for everything
      else). Kept because the Boss still reads it (``Boss.era``).
    * ``death_spawned`` — the one-shot burst guard. ``Session.on_enemy_death``
      sets it through ``Enemy.mark_death_spawned()`` the first time a death is
      reported, so a double-death frame can never double-burst.
    """

    era: int = 0
    enabled: bool = False
    at_hp_fraction: float = 0.0
    spawn_hp_fraction: float = 1.0
    counts: dict = {}          # per-instance copy: Component.__init__:61-62
    death_spawned: bool = False
```

All six field types are JSON-safe (E-11). `Component._check_type` accepts an `int`
for a `float` field, so `at_hp_fraction=0` from JSON is fine — but pass
`float(...)` anyway (§2.5).

> **`counts` aliasing trap.** `Component.__init__:61-62` copies a mutable
> *default*, but `:68` stores an *override* **by reference**. Constructing
> `DeathSpawn(counts=block["death_spawn"]["spawns"][era])` would alias the loaded
> balance dict onto every enemy. **Always construct with `counts=dict(row)`.**

### 2.5 `game/enemies/enemy.py` — threshold death + the resolver (ER-3's regions)

**(a) Import** (`:39`): `from .components import DeathSpawn, EnemyCombat, PathAgent`
(alphabetical; `BossState` is gone).

**(b) A new overridable era hook** on `Enemy`, next to `_resolve_stats`
(`:131-133`). This is what lets `Boss.__init__` disappear:

```python
    def _resolve_era(self, balance, tier):
        """Which row of ``death_spawn.spawns`` (and, for the Boss, of ``stats``)
        this unit uses. Types with no era table are always row 0."""
        return 0
```

**(c) `Enemy.__init__` (`:93-127`)** — reuse ER-1's `block` local (`:99-101`), then
**APPEND** `DeathSpawn(...)` as the **LAST** entry of the component list (`:102-112`).
Appending at the end keeps your diff off ER-2's `PathAgent(...)` line at `:104`.
`DeathSpawn` has no `update()`, so list position is behaviourally irrelevant.

```python
        ds = block["death_spawn"]
        era = self._resolve_era(enemies_balance, tier)
        rows = ds["spawns"]
        row = rows[min(max(era, 0), len(rows) - 1)]
        components = [
            Health(max_hp=hp, hp=hp),
            PathAgent(),
            Movement(speed=speed),
            EnemyCombat(dmg=dmg, attack_speed=attack_speed),
            RangeSensor(range_tiles=attack_range),
            SpriteAnimator(slot_key=slot, animation="walk",
                           phase_ms=(col * 137 + row * 251) % 2000,
                           fit_tiles=float(block["footprint"]),
                           scale=float(block["sprite_scale"])),
            DeathSpawn(era=era,
                       enabled=ds["enabled"],
                       at_hp_fraction=float(ds["at_hp_fraction"]),
                       spawn_hp_fraction=float(ds["spawn_hp_fraction"]),
                       counts=dict(row)),
        ]
```

> ⚠ **Name collision — read this twice.** `row` is ALREADY a parameter of
> `Enemy.__init__` (the spawn tile's row, used at `:109` in
> `phase_ms=(col * 137 + row * 251) % 2000` and at `:123` `self._row = row`).
> **Do not shadow it.** Name the resolved spawn-counts dict something else —
> e.g. `spawn_row` — and keep `SpriteAnimator`'s `phase_ms` expression byte-identical.
> Shadowing `row` silently changes every enemy's animation phase and the stored
> `_row`, and no test would obviously say why.

Direct indexing (`block["death_spawn"]`, `ds["enabled"]`, …) — **no `.get()`
defaults**; the keys are schema-required and every test loads the real
`data/balancing/enemies.json` through `game.core.balance.load_balance`.

**(d) `alive` (`:150-152`)** — the whole of D4:

```python
    @property
    def alive(self):
        """Dead once HP falls to or below ``at_hp_fraction`` of max (ER-3 / D4:
        breaking formation IS dying — one code path, no separate break state).
        At the default ``at_hp_fraction`` 0.0 this is exactly
        ``not Health.is_dead`` (``hp <= 0``), so every pre-ER-3 type is
        byte-identical."""
        h = self.get_component(Health)
        ds = self.get_component(DeathSpawn)
        return h.hp > h.max_hp * ds.at_hp_fraction
```

At `at_hp_fraction == 0.0` this is `hp > 0.0` ≡ `not (hp <= 0)` ≡
`not Health.is_dead`. Exact, including `hp == 0` and `max_hp == 0`.
**`Health.is_dead` itself is NOT changed** — `game/buildings/building.py:227,240`
still uses it, and buildings have no `DeathSpawn`.

**(e) The one-shot guard + the plan, on the BASE `Enemy`** (they are no longer
boss-only). Put them right after `dmg` (`:154-156`):

```python
    # -- duck-typed contract read by Session.on_enemy_death (ER-3) ----------

    @property
    def death_spawn_plan(self):
        """The burst this unit leaves behind, or ``None`` when it carries no
        ENABLED ``death_spawn``. Plain, already-resolved data: the Session
        stashes it and hands it straight back to
        ``Spawner.spawn_death_swarm`` without ever inspecting it, so
        ``game/core`` still imports nothing from ``game/enemies``."""
        ds = self.get_component(DeathSpawn)
        if not ds.enabled:
            return None
        return {"counts": dict(ds.counts),
                "spawn_hp_fraction": ds.spawn_hp_fraction}

    @property
    def death_spawned(self):
        return self.get_component(DeathSpawn).death_spawned

    def mark_death_spawned(self):
        """One-shot burst guard setter. A METHOD, not a property setter — the
        E-11 ``GameObject.__setattr__`` guard intercepts public attribute
        assignment before a data descriptor would run."""
        self.get_component(DeathSpawn).death_spawned = True
```

**(f) `Boss` (`:186-256`)** — `__init__` and `self._era` are **DELETED** outright
(nothing else reads `_era`; verified by grep). What remains:

```python
class Boss(Enemy):
    """... (update the docstring: era/death_spawned/mark_death_spawned are read
    over ``DeathSpawn``, not ``BossState``; the swarm is now the generalised
    ER-3 mechanic with at_hp_fraction 0.0 + spawn_hp_fraction 1.0.)"""

    ETYPE = "boss"
    REGISTRY_GROUP = "Boss"
    DEFAULT_SLOT = "boss_era_0"
    STAT_SUBTREE = ("Boss",)
    EXTRA_TAGS = ("boss",)
    HP_BAR_W, HP_BAR_H, HP_BAR_LIFT = 48, 4, 48

    def _resolve_era(self, balance, tier):
        # `tier` doubles as the era index for the boss (spawner-threaded, 10G).
        return min(max(tier, 0),
                   len(balance["EnemyTypes"]["Boss"]["stats"]) - 1)

    def _resolve_stats(self, balance, tier):
        st = balance["EnemyTypes"]["Boss"]["stats"][self._resolve_era(balance, tier)]
        return (st["hp"], st["dmg"], st["move_speed"], st["attack_speed"],
                st["attack_range_tiles"])

    def on_spawn(self):
        ...                       # UNCHANGED (:222-240)

    @property
    def era(self):
        """The era index (read by tests + any future era-keyed UI)."""
        return self.get_component(DeathSpawn).era
```

`Boss.stats` and `Boss.death_spawn.spawns` both have exactly 5 rows, so
`_resolve_era`'s clamp against `stats` lands on the same row `spawn_death_swarm`
picked today (`spawner.py:244` clamped an already-clamped era against a 5-row
table). **Byte-identical.**

> **Ordering constraint:** `_resolve_era` is called from `Enemy.__init__`
> **before** `super().__init__()` completes — it must only read its arguments,
> never `self._*` state. It does.

**(g) `game/enemies/__init__.py`** — `BossState` → `DeathSpawn` in the import
(`:7`) and in `__all__` (`:13`, keeping alphabetical order).

### 2.6 `game/enemies/spawner.py` — the generalised burst (ER-3's ONLY region here)

Replace `spawn_death_swarm` (`:235-251`, the last method in the file). ER-2 owns
the `rng.choice(spawn_tiles)` sites at `:113`, `:154-159`, `:171`, `:181` — do not
go near them.

```python
# spawn_counts key -> the etype it spawns. The iteration ORDER is load-bearing:
# it fixes how many draws each burst takes from the injected `rng` (variant
# picks), so it must stay standard -> raider -> siege (prototype game.py:1314-34).
_SWARM_TYPES = (("standard", "regular"), ("raider", "raiders"),
                ("siege", "siege"))
```

```python
    def spawn_death_swarm(self, scene, col, row, plan):
        """Burst ``plan`` — an enemy's resolved ``death_spawn_plan`` — at
        ``(col, row)``, IMMEDIATELY into the scene (never the queue), so the
        children path from that tile on spawn. Members take the CURRENT round's
        scale tier (standard + siege scale; raiders never do). Each child is
        seeded to ``plan["spawn_hp_fraction"]`` of its own max HP; at 1.0
        (the Boss's 10G swarm) ``Health`` is not touched at all, so that path is
        byte-identical. The Session flushes this before its wave-clear check;
        all enemy construction stays in this package."""
        counts = plan["counts"]
        frac = plan["spawn_hp_fraction"]
        for etype, key in _SWARM_TYPES:
            for _ in range(counts[key]):
                enemy = create_enemy(
                    etype, col, row, self._balance, self._tilemap,
                    self._tier, self._registry, self._rng)
                if frac < 1.0:
                    health = enemy.get_component(Health)
                    health.hp = max(1, int(health.max_hp * frac))
                scene.spawn(enemy)
```

Add `from engine.core import Health` to the imports (`:19-21`). Engine import —
no layering break.

**Why `if frac < 1.0` and not an unconditional `int(max_hp * frac)`:** it
guarantees the Boss path never writes `Health.hp` at all, so "byte-identical" is
structural, not a float-rounding argument. **Keep the guard.**

**Why `max(1, …)`:** a child must never spawn already-dead. Note the designer
footgun in `game/enemies/CLAUDE.md`: a `spawn_hp_fraction` at or below a child
type's own `at_hp_fraction` makes the child die on the frame it appears (and, if
that child had an enabled `death_spawn`, chain). The schema description says so
too. ER-3 does **not** add a runtime guard for it — data is the source of truth
and the editor's 0..1 spinbox bounds are the fence.

Update the module docstring (`:14`), which names `spawn_death_swarm` as "the
Session-driven boss-death burst".

### 2.7 `game/core/session.py` — the generalised seam + the stash (ER-3 owns this file)

**Stash init (`:60`)** — a **list**, not a single slot. More than one enemy can
break in the same frame (an ER-4 Formation wave will), and the 10G single-slot
stash would silently drop all but the last.

```python
        # (col, row, plan) death-spawn bursts to flush in post_sim (ER-3; the
        # 10G single-slot `_boss_swarm_pending` generalised — several units can
        # die in one frame). `plan` is an OPAQUE payload from the enemy's
        # `death_spawn_plan`; core never inspects it, it just hands it back.
        self._death_spawns_pending = []
```

**`on_enemy_death` (`:416-436`)** — replace the `ETYPE == "boss"` gate
(`:424-425`) with the capability gate. **Everything else in the method (splatter
event, `enemies_killed`, `_award_enemy_xp`) is untouched.**

```python
        # -- ER-3 death spawn: one-shot stash for ANY type carrying an ENABLED
        # `death_spawn` (10G's boss swarm is now just one instance of it).
        # Duck-typed — game/core imports nothing from game/enemies. The
        # DeathSpawn.death_spawned guard makes a second report of the same unit
        # a no-op. A unit despawned by quick-skip / a lives wipe / a cheat never
        # reaches this callback, so it spawns nothing.
        plan = getattr(enemy, "death_spawn_plan", None)
        if plan is not None and not getattr(enemy, "death_spawned", True):
            enemy.mark_death_spawned()
            wx, wy = enemy.transform.world_pos
            self._death_spawns_pending.append((round(wx), round(wy), plan))
        # -- /ER-3 --
```

Both `getattr` defaults are the safe ones: a stub enemy with neither attribute
yields `plan is None` **and** `death_spawned is True` → no burst. (Several tests
pass bare stubs through the death callbacks; keep this.)

**`post_sim` flush (`:291-298`)** — same position, **still strictly before the
wave-clear check at `:299`**.

```python
        # -- ER-3: flush every death-spawn burst BEFORE the wave-clear check, so
        # the round can never end in the gap between a unit's death and its
        # children hitting the field. Enemy construction stays in the Spawner.
        if self._death_spawns_pending:
            pending = self._death_spawns_pending
            self._death_spawns_pending = []
            for col, row, plan in pending:
                self.spawner.spawn_death_swarm(scene, col, row, plan)
        # -- /ER-3 --
```

Note the drain-then-iterate (rebind the list to `[]` **before** the loop): a
child could in principle die inside the same frame later; re-entrancy must not
lose or double-run a burst.

`game/core/session.py` contains **no other reference** to `boss`-swarm state
(grep `_boss_swarm_pending` — only `:60`, `:294-296`, `:428`). The boss cutscene
(`:346-370`, `:447-462`) is a separate mechanism keyed off `round_interval` and is
**not** touched.

### 2.8 How 10G is reproduced byte-for-byte — the proof, step by step

| 10G today | ER-3 | Identical because |
|---|---|---|
| `Boss.__init__` clamps era vs `stats` (5 rows) | `Boss._resolve_era` clamps era vs `stats` (5 rows) | same expression, same table |
| `alive = not Health.is_dead` = `hp > 0` | `alive = hp > max_hp * 0.0` = `hp > 0` | `Boss.death_spawn.at_hp_fraction == 0.0` |
| `on_enemy_death` gates on `ETYPE == "boss"` | gates on `death_spawn_plan is not None` | only `Boss` ships `enabled: true`; the other three ship `enabled: false` → `plan is None` |
| stash `(col, row, era)` (single slot) | stash `[(col, row, plan)]` (list) | only one boss per round → the list holds exactly one entry |
| flush before wave-clear | flush before wave-clear | same position in `post_sim` |
| `spawns[clamp(era)]` at flush time | row clamped at CONSTRUCTION, carried on `DeathSpawn.counts` | era is already clamped in `Boss`; `spawns` and `stats` are both 5 rows |
| iterate `("standard","regular"), ("raider","raiders"), ("siege","siege")` | same tuple, same order (`_SWARM_TYPES`) | identical `rng` draw sequence in `variant_slot` ⇒ identical variant picks |
| children at `self._tier`, full HP | children at `self._tier`; `Health` untouched when `frac == 1.0` | `Boss.death_spawn.spawn_hp_fraction == 1.0` |
| values `{10/5/1, 14/7/2, 20/10/3, 26/13/4, 34/16/5}` | same 5 rows, moved under `death_spawn` | the 15 `_py_only` parity entries assert exactly this against the prototype |

---

## 3. File scope + shared-file contract

ER-2 runs **concurrently** with you off the umbrella. Region ownership is
**BINDING**.

### 3.1 Files ER-3 owns OUTRIGHT

| File | Change |
|---|---|
| `game/core/session.py` | stash init `:60`; `post_sim` flush `:291-298`; `on_enemy_death` gate `:424-425`. Nothing else. |
| `data/balancing/enemies.json` | `death_spawn` block on all four `EnemyTypes`; delete `Boss/death_spawns` |
| `data/schemas/enemies.schema.json` | `$defs/death_spawn`; `death_spawn` property + `required` on all four types; delete `Boss.death_spawns` + its `required` entry; reword `Boss.description` |
| `tools/tests/balancing_parity_map.json` | re-path the 15 `_py_only` `death_*` entries (§3.4); update `_policy` prose |
| `game/enemies/__init__.py` | `BossState` → `DeathSpawn` (`:7`, `:13`) |
| `game/enemies/CLAUDE.md`, `data/CLAUDE.md` | docs (§4) |

### 3.2 Shared files — ER-3's regions ONLY

| File | **ER-3 owns** | **Do NOT touch** |
|---|---|---|
| `game/enemies/enemy.py` | the `.components` import `:39`; `_resolve_era` (new, beside `_resolve_stats` `:131-133`); the `DeathSpawn(...)` entry **appended at the END** of the component list `:102-112` + the `ds`/`era`/`spawn_row` locals just above it; `alive` `:150-152`; the new `death_spawn_plan` / `death_spawned` / `mark_death_spawned` on `Enemy` (after `dmg` `:154-156`); the whole `Boss` class body `:186-256` | **ER-2 owns the `PathAgent(...)` construction line ONLY** (`:104`) — it will add `footprint=…` there. **ER-4 owns** the new `Formation` subclass + `ENEMY_CLASSES` (`:259-265`). Leave `Raider` `:159-169` / `SiegeCannon` `:172-183` alone. |
| `game/enemies/components.py` | `BossState` → `DeathSpawn`, **in place at `:273-279`** (end of file) | **ER-2 owns `PathAgent` (`:43-207`)** — do not touch it, not even its docstring. `EnemyCombat` (`:210-270`) and `_condition_mods` (`:28-38`): nobody's, leave them. |
| `game/enemies/spawner.py` | `spawn_death_swarm` `:235-251` (the last method); the `_SWARM_TYPES` module constant; the `from engine.core import Health` import; the module docstring line `:14` | **ER-2 owns the `rng.choice(spawn_tiles)` sites** (`:113`, `:154-159`, `:171`, `:181`) and may factor them into a helper. Do not touch `_compose` / `_boss_round` / `_raider_group` / `_siege_groups` / `_build_queue` / `update`. |
| `tools/tests/test_boss.py` | **ONE line**: `:213` `spawns = BOSS["death_spawns"][0]` → `spawns = BOSS["death_spawn"]["spawns"][0]`. Plus new cases (§4). | Every existing assertion. If any other one needs changing, **stop and report** — that is a behaviour regression, not a rename. |
| `tools/tests/test_balancing_parity.py` | **docstring only** (`:8-9` names `death_spawns`), optional | any test logic. **Do NOT add a `DROPPED:` branch to `test_py_only_boss_eras_expectations`.** |

**Expect one trivial merge conflict** with ER-2 in `Enemy.__init__`'s component
list (its `PathAgent(footprint=…)` edit and your appended `DeathSpawn(...)` sit
inside one diff hunk). **Resolution: keep BOTH lines.** Nothing else in these
three files should conflict.

### 3.3 Files ER-3 must NOT touch (hard boundary)

`game/map/pathfinder.py` · `game/enemies/combat.py` · `game/buildings/**` ·
`data/slots.json` · `engine/**` (including `engine/core/health.py` — `Health.is_dead`
stays exactly as it is) · `editor/**` · `game/ui/**` · `game/main.py` ·
`game/core/xp.py` · `data/balancing/core.json`.

### 3.4 The parity-map re-pathing plan — READ THIS BEFORE YOU EDIT THE MAP

`tools/tests/balancing_parity_map.json` has **TWO tables with different
semantics**:

- The **main mapping table** (`Balancing_Enemies.json` etc.) — its consumer
  `test_balancing_parity.py:84-85` **skips** entries whose value is a
  `"DROPPED:…"` string.
- **`_py_only`** — its consumer `test_py_only_boss_eras_expectations`
  (`test_balancing_parity.py:101-108`) does `resolve(self.docs, entry["path"])`
  and `entry["expect"]` with **NO `DROPPED:` branch**. A bare string there raises
  `TypeError: string indices must be integers`.

ER-3 moves the Boss's death table. **The 15 `_py_only` `death_*` entries must be
RE-PATHED** — `_py_only` is a literal-expectation table (`{path, expect}`) and
supports it natively. **Do NOT retag them `DROPPED:`. Do NOT delete them** — they
are the parity proof that the 10G swarm is unchanged, and they are what makes
§2.8's byte-identical claim mechanically checkable.

The change is a pure prefix swap:
`enemies:EnemyTypes/Boss/death_spawns/N/<k>` → `enemies:EnemyTypes/Boss/death_spawn/spawns/N/<k>`.
`resolve()` (`:26-32`) splits on `/` and treats digit segments as list indices, so
the new path resolves unchanged.

**All 15 entries, exhaustively** (values must be left EXACTLY as they are):

| `_py_only` key | new `path` | `expect` |
|---|---|---|
| `BOSS_ERAS[0].death_regular` | `enemies:EnemyTypes/Boss/death_spawn/spawns/0/regular` | 10 |
| `BOSS_ERAS[0].death_raiders` | `enemies:EnemyTypes/Boss/death_spawn/spawns/0/raiders` | 5 |
| `BOSS_ERAS[0].death_siege`   | `enemies:EnemyTypes/Boss/death_spawn/spawns/0/siege`   | 1 |
| `BOSS_ERAS[1].death_regular` | `enemies:EnemyTypes/Boss/death_spawn/spawns/1/regular` | 14 |
| `BOSS_ERAS[1].death_raiders` | `enemies:EnemyTypes/Boss/death_spawn/spawns/1/raiders` | 7 |
| `BOSS_ERAS[1].death_siege`   | `enemies:EnemyTypes/Boss/death_spawn/spawns/1/siege`   | 2 |
| `BOSS_ERAS[2].death_regular` | `enemies:EnemyTypes/Boss/death_spawn/spawns/2/regular` | 20 |
| `BOSS_ERAS[2].death_raiders` | `enemies:EnemyTypes/Boss/death_spawn/spawns/2/raiders` | 10 |
| `BOSS_ERAS[2].death_siege`   | `enemies:EnemyTypes/Boss/death_spawn/spawns/2/siege`   | 3 |
| `BOSS_ERAS[3].death_regular` | `enemies:EnemyTypes/Boss/death_spawn/spawns/3/regular` | 26 |
| `BOSS_ERAS[3].death_raiders` | `enemies:EnemyTypes/Boss/death_spawn/spawns/3/raiders` | 13 |
| `BOSS_ERAS[3].death_siege`   | `enemies:EnemyTypes/Boss/death_spawn/spawns/3/siege`   | 4 |
| `BOSS_ERAS[4].death_regular` | `enemies:EnemyTypes/Boss/death_spawn/spawns/4/regular` | 34 |
| `BOSS_ERAS[4].death_raiders` | `enemies:EnemyTypes/Boss/death_spawn/spawns/4/raiders` | 16 |
| `BOSS_ERAS[4].death_siege`   | `enemies:EnemyTypes/Boss/death_spawn/spawns/4/siege`   | 5 |

The other 30 `_py_only` entries (`stats/N/{hp,dmg,move_speed,attack_speed,
attack_range_tiles,name}`) are **untouched** — `_py_only` stays at **45 entries**.

**The main table needs NO change.** Its `BOSS_DEATH_REGULAR` / `BOSS_DEATH_RAIDERS`
/ `BOSS_DEATH_SIEGE` entries are already `DROPPED:` strings (verified) and no
main-table entry points at `Boss/death_spawns`.

Also update the `_policy` prose string — it says *"reshaped into `Boss/stats` +
`Boss/death_spawns`"* → `Boss/death_spawn/spawns`. (`_policy` is `_`-prefixed, so
`entries()` and `setUpClass` skip it; editing it is safe.)

Rewrite the file through `engine.data_io.dumps_deterministic` (sorted keys,
2-space indent) — it is a test fixture, not a schema'd data file, but it is
committed in that shape; keep it byte-clean.

---

## 4. Exit gate + Quick Test

### 4.1 Gate (both commands, from the repo root)

```
py tools/smoke.py
py -m unittest discover -s tools/tests -t .
```

**ZERO NEW failures against the umbrella baseline: 908 tests, 18 failures, 1 skip.**
Compare failure **names**, not counts. The 18 known failures are:

- **6** `test_balancing_parity` (pre-existing on `Development`)
- **10** editor / Qt-env
- `test_details_panel::test_too_small_sheet_rejected` — ER-1 legitimately
  replaces it
- `test_combat_speed::test_2x_spawns_the_wave_faster_than_1x` — timing-flaky

Data changed ⇒ `tools/smoke.py`'s schema validation over all of `data/` must pass.

### 4.2 ⚠ THE PARITY TESTS WILL SILENTLY **SKIP** IN YOUR WORKTREE — read this

`tools/tests/test_balancing_parity.py:20-21`:

```python
REPO  = Path(__file__).resolve().parents[2]
PROTO = REPO.parent / "HowToBeHuman" / "ClaudePrototype" / "HowToBeHuman" / "balancing"
```

and the class is `@unittest.skipUnless(PROTO.is_dir(), …)` (`:43`). In a git
worktree under `.claude/worktrees/agent-XXX/`, `REPO.parent` is
`.claude/worktrees/` — the prototype is not there, so **the entire
`TestBalancingParity` class skips and your central proof never runs.** It will
look green and prove nothing, and your re-pathing bug will land on the umbrella.

**This matters more to ER-3 than to any other phase in the batch.** Do ONE of
these, and say in your report which:

- **Preferred — put the worktree where `REPO.parent` resolves.** The prototype
  lives at `C:/Users/serap/OneDrive/Documents/GitHub/HowToBeHuman/ClaudePrototype/HowToBeHuman/balancing`
  (verified present). So create the worktree as a **SIBLING of the repo**, i.e.
  directly under `C:/Users/serap/OneDrive/Documents/GitHub/`:
  ```
  git worktree add ../er3-parity phase-ER-3-death-spawn
  ```
  Run `py -m unittest tools.tests.test_balancing_parity -v` there and confirm you
  see **4 tests RUN** (not skipped) — `test_mapping_covers_every_prototype_key_exactly`,
  `test_migrated_values_equal_prototype_values`, `test_dropped_entries_carry_a_reason`,
  `test_py_only_boss_eras_expectations`. Then confirm the failure set is the
  **same 6** as the baseline (they are pre-existing) and that
  `test_py_only_boss_eras_expectations` is **NOT** among them. Clean the worktree
  up afterwards.
- **Fallback — replicate the assertion by hand.** For each of the 15 re-pathed
  entries, load `data/balancing/enemies.json` and assert
  `resolve(docs, entry["path"]) == entry["expect"]`, and cross-check each
  `expect` against `BOSS_ERAS` in
  `../HowToBeHuman/ClaudePrototype/HowToBeHuman/balancing/balancing_enemies.py`.
  Do it in a throwaway script; do not commit it.

Whichever you pick: **a `TypeError: string indices must be integers` out of
`test_py_only_boss_eras_expectations` means you retagged a `_py_only` entry
`DROPPED:` — go back and re-path it instead.**

### 4.3 Tests to write / update (named, not optional)

**`tools/tests/test_boss.py`** — the central proof. **It must stay green.**
- The ONLY permitted edit to existing code is `:213`
  `BOSS["death_spawns"][0]` → `BOSS["death_spawn"]["spawns"][0]`.
- `TestDeathSwarm.test_swarm_spawns_once_at_boss_tile_with_current_tier`
  (`:208-235`) must pass **unmodified** otherwise — same counts, same tile, same
  tier-scaled HP, and its one-shot re-report check at `:230-235` is your
  double-death guard test for the Boss.
- `test_quick_skip_despawns_boss_without_swarm` (`:237-242`) must pass unmodified.
- `TestBossEraStats` (`:146-186`) must pass unmodified — `b.era` still resolves
  (now over `DeathSpawn`), and `test_huge_era_clamps_to_last_row` pins the clamp.
- **Add** `test_swarm_children_spawn_at_full_hp`: every swarm child's
  `Health.hp == Health.max_hp` (pins `spawn_hp_fraction == 1.0` ⇒ `Health`
  untouched).

**`tools/tests/test_enemies.py`** (or a new `tools/tests/test_death_spawn.py` —
your call; keep it in ONE file) — the new mechanic, driven by a synthesised
balance dict deep-copied from the real one so you can flip fields without
touching `data/`:
1. **`enabled: false` spawns nothing.** Kill a `Standard` through a real
   `frame()`/`resolve_combat` + `Session` cycle; assert `post_sim` spawned no
   enemies and `session._death_spawns_pending == []`.
2. **A 50% threshold breaks exactly once and spawns children at 80% HP.** Build a
   type with `at_hp_fraction: 0.5`, `spawn_hp_fraction: 0.8`,
   `spawns: [{"regular": 4, "raiders": 0, "siege": 0}]`. Assert:
   - `alive` is **True** at `hp == max_hp * 0.5 + 1` and **False** at
     `hp == max_hp * 0.5` (the boundary is `<=`, i.e. `hp > threshold` is alive);
   - one `resolve_combat` sweep reports the death **once**, despawns it, and
     `post_sim` puts exactly 4 standards on the field;
   - each child's `hp == max(1, int(child_max_hp * 0.8))` and `< max_hp`;
   - the children are at the parent's tile.
3. **The one-shot guard holds across a double-death frame.** Call
   `session.on_enemy_death(e)` twice on the same unit (and/or run two
   `resolve_combat` sweeps before a `scene.update` applies the despawn queue);
   assert `len(session._death_spawns_pending) == 1` after the first, and that a
   second `post_sim` adds nothing.
4. **`at_hp_fraction: 0.0` is byte-identical to `Health.is_dead`.** Parametrise
   over `hp ∈ {max_hp, 1, 0}` and assert `enemy.alive == (not
   enemy.get_component(Health).is_dead)` for every stock type.
5. **Two units breaking in the SAME frame both burst** (the list-stash fix). This
   is the one thing 10G's single-slot stash could not do and ER-4 depends on.

**`tools/tests/test_balancing_data.py`** — no new code; it must stay green. It is
what enforces D-12 on the four new leaves (`description` on all; `minimum` +
`maximum` on `at_hp_fraction` and `spawn_hp_fraction`) and D-3 canonical form on
disk.

**`tools/tests/test_balancing_parity.py`** — no logic change. See §4.2.

**`tools/tests/test_editor_panels.py`** — no new code, but **run it and read the
result**: it constructs the balancing panel over every domain and is the test that
would have caught a `oneOf` (§2.1). If the enemies panel raises
`ValueError: enemies.<path>: no widget for schema …`, you have introduced a
type-less schema node — go fix the schema, not the panel.

### 4.4 Quick Test (verbatim from `planning/EnemyReworkPLAN.md` ER-3)

> Reach a boss round — the swarm behaves exactly as before. Then untick `enabled`
> in the editor's balancing panel, save, replay: no swarm.

Concretely: `py game/main.py` → `Ctrl+L` cheat menu → `Go to Round 10` → End Turn
→ kill the boss → the 10/5/1 swarm bursts at its tile, exactly as today. Then
`py editor/main.py` → enemies → Boss → **Death Spawn** section → untick `enabled`
→ **Save Balancing Changes** → Play → same round: the boss dies and leaves
nothing. **Restore `enabled: true` before committing** (`git diff
data/balancing/enemies.json` must show only the intended restructure).

### 4.5 Docs to update (package docs only — not the root router)

- **`game/enemies/CLAUDE.md`** — rewrite the **Boss (10G) → "Death swarm"** bullet
  and add an **ER-3 `death_spawn`** section to **Rules**: the mechanic, D4
  ("breaking formation IS dying" — `alive` is `hp > max_hp * at_hp_fraction`, ONE
  code path), the `DeathSpawn` component absorbing `BossState`, the era-indexed
  `spawns` array (why there is no union), the `death_spawn_plan` /
  `death_spawned` / `mark_death_spawned()` **method** contract (E-11), and the
  `spawn_hp_fraction <= child at_hp_fraction` footgun. Also update the
  **"Round-loop / XP callbacks — layering trick"** section's 10G bullet: the
  handshake is now type-agnostic and carries an opaque plan, not `(col, row, era)`.
- **`data/CLAUDE.md`** — the parity note at `:48-49` names
  `Boss/death_spawns`; re-point it at `Boss/death_spawn/spawns` and note that
  `_py_only` is a **literal-expectation** table whose consumer has **no
  `DROPPED:` branch** — entries there are re-pathed, never retagged. Document the
  `death_spawn` block shape in the enemies-domain section.
- **`game/core/CLAUDE.md`** — the "Death swarm handshake (layering)" bullet under
  *Boss cutscene + bonuses (Phase 10G)*: the gate is no longer `ETYPE == "boss"`,
  the stash is a list, and the payload is opaque. **This is a third package doc —
  the plan's Docs bullet names only two. Update it anyway; leaving it wrong is
  worse than an off-plan edit.** Report that you did.

### 4.6 Report exactly what was verified

Name which: `py tools/smoke.py` · the full unittest run (with the failure-name
diff vs the 18-failure baseline) · **the sibling-worktree parity run (§4.2) and
whether the 4 parity tests RAN or SKIPPED** · a live `py game/main.py` boss round
· a live `py editor/main.py` toggle. Per the root router's exit gate, state
whether each was a real run or a static read.
