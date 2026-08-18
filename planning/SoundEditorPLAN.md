<!-- status: NOT STARTED — SD-1–SD-7 -->

# SoundEditorPLAN.md — Sound slots in balancing, audio in the game

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`VfxAuthoringPLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/SoundEditorPLAN.md SD-1-SD-7` or phase-by-phase.

**Source**: `Sound checklist.md` (21 sound rows) plus the scoping session of
2026-08-18. This document **replaces** an earlier draft of the same name that
designed a central `data/audio/sound_bank.json` and a separate editor **Sound**
menu. That design is dropped: sounds belong *inside the balancing of the element
that makes them*, not in a bank off to the side.

## 1. Vision

Every sound in the game is a **slot inside the balancing of the thing that makes
it**. Open `buildings` in the editor's balancing form and each building family
has a **Sounds** section: placement, selection, upgrade, death, attack,
upkeep/boost. Each slot is a composite widget — *Import…* / *Use existing…*, a
clip list (several clips = random variation), per-clip volume and in/out trim, a
loop toggle, and a ▶ preview. Global defaults sit on the domain's globals; a
per-element slot left empty **inherits the default**, so one imported clip
covers everything until you want a specific one.

The game never names an audio file. It calls `sfx.play(...)` with a resolved
slot; the resolver walks **element override → global default → silence**.

Today there is effectively **no sound system** to build on *(all verified in the
`SoundEditor` worktree, 2026-08-18)*:

- `engine/audio.py:15,27,35` — three functions (`play_music` / `stop_music` /
  `set_volume`). Music only. No `pygame.mixer.Sound` anywhere in the repo.
- `game/main.py:67,999` — one hardcoded boot track.
- `game/ui/cutscene_player.py:16,69` — cutscene companion audio; it uses the
  same `music` channel and nothing restores the previous track (`:67`).
- `game/ui/settings.py:71` — `volume: float = 0.8  # inert (no audio system)`,
  drawn at `:112-113,229-235` with the label `"(no audio yet)"`.
- No audio schema. `data/audio/` holds one 49 MB `.wav` and no JSON.

### Scoping decisions (taken with the user)

- **D1 — Global default + per-element override.** Untouched elements inherit;
  no phantom copies. (Rejected: global-only, which forecloses per-building and
  per-enemy variation; per-element-only, which makes every element silent until
  individually filled.)
- **D2 — Slots live inside the existing balancing domains** (`core` / `ui` /
  `map` / `buildings` / `enemies`), not in a new bank file. This is the whole
  point: the sound sits with the thing it belongs to, and the editor's existing
  schema-driven balancing form, save path, and history come for free.
- **D3 — Per-slot features**: preview ▶ button, random variation (several clips
  per slot), in/out trim, loop toggle — on top of file + volume.
- **D4 — Music**: a **default** music slot with **building-phase** and
  **combat-phase** overrides, plus **menu** and **cutscene** slots. **Ambient is
  a separate slot**, not part of music.
- **D5 — Button click**: a global default plus a per-button override, carried by
  the existing per-widget override object in `data/ui/screens/*.json` (which
  already takes optional `font` / `skin` / `tint` / `text_id` patches — see
  `data/schemas/ui_screen.schema.json:46,110,127`).
- **D6 — Settings gets Master + Music + SFX sliders**, replacing the inert one.
  **Ambient plays on the SFX bus.**
- **D7 — Enemy overrides are per enemy type** — the ten `EnemyTypes` entries
  (Boss, Commander, Digger, Drummer, Formation, Raider, SiegeCannon, Sniper,
  Standard, Tutorial) — *not* per type × era.
- **D8 — Import copies `.ogg` / `.wav` / `.mp3` as-is**, with an optional
  **transcode-to-.ogg** checkbox powered by **`soundfile`** (added to
  `requirements.txt` as OPTIONAL; the checkbox greys out if it is absent).
  Rejected: ffmpeg-on-PATH — *measured*: no ffmpeg on this machine, so the
  option would be dead out of the box.
- **D9 — Plan scale: flat.** Seven phases on a mostly linear chain.

## 2. Architecture

```
data/balancing/                          engine/audio/   (audio.py → package)
────────────────                         ─────────────
core.json      Sounds.Music/Ambient/Game  __init__.py  re-exports play_music,
ui.json        Sounds.*                                stop_music, set_volume
map.json       Sounds.*                   bank.py      PURE: resolve override→
buildings.json BuildingsGlobal.Sounds                  default→silence, random
               + <family>.sounds                       pick (injected rng),
enemies.json   EnemySounds (defaults)                  volume math. No pygame.
               + EnemyTypes.<type>.sounds  sfx.py      Sound cache, channel pool,
data/audio/imported/*.ogg  ◄── clips                   cooldown, trim, buses
data/ui/screens/*.json     ◄── per-button  music.py    streaming channel, phase/
                               click override          menu/cutscene switching

editor/                                   game/
───────                                   ─────
sound_import.py  (new, pure)              main.py   sfx.init() after pygame.init;
  copy/transcode → data/audio/imported/             gp["sfx"]
panels/sound_slot.py (new)                buildings/, enemies/, ui/, core/
  SoundSlotWidget                           ~20 trigger call sites
panels/balancing.py  += x-widget hook     ui/settings.py  Master/Music/SFX
```

**Flow**: designer opens a domain in the balancing panel → a `sound_slot` node
renders as `SoundSlotWidget` → *Import…* copies the clip into
`data/audio/imported/` via `editor/sound_import.py` → the widget commits the
whole slot object through the panel's existing `_commit` → Save writes through
`engine.data_io.write_validated` → at runtime the game's dispatch seam resolves
**element override → global default → silence** and calls
`engine.audio.sfx.play(clip, bus)`.

### Load-bearing facts this design rests on

- `editor/panels/balancing.py` is a **generic schema-walking form generator** —
  `_build_object:361`, `_add_leaf_row:522`, and the one widget switch
  `_make_widget:670`. It already supports composite rendering steered by schema
  extensions: `x-paired` (`:372`), `x-toggle` (`_build_toggle_checkbox:638`),
  `x-array-editable` (`:419`). An `x-widget: "sound_slot"` hook is the same move,
  and it is why D2 costs almost no editor code.
- **`data/CLAUDE.md:410-412` — never use `oneOf` or a type-less node; it crashes
  the balancing panel for the whole domain.** Hence no nullable trim: `end: 0.0`
  is the "play to the end" sentinel.
- **`data/CLAUDE.md:438-455` — local `#/$defs/` refs only, never cross-file.**
  So the `sound_slot` `$defs` block is *duplicated* into each domain schema and
  pinned identical by a generator + drift test. Precedent:
  `tools/gen_sprite_slot_enum.py` + `tools/tests/test_schema_slot_sync.py`.
- **`editor/panels/viewport.py` sets `SDL_AUDIODRIVER=dummy` at module level for
  the whole editor process** — in-editor preview therefore cannot use
  `pygame.mixer`. It uses QtMultimedia, lazily imported, degrading to a disabled
  button (precedent `editor/thats_my_producer.py:15-32`). *Verified: QtMultimedia
  imports cleanly on this machine.*
- `editor/cutscene_import.py:93-151` (`audio_dest`, `import_audio`) is the
  existing audio-file import-copy flow; `editor/asset_import.py:55-71`
  (`sheet_users` / `unreferenced_sheets`) is the refcounting model.
- `tools/tests/temp_data.py:9` stubs `.wav/.mp3/.ogg/.mp4` to zero bytes in the
  temp `data/` copy; a test that actually decodes must set `DECODES_MEDIA:119`.
- `game/main.py:747` `pygame.init()` is where the mixer initialises; `gp` (built
  at `:1019`) is the de-facto system registry — audio joins as `gp["sfx"]`.
- *Verified*: numpy 2.4.6 imports, but only transitively via the OPTIONAL
  `opencv-python`. Start-trim must feature-detect it (§5).

### 2.1 The slot shape (`$defs/sound_slot`, duplicated per domain schema)

```json
"death": {
  "clips": [
    {"file": "imported/building_death_a.ogg", "volume": 0.8, "start": 0.0, "end": 0.0}
  ],
  "loop": false,
  "pick": "random"
}
```

- `file` — path relative to `data/audio/`. Empty string = no clip.
- `volume` — 0.0–1.0, multiplied by the bus volume and the master volume.
- `start` / `end` — seconds. `end: 0.0` means *play to the end* (a sentinel, not
  `null` — see the `oneOf` rule above).
- `loop` — one-shot vs looping (ambient, music).
- `pick` — `"random"` | `"sequential"`, used when `clips` has more than one entry.
- **`clips: []` on a global default = silence. `clips: []` on an element
  override = inherit the default.** Both layers are always present in the JSON
  (full `required` per `data/CLAUDE.md`), so the form always renders them and no
  "create the override key" machinery is needed.

### 2.2 Buses

The bus is fixed by *where the slot lives*, not by a data field a designer can
mis-set:

| Bus | Slots | Channel |
|---|---|---|
| `music` | `core.Sounds.Music.*` | `pygame.mixer.music` (streaming, one at a time) |
| `sfx` | everything else, including `core.Sounds.Ambient` (D6) | `pygame.mixer.Sound` on a pooled channel |

Effective volume = `master × bus × clip.volume`.

### 2.3 Checklist → slot map (all 21 rows)

| Checklist row | Slot |
|---|---|
| Music / ambient | `core.Sounds.Music.default` + `core.Sounds.Ambient.default` |
| game start sound | `core.Sounds.Game.game_start` |
| round win / loss | `core.Sounds.Game.round_win` / `.round_loss` |
| round start (humans screaming) | `core.Sounds.Game.round_start` |
| level up sound | `core.Sounds.Game.level_up` |
| buying plot | `map.Sounds.buy_plot` |
| tile placement sound | `map.Sounds.tile_placement` |
| cutscene sound/music | `core.Sounds.Music.cutscene` |
| menu music | `core.Sounds.Music.menu` |
| not enough love | `ui.Sounds.not_enough_love` |
| button click | `ui.Sounds.button_click` + per-widget `sound` in `data/ui/screens/*.json` |
| Building death sound | `buildings.BuildingsGlobal.Sounds.death` (+ per-family) |
| Building upgrade sounds | `…Sounds.upgrade` (+ per-family) |
| upkeep/boost | `…Sounds.upkeep_boost` (+ per-family) |
| selection sound | `…Sounds.selection` (+ per-family) |
| placement sound | `…Sounds.placement` (+ per-family) |
| boss death sound | `enemies.EnemyTypes.Boss.sounds.death` |
| cannon/boss attack sound | `EnemyTypes.Boss.sounds.attack` + `EnemyTypes.SiegeCannon.sounds.attack` |
| boss spawn | `EnemyTypes.Boss.sounds.spawn` |
| Enemy death sound | `enemies.EnemySounds.death` (+ per-type) |
| Enemy attack sound | `enemies.EnemySounds.attack` (+ per-type) |
| *(D4, beyond the checklist)* | `core.Sounds.Music.building_phase`, `core.Sounds.Music.combat_phase` |

Building sound events also include `attack`; economy buildings that never attack
simply stay silent.

## 3. Build order (flat)

| Phase | Scope (package) | Status |
|-------|-----------------|--------|
| SD-1 | Slot schema + `$defs` generator + all balancing subtrees (data) | not started |
| SD-2 | `engine/audio/` package: pure bank + sfx + music channels (engine) | not started |
| SD-3 | Editor: `sound_import.py`, `SoundSlotWidget`, `x-widget` hook, preview (editor) | not started |
| SD-4 | Triggers: buildings + map (game) | not started |
| SD-5 | Triggers: enemies + boss (game) | not started |
| SD-6 | Triggers: UI + per-button override + Master/Music/SFX sliders (game + data) | not started |
| SD-7 | Music & round/game events; retire the hardcoded boot track (game) | not started |

SD-1 gates everything. SD-2 and SD-3 depend only on SD-1 and are independent of
each other. SD-4 – SD-7 need SD-2.

---

### Phase SD-1 — Slot schema + balancing subtrees (data)

**Goal**: the data model exists and validates. No engine, no editor, no sound.

**Read**: `data/CLAUDE.md`.

**Files** — new: `tools/gen_sound_slot_defs.py` (writes the identical
`$defs/sound_slot` + `$defs/sound_clip` block into every domain schema that uses
it — the `tools/gen_sprite_slot_enum.py` pattern),
`tools/tests/test_sound_slots_data.py`.
Modified: `data/schemas/{core,ui,map,buildings,enemies}.schema.json` (the `$defs`
block, the `Sounds` subtrees, every slot site marked `x-widget: "sound_slot"`,
per-key `description` + `minimum`/`maximum` per D-12),
`data/balancing/{core,ui,map,buildings,enemies}.json` (the subtrees, all slots
empty). Imported clips stay committed content (D-31) — do **not** gitignore them.

**Tests** (`test_sound_slots_data.py`): the `$defs` block is byte-identical
across all five schemas (drift test); every checklist slot in §2.3 exists at its
stated path; an empty slot validates; a slot with two clips validates; an
out-of-range `volume`, an unknown key, and a `null` trim value each fail; no
node added to the touched schemas is type-less or uses `oneOf`; the `pick` enum
is exactly `["random", "sequential"]`.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_slots_data.py -q`.
**Quick test**: `py editor/main.py` → select `buildings` → the new `Sounds`
sections render (as plain nested fields at this phase — the composite widget is
SD-3) and the domain does not crash.

### Phase SD-2 — `engine/audio/` package (engine)

**Goal**: sound can be played by code, headlessly safe, with no game vocabulary
in `engine/`.

**Read**: `engine/CLAUDE.md`.

**Files** — new: `engine/audio/__init__.py` (re-exports `play_music`,
`stop_music`, `set_volume` **exactly** — `game/main.py:67`,
`game/ui/cutscene_player.py:16` and `tools/tests/test_audio.py` all import from
`engine.audio`), `engine/audio/bank.py` (pure: `resolve(default_slot,
override_slot)`, `pick_clip(slot, rng)`, `effective_volume(clip, bus, master)`),
`engine/audio/sfx.py` (`init()`, `play(clip, bus)`, `set_bus_volume`,
`stop_all`; `pygame.mixer.Sound` cache keyed by `(file, start, end)`, channel
pool, per-slot cooldown and max-concurrent cap), `engine/audio/music.py`
(`play(clip)`, `stop()`, `push`/`pop` so a cutscene restores the previous track —
fixing the clobber noted at `game/ui/cutscene_player.py:66`),
`tools/tests/test_audio_bank.py`, `tools/tests/test_audio_sfx.py`.
Deleted: `engine/audio.py` (becomes the package).

**Decisions**: every entry point keeps `engine/audio.py`'s swallow-and-continue
guard, so `SDL_AUDIODRIVER=dummy` and machines with no device degrade to silence
rather than crashing. `bank.py` is pure — no pygame, no globals, `rng` injected,
`data_dir`-injectable. **Start-trim needs numpy** (`pygame.sndarray` slicing) and
numpy is only a transitive optional here, so `sfx.py` feature-detects it and
falls back to `end`-only trim (`Sound.play(maxtime=…)`); it must never add a hard
dependency.

**Tests**: `bank.py` tests are headless and pure (override wins; empty override
falls through to default; empty default → `None`; `random`/`sequential` picking
with a seeded rng; volume math). `sfx` tests assert the graceful-degradation
invariant already pinned by `tools/tests/test_audio.py` (never raises with the
mixer quit / a missing file) plus cache, cooldown and cap behaviour against a
fake mixer. `tools/tests/test_audio.py` must keep passing verbatim — it pins the
re-export surface.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_audio.py tools/tests/test_audio_bank.py tools/tests/test_audio_sfx.py -q`.
**Quick test**: `py game/main.py` boots and the existing music still plays.

### Phase SD-3 — Editor sound slot (editor)

**Goal**: a designer imports a clip, sets volume/trim/loop, adds variations, and
hears it — without leaving the balancing form.

**Read**: `editor/CLAUDE.md`.

**Files** — new: `editor/sound_import.py` (PURE — Qt-free and pygame-free:
`clip_ref(name)`, `import_clip(data_dir, src, name, transcode=False)` copying
into `data/audio/imported/`, `imported_clips(data_dir)` for the reuse picker,
`clip_users` / `unreferenced_clips` refcounting modelled on
`editor/asset_import.py:55-71`, `transcode_available()`),
`editor/panels/sound_slot.py` (`SoundSlotWidget`),
`tools/tests/test_sound_import.py`, `tools/tests/test_sound_slot_widget.py`.
Modified: `editor/panels/balancing.py` — `_build_object:361` intercepts
`prop.get("x-widget") == "sound_slot"` and emits a `SoundSlotWidget` instead of
recursing; the widget commits the whole slot object through the existing
`_commit:725`, and `_set_widget_value:795` / `_apply_snapshot:806` learn the new
widget type. `tools/tests/test_editor_viewport.py` (`TestPurity` += the two new
modules — editor rule 2). `requirements.txt` (+ `soundfile`, marked OPTIONAL in
the same style as `opencv-python`).

**Decisions**: preview uses **QtMultimedia**, lazily imported inside a `try`
(precedent `editor/thats_my_producer.py:15-32`), because
`editor/panels/viewport.py` sets `SDL_AUDIODRIVER=dummy` process-wide —
`pygame.mixer` in the editor is silent by construction. Missing QtMultimedia ⇒
the ▶ button disables itself. The transcode checkbox is enabled only when
`soundfile` imports; the raw-copy path always works. Files above a size
threshold get a warning (`data/audio/Bass_and_drum_Duo.wav` is already 49 MB).
`QFileDialog` stays confined to one `_on_*_clicked` method and dialog
construction is split from display, so no test `exec()`s (editor rule 12).

**Tests**: `test_sound_import.py` (pure, no Qt) — copy into a temp `data_dir`,
`clip_ref` shape, refcounting, transcode skipped cleanly when `soundfile` is
absent, non-audio extension rejected. `test_sound_slot_widget.py` — the widget
renders from a slot dict and round-trips it through `_commit`; adding/removing a
clip restructures the list; volume/trim bounds come from the schema;
`QtCase.track` destroys every widget (editor rule 17); assert against a pinned
fixture, never live `data/` (rule 18). Any test that actually decodes a clip must
set `DECODES_MEDIA` (`tools/tests/temp_data.py:119`) — audio is stubbed to zero
bytes in the temp copy.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_import.py tools/tests/test_sound_slot_widget.py tools/tests/test_editor_viewport.py -q`.
**Quick test**: `py editor/main.py` → `buildings` → *DefenceBuildings →
BasicDefence → Sounds → attack* → **Import…** a short clip → ▶ plays it → set
volume 0.5 → Save → reopen the editor and confirm it persisted into
`data/balancing/buildings.json`.

### Phase SD-4 — Triggers: buildings + map (game)

**Goal**: placement, selection, upgrade, death, attack and upkeep/boost sounds
fire; buying a plot and placing a tile make a noise.

**Read**: `game/CLAUDE.md`, then `game/buildings/CLAUDE.md`.

**Files** — modified: `game/main.py` (`sfx.init(data_dir)` after
`pygame.init():747`; `gp["sfx"]`), `game/buildings/*` (placement, upgrade,
death, attack, selection, upkeep/boost call sites), `game/map/*` and
`game/ui/building_ui.py` (buy-plot, tile placement), `game/core/balance.py` if a
loader seam is needed. New: `tools/tests/test_sound_triggers_buildings.py`.

**Decisions**: game code resolves through **one seam** — a
`game/ui/effects.py`-style dispatcher (`play_building_sound(kind, family)`) that
looks up the family override then the global default, mirroring how
`game/ui/effects.py::_play` / `_play_typed` already dispatches VFX. No `game/`
module ever names an audio file, and `engine/` never branches on a building type
string (D5, layering). **Locate every call site fresh** — the previous draft of
this plan cited line numbers that no longer resolve.

**Tests**: a fake `sfx` records `(slot_path, clip)` calls; assert the right slot
fires on place / upgrade / death / attack / select / upkeep, that an empty
override falls back to the default, and that an empty default is a silent no-op
rather than a crash.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_triggers_buildings.py -q`.
**Quick test**: `py game/main.py` → buy a plot (sound) → place a defence building
(placement) → select it (selection) → upgrade it (upgrade) → let it shoot
(attack) → let it die (death).

### Phase SD-5 — Triggers: enemies + boss (game)

**Goal**: enemy spawn/attack/death and the three boss rows fire, with per-type
overrides.

**Read**: `game/CLAUDE.md`, then `game/enemies/CLAUDE.md`.

**Files** — modified: `game/enemies/*` (spawner, walker, combat sweep),
`game/core/session.py` / `game/core/boss_bonuses.py` for boss spawn.
New: `tools/tests/test_sound_triggers_enemies.py`.

**Decisions**: the override key is the `EnemyTypes` entry (D7), reached via the
existing `registry_group` / type mapping — **not** a new string convention.
`data/schemas/enemies.schema.json:663-667` warns explicitly that the registry
label is not the `EnemyTypes` key (`Standard → "Walker"`,
`SiegeCannon → "Siege Cannon"`); match by field, never by convention. Boss spawn,
boss attack and boss death are the `Boss` type's override rows; the cannon attack
is `SiegeCannon`'s. A 40-enemy wipe in one frame is the load case — SD-2's
per-slot cooldown and max-concurrent cap are load-bearing here, not polish.

**Tests**: fake-`sfx` assertions per type; a mass-death burst plays at most the
cap; `SiegeCannon` and `Boss` attacks resolve to their overrides while an
un-overridden type falls back to `EnemySounds`.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_triggers_enemies.py -q`.
**Quick test**: `py game/main.py` → reach a wave with siege cannons (their attack
differs from the default) → reach a boss round (spawn, attack, death).

### Phase SD-6 — UI triggers, per-button override, volume sliders (game + data)

**Goal**: buttons click, "not enough love" is audible, and the settings screen
has working Master / Music / SFX sliders.

**Read**: `game/CLAUDE.md`, then `game/ui/CLAUDE.md`.

**Files** — modified: `data/schemas/ui_screen.schema.json` (an **optional**
`sound` key on the per-widget override object — optional by omission from
`required`, so every existing `data/ui/screens/*.json` stays byte-identical),
`game/ui/widgets.py` + `game/ui/shell.py` (`_main_menu_click:205`,
`_settings_click:246`, `_pause_click:255`) for the click seam,
`game/ui/overlays.py` (or wherever `ui.Timing.not_enough_love_duration` is
consumed), `game/ui/settings.py` (three sliders replacing the inert `volume:71`
and the `_audio_note` label at `:112-113,229-235`), `game/ui/strings.py` +
`data/ui/strings.json` (retire `settings.no_audio`, add music/SFX labels), and a
regeneration of `data/ui/screen_defaults.json` / `screen_previews.json` via
`tools/export_ui_layouts.py` if the settings layout changes.
New: `tools/tests/test_sound_triggers_ui.py`.

**Decisions**: the per-button override resolves once, in the widget click seam —
the widget's own `sound` if set, else `ui.Sounds.button_click`. Each slider sets
a bus volume through `engine.audio.sfx.set_bus_volume` / `music.set_volume`, and
persists wherever the settings screen already persists. Ambient is on the SFX bus
(D6). `screen_defaults.json` / `screen_previews.json` are generated-but-committed
— regenerate them in this phase or the drift test fails.

**Tests**: the click seam plays the global slot; a widget carrying a `sound`
override plays that instead; bus volume multiplies correctly; the schema still
validates every unmodified `data/ui/screens/*.json`.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_triggers_ui.py tools/tests/test_ui_screens.py -q`.
**Quick test**: `py game/main.py` → click menu buttons (click sound) → Settings →
drag Music to 0 (music stops, SFX keeps playing) → drag SFX to 0 → in game, try
to place a building you cannot afford (not-enough-love sound at SFX volume).

### Phase SD-7 — Music and round/game events (game)

**Goal**: every remaining checklist row plays, and no audio path is hardcoded.

**Read**: `game/CLAUDE.md`, then `game/core/CLAUDE.md`.

**Files** — modified: `game/main.py` (**delete** the hardcoded
`play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav", loop=True)` at `:999`;
that track becomes the imported clip of `core.Sounds.Music.default`),
`game/core/phases.py` + `game/core/session.py` (building-phase / combat-phase
music switch; round start / win / loss), `game/core/levelup.py` (level-up sound),
`game/ui/shell.py` (menu music on `to_main_menu:116` / `enter_gameplay:108`;
game-start sound), `game/ui/cutscene_player.py` (cutscene music slot, using
`music.push`/`pop` so the previous track resumes), `data/balancing/core.json`
(seed the default music slot with the existing WAV).
New: `tools/tests/test_sound_music.py`.

**Decisions**: music resolution is `phase override → default`, exactly like every
other slot — building phase and combat phase are overrides of
`core.Sounds.Music.default` (D4). Ambient loops on the SFX bus concurrently with
music. Switching to a track that is already playing is a no-op — never restart it
on every phase tick.

**Tests**: a fake music channel records `play`/`stop`; the phase machine switches
tracks on transition and only on transition; an empty phase override falls back
to the default; the cutscene push/pop restores the prior track; round win/loss
and level-up fire exactly once each.

**Exit gate**: `py tools/smoke.py` +
`py -m pytest tools/tests/test_sound_music.py -q`.
**Quick test**: `py game/main.py` → menu music at the main menu → start a game
(game-start sound, then building-phase music) → end turn (round-start scream,
combat-phase music) → clear the wave (round-win) → level up (level-up sound) →
trigger a cutscene (its music plays, then the previous track resumes).

---

## 4. Verification (whole plan)

Each phase's own gate is written above, and that is what the executing agent
runs — `py tools/smoke.py` plus the named test files, then the Quick Test.

The **single** full `py tools/testgate.py check` happens once, in the main
session, at handoff. §"Test Suite Policy" in the root `CLAUDE.md` is the only
authority on this; do not restate a different rule here.

Tests must never write into `data/` (`TempDataCase`; a session fixture hashes
`data/` and fails the run if it changed) and must never assert against live
`data/` content — pin the fixture.

## 5. Risks / open items

- **Start-trim depends on numpy**, which is present only transitively via the
  OPTIONAL `opencv-python` (*measured*: numpy 2.4.6 imports today). SD-2 must
  feature-detect it and ship `end`-only trim when it is missing; the editor greys
  the `start` field out in that case. Do **not** promote numpy to a hard
  dependency without asking.
- **`soundfile` is a new dependency** (D8). It must be OPTIONAL — the transcode
  checkbox disables itself if the import fails, and the raw-copy path always
  works.
- **Repo size.** Audio is committed content. `data/audio/Bass_and_drum_Duo.wav`
  is already 49 MB; 21 more uncompressed clips would hurt. The transcode option
  and the import-size warning are mitigation, not a guarantee.
- **`engine/audio.py` → package conversion** is the one backwards-compat risk
  (SD-2). Three importers depend on the exact re-export surface.
- **Channel exhaustion / mix mud** on a mass enemy wipe — SD-2's cooldown and
  max-concurrent cap are load-bearing for SD-5.
- **Empty-clips semantics differ by layer** (default = silence, override =
  inherit). Deliberate and cheap, but it must be stated in the `SoundSlotWidget`
  tooltip or a designer will be confused by it.
- **`screen_defaults.json` / `screen_previews.json` are generated-but-committed**
  — SD-6 regenerates them if it changes the settings layout, or the drift test
  fails.
- Every file:line in this document was re-verified in the `SoundEditor` worktree
  on **2026-08-18**. The previous draft's citations had drifted badly (including
  a reference to `editor/main_window.py`, which does not exist) — re-check before
  executing if much time passes.
