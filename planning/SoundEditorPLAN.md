<!-- status: NOT STARTED — SE-1–SE-6 -->

# SoundEditorPLAN.md — Sound authoring in the editor, audio in the game

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/SoundEditorPLAN.md SE-1-SE-6` or phase-by-phase.

Source: `Sound document ideation.md` (user-supplied), plus four scoping
decisions taken with the user (§1).

## 1. Vision

The editor gets a **Sound** root in the left tree, directly below **VFX**, with
five children — **Buildings, Enemies, Environment, Music, UI**. From it a
designer authors every sound in the game without touching JSON: import a clip
the same way spritesheets are imported, set its volume and its in/out trim,
preview it in-panel, and choose **single** mode (one clip) or **array** mode (a
list; the game picks one at random each time the event fires).

Buildings and enemies have **default** sounds that every instance inherits, and
a per-thing override layer underneath. A building that has never been touched in
the Sound menu shows *"inherits default"* — not a copy — so the fallback stays
visible and no phantom overrides get written.

Today there is effectively **no sound system** to build on:

- `engine/audio.py:15-40` — three functions (`play_music` / `stop_music` /
  `set_volume`). Music only. No SFX, no channels. *(verified)*
- `game/main.py:223` — the single audio call site in the game: one looping track
  at boot, windowed runs only. *(verified)*
- `game/ui/settings.py:172` — a volume slider labelled **"(no audio yet)"**,
  never wired to `set_volume()`. *(verified)*
- Zero triggers for building placed / upgraded / death / attack / repair, enemy
  spawn / attack / death / reaches-hole, boss phases, or UI clicks. *(verified)*

So this plan builds three layers — data, engine, editor — and then wires ~15
game trigger points. It spans `data/`, `engine/`, `game/` and `editor/`; each
phase below is scoped to as few packages as the work allows, and each names the
ONE package doc its executor should read.

### Scoping decisions (taken with the user)

- **D1 — Sound gets its own data model**, `data/audio/sound_bank.json`, *not* a
  `slots.json` category. VFX is an asset-only registry category and the selector
  picks it up for free (`editor/panels/selector.py:110-148`), which made reuse
  tempting. But audio has no frames, no animation rows, no frame size, and it
  *does* need array mode, per-clip volume and trim — none of which
  `asset_manifest.schema.json` can express. Forcing sound through a sprite-shaped
  schema would be a lie the whole editor then has to special-case.
- **D2 — Full scope.** Editor *and* engine *and* every trigger, including boss
  and per-era music. Sound is audible in-game when SE-6 lands.
- **D3 — Environment = placeable emitters.** The ideation doc's environment
  sentence is truncated ("there should be a tool that can"); the user's
  clarification is a **placeable sound emitter** on the map, choosing from the
  environment sounds imported in the Sound menu, with a radius and distance
  falloff.
- **D4 — In-panel preview**, play/stop plus numeric trim fields. No waveform
  rendering (needs a decoder and a custom paint widget; not worth it here).

## 2. Architecture

```
data/                                    engine/audio/  (audio.py → package)
────                                     ──────────────
schemas/sound_bank.schema.json           __init__.py  re-exports play_music,
audio/sound_bank.json   ◄── the bank                  stop_music, set_volume
audio/imported/*.ogg    ◄── clips        bank.py      pure: load, resolve,
schemas/map_file.schema.json                          array pick   (no pygame)
  += sound_emitters[]                    sfx.py       Sound cache, channel pool,
                                                      trim, master volume
editor/                                  game/
───────                                  ─────
panels/sound.py   (new)                  buildings/, enemies/, ui/  call
  Buildings │ Enemies │ Environment        sfx.play("building.placed", ctx)
  Music     │ UI                         core/  music per era/phase
panels/selector.py  += Sound root         main.py  emitter falloff per frame
map_session.py      += emitter cmds
panels/viewport.py  += emitter place
```

**Flow**: designer imports a clip → `editor/panels/sound.py` copies it into
`data/audio/imported/` and writes the bank through `engine.data_io.write_validated`
→ at runtime `bank.resolve(event_key, ctx)` walks **override → default →
silence** → `sfx.play()` fetches the cached `pygame.mixer.Sound`, picks a channel,
applies clip volume × master volume, and plays.

### 2.1 The bank

```json
{
  "version": 1,
  "defaults": {
    "building.placed": {
      "mode": "array",
      "clips": [{"file": "imported/place_a.ogg", "volume": 0.8,
                 "start": 0.0, "end": null}]
    }
  },
  "overrides": {
    "building.stone_thrower_t1_lvl1.placed": {"mode": "single", "clips": [...]}
  },
  "environment": {
    "wind_loop": {"mode": "single", "clips": [...]}
  }
}
```

`start`/`end` are seconds from the clip head; `end: null` means "to the end".
`volume` is 0.0–1.0. `mode` is `"single"` (clips must be length 1) or `"array"`
(one clip picked at random per play).

### 2.2 Event-key grammar

Flat dotted strings. This is the whole indirection layer — the game never names
a file, only an event.

| Family | Default key | Override key |
|---|---|---|
| Building | `building.<event>` | `building.<slot_key>.<event>` |
| Enemy | `enemy.<event>` | `enemy.<group>.<era>.<event>` |
| Boss | `boss.<event>` | `boss.<slot_key>.<event>` |
| UI | `ui.<event>` | — (no per-thing layer) |
| Music | `music.era.<n>`, `music.phase.<name>`, `music.menu`, `music.special.<name>` | — |

Events — buildings: `placed, upgraded, death, ui_select, attack, repair`
(economy buildings included; `attack`/`repair` simply stay silent for those that
never fire them). Enemies: `spawn, attack, death, reaches_hole`. Boss:
`entrance_music, entrance_voice, attack, death, reaches_hole, phase2`. UI:
`click, cancel, menu_click`.

**Why enemy overrides key on `<group>.<era>`**: the ideation doc wants an era-1
walker to sound different from an era-3 walker. That distinction already exists
in the registry group path — `game/enemies/enemy.py:45,62` calls
`registry.group_slots("enemies", (group, era_label))`. Keying on it means
era-specific sound falls out of the existing model instead of inventing a
second one.

### 2.3 Layering

`engine/audio/bank.py` is **pure** — no pygame, no globals, `data_dir`-injectable
— so it unit-tests headless. `sfx.py` is the only new pygame surface; `game/`
calls `sfx.play(...)` and never touches `pygame.mixer`. `editor/` and `game/`
still never import each other. Every `sfx` entry point carries the same
swallow-and-continue guard `engine/audio.py:15-40` already uses, so a machine
with no audio device — or a headless CI run — degrades to silence rather than
crashing.

## 3. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| SE-1  | Sound-bank schema + `data/audio/` layout + pure resolver | not started |
| SE-2  | Engine SFX playback: channel pool, trim, master volume, settings slider | not started |
| SE-3  | Editor Sound menu: tree root, panel, import, single/array, volume/trim, preview | not started |
| SE-4  | Trigger wiring: buildings, enemies, UI | not started |
| SE-5  | Music: per-era / per-phase / special / menu, plus boss entrance + phase 2 | not started |
| SE-6  | Environment emitters: map schema, editor placement, falloff playback | not started |

SE-2 and SE-3 both depend only on SE-1 and are independent of each other — the
editor can be built against the schema while engine playback lands in parallel.
SE-4 and SE-5 need SE-2. SE-6 needs both SE-2 and SE-3.

---

### Phase SE-1 — Sound-bank schema + resolver (pure)

**Package**: `data/` + `engine/` — read `data/CLAUDE.md`.

**Goal**: the bank exists, validates, and resolves. No playback, no UI.

**Files** — new: `data/schemas/sound_bank.schema.json`,
`data/audio/sound_bank.json` (seeded with the full default key set, empty clip
lists), `data/audio/imported/.gitkeep`, `engine/audio/bank.py`,
`tools/tests/test_sound_bank.py`. Modified: `engine/audio.py` → `engine/audio/__init__.py`
re-exporting the existing three functions unchanged; `tools/smoke.py` if
`validate_data` does not already reach `data/audio/` (the directory-exception
precedent is `data/maps/` → `map_file.schema.json` and `data/agent_forms/` →
`agent_form.schema.json`, `tools/smoke.py::validate_data`).

**Tests**: bank loads and validates; `mode: "single"` with two clips is rejected
by the schema; unknown event key resolves to `None`, not a raise; resolution
order override → default → silence; array pick is deterministic under a seeded
RNG; `start`/`end` out of order rejected; a round-trip through `write_validated`
is byte-stable (sorted keys, 2-space indent, trailing newline).

**Exit gate**: `py tools/smoke.py` validates the new file; `py tools/testgate.py
check --affected` → GATE PASS. `game/main.py:51`'s `from engine.audio import
play_music` still works (the package conversion must be invisible).

---

### Phase SE-2 — Engine SFX playback

**Package**: `engine/` — read `engine/CLAUDE.md`. Use `engine-coder`.

**Goal**: `sfx.play(event_key, ctx)` makes noise, with volume, trim, array pick
and a channel budget. The settings slider stops lying.

**Files** — new: `engine/audio/sfx.py`. Modified: `engine/audio/__init__.py`
(export `play`, `set_master_volume`, `init`), `game/ui/settings.py` (wire the
slider at :172 to master volume; delete the "(no audio yet)" label),
`tools/tests/test_audio.py` (extend).

**Design points**:
- `pygame.mixer.Sound` cache keyed by resolved clip path; a bounded channel pool
  with a **per-event-key cooldown and max-concurrent cap** — 40 enemies dying in
  one frame must not become mud or exhaust channels.
- Trim: `end` via `Sound.play(maxtime=ms)`. `start` requires a sliced buffer —
  slice once at load and cache the sliced `Sound`. If that needs numpy
  (`pygame.sndarray`) and numpy is not already a dependency, **ship `end`-only
  trim** and record start-trim as an open item rather than adding a dep.
- Master volume multiplies clip volume; both clamp to [0, 1].

**Tests**: every `sfx` entry point is a no-op that raises nothing with the mixer
uninitialised (the headless case — this is the invariant `test_audio.py` already
guards for music); cooldown suppresses a second play inside the window; the
channel cap is respected under a burst; master × clip volume math; cache returns
the same object twice.

**Exit gate**: `py tools/testgate.py check --affected` → GATE PASS;
`py tools/smoke.py` 5-frame headless boot still clean.

---

### Phase SE-3 — Editor Sound menu

**Package**: `editor/` — read `editor/CLAUDE.md` then `editor/panels/CLAUDE.md`.
Consider opening with `/add-editor-feature`.

**Goal**: a designer can do everything in §1 from the editor.

**Files** — new: `editor/panels/sound.py`, `editor/sound_import.py` (clip copy +
bank write; mirror `editor/asset_import.py:46,139`),
`tools/tests/test_editor_sound.py`. Modified: `editor/panels/selector.py`
(inject the **Sound** root immediately after the VFX category node — Sound is
not a registry category, so it is an explicit root, not a `registry.categories()`
entry), `editor/main_window.py:109` (`_on_node_selected` routes sound nodes to
the new panel), `tools/tests/test_editor_viewport.py` (`TestPurity` +=
`editor.panels.sound`, `editor.sound_import`).

**Design points**:
- Five children: Buildings, Enemies, Environment, Music, UI. Buildings/Enemies
  open on the **defaults** row with a per-thing list beneath; untouched rows
  render *"inherits default"* and write nothing.
- Per event key: mode toggle, clip list (add / remove / reorder), per-clip
  **Import…**, volume spin, start/end trim spins, **▶ / ■** preview.
- Preview uses `QtMultimedia.QMediaPlayer` via the lazy-import,
  degrade-gracefully pattern at `editor/thats_my_producer.py:15-28` — if
  QtMultimedia is unavailable the button disables itself, it does not crash.
- Canonical import format is **`.ogg`** (size; pygame handles it natively).
  Accept `.wav` on import too, but do not transcode — store as-is.
- Every write goes through `write_validated`. Single-selection model, one render
  path (ED-22).

**Tests** (`editor` tier): panel builds for each of the five tabs against a temp
`data/` copy; importing a clip lands it in `data/audio/imported/` *inside the
temp tree* and the bank re-validates; toggling single→array preserves clip 1;
an untouched per-thing row writes no `overrides` entry; preview is skipped
cleanly when QtMultimedia is absent. `TempDataCase` throughout — never assert
against live `data/`.

**Exit gate**: `py tools/testgate.py check --affected` → GATE PASS. Manual:
`py editor/main.py` → Sound → Buildings → import a clip on `building.placed` →
preview plays.

---

### Phase SE-4 — Trigger wiring: buildings, enemies, UI

**Package**: `game/` — read `game/CLAUDE.md`.

**Goal**: the game fires the events. Sound is audible in play.

**Files** — modified (call sites already located, *verified*):
`game/buildings/registry.py:43` (placed), the building `upgrade()` path and the
repair path in `game/buildings/`, `game/core/session.py:385`
(`_award_building_deaths` → building death), `game/enemies/spawner.py` (spawn),
`game/enemies/combat.py:333` (`resolve_combat` → attack, both directions),
`game/main.py:625` + `game/core/session.py:427` (enemy death), the
reaches-hole path, `game/ui/shell.py:93,109,123,137,146` and
`game/ui/building_ui.py:722,766,798,854` (UI clicks and the upgrade-UI select).

**Design points**: each call is one line — `sfx.play(key, ctx)` — with `ctx`
carrying the slot key (buildings) or group+era (enemies) so `bank.resolve` can
find an override. No game-logic change; no behaviour depends on the return.

**Tests**: a headless session runs a wave end-to-end with a stub `sfx` recording
event keys, and asserts the expected keys fire in order with the right override
context. This is the phase's real value — it pins the *keys*, which are the
contract the editor writes against.

**Exit gate**: `py tools/testgate.py check --affected` → GATE PASS. Manual:
place a building and hear it; kill an enemy and hear it.

---

### Phase SE-5 — Music

**Package**: `game/` — read `game/CLAUDE.md`.

**Goal**: music per era, per phase, special occasion, main menu; boss entrance
music + voiceline + phase-2 sting.

**Files** — modified: `game/main.py:223` (replace the hardcoded boot track with
`music.menu` / the active era key), the era- and phase-transition sites in
`game/core/`, `game/core/boss_bonuses.py` (see below), `engine/audio/__init__.py`
if a crossfade helper is wanted.

**Open item carried into this phase**: boss **phase 2** has no existing trigger
point in `game/core/boss_bonuses.py` *(inferred — scout found none)*. The
executor must first locate or create the phase-transition hook, and should
surface it to the user if creating one means a behaviour change rather than a
pure hook.

**Tests**: music key selection per era/phase is a pure function and is tested as
one; boss entrance fires exactly once per boss.

**Exit gate**: `py tools/testgate.py check --affected` → GATE PASS.

---

### Phase SE-6 — Environment emitters

**Package**: spans `data/` + `editor/` + `game/` — tell the user before starting;
it is the one phase that legitimately crosses packages.

**Goal**: a designer places a sound emitter on the map; the game plays its
environment sound with distance falloff.

**Files** — modified: `data/schemas/map_file.schema.json` (add a
`sound_emitters` array — copy the `deco` array shape at schema lines 79-107,
plus `sound` (a key into the bank's `environment` section) and `radius`),
`editor/map_session.py:330,333` (mirror `_DecoPlaceCommand` /
`_DecoRemoveCommand` — undo/redo comes free from the `QUndoStack`),
`editor/panels/viewport.py:88+` (palette-armed left-click places, erase removes),
`editor/panels/palette.py` (emitter tool), `game/main.py` (per-frame falloff).

**Design points**: emitters are **passive data** — no `GameObject`, no
`RenderItem`, no entry in `engine/tilemap.py::render_items`. Each frame, take the
camera-centre world point (`cs.screen_to_world(view_w/2, view_h/2)`,
`game/main.py:147-148`), compute linear falloff over `radius`, set that
emitter's channel volume. The editor *should* draw a radius ring while the
emitter tool is armed, so the designer can see what they are placing.

**Tests**: a map with emitters round-trips through the schema; place/remove
undo/redo restores exactly; falloff is a pure function tested at centre, edge,
and beyond radius; a map with no `sound_emitters` key still loads (backwards
compatible — the field is optional).

**Exit gate**: `py tools/smoke.py` (map schema + boot) and the **full**
`py tools/testgate.py check` → GATE PASS. Manual: place an emitter, walk the
camera away, hear it fade.

## 4. Verification (whole plan)

```
py tools/smoke.py           # data validation + 5-frame headless boot
py tools/testgate.py check  # GATE PASS or you are not done
```

`--affected` while iterating; the full `check` once, at handoff. Tests must copy
`data/` to a tempdir (`TempDataCase`) — the session fixture fails the run if
`data/` changed. Never assert against live `data/` content; pin fixtures.

**Quick Test for the PR**: `py editor/main.py` → Sound → Buildings → import a
clip on `building.placed` → preview plays → save → `py game/main.py` → place a
building → hear it. Then place an environment emitter in the map editor, load
that map, and move the camera away — the sound fades.

## 5. Risks / open items

- **Start-trim slicing** may need numpy (`pygame.sndarray`). If numpy is not
  already a dependency, SE-2 ships `end`-only trim (`maxtime`) and start-trim
  becomes an open item — do not add a dependency to close it without asking.
- **Channel exhaustion / mix mud** — a 40-enemy wipe in one frame. SE-2's
  per-event cooldown and max-concurrent cap are load-bearing, not polish.
- **Boss phase-2 has no hook** *(inferred)* — SE-5 may have to create one; that
  is a game-logic touch inside a plan that is otherwise additive.
- **`engine/audio.py` → package conversion** is the one backwards-compat risk in
  SE-1. `game/main.py:51` and `tools/tests/test_audio.py` both import from it;
  the re-export must be exact.
- **QtMultimedia may be absent** — already an established optional at
  `editor/thats_my_producer.py`; the preview button disables itself.
- **The ideation doc's environment sentence is truncated.** The emitter design in
  SE-6 is the user's spoken clarification, not the document's — re-confirm before
  building SE-6 if much time has passed.
- **Volume UX**: master volume lives in `game/ui/settings.py`; there is no
  separate music/SFX split. If the user wants one later it is a settings change,
  not a bank change — the split belongs above `sfx.play`, not in the schema.
