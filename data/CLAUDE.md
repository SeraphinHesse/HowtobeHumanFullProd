# CLAUDE.md — DATA package

Self-contained guide for `data/` — the single source of truth every other
package reads. Requirements: SPEC.md §5 (`D-*`). **When you change a format or
schema, update THIS doc.**

**Adding or changing a balancing tunable? Use the `/add-balancing-value` skill**
— it keys into `balancing/<domain>.json` + the schema mirror through the
validating writer; don't hand-edit the JSON.

## What lives here
- `schemas/` — one JSON Schema per file type.
  `dispatch_handoff.schema.json` is the ONLY schema with no `data/` content file
  at all (handoffs are written to the gitignored `.claude/dispatch/`, still
  through `write_validated` — the single write path holds), which is legal:
  `tools/smoke.py::validate_data` skips `data/schemas/` entirely. Three others
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
  `data/balancing/vfx.json` content, not to its schema. Since **Phase 9A** the other
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
- **Enemy sizing leaves (ER-1)**: each `enemies.json` `EnemyTypes/*` block carries
  a required `footprint` (int tiles, 1–8: the unit occupies footprint² tiles and
  its sprite is downscaled to `footprint*tile_w` wide, never upscaled) and
  `sprite_scale` (number 0.1–8, applied AFTER that fit — the knob for low-res
  art). The dead `Boss/era_sizes` and the `sprite_w`/`sprite_h` on every
  `Boss/stats` row were deleted from content AND schema in the same change:
  nothing read them, and render size now derives from the footprint.
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
  D-3 sorted-keys dumps and IS the editor tree order; the first five keys
  mirror the D-10 domains, then asset-only `vfx`/`deco`/`backgrounds`), each with
  `key/display_name/frame_w/frame_h/animations/groups`. `animations[0]` is
  always `idle` (schema-enforced). `groups` is a recursive tree of
  `{label, slots[] XOR children[]}`; a slot key may repeat across groups of
  ONE category (meditators reuse musician art) but never across categories
  (frame size would be ambiguous — loader rejects it).
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
  buttons (action/boss/close/preview_*/rename_dice/lightning/boss_close) ·
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
  block — `widgets.COND_LABELS` and every other inline color literal in
  `game/ui` stay code, deliberately out of scope.
- **Parity is the safety net for both files**: the committed content is
  today's hardcoded values verbatim, and `tools/tests/test_theme_data.py`
  pins that (a) configuring from the stock fixture doc reproduces
  `test_ui_skinning.py`'s golden baseline byte-for-byte, and (b) the
  UNCONFIGURED module defaults (the fallback bare construction uses) equal
  that same fixture — the two value sets can never silently drift apart.
- **`ui_screen.schema.json` widget `tint` (D6)**: one new key in the
  per-widget override object, same 3-4-int-array shape as `color` — like
  every other widget override key (`rect`/`skin`/`font`/`label`/`color`/
  `text_color`/`visible`), it is absent-by-default (the object carries no
  `required` array: a widget's override is always a PARTIAL patch, never a
  full record). A skinned widget's `tint` multiplies its sheet at draw time
  (`engine/render/CLAUDE.md`'s nine-slice/`BLEND_RGBA_MULT` section);
  omitted = unchanged, so an existing screen doc that predates `tint` keeps
  validating and rendering exactly as before.

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
  format has NO spawn-point objects.
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
