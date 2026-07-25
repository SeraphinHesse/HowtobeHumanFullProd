# Phase ESV-3a — Procedural VFX emitters → `engine/vfx/`, params → `data/balancing/vfx.json`

Source plan: `planning/EntitySceneVfxPLAN.md` §ESV-3 (`:198-210`). ESV-3 was split
by file ownership after the user widened its scope; **ESV-3a owns the particle /
gold / splatter / slash / floater-style effects. ESV-3b (later) takes the
scene-object effects (craters, beams, lightning, boss announce).**

**Open with these skills, do not hand-roll:** `/add-engine-component` for the
emitter/system components under `engine/vfx/`, and `/add-category` +
`/add-balancing-value` for the new `vfx` balancing domain.

**Landing condition: byte-identical.** Today's constants become the shipped
JSON defaults. Nothing changes on screen. Any pixel difference is a bug in this
phase, not a design choice.

---

## 1. Behavioral spec

### 1.1 Where the behaviour lives today

`game/ui/effects.py` is the single VFX hub (**verified**). Module constants sit
at `:33-103`; `FloaterManager` at `:216-732` holds all state (`_floaters`,
`_particles`, `_gold`, `_slashes`, `_splatters`, `_announce_age`,
`:228-241`); `update(dt)` at `:402-422` ages every list; the submit functions are
called from `game/main.py:764-778` (**verified**). The manager is constructed at
`game/main.py:263` as `FloaterManager(ui_balance, core_balance)` (**verified**).

Helper classes to be moved or mirrored: `_Particle` `:145-174` (world anchor +
base-zoom pixel offset, `step(dt)` integrates gravity, `color()` indexes the ramp
by age fraction), `_GoldHighlight` `:177-194` (in/hold/out `frac()`), `_Slash`
`:197-213` (2-3 diagonal lines built once at construction).

### 1.2 Effects ESV-3a ports

| Effect | Today (site) |
|---|---|
| Spark burst ×4 presets | `spawn_building_vfx` `:286-299`, `_SPARK_PRESETS` `:76-84` |
| Building death burst | `watch_buildings` `:318-323`, `_DEATH_*` `:89-92` |
| Muzzle spray (std + siege-strong) | `watch_enemies` `:359-368`, `_MUZZLE_*` `:93-96` |
| Melee slash | `_Slash.__init__` `:203-213`, `_SLASH_*` `:97-98` |
| Gold tile highlight | `_GoldHighlight` `:177-194` + `submit_gold_highlights` `:456-467` |
| Blood splatter | `submit_splatters` `:442-454`, `_SPLATTER_*` `:99-100` |
| Floater colour/lifetime params | `:33-41`, used `:248/:260/:268-270/:281` |

### 1.3 The complete tunable table

Every row: today's value (**verified**, cited) → its key under
`procedural` in `data/balancing/vfx.json`. The JSON default MUST equal the
"today" column exactly.

#### `procedural.spark` — spark bursts (`effects.py:76-84`, `:292-297`)

| Today | Value | JSON key |
|---|---|---|
| `_SPARK_PRESETS["place"]` `:78` | life `0.75`, count `10` | `spark.presets.place.{life,count}` |
| `_SPARK_PRESETS["level1"]` `:79` | `0.55`, `7` | `spark.presets.level1.{life,count}` |
| `_SPARK_PRESETS["level2"]` `:80` | `0.88`, `16` | `spark.presets.level2.{life,count}` |
| `_SPARK_PRESETS["tier"]` `:81` | `1.20`, `26` | `spark.presets.tier.{life,count}` |
| `_SPARK_GRAVITY` `:82` | `55.0` | `spark.gravity` |
| `_SPARK_RAMP` `:83-84` | `[[255,230,80],[255,150,40],[210,60,30]]` | `spark.ramp` |
| inline `random.uniform(-28, 28)` `:295` | `-28.0` / `28.0` | `spark.vx_min` / `spark.vx_max` |
| inline `random.uniform(-70, -20)` `:295` | `-70.0` / `-20.0` | `spark.vy_min` / `spark.vy_max` |
| inline `size=(2, 2)` `:297` | `2` / `2` | `spark.size_w` / `spark.size_h` |

#### `procedural.death_burst` — building death (`:89-92`, `:318-323`)

| Today | Value | JSON key |
|---|---|---|
| `_DEATH_LIFE` `:89` | `0.65` | `death_burst.life` |
| `_DEATH_COUNT` `:90` | `14` | `death_burst.count` |
| `_DEATH_GRAVITY` `:91` | `60.0` | `death_burst.gravity` |
| `_DEATH_COLORS` `:92` | `[[150,90,200],[120,70,170],[180,120,230]]` | `death_burst.colors` |
| inline `uniform(-45, 45)` `:320` | `-45.0` / `45.0` | `death_burst.vx_min` / `vx_max` |
| inline `uniform(-80, -10)` `:320` | `-80.0` / `-10.0` | `death_burst.vy_min` / `vy_max` |
| inline `randint(2, 4)` `:323` | `2` / `4` | `death_burst.size_w_min` / `size_w_max` |
| inline `randint(2, 5)` `:323` | `2` / `5` | `death_burst.size_h_min` / `size_h_max` |

**Note the shape difference (load-bearing):** a death shard's ramp is a
**1-tuple** — `(random.choice(_DEATH_COLORS),)` `:322` — i.e. one colour picked
per particle and held for its whole life, NOT a 3-stop age ramp like the spark.
Reproduce that exactly, including the RNG draw order (see §2.4).

#### `procedural.muzzle` — muzzle spray (`:93-96`, `:359-368`)

| Today | Value | JSON key |
|---|---|---|
| `_MUZZLE_LIFE` `:93` | `0.20` | `muzzle.life` |
| `_MUZZLE_LIFE_STRONG` `:93` | `0.32` | `muzzle.life_strong` |
| `_MUZZLE_COUNT` `:94` | `8` | `muzzle.count` |
| `_MUZZLE_COUNT_STRONG` `:94` | `13` | `muzzle.count_strong` |
| `_MUZZLE_RAMP` `:95` | `[[255,230,120],[220,90,50],[130,30,20]]` | `muzzle.ramp` |
| `_MUZZLE_SMOKE` `:96` | `[100,80,80]` | `muzzle.smoke_color` |
| inline `random.random() < 0.25` `:362` | `0.25` | `muzzle.smoke_chance` |
| inline `uniform(-90, -30)` `:367` | `-90.0` / `-30.0` | `muzzle.vx_min` / `vx_max` |
| inline `uniform(-35, 35)` `:368` | `-35.0` / `35.0` | `muzzle.vy_min` / `vy_max` |
| implicit gravity `0.0` `:368` | `0.0` | `muzzle.gravity` |
| implicit `size` default `(2, 2)` `:153` | `2` / `2` | `muzzle.size_w` / `size_h` |

Smoke particles get a **1-tuple** ramp `(_MUZZLE_SMOKE,)` `:362`; non-smoke get
the 3-stop `_MUZZLE_RAMP`. The `random.random()` smoke roll happens **before**
the two `uniform` velocity draws, per particle (`:362-368`) — preserve order.

#### `procedural.slash` — melee slash (`:97-98`, `:203-213`)

| Today | Value | JSON key |
|---|---|---|
| `_SLASH_LIFE` `:97` | `0.28` | `slash.life` |
| `_SLASH_COLORS` `:98` | `[[220,230,255],[200,215,245],[255,255,255]]` | `slash.colors` |
| inline `randint(2, 3)` `:209` | `2` / `3` | `slash.lines_min` / `lines_max` |
| inline `uniform(-6, 6)` `:210` | `-6.0` / `6.0` | `slash.ox_min` / `ox_max` |
| inline `uniform(-10, 2)` `:211` | `-10.0` / `2.0` | `slash.oy_min` / `oy_max` |
| inline `11 if large else 7` `:207` | `11` / `7` | `slash.size_large` / `slash.size` |

Per line the draw order is `ox`, `oy`, `rng.choice(colors)` (`:210-213`).

#### `procedural.gold_highlight` — tile highlight (`:85-88`, `:456-467`)

| Today | Value | JSON key |
|---|---|---|
| `_GOLD_LIFE` `:85` | `1.20` | `gold_highlight.life` |
| `_GOLD_IN` `:86` | `0.15` | `gold_highlight.fade_in` |
| `_GOLD_HOLD` `:86` | `0.35` | `gold_highlight.hold` |
| `_GOLD_FILL` `:87` | `[255,215,0]` | `gold_highlight.fill_color` |
| `_GOLD_BORDER` `:88` | `[255,240,80]` | `gold_highlight.border_color` |
| inline `int(90 * frac)` `:464` | `90` | `gold_highlight.fill_alpha` |
| inline `width=2` `:467` | `2` | `gold_highlight.border_width` |

Fade-out is DERIVED: `life - fade_in - hold` (`:193`). Do NOT add an
`fade_out` key — it would let the three drift out of sum. Keep the derivation
and say so in the schema `description`.

#### `procedural.splatter` — blood (`:99-100`, `:442-454`)

| Today | Value | JSON key |
|---|---|---|
| `_SPLATTER_COLOR` `:99` | `[180,30,30]` | `splatter.color` |
| `_SPLATTER_ALPHA` `:100` | `170` | `splatter.alpha` |
| inline `4.0 / (tile_w / 2.0)` `:447` | `4.0` | `splatter.radius_px` |
| inline `r * 0.6` jitter `:450` | `0.6` | `splatter.jitter` |

`radius_px` stays a **screen-pixel** value converted to world units by the same
`/(tile_w/2.0)` expression — that division is geometry, not a tunable.

#### `procedural.floaters` — colour/lifetime ONLY (`:33-41`)

**Text layout is NOT in scope** (`submit_floater` / `submit` `:428-438` is HUD
chrome and stays untouched — see §3).

| Today | Value | JSON key |
|---|---|---|
| `_UPKEEP_BLUE` `:33` | `[120,170,230]` | `floaters.upkeep_color` |
| `_XP_PURPLE` `:34` | `[202,140,245]` | `floaters.xp_color` |
| `_XP_LIFE` `:35` | `0.9` | `floaters.xp_life` |
| `_PAINTER_FINISHED` `:38` | `[255,255,100]` | `floaters.painter_finished_color` |
| `_PAINTER_LOST` `:39` | `[255,100,100]` | `floaters.painter_lost_color` |
| `_PAINTER_LIFE` `:40` | `1.5` | `floaters.painter_life` |
| `_BOOST_WHITE` `:41` | `[255,255,255]` | `floaters.boost_color` |

### 1.4 Explicitly out of scope (do not touch)

- `submit_craters` `:530`, `submit_beams` `:507`, `submit_lightning` `:546`,
  `submit_announce` `:681-705` and their constants (`_BEAM_COLORS` `:46`,
  `_CRATER_COLOR` `:47`, `_ANNOUNCE_*` `:50-51`, `_BOLT_*` `:67-71`,
  `_LIGHTNING_MARKER` `:71`) → **ESV-3b**.
- HP bars: `submit_hp_bars` `:601-618`, `submit_enemy_hp_bars` `:620-665`,
  `_sprite_top` `:106-130`, `_ENEMY_BAR_*` `:61-62`, boss bar constants `:53-54`
  and `submit_boss_bars` `:707-731`. **ESV-1 is editing the HP-bar functions
  right now, in parallel.** See §3.
- Projectile dot `submit_projectiles` `:469-485` + `_PROJECTILE_*` `:101-102` —
  HUD chrome, stays.
- Floater TEXT layout `submit` `:428-438` (rise `-20 - 36*frac`, the last-third
  alpha fade) — stays.
- `AOE_TRAVEL_TIME` and `BEAM_MIN_TICK` (`game/enemies/combat.py:41,43`) are
  **simulation timing, not cosmetics.** Porting them would breach guardrail D4.
  Leave them where they are.

---

## 2. Architecture plan

### 2.1 `engine/vfx/` package shape (all new, all pure Python)

```
engine/vfx/__init__.py     # the public surface: params + Particle + VfxSystem
engine/vfx/params.py       # frozen dataclasses — one per effect family
engine/vfx/particle.py     # Particle (from effects.py:145-174) + GoldHighlight + Slash
engine/vfx/emitters.py     # pure emit_* functions: (rng, anchor, params) -> objects
engine/vfx/system.py       # VfxSystem: owns the lists, update(dt), submit(...)
```

`engine/vfx/` is **pure Python — no pygame** (it submits through `Renderer`,
which owns the backend). It joins the pure half of the engine's import
allow-list (`engine/CLAUDE.md` "Hard rules").

### 2.2 D5 / engine purity — the top risk of this phase

`engine/vfx/` must NOT:
- import `game.*` or `editor.*`;
- import `engine.data_io`, `json`, or any balancing loader;
- know a `data/` path or call `open()` / read JSON;
- carry game vocabulary in names (no `siege`, no `painter`, no `raider` —
  `engine/CLAUDE.md` "No game-specific names in the engine"). Presets are keyed
  by caller-supplied strings, never by an engine-side enum of game concepts.

Params arrive as **injected frozen dataclasses** built by the caller. This is
what lets `editor/` reuse the same emitters for ESV-4's preview without either
package importing the other.

**The tempting violation is a convenience `load_defaults()` helper** — a future
contributor adds one "just so tests don't have to build params", and the layer
is gone. §4 test 3 pins this as a RULE over the package's source text, not
merely as an import smoke test, precisely so that helper cannot be added later
without turning a test red.

### 2.3 The params contract

`engine/vfx/params.py` holds frozen dataclasses with **no defaults** — a default
here would be a second home for a value that lives in `data/` (G-7). Suggested
shape (the executor may refine; keep one dataclass per table in §1.3):

- `BurstParams(life, count, gravity, ramp, vx_min, vx_max, vy_min, vy_max, size_w, size_h)`
  — covers spark (per preset) and muzzle.
- `ShardBurstParams(...)` — death burst, whose colour is a per-particle pick and
  whose size is a per-particle range.
- `SlashParams(life, colors, lines_min, lines_max, ox_min, ox_max, oy_min, oy_max, size, size_large)`
- `GoldParams(life, fade_in, hold, fill_color, border_color, fill_alpha, border_width)`
- `SplatterParams(color, alpha, radius_px, jitter)`

Floater colours/lifetimes are **not** an engine concern — they are read by
`game/ui/effects.py` straight out of the loaded dict at the existing call sites
(`:248`, `:260`, `:268-270`, `:281`). Do not invent an engine dataclass for them.

### 2.4 Injected RNG — required, not optional

Today's emitters call the module-level `random` directly (`:295`, `:320`,
`:362`, `:367`), which is untestable. Every emitter takes an **injected `rng`**
(`random.Random`-compatible: `uniform`, `randint`, `random`, `choice`) as its
first argument. `VfxSystem.__init__(params, *, rng)` holds one and threads it.

`_Slash` already has the seam (`rng=random`, `:203`) — follow it.

**Draw order is behaviour.** Reproduce the exact sequence and count of RNG calls
per particle, or a seeded test can never pin equality and the visual character
shifts. Per site:
- spark `:295`: `uniform(vx)`, `uniform(vy)` — 2 calls/particle.
- death `:320-323`: `uniform(vx)`, `uniform(vy)`, `choice(colors)`,
  `randint(size_w)`, `randint(size_h)` — 5 calls/particle, in that order.
- muzzle `:362-368`: `random()`, `uniform(vx)`, `uniform(vy)` — 3 calls/particle,
  the smoke roll FIRST.
- slash `:209-213`: `randint(lines)` once, then per line `uniform(ox)`,
  `uniform(oy)`, `choice(colors)`.

### 2.5 `VfxSystem` — state + update + submit

`VfxSystem` takes over the four ESV-3a lists (`_particles`, `_gold`, `_slashes`,
`_splatters`) and the matching slice of `update(dt)` (`:413-421`). It exposes:

- `emit_burst(kind_params, wx, wy)` / `emit_shards(...)` / `emit_slash(...)` /
  `emit_gold(col, row)` / `add_splatters(points)` / `clear_splatters()` / `clear()`
- `update(dt)` — the age/step/filter loop lifted verbatim from `:413-421`.
- `submit_hud(renderer, cs)` — particles + slashes, i.e. `submit_fx` `:487-505`.
- `submit_world(renderer, cs)` — splatters + gold highlights, i.e.
  `submit_splatters` `:442-454` + `submit_gold_highlights` `:456-467`.

**All drawing goes through `Renderer`** — `submit_hud(HudRect/HudLines)`,
`submit_overlay_polys`, `submit_overlay_lines` (`engine/render/renderer.py:79`,
documented in `engine/render/CLAUDE.md` "Overlay primitives"). One render path,
ED-22. No new primitive types.

**Two submit methods, not one**, because `game/main.py:764-778` interleaves them
at different points in the frame: splatters + gold at `:764-765` (world overlay,
before the panel), particles + slashes at `:775` (HUD, after the bars). Merging
them would reorder the draw and break byte-identity.

### 2.6 How `game/` loads and passes the values

1. `data/balancing/vfx.json` + `data/schemas/vfx.schema.json` are new. The
   schema's top level is `{"procedural": {...}}` — **ESV-3b adds keys inside
   `procedural`, ESV-5 adds a sibling `triggers` block.** Structure it so both
   are additive (`procedural` is `"required"`; do not mark future siblings).
2. `game/core/balance.py:14` — add `"vfx"` to `DOMAINS`. `load_balance` `:17-23`
   already resolves `data/balancing/<domain>.json` against
   `data/schemas/<domain>.schema.json` by convention (**verified**), so no loader
   logic changes; only the tuple and its docstring ("all five domains" → six).
3. `game/main.py:197-201` gains `vfx_balance = load_balance(data_dir, "vfx")`,
   passed to `FloaterManager(...)` at `:263`.
4. `game/ui/effects.py` gains a **private adapter** — `_params_from_balance(vfx)`
   — that turns the validated dict into the engine dataclasses. This mapping
   (JSON key names ↔ dataclass fields) is the ONE place the two vocabularies
   meet, and it belongs on the game side so `engine/vfx/` never learns a key
   name. Colours arrive from JSON as lists; convert to tuples at the boundary
   (`HudRect`/`OverlayPolys` colours are tuples today).
5. `FloaterManager` keeps its public method names (`spawn_building_vfx`,
   `watch_buildings`, `watch_enemies`, `spawn_death_events`, `clear_splatters`,
   `clear`, `update`, `submit_splatters`, `submit_gold_highlights`, `submit_fx`)
   and delegates their bodies to the `VfxSystem` it now owns. **Do not rename a
   public method** — `game/main.py` and the existing tests call them by name.

### 2.7 D8 — `vfx` becomes a balancing domain automatically

`editor/domains.py:35-45` derives the domain list as slots.json category order ∩
the categories with a `data/balancing/<key>.json` (**verified**). `vfx` is
already a slots.json category (`data/slots.json:731`, **verified**), so creating
the balancing file promotes it with zero editor edits — exactly what
`tools/tests/test_editor_panels.py:189-200` demonstrates using `vfx` as its
synthetic example (**verified**).

That is also the problem: three shipped tests currently encode "vfx is NOT a
domain". They must be updated — **at the pinned fixture, never by re-pointing at
live `data/`**:
- `test_editor_panels.py:176-182` — `CANONICAL` (`domains()` on the real
  `data/`) grows a `"vfx"` entry, positioned per slots.json order.
- `test_editor_panels.py:189-195`
  (`test_new_balancing_file_adds_a_domain_in_slots_order`) — its whole premise is
  "vfx is asset-only TODAY". Re-point it at another asset-only category
  (`deco` / `backgrounds`), keeping the test's meaning intact.
- `test_editor_panels.py:343-348`
  (`test_asset_only_categories_exist_but_are_not_domains`) — drop the `vfx`
  assertion, keep `deco`.

**Where `vfx` lands in the tuple is INFERRED, not verified.** I read "after
`core`" off the existing test's expectation (`CANONICAL + ("vfx",)`,
`test_editor_panels.py:195`) — which is circular, because that test is one of
the three this phase invalidates. **Confirm the position against the category
order in `data/slots.json` directly before writing the fixture.**

`editor/domains.py:54`'s docstring also names vfx as asset-only with no schema
and goes stale the moment this phase lands. Fixing it is **sanctioned** — see §3.

---

## 3. File scope + shared-file contract

### May create

| Path | Contents |
|---|---|
| `engine/vfx/__init__.py` | public surface |
| `engine/vfx/params.py` | frozen param dataclasses |
| `engine/vfx/particle.py` | `Particle`, `GoldHighlight`, `Slash` |
| `engine/vfx/emitters.py` | pure `emit_*(rng, …)` functions |
| `engine/vfx/system.py` | `VfxSystem` |
| `data/balancing/vfx.json` | the `procedural` block, defaults = §1.3 |
| `data/schemas/vfx.schema.json` | its schema |
| `tools/tests/test_vfx.py` (name at executor's discretion) | §4 tests |

### May modify — exact insertion points

| File | Exact scope |
|---|---|
| `game/ui/effects.py` | constants block `:33-103` (**delete only the ESV-3a rows** listed in §1.3; leave `:46-71`, `:101-102` alone); helper classes `_Particle` `:145-174`, `_GoldHighlight` `:177-194`, `_Slash` `:197-213` (moved to `engine/vfx/`); `FloaterManager.__init__` `:225-242`; `spawn_building_vfx` `:286-299`; the death-burst block `:318-323` inside `watch_buildings`; the muzzle/slash block `:355-368` inside `watch_enemies`; `spawn_death_events` `:373-383`; `clear_splatters` `:385-388`; `clear` `:392-400`; the 10J half of `update` `:412-422`; `submit_splatters` `:442-454`; `submit_gold_highlights` `:456-467`; `submit_fx` `:487-505` |
| `game/core/balance.py` | `DOMAINS` `:14` + the module docstring's "five domains" `:1`. **Also in scope:** whatever `load_all` `:26-28` breaks — grep for callers; a test pinning a 5-tuple is a fixture update, not a reason to hold `vfx` out of `DOMAINS` (coordinator ruling 2). |
| `game/main.py` | `:197-201` (add the `vfx` load) and `:263` (pass it). **Justification:** `FloaterManager` cannot receive the params any other way — it is constructed there and nowhere else; this is the minimum edit, two lines, no logic change. Do NOT touch the `:755-785` submit ordering. |
| `editor/domains.py` | **THE `is_domain_category` DOCSTRING AT `:48-55` ONLY** — the sentence "vfx/deco/backgrounds carry no schema — they are asset-only" becomes false when this phase lands. Sanctioned by coordinator ruling 1. **No logic, no signature, no other file under `editor/`, nothing else in this module.** |
| `data/CLAUDE.md` | record `vfx` as a balancing domain (new `data/balancing/vfx.json` + `data/schemas/vfx.schema.json`), per root `CLAUDE.md` step-2 rule "if anything architectural changed, update the package CLAUDE.md". `/add-category` will want this. Sanctioned by coordinator ruling 3. |
| `tools/tests/test_editor_panels.py` | the three fixture updates named in §2.7 — **fixture edits only**, no re-point at live `data/` |
| `engine/CLAUDE.md` | a `vfx/` row in the subsystem table + a short "top-level modules"/purity note. Add `engine/vfx/CLAUDE.md` if the package grows its own conventions worth a doc. |
| `game/ui/CLAUDE.md` | update the "QOL + FX sweep (10J)" FX bullet + "Known divergences" to say the procedural params now live in `data/balancing/vfx.json` and the emitters in `engine/vfx/` |
| `tools/tests/conftest.py` | a `TIERS` entry for the new test module (required — `test_tiers.py` fails without it, `engine/CLAUDE.md` "Conventions") |

### Must NOT touch

- **`planning/EntitySceneVfxPLAN.md` — the plan doc is OUT OF SCOPE for this
  executor and for every phase agent.** The build-order table (including the
  ESV-3a / ESV-3b split and the widened scope) is updated once by the
  coordinator at the end of the run, then re-mirrored via `/setcurrentplan`.
  Six agents editing that table concurrently is a guaranteed conflict. Do not
  flip a Status cell, do not add a row. Root `PLAN.md` is a generated mirror and
  is never hand-edited by anyone.
- **`submit_hp_bars` `:601-618`, `submit_enemy_hp_bars` `:620-665`, `_sprite_top`
  `:106-130`, `_ENEMY_BAR_*` `:61-62` — ESV-1 owns these RIGHT NOW, in parallel.**
  A diff that reformats or re-indents them will conflict. Do not reflow the file,
  do not run a whole-file formatter, do not renumber constants that live outside
  §1.3's tables.
- `submit_craters` `:530-542`, `submit_beams` `:507-528`, `submit_lightning`
  `:546-597`, `submit_announce` `:681-705`, `spawn_boss_events` `:669-679`,
  `submit_boss_bars` `:707-731` and their constants — **ESV-3b**.
- `submit` `:428-438` (floater text layout), `submit_projectiles` `:469-485`.
- `game/enemies/combat.py` (D4 — see §1.4).
- Anything under `editor/` beyond the single sanctioned docstring above (ESV-4
  owns the preview).
- `data/` at test time — tests use `TempDataCase` and never write into the real
  `data/` (the session fixture hashes it and fails the run if it changed).

### Shared-file contract with ESV-1 (`game/ui/effects.py`)

Both phases edit this file. The split is by line range and it is clean:
**ESV-1 owns `:106-130` + `:601-665`** (sprite-top + HP bars). **ESV-3a owns
everything in the §3 "may modify" row above and nothing else in the file.** The
two ranges do not overlap. If a merge conflict appears anywhere other than the
import block at `:20-31`, one side has exceeded its scope — stop and report
rather than resolving it.

The import block `:20-31` is the one shared touchpoint: ESV-3a adds an
`engine.vfx` import and may drop `import random` `:20` **only if** no ESV-3b
effect still uses it — `submit_lightning:566` does (`_BOLT_JITTER`), so
**`import random` stays.**

### Schema requirements (`data/schemas/vfx.schema.json`)

- Every numeric key carries `description` + `minimum` + `maximum` (D-12). Copy
  the house pattern from `data/schemas/buildings.schema.json` (**verified** —
  e.g. its `attack_speed` block: `description` / `maximum` / `minimum` / `type`).
- Colours are `array` of 3 `integer`s, `minItems: 3`, `maxItems: 3`, items
  `minimum: 0` / `maximum: 255`. Ramps are arrays of colours,
  `minItems: 1`. Define these once in `$defs` (`color`, `ramp`) as
  `buildings.schema.json` defines its `$defs` blocks.
- `additionalProperties: false` at every object level (house pattern).
- Top level: `{"procedural": {...}}`, `procedural` required. Leave room for
  ESV-5's sibling `triggers` — do not close the top level so tightly that adding
  it is a breaking edit (`additionalProperties: false` + adding a key later is
  fine; a `maxProperties` would not be).
- `data/balancing/vfx.json` is written with the deterministic writer (sorted
  keys, 2-space indent, trailing newline — D-3), which `/add-balancing-value`
  handles.
- `tools/smoke.py` validates by stem convention
  (`data/foo.json ↔ schemas/foo.schema.json`, `tools/smoke.py:26-62`,
  **verified**) — the new pair needs no smoke.py edit.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py                        # data validation + 5-frame headless boot
py tools/testgate.py check --affected    # blast radius ∪ core tier
```

**NOT the full suite** — `--affected` is the gate for this phase. The gate is
`GATE PASS`; a red test outside this diff's blast radius gets reported, not
investigated.

### Required tests

1. **Seeded parity, muzzle spray** — a `VfxSystem` with a `random.Random(seed)`
   and the default params emits a particle set whose count, per-particle ramp,
   lifetime, velocity, gravity and size **exactly equal** what the old code path
   produced from the same seed. Pin standard (8) and siege-strong (13) and the
   smoke/non-smoke ramp split. The old path is reproducible from `effects.py`
   `:359-368` — encode the expected values as literals in the test, not by
   calling the old code.
2. **Seeded parity, death burst** — same, for the 14-shard burst `:318-323`:
   count, the per-particle 1-tuple colour, the two independent size draws,
   gravity `60.0`, life `0.65`. This is the strictest pin because it makes 5 RNG
   draws per particle in a fixed order (§2.4).
3. **D5 as a RULE over `engine/vfx/`, not just an import smoke test** — scan the
   SOURCE TEXT of every file in the package and assert it contains **no
   `open(`**, **no `import json` / `from json`**, **no import of `game.*`,
   `editor.*`, `engine.data_io` or any balancing loader**, and **no `pygame`
   import**. State the rule in the test's docstring: the emitters take injected
   params, full stop. The failure mode this exists to catch is a future
   convenience `load_defaults()` helper — an import-graph-only version of this
   test would happily pass the day someone adds one, because it would pull in a
   loader the package "already depends on" transitively. Scan the text. Follow
   the existing `TestPurity` source-scan pattern used by `game/ui` and `editor/`.
4. **Domain promotion** — with the balancing file present, `"vfx"` appears
   exactly once in `editor.domains.domains(data_dir)`, in slots.json order.
   Against a `TempDataCase` copy, never live `data/`. Confirm the expected
   POSITION against `data/slots.json`'s category order before writing it
   (§2.7 — do not copy it from the test this phase invalidates).
5. **Schema completeness** — walk `data/schemas/vfx.schema.json` and assert every
   `"type": "integer"|"number"` leaf carries `description`, `minimum` and
   `maximum` (D-12). This is the cheap generic guard that keeps ESV-3b and ESV-5
   honest when they add keys.
6. **Default round-trip** — every value loaded from `data/balancing/vfx.json`
   equals the §1.3 "today" column. This is the byte-identity contract in test
   form; it is what makes a later retune a deliberate, visible diff.

Every test that reads or writes data uses `TempDataCase`. Every new test module
gets a `TIERS` entry in `conftest.py`.

### Quick Test (in-game, manual)

```bash
py game/main.py
```

1. Unlock a tile and **place** a building → gold spark burst **and** the gold
   tile diamond fade (in 0.15 / hold 0.35 / out 0.70). Upgrade it in-tier
   (smaller burst, no gold), then **advance a tier** → the biggest burst (26
   sparks, 1.2 s) **plus** a gold diamond.
2. End Turn. When ranged enemies engage a building → the leftward orange
   **muzzle spray** with occasional grey smoke motes; a **siege** unit's spray is
   visibly denser and longer. A **raider** (or the boss) instead shows 2-3 white
   diagonal **slash** lines.
3. Let a defender die → the 14 purple **death shards** arcing under gravity, and
   the kill line in the game log for a named building.
4. Kill enemies → red **blood splatters** on the ground, persisting until the
   next wave starts, and gated off when gore is disabled in settings.
5. Every one of the above must look **unchanged from `Development`.** If
   anything reads faster, denser, brighter or differently coloured, the port is
   wrong — that is the whole acceptance criterion for this phase.

---

## 5. Notes for the executor

**Coordinator rulings, already folded into §3/§4 — do not re-litigate:**
`editor/domains.py:48-55` docstring is sanctioned (that docstring only);
`game/core/balance.py` `load_all` fallout is in scope; `data/CLAUDE.md` is in
scope; `planning/EntitySceneVfxPLAN.md` is NOT (the coordinator updates the
build-order table once, at the end of the run).

**One claim in this brief is INFERRED and must be checked before you rely on
it:** where `vfx` lands in `domains()`'s tuple order (§2.7, §4 test 4). Read
`data/slots.json`'s category order directly — do not take it from
`test_editor_panels.py:195`, which this phase invalidates.

**One design note, in case it tempts you:** `_SPARK_PRESETS` is keyed by the game
strings `place`/`level1`/`level2`/`tier` (`:76-81`). Those are game vocabulary
and must not become an engine enum. The JSON holds them under
`spark.presets.<key>`; `game/ui/effects.py` resolves key → `BurstParams` before
calling the engine, keeping the existing `.get(kind, presets["place"])` fallback
(`spawn_building_vfx:290`) on the game side.
