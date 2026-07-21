# Phase ESV-5 — Sprite one-shots (`PlayOnceVfx`) + trigger table + importer slots

Source plan: `planning/EntitySceneVfxPLAN.md` §ESV-5 (+ §6 item 2, folded in
here by the plan's own instruction). Branch: `phase-esv-5-sprite-oneshots` off
`VfxEditor`. **Cross-package: data + engine + game + editor.**

**Read**: `data/CLAUDE.md`, `engine/CLAUDE.md`, `game/ui/CLAUDE.md`,
`editor/CLAUDE.md`. **Read first**: `docs/briefs/phase-esv-3a-vfx-emitters.md`
and `docs/briefs/phase-esv-3b-scene-vfx.md` — their patterns
(`_params_from_balance`, frozen param dataclasses, the injected stdlib `random`
module, `TestEnginePurity`'s source-text scan) are PROVEN. Extend them; do not
re-litigate them.

**Open with these skills, do not hand-roll**: `/add-balancing-value` for the new
`triggers` block, `/add-engine-component` for the new `engine/vfx/` module.

**Landing condition: byte-identical with no art imported.** Every shipped
trigger row reproduces today's behaviour exactly. The one new row
(`defender_fire`) ships INERT. Any pixel difference on a fresh checkout is a bug
in this phase, not a design choice.

**Guardrail D4 (from the plan's §1)**: purely cosmetic. Nothing here reads or
writes damage, range, splash or simulation state.

---

## 1. Behavioural spec

### 1.1 The 8 live one-shot trigger sites (all **verified**, post-ESV-3b line numbers)

`game/ui/effects.py` is 706 lines. These are the ONLY sites this phase re-routes:

| # | Site | file:line | Today's call | Event name |
|---|---|---|---|---|
| 1 | `spawn_building_vfx`, kind `place` | `effects.py:339` (+ `:341` gold) | `emit_burst(presets["place"])` + `emit_gold` | `building_placed` |
| 2 | `spawn_building_vfx`, kind `level1`/`level2` | `effects.py:339` | `emit_burst(presets["level1"/"level2"])` | `building_level_up` |
| 3 | `spawn_building_vfx`, kind `tier` | `effects.py:339` (+ `:341` gold) | `emit_burst(presets["tier"])` + `emit_gold` | `building_tier_up` |
| 4 | `watch_buildings` | `effects.py:360` | `emit_shards(wx, wy)` | `building_destroyed` |
| 5 | `watch_enemies`, raider/boss | `effects.py:393` | `emit_slash(wx, wy, large=…)` | `enemy_attack_melee` |
| 6 | `watch_enemies`, others | `effects.py:395` | `emit_muzzle(wx, wy, strong=…)` | `enemy_attack_ranged` |
| 7 | `spawn_death_events` | `effects.py:410` | `add_splatters(events)` | `enemy_death` |
| 8 | mortar shell impact | `game/enemies/combat.py` `ProjectileAOE` impact — the `Crater(...)` construction | (spawns the `Crater` GameObject) | `splash_impact` |

Plus one event with **no site today**:

| 9 | **`defender_fire`** | `game/enemies/combat.py` `_fire` `:474-478` / `_fire_splash` `:481-491` | **nothing — defenders emit NO VFX today** | `defender_fire` |

**This is the phase's most important fact and it was confirmed by grep**: the
only `emit_muzzle`/`emit_slash` call sites in the whole repo are `effects.py:393`
and `:395`, both inside `watch_enemies`, i.e. **enemy** attacks. A defender firing
produces a projectile and nothing else. `defender_fire` therefore ships with
**both** `sprite_slot` and `procedural` empty — an inert row that a designer
turns on. ESV-6 uses it as the convergence demo. **Do not bind it to the
procedural muzzle "to be consistent"** — that would be a visible behaviour change
on landing and breaks the plan's ordering rule.

### 1.2 Explicitly NOT trigger events (do not add rows for these)

- **Floaters** (`spawn_income_events` `:291`, `spawn_xp_events` `:300`,
  `spawn_painter_events` `:310`, `spawn_boost_events` `:322`) — text, not bursts.
  Their dead-data gap is **ESV-6's** job (plan §6 item 1). **Do not touch
  `effects.py:62-70` or `procedural.floaters` in this phase.**
- **Continuous / stateful effects**: `submit_beams` `:492`, `submit_craters`
  `:519`, `submit_lightning` `:539`, `submit_announce` `:692`. The plan's §5 is
  explicit: *"Beams/lightning are continuous and stay procedural — do not force
  them into `PlayOnceVfx`."* `splash_impact` (#8) is the crater's **spawn**
  moment, which IS a one-shot; the crater's continuous fade DRAW stays exactly as
  it is.
- **HUD chrome**: `submit_hp_bars`, `submit_enemy_hp_bars`, `submit_boss_bars`,
  `submit_projectiles`, `submit`.

### 1.3 Anchors are ESV-6's job, not this phase's

ESV-5 spawns every effect at **exactly the world point it uses today** (tile
centre / `transform.world_pos`). `game/anchors.py world_offset` exists and works,
but re-pointing spawn points at the `muzzle`/`impact` anchors is **ESV-6**. Keep
the two changes separable — if ESV-5 also moved the spawn points, a visual
regression could not be attributed.

---

## 2. Architecture plan

### 2.1 `engine/vfx/play_once.py` (new) — copy the Corpse pattern

`SpriteAnimator` (`engine/core/sprite_animator.py:14-39`, **verified**) declares
`slot_key`, `animation`, `phase_ms`, `anim_time_ms`, `fit_tiles`, `scale`. It has
**no `loop_count`, no completion signal** — `update(dt)` just accumulates
`anim_time_ms` unbounded. **Do not add a `loop_count` field to `SpriteAnimator`.**
The plan (D6) allows either approach and completion-tracking inside the new
GameObject is strictly cheaper: `SpriteAnimator` is used by every building and
enemy in the game, and a new field on it is a save/load + editor-inspector
surface change for a problem that one cosmetic object has.

**The pattern to copy is `game/enemies/corpse.py:26-77`** (**verified** — it is
the proven cosmetic self-despawn in this repo, landed in `4302b16`):

```python
class PlayOnceFade(Component):
    """Ages to ``life_ms`` then despawns the owner (the ``CorpseFade`` pattern)."""
    life_ms: int = 0
    age_ms: float = 0.0

    def on_added(self, owner):
        self._owner = owner      # transient env refs, E-11 underscore
        self._scene = None

    def update(self, dt):
        self.age_ms += dt * 1000.0
        if self.age_ms >= self.life_ms:
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(self._owner)


class PlayOnceVfx(GameObject):
    """A one-shot cosmetic sprite: plays its sheet once at a world point, then
    despawns."""
    # name="vfx_oneshot", tags=("vfx_oneshot",), Transform(wx, wy, layer),
    # components=[SpriteAnimator(slot_key, animation=ONESHOT_ANIM, …),
    #             PlayOnceFade(life_ms=…)]


def spawn_play_once(scene, assets, slot_key, wx, wy, *, layer="entities",
                    fit_tiles=0.0, scale=1.0):
    """Spawn a ``PlayOnceVfx`` playing ``slot_key``'s sheet once. Returns None
    when the slot has no art — the caller's cue to run its procedural
    fallback (E-37 art tolerance)."""
```

`ONESHOT_ANIM = "idle"` — the `vfx` slot category declares exactly one animation
row, `["idle"]` (`data/slots.json:715-731`, **verified**).

**The `None` return is the entire art-tolerance mechanism.** Derive `life_ms`
from `assets.animation_total_ms(slot_key, ONESHOT_ANIM)`
(`engine/assets/store.py:46-50`, **verified** — returns `None` when the slot or
animation is absent, with **no** fallback to idle). `None` → return `None`, spawn
nothing. This is the same read `spawn_corpse` uses to decide whether a death
animation exists.

**D5 engine purity**: `play_once.py` receives `assets` as an argument. It must
NOT import `game.*`/`editor.*`/`engine.data_io`, must not `import json`, must not
`open(`, must not import `pygame`, and must carry no game vocabulary in its names
(`muzzle`/`hit`/`explosion` are generic VFX nouns and are fine; `defender`,
`mortar`, `siege` are not). `TestEnginePurity` in `tools/tests/test_vfx.py`
globs `engine/vfx/*.py` so the new module is covered automatically — **confirm
that and say so in your report.**

**`VfxSystem` needs NO change.** It owns particle lists; `PlayOnceVfx` objects
live in the scene and age in `scene.update`, exactly as `Crater`/`LightningFX`/
`Corpse` do. Do not add a parallel engine-side list — that would be a second
source of truth for the same despawn clock (the ESV-3b §2.1 ruling, which
applies verbatim here).

### 2.2 `data/slots.json` — four new slots

The `vfx` category (`data/slots.json:715-731`, **verified**) is the simplest in
the file: one group, flat `slots` array, category-level `frame_w`/`frame_h` 64
and `animations: ["idle"]`.

Extend the `Effects` group's `slots` array from `["vfx_hit", "vfx_explosion"]` to
include `vfx_muzzle`, `vfx_death`, `vfx_slash`, `vfx_crater`. Bare strings — no
per-slot overrides. Keep the array's existing ordering convention.

**That is the entire importer change.** `editor/asset_import.py:139-150`'s
`import_idle_sheet` calls `registry.frame_size(slot_key)`, which raises `KeyError`
for a slot absent from `slots.json` — so registry membership IS importability.
**No editor code is needed to make these importable.** (§2.4's stack fix is a
separate, pre-existing defect.)

### 2.3 The trigger table — `data/balancing/vfx.json` + schema

A **new top-level `triggers` object, sibling to `procedural`.** The schema's own
description already anticipates it (`data/schemas/vfx.schema.json`: *"ESV-5 adds
a sibling triggers object at the top level"*, **verified**). It is the ONLY other
top-level key — do not nest it under `procedural`, and do not add a third.

Per-event row shape:

```json
"triggers": {
  "enemy_attack_ranged": { "sprite_slot": "", "procedural": "muzzle" }
}
```

**Resolution order, identical at every call site:**

1. `sprite_slot` non-empty **AND** `spawn_play_once` returns an object → done, the
   sheet plays.
2. Otherwise → run the procedural kind named by `procedural`.
3. `procedural` empty (or the row absent) → **silent no-op**, never a raise
   (E-37).

Note the ordering: a bound slot with **no art imported** falls through to step 2.
That is what makes a fresh checkout byte-identical.

**Shipped defaults** — every row reproduces today:

| Event | `sprite_slot` | `procedural` |
|---|---|---|
| `building_placed` | `""` | `"spark_place"` |
| `building_level_up` | `""` | `"spark_level"` |
| `building_tier_up` | `""` | `"spark_tier"` |
| `building_destroyed` | `""` | `"death_burst"` |
| `enemy_attack_melee` | `""` | `"slash"` |
| `enemy_attack_ranged` | `""` | `"muzzle"` |
| `enemy_death` | `""` | `"splatter"` |
| `splash_impact` | `""` | `"crater"` |
| `defender_fire` | `""` | `""` |

**A naming subtlety you must resolve deliberately:** `spawn_building_vfx` takes a
`kind` in `place|level1|level2|tier` and looks up `self._spark_presets`
(`effects.py:337`). The table above collapses `level1`/`level2` into one event
(`building_level_up`) because they differ only by preset, not by effect identity.
**Keep the existing `_spark_presets.get(kind, presets["place"])` lookup for the
PROCEDURAL branch** — the procedural kind `spark_level` resolves to the preset for
the actual `kind` argument. The event only decides *which effect family* plays;
the preset detail stays where it is. If you find this collapse makes the code
worse, splitting into `building_level1`/`building_level2` is acceptable — **say
which you chose and why in your report.**

**Gold highlight is NOT a separate event.** `emit_gold` at `:341` is a rider on
`place`/`tier` (`if kind in ("place", "tier")`). Leave that conditional exactly
as-is, outside the trigger dispatch. Making it a tenth event would let a designer
desynchronise the burst from its highlight for no gain.

**Schema requirements** (D-12 house policy, `data/CLAUDE.md`):
- `additionalProperties: false` at every object level; every event key `required`.
- `sprite_slot`: a string **enum** — `""` plus the six `vfx_*` slot keys.
- `procedural`: a string **enum** — `""` plus the eight procedural kinds above.
- `description` on every key, including the enums (say what `""` means).
- Enums, not free strings: a typo'd slot key must fail validation at write time,
  not silently no-op at runtime.
- The deterministic validating writer only (sorted keys, 2-space indent, D-3).

### 2.4 Fix the ESV-4 stack-index defect (plan §6 item 2)

The plan says: *"Fold the fix into ESV-5's brief, not deferred past it."*
**Two real defects, both `editor/main.py`** (**verified** by reading the file):

1. **`_leave_vfx_mode()` `:444-445`** calls
   `self.right_stack.setCurrentWidget(self.details)`. But `self.details` is a
   **child of** `self.details_pane` (`:299-306`), not a stack page — only
   `details_pane` was ever `addWidget`-ed (`:307`). Qt makes this a no-op (and
   logs a warning). Compare `:384` and `:424`, which both correctly use
   `self.details_pane`. **Consequence: select a vfx node once and you can never
   return to the asset importer for the rest of the session.**
2. **`_enter_vfx_mode()` `:441-442`** swaps to the vfx preview (index 3)
   *instead of* the details pane, so a selected `vfx` node cannot show the asset
   importer at all — which §2.2 just made necessary.

**The fix — reuse ESV-2's own precedent.** `:298-307` already solved exactly this
shape by putting two panels in one container:

```python
self.details_pane = QWidget()
details_pane_layout = QVBoxLayout(self.details_pane)
details_pane_layout.setContentsMargins(0, 0, 0, 0)
details_pane_layout.addWidget(self.details)
details_pane_layout.addWidget(self.anchors)
self.right_stack.addWidget(self.details_pane)     # index 0
```

Do the same for the preview: **add `self.vfx_preview` as a third child of
`details_pane`'s layout, and delete stack index 3.**

- `:309` — remove `self.right_stack.addWidget(self.vfx_preview)`; add
  `details_pane_layout.addWidget(self.vfx_preview)` and
  `self.vfx_preview.setVisible(False)` at construction.
- `_enter_vfx_mode()` → `self.right_stack.setCurrentWidget(self.details_pane)`
  **and** `self.vfx_preview.setVisible(True)`.
- `_leave_vfx_mode()` → `self.vfx_preview.setVisible(False)`. **No stack call at
  all** — the other `_leave_*` handlers already own the stack page, and
  `_on_node_selected` `:338-347` calls `_leave_map_mode()`/`_leave_screen_mode()`
  before the vfx branch, so the page is already correct. This deletes the buggy
  line rather than fixing it.
- **`:843`** — the render gate `if self.right_stack.currentWidget() is
  self.vfx_preview:` must become `if self.vfx_preview.isVisible():`. **Miss this
  and the preview goes permanently black.** It is the only other read of the
  index-3 relationship (**verified** by grepping `vfx_preview` in `editor/main.py`
  — the six hits are `:64`, `:105`, `:173`, `:174`, `:309`, `:442`, `:843`).

Result: `right_stack.count() == 3`, both panels reachable for a vfx node, and the
anchors panel keeps behaving exactly as ESV-2 left it.

**Check the vertical budget.** `details_pane` will now stack three panels. If the
preview is squeezed unusably, a `QSplitter` inside `details_pane` (or a stretch
factor) is the right escalation — **but keep index 0 as the single stack page.**
Report what you did.

### 2.5 `game/ui/effects.py` — the dispatch seam

Add a `_triggers_from_balance(vfx)` helper beside `_params_from_balance`
(`:117`), returning a plain `{event: (sprite_slot, procedural)}` dict. Same
principle as `_params_from_balance`: **this is the ONE place a JSON key name is
read**; nothing downstream learns a key name.

Add one private dispatcher on `FloaterManager`:

```python
def _play(self, event, wx, wy, **kw):
    """Consult the trigger table: a bound sprite slot with art spawns a
    PlayOnceVfx; otherwise the named procedural kind runs; an empty row is a
    silent no-op (E-37)."""
```

`**kw` carries the per-kind extras the procedural branch needs (`preset` for the
spark burst, `large=` for the slash, `strong=` for the muzzle, `points=` for the
splatter).

**`_play` needs two handles `FloaterManager` does not have today: the `AssetStore`
and the `Scene`.** Wire both as **host-set attributes**, following the existing
`self.log = None  # GameLog, wired by the host` precedent at `:273`:

- `effects.py` `__init__`: `self.assets = None` and `self.scene = None` beside
  `self.log`.
- `game/main.py` `build_gameplay`, beside `:277-278`
  (`gp["panel"].on_build_vfx = …` / `gp["floaters"].log = …`):
  `gp["floaters"].assets = assets` and `gp["floaters"].scene = world.scene`.

**Do NOT change `FloaterManager.__init__`'s signature.** ESV-3a made
`vfx_balance` a required third arg, updated its own branch's tests, and missed
`tools/tests/test_hp_bar_anchors.py` which ESV-1 added in parallel — a textually
clean, semantically broken merge fixed at integration in `b960d12`. Attribute
wiring avoids repeating that. `assets` is already in scope at `main.py:186`; a
fresh `FloaterManager` and a fresh scene are built together per run in
`build_gameplay`, so the two attributes cannot desync.

Either handle being `None` (every existing test constructs `FloaterManager`
bare) must degrade to the procedural branch, never raise. Pin that with a test.

**Site #8 (`splash_impact`) is the odd one out**: the crater is spawned in
`game/enemies/combat.py`, not `effects.py`, and `FloaterManager` is not reachable
from there. Options, in order of preference:
- **(a)** Push a `splash_impact` event onto a `RunState` ledger at the impact and
  drain it in `spawn_death_events`' neighbourhood — the drained-ledger house
  pattern this file uses everywhere.
- **(b)** Leave #8's `Crater` spawn untouched and have the trigger row's sprite
  branch spawn an *additional* `PlayOnceVfx` at the impact.
- **(c)** If neither is clean within this phase's budget, **ship the
  `splash_impact` row in the schema and JSON but leave its call site unrouted**,
  and say so LOUDLY in your report so ESV-6 picks it up.

Prefer (a). Do **not** thread `FloaterManager` into `resolve_combat` — that is a
`game/ui → game/enemies` dependency in the wrong direction.

### 2.6 No new loading plumbing

`vfx` is already a balancing domain; `game/main.py:202` loads it and passes it to
`FloaterManager` (`:264`). ESV-5 adds a top-level key that
`_triggers_from_balance` reads from the same dict. `tools/smoke.py` validates by
stem convention — no smoke.py edit. `editor/domains.py`'s derived list is
unchanged (`vfx` is already in `test_editor_panels.py:156`'s `CANONICAL`).

---

## 3. File scope

### May create

| Path | Contents |
|---|---|
| `engine/vfx/play_once.py` | §2.1 |
| `tools/tests/test_vfx_play_once.py` | §4 tests (extending `test_vfx.py` is equally fine) |

### May modify

| File | Exact scope |
|---|---|
| `engine/vfx/__init__.py` | add `PlayOnceVfx`/`PlayOnceFade`/`spawn_play_once` to imports + `__all__`, alphabetical. **APPEND only — never rename or reshape anything ESV-3a/3b exported**; `editor/panels/vfx_preview.py` consumes that surface. |
| `data/slots.json` | §2.2 — four slot strings, nothing else |
| `data/balancing/vfx.json` | §2.3 — the new top-level `triggers` object. **Do not touch `procedural`.** |
| `data/schemas/vfx.schema.json` | §2.3 — the `triggers` subschema + `required`; update the top-level `description`'s "ESV-5 adds…" sentence to past tense |
| `game/ui/effects.py` | §2.5 — `_triggers_from_balance`, `_play`, `self.assets`/`self.scene`, and the 7 in-file call sites (`:339`, `:341`-adjacent, `:360`, `:393`, `:395`, `:410`). Module docstring gains an ESV-5 paragraph. **Do NOT change `__init__`'s signature.** |
| `game/main.py` | §2.5 — two attribute assignments near `:277-278`. **Do NOT touch the `:766-780` submit ordering.** |
| `game/enemies/combat.py` | §2.5 option (a) only — the ledger push at the `Crater` spawn. **`AOE_TRAVEL_TIME`, `BEAM_MIN_TICK`, `_predict_lead`, every damage/range expression are FORBIDDEN (D4).** |
| `game/core/state.py` (or wherever `RunState` lives) | §2.5 option (a) only — one new ledger list beside `enemy_death_events` |
| `editor/main.py` | §2.4 — `:298-309`, `:441-445`, `:843`. Nothing else. |
| `tools/tests/**` | §4; plus `conftest.py`'s `TIERS` entry if you add a module (`test_tiers.py` fails without it) |
| `engine/CLAUDE.md` | the `vfx/` subsystem row gains `play_once` |
| `game/ui/CLAUDE.md` | the "QOL + FX sweep (10J)" section gains an **ESV-5** bullet beside the ESV-3a/3b ones (trigger-table indirection + the two host-wired attributes) |
| `editor/CLAUDE.md` | the vfx-mode routing note, if one exists |
| `data/CLAUDE.md` | the `vfx` paragraph: `triggers` is now a real top-level sibling; the four new slots |

### Must NOT touch

- **`game/ui/effects.py:62-70`** (the floater constants) and
  **`procedural.floaters`** — ESV-6 owns them (plan §6 item 1).
- `submit_beams` `:492`, `submit_craters` `:519`, `submit_lightning` `:539`,
  `submit_announce` `:692` and their params — §1.2.
- `_params_from_balance` `:117-…`, `_ramp` `:107`, `_color` `:103`, and every
  `procedural.*` block in `vfx.json`/its schema.
- `engine/core/sprite_animator.py` — §2.1 (no `loop_count`).
- `game/anchors.py` and every anchor read site — ESV-6.
- HUD chrome: `submit_hp_bars`, `submit_enemy_hp_bars`, `submit_boss_bars`,
  `submit_projectiles`, `submit`, and their constants.
- `planning/EntitySceneVfxPLAN.md`, root `PLAN.md` — the orchestrator updates the
  build-order table at the end.
- Do not reflow `game/ui/effects.py` or `editor/main.py`, do not run a whole-file
  formatter, do not renumber constants outside this brief's tables.

---

## 4. Exit gate + Quick Test

### Gate

```bash
py tools/smoke.py                        # data validation + 5-frame headless boot
py tools/testgate.py check --affected    # blast radius ∪ core tier
```

`GATE PASS` or you are not done. **The gate is ZERO** — there is no baseline to
tolerate. A red test clearly outside this diff's blast radius: **note it in your
report and stop**, do not investigate.

Do **not** run the full `check` — `--affected` is this phase's gate. Do **not**
run a manual `pytest` sanity pass first; it duplicates the gate.

### Required tests

Every test uses `TempDataCase` / the pinned `FIXTURE_DATA` snapshot
(`tools/tests/fixture_data.py`; the ESV-3a pattern at `test_vfx.py:23-24`), never
writes into `data/`, and **never asserts against live `data/` content**. Encode
expectations as **literals** — never re-read the JSON you are validating.
**Seed any RNG** (`game/CLAUDE.md`: a bare `random` made a test fail ~1 run in 10).

1. **`spawn_play_once` returns `None` for a slot with no art** and spawns
   nothing into the scene. This is the art-tolerance contract.
2. **`PlayOnceVfx` despawns after exactly one play** — with a fixture sheet whose
   `animation_total_ms` is known, stepping the scene to just under the duration
   keeps it alive and just over despawns it. Assert the scene object count both
   sides.
3. **Byte-identical fallback, all 8 events.** With no art, each event's dispatch
   produces the **same particle/splatter set** as calling the `VfxSystem` method
   directly with the same seed. This is the landing-condition contract in test
   form — write it for all eight, not a representative sample.
4. **`defender_fire` is inert** — dispatching it with no art and the shipped row
   emits nothing and raises nothing.
5. **Reassignment works** — rewriting a row's `procedural` in a temp `vfx.json`
   changes which effect the event plays; rewriting `sprite_slot` to a slot WITH a
   fixture sheet spawns a `PlayOnceVfx` instead of particles.
6. **Missing row / empty row / `None` handles** — an event absent from the table,
   a row with both fields `""`, and a `FloaterManager` with `assets=None` or
   `scene=None` each degrade silently (E-37). No raise, ever.
7. **Schema**: the fixture `vfx.json` validates with `triggers`; an unknown event
   key fails; a `sprite_slot` not in the enum fails; a `procedural` not in the
   enum fails. Every key carries a `description` (extend the existing generic
   walker in `test_vfx.py` if it already covers the whole file — **verify whether
   it does and say so** rather than duplicating it).
8. **Slot registry**: the four new `vfx_*` slots resolve through
   `registry.frame_size` (i.e. they are importable) and inherit 64×64.
9. **Engine purity extended** — confirm `TestEnginePurity`'s glob covers
   `play_once.py`. Assert the scanned file COUNT equals the package's actual
   module count, so a future subpackage cannot slip past the glob.
10. **Editor (editor tier, offscreen Qt, temp data dir)**: selecting a `vfx` node
    leaves `right_stack` on `details_pane` **and** makes `vfx_preview` visible;
    selecting a non-vfx node hides the preview and keeps the importer reachable
    (**the regression pin for the `:445` bug** — this test must fail on the
    current code); `right_stack.count() == 3`.
11. `tools/tests/test_editor_viewport.py:728-758` `TestPurity` — add any new
    editor module (none expected; confirm).

### Quick Test (manual)

```bash
py editor/main.py
```
1. Select the **VFX** node in the selector: **both** the asset importer and the
   VFX preview are visible in the right pane, and the preview animates.
2. Select a **building** node: the preview disappears, the importer + anchors
   panel are there. Select the VFX node again: it comes back. *(On the current
   code, step 2 is impossible — that is the bug you fixed.)*
3. Import any placeholder 64×64 sheet into `vfx_muzzle`.
4. In the `vfx` balancing form, set `triggers.enemy_attack_ranged.sprite_slot`
   to `vfx_muzzle`. Save.

```bash
py game/main.py
```
5. Reach ENEMY phase with a blocked ranged enemy: its attack now plays the
   imported sheet once, at the same point the muzzle spray used to appear.
6. Clear the row back to `""` → the procedural muzzle spray returns, unchanged.
7. **Everything else looks exactly as it did before this phase** — sparks on
   place/upgrade, gold highlight, building-death shards, melee slash, blood
   splatters, mortar craters, beams, lightning, boss banner. Any difference is a
   bug.
8. Defenders still emit **no** fire VFX (`defender_fire` is inert by design).

---

## 5. Notes for the executor

- **The one INFERRED claim in this brief**: §2.5's assertion that option (a)
  (the ledger) is cleaner than (b) for `splash_impact`. Read the impact site
  yourself before committing to it, and take (c) with a loud report rather than
  forcing a bad seam.
- **Report LOUDLY**: any public signature change (so ESV-6 can be adjusted), and
  your `building_level_up` vs `building_level1`/`level2` decision (§2.3).
- **Report, do not fix**: anything you notice about `procedural.floaters` or the
  anchors — both are ESV-6's.
- Tag every claim in your report **measured** / **verified** / **inferred**
  (`/report`).
