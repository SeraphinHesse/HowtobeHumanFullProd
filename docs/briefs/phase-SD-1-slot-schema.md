# Phase SD-1 — Slot schema + balancing subtrees (data)

Source plan: `planning/SoundEditorPLAN.md` §2.1 (slot shape), §2.2 (buses),
§2.3 (the 21-row checklist→slot map), §3 (build order, `SoundEditorPLAN.md:204`).
Package doc to read first: `data/CLAUDE.md`. Skill to open with:
`/add-balancing-value` (this phase is a large, structured instance of exactly
that task — never hand-edit `data/balancing/*.json`; go through the validating
writer).

**Goal**: the data model exists and validates. No engine, no editor, no sound.
SD-1 gates SD-2 – SD-7; every other phase reads key paths this phase creates,
so the paths in §3 are a contract, not a suggestion.

---

## 1. Behavioral spec

### What exists today (all cited, none assumed)

- There is **no audio schema and no sound data**. `data/audio/` holds exactly
  one file, `Bass_and_drum_Duo.wav` (~49 MB), and no JSON *(verified: `ls
  data/audio/`)*. Nothing in `.gitignore` mentions `audio` *(verified: `grep -rn
  "audio" .gitignore` returns nothing)* — **imported clips are committed
  content** (D-31, `SoundEditorPLAN.md:231`); do not add an ignore rule.
- The five domains this phase touches are closed documents: every one ships
  `additionalProperties: false` at every object level with a **full `required`
  list** (`data/CLAUDE.md:537-546`). *Verified* top-level shapes:
  - `core`: properties == required == `Camera, Debug, EnemyIntro, General,
    LightningStrike, PhaseLoop, Seasons, TheHole, Tutorial, XP`
    (`data/schemas/core.schema.json:983`).
  - `ui`: properties `BuildingColors, Debug, FX, Keybindings, Menu, Timing`;
    required omits `BuildingColors` (`data/schemas/ui.schema.json:353`).
  - `map`: `Pathfinding, SpawnDeco, TileConditions, TileUnlocking`
    (`data/schemas/map.schema.json:478`).
  - `buildings`: `BoostBuildings, BuildingsGlobal, DefenceBuildings,
    EconomyBuildings, StructureBuildings`
    (`data/schemas/buildings.schema.json:1238`); `BuildingsGlobal` currently
    holds `Movement, defence_range_pathfinding, random_names, xp_on_death`
    (`data/schemas/buildings.schema.json:1246`).
  - `enemies`: `CrowdSpacing, EnemyScaling, EnemyTypes, MortarTargeting`
    (`data/schemas/enemies.schema.json:478`-equivalent top-level `required`);
    `EnemyTypes` has exactly ten entries — `Boss, Commander, Digger, Drummer,
    Formation, Raider, SiegeCannon, Sniper, Standard, Tutorial`
    (`data/schemas/enemies.schema.json:674`, D7 of the plan).
- **`oneOf` and type-less schema nodes are banned** — a type-less node crashes
  the editor's balancing panel for the whole domain
  (`data/CLAUDE.md:509-512`, restated at `SoundEditorPLAN.md:113-115`). This is
  why the trim sentinel is `end: 0.0`, **never `null`** (`SoundEditorPLAN.md:149-150`).
- **Local `#/$defs/` refs only; cross-file `$ref` is forbidden**
  (`data/CLAUDE.md:537-541`, and the sibling case at `data/CLAUDE.md:24`, where
  `balancing/ui.json`'s `Keybindings` re-declares `keybindings.schema.json`'s
  property set BY HAND for exactly this reason). Hence the `$defs` block is
  **duplicated into all five domain schemas and pinned identical by a generator
  + drift test** (`SoundEditorPLAN.md:116-119`).
- **The precedent to copy** is `tools/gen_sprite_slot_enum.py` +
  `tools/tests/test_schema_slot_sync.py`: a headless, deterministic, idempotent
  generator that loads each schema with `json.loads`, mutates the `$defs`
  in place, and rewrites it through `engine.data_io.dumps_deterministic`
  (`tools/gen_sprite_slot_enum.py:65-81`, docstring `:30-33`), plus a test that
  compares the committed schema against a freshly computed value and fails with
  a "re-run the generator" message (`tools/tests/test_schema_slot_sync.py:36-48`).
- **D-12 is enforced by tests, not convention** — every typed leaf at any depth
  needs a `description` (`tools/tests/test_balancing_data.py:99-110`) and every
  `integer`/`number` leaf needs both `minimum` and `maximum`
  (`tools/tests/test_balancing_data.py:111-123`). The walker resolves local
  `#/$defs/` refs (`tools/tests/test_balancing_data.py:33-53`), so the new
  `$defs` are walked once per reference site — a missing `description` on
  `sound_clip.file` fails five domains at once. `data/CLAUDE.md:552` states the
  bounds policy (fractions 0–1, seconds 0–60, …).
- **Files must be byte-canonical on disk** — `test_files_are_canonical_on_disk`
  (`tools/tests/test_balancing_data.py:88-97`) compares each schema AND each
  balancing doc against `dumps_deterministic` of its own content. Keys are
  sorted by the writer (`engine/data_io.py:76,81-87`), so **you never choose an
  insertion position**: add the key, write through the writer, done.
- **`x-widget` must live INSIDE the `$def`, not beside the `$ref`.** *Verified*:
  `editor/panels/balancing.py:370` does `prop = self._deref(prop)` at the top of
  the property loop, and `_deref` (`editor/panels/balancing.py:335-341`)
  *replaces* the node with the `$defs` target — any sibling key written next to
  a `$ref` is silently discarded before `x-paired` (`:371`) or any other
  extension is read. SD-3's `x-widget: "sound_slot"` interception at
  `_build_object:361` therefore only fires if the marker is a property of
  `$defs/sound_slot` itself. Getting this wrong produces a phase that passes its
  own tests and silently breaks SD-3.
- The balancing panel skips schema keys absent from the document
  (`editor/panels/balancing.py:368-369`, `if key not in value: continue`) —
  which is why every slot must be **present and required in the JSON**, empty
  rather than missing (`SoundEditorPLAN.md:153-156`).
- **Existing history snapshots need no migration.** `data/balancing_history/*.json`
  validates against `schemas/balancing_history.schema.json`, whose `snapshot` is
  a deliberately unconstrained `{"type": "object"}`
  (`data/schemas/balancing_history.schema.json:24-27`; rule at
  `data/CLAUDE.md:36-44`) — 30 committed `buildings` snapshots stay valid.
- Game-side loading is generic (`game/core/balance.py:20 load_balance`,
  `:29 load_all`) — no code enumerates domain top-level keys, so adding
  `Sounds` breaks nothing at runtime *(verified)*.
- `tools/smoke.py:25 validate_data` validates every `data/**/*.json` against its
  stem-paired schema, so the five edited pairs are covered by the smoke run.

### Required behavior after this phase

1. Both `$defs` blocks (`sound_clip`, `sound_slot`) exist, **byte-identical**,
   in all five domain schemas, produced by `tools/gen_sound_slot_defs.py`.
2. Every slot path listed in §3 exists in the schema and in the content doc,
   with the empty value `{"clips": [], "loop": false, "pick": "random"}`
   (`loop: true` for the six looping slots — all five `core.Sounds.Music.*` and
   `core.Sounds.Ambient.default` — marked in the §3 tables).
3. `py tools/smoke.py` validates all five pairs; the D-12 walks pass; the docs
   are canonical on disk.
4. Nothing else changes: no engine code, no editor code, no `.gitignore` entry,
   no clip files imported.

---

## 2. Architecture plan

### 2.1 The two `$defs` (canonical text lives in the generator)

`tools/gen_sound_slot_defs.py` owns the ONE literal definition of both blocks
as module-level dicts, exactly as `gen_sprite_slot_enum.py` owns its enum
computation. Shape (schema, not content):

```
$defs/sound_clip   type: object, additionalProperties: false
  required: [file, volume, start, end]
  file    string   description: "Path relative to data/audio/ (e.g.
                   'imported/building_death_a.ogg'). Empty string = no clip."
                   (no minLength — "" is legal)
  volume  number   0.0 .. 1.0, multiplied by the bus volume and master volume
  start   number   seconds; 0.0 = from the beginning
  end     number   seconds; 0.0 is the SENTINEL for "play to the end"
                   (deliberately not null — data/CLAUDE.md:509-512)

$defs/sound_slot   type: object, additionalProperties: false
  x-widget: "sound_slot"        <-- inside the $def; see §1 (balancing.py:370)
  required: [clips, loop, pick]
  clips  array of {"$ref": "#/$defs/sound_clip"}, minItems 0, NO maxItems
         description states the two-layer semantics: [] on a GLOBAL default
         = silence; [] on an ELEMENT override = inherit the default.
  loop   boolean
  pick   string, enum EXACTLY ["random", "sequential"]
```

Bounds to use: `volume` 0.0–1.0 (the fractions rule, `data/CLAUDE.md:552`);
`start`/`end` **0.0–3600.0** — a **deliberate, orchestrator-approved deviation**
from the same line's "seconds 0–60" convention, which was written for VFX
timings, not audio: `core.Sounds.Music.*` clips run minutes
(`Bass_and_drum_Duo.wav` alone is 49 MB). **This is decided, not open — a
reviewer must not flag it as a bug.** Say so in the `description` of both
fields, so the deviation is documented where a reader meets it.

Every slot *site* is written as `{"$ref": "#/$defs/sound_slot", "description":
"<what this sound is>"}`. The per-site `description` is for the human reading
the schema; note that `_deref` drops it in the editor form, so it is
documentation only, and the panel's tooltip comes from the `$def`'s own
description — write a useful one there too.

### 2.2 The generator

`tools/gen_sound_slot_defs.py`, modelled on `tools/gen_sprite_slot_enum.py`:

- module docstring explaining WHY the block is duplicated (no cross-file `$ref`,
  `data/CLAUDE.md:537-541`) and naming its drift test;
- `SOUND_CLIP_DEF` / `SOUND_SLOT_DEF` module constants (or a
  `sound_slot_defs()` function returning both — the drift test imports this);
- `DOMAINS = ("buildings", "core", "enemies", "map", "ui")`;
- `apply(schema_path)`: `json.loads` → `schema["$defs"]["sound_clip"] = …`,
  `schema["$defs"]["sound_slot"] = …` → write
  `data_io.dumps_deterministic(schema)`. Note `ui.schema.json` and
  `map.schema.json` currently have **no `$defs` key at all** *(verified: empty
  `$defs` list for both)* — the generator must create it;
- `main(argv=None)` with `--data-dir`, printing one line per schema;
- headless, deterministic, **idempotent** — running it twice is a no-op.

The generator writes `$defs` ONLY. Slot sites, `Sounds` subtrees, `required`
lists and the content documents are hand-authored in this phase (they are
one-time structure, not a derived list) — the generator exists so the
*duplicated* block can never drift.

### 2.3 Writing the content

Author the five `data/balancing/*.json` edits through
`engine.data_io.write_validated` (`engine/data_io.py:81`) — a short throwaway
script under the scratchpad, or the `/add-balancing-value` path. Never hand-type
JSON into the domain files: the writer validates before touching disk and
formats canonically, which is what `test_files_are_canonical_on_disk` checks.

Order of work (each step leaves the tree validating):
1. generator + run it → five schemas gain `$defs`;
2. schema `Sounds` subtrees + `sounds` blocks + `required` updates, one domain
   at a time;
3. content subtrees, same order;
4. `tools/tests/test_sound_slots_data.py`.

---

## 3. File scope + shared-file contract

### New files (owned entirely by SD-1)

| Path | Contents |
|---|---|
| `tools/gen_sound_slot_defs.py` | the canonical `$defs/sound_clip` + `$defs/sound_slot`, and the writer that stamps them into the five schemas |
| `tools/tests/test_sound_slots_data.py` | the drift test + the slot-path/validation tests in §4 |

### Modified files

| Path | Change |
|---|---|
| `data/schemas/core.schema.json` | `$defs` (generated) + `Sounds` subtree + `required` += `Sounds` |
| `data/schemas/ui.schema.json` | `$defs` (created) + `Sounds` subtree + `required` += `Sounds` |
| `data/schemas/map.schema.json` | `$defs` (created) + `Sounds` subtree + `required` += `Sounds` |
| `data/schemas/buildings.schema.json` | `$defs` (generated) + `BuildingsGlobal.Sounds` + `sounds` on all 12 leaf families + `required` updates |
| `data/schemas/enemies.schema.json` | `$defs` (generated) + top-level `EnemySounds` + `sounds` on all 10 `EnemyTypes` + `required` updates |
| `data/balancing/{core,ui,map,buildings,enemies}.json` | the matching subtrees, every slot empty |

**Out of scope, explicitly**: `.gitignore` (clips are committed content, D-31),
`data/schemas/ui_screen.schema.json` (the per-widget `sound` override is
**SD-6**), `engine/**`, `editor/**`, `game/**`, `requirements.txt`,
`data/audio/**` (no clip is imported in this phase), `data/balancing/vfx.json`
/ `progression.json` / `boss_upgrades.json` (no sound slots).

### The contract — exact key paths downstream phases read

Every path below is a `#/$defs/sound_slot` object. Downstream phases index these
strings literally; do not rename, nest differently, or "tidy" them.

**`data/balancing/core.json` → `Sounds`** (read by SD-7, and by SD-6 for buses)
```
core.Sounds.Music.default            loop: true
core.Sounds.Music.building_phase     loop: true   (D4 override of .default)
core.Sounds.Music.combat_phase       loop: true   (D4 override of .default)
core.Sounds.Music.menu               loop: true
core.Sounds.Music.cutscene           loop: true
core.Sounds.Ambient.default          loop: true   (SFX bus, D6)
core.Sounds.Game.game_start          loop: false
core.Sounds.Game.round_start         loop: false
core.Sounds.Game.round_win           loop: false
core.Sounds.Game.round_loss          loop: false
core.Sounds.Game.level_up            loop: false
core.Sounds.Game.game_over           loop: false   (NEW — see below)
```
`Sounds` is an object with required children `Ambient`, `Game`, `Music`;
`Ambient` has the single required child `default`.

**`Ambient.default`, NOT `Ambient.loop` — orchestrator decision, and a
deliberate deviation from `planning/SoundEditorPLAN.md:174`**, which names the
slot `Ambient.loop`. That name produced the doubled path
`core.Sounds.Ambient.loop.loop` (a *slot* named `loop`, whose slot object also
carries a `loop` boolean). SD-1 is the only phase that can fix it, because
SD-2/SD-7 hard-code the path; SD-7 has been told the same. Use `default`
everywhere — schema, content, tests.

**`core.Sounds.Game.game_over` is NEW** and is not in `SoundEditorPLAN.md`'s
§2.3 table: the user decided the game-over screen gets its own sting rather
than holding the combat track. It is an ordinary `$defs/sound_slot` shipping
`{"clips": [], "loop": false, "pick": "random"}`, exactly like its five `Game`
siblings. SD-1 only creates it; SD-7 fires it on the game-over edge.

**`data/balancing/ui.json` → `Sounds`** (read by SD-6)
```
ui.Sounds.button_click               loop: false
ui.Sounds.not_enough_love            loop: false
```
`ui.Sounds` is **CLOSED to exactly these two keys** — `additionalProperties:
false`, `required: [button_click, not_enough_love]`, and **not** an extensible
`additionalProperties: {$ref: …}` map. Confirmed with SD-6, which owns the
per-widget override: a button that needs its own click sound gets an optional
`sound` key on the per-widget override object in
`data/schemas/ui_screen.schema.json` (SD-6's file, not SD-1's), never a new key
here.

**`data/balancing/map.json` → `Sounds`** (read by SD-4)
```
map.Sounds.buy_plot                  loop: false
map.Sounds.tile_placement            loop: false
```

**`data/balancing/buildings.json`** (read by SD-4). Six event keys, the SAME six
everywhere — global defaults under `BuildingsGlobal.Sounds`, per-family
overrides under `<Group>.<Family>.sounds`:
```
buildings.BuildingsGlobal.Sounds.{placement, selection, upgrade, death, attack, upkeep_boost}
```
and `sounds` with those same six keys on **all twelve leaf families**
*(verified against `data/balancing/buildings.json`; the count is pinned by
`tools/tests/test_balancing_data.py:220`)*:
```
BoostBuildings.{Damage, HP, Speed}.sounds.*
DefenceBuildings.{AOEDefence, BasicDefence, BeamDefence, StormPriest}.sounds.*
EconomyBuildings.{Meditators, Musicians, Painters}.sounds.*
StructureBuildings.{Blocker, WallBuilder}.sounds.*
```
`sounds` goes on the **leaf family** blocks (the ones carrying `building_type`),
NOT on the `globals` sub-objects of `BoostBuildings` / `DefenceBuildings` — a
`globals` block is a group-level tunable bag, and adding a second override layer
there would give SD-4 an ambiguous resolution order. Add `sounds` to each
family's `required`, and `Sounds` to `BuildingsGlobal.required`.
Economy buildings never attack; their `attack` slot ships **present but empty**
and therefore silent (`SoundEditorPLAN.md:197-198`, orchestrator-confirmed) —
the six event keys are uniform across all twelve families.

**The capital/lowercase split is DELIBERATE, not a typo.** The global block is
`BuildingsGlobal.`**`Sounds`** (capital S) and the per-family override is
`<Family>.`**`sounds`** (lowercase s). It follows the domain's existing
convention, which SD-4 reads literally on both sides: `buildings.schema.json`
already spells group/section containers in PascalCase (`BuildingsGlobal`,
`DefenceBuildings`, `Movement`) and per-element tunable keys in snake_case
(`building_type`, `card_slots`, `starts_unlocked`, `xp_on_death`) — the same
split `enemies.json` uses for `EnemySounds` (top-level defaults, PascalCase)
versus `EnemyTypes.<Type>.sounds` (per-element, lowercase). A reviewer will
challenge this; the answer is that it is intentional, mirrored in enemies, and
SD-4/SD-5 index both spellings verbatim. Do not "normalise" either one.

**`data/balancing/enemies.json`** (read by SD-5). Three event keys:
```
enemies.EnemySounds.{death, attack, spawn}                  <- NEW top-level key, the defaults
enemies.EnemyTypes.<Type>.sounds.{death, attack, spawn}     <- per-type override, D7
```
for all ten `<Type>` values *(verified list)*: `Boss, Commander, Digger,
Drummer, Formation, Raider, SiegeCannon, Sniper, Standard, Tutorial`. The three
checklist boss rows and the cannon row resolve to
`EnemyTypes.Boss.sounds.{spawn, attack, death}` and
`EnemyTypes.SiegeCannon.sounds.attack` (`SoundEditorPLAN.md:190-192`) — they need
no extra keys, only the uniform per-type block. `EnemySounds` joins the
top-level `required` list; `sounds` joins each type's `required`.
SD-5 resolves the type key via the existing `registry_group` field, never by
string convention (`data/schemas/enemies.schema.json:663-667`,
`data/CLAUDE.md:405-420`) — SD-1 adds nothing for that.

**Every slot ships as** `{"clips": [], "loop": <false|true per the tables>,
"pick": "random"}`. `clips: []` on a global default means silence; `clips: []`
on an element override means inherit — the difference is documented in the
`$def`'s description and is SD-2's `bank.resolve` contract
(`SoundEditorPLAN.md:153-156, 256-258`).

**Bus assignment is positional, not a data field** (`SoundEditorPLAN.md:158-168`):
`core.Sounds.Music.*` is the music bus; *everything else, including
`core.Sounds.Ambient.loop`*, is the sfx bus. Do NOT add a `bus` key — SD-2
derives it from the path.

**Marker contract for SD-3**: `x-widget: "sound_slot"` is a property of
`$defs/sound_slot` itself. SD-3's `_build_object` interception
(`editor/panels/balancing.py:361`) reads it AFTER `_deref` (`:370`), so this
placement is load-bearing. Do **not** also write `x-widget` beside the
`$ref` at each site; it would be dead text.

**Deliberately NOT added in SD-1**: `x-array-editable` on `clips`. The generic
panel's array +/- Row machinery is not the interface designers get — SD-3's
`SoundSlotWidget` owns clip add/remove. Until then `clips` renders as an empty
collapsible section, which is the expected SD-1 Quick Test appearance.

---

## 4. Exit gate + Quick Test

### Exit gate (run exactly these; nothing else)

```
py tools/smoke.py
py -m pytest tools/tests/test_sound_slots_data.py -q
py -m pytest tools/tests/test_balancing_data.py -q
```

`test_balancing_data.py` is in the gate because it is the file that enforces
D-12 (`:99`, `:111`) and canonical-on-disk (`:88`) over the exact five documents
this phase edits — it is a *targeted* run over this phase's files, which is what
a subagent may run. **Do not run the full suite, `py tools/testgate.py check`,
`--affected`, or a tier sweep (`-m core` / `-m editor` / `-m meta`)** — the
`test_guard.py` hook denies all four from a subagent, and the single full gate
belongs to the main session at handoff (root `CLAUDE.md`, §"Test Suite Policy",
is the only authority).

### What `tools/tests/test_sound_slots_data.py` must cover

(from `SoundEditorPLAN.md:233-238`, tests kept minimal — assert the contract,
not the implementation)

1. **Drift**: for each of the five schemas, `$defs["sound_clip"]` and
   `$defs["sound_slot"]` equal the generator's canonical dicts, and all five are
   equal to each other — failing with a "re-run `py tools/gen_sound_slot_defs.py`"
   message (copy the wording style of
   `tools/tests/test_schema_slot_sync.py:44-48`).
2. **Generator idempotence**: applying it to a temp copy twice yields
   byte-identical output.
3. **Every §3 slot path exists** in both schema and content, as a table of
   literal path strings in the test — **12** core (5 `Music` + 1 `Ambient` +
   **6** `Game`, `game_over` included) + 2 ui + 2 map + 6 global building +
   12×6 family + 3 `EnemySounds` + 10×3 enemy-type paths = 129. Assert
   `core.Sounds.Ambient.default` and assert `core.Sounds.Ambient.loop` is
   ABSENT, so the rename cannot silently regress.
4. **Validation, positive**: an empty slot validates; a slot with two clips
   validates; `pick: "sequential"` validates.
5. **Validation, negative** (`jsonschema.ValidationError` each): `volume: 1.5`;
   an unknown key inside a clip; `end: null`; `pick: "first"`.
6. **`pick`'s enum is exactly `["random", "sequential"]`.**
7. **No node the phase added is type-less or uses `oneOf`** — walk both `$defs`
   and every `Sounds`/`sounds` subtree in the five schemas and assert each
   object/leaf node carries a `type` (or is a pure `{"$ref"}` site) and that
   `"oneOf"` appears nowhere in them (`data/CLAUDE.md:509-512`).

Tests must not write into `data/` — copy to a tempdir (`TempDataCase`); a
session fixture hashes `data/` and fails the run if it changed
(`SoundEditorPLAN.md:479-481`). No clip is decoded here, so `DECODES_MEDIA`
(`tools/tests/temp_data.py:119`) is not needed.

### Quick Test (in-game / in-editor — run by the orchestrator or the user)

```
py editor/main.py
```
→ open the **Balancing** panel → select `buildings` → expand
`BuildingsGlobal → Sounds` and `DefenceBuildings → BasicDefence → sounds`:
each of the six event sections renders as a plain nested form (a `clips`
collapsible section that is empty, a `loop` checkbox, a `pick` text/enum field —
the composite widget is SD-3), and the domain does **not** blank out or throw.
Repeat for `core` (`Sounds → Music → default`, `Sounds → Ambient → default`,
`Sounds → Game → game_over`), `ui`, `map` and `enemies`
(`EnemySounds` and `EnemyTypes → Boss → sounds`). Then Save Balancing Changes
once on `core` and confirm `data/balancing/core.json` round-trips unchanged
apart from the history append. A domain that renders empty or raises is the
type-less/`oneOf` failure mode described above.

### Decisions already taken (do not re-litigate)

Three questions this brief originally raised are **closed by the orchestrator**;
they are recorded here so a reviewer sees the ruling next to the deviation.

1. **`start`/`end` bounds = 0.0–3600.0 s.** APPROVED deviation from
   `data/CLAUDE.md:552` ("seconds 0–60" was written for VFX timings, not
   audio). See §2.1.
2. **The ambient slot is `core.Sounds.Ambient.default`**, not the plan's
   `Ambient.loop` (`SoundEditorPLAN.md:174`) — the doubled `Ambient.loop.loop`
   path is fixed here because SD-2/SD-7 hard-code it. SD-7 is aligned.
3. **`attack` exists on the economy families**, shipping empty and therefore
   silent (`SoundEditorPLAN.md:197-198`). The six event keys are uniform across
   all twelve families; no family-specific key set.

Also confirmed by the sibling briefs, and therefore load-bearing here:
`x-widget` inside `$defs/sound_slot` (SD-3 depends on it, §1/§3);
`enemies.EnemySounds.spawn` as a global default (SD-5 reads it);
the `Sounds`/`sounds` case split (SD-4 reads both, §3);
`ui.Sounds` closed to exactly two keys (SD-6 owns the per-widget override).

### Open question remaining

1. **`editor/balancing_history.py` restore**: an old snapshot restored after
   this phase lacks the `Sounds` keys and will fail `write_validated`. Committed
   snapshots stay *valid as history* (`snapshot` is an unconstrained object,
   `data/schemas/balancing_history.schema.json:24-27`), so nothing breaks today —
   but restoring a pre-SD-1 snapshot is a known sharp edge. Out of scope for
   SD-1; flagged so it is not discovered as a bug in SD-3.
