# CLAUDE.md — DATA package

Self-contained guide for `data/` — the single source of truth every other
package reads. Requirements: SPEC.md §5 (`D-*`). **When you change a format or
schema, update THIS doc.**

**Adding or changing a balancing tunable? Use the `/add-balancing-value` skill**
— it keys into `balancing/<domain>.json` + the schema mirror through the
validating writer; don't hand-edit the JSON.

## What lives here
- `schemas/` — one JSON Schema per file type.
  `dispatch_handoff.schema.json` and `highscores.schema.json` are the TWO
  schemas with no `data/` content file at all (handoffs are written to the
  gitignored `.claude/dispatch/`, high scores to the gitignored `scores/`, both
  still through `write_validated` — the single write path holds), which is
  legal: `tools/smoke.py::validate_data` skips `data/schemas/` entirely. When a
  schema governs per-machine runtime state rather than designer content, this
  is the shape to copy. Three others
  (`map_file`, `balancing_history`, `agent_form`) pair with a whole **directory**
  rather than a stem-mate — see the directory rule below.
- `slots.json` — the slot registry (which asset slots exist per category,
  frame sizes, animation vocabularies, editor grouping) (D-32, E-34; see
  the Phase 5 section for why it is NOT under `schemas/`).
- `balancing/` — one file per domain (`buildings.json`, `enemies.json`,
  `map.json`, `ui.json`, `core.json`, `vfx.json`) (D-10).
- `balancing_history/` — one file per domain (`buildings.json`, …, matching
  `balancing/`'s stems), each a flat newest-first JSON array of full-document
  snapshots appended only by the editor's explicit "Save Balancing Changes"
  action (`editor/balancing_history.py`, `editor/panels/balancing.py`). The
  **second schema-pairing exception** (see the three-exception rule below):
  every `data/balancing_history/*.json` validates against
  `schemas/balancing_history.schema.json`, not `schemas/<domain>.schema.json`
  — its filename stem intentionally collides with the real domain file's stem,
  so `tools/smoke.py` special-cases the directory the same way it already does
  for `maps/`.
- `agent_forms/` — one agent-dispatch **form spec** per game thing-type
  (`add-enemy.json`, …), the data the editor renders its "Add new X" dialog
  from (AD-1). The **third schema-pairing exception**: every
  `data/agent_forms/*.json` validates against `schemas/agent_form.schema.json`
  regardless of its stem (the stem is the form `id`, cross-checked by
  `editor/agent_forms.load_form_specs`, which the schema cannot express). Read
  ONLY through `editor.agent_forms`; the handoff a submitted form writes is NOT
  data/ content — it goes to gitignored `.claude/dispatch/`.
- `maps/` — map files (terrain/zone grid with spawning as a painted zone,
  deco layer, base position) + `active_map.json` pointer (D-20/21).
- `sprites/` — `asset_manifest.json` (manifest v2, D-30) + `imported/` sheet
  PNGs (committed — they are content, not build artifacts).

## Balancing files (Phase 4 D-10/11/12, restructured Phase 9A)
- Six domains exist: `balancing/{buildings,enemies,map,ui,core,vfx}.json`,
  each with `schemas/<domain>.schema.json`. **`vfx` is the newest (ESV-3a)**:
  it promoted `vfx` from an asset-only `slots.json` category to a full
  balancing domain (`editor/domains.py::domains()` derives the domain list,
  so this needed zero editor edits — see `/add-category`). Its `procedural`
  top-level block holds the particle/gold/slash/splatter emitter tunables
  ported out of `game/ui/effects.py` module constants (spark bursts,
  building-death shards, muzzle spray, melee slash, gold tile highlight,
  blood splatter, floater colour/lifetime); `engine/vfx/` holds the pure
  emitters, injected with these values as frozen dataclasses (D5 — the
  engine never reads `data/` itself). **ESV-3b** added four more sibling
  blocks inside the same `procedural` object — `beam` (Sun Scorcher line
  colour ramp/width/origin-lift), `crater` (mortar scorch colour/alpha/fade
  life), `lightning` (bolt/flash/marker colours, widths, jitter, segment
  count, the two fade lifetimes), `announce` (boss-banner colour/alpha
  ceiling) — reusing the same `$defs/color`/`$defs/ramp` schema shapes.
  Unlike ESV-3a's five, none of these four are `VfxSystem` state: the scene
  already owns the crater/lightning fade clocks (`CraterFade`/
  `LightningFXFade` components), so the two cosmetic lifetimes
  (`crater.life`, `lightning.bolt_life`/`marker_life`) are threaded as
  REQUIRED constructor arguments from `game/enemies/combat.py`'s
  `resolve_combat` / `game/core/lightning.py`'s `strike` down to those
  components — never a code-side default. **ESV-5** added the promised
  sibling `triggers` object at the top level: one row per cosmetic EVENT
  (`building_placed`/`_level_up`/`_tier_up`, `building_destroyed`,
  `enemy_attack_melee`/`_ranged`, `enemy_death`, `splash_impact`,
  `defender_fire`), each `{sprite_slot, procedural}` — an enum'd `vfx_*` slot
  key (or `""`) to play as a one-shot sprite when it has imported art, and an
  enum'd procedural fallback (or `""` for a silent no-op). `slots.json`'s
  `vfx` category's `Effects` group grew four new slots for this —
  `vfx_muzzle`/`vfx_death`/`vfx_slash`/`vfx_crater` — alongside the two
  pre-existing, still-unbound `vfx_hit`/`vfx_explosion`. **ESV-6** (the
  plan's final phase) added the 10th trigger row, `projectile_hit`
  (`{sprite_slot: "", procedural: ""}`, shipped INERT like `defender_fire`) —
  the target's `impact` anchor at a homing projectile's landing, and the
  first consumer of the `vfx_hit`/`vfx_explosion` slots the plan's opening
  complaint named as orphaned. The `sprite_slot` enum already accepted both
  before this phase; only the `triggers` object's `properties`/`required`
  needed the new key. ESV-6 also re-pointed a subset of the ESV-5 dispatch
  sites at manifest anchors (VISUAL ONLY, D4) — a `data/` change to
  `data/balancing/vfx.json` content, not to its schema. **The
  fix-anchor-offset-and-bullet-sprites follow-up** (post-ESV live-testing)
  added a sibling `procedural.projectile` block — `stone_color`/
  `shell_color`/`stone_size`/`shell_size`/`lift_frac`, the fallback dot
  `submit_projectiles` draws for an in-flight shot with no imported sprite —
  and two new `vfx` category slots in `slots.json`'s `Effects` group,
  `vfx_projectile`/`vfx_shell` (shared across every defender/every mortar
  respectively, never per-building art), both bare strings inheriting the
  category's 64×64/`["idle"]` shape like every other `vfx_*` slot. It is
  NOT a `triggers` row — a projectile is a continuous in-flight object, like
  a beam or a lightning bolt, not a one-shot sprite. The same follow-up fixed
  a Fix-1 anchor/offset composition bug (`engine/assets/store.py`'s new
  `offset()` accessor, `game/anchors.py`, `editor/panels/viewport.py`) that
  touches no schema. Since **Phase 9A** the other
  five hold the prototype's live tuning verbatim, restructured into the
  REPLAN nested feature tree (see planning/MIGRATION_PLAN.md): PascalCase
  group objects
  (`EconomyBuildings`, `TheHole`, `EnemyScaling`, …), snake_case leaves,
  tier struct-lists under a `tiers` key with the prototype's field names
  verbatim. The prototype's 4 stringified
  LIGHTNING lists became real JSON arrays; the Features file dissolved into
  one canonical wired flag per concept (`ui:FX/gore_enabled`,
  `ui:FX/bg_art/enabled`, `ui:FX/income_floaters_enabled`,
  `ui:FX/boss_announce/enabled`, `core:TheHole/building_revive`,
  `core:XP/xp_from_buildings`).
- **Enemy sizing leaves (ER-1; per-era for the Boss since BR-1)**: each
  `enemies.json` `EnemyTypes/*` block carries
  a required `footprint` (int tiles, 1–8: the unit occupies footprint² tiles and
  its sprite is downscaled to `footprint*tile_w` wide, never upscaled) and
  `sprite_scale` (number 0.1–8, applied AFTER that fit — the knob for low-res
  art). The dead `Boss/era_sizes` and the `sprite_w`/`sprite_h` on every
  `Boss/stats` row were deleted from content AND schema in the same change:
  nothing read them, and render size now derives from the footprint.
- **`registry_group` (fix-editor-preview-footprint)**: each `EnemyTypes/*`
  block also carries a required `registry_group` string — the
  `data/slots.json` "enemies" group label that type's sprites live under
  (`Standard`->`"Walker"`, `Raider`->`"Raider"`, `SiegeCannon`->`"Siege
  Cannon"`, `Formation`->`"Formation"`, `Boss`->`"Boss"`). It exists so
  `editor/sprite_fit.py`'s pure `slot_draw_fit` resolver can find a preview
  slot's real render `(footprint, sprite_scale)` — the values a `RenderItem`
  needs for the entity preview and its anchor handle to match the game
  (`editor/panels/CLAUDE.md`'s Anchor handles section) — WITHOUT the editor
  importing `game/` (D5). The link previously existed only in
  `game/enemies/enemy.py`'s Python `REGISTRY_GROUP` class constants, and two
  of the five labels do NOT match their `EnemyTypes` key by string
  (`Standard`/`SiegeCannon`), so matching by convention would have violated
  "schemas over convention" — hence a real, required data field instead.
  `game/enemies/enemy.py`'s `REGISTRY_GROUP` constants remain a second,
  UN-refactored home for the same value (deliberate, reported follow-up
  work); `tools/tests/test_enemies.py`'s `TestRegistryGroupDrift` pins the
  two together.
- **Era rows (`enemies.json`, EnemyScalingReworkPLAN ES-2..ES-4)** — the shape
  of enemy difficulty, and the single biggest thing to know before editing this
  file. `EnemyScaling` owns ONE global clock (`rounds_per_era: 10`,
  `boss_round_in_era: 10`) plus its own `eras: [{batch_size, spawn_interval}]`;
  each of `Standard`/`Raider`/`SiegeCannon`/`Formation` owns
  `eras: [{stats:{hp,dmg,move_speed,attack_speed,attack_range_tiles},
  per_round:{hp,dmg,move_speed}, count_start, count_per_round}]`. Every era
  array is `minItems: 1`, **no `maxItems`** — variable length, independent per
  type, and therefore resizable in the editor with no editor code (ER-5).
  - **DELETED keys, do not reintroduce**: `EnemyScaling.base_enemy_count` /
    `enemies_per_round` / `scale_every_n_levels` / `scale_tiers` / the global
    `spawn_interval`; `Boss.round_interval`; and per type `base_count` /
    `per_round` / `rounds_per_cannon` / `rounds_per_formation`. The flat
    `hp`/`dmg`/`move_speed`/`attack_speed`/`attack_range_tiles` left the type
    root — they live in era rows now. `Boss` keeps its own 5-row `stats[]` +
    `round_counts[]` (BossReworkPLAN's territory) — and since **BR-1** its
    `footprint`, `sprite_scale` and `shake` are DELETED from the type root and
    live inside each `stats[]` row, so every boss variable is per-era.
  - **Kept FLAT at the type root, deliberately** (D10, exhaustive):
    `start_round`, `footprint`, `sprite_scale`, `death_spawn`, `registry_group`,
    `kidnapping`, `hunts`, `condition_path_weights`, `mix_ratio`,
    `queue_lead_count`. Only numbers that scale with the round went per-era.
    **BR-1 carved out ONE exception**: the Boss's `footprint`/`sprite_scale`
    are per-era (in its `stats[]` rows), because a designer must be able to
    make the era-4 boss physically bigger than the era-0 one. Every other type
    — and every other key in that list — is unchanged. `editor/sprite_fit.py`
    reads BOTH shapes since **BR-5** (it read only the flat pair before, so
    every boss slot preview silently drew at the render defaults).
  - **`Boss.second_phase` is the SECOND carve-out (BR-5)**: its
    `at_hp_fraction`/`spawn_hp_fraction`/`delayed_spawns`/`spawn_delay` left
    the block root for a 5-row `staging` array (`$defs/second_phase_row`),
    index-aligned with `stats[]`/`round_counts[]`/`spawns[]`, so a designer can
    stage the era-0 boss at half health without touching era 4. They are their
    OWN array rather than extra keys on a `spawns[]` row because that row is
    the SHARED `$defs/spawn_counts` (D7). Unlike the boss's other three arrays
    it is **not** run through `endgame_boss_scaling` — it clamps past era 4;
    compounding a fraction would drive `at_hp_fraction` above 1.0. Shipped
    values: era 0 `0.5`/`0.5` (D5), eras 1–4 `0.0`/`1.0`.
  - **`endgame_scaling` blocks** (per type `{hp, dmg, move_speed, count}`, plus
    `EnemyScaling.endgame_scaling {batch_size, spawn_interval}`) are FACTORS,
    not values: past the last authored era the last row is reused with every
    leaf multiplied by `factor ** N`. **All ship 1.0**, so they are
    behaviour-neutral until a designer tunes them; that is the intended knob for
    "what happens after round 50", replacing the old freeze-forever cliff.
    - **`Boss.endgame_boss_scaling` (BR-4) is the Boss's own version** — one
      block for all THREE of its per-era arrays (`stats[]`, `round_counts[]`,
      `second_phase.spawns[]`), 13 factors, all 1.0. Its KEY NAMES are the LEAF
      names inside those rows (`hp`, `footprint`, `interval`/`strength` for the
      two `shake` leaves, `regular`/`raiders`/`siege`/`commander` for the
      counts) because `era_math.resolve_era_row` matches a factor to a leaf by
      name — renaming a key to something prettier silently disables it.
  - **`count_start` is a `number`, not an integer — and that is load-bearing
    (D3′).** Counts resolve as `floor(count_start + (round − r0) ×
    count_per_round)`, re-anchored at each era's first round. The pre-era
    accretion formulas floored from a type-GLOBAL anchor, so re-anchoring per
    era throws away a fractional remainder: with an integer `count_start` the
    Formation is one short from round 22 onward. The seeded rows therefore carry
    the exact rational value at the era's first round and the resolver floors
    once. A designer authoring a fresh era types a whole number and gets the
    obvious behaviour; fractions appear only in seeded accretion rows.
    - **Write FULL float precision, never a 3-decimal display value.** Era 2/4
      of the Formation are `2.666666666666667` / `9.333333333333334`, not
      `2.667` / `9.333` — the plan's §4 table shows the rounded forms for
      readability and they are WRONG as data: `9.333 + 2 × ⅓` floors to 9 at
      round 43 where the true value gives 10.
    - **Designer nuance (no live effect today, all factors are 1.0):** under a
      non-1.0 `count` endgame factor, an int-authored `count_start` floors twice
      (once in the endgame scaling, once in the count resolve) while a
      float-authored one floors once, so two rows that look equivalent can
      differ by one enemy past the last era. `era_math.count_at_round` is the
      final authority on how many spawn (D3′); if you need an exact endgame
      count, check it there rather than reading the row.
- **`death_spawn` (ER-3)**: each `enemies.json` `EnemyTypes/*` block carries a
  **required** `death_spawn` block — `at_hp_fraction` (number 0–1: the unit dies
  once `hp <= max_hp *` this; `0.0` = the normal die-at-zero rule), `enabled`
  (bool: false = dies normally, spawns nothing), `spawn_hp_fraction` (number
  0–1: children spawn at this fraction of their OWN max HP; `1.0` = full) and
  `spawns` — **always an ARRAY of `$defs/spawn_counts` rows, one per era**,
  resolved `spawns[clamp(era)]`. The Boss carries 5 rows (index-aligned with its
  `stats`); a type with no eras carries a single row and always clamps to row 0,
  which IS the "flat per-type table" case. There is deliberately **no `oneOf`
  union** — a type-less schema node crashes the editor's balancing panel for the
  whole domain. Required-not-optional because `data/` is the only value store (a
  code-side default is banned) and the editor panel skips schema keys absent from
  the doc. `Boss/death_spawns` was REPLACED by `Boss/death_spawn` (the 5 rows
  moved verbatim under `spawns`).
  - **`$defs/spawn_counts` gained a required `commander` key (BR-1/D3)** — the
    `$def` is SHARED by every `death_spawn.spawns` row and by
    `Boss.round_counts`, so all 14 committed rows now carry `commander: 0`.
    The Commander enemy type itself landed in **BR-2** —
    `EnemyTypes.Commander`, a normal era-shaped block (its own `eras[]` rows,
    `endgame_scaling`, flat `footprint`/`sprite_scale`, `registry_group
    "Commander"`, four `commander_stage_*` slots in `slots.json`) shipped
    DORMANT as a *wave* enemy: every era row's `count_start`/`count_per_round`
    is 0, so it never enters a wave. It reaches the board by exactly one route
    — `Boss.second_phase.spawns[0].commander` is 1, the era-0 boss's staged
    child; every other `commander` count is still 0. Widening
    the shared `$def` was chosen deliberately over a boss-only count table,
    overriding the standing argument against it in `game/enemies/CLAUDE.md`.
- **The parity gate is GONE, and balancing values are now free.** The migration
  is complete: `tools/tests/test_balancing_parity.py` and its committed mapping
  table (`balancing_parity_map.json`) are **deleted**, along with the prototype's
  claim on these numbers. Moving, renaming, retuning or dropping a balancing key
  no longer has to be mirrored into a parity map, and no test compares `data/`
  against `../HowToBeHuman`. What still guards you: the schemas (D-*), the
  editor's validating writer, and `tools/tests/test_balancing_data.py`. Tune
  freely — a number that differs from the prototype is a design decision now, not
  a regression.
- **Schema shape (9A)**: tier/struct subschemas live in each schema's
  `$defs`, referenced via **local `#/$defs/` refs only** (plain
  `jsonschema.validate` resolves in-document refs fine; cross-file still
  forbidden). Every object level in all five balancing domains keeps
  `additionalProperties:false` + full `required`, no exceptions (the former
  `era_unlock_round` group-level key was the last one read as optional by
  convention anywhere near buildings — it never actually was schema-optional,
  and it is deleted now that the meditator/beam/wall-builder round gate is a
  single `tiers[0].unlock_min_round`, no separate era key). No `allOf`
  composition (it breaks `additionalProperties:false`).
  `random_names` has `minItems:1` and NO `maxItems` (the 9H add-name menu
  appends). Bounds policy, documented per-domain in the schema description:
  fractions/chances 0–1, HP/DMG (×10) 0–100000, costs/counts 0–10000,
  rounds/levels 0–1000, seconds 0–60, pixels ±4096.
- **D-12 convention**: every property carries a `description` documenting
  units/scale (a test enforces presence), and every numeric property
  declares `minimum`/`maximum` — the editor derives spinbox ranges from
  them, making out-of-range input unrepresentable (ED-30). ×10 combat
  scale is noted in descriptions where it will apply; `core.json`'s
  `base_hp` stays 10, absolute HP — the deliberate NOT-×10 exception.
- Schemas follow the house style: `$id`, draft 2020-12,
  `additionalProperties: false`, all keys `required`, canonical D-3
  formatting (author schemas via `dumps_deterministic`, content via
  `write_validated` — never hand-format).

## Asset data (Phase 5, D-30/31/32 specifics)
- **`slots.json` location is a deliberate D-32 deviation**: SPEC says
  `data/schemas/slots.*`, but `tools/smoke.py` skips `data/schemas/` when
  validating, and the registry must be validated content — so it lives at
  `data/slots.json` with `schemas/slots.schema.json`.
- **`slots.json` shape**: ordered `categories[]` (array — order survives
  D-3 sorted-keys dumps and IS the editor tree order; the first SIX keys
  mirror the D-10 domains — `vfx` was promoted to one by ESV-3a — then the
  asset-only tail `deco`/`conditions`/`backgrounds`/`walls`), each with
  `key/display_name/frame_w/frame_h/animations/groups`. `animations[0]` is
  always `idle` (schema-enforced). `groups` is a recursive tree of
  `{label, slots[] XOR children[]}`; a slot key may repeat across groups of
  ONE category (shared art) but never across categories
  (frame size would be ambiguous — loader rejects it). **No committed group
  shares a key today** — the Meditator line used to point at the Musician's
  `flute_player`/`harp_player`/`trio` slots and was deliberately given its own
  `meditator_`/`shaman_`/`sun_priest_` keys, so the two lines can never drag
  each other's art around again.
- **`slots[]` entries: bare key OR frame-size override (ER-1, D1)**. An entry is
  either a bare key string (inherits the category's `frame_w`/`frame_h`) or
  `{key, frame_w, frame_h}` overriding it for that ONE slot. Bare is the norm; the
  object form exists for art whose sheet is cut at a different size than its
  category — `ui_bg_main_menu` (480×270, a whole-sheet background in the 64×64
  `ui` category) is the one committed user, and without the override the importer
  would grid-slice that one frame into a 7×4 grid. It describes **slicing, not
  drawing** — on-screen size comes from the render fit
  (`engine/render/CLAUDE.md`).
  - **The override DOES propagate to "+ Variant"** (A7): `registry_ops.add_variant`
    now inherits the family stem's frame-size override on creation, so
    `ui_bg_main_menu_v2` inherits the `ui_bg_main_menu` 480×270 override.
    Bare stems stay bare (regression pin for enemies/deco); independently
    resizable afterwards via the Frame W/H spinboxes.
  - **`uniqueItems` no longer implies key uniqueness**: it compares whole values,
    so `"foo"` and `{"key": "foo", …}` are two distinct items. It is kept (it
    still catches literal duplicates, and it is the D-3 house style), and
    `SlotRegistry.__init__` picks up the slack — a key repeated within a category
    must AGREE on its frame size or the loader raises `ValueError`. Schemas for
    what schemas can express; loader cross-checks for what they cannot (the
    `engine/tilemap.py` precedent).
- **`conditions` (Tile Conditions) is an asset-only category** (no
  `balancing/conditions.json`, no `schemas/conditions.schema.json`) holding the
  art for the four runtime tile conditions, restructured so each condition
  type is its OWN top-level group — `Grass`/`Mountain`/`Pond`/`Forest` — and
  WITHIN each, one leaf child per zone STATE — `Buildable`/`Built`/`Combat`/
  `Spawning` — each independently a variant family ("+ Variant" →
  `cond_mountain_buildable_v2`). Slot key convention: `cond_<condition>_
  <state>` (`cond_mountain_buildable`, `cond_mountain_built`,
  `cond_mountain_combat`, `cond_mountain_spawning`, …), 16 slots total. The
  game rolls a condition + a variant index PER TILE once at map load
  (`game/map/CLAUDE.md`'s roll), but the ART slot it resolves to is
  **dynamic**: it re-resolves to the tile's current zone state's family
  (at the SAME stable variant index) every time `TileMap.set_tile_state`
  fires, so e.g. a mountain looks different once built-over. 64×96 like
  buildings/deco, NOT 64×32 like map tiles — a mountain rises above its tile.
  Keys are `cond_*` on purpose: `tile_forest` already belongs to the `map`
  category's backgrounds, and a key in two categories is a load error. Tile
  conditions are **not** in the map file — they roll at runtime — so nothing
  here is paintable; the editor only imports their art. Rendering + the tint
  fallback → `game/map/CLAUDE.md`.
- **`walls` is an asset-only category too** (no `balancing/walls.json`, no
  `schemas/walls.schema.json` — that absence is exactly what keeps it out of
  `editor/domains.py::domains()`), holding the art for the WallBuilder's
  destructible edge walls: one `Wall` group with three variant-family children
  (`Bush Wall`/`Wooden Wall`/`Stone Wall`), 9 slots, `wall_t{1..3}_lvl{1..3}`.
  64×96 like buildings — a wall rises above its tile. Its animation vocabulary
  is NOT a set of animations but a set of SIDES: `["idle", "edge_se",
  "edge_sw", "edge_nw", "edge_ne"]`, one manifest row per isometric tile-diamond
  side (row 0 stays `idle`, schema-forced, and holds a generic preview segment
  for the editor's slot list). `game/map/wall_render.py` owns the neighbour
  delta → side-row table; a frame blits centred on the tile centre, so in a
  64×96 frame the diamond's corners are fixed at top `(32,32)`, right `(64,48)`,
  bottom `(32,64)`, left `(0,48)`. The committed starting art was generated by
  `tools/gen_wall_sheets.py` (deterministic, re-runnable, writes the 9 sheets
  AND their manifest entries) — it is ordinary editable D-31 content, not a
  build artifact: repaint or re-import it freely.
- **Variant families**: a leaf group whose slots are INTERCHANGEABLE art for
  one thing. `enemies` eras (`Walker → Era 2 → [enemy_stage_2,
  enemy_stage_2_v2]`), `deco` prop TYPES (`Props → Rock → [deco_rock,
  deco_rock_v2]`) and `ui` SKINS (`Buttons → Button → [ui_button,
  ui_button_v2]`) are all shaped this way, and the editor's "+ Variant"
  button appends `<stem>_v<k>` to any of them. **This is why every `ui` group is
  a parent with leaf children rather than a flat `slots` list**: a flat leaf makes
  `selection.variant_target()` return `None` and `registry_ops.add_variant()`
  raise — "+ Variant" silently dies. `map → Tiles → Background` is NOT a
  variant family: every background slot needs its own map-file legend code, so
  "another background variant" is just another numbered `tile_background_<n>`
  type. Deco types are added as whole leaf subgroups (`Prop <n>` holding
  `deco_prop_<n>`), never appended to a flat list.
- **Frame sizes (SPEC §9.1 resolved)**: buildings / enemies / deco / core
  64×96; map tiles 64×32; ui / vfx 64×64 (except `ui_bg_main_menu`, 480×270 by
  per-slot override); backgrounds 480×270 (10K full-frame menu art, drawn as a
  screen-space `HudSprite` — not a world sprite). All data — edit `slots.json`.
- **`ui` animation vocabulary is the four button states** (10L-A):
  `["idle", "hover", "pressed", "disabled"]` — one sheet per widget skin, one
  manifest ROW per state (row 0 = idle, schema-enforced as everywhere), and each
  state row may itself be multi-frame. A missing row falls back to idle, so a
  partial sheet is fine.
- **`sprites/asset_manifest.json` (manifest v2, D-30)**:
  `{version: 2, entries: {slot: {sheet: "imported/<slot>.png", frame_w,
  frame_h, offset_x, offset_y, rows[]}}}` with row =
  `{animation, frames, fps, hidden[], loop_start, loop_end, loop_count}`;
  `rows[0].animation` is schema-forced to `idle` (`prefixItems`). Written ONLY
  by the editor's import panel, through `write_validated`. (The one-shot
  migration tool that seeded it is deleted — the editor is the only door now.)
  - **`slice` (A2) and `anchors` (ESV-1) are the two OPTIONAL per-entry keys** —
    everything else is `required`. `"slice": [left, top, right, bottom]`, ints
    0..1024, nine-slice margins in FRAME pixels (same convention as
    `offset_x`/`offset_y`). It exists so a UI panel/button skin can be drawn at
    any size with its corners intact: corners blit 1:1, edges stretch on one
    axis, the centre on both. **HUD sprites only** — world sprites ignore it and
    keep uniform zoom scaling. Omit it for plain scaling; no committed entry
    carries one yet. The geometry lives in `engine/render/backend.py` (see
    `engine/render/CLAUDE.md`). `"anchors": {muzzle?, impact?, hp_bar?,
    floater_origin?, status_icon?, beam_endpoint?}` — six declared named
    `[x, y]` frame-px handle points, all optional, same coordinate convention.
    Unlike `slice` they are pure metadata (never affect slicing/blitting); see
    `engine/assets/CLAUDE.md`. No committed entry carries one yet.
  - **`slice` (A2) and `tint_overlay` are the OPTIONAL per-entry keys** —
    everything else is `required`. `tint_overlay` (bool) is a render hint the
    engine carries uninterpreted: "keep drawing the consumer's own flat colour
    overlay under this art". Read only by the game's tile-condition art; omit
    it for sprite-only (omitted ⇒ `False` ⇒ byte-identical entry), and note a
    condition slot with NO entry always draws the overlay since there is no
    sprite. Authored by the Details panel's checkbox, `conditions` category
    only. `"slice": [left, top, right, bottom]`, ints 0..1024, nine-slice
    margins in FRAME pixels (same convention as `offset_x`/`offset_y`). It exists
    so a UI panel/button skin can be drawn at any size with its corners intact:
    corners blit 1:1, edges stretch on one axis, the centre on both. **HUD sprites
    only** — world sprites ignore it and keep uniform zoom scaling. Omit it for
    plain scaling; no committed entry carries one yet. The geometry lives in
    `engine/render/backend.py` (see `engine/render/CLAUDE.md`).
- **`sprites/imported/*.png` are committed content (D-31)**, copied there at
  import time by the editor (historically also by the migration tool, now gone).
  Never gitignore them.
- **A sheet may be SHARED — `sheet` is a path, not a slot-derived name.** The
  engine resolves `sprites_dir / entry.sheet` verbatim
  (`engine/assets/store.py`), and the schema's pattern always allowed any
  `imported/*.png`. The editor's **"Use Spritesheet…"** uses that: it points a
  slot's entry at ANOTHER slot's PNG and copies no bytes, so one file backs many
  slots (a variant reusing its parent's art, two props sharing a sheet).
  `imported/<slot>.png` is therefore only (a) the file a slot's own *file* import
  owns and (b) the fallback for a slot with no entry — **never re-derive it as
  "the slot's sheet"; read the entry's `sheet`.**
  - **Deleting art must refcount.** `editor/asset_import.py`'s `sheet_users` /
    `unreferenced_sheets` are the one authority: a PNG is unlinked only when no
    remaining entry points at it. Clearing one slot of a shared sheet keeps the
    file for the others; the last user takes it with them. Unlinking
    `imported/<slot>.png` blind would blank every slot linked to it.
  - **Orphans are legal and deliberate.** Re-linking a slot away from art only it
    used leaves that PNG on disk, unreferenced and inert. It stays listed in the
    picker, which is how you get it back — silently deleting art on a link change
    is the worse failure.

## UI screen data (Phase 10L-B, R3; wave-3 population Phase 3)
- **`data/ui/screens/<screen_id>.json`**: per-screen override format. One file
  per screen — the original 12 (main_menu, pause, settings, credits, add_name,
  game_over, levelup, hud, building_panel, cheat_menu, game_log,
  boss_cutscene) plus Phase 3's `overlays` (the map-overlay RANGE/HEATMAP
  toggle pills, added the sanctioned "drop in a file + ids" way — a NEW
  screen id beyond the original 12, per `game/ui/CLAUDE.md`'s customization
  section). Every file started life EMPTY `{}`; Phase 3 populated 11 of the
  13 with real `skin`/`defaults` content wiring the baked `ui_button`/
  `ui_panel`/`ui_panel_stone` assets in (`game_log.json` stays `{}` — R3's
  "container styling only, never position log lines" contract).
- **Wave-3 Fix 2 (USER DECISION): one slot PER BUTTON TYPE, not one shared
  `ui_button`.** `slots.json`'s `ui` → Buttons group carries 8 leaf children
  (each its own PNG via `tools/bake_ui_sheets.py`, no shared `sheet` path
  between them, all `[4,4,4,4]`-sliced) wired as: `ui_button` (shell menus —
  main_menu/pause/settings/credits/add_name/game_over, unchanged) ·
  `ui_button_end_turn` → hud.json `btn_end_turn` · `ui_button_pause` →
  hud.json `btn_pause` · `ui_button_panel` → building_panel.json's id'd
  buttons (action/boss/close/preview_*/rename_dice/boss_close — `lightning`
  was removed by the Storm Priest rework, which deleted the base_info
  lightning section/button entirely) ·
  `ui_button_card` → building_panel.json `defaults.button_skin` (construct/
  upgrade cards) · `ui_button_cheat` → cheat_menu.json `btn_*` · `ui_button_
  pill` → overlays.json `btn_range`/`btn_heatmap` · `ui_choice_box` → levelup.
  json `defaults.panel_skin` and boss_cutscene.json `box_a`/`box_b` (baking
  the same idle+hover stone look as `ui_panel_stone`, which stays registered
  and baked separately as a panel style).
  `background: {slot} | {color}` sets the background (slot key OR RGB[A]);
  `defaults: {button_skin?, panel_skin?, font?, text_color?}` applies per-kind
  styling to DYNAMIC-count content that carries no id (construct cards, the
  boss-history popup, levelup's option boxes — `ScreenSkinning.defaults()`);
  `widgets: {<id>: {rect?, skin?, font?, color?, text_color?, label?,
  visible?}}` overrides any named widget's properties.
- **`data/ui/screen_defaults.json`**: generated-but-committed file, written by
  `tools/export_ui_layouts.py` (B3) and validated by a test that re-runs the
  exporter (B3). FLAT shape, keyed directly by screen id at the root:
  `{<screen_id>: {widgets: {<id>: {rect, kind, label}}, mock_note}}`, where
  `kind` is one of `button | panel | label | backdrop | bar | field`. Pairs
  with `schemas/screen_defaults.schema.json` by normal stem pairing — no
  directory exception needed for this one file. Editor previews render from
  defaults + overrides only. Merge conflicts on two branches resolve by
  re-running the exporter (deterministic output).
- **SCHEMA-PAIRING EXCEPTION (the directory rule — now THREE + ONE)**:
  `data/ui/screens/*.json` (any stem, the screen id) → `ui_screen.schema.json`
  (exact parallel to `data/maps/*.json` → `map_file.schema.json`).
  `tools/smoke.py::validate_data` special-cases the directory exactly like
  maps. `data/ui/screen_defaults.json` pairs normally via stem to
  `schemas/screen_defaults.schema.json` (a plain stem-mate, not a directory
  exception — its schema's root is the flat per-screen map, not a `screens`
  wrapper).
- **`ui` animation vocabulary** (`slots.json` A3): `["idle", "hover",
  "pressed", "disabled"]` — button states become manifest rows (plan decision
  2, landed A3). Widget skins source the `ui` slots; per-slot animation
  vocabulary + partial-sheet fallback apply uniformly.

## Theme data (UH-6, D5/D6)
- **`data/ui/fonts.json`** ↔ `schemas/fonts.schema.json` (normal stem
  pairing, no directory exception): exactly the 7 keys
  `engine/render/fonts.py`'s `_FONT_SPECS` ships (`sm/md/lg/xl/xxl/hud_phase/
  hud_lvl`), each `{"size": int 4-72, "bold": bool}`, all required
  (`additionalProperties: false` — a designer cannot invent a new preset key
  through this schema; adding one is a schema change). The game loads +
  validates it at boot (`game/main.py`, before the `Shell`/screens are
  built) and calls `engine.render.fonts.configure_fonts(doc)`; a missing/
  invalid file fails LOUD (D-2 — this is data, not art; E-37 does not
  apply). The editor's Theme panel (`editor/panels/game_theme.py`) is the
  only writer, through `write_validated`, staged like `balancing.py`.
  `configure_fonts` never moves `layout_h`/`_LAYOUT_H` (`engine/render/
  CLAUDE.md`) — font size is drawn-glyph-only, not stored layout.
- **`data/ui/palette.json`** ↔ `schemas/palette.schema.json` (same normal
  pairing): one key per `game/ui/widgets.py` `C_*` constant, snake_case with
  the `C_` prefix dropped (`gold`, `ui_panel`, `panel_stone`, …), each an RGB
  3-int array 0-255, all required. The game loads + validates it at boot and
  calls `widgets.configure_palette(doc)`, which rebinds every `C_*` module
  attribute (mechanical `"C_" + key.upper()`). This IS the whole `C_*`
  block — `widgets.cond_label`'s COLOR half and every other inline color
  literal in `game/ui` stay code, deliberately out of scope (its LABEL TEXT
  half moved to `strings.json` below, Phase C).
- **Parity is the safety net for both files**: the committed content is
  today's hardcoded values verbatim, and `tools/tests/test_theme_data.py`
  pins that (a) configuring from the stock fixture doc reproduces
  `test_ui_skinning.py`'s golden baseline byte-for-byte, and (b) the
  UNCONFIGURED module defaults (the fallback bare construction uses) equal
  that same fixture — the two value sets can never silently drift apart.
- **`data/ui/strings.json`** ↔ `schemas/strings.schema.json` (normal stem
  pairing): a FLAT `{string_id: template}` map, one dotted id per source
  module/call-site (`hud.phase.building`, `hud.income.base`,
  `widgets.condition.grass`, `levelup.heading`, `boss_cutscene.headline_win`,
  …), `additionalProperties: false` with every key `required` — the same
  closed-set convention as `fonts.json`/`palette.json` (a designer cannot
  invent a new id through this schema; adding one is a schema change).
  Covers UI text that Phase B's per-widget `label` override
  (`ui_screen.schema.json`) structurally cannot: text that varies by
  runtime/enum state (a phase banner, a win/loss headline) or is BUILT FROM
  A TEMPLATE with live values (`"LIVES {count}"`, `"ROUND {n}"`) — there is
  no single fixed string to attach to a widget id for those. Templates use
  Python `str.format()` placeholders; each property's `description`
  documents which keyword(s) its call site passes. The game loads +
  validates it at boot (`game/main.py`, alongside `fonts.json`/
  `palette.json`) and calls `game.ui.strings.configure_strings(doc)`, which
  rebinds the module's string table in place; every call site resolves text
  via `game.ui.strings.T(string_id, **kwargs)` — never a raw f-string. A
  missing/invalid file fails LOUD (D-2 — boot config data, not art; E-37
  does not apply). The editor's Strings panel (`editor/panels/
  strings_panel.py`) is the only writer, through `write_validated`, staged
  like `fonts.json`/`palette.json`. **No separate editor-side consumer to
  reconfigure** (`game/ui/strings` is game-only, off limits to the editor,
  same as `palette.json`'s case above) — the game re-reads `strings.json`
  at its own next boot.
- **`ui_screen.schema.json` widget `tint` (D6)**: one new key in the
  per-widget override object, same 3-4-int-array shape as `color` — like
  every other widget override key (`rect`/`skin`/`font`/`label`/`color`/
  `text_color`/`visible`), it is absent-by-default (the object carries no
  `required` array: a widget's override is always a PARTIAL patch, never a
  full record). A skinned widget's `tint` multiplies its sheet at draw time
  (`engine/render/CLAUDE.md`'s nine-slice/`BLEND_RGBA_MULT` section);
  omitted = unchanged, so an existing screen doc that predates `tint` keeps
  validating and rendering exactly as before.
- **`data/fonts/font_manifest.json`** ↔ `schemas/font_manifest.schema.json`
  (UH-Font-A, normal stem pairing): `{"version": 1, "entries": {<font_id>:
  {"file": "imported/<font_id>.<ttf|otf>", "display_name": "..."}}}` — every
  custom font a designer has imported through the editor's Theme panel,
  ORTHOGONAL to `data/ui/fonts.json`'s 7-preset size/bold system above
  (completely untouched by this feature). `data/fonts/imported/*.ttf`/
  `*.otf` are committed content (mirrors `data/sprites/imported/*.png`'s
  D-31 precedent), written ONLY by `editor.font_import.import_font_file`
  through `write_validated`.
- **`data/ui/active_font.json`** ↔ `schemas/active_font.schema.json` (normal
  stem pairing): `{"font_id": "default" | <font_manifest entry id>}` — the
  single pointer to the game-wide custom font family. `"default"` means
  today's `pygame.font.SysFont("monospace", ...)` behavior; any other value
  must match an entry in `font_manifest.json` — a cross-file check the
  schema can't express, so `game/main.py`'s boot loader cross-checks it
  (entry exists AND its file exists on disk) and fails LOUD (D-2, the
  `engine.tilemap.load_map` precedent) rather than degrading. The editor's
  Theme panel is the only writer (staged like `fonts.json`/`palette.json`);
  its own resolution (`editor.theme_ops.resolve_active_font_path`) degrades
  to `None` instead of raising (editor-side E-37 grace). Loaded once at boot
  and passed to `engine.render.fonts.configure_fonts`'s `font_path=` kwarg
  — `None` for `"default"`, an absolute path otherwise; every `font_key`
  then builds via `pygame.font.Font(font_path, size)` instead of
  `SysFont`. `layout_h`/`_LAYOUT_H` are unaffected either way (same
  invariant as a plain size change above).

## Map data (Phase 6, D-20/21/22 specifics)
- **`maps/<id>.json` (map files)**: `id` (== filename stem, loader-enforced),
  `display_name`, `cols`/`rows` (each map owns its dims, 4..1024; geometry.json
  keeps only tile pitch + zoom levels as global truth — large maps stay
  performant via windowed tile culling, see engine `visible_render_items`),
  `terrain` (rows strings of
  cols single-char codes — one line per row keeps diffs cheap), `legend`
  (schema-pinned char→{slot, checker} table: b/c/s = buildable/combat/
  spawning with checkerboard `_b` alternation, f/l/o = forest/cliff/ocean
  background, no alternation — the file is self-describing, no package
  hardcodes tile vocabulary), `base` ({col,row,slot} — slot const-pinned to
  `base_hole`), `camera_start` (nullable {col,row,slot}), `start_area`
  (nullable {col,row,slot} — slot const-pinned to `start_area`; {col,row} is
  the 2×2 starting area's MIN corner, spans col..col+1 × row..row+1, loader
  cross-checks col+1 < cols / row+1 < rows; anchors the game's tile-unlock
  section grid, never forces tile states, drawn by the editor as an outline
  only; existing maps were migrated to `"start_area": null`), `deco` (world
  positions; renders ABOVE entities, E-26). Spawning is a painted zone — the
  format has NO spawn-point objects (`spawnable_background` below schedules
  when a cell BECOMES that zone; it is still not a spawn point).
  `tutorial_flute`/`tutorial_stone`
  (nullable {col,row,slot}, same shape as `camera_start`; slots const-pinned
  to `"tutorial_flute"`/`"tutorial_stone"`, TU-1, planning/TutorialPLAN.md D1)
  are the tutorial's designer-painted forced-first-placement tiles — never
  rendered by the game or the editor's normal render pipeline; existing maps
  were migrated to `"tutorial_flute": null, "tutorial_stone": null`.
- **`spawnable_background` — the designer-authored spawn reserve.** A list of
  `{col, row, stage}` marks (`stage` 1..1000 = the designer STAGE at which that
  cell flips BACKGROUND → SPAWNING; every mark numbered n releases together,
  once). **The field was called `purchase` until stage zones landed** — it is a
  stage number, never a purchase count, and only `stage_zones` below advances
  the stage. It is an **invisible OVERLAY, not a legend tile code**: the
  painted forest/cliff/ocean underneath keeps drawing, and like
  `start_area`/`tutorial_*` it is deliberately NOT emitted by any render
  emitter, so the game never draws it. **On disk a list sorted by (row, col)**
  (D-3 determinism); **in memory a dict `{(col, row): stage}`** on
  `TileMapDoc` — the editor paints O(1) per cell, which the list form cannot.
  `engine.tilemap.validate_doc` bounds-checks every mark (D-2, the `deco`
  check's twin); `stage >= 1` is the schema's job. An empty array is legal
  and is the "no reserve painted" state — existing maps were migrated to
  `"spawnable_background": []`. Runtime precedence → `game/map/CLAUDE.md`;
  the brush → `editor/panels/CLAUDE.md`.
- **`despawnable_spawn` — the designer-authored despawn schedule.** The exact
  sibling of `spawnable_background` above, same shape (`{col, row, stage}`
  marks, `stage` 1..1000), same invisibility (no render emitter touches it),
  same on-disk list sorted by (row, col) / in-memory
  `{(col, row): stage}` dict on `TileMapDoc`, same `validate_doc`
  bounds check. It is painted on SPAWNING tiles and every mark numbered n flips
  its tile SPAWNING → COMBAT when the run's stage counter reaches n. An empty
  array is the "no despawn schedule painted" state — existing maps were migrated
  to `"despawnable_spawn": []`. Runtime precedence (including the
  retire-the-reserve stage that runs once the stage has spent BOTH mark sets) →
  `game/map/CLAUDE.md`.
- **`stage_zones` — the designer-authored STAGE counter, and the ONLY thing
  that advances it.** The THIRD overlay of the same shape (`{col, row, stage}`
  marks, `stage` 1..1000; same invisibility, same (row, col)-sorted list on
  disk / `{(col, row): stage}` dict in memory, same `validate_doc` bounds
  check) — painted on COMBAT tiles. Buying a 2×2 whose four tiles intersect the
  painted set takes the MAXIMUM stage under those four tiles; if it exceeds the
  run's current stage (which starts at 0 and never decreases) the stage advances
  to it, and every release/despawn batch the jump passed over fires in ascending
  order. Buying anywhere unpainted never advances the stage — **`n` is a
  designer stage, not a purchase count, which is why the two sibling overlays'
  `purchase` field was renamed `stage` in the same change.** An empty array is
  the "no stage zones painted" state (the stage stays 0 forever, and with no
  marks of any of the three kinds the runtime's implicit recede behaves exactly
  as it did before this feature) — existing maps were migrated to
  `"stage_zones": []`. Runtime precedence → `game/map/CLAUDE.md`.
- **`tile_conditions` — the designer-painted TILE-CONDITION overrides.** The
  FOURTH overlay of the same shape, and the first whose value is a NAME rather
  than a stage number: `{col, row, condition}` marks, `condition` an **enum of
  `grass`/`mountain`/`pond`/`forest`**. Same invisibility (no render emitter
  touches it — the game's own condition-ART emitter draws conditions off the
  runtime `Tile`, never off this field), same (row, col)-sorted list on disk /
  `{(col, row): "pond"}` dict in memory on `TileMapDoc`, same `validate_doc`
  bounds check. **That enum is the SINGLE source of the four names** — the game
  maps it through `tiles.py`'s `CONDITION_BY_MAP_KEY`, the editor reads it
  through `engine.tilemap.condition_codes_from_schema`, and neither hardcodes
  the list. A marked cell takes that condition and is **excluded from the
  runtime's random condition roll**; a mark wins everywhere, including
  BACKGROUND tiles and the starting unlocked pocket, which the roll itself
  skips. An empty array is the "nothing painted, the whole map rolls" state —
  existing maps were migrated to `"tile_conditions": []`. Runtime precedence →
  `game/map/CLAUDE.md`; the brush → `editor/panels/CLAUDE.md`.
- **`balancing/map.json` `TileUnlocking.spawn_recede_enabled`** (bool, default
  `true`) is the master switch for the OLD implicit recede rule only — `false`
  and the band never recedes on unlock, whatever the reserve state. It does not
  gate the reserve.
- **SCHEMA-PAIRING EXCEPTIONS (the directory rule — there are THREE)**: the
  default is stem pairing (`data/foo.json` ↔ `schemas/foo.schema.json`, missing
  schema fails loud). `tools/smoke.py::validate_data` implements + tests exactly
  three directory exceptions: (1) every `data/maps/*.json` EXCEPT
  `active_map.json` → `schemas/map_file.schema.json` (`active_map.json` keeps
  normal stem pairing via `active_map.schema.json`; the stem `map` still belongs
  to the BALANCING domain, `balancing/map.json`); (2) every
  `data/balancing_history/*.json` → `schemas/balancing_history.schema.json`;
  (3) every `data/agent_forms/*.json` → `schemas/agent_form.schema.json`.
  Adding a fourth means editing that `if/elif` chain and pinning it in a test.
- Dimension consistency (terrain row count/lengths, base/deco in bounds)
  is beyond JSON Schema → `engine.tilemap.load_map` cross-checks and fails
  LOUD (D-2). Read/write map files ONLY through `engine.tilemap`.
- **`maps/active_map.json` (D-21)**: `{"active": "<map_id>"}` — written
  ONLY by the editor's Set Active action (and tests). The game follows it
  at boot and fails loud if missing/invalid (art tolerance E-37 does not
  apply to map data).
- `maps/first_light.json` is the committed starter map (prototype-exact
  initial layout) so the game always boots on real data.

## Tutorial + cutscenes data (Phase TU-1, D3/D4)
- **`data/tutorial/tutorial.json` ↔ `schemas/tutorial.schema.json`**: normal
  stem pairing (the file's stem `tutorial` already equals its schema's stem,
  so no `tools/smoke.py` directory exception was needed — the plain `else:
  schema = schema_dir / f"{path.stem}.schema.json"` branch already resolves
  it). Root keys: `skippable`/`first_loss_costs_life` (bools, the script's
  behavioral toggles), `messages` (a **closed** 3-key object,
  `economy_intro`/`lives_intro`/`close_panel_hint` — TU-8 added the third,
  all required strings — the two message-box texts verbatim from the
  designer brief plus the flute chain's non-modal close-panel banner text),
  `steps` (array, `minItems:1`; each step is `additionalProperties:false` —
  `id`, `message` (nullable string id into `messages`), `highlight` (array
  of opaque string ids), `advance_on` (string event id), `allow` (array of
  allowed input action ids), `flags` (object, `additionalProperties:true` —
  the ONE deliberately open leaf, so later phases attach per-step data with
  no schema bump), `revert_on`/`revert_to` (TU-8, both nullable strings —
  the backward mirror of `advance_on`/a target step `id`; `revert_to` naming
  a step absent from `steps` is a safe engine-side no-op, not a schema
  violation, since the schema can't express "must be one of the other
  steps' ids" without a doc-wide cross-check)). TU-1 seeds only the round-1
  step list (flute-player placement chain); TU-6/TU-7 append round-2 steps,
  TU-8 adds the revert-flow fields (every existing step now carries an
  explicit `null`/`null` pair) plus one new close-panel-hint step, all under
  this same schema. Read only by `engine/tutorial.py`'s generic
  step-sequencer (TU-6+) — the engine knows nothing of flutes or holes; the
  game-side director binds the opaque ids to real things.
- **`data/video/cutscenes.json` ↔ `schemas/cutscenes.schema.json`**: same
  normal stem pairing (no directory exception). An open registry keyed by
  cutscene id (`additionalProperties: {$ref: #/$defs/entry}`), each entry
  `{video, audio (nullable), length, trigger}`. `trigger` is a closed enum
  today (`intro`/`first_end_turn`) — a new trigger point is a schema bump.
  TU-1 seeds `intro` (mirroring, but not yet migrating, `game/main.py`'s
  still-hardcoded `data/video/cutscene.mp4` + `ui.json`'s
  `Menu.cutscene_length` — that migration is TU-5's job) and
  `first_end_turn` (new, fires in `session.end_turn()` on round 1 before
  `spawner.begin_round()`, wired by TU-5+).
- **`data/balancing/core.json`'s `Tutorial` group** (alphabetically between
  `TheHole` and `XP`): one leaf, `economy_buildings_required` (integer,
  minimum 1) — the number of economy buildings the player must place before
  the tutorial's first End Turn / first-end-turn cutscene. Behavioral
  toggles (`skippable`, `first_loss_costs_life`) live in the tutorial script
  above, not here — the editor's Tutorial section owns those.
- **`data/slots.json`'s `core` category gained two new one-slot groups**,
  `"Tutorial Flute"` (`tutorial_flute`) and `"Tutorial Stone"`
  (`tutorial_stone`), same shape as `"Start Area"`. Neither is a real sprite
  — the marker is drawn as an outline — the group exists solely so the
  editor's palette brush buttons (TU-2) have a slot key to arm.

## Rules
- **JSON here is the ONLY value store** (D-1). Never move a value into Python;
  never reintroduce the prototype's py+json dual system.
- **Schema first:** adding a key = update the schema in the same change, then
  the content file. All writes validate (D-2); the game fails loud in dev on
  invalid data.
- Deterministic formatting: sorted keys, 2-space indent (D-3) — keeps diffs
  minimal for git and agents.
- Designers never hand-edit these files (the editor is their interface); you
  (an agent) may edit directly, but only schema-valid writes, and only with
  the user's say-so or a dispatched task's scope.
- Balance semantics: ×10 combat HP/DMG scale; `BASE_HP` stays 10; units and
  scale are documented per key in the schema (D-12).
- `active_map.json` changes only via the editor's selector (D-21) unless the
  user explicitly asks.

## Verify before finishing
Validate every touched file against its schema, then:
```bash
py tools/smoke.py
py tools/testgate.py check     # the gate is ZERO failures
```
Report agreement explicitly.

**`data/` is live designer content, and the tests must never touch it.** Tests
copy it to a tempdir (`TempDataCase`); a session fixture hashes `data/` before
and after the suite and fails the run if a single byte changed. This is not
theoretical — the suite used to paint tiles into real maps and invent map files,
silently, for months (`tools/data_guard.py`).

The corollary binds tests too: **never assert against live `data/` content.** Pin
the fixture instead. "The Painter slot has no art" and "first_light is the active
map" were both true when written and both false later — that is what put 18 tests
permanently in the red.
