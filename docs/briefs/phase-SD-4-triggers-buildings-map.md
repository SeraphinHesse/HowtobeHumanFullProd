# Phase SD-4 — Triggers: buildings + map (game)

Source plan: `planning/SoundEditorPLAN.md` (§2.1 slot shape, §2.2 buses, §2.3
checklist→slot map, the SD-4 phase block). Base: SD-1 (schemas + balancing
subtrees) and SD-2 (`engine/audio/`) are DONE and are **consumed, never
re-implemented**. You may not edit `engine/**` or `data/schemas/**` in this
phase.

**Line citations below were re-verified in this worktree on 2026-08-18, AFTER
the `origin/Development` merge (`82d37cf`).** The plan doc's own citations
(`game/main.py:588` for `pygame.init()`, `:825` for `gp`, `:785` for the boot
track) predate that merge and no longer resolve — the live numbers are
`game/main.py:747`, `:1019` and `:998-999`, in a 2705-line file. Re-check with
`grep -n` before editing; if the tree has moved again, every anchor below is
named by CONTENT, and the content is what binds.

---

## 0. The SD-2 API this phase consumes (pinned — do not deviate)

Import **only** `engine.audio`. Every mixer-touching call returns `bool` and
**never raises**, so headless runs (`tools/smoke.py`, the whole suite, the
editor's `SDL_AUDIODRIVER=dummy`) degrade to silence rather than failing.

```python
engine.audio.init(data_dir, *, channels=24) -> bool      # idempotent; after pygame.init()
engine.audio.play_slot(default_slot, override_slot=None, *,
                       bus="sfx", key=None, rng=None, loop=None) -> bool
engine.audio.bank.resolve(default_slot, override_slot=None)  # the §2.1 rule
```

- `bank.resolve` **already implements the override→default→None rule** (quoted
  verbatim in §3). `play_slot` calls it for you — SD-4 passes both layers and
  never pre-resolves, and never re-derives "is this empty".
- `key` is an **opaque cooldown / concurrency bucket**; the engine never parses
  it. SD-4 passes the slot path string (e.g.
  `"buildings.BuildingsGlobal.Sounds.attack"`) so per-slot cooldown and the
  max-concurrent cap bucket the way SD-2 intended.
- `engine/audio.py` is today a *module*; SD-2 converts it to a package while
  preserving `play_music` / `stop_music` / `set_volume`. Three importers pin
  that legacy surface, one of them `game/main.py:67` — **SD-4 does not touch
  that line** (SD-7 does).
- **PINNED, do not harmonize**: the three legacy functions return **`None`**
  (`tools/tests/test_audio.py:23-44` asserts it); the new `init` / `play_slot`
  return **`bool`**. The mismatch is deliberate and load-bearing — "tidying" the
  legacy three to return `bool` breaks a pinned test, and treating `play_slot`'s
  `False` as an error is equally wrong (see below: `False` is the normal
  no-device / empty-slot answer).

---

## 1. Behavioral spec

Every sound in this phase is a **slot** resolved through SD-2's bank, never a
file path named by `game/`. The slots this phase fires, by their §2.3 path:

### buildings

| Slot (§2.3) | Fires when | Live call site |
|---|---|---|
| `buildings.BuildingsGlobal.Sounds.placement` (+ per-family) | a construct-modal CONFIRM actually placed ≥1 building | `game/ui/building_ui.py:2470` — `self.last_placed_type = p.building_type`, the "a real placement landed" signal, set only after the `placed_any` guard at `:2465-2469` |
| `buildings.BuildingsGlobal.Sounds.selection` (+ per-family) | a click / drag-select opens the panel on a tile whose `occupant` is a building | `game/main.py:1627` (`update_selection` → `panel.open_for_tile`) and `game/main.py:1664` (`finish_drag_select` → `panel.open_for_tile`) |
| `buildings.BuildingsGlobal.Sounds.upgrade` (+ per-family) | an UPGRADE/ADVANCE click actually spent love and levelled/advanced ≥1 building | `game/ui/building_ui.py:2219` `_upgrade_click`, inside the `action_btn` branch (`:2251`ff) — AFTER the `st.love < total` flash guards, on the success path(s) only |
| `buildings.BuildingsGlobal.Sounds.death` (+ per-family) | a non-base building's `alive` flips True→False this frame | mirrors `FloaterManager.watch_buildings` (`game/ui/effects.py:840-860`), driven from `game/main.py:2299` |
| `buildings.BuildingsGlobal.Sounds.attack` (+ per-family) | a combat building fires | `Attacker.cooldown` (`game/buildings/components.py:75-82`) RESET (grew) since last frame — the exact cadence detector `FloaterManager.watch_enemies` already uses for enemies (`game/ui/effects.py:872-906`) |
| `buildings.BuildingsGlobal.Sounds.upkeep_boost` (+ per-family) | payday charged upkeep and/or a booster ticked | the INCOME phase edge, `game/main.py:2200-2202` (`gp["floaters"].begin_payout(session.state)`); the ledgers are `state.income_events` rows tagged `"upkeep"` (filled `game/core/payday.py:266-275`) and `state.boost_events` (filled `game/core/payday.py:152-162`) |

**Why `attack` is a cooldown watcher, not a callback.** The existing shot seam
`resolve_combat(..., on_defender_fire=...)` (`game/main.py:2148-2158`,
`game/enemies/combat.py:892-893,999-1000`) carries **only `(wx, wy)`** — no
shooter, hence no family. `game/CLAUDE.md` records that this signature was
deliberately NOT widened for telemetry; do not widen it for sound either. The
`Attacker.cooldown` watcher yields the building OBJECT, which is what the
per-family override needs.

**Event volume is bounded, deliberately.**
- `placement` / `upgrade`: **once per click**, not once per tile of a batch. A
  10-tile batch place is one sound.
- `upkeep_boost`: **at most once per distinct family per payday** (≤5 plays), in
  first-seen ledger order — not once per building.
- `death` / `attack`: one per event; SD-2's per-slot cooldown and
  max-concurrent cap (bucketed by the `key=` you pass) are what keep a wipe or a
  firing line from turning to mud. SD-4 adds no second cap of its own.

### map

| Slot (§2.3) | Fires when | Live call site |
|---|---|---|
| `map.Sounds.buy_plot` | a tile purchase actually spent love | `game/ui/building_ui.py:2121` `_unlock_click` → `self.last_unlocked = unlocked_any` (`:2152`), read by the host at `game/main.py:1476-1478` |
| `map.Sounds.tile_placement` | same event, layered second | same site |

**Both map slots fire once per successful purchase, together** (`buy_plot`
first, `tile_placement` second) — the coin and the ground. A multi-chunk batch
purchase is still ONE of each. See §Open questions: the alternative reading (one
`tile_placement` per converted 2×2 chunk, `TileMap.do_unlock`
`game/map/tile_map.py:761-800`) needs a new `BuildingUI` transient and can stack
3-4 plays on one click; it was NOT chosen and needs a human ruling if the
designer meant it.

### Silence is a first-class outcome

An unfilled slot must be a **no-op — never a crash, never a log-spam line**.
`tools/smoke.py`, the whole test suite and the editor all run with no audio
device; `data/balancing/*.json` ships every slot empty out of SD-1. So the
correct behaviour of this entire phase, on today's data, is *nothing audible and
nothing different*.

---

## 2. Architecture plan

**One seam, one new module: `game/sounds.py`.**

Modelled on `game/vfx_variants.py` / `game/vfx_misc.py` — the two small
top-level `game/` modules that own the GAME vocabulary for a mechanism whose
pure half lives in `engine/` (`game/CLAUDE.md`, "VFX variant selection"). Same
split here: `engine/audio/bank.py` knows about slots, clips and volume math and
nothing about buildings; `game/sounds.py` is where the words
`"placement"`/`"upgrade"`/`"buy_plot"` and the `SUBTREE` family lookup live.
`engine/` must never branch on a building-type string (D5, layering).

**Lifetime: the object is built once at BOOT and lives for the whole process** —
never rebuilt per run, never cleared at teardown (see §3). It holds no run state.

```
game/sounds.py                     (new — no pygame, no file paths, no Qt)
  class GameSounds:
    __init__(buildings_balance, map_balance, *, audio=engine.audio, rng=None)
    play_building_event(kind, building)      # placement/selection/upgrade/
                                             # death/attack/upkeep_boost
    play_map_event(kind)                     # buy_plot / tile_placement
    watch(scene)                             # per-frame: death + attack detect
    payday(state, tilemap)                   # upkeep_boost, <=1 per family
```

- **Every play is exactly one call**:
  `self._audio.play_slot(default_slot, override_slot, bus="sfx", key=<slot path>,
  rng=self._rng)`. `GameSounds` computes the two dicts and the key string and
  nothing else. It does not import `pygame`, does not resolve file paths, does
  not own volume, and does not call `bank.resolve` itself.
- **The family override key is the building's `SUBTREE` class tuple**
  (`game/buildings/building.py:39`; e.g. `("DefenceBuildings", "BasicDefence")`
  at `game/buildings/defender.py:12`, `("EconomyBuildings", "Musicians")` at
  `game/buildings/musician.py:12`). ONE private helper,
  `_family_sounds(building)`, walks `buildings_balance` down that tuple and
  returns the family's sounds node or `{}`. **This helper is the single place
  the per-family JSON shape is known.**
- **The key case is SPLIT, and that is intentional — not a typo.** SD-1 shipped
  capital `Sounds` on the global node (`buildings.BuildingsGlobal.Sounds.<kind>`)
  and lowercase `sounds` on each of the 12 leaf families
  (`DefenceBuildings.BasicDefence.sounds.<kind>`). The capital matches the
  domain-level group naming of every other `BuildingsGlobal` child; the lowercase
  matches the leaf families' own field naming. `_family_sounds()` reads
  `sounds` (lowercase) and the global reader reads `Sounds` (capital);
  say so in a comment there, or a reviewer will "correct" one of them.
- **Everything is duck-typed and None-safe.** A `scene` with no buildings, a
  building with no `SUBTREE`, a balance dict with no `Sounds` key, an audio
  module whose mixer never initialised — all resolve to a silent return. Copy
  `FloaterManager._play`'s degrade-never-raise contract
  (`game/ui/effects.py:755`). `play_slot` returning `False` is normal, not an
  error to log.
- **Two watchers, one dict each**, both with the id-keyed eviction pattern
  `watch_enemies` uses (`game/ui/effects.py:904-906`): `_building_alive` (death)
  and `_attack_cooldowns` (attack). Do NOT modify `FloaterManager` to piggyback
  — a separate watcher keeps `game/ui/effects.py` (1829 lines, VFX-owned) out of
  this phase's diff entirely and makes the whole module unit-testable with a
  hand-built `Scene`.
- **The panel reaches the seam through a host-set callback**, exactly like
  `gp["panel"].on_build_vfx = gp["floaters"].spawn_building_vfx`
  (`game/main.py:1118`). `BuildingUI` gains ONE optional attribute
  `on_sound = None` beside `on_build_vfx`, and calls
  `self.on_sound(kind, building)` guarded by `if self.on_sound is not None:`.
  `game/ui/` must not import `game.sounds` and must not know what a bus is.
- **Bus**: everything in this phase is `bus="sfx"` (§2.2 — the bus is fixed by
  where the slot lives, never a data field a designer can mis-set). `loop=` is
  never passed in this phase.

---

## 3. File scope + shared-file contract

### The override-resolution rule (§2.1, verbatim — this is the contract)

> **`clips: []` on a global default = silence. `clips: []` on an element
> override = inherit the default.** Both layers are always present in the JSON
> (full `required` per `data/CLAUDE.md`), so the form always renders them and no
> "create the override key" machinery is needed.

SD-2's `engine.audio.bank.resolve(default_slot, override_slot=None)` already
implements this, and `play_slot` calls it. Pass both layers; do not re-derive
it, and do not add a second "is this empty" test in `game/sounds.py`.

### `gp["sfx"]` — the type, stated for SD-5 / SD-6 / SD-7

**`gp["sfx"]` is an instance of `game.sounds.GameSounds`** — the game-side
dispatcher, NOT the `engine.audio` module.

**It has PROCESS lifetime, not run lifetime** (orchestrator decision, 2026-08-18).
It is constructed ONCE in `main()` at boot (anchor 5, `:884`), seeded straight
into the `gp` literal (anchor 4), and **is never cleared** — not by
`teardown_gameplay()`, not between runs. So it is non-`None` from `:885` onward
for the whole process, including the main menu, Settings, Credits and the
game-over screen.

Why: SD-6's UI click sink forwards to `gp["sfx"]`, and menu/Settings buttons must
click audibly *before any run exists*. A run-scoped dispatcher would leave the
entire shell silent, and quitting to menu would silence it again.

It holds no run state — only the two balancing dicts, an RNG and two watcher
caches keyed by `id(building)`. The watcher caches are the one thing that
survives a run it should not: **`GameSounds.watch()` must self-evict** (the
`id`-keyed `seen`-set eviction at `game/ui/effects.py:904-906`), which it already
does per frame, so a torn-down world's ids drain on the next run's first frame.
Do not "fix" this by clearing the object.

SD-5's decision to bypass `gp` and import `engine.audio` directly (degrading to
a silent no-op if SD-4 has not landed) is compatible and needs nothing from
SD-4: both paths call the same `play_slot`, and the cooldown/cap buckets are the
`key=` strings, not the caller.

### New files

- `game/sounds.py`
- `tools/tests/test_sound_triggers_buildings.py`

### Modified files

- `game/ui/building_ui.py` — add `self.on_sound = None` beside
  `self.last_placed_type = None` (`:970`); call it at three success sites:
  `_do_place` beside `:2470`, and the upgrade + advance success branches inside
  `_upgrade_click`'s `action_btn` branch (`:2251`ff). No other change; the panel
  stays pygame-free and must not import `game.sounds`.
- `game/main.py` — see the contract below.
- `game/CLAUDE.md` — one short section documenting the `game/sounds.py` seam and
  the `on_sound` callback, in the same voice as the "VFX variant selection"
  section. Do NOT touch the root `CLAUDE.md` or another package's doc.

### `game/main.py` — SHARED FILE contract (SD-6 and SD-7 also touch it)

SD-4 makes **ten** edits to `game/main.py` (2705 lines), each ONE contiguous
block, each anchored to existing content. Nothing else in the file is SD-4's.
Anchor 7 is listed because it is a deliberate **no-edit** that a reviewer would
otherwise flag as a bug — it is not one of the ten.

Rows are listed in FILE order, so the numbering runs 1, 2, 3, 5, 4, 6…
— anchor 5 (`:884`) precedes anchor 4 (`:1019`), and must: the `gp`
literal seeds itself from the local anchor 5 binds.

| # | Anchor (current line) | SD-4's edit |
|---|---|---|
| 1 | `from engine.audio import play_music` — **`:67`** | Insert ONE line immediately AFTER it: `import engine.audio as game_audio  # SD-4`. **Do not modify `:67` itself** — SD-7 owns that line (it retires the boot track); SD-7 must keep the new `:68` line. Import `engine.audio` only, never a submodule. |
| 2 | `from game.map.wall_render import FRONT_SIDES, WALL_CATEGORY` — **`:117`** | Insert ONE line immediately AFTER it: `from game.sounds import GameSounds  # SD-4`. (Chosen over the `game.ui` import block so a UI-import change in SD-6 cannot collide.) |
| 3 | `pygame.init()` — **`:747`** | Insert ONE contiguous block (≤4 lines incl. comment) immediately AFTER it: `game_audio.init(data_dir)`. `data_dir` is already resolved at `:730`. It returns `bool` and never raises — **do not branch on it, do not log a failure**; a machine with no device is a supported configuration. This is the ONLY `init` in the game; SD-6's bus sliders and SD-7's music must reuse it, never add a second. The dispatcher is NOT built here — `buildings_balance`/`map_bal` do not exist yet (see anchor 5). |
| 5 | `vfx_balance = load_balance(data_dir, "vfx")  # ESV-3a: procedural VFX params` — **`:884`**, the last line of the balancing-load run at `:880-884` | Insert ONE contiguous block (≤3 lines incl. comment) immediately AFTER it: `sounds = GameSounds(buildings_balance, map_bal)`, a plain `main()` local. **This is BOOT, not `build_gameplay()`.** `:884` is the earliest point where both dicts exist (`map_bal:880`, `buildings_balance:881`) and it is still 84 lines before `shell = Shell(...)` at `:968`, so the object provably exists before any click can reach the shell. Nothing is added to `build_gameplay()`; `:1089` is NOT touched. |
| 4 | the `gp = {` literal — **`:1019-1029`**, last key line `"tutorial": None, "tutorial_message": None}` (`:1029`) | Add ONE key `"sfx": sounds,` on its own line immediately BEFORE `:1029` — seeded with the boot-built object from anchor 5, **not `None`**. This key is the registry entry every later phase reads; it is simply never `None` after `:885`. |
| 6 | `gp["panel"].on_build_vfx = gp["floaters"].spawn_building_vfx` — **`:1118`** | Insert ONE line immediately AFTER it: `gp["panel"].on_sound = gp["sfx"].play_building_event`. |
| 7 | the key tuple in `teardown_gameplay()` — **`:1171-1173`** | **DO NOT TOUCH IT. `"sfx"` must NOT be added to that tuple.** The dispatcher deliberately survives teardown so the player returns to an audible main menu (SD-6's click sink reads `gp["sfx"]`). Nulling it here would silence every menu after the first quit-to-menu — this looks like an omission next to the 14 keys that ARE cleared, and it is not. Leave a one-line comment saying so at the tuple, or a reviewer will "fix" it back. |
| 8 | `elif panel.last_unlocked:` … `panel.last_unlocked = False` — **`:1476-1478`** | Insert the two map plays INSIDE that branch, immediately after `gp["tutorial"].on_tile_unlocked()` (`:1477`): `buy_plot` then `tile_placement`. |
| 9 | `panel.open_for_tile(gp["sel"][0], …)` in `update_selection` — **`:1627-1628`** | Insert ONE line immediately AFTER the call: the selection play, guarded on the primary tile's `occupant`. |
| 10 | `panel.open_for_tile(picked[0], …)` in `finish_drag_select` — **`:1664`** | The same ONE line. (`:1581`, the drag-select DESELECT path, is deliberately NOT a selection sound.) |
| 11a | `gp["floaters"].begin_payout(session.state)` — **`:2202`** | Insert ONE line immediately AFTER it: `gp["sfx"].payday(session.state, world.tile_map)`. |
| 11b | `gp["floaters"].watch_enemies(world.scene)` — **`:2300`** | Insert ONE line immediately AFTER it: `gp["sfx"].watch(world.scene)`. |

Rules for reconciliation:
- **Never edit `:67`, and never edit `:998-999`** (the `if max_frames is None:`
  guard and `play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav",
  loop=True)`). Both are SD-7's; they sit between anchors 1 and 4, and deleting
  either here would silence the game mid-plan.
- **Never touch `game/ui/settings.py`, `game/ui/widgets.py`, `game/ui/shell.py`
  or `game/ui/overlays.py`** — those are SD-6's.
- Do not reorder or reformat any anchor line; SD-6/SD-7 reconcile by content.
- **`gp["sfx"]` is never `None` after `:885`** — no call site needs a `None`
  guard, and none should add one. What call sites DO need is a `gp["world"]`
  guard where they already had one: anchors 11a/11b sit inside the existing
  world-update block, and anchors 8/9/10 inside existing panel branches, so they
  inherit those guards unchanged.

### Explicitly OUT of scope

`engine/**`, `data/schemas/**`, `data/balancing/*.json` (SD-1 shipped the empty
slots; SD-4 imports no clip and seeds no default), `game/enemies/**` (SD-5),
`game/core/payday.py` (read its ledgers from the host; do not add an audio call
inside the payday ordering — it is prototype-exact and sacrosanct,
`game/CLAUDE.md`), and `game/ui/effects.py`.

---

## 4. Exit gate + Quick Test

### Tests to write (bare minimum — one file, no more)

`tools/tests/test_sound_triggers_buildings.py`, driving `game/sounds.py`
DIRECTLY with a fake audio object recording every
`play_slot(default, override, bus=, key=, …)` call. Do not boot `game/main.py`
and do not build a window.

1. Each of the six building kinds calls `play_slot` once, with the family's
   override as `override_slot`, the global as `default_slot`, `bus="sfx"`, and
   the slot path as `key=`.
2. The engine, not `GameSounds`, owns the empty-clips rule: a `GameSounds` with
   a family that has no sounds node passes `override_slot=None` (or `{}`) rather
   than skipping the call, and a missing global still results in no crash.
3. `buy_plot` and `tile_placement` each fire once per `play_map_event` call.
4. `watch(scene)`: a building whose `alive` flips fires `death` exactly once (a
   second `watch` pass fires nothing); an `Attacker.cooldown` that GREW fires
   `attack`, one that shrank does not.
5. `payday`: two buildings of the same family with upkeep produce ONE
   `upkeep_boost` call.
6. `_family_sounds` reads the lowercase leaf key while the global reader reads
   the capital one — one assertion, so the split cannot be silently "tidied"
   away.

Seed any RNG you inject (`game/CLAUDE.md`'s standing rule). Use
`tools/tests/fixture_data.FIXTURE_DATA` or a pinned in-test balance dict — never
assert against live `data/` content, and never write into `data/`.

### Exit gate (run exactly these — nothing else)

```
py tools/smoke.py
py -m pytest tools/tests/test_sound_triggers_buildings.py -q
py -m pytest tools/tests/test_audio.py -q
```

(The second pytest run is here only because SD-4 adds the `game_audio.init` boot
call that `test_audio.py`'s graceful-degradation invariant covers.)

**Do not run `py tools/testgate.py check`, do not pass `--affected`, and do not
run a tier sweep (`-m core` / `-m editor` / `-m meta`).** The `test_guard.py`
hook denies all of them from a subagent; the single full gate belongs to the
main session at handoff (§"Test Suite Policy", root `CLAUDE.md`). Your bar is
the two targeted runs above: zero failures, zero unexpected skips.

### Quick Test (in-game — the orchestrator or the user runs this)

With **no clips imported** (today's data), first prove the no-op:

0. `py game/main.py` → sit on the main menu, start a run, play a full round,
   quit to menu, start a second run. Nothing sounds different (the SD-7 boot
   track still plays, untouched), nothing crashes, no new warning spam in the
   terminal, and the second run behaves exactly like the first — that last part
   is what proves the boot-lifetime dispatcher survives teardown cleanly. This is
   the real regression test for the phase.

Then, with SD-3's editor available, import ONE short clip into
`buildings.BuildingsGlobal.Sounds.placement` and one into `map.Sounds.buy_plot`,
Save, and:

1. `py game/main.py` → buy a plot → the buy-plot clip plays **once**, even on a
   multi-chunk purchase.
2. Place a defence building → the placement clip plays once. Place a 3-tile
   batch → still once.
3. Select it → silence (its slot is empty) — and confirm that is silence, not a
   traceback.
4. Import a clip into `DefenceBuildings.BasicDefence`'s `attack` override, Save,
   reboot → let it shoot: the override plays, and a firing line does not turn to
   mud (SD-2's cooldown/cap holding on the `key=` bucket).
5. Empty that override's `clips` again, Save, reboot → the global default plays
   instead (the §2.1 inherit rule, live).

---

## Decisions taken (orchestrator, 2026-08-18) — do not re-litigate

1. **`map.Sounds.tile_placement` fires ONCE per successful purchase, layered
   with `buy_plot`** (coin + ground). The per-2x2-chunk alternative is
   **rejected**: it needs a new `BuildingUI` transient and stacks 3-4 plays on
   one click.
2. **The per-family key case is split on purpose** — capital `Sounds` on
   `BuildingsGlobal`, lowercase `sounds` on the 12 leaf families. Handle both in
   `_family_sounds()`; see §2.
3. **`upkeep_boost` stays capped at ≤1 play per distinct family per payday.**
4. **`GameSounds` is built at BOOT** (anchor 5, `:884`) and **survives
   teardown** (anchor 7 is a deliberate no-edit). `gp["sfx"]` is never `None`
   after `:885`. See §3.

## Cross-phase notes (from the orchestrator — informational, no action)

- **SD-7 deletes `:67` while SD-4 inserts at `:68`.** This is the phases' only
  textual collision and **the orchestrator resolves it at merge**. Write your
  insertion exactly as anchor 1 says and do not try to coordinate around it.
- SD-7's `game/main.py` set is {`:67`, `:998-999`, plus its own E–K anchors} —
  otherwise disjoint from SD-4's.
- SD-6's anchors are `:832`, `:968-970`, `:1210-1214` — no overlap with SD-4's.
- A slot `core.Sounds.Game.game_over` exists in SD-1's data. **SD-7 fires it,
  not SD-4** — do not wire it here.

## Remaining open questions

None. Everything this brief flagged has been ruled on above; if the code
disagrees with a cited line, report it rather than improvising.
