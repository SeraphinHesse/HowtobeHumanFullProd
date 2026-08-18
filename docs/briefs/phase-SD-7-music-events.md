# Phase SD-7 — Music and round/game events (game)

Source plan: `planning/SoundEditorPLAN.md` §2.1 (slot shape), §2.2 (buses),
§2.3 (checklist→slot map), "Phase SD-7". Depends on **SD-1** (schemas +
`data/balancing/core.json` subtrees) and **SD-2** (`engine/audio/` package).

**You may not edit `engine/**` or `data/schemas/**`.** SD-2 owns the audio API,
SD-1 owns the schemas. If either is missing what you need, stop and report it —
do not re-implement it here.

### SD-2's pinned audio API (import ONLY `engine.audio`)

Confirmed by the SD-2 planner, 2026-08-18. Every call returns `bool` and
**never raises**:

- `engine.audio.music.play_slot(slot, *, rng=None, loop=None) -> bool`
- `engine.audio.music.play(clip, *, loop=True, force=False) -> bool` — **playing
  the file that is already playing is a no-op returning True**. That is most of
  §1.2's "never restart the stream" rule for free; do not build a second
  identity cache on top of it, and never pass `force=True` from this phase.
- `engine.audio.music.push(clip, *, loop=False) -> bool` /
  `engine.audio.music.pop() -> bool` — a stack.
- `engine.audio.music.current() -> dict | None`, `engine.audio.music.stop()`
- `engine.audio.bank.resolve(default_slot, override_slot=None)` — the §2.1
  override→default→silence rule. **Do not re-implement it.**
- `engine.audio.sfx.play_slot(slot, *, loop=False)` for the sfx bus.

`gp["sfx"]` is **SD-4's game-side dispatcher object**, not the raw
`engine.audio.sfx` module. Consume what SD-4 registers; add no bootstrap of your
own.

All line numbers below were re-verified in the `SoundEditor` worktree on
2026-08-18. The plan doc's own SD-7 citations have DRIFTED (it says
`game/main.py:785` and `game/ui/cutscene_player.py:66`; the real boot-track site
is `game/main.py:999`, its import `:67`). Re-check with `grep -n` before editing
if the file has moved under you.

---

## 1. Behavioral spec

### 1.1 Slots this phase consumes (all created by SD-1)

Music bus — `pygame.mixer.music`, **streaming, exactly ONE at a time**
(`planning/SoundEditorPLAN.md:165`):

| Slot | Plays when |
|---|---|
| `core.Sounds.Music.default` | fallback for every music slot below whose `clips` is empty |
| `core.Sounds.Music.menu` | shell is in a menu state (main menu, settings, credits, add-name, high scores) |
| `core.Sounds.Music.cutscene` | a cutscene is playing and the cutscene entry carries no companion `audio` of its own |
| `core.Sounds.Music.building_phase` | gameplay, phase in {BUILDING, ROUND_END, LEVELUP, INCOME, BOSS_CUTSCENE} |
| `core.Sounds.Music.combat_phase` | gameplay, phase in {ENEMY, ENEMY_INTRO} |

SFX bus — `pygame.mixer.Sound` on a pooled channel:

| Slot | Fires on |
|---|---|
| `core.Sounds.Ambient.default` | started once when audio is enabled; loops forever |
| `core.Sounds.Game.game_start` | a new run is built (`build_gameplay`) |
| `core.Sounds.Game.round_start` | the wave actually spawns — the edge into `GamePhase.ENEMY` |
| `core.Sounds.Game.round_win` | the round ends with no life lost |
| `core.Sounds.Game.round_loss` | a round ends having lost a life **and the run continues** |
| `core.Sounds.Game.game_over` | the fatal breach — lives hit 0 (see §1.3) |
| `core.Sounds.Game.level_up` | `RunState.village_level` increases |

**`core.Sounds.Ambient` rides the `sfx` bus, NOT the music bus** — decision D6
(`planning/SoundEditorPLAN.md:60-61,166`). It is a looping `sfx.play` and it is
NOT part of the one-stream music arbitration below: ambient plays *concurrently*
with whatever music is playing, and the SD-6 SFX slider governs its volume.
Putting ambient on `pygame.mixer.music` would silence the actual music, because
there is only one music stream.

Every slot resolves **override → default → silence** through SD-2's
`engine.audio.bank.resolve` (`planning/SoundEditorPLAN.md:256-258`): an empty
`clips` on `building_phase` falls back to `Music.default`; an empty
`Music.default` too means silence, not a crash. `core.Sounds.Game.*` and
`core.Sounds.Ambient.default` have no override layer — empty is simply silent.

**Two deliberate deviations from the plan doc, both decided by the orchestrator
after `planning/SoundEditorPLAN.md` was written — SD-1 ships them:**

- The ambient slot is **`core.Sounds.Ambient.default`**, not
  `core.Sounds.Ambient.loop` as `planning/SoundEditorPLAN.md:174` says. The old
  name produced the doubled path `Ambient.loop.loop`, because the slot itself
  already carries a `loop` boolean (§2.1 of the plan). Hard-code `Ambient.default`.
- **`core.Sounds.Game.game_over` is a new slot** beyond the 21-row checklist
  (`planning/SoundEditorPLAN.md:170-198`): the user wants a distinct game-over
  sting. SD-1 adds it; SD-7 fires it.

### 1.2 The music transition rule (one stream, so this is an arbitration)

The director resolves **one winner per frame** from this priority stack, top
wins:

1. **Cutscene** — an intro cutscene (`shell.state == GameState.CUTSCENE`,
   `game/main.py:2026`) or an in-gameplay cutscene (`gp["cutscene"] is not
   None`, `game/main.py:2047`). On the *entering* edge: `music.push(clip)`
   where `clip` is the cutscene entry's own companion audio when it has one
   (`entry.get("audio")` → `game/ui/cutscene_player.py:46-47`), otherwise the
   resolved `core.Sounds.Music.cutscene`. On the *leaving* edge: `music.pop()`,
   which resumes the track that was playing before — this is the documented bug
   at `game/ui/cutscene_player.py:63-69` ("nothing restores it afterward") and
   fixing it is part of this phase.
2. **PAUSED and GAME_OVER hold the current track.** No switch on either. This is
   a statement about the **music bus only** — the game-over *sting*
   (`core.Sounds.Game.game_over`, §1.3) is an **sfx one-shot played OVER the held
   combat track**, not a music change, so the two rules do not conflict: on the
   fatal breach the music keeps streaming untouched and one sfx clip fires.
   Pausing
   must not swap gameplay music for menu music (`GameState.PAUSED` is a member of
   `_MENU_STATES`, `game/ui/shell.py:42-43` — do NOT drive menu music off that
   tuple), and the game-over screen keeps the combat track until the player
   returns to the menu.
3. **Menu** — `shell.state` in {MAIN_MENU, SETTINGS, CREDITS, ADD_NAME,
   HIGHSCORES} → `Music.menu`.
4. **Gameplay** — `shell.state` in the world states, resolved off
   `session.state.phase` (`game/core/phases.py:14-24`): ENEMY / ENEMY_INTRO →
   `Music.combat_phase`; BUILDING / ROUND_END / LEVELUP / INCOME /
   BOSS_CUTSCENE → `Music.building_phase`.

Invariants on top of the stack:

- **Switching to the track that is already playing is a NO-OP.** The director
  holds the currently-playing clip identity and compares before calling
  `music.play`. Ticking every frame must never restart the stream — plan
  decision, `planning/SoundEditorPLAN.md:452-454`.
- **Resolving to silence stops the stream** (`music.stop()`), and the
  "currently playing" identity becomes `None`, so the next non-empty resolution
  starts cleanly.
**Which API each transition uses — explicitly:**

| Transition | Call |
|---|---|
| menu <-> building-phase <-> combat-phase (the whole priority-4/3 arbitration) | `music.play_slot(...)` — **replace**, never push |
| entering a cutscene (intro or in-gameplay) | `music.push(clip, loop=False)` — **stack**, so the underlying phase track survives |
| leaving a cutscene (done, skipped, or released) | `music.pop()` — resumes the stacked track |
| the resolved slot is empty (silence) | `music.stop()` |

Nothing else pushes. A push that is never popped strands the stack, so the
`pop()` must sit on the *same* host edge that calls `release()`
(`game/main.py:2029-2030` and `:2051-2052`) — including the SKIPPED path, which
goes through that same `done` / `release` branch.

The `push`/`pop` pair is SD-2's; do not hand-roll a save/restore. And because
`music.play` already no-ops on the same file, the director needs **no
clip-identity cache of its own** — call `play_slot` and let SD-2 absorb the
repeat. `music.current()` is available if a test wants to assert what is
streaming.

### 1.3 Round win / round loss

The distinction is **did this round cost a life**, which is exactly the branch
`Session.post_sim` already takes at `game/core/session.py:468-472`: the
`_wipe_pending` arm is a base breach (loss), the `elif` arm is a clean wave
clear (win). Both call `_begin_round_end()`.

`game/core` is pure (no pygame — `tools/tests/test_phase_loop.py:585-591`
enforces it), so **do not put an audio call in `session.py`**. Decide host-side
from a lives delta, the precedent already used for the HUD
(`game/ui/hud.py:337` tracks `base_lives` by delta, not by ledger):

- snapshot `session.state.base_lives` on the edge INTO `GamePhase.ENEMY`;
- on the edge INTO `GamePhase.ROUND_END`, fire `round_loss` if
  `base_lives < snapshot`, else `round_win`; each fires **exactly once per
  round**;
- **the fatal breach fires `game_over` ALONE — never `round_loss` as well.**

**Why `game_over` alone (the call you were asked to make, with its reasoning):**

1. *No collision.* Two stings on the same frame, on the same bus, mixed at the
   same instant, is the one thing a distinct game-over sound must not sound
   like. The sting the user asked for has to land clean.
2. *The structure already says so.* `Session.on_base_hit` splits at
   `game/core/session.py:686-692`: the fatal branch sets
   `st.state = GameState.GAME_OVER` and does **NOT** set `_wipe_pending`, so the
   round never reaches `_begin_round_end` and the ROUND_END edge that owns
   `round_win`/`round_loss` is *structurally unreachable* on that frame — and
   `post_sim` returns early on GAME_OVER (`game/core/session.py:655`) for every
   frame after. So the two events already live on two mutually exclusive edges,
   and firing `round_loss` at anchor J would mean *manufacturing* a second event
   that the round machine itself never produced.
3. *It reads right.* "You lost a life, the run goes on" and "the run is over" are
   different beats; the second is not a louder version of the first.

The resulting rule, exhaustive and non-overlapping:

| Frame | Sting |
|---|---|
| ROUND_END edge, `base_lives == snapshot` | `round_win` |
| ROUND_END edge, `base_lives < snapshot` | `round_loss` |
| GAME_OVER mirror edge (`game/main.py:2259-2262`) | `game_over` — and nothing else |

Anchor J therefore fires **`game_over` only**. If a future design does want both,
that is a deliberate change with a stagger, not a coder tidy-up.

`level_up` fires on an increase of `session.state.village_level`
(`game/core/game_state.py:74`, advanced by `game/core/session.py:541`) — again a
host-side delta beside `gp["prev_phase"]`, not an edit to `session.py`.

`round_start` reuses the ENEMY-phase edge the host already computes at
`game/main.py:2223-2226`. `game_start` fires in `build_gameplay()` beside
`shell.enter_gameplay()` (`game/main.py:1154`).

### 1.4 Headless safety (hard requirement)

`tools/smoke.py:79` boots `main(max_frames=FRAMES, autostart=True)` with no
audio device. The current hardcoded track is gated by `if max_frames is None:`
(`game/main.py:998`) precisely so headless runs do no mixer work. **Keep that
gate**: the director is constructed always but *enabled* only when
`max_frames is None`; when disabled, `tick`, the game-event calls and the ambient
start are cheap no-ops that touch neither `pygame.mixer` nor the filesystem.
SD-2's swallow-and-continue guard is the second net, not the first — relying on
it alone would make smoke load a 49 MB WAV on every boot.

---

## 2. Architecture plan

### 2.1 Retiring the hardcoded boot track

**What is being retired**, verbatim, `game/main.py:998-999`:

```python
    if max_frames is None:  # windowed run only — headless tests stay silent/fast
        play_music(data_dir / "audio" / "Bass_and_drum_Duo.wav", loop=True)
```

plus its import, `game/main.py:67`:

```python
from engine.audio import play_music
```

`play_music` has no other use in `game/main.py` (*verified*: `grep -n play_music
game/main.py` returns only `:67` and `:999`), so the import goes with it.

**Does deleting `:67` break the legacy-surface tests? No — verified.**
`tools/tests/test_audio.py` imports the surface directly (`from engine import
audio` at `:13`, calling `audio.play_music` at `:25,29,30,42`); it never imports
`game.main` and never asserts that any particular consumer exists. The other live
consumer, `game/ui/cutscene_player.py:16`, is **not yours to change** — leave
that import exactly as it stands. SD-2 preserves `play_music` / `stop_music` /
`set_volume` on the package, so after this phase the legacy surface has two
pinning consumers instead of three and every test still passes.

*Flag for the orchestrator, not for this phase*: `test_audio.py` asserts
`assertIsNone(audio.play_music(...))` (`:25,29,30`), while SD-2's new API returns
`bool`. The **legacy re-exports must keep returning `None`** or SD-2 breaks that
file. Not SD-7's to fix — raised here because SD-7's gate runs `test_audio.py`.

**What replaces it**: those two lines become the construction of a
`MusicDirector` (below), enabled iff `max_frames is None`. The audio file itself
is neither deleted nor orphaned — `data/audio/Bass_and_drum_Duo.wav` becomes the
seeded clip of `core.Sounds.Music.default` in `data/balancing/core.json`:

```json
"clips": [{"file": "Bass_and_drum_Duo.wav", "volume": 1.0, "start": 0.0, "end": 0.0}],
"loop": true,
"pick": "random"
```

(`file` is relative to `data/audio/` — `planning/SoundEditorPLAN.md:147`. The
clip sits at the root of `data/audio/`, not under `imported/`, because it
predates the importer.) Write it through the validating writer, not by
hand-editing JSON, and leave every other slot empty. Net behaviour: a windowed
boot still plays the same track — now because the default music slot resolves to
it, not because a path is baked into `main.py`.

### 2.2 New module — `game/music_director.py`

One new game-level module at the game root (beside `game/vfx_misc.py`). **Not**
`game/core/`, which may not import pygame
(`tools/tests/test_phase_loop.py:585-591`), and **not** `game/ui/`, whose purity
test bans a *direct* pygame import (`tools/tests/test_shell.py:259-274`).

Two layers, so the tests need no pygame:

- **Pure decision functions** (stdlib + `game.core.phases` only):
  - `resolve_music_key(shell_state, phase, cutscene_active)` → one of
    `"cutscene" | "menu" | "combat_phase" | "building_phase"`, or `None`
    meaning "hold whatever is playing" (PAUSED / GAME_OVER). This is §1.2's
    stack and nothing else.
  - `round_outcome(lives_before, lives_after)` → `"win" | "loss"`.
- **`MusicDirector`** — holds `core_balance`, the SD-2 `music` module
  (injectable for tests), `enabled`, and the last key it resolved (only so the
  cutscene push/pop edges fire once — **not** a clip cache; `music.play` already
  no-ops on a repeat):
  - `tick(shell_state, phase, cutscene_entry)` — `resolve_music_key` → the slot
    dict off `core_balance` → `engine.audio.music.play_slot(slot, loop=True)`,
    or `music.stop()` when the slot resolves to silence, or nothing at all when
    the key is `None` (hold).
  - `enter_cutscene(entry)` → `music.push(clip, loop=False)`;
    `leave_cutscene()` → `music.pop()`.
  - `start_ambient(sfx)` — `core.Sounds.Ambient.default` on the **sfx** bus with
    `loop=True`; idempotent (call once, guard with a flag).
  - `play_game_event(name)` — `core.Sounds.Game.<name>` on the sfx bus, for the
    **six** one-shots: `game_start`, `round_start`, `round_win`, `round_loss`,
    `game_over`, `level_up`.

The override→default fallback is `engine.audio.bank.resolve(default_slot,
override_slot)`: `menu` / `cutscene` / `building_phase` / `combat_phase` are the
**override**, `core.Sounds.Music.default` is the **default**. Do not write that
walk yourself.

Ambient and the six game one-shots go through **SD-4's `gp["sfx"]` dispatcher
object**, not the raw module. **`gp["sfx"]` is built at BOOT and survives
`teardown_gameplay()`** (SD-4, so that menu clicks are audible), so it is
non-`None` for the whole process life, including while the shell is up and
between runs. **Write no `if gp["sfx"] is not None` guard** — the only liveness
question left is the director's own `enabled` flag (§1.4), and a redundant guard
here would imply a `None` window that does not exist and invite someone to
"fix" the wrong thing later. If that object exposes a generic slot play, use it;
only if it does not, call `engine.audio.sfx.play_slot` with a slot you resolved
via `bank.resolve`. Either way: **do not call `sfx.init()`, do not register a
second `gp` audio key, and never prefer the raw module over the dispatcher.**

### 2.3 Host wiring (all in `game/main.py`, one statement per site)

The insertion points are §3.3's anchors. Every one is a single statement inside
an existing branch — the phase-edge idiom
(`if phase == X and gp["prev_phase"] != X:`) at `game/main.py:2200-2250` is the
pattern to copy, not to redesign.

`game/ui/cutscene_player.py` keeps its own companion-audio call (`:68-69`); the
director wraps it by pushing before `start()` and popping after the host's
`release()`, so `cutscene_player.py` changes only in its docstring (`:63-68`),
which currently documents the clobber this phase fixes.

---

## 3. File scope + shared-file contract

### 3.1 New files

| File | Purpose |
|---|---|
| `game/music_director.py` | the module in §2.2 |
| `tools/tests/test_sound_music.py` | the tests in §4 |

### 3.2 Modified files

| File | Change |
|---|---|
| `game/main.py` | the anchors in §3.3 |
| `game/ui/cutscene_player.py` | docstring only (`:63-68`) — the clobber it documents is now fixed by the host's push/pop. No behaviour change. |
| `data/balancing/core.json` | seed `Sounds.Music.default` with the existing WAV (§2.1), through the validating writer |

**Nothing else.** No `engine/**`, no `data/schemas/**`, no `game/core/*.py`, no
`game/ui/shell.py`.

### 3.2b DO NOT TOUCH — `tools/tests/test_audio.py`

`tools/tests/test_audio.py:23-44` asserts `assertIsNone` on `play_music`,
`stop_music` and `set_volume`, plus a mixer-torn-down no-raise case. That is
**correct and intentional**: SD-2's pinned API keeps those three legacy
re-exports returning `None`, and only the NEW calls (`init`, `play_slot`, …)
return `bool`. The briefs agree — there is nothing to harmonize.

**Do not "tidy" those assertions to `assertTrue` / `assertIsNotNone`, and do not
edit that file at all.** It is named in SD-7's exit gate, so an edit made in
passing turns *your* gate red for a change that was never yours. If it fails,
report it; do not adjust it.

### 3.3 `game/main.py` — SHARED with SD-4 and SD-6. Exact anchors.

`game/main.py` is touched by **SD-4** (which owns the audio bootstrap —
`sfx.init(...)` after `pygame.init()` and the `gp["sfx"]` registration), by
**SD-6**, and by this phase. SD-7 **consumes** what SD-4 registers and adds no
bootstrap of its own. Reconcile by these anchors; if a line has moved, match the
quoted text, not the number.

| # | Anchor (verified 2026-08-18) | SD-7's edit | Conflict |
|---|---|---|---|
| A | `:67` `from engine.audio import play_music` | **DELETE** (its sole other use is `:999`) | none — SD-4 adds its own imports below |
| B | `:747` `pygame.init()` | **DO NOT TOUCH** — SD-4's bootstrap anchor | **SD-4 owns it** |
| C | `:998-999` the `if max_frames is None:` boot-track block | **DELETE both lines**; construct `MusicDirector(core_balance, enabled=max_frames is None)` here and start ambient | low |
| D | `:1019-1029` the `gp = {...}` literal | **DO NOT TOUCH** — SD-4 adds `"sfx"`; SD-7 keeps its director in a `main()` local and adds no `gp` key | **SD-4 owns it** |
| E | `:1141` `gp["prev_phase"] = gp["world"].session.state.phase` (in `build_gameplay`) | add the per-run snapshots (`prev_village_level`, `lives_at_wave_start`) right after | low |
| F | `:1154` `shell.enter_gameplay()` (end of `build_gameplay`) | fire `game_start` immediately before it | low |
| G | `:2025` `st = shell.state` (top of the "2. simulate / update" block) | one `director.tick(...)`, after `st` is bound and before the state branch at `:2026` | medium — SD-6's slider work is in the input block above, not here |
| H | `:2223-2226` the `GamePhase.ENEMY` edge (`gp["floaters"].clear_splatters()`) | fire `round_start` + snapshot `base_lives` inside the same `if` | low |
| I | `:2252-2255` the watcher tail (`gp["overlays"].track(...)` → `gp["prev_phase"] = session.state.phase`) | add the ROUND_END edge (win/loss) and the `village_level` delta (level-up) **before** `:2255` reassigns `prev_phase` | low |
| J | `:2259-2262` the game-over mirror (`shell.enter_game_over()`) | fire `game_over` inside that `if` — **and nothing else** (§1.3); no music call, the track is held | low |
| K | `:2026-2031` (intro cutscene) and `:2039-2052` (`gp["cutscene"]`) | `enter_cutscene` / `leave_cutscene` on those existing edges | low |

**Merge note for the orchestrator**: SD-4 owns B + D, SD-7 owns A + C + E–K —
disjoint sets. The nearest approach is A (import block) versus SD-4's own new
imports, and C versus B, ~250 lines apart. SD-6 touches `game/ui/settings.py`,
`game/ui/widgets.py` and `game/ui/shell.py`, none of which SD-7 modifies: the
plan's SD-7 block lists `game/ui/shell.py`, but the menu-music edge is read
host-side off `shell.state` at anchor G, so **SD-7 leaves `shell.py` untouched**
and that overlap disappears.

---

## 4. Exit gate + Quick Test

### Tests — bare minimum, one file

`tools/tests/test_sound_music.py`, fakes only (a fake `music` recording
`play`/`stop`/`push`/`pop`, a fake `sfx` recording `(slot, clip)`), against a
pinned balancing fixture, never live `data/`:

1. `resolve_music_key` returns the right key for: main menu, PAUSED (`None` =
   hold), GAME_OVER (`None` = hold), BUILDING, ENEMY, cutscene-active.
2. A phase transition calls `music.play_slot` with the other track. The
   already-playing no-op is **SD-2's** contract (`music.play` returns True
   without restarting), so assert the director's call — do not test a de-dup the
   director does not own.
3. An empty `combat_phase` override falls back to `Music.default` (through
   `bank.resolve`); an empty `Music.default` too → `music.stop()`, no exception.
4. `enter_cutscene` / `leave_cutscene` call `push` then `pop`, exactly once each,
   including on the skip path.
5. `round_outcome` + the one-shots: a life-losing round that CONTINUES yields
   `round_loss`, a clean round `round_win`, each recorded exactly once; the
   **fatal breach yields `game_over` and NOT `round_loss`** (§1.3 — assert the
   recorded slot list is exactly `["game_over"]` for that frame, so a later
   "improvement" that adds the second sting fails here); `level_up` fires on a
   `village_level` increase and not on a repeat tick.
6. `MusicDirector(enabled=False)` makes every entry point a no-op (headless).

Do not add coverage beyond this list.

### Exit gate

```bash
py tools/smoke.py
py -m pytest tools/tests/test_sound_music.py tools/tests/test_audio.py tools/tests/test_phase_loop.py -q
```

(`test_audio.py` pins the `engine.audio` re-export surface you just stopped
importing; `test_phase_loop.py` carries the `game.core` pygame-purity guard you
must not break.) `GATE PASS` or you are not done.

**You may run nothing else.** Never `py tools/testgate.py check`, never
`--affected`, never a tier sweep (`-m core` / `-m editor` / `-m meta`) — the
`test_guard.py` hook DENIES all four from a subagent. The single full gate is the
main session's step at handoff (root `CLAUDE.md` §"Test Suite Policy").

### Quick Test (in-game; the orchestrator or user runs this, not you)

`py game/main.py` →
1. main menu: **menu music** plays (with only `Music.default` seeded, that is the
   old Bass-and-drum track — proving the hardcoded path is gone and the data
   path replaced it);
2. START NEW GAME: **game-start** sound, then **building-phase** music;
3. End Turn: **round-start** scream as the wave spawns, music switches to
   **combat**; press Esc to pause — the music does **not** change;
4. clear the wave: **round-win**; lose a life and survive: **round-loss**
   (one sting, not two);
5. take the level-up: **level-up** sound;
6. reach a cutscene: its audio plays and the previous track **resumes** after;
7. lose the last life: the **game-over sting** fires ALONE (no round-loss under
   it) and the combat music **keeps playing** through the game-over screen —
   it only changes when you return to the main menu;
8. throughout, the **ambient** loop is audible underneath the music (SFX bus).
