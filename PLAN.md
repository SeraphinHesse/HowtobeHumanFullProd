<!-- active-plan: VfxAuthoringPLAN.md | set: 2026-08-13 -->
> **Active plan:** VfxAuthoringPLAN.md (mirror). Source of truth:
> `planning/VfxAuthoringPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: IN PROGRESS — 2/8 phases (VA-1, VA-2 done), authored 2026-08-13 -->
<!-- plan-scale: medium -->

# VfxAuthoringPLAN.md — Authoring the VFX roster

Phased, agent-executable plan (same family as `EntitySceneVfxPLAN.md` /
`AgentDispatchPLAN.md`). Base branch: `Development`; work branch
`vfx-authoring`. Runnable via `/execute-plan-phases planning/VfxAuthoringPLAN.md
VA-1-VA-8` or phase-by-phase. Four packages: **data · engine · game · editor**.

Direct successor to `planning/completed plans/EntitySceneVfxPLAN.md`. Read that
plan's §7 (post-plan live-testing follow-ups) before touching anchors or draw
order — it records four bugs this area has already produced.

## 1. Vision

ESV gave the designer control over how each effect *looks*: procedural params in
`data/balancing/vfx.json`, a live preview panel, a `triggers` table binding ten
game events to a `vfx_*` spritesheet or a procedural kind.

It gave no control over the **roster**. You cannot add an effect, remove one,
rename one, or give one alternate art. Three things the designer wants are not
in the system at all — the building respawn, the tile-selection outline, and the
2×2 section outline. And no effect can say whether it draws over or under the
things on the map.

After this plan a designer can, without an agent:

- **Add, remove and rename** VFX effects and their variants from the editor,
  with the imported art, the manifest entry and the trigger bindings following
  the rename.
- **Give an effect alternate art** and choose how a variant is picked at play
  time — at random, by the source's level (era for enemies, tier for buildings),
  or by a named misc value that code hooks up later.
- **Author the respawn effect and all seven tile highlights** the same way as
  every other effect: tunable, previewable, replaceable by a spritesheet.
- **Say whether an effect draws in front of or behind** the buildings and
  enemies, per effect.

## 2. Architecture

```
data/                              engine/                        game/ + editor/
─────                              ───────                        ───────────────
slots.json  vfx category           coords/system.py               game/vfx_misc.py   (NEW)
  Effects ▸ per-effect leaf          depth_key(..., rank)  ◄──┐     misc provider registry
  groups  (RESTRUCTURE, VA-1)                                 │
    └─ variants <stem>_v<k>        render/item.py             ├─► game/ui/effects.py
                                     WorldRect (NEW)          │     _play  (one-shot)
schemas/vfx.schema.json              screen-px size,          │     _submit_highlight (NEW,
  trigger_row                        world depth, rank        │        continuous)
    + variant_select {mode,        vfx/system.py              │     variant resolve site
        misc_key}                    submit_world (NEW) ──────┘
    + draw_in_front                                             editor/registry_ops.py
    sprite_slot enum: GENERATED    vfx/params.py                  add_vfx_effect (NEW)
                                     +8 param dataclasses         remove_slot    (NEW)
balancing/vfx.json                                                rename_slot    (NEW)
  procedural.respawn      (NEW)                                 editor/panels/vfx_preview.py
  procedural.highlights.* (NEW ×7)                                roster strip, trigger bind,
  triggers +8 rows                                                variant-select, layer bool
ui/palette.json
  −highlight −highlight2 −range_highlight   (move to vfx.json)
```

### Decisions (with rationale)

- **D1 — The `vfx` slot category becomes one leaf child group per effect.**
  Variants in this repo are `<stem>_v<k>` slots inside a leaf *child* group;
  `selection.variant_target()` returns `None` for a flat `slots` list, so
  `registry_ops.add_variant` is unreachable and "+ Variant" silently dies.
  `data/CLAUDE.md` already states this as the reason every `ui` group is a
  parent-with-children. `walls` and `conditions` set the same precedent. **Zero
  schema change** — `$defs/group_node` already recurses.

- **D2 — `vfx.schema.json`'s `sprite_slot` enum becomes generated.** It is
  hand-typed and already stale: six keys against thirteen real slots. Add,
  remove and rename each break it, silently, in the direction that matters
  (a valid binding rejected, or a dangling one accepted). `tools/
  gen_sprite_slot_enum.py` already regenerates `core.schema.json`'s slot enum
  from the live `SlotRegistry`, with `tools/tests/test_schema_slot_sync.py` as
  the CI drift gate. Extend both rather than growing a second mechanism.
  **`trigger_row.procedural` is NOT generated** — a correction made during
  VA-1, which had planned to generate both. Its values name game-code kinds
  (`game/ui/effects.py::_run_procedural`'s if/elif ladder), not `procedural.*`
  balancing keys: `spark_place`/`spark_level`/`spark_tier` are spark PRESETS
  with no key of their own, and several `procedural.*` blocks (`floaters`,
  `projectile`, `drummer_aura`, …) are not one-shot kinds at all. Generating
  it from the balancing doc would rewrite the enum into something the shipped
  trigger rows fail against. The kind vocabulary is code-owned (D9); only the
  slot list is data.

- **D3 — Variants are spritesheet-only** (user's call). A procedural effect
  keeps its single param block. A "procedural variant" would mean N param sets
  per family, which multiplies the schema, the dataclasses and the preview by
  the variant count for a lever the designer did not ask for.

- **D4 — Level mode resolves to variant 0 where no source object is in hand**
  (user's call). Five of the ten events carry only a world point; only
  `building_destroyed`, `enemy_attack_melee` and `enemy_attack_ranged` hold the
  object (`watch_buildings`/`watch_enemies`). Widening `RunState.*_events` and
  the `resolve_combat` callbacks to thread a tier through is a real cost for a
  cosmetic lever, and the fallback is visible and explainable in the editor.

- **D5 — ONE `draw_in_front` bool, implemented as a depth-key rank, not a
  layer switch.** Buildings and enemies share the `entities` layer and sort by
  iso depth, so no layer choice can express "in front of buildings but behind
  enemies" — which is why there is one bool and not two. `depth_key` gains a
  fourth element: `(layer_index, wx+wy, wy, rank)`. Entities keep rank 0; an
  effect submits ±1. The effect stays on `entities`, so real iso depth survives
  — an effect on a near tile still draws over a building on a far one — and the
  bool decides only the same-tile tie, which is where front/behind is actually
  visible. Switching the effect to `deco`/`terrain` instead would discard iso
  depth entirely. The layer-primary invariant the ground cache depends on is
  untouched: layer is still element 0.

- **D6 — Procedural effects need a screen-pixel-sized, world-depth-sorted
  primitive: `WorldRect`.** Sparks, slashes and muzzle motes are `HudRect`s
  drawn dead last, so they cannot participate in D5 at all. `submit_world_fill`
  is the existing depth-sorted primitive but its polygon is world-space and
  scales with zoom — wrong for a particle, which is a fixed pixel size.
  `WorldRect` is `WorldFill`'s shape with a pixel rect instead of world points.

- **D7 — The tile highlights are CONTINUOUS, so they get their own dispatcher.**
  `_play` spawns a `PlayOnceVfx` with a despawn clock; a selection outline is
  drawn every frame for as long as the tile is selected. `_submit_highlight
  (event, col, row)` is its sibling: the bound slot's sheet as a looping
  `RenderItem` when it has art (the same `animation_total_ms(...) is not None`
  test every art-tolerant site uses), else the existing `submit_tile_diamond`.
  Forcing a highlight through `PlayOnceVfx` would respawn it every frame.

- **D8 — The three palette highlight colours MOVE to `vfx.json`; they are not
  copied.** `highlight`, `highlight2` and `range_highlight` are in
  `data/ui/palette.json` today. Leaving them there and adding them to `vfx.json`
  is two homes for one value (G-7) — the exact dead-data gap ESV-3a opened with
  `procedural.floaters` and ESV-6 had to close. `configure_palette` raises on a
  key-set mismatch, so removing them from `_PALETTE_KEYS` is loud, never silent.
  `C_MOVE_HIGHLIGHT`/`C_TUTORIAL_HIGHLIGHT` are bare code constants and move the
  same way.

- **D9 — The event vocabulary stays code-owned; bindings are open** (user's
  call). `triggers` keeps its closed, all-required schema; this plan adds eight
  keys to it and no mechanism for a designer to invent a ninth. An open registry
  would let a designer author a row nothing ever fires — inert data that looks
  live. `/add-vfx`'s `triggers_by_type` proposal is explicitly NOT adopted here.

- **D10 — Every trigger row ships `draw_in_front: true`.** That reproduces
  today's always-on-top behaviour exactly, so VA-3 is a visual no-op and nothing
  moves until a designer unticks a box. Same doctrine as ESV-1/ESV-3 landing
  byte-identical.

## 3. Package routing (read the ONE doc per phase)

| Phase touches | Read |
|---|---|
| `slots.json` restructure, vfx schema, balancing rows | `data/CLAUDE.md` |
| `depth_key`, `WorldRect`, `VfxSystem` | `engine/CLAUDE.md`, `engine/render/CLAUDE.md` |
| respawn ledger, highlight dispatcher, palette move | `game/CLAUDE.md`, `game/ui/CLAUDE.md` |
| registry ops, VFX panel | `editor/CLAUDE.md`, `editor/panels/CLAUDE.md` |

VA-2, VA-4 and VA-5 are cross-package — tell the user; they decide whether the
executing agent reads both docs.

## 4. Build order

| Phase | Scope | Package | Depends on | Status |
|-------|-------|---------|------------|--------|
| VA-1 | vfx slot restructure + generated schema enums | data + tools | — | **done** |
| VA-2 | `variant_select`/`draw_in_front` schema; resolver; `vfx_misc` | data + game | VA-1 | **done** |
| VA-3 | `depth_key` rank; `WorldRect`; `submit_world` | engine | — | todo |
| VA-4 | `building_respawn` trigger | game + data | VA-2 | todo |
| VA-5 | seven highlights → trigger-driven; palette move | game + data | VA-2, VA-3 | todo |
| VA-6 | `registry_ops` add/remove/rename; vfx variants | editor | VA-1 | todo |
| VA-7 | VFX panel roster/binding/variant/layer UI | editor | VA-6, VA-2 | todo |
| VA-8 | preview paths for the eight new families | editor | VA-4, VA-5, VA-7 | todo |

Ordering rule, inherited: **nothing changes visible behaviour until the piece
behind it is real.** VA-1 through VA-4 land as visual no-ops.

---

## VA-1 — Slot restructure + generated enums

**Goal.** The `vfx` category can host variants, and the schema's slot enum stops
being a hand-typed list that add/remove/rename would silently break.

**Files.** Modified: `data/slots.json` (the `vfx` category's `Effects` group
gains `children`, one leaf per effect, replacing the flat `slots` list — the
`vfx_crater` frame-size override rides along);
`tools/gen_sprite_slot_enum.py` (also regenerate `vfx.schema.json`'s
`$defs/trigger_row.sprite_slot` enum, plus the `procedural` enum from the live
`procedural.*` keys); `data/schemas/vfx.schema.json` (enums become generated
output); `tools/tests/test_schema_slot_sync.py`.

**Tests.** The registry still resolves all 13 slots and their frame sizes after
the restructure; `selection.variant_target()` now returns a target for a vfx
node; the generated `sprite_slot` enum equals the live vfx slot key set; the
drift gate fails on a hand-edited enum.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_registry.py tools/tests/test_schema_slot_sync.py -q` ·
Quick Test: `py editor/main.py`, open the VFX node — every effect still lists and
its art still resolves.

---

## VA-2 — Variant selection + the layering bool

**Goal.** A trigger row can say how to pick among a slot's variants, and whether
its effect draws in front of or behind the entities. Nothing reads the bool yet
(VA-3 does); the resolver picks variant 0 for every un-varianted slot, so this
lands as a no-op.

**Files.** Modified: `data/schemas/vfx.schema.json` (`$defs/trigger_row` gains
`variant_select` — `{mode: "random"|"level"|"misc", misc_key: string}` — and
`draw_in_front: boolean`, both required, D9's closed-object style);
`data/balancing/vfx.json` (all ten rows get `{"mode":"random","misc_key":""}`
and `draw_in_front: true`, D10); `game/ui/effects.py` (`_triggers_from_balance`
carries the two new fields; resolve the variant before `spawn_play_once`).
New: `game/vfx_misc.py` (`register(key, fn)` / `resolve(key) -> int`, unregistered
→ 0); a pure variant resolver beside it.

**Tests.** A slot with no variants resolves to itself under every mode; random
mode with an injected seeded rng picks deterministically from the family; level
mode clamps an out-of-range tier and returns variant 0 at an object-less event
(D4); an unregistered misc key returns 0 and never raises; the ten shipped rows
validate.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_vfx.py -q` ·
Quick Test: `py game/main.py` — every effect plays exactly as before.

---

## VA-3 — Depth rank + `WorldRect`

**Goal.** The render layer can express "this draws behind the thing on its tile"
for a fixed-pixel-size item. Byte-identical output until something passes a
non-zero rank.

**Files.** Modified: `engine/coords/system.py` (`depth_key(wx, wy,
layer_index=0, rank=0)` → 4-tuple); `engine/render/item.py` (`WorldRect`
beside `WorldFill`; `rank` field on the depth-participating items);
`engine/render/renderer.py` (`submit_world_rect`; the `flush` sort passes
`rank`); `engine/vfx/system.py` (`submit_world` beside `submit_hud`).

**Re-read `engine/render/` before starting** — `Development` gained
`backend_gpu.py`, `ground_cache_gpu.py`, `backend_api.py` and a
`flush(target, hud_target=…)` split since this plan's exploration. Both backends
must draw a `WorldRect`.

**Tests.** `depth_key` with default rank sorts identically to the 3-tuple on a
representative queue; equal-depth items order by rank; a rank never outranks the
layer (the ground-cache invariant); a `WorldRect` renders through both backends;
`VfxSystem.submit_world` emits the same rects `submit_hud` does, at the same
screen positions.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_render.py tools/tests/test_coords.py tools/tests/test_vfx.py -q` ·
Quick Test: `py game/main.py` — sparks, slashes and muzzle motes look unchanged.

---

## VA-4 — `building_respawn`

**Goal.** A building revived by payday plays an effect at its tile.

**Files.** Modified: `game/core/payday.py` (the slot-9 `b.rebuild()` loop
appends to a new ledger — the building and its tile are both already in scope);
`game/core/run_state.py` (`building_respawn_events`, the `painter_events` shape);
`game/main.py` (drain on the INCOME phase edge, beside `spawn_painter_events`);
`game/ui/effects.py` (`spawn_building_respawn_events` + the `_play` call);
`data/schemas/vfx.schema.json` + `data/balancing/vfx.json` (the trigger row and
a `procedural.respawn` block); `engine/vfx/params.py` (its dataclass — APPEND
only, and every direct `VfxParams(...)` construction needs the new argument:
`editor/vfx_params.py` and `tools/tests/test_vfx.py`'s `VFX_PARAMS`);
`data/slots.json` (a `vfx_respawn` effect group).

**Tests.** A payday that revives a building fills the ledger once per building;
a payday with `building_revive` off fills nothing; the drain plays the effect at
the building's tile and clears the ledger; with no art the procedural fallback
runs (E-37).

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_payday.py tools/tests/test_vfx.py -q` ·
Quick Test: `py game/main.py`, lose a building, reach a payday with revive
unlocked — the effect plays where it comes back.

---

## VA-5 — The seven tile highlights

**Goal.** `tile_selected`, `section_2x2`, `attack_range`, `move_target`,
`wall_edge`, `upgrade_batch` and `tutorial_highlight` become effects: tunable,
bindable to a spritesheet, and subject to the layering bool.

**Files.** Modified: `game/ui/effects.py` (`_submit_highlight`, D7);
`game/ui/building_ui.py` (`_highlight_tiles` entries carry the event name, not a
colour — the five fill sites and the `submit()` draw loop);
`game/main.py` (the tutorial and drag-select highlight sites);
`game/ui/widgets.py` (drop `C_MOVE_HIGHLIGHT`/`C_TUTORIAL_HIGHLIGHT` and the
three palette-backed keys from `_PALETTE_KEYS`, D8);
`data/ui/palette.json` (remove the three keys);
`data/schemas/palette.schema.json`; `data/schemas/vfx.schema.json` +
`data/balancing/vfx.json` (seven trigger rows + `procedural.highlights.*`);
`engine/vfx/params.py`; `editor/vfx_params.py`; `data/slots.json` (seven slots).

**Tests.** Each highlight draws with the colour from `vfx.json`, not a constant;
`configure_palette` still raises on a mismatched key set (the removal is
coordinated, not silent); a highlight with imported art draws the sheet and
without it draws the diamond; the 2×2 section still highlights the clicked tile
plus its three chunk siblings; `draw_in_front: false` puts a highlight behind a
same-tile building **asserted against the depth queue, not by reordering submits**
(reordering an overlay submit is a documented no-op).

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_vfx.py tools/tests/test_building_ui.py -q` ·
Quick Test: `py editor/main.py` retint the selection outline; `py game/main.py`
select a tile and a 2×2 section and see it.

---

## VA-6 — Add, remove, rename

**Goal.** The three verbs exist as pure ops, tested, before any UI calls them.

**Files.** Modified: `editor/registry_ops.py` — `add_vfx_effect(data_dir,
name)` (the `add_button_family` stack: slug derivation, validate-before-any-write,
`_append_child_group`), `remove_slot(data_dir, slot_key)` (refuse while bound in
any `triggers` row; drop the manifest entry; drop the leaf group when it empties;
unlink the PNG **only** when `asset_import.unreferenced_sheets` clears it),
`rename_slot(data_dir, old_key, new_key)` (rekey `slots.json` and the manifest
entry, rename `data/sprites/imported/<old>.png` and rewrite `sheet`, rewrite every
matching `triggers[*].sprite_slot`; validate the new key is free across the whole
registry first). `editor/main.py` (`"vfx"` into `_VARIANT_TARGETS`).

**Tests.** Add produces a schema-valid `slots.json` and a reachable variant
target; a duplicate name and a name that slugs to nothing both raise before any
write; remove refuses a bound slot; remove leaves a PNG that another slot links;
rename migrates all four references and is a no-op on a free-standing slot;
every op leaves the tree schema-valid; new modules join `TestPurity`.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_registry_ops.py -q` ·
Quick Test: drive the three ops from `py -c` against a temp data dir and diff the
JSON.

---

## VA-7 — The panel

**Goal.** The feature, visible: roster controls, trigger binding, variant-select,
layering bool.

**Files.** Modified: `editor/panels/vfx_preview.py` (roster strip with the
live-slug dialog and confirm-before-delete — **wrap the delete connect in a
lambda**, `clicked(bool)` lands in `confirm=` and skips the dialog; a
trigger-binding row; mode combo + misc key field + misc value scrubber; the
`draw_in_front` checkbox); `editor/main.py` (wiring + `_reload_registries()`
after each registry op); `tools/tests/test_vfx_preview.py`.

**Re-read `vfx_preview.py` first** — it gained 205 lines on `Development` since
this plan's exploration.

**Tests** (offscreen Qt, temp data dir): each roster control calls its op with
the right arguments and refreshes the tree; delete asks first; a mode change
stages into `vfx.json` and does not write; the misc scrubber changes the preview
without touching data; `TestPurity` covers every new module.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_vfx_preview.py -q` ·
Quick Test: the five live steps in §6.

---

## VA-8 — Preview the new families

**Goal.** Respawn and the seven highlights render live in the preview instead of
the E-37 placeholder.

**Files.** Modified: `editor/panels/vfx_preview.py` (preview paths beside
`_EMIT_FAMILIES`/`_POINT_FX_FAMILIES`); `tools/tests/test_vfx_preview.py`.

**Tests.** Each of the eight families selects without the placeholder and
requests the engine emitter/primitive with the staged params (assert the params,
never pixels); an unknown family still degrades to the placeholder.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_vfx_preview.py -q` ·
Quick Test: `py editor/main.py`, step the family combo through all eight.

---

## 5. Risks / open items

- **The palette split (D8)** removes three colours from the editor's theme
  screen. The alternative — leave them in `palette.json` and have the VFX panel
  write palette values — is a cross-domain write from a panel that today has
  zero writers. Flagged to the user at plan time; revisit only if they ask.
- **Moving particles into the depth queue (D6)** is the largest visual-regression
  risk here. D10's `draw_in_front: true` default is the guard: nothing moves
  until a box is unticked.
- **`VfxParams` is append-only with no defaults.** Eight new families is eight
  coordinated edits across `engine/vfx/params.py`, `editor/vfx_params.py` and
  `tools/tests/test_vfx.py`'s fixture. It breaks loudly at construction, which
  is the design — but ESV-6 and two later features each hit it, so expect it.
- **The 2×2 "outline" is four diamonds**, not a perimeter. Nothing in the game
  draws a true 2×2 perimeter (only the editor does, for `start_area`, via raw
  `submit_overlay_lines`). If the designer wants a real perimeter that is a new
  primitive and a new phase.
- **Editor-tier tests are flaky under the gate's parallel workers** — an ESV
  open item, not caused here, but VA-7/VA-8 land in exactly those modules.
- **`tools/tests/fixtures/data/` is stale** (an ESV open item). VA-1 changes
  `slots.json`'s shape, so the vfx part of the fixture must be mirrored
  deliberately.

Test policy for every phase is root `CLAUDE.md` §"Test Suite Policy" and nothing
else. The single full `py tools/testgate.py check` happens ONCE, in the main
session, at `/commitpushpr` stage 5 — after the PR is up and after `Development`
has been merged down.

## 6. Live acceptance (the whole plan, end to end)

1. `py editor/main.py` → VFX node → **Add effect** "Shockwave" → `vfx_shockwave`
   appears in `slots.json` and the tree. **Add variant** → `_v2`.
2. Import a sheet into it; **Rename** to `vfx_ripple`; confirm the PNG, the
   manifest entry and the trigger binding all followed.
3. Bind `building_respawn` to it, set **random**, untick **draw in front**.
4. `py game/main.py` → let a payday revive a building → the effect plays at its
   tile and passes **behind** the building.
5. Select a tile and a 2×2 section → both outlines render from `vfx.json`.
   Retint them in the editor and see it in game.
6. Delete `vfx_ripple` while still bound → refused with a message. Unbind,
   delete → gone, and a shared PNG survives if another slot links it.
