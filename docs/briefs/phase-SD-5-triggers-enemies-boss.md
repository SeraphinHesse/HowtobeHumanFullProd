# Phase SD-5 — Triggers: enemies + boss (game)

Source plan: `planning/SoundEditorPLAN.md` §2.1 (slot shape), §2.2 (buses),
§2.3 (checklist → slot map), "Phase SD-5". Base branch: the SD umbrella branch.

**Consumes, never re-implements:** the `engine/audio/` API published by SD-2
(`engine.audio.sfx.play(clip, bus)` and friends) and the schemas + balancing
subtrees published by SD-1 (`enemies.EnemySounds`, `enemies.EnemyTypes.<Type>.sounds`).
**Do NOT edit `engine/**` or `data/schemas/**` or `data/balancing/**` in this phase.**
All citations below were re-verified in the `SoundEditor` worktree on 2026-08-18.

---

## 1. Behavioral spec (with citations)

Every row this phase fires, named by its §2.3 path. All of them are on the
**`sfx` bus** (§2.2: `music` is only `core.Sounds.Music.*`; everything else is
`sfx`).

### 1.1 `enemies.EnemySounds.death` (+ per-type overrides)

Fires **once per enemy, at the single sweep where an enemy is confirmed dead and
despawned**: `game/enemies/combat.py:690-697` —

```
690:    for enemy in scene.by_tag("enemy"):
691:        if not enemy.alive:
...
695:            if on_enemy_death is not None:
696:                on_enemy_death(enemy)
697:            scene.despawn(enemy)
```

This is the correct and ONLY seam because:

- It is the one place `alive` flipping False is acted on for **every** type
  (`combat.py:695` is where `Session.on_enemy_death` is already called).
- An enemy that reached the hole was already despawned by
  `_resolve_base_arrivals` at `combat.py:688` and can never reach this sweep
  (`combat.py:692-694` states exactly this) — so a base arrival makes **no**
  death sound. That is intended and must not be "fixed" here.
- A boss in its delayed second phase is `alive == True` until `phase_complete`
  (`game/enemies/enemy.py:417`, and `game/enemies/CLAUDE.md`'s second-phase
  section), so the boss's death sound fires **once**, at its real death, not at
  the phase crossing.
- A retagged kidnapper is no longer tagged `"enemy"` (`game/enemies/kidnap.py`),
  so carrying a building home is not a death.

Per-type override: the enemy's own `EnemyTypes` block (see §1.5). So
`enemies.EnemyTypes.Boss.sounds.death` (the "boss death sound" checklist row)
needs **no boss-specific call site** — it is this one site resolving the Boss's
override.

### 1.2 `enemies.EnemySounds.attack` (+ per-type overrides), incl.
`enemies.EnemyTypes.Boss.sounds.attack` and
`enemies.EnemyTypes.SiegeCannon.sounds.attack`

An enemy "attacks" at exactly **three** sites, all in
`game/enemies/components.py`, and all three are one cooldown-gated swing:

1. **The edge-WALL branch** — `EnemyCombat.update`, `components.py:877` (def),
   the fire happens under `if self.cooldown <= 0:` at `components.py:895-908`
   (`tm.damage_wall(*wall, dmg)` at `:899`, cooldown re-armed at `:908`).
2. **The BUILDING branch** — same method, `components.py:926-944`
   (`health.damage(dmg)` at `:931`, `RoundStats` credit at `:933-935`, cooldown
   re-armed at `:944`). This branch serves **melee AND ranged** units alike:
   NE-1 widened the gate at `components.py:885` from `pa.blocked` to
   `pa.blocked or pa.in_range`, so the Sniper's stand-off shot is this same
   swing (`game/enemies/CLAUDE.md`, "Ranged stand-off"). **Do not add a second
   attack path** — that doc says so explicitly.
3. **The Digger eruption** — `BurrowAgent._strike`, `components.py:1229-1249`
   (`health.damage(dmg)` at `:1242`). It is documented as
   "`EnemyCombat.update()`'s single-target damage application, verbatim"
   (`components.py:1230-1234`), so it is an attack and gets the sound.

The Boss and the SiegeCannon are ordinary melee units and go through site 2, so
`EnemyTypes.Boss.sounds.attack` and `EnemyTypes.SiegeCannon.sounds.attack` (the
"cannon/boss attack sound" checklist row) are, again, the per-type resolution of
this one seam — **no type-name branch anywhere in the code**.

Fire the sound **inside the `if self.cooldown <= 0:` body, at the point the
cooldown is re-armed**, so one swing = one sound, and a blocked-but-cooling unit
is silent.

### 1.3 `enemies.EnemyTypes.Boss.sounds.spawn`

Fires at the wave pop in `game/enemies/spawner.py:522-535`:

```
528:            tile, etype, delay = self._queue.pop(0)
531:            era = self._boss_era if etype == "boss" else self._era
532:            enemy = create_enemy(...)
534:            self._attach_scene(enemy, scene)
535:            scene.spawn(enemy)
```

Fire it immediately after `scene.spawn(enemy)` at `:535`, for **every** popped
enemy — resolved through the same per-type machinery, so a type with no authored
`spawn` clips is a silent no-op and only the Boss is audible today.

**Decision — do NOT fire spawn at `Spawner._spawn_child` (`spawner.py:584-596`).**
That is the death-swarm / second-phase child path
(`spawn_death_swarm:549-562`, `_advance_second_phases:600`); a 55-child era-4
burst is precisely the load case §5 of the plan flags, and §2.3 authors no
child-spawn row. State this in a code comment so a later phase does not "fix" it.

### 1.4 Silence and load

- A resolved slot with no clips is a **no-op**, never a crash and never a log
  line per enemy.
- A 40-enemy wipe in one frame runs §1.1 forty times in one loop. SD-5 does
  **not** implement its own throttle: SD-2's per-slot cooldown and
  max-concurrent cap are the mechanism (plan §5, "Channel exhaustion / mix mud …
  load-bearing for SD-5"). SD-5's obligation is only to call `play` once per
  event and let SD-2 clamp.
- Headless-safe throughout: `engine/audio` keeps `engine/audio.py`'s
  swallow-and-continue guard (SD-2 decisions), so `SDL_AUDIODRIVER=dummy`, a
  quit mixer, or `sfx.init()` never having run all degrade to silence.
  **Game logic never touches pygame for audio** — the only audio call in this
  phase is `engine.audio.sfx.play`.

### 1.5 How a type is identified — by FIELD, never by convention (D7)

The `EnemyTypes` key for a live enemy is its class's **`STAT_SUBTREE`**, which
is already "under EnemyTypes; drives EVERY lookup" (`game/enemies/enemy.py:110`)
and is a 1-tuple on all ten types: `Standard` (`enemy.py:110`), `Raider`
(`:578`), `SiegeCannon` (`:587`), `Formation` (`:612`), `Sniper` (`:646`),
`Commander` (`:682`), `Tutorial` (`:700`), `Digger` (`:733`), `Drummer`
(`:800`), `Boss` (`:834`).

**Use `STAT_SUBTREE`, never `ETYPE` and never `REGISTRY_GROUP`.**
`data/schemas/enemies.schema.json:663-667` warns that the registry label is not
the `EnemyTypes` key (`Standard → "Walker"`, `SiegeCannon → "Siege Cannon"`),
and `ETYPE` is lowercase and differs again (`"siege"`, `enemy.py:584`). The
Tutorial walker shares `REGISTRY_GROUP = "Walker"` with Standard
(`enemy.py:698`) but has its own subtree — another reason `STAT_SUBTREE` is the
only correct key.

The balancing dict is already on every enemy: `self._balance = enemies_balance`
(`game/enemies/enemy.py:207`, an E-11-legal transient beside `_tilemap`). **No
new plumbing, no new constructor argument, no host wiring is needed to reach
`EnemySounds` / `EnemyTypes.<Type>.sounds`.**

---

## 2. Architecture plan

One new module, `game/enemies/sounds.py`, plus four call sites.

### 2.1 `game/enemies/sounds.py` (new, ~60 lines)

The single dispatch seam for this package — the `game/ui/effects.py::_play`
shape SD-4 uses for buildings, and the same "one seam, no file names in
`game/`" rule (plan §SD-4 decisions).

```
DEATH, ATTACK, SPAWN = "death", "attack", "spawn"

def slot_for(enemy, kind) -> dict | None      # PURE. resolution only.
def play_enemy_sound(enemy, kind) -> None     # slot_for + engine.audio.sfx.play
```

- `slot_for(enemy, kind)` reads `enemy._balance` and `type(enemy).STAT_SUBTREE`,
  then applies the §2.1 override rule (quoted verbatim in §3.3 below) via
  `engine.audio.bank.resolve(default_slot, override_slot)` — **SD-2's pure
  resolver; do not write a second one.** It returns the resolved slot (or
  `None`).
- `play_enemy_sound` calls `sfx.play(clip, "sfx")` with the clip SD-2's
  `bank.pick_clip` chooses. If SD-2's `sfx.play` already takes a slot, pass the
  slot — read `engine/audio/sfx.py`'s actual published signature first and match
  it; do not invent a wrapper API.
- Import style: `from engine.audio import sfx` at module scope, then
  `sfx.play(...)`. This is what makes the tests trivially fake-able
  (monkeypatch `game.enemies.sounds.sfx`) with **no new global seam** of the
  `components.set_damage_hook` kind.
- Every failure mode is silence: no enemy `_balance`, no `sounds` key, no
  clips, `sfx.init()` never called, mixer absent. Never raises — one enemy with
  odd data must not take down the frame that killed it.
- No pygame import. No `data/` I/O. No file names.

### 2.2 Call sites (four edits, all one line + a comment)

| Slot | File | Anchor |
|---|---|---|
| `death` | `game/enemies/combat.py` | inside `if not enemy.alive:` at `:691`, **before** `scene.despawn(enemy)` at `:697` (the object must still be in the scene / fully readable) |
| `attack` (wall) | `game/enemies/components.py` | in the `if self.cooldown <= 0:` body, beside `self.cooldown = self.buffed_attack_speed` at `:908` |
| `attack` (building + ranged) | `game/enemies/components.py` | same, beside `self.cooldown = self.buffed_attack_speed` at `:944` |
| `attack` (Digger eruption) | `game/enemies/components.py` | end of `_strike`, after the `_damage_hook` block at `:1246-1249` |
| `spawn` | `game/enemies/spawner.py` | after `scene.spawn(enemy)` at `:535` (the wave pop only — see §1.3) |

`components.py` reaches the owner via the `owner` local both sites already hold
(`components.py:878`, `:1229`). Import `sounds` **lazily inside the function** in
`components.py` if a module-scope import would close a cycle
(`sounds.py` imports nothing from `game.enemies`, so it should not — verify, do
not assume).

### 2.3 What this phase deliberately does NOT do

- No new balancing keys, no schema edits, no `data/` writes.
- No throttle/cooldown of its own (§1.4).
- No `game/main.py` bootstrap (§3.2).
- No change to `Session.on_enemy_death`, `game/core/session.py` or
  `game/core/boss_bonuses.py`. The plan's SD-5 file list named them for boss
  spawn; **that turned out to be unnecessary** — boss spawn is the spawner's
  wave pop (§1.3), inside `game/enemies/`. Staying out of `game/core/` keeps
  SD-5 out of SD-7's way.

---

## 3. File scope + shared-file contract

SD-5 runs **in the same wave as SD-4 / SD-6 / SD-7**. Its whole file scope is
inside `game/enemies/**` plus one new test file.

### 3.1 Files

**New**
- `game/enemies/sounds.py`
- `tools/tests/test_sound_triggers_enemies.py`

**Modified (all owned solely by SD-5 in this wave)**
- `game/enemies/combat.py` — one call inside the death sweep, `:690-697`.
- `game/enemies/components.py` — three calls, at `:908`, `:944`, `:1249`.
- `game/enemies/spawner.py` — one call after `:535`.
- `game/enemies/__init__.py` — export `play_enemy_sound` / `slot_for` beside the
  existing re-exports (`__init__.py:6-20`, `__all__` from `:22`), keeping
  `__all__` sorted as it already is.
- `game/enemies/CLAUDE.md` — a short "Sounds (SD-5)" section: the four call
  sites, `STAT_SUBTREE`-as-the-key rule, and the "no spawn sound for
  `_spawn_child`" decision.

### 3.2 `game/main.py` — **NOT NEEDED. Verified.**

SD-5 needs **no** edit to `game/main.py`, and must not make one.

- **Reason it is not needed:** the balancing dict is already on every enemy
  (`game/enemies/enemy.py:207` `self._balance = enemies_balance`), and SD-2
  publishes `engine.audio.sfx` as a **module-level** API
  (`init()` / `play(clip, bus)` / `set_bus_volume` / `stop_all`, plan §SD-2
  Files), so `game/enemies/sounds.py` imports it directly. There is nothing for
  a host to hand down.
- **What SD-5 consumes from SD-4:** the single `sfx.init(data_dir)` call SD-4
  adds after `pygame.init()` (`game/main.py:588`) and the `gp["sfx"]` registry
  entry (`gp` built at `game/main.py:825`). **SD-5 must NOT add its own
  bootstrap** and must not read `gp`. If SD-4 has not landed when SD-5 runs,
  every enemy sound is silently a no-op and every test still passes — that is
  the intended degradation, not a bug to work around.
- If, contrary to this analysis, an implementer concludes a `main.py` edit IS
  required: **stop and report it to the orchestrator instead of editing.**
  SD-4 owns `game/main.py` this wave, and the two anchor lines that would
  collide are `game/main.py:588` (`pygame.init()`) and `game/main.py:825`
  (the `gp` literal).

### 3.3 The override-resolution rule (§2.1, verbatim)

> **`clips: []` on a global default = silence. `clips: []` on an element
> override = inherit the default.** Both layers are always present in the JSON
> (full `required` per `data/CLAUDE.md`), so the form always renders them and no
> "create the override key" machinery is needed.

Here the *global default* layer is `enemies.EnemySounds.<kind>` and the *element
override* layer is `enemies.EnemyTypes.<STAT_SUBTREE[0]>.sounds.<kind>`.
Implement it by **calling SD-2's `engine.audio.bank.resolve(default_slot,
override_slot)`**, not by re-deriving it.

### 3.4 Open question for the orchestrator

§2.3 authors a **global** row for `death` and `attack` only; `spawn` appears
solely as `EnemyTypes.Boss.sounds.spawn`. Whether SD-1 ships an
`EnemySounds.spawn` default key is therefore not settled by the plan. SD-5 must
read the default layer defensively for `spawn` (a missing key ⇒ "no default" ⇒
the Boss override alone decides) — a **shape** fallback across a phase boundary,
exactly the reading `game/enemies/enemy.py:190-196` documents for
`phase.get("delayed_spawns", …)`, **not** a G-7 code-side default for an
authored value. If SD-1 did ship the key, index it directly. Confirm against the
landed `data/schemas/enemies.schema.json` before writing the resolver.

---

## 4. Exit gate + Quick Test

### Exit gate (run exactly these — nothing else)

```bash
py tools/smoke.py
py -m pytest tools/tests/test_sound_triggers_enemies.py -q
py -m pytest tools/tests/test_enemies.py -q
```

Both pytest runs are targeted at this phase's files (the new trigger test, plus
the existing enemy suite that pins the touched `combat.py` / `components.py` /
`spawner.py` behaviour). Read the one line each prints; the gate is ZERO.

**Do not run** `py tools/testgate.py check`, `--affected`, or a tier sweep
(`-m core` / `-m editor` / `-m meta`) — the `test_guard.py` hook denies all of
them for a subagent, and the single full gate belongs to the main session at
handoff (root `CLAUDE.md` §"Test Suite Policy" is the authority).

### Tests — BARE MINIMUM (five; do not add more)

`tools/tests/test_sound_triggers_enemies.py`, headless, pure, no pygame, a fake
`sfx` monkeypatched onto `game.enemies.sounds` recording `(slot, clip)` calls,
and a **pinned balancing fixture** (never live `data/`; never write into
`data/`).

1. **death fires once** — an enemy whose `alive` is False goes through
   `resolve_combat`'s sweep and records exactly one `death` play.
2. **attack fires on a swing** — a blocked `EnemyCombat` with an expired
   cooldown records exactly one `attack` play; the same component ticked again
   while cooling records none.
3. **per-type override wins** — a `SiegeCannon` (and a `Boss`) with an authored
   `sounds.attack` resolves to that clip; a type with an empty override
   (`clips: []`) falls back to `EnemySounds.attack`.
4. **empty default is a silent no-op** — an empty `EnemySounds` slot with an
   empty override plays nothing and raises nothing.
5. **boss spawn** — a `Spawner` wave pop of a `"boss"` entry records one `spawn`
   play; a `_spawn_child` call records none (§1.3).

Seed any RNG a test's outcome depends on (`game/CLAUDE.md`, "Seed the RNG").

### Quick Test (in-game — the orchestrator or the user runs this, not the coder)

`py game/main.py` →
1. Play to any ordinary wave: walkers dying make the default death sound; a
   walker punching a wall/building makes the default attack sound.
2. Reach a wave with **siege cannons** — their attack is audibly *different*
   from the default (that is the whole point of the per-type override row).
3. Reach a **boss round** (`round_in_era == boss_round_in_era`): the boss's
   spawn sound plays as it enters, its attack sound plays when it hits a
   building, and its death sound plays once when it actually dies — **not** when
   it freezes into its second phase.
4. A 30–40 enemy wipe in one frame is a burst, not a wall of mud (SD-2's cap
   doing its job).
