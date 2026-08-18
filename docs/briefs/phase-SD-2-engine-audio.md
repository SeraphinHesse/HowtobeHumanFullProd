# Phase SD-2 — `engine/audio/` package (engine)

Plan: `planning/SoundEditorPLAN.md` §"Phase SD-2" (lines 246-284), §2.1 slot
shape (135-156), §2.2 buses (158-168), §5 risks (483-500).
Package doc to read first: `engine/CLAUDE.md` (hard rules at `:349-360`).

**Goal**: sound can be played by code — headless-safe, with NO game vocabulary
in `engine/` — and the public surface four later phases (SD-4/5/6/7) call is
frozen here.

**This phase does not touch `game/` or `editor/` at all.** `engine/CLAUDE.md:19-22`
forbids it, and the wiring SD-4 will do is only *described* in §3 below.

---

## 1. Behavioral spec

### 1.1 What exists today (all citations verified in this worktree, 2026-08-18)

- `engine/audio.py` is 41 lines, three functions and one import:
  `play_music(path, loop=True, volume=None)` at `engine/audio.py:15`,
  `stop_music()` at `:27`, `set_volume(v)` at `:35`. Each body is a
  `try: … except Exception: pass` — the swallow-and-continue contract stated in
  its module docstring (`engine/audio.py:1-11`).
- `pygame.mixer.Sound` appears nowhere in the repo (*verified*: repo-wide grep).
  There is no bus, no channel pool, no volume registry, no clip cache.
- Three importers pin the re-export surface and must keep working **byte-for-byte
  unchanged**:
  - `game/main.py:67` — `from engine.audio import play_music`
  - `game/ui/cutscene_player.py:16` — `from engine.audio import play_music, stop_music`
  - `tools/tests/test_audio.py:13` — `from engine import audio`, then
    `audio.play_music` / `audio.stop_music` / `audio.set_volume`
    (`tools/tests/test_audio.py:25,29,30,33,34,42-44`).
- `tools/tests/test_audio.py:36-44` is the graceful-degradation pin: it calls
  `pygame.mixer.quit()` and then requires all three calls to no-op. It also runs
  under `SDL_AUDIODRIVER=dummy` (`tools/tests/test_audio.py:8-9`).
- The cutscene clobber this phase gives SD-7 the tool to fix:
  `game/ui/cutscene_player.py:60-68` — `start()` calls
  `play_music(self._audio_path, loop=False)` and the docstring at `:63-66` says
  outright "this replaces whatever background music was already playing;
  nothing restores it afterward."
- The hardcoded boot track (SD-7 deletes it, **not this phase**):
  `game/main.py:998-999` — `play_music(data_dir / "audio" /
  "Bass_and_drum_Duo.wav", loop=True)`, guarded by `if max_frames is None`
  (headless runs never start music).
- `pygame.init()` is at `game/main.py:747`; the `gp` registry dict is built at
  `game/main.py:1019`. **NOTE: the plan doc cites `:588`, `:785` and `:825` for
  these three — those line numbers have drifted; the numbers above are the live
  ones (*verified* by reading the file).**
- `editor/panels/viewport.py` sets `SDL_AUDIODRIVER=dummy` at module level for
  the whole editor process (`planning/SoundEditorPLAN.md:120-124`), so nothing
  this phase writes may assume a real device even inside the editor.
- numpy is present (2.4.6) but only transitively via the OPTIONAL
  `opencv-python` (`planning/SoundEditorPLAN.md:132-133`, `:485-489`). It is a
  feature-detect, never an import at module top level that can fail the package.
- Tier/domain registries a new test module must join or the suite fails:
  `conftest.py:36` (`TIERS`; `"test_audio": "core"` at `conftest.py:85`) and
  `tools/test_domains.py`'s `"engine"` tuple (`tools/test_domains.py:155-183`;
  `"test_audio.py"` at `:161`). `tools/test_domains.py:16-22` states both rules:
  exactly one domain per module, no catch-all.

### 1.2 What must be true when this phase is done

1. `engine/audio.py` is **deleted**; `engine/audio/` is a package and
   `from engine.audio import play_music, stop_music` still resolves, with the
   same signatures and the same never-raise behaviour.
2. `tools/tests/test_audio.py` passes **verbatim** — do not edit that file.
3. Resolution `element override → global default → silence` is implemented as a
   pure function over the §2.1 slot dicts, with no pygame and no globals.
4. Effective volume is exactly `master × bus × clip.volume`, clamped to
   `[0.0, 1.0]` (`planning/SoundEditorPLAN.md:168`).
5. Two buses only (`planning/SoundEditorPLAN.md:163-166`): `"music"` →
   `pygame.mixer.music` (streaming, one track at a time); `"sfx"` →
   `pygame.mixer.Sound` on a pooled channel. The bus is a **parameter**, never
   inferred from a data field.
6. Every mixer-touching entry point degrades to a no-op and returns a falsy
   result rather than raising — no device, mixer quit, missing file,
   unsupported codec, `SDL_AUDIODRIVER=dummy`, `data/audio/imported/` absent.
7. Per-slot cooldown and a max-concurrent cap exist and are load-bearing for
   SD-5's 40-enemy wipe (`planning/SoundEditorPLAN.md:384-385`, `:498-499`).
8. Start-trim feature-detects numpy and falls back to `end`-only trim via
   `Sound.play(maxtime=…)` when it is absent
   (`planning/SoundEditorPLAN.md:269-272`).
9. **No game vocabulary anywhere in the new package** — no "building", "enemy",
   "boss", "wave", "love", no `data/balancing/*.json` key names, no slot
   *paths*. The package takes bus names (opaque strings), slot dicts and clip
   dicts. (`engine/CLAUDE.md:358-360`; the same rule `engine/vfx/variants.py`
   keeps — `engine/CLAUDE.md:314-330`.)

---

## 2. Architecture plan

Four modules, mirroring `engine/vfx/`'s shape (pure params/logic split from the
stateful system; see `engine/vfx/__init__.py:1-24`).

```
engine/audio/__init__.py   facade + legacy re-exports; the ONLY module
                           SD-4..SD-7 need to import
engine/audio/bank.py       PURE. no pygame, no module globals, rng injected.
                           resolve / pick / volume math / path + trim helpers
engine/audio/sfx.py        pygame.mixer.Sound: clip cache, channel pool,
                           cooldown, concurrency cap, bus+master volume registry
engine/audio/music.py      pygame.mixer.music: one streaming track,
                           push/pop stack, "already playing = no-op"
```

Dependency direction is strictly `__init__ → {music, sfx} → bank`. `sfx.py`
never imports `music.py`; `music.py` imports `sfx` only to *read* gains. Nothing
in the package imports `game/`, `editor/`, or a balancing loader.

**Where the volume state lives.** `sfx.py` owns the single registry
(`_MASTER: float`, `_BUS: dict[str, float]`) because it is the module `init()`
and the channel pool live in. `music.py` reads it through
`sfx.master_volume()` / `sfx.bus_volume("music")` when it starts a track and
when `music.refresh_volume()` is called. The **fan-out** — poking a live music
track after a slider move — lives in `__init__.py`'s `set_bus_volume` /
`set_master_volume` wrappers, so SD-6 makes exactly one call per slider. Do not
add a listener/callback registry; the two-line wrapper is the whole mechanism.

**Legacy vs. new volume API — keep them separate.** `set_volume(v)` stays the
raw `pygame.mixer.music.set_volume` passthrough that `tools/tests/test_audio.py:33,43`
pins. The new bus/master registry is `set_bus_volume` / `set_master_volume`.
Do not redefine `set_volume` in terms of the registry.

**Trim.** `clip["start"]`/`clip["end"]` are seconds; `end == 0.0` is the
"play to the end" sentinel (`planning/SoundEditorPLAN.md:148-150`) — never
`None`, never a `oneOf`. On the `sfx` bus:
- `end > 0` alone → `Sound.play(..., maxtime=int((end - start) * 1000))`.
- `start > 0` → needs a sliced `pygame.sndarray` buffer, which needs numpy.
  Feature-detect once (`_numpy()` doing a lazy `import numpy` inside a `try`,
  cached in a module global; the `engine/video.py` lazy-cv2 precedent,
  `engine/CLAUDE.md:157-162`). If numpy is missing, **ignore `start`** and apply
  `end`-only trim; expose the fact through `sfx.start_trim_available() -> bool`
  so SD-3 can grey the field out. numpy must never be promoted to a hard
  dependency in `requirements.txt` by this phase.
- On the `music` bus, `start` maps to `pygame.mixer.music.play(loops, start)`
  where supported and is swallowed if not; `end` is ignored (streaming).

**Cache.** `sfx` keys its `Sound` cache by `(str(path), round(start, 3),
round(end, 3))` per the plan (`planning/SoundEditorPLAN.md:259-260`) — trimmed
variants are distinct objects. A load failure caches a `None` sentinel so a
missing file is not re-opened every frame.

**Channel pool.** `pygame.mixer.set_num_channels(n)` at `init`, then
`pygame.mixer.find_channel()` per play. `find_channel()` returning `None` (all
busy) is a normal miss → return `False`, never force-steal a channel.

**Cooldown / cap.** Both are keyed by the caller's opaque `key` string (SD-4+
pass the slot path, e.g. `"buildings.death"` — the engine never parses it, never
branches on it). A `play` whose `key` fired less than `cooldown` seconds ago is
dropped; a `key` already holding `max_concurrent` live channels is dropped. Time
comes from an injectable `now` parameter defaulting to `time.monotonic()` so
tests are deterministic without sleeping.

**Testability seam (contract, not an option).** Both `sfx.py` and `music.py`
must call pygame through the **module attribute** (`pygame.mixer.Sound(...)`,
never `from pygame.mixer import Sound`), so a test can
`unittest.mock.patch.object(sfx, "pygame", FakeMixer())`. This is what makes the
cache / cooldown / cap tests possible with no audio device.

**Doc update (in scope, required).** `engine/CLAUDE.md` — the `audio.py` bullet
at `:153-156` becomes an `engine/audio/` package entry (it is a subsystem now;
either give it a row in the subsystem table at `:24-31` with an
`engine/audio/CLAUDE.md`, or keep it as a top-level bullet — the executing agent
picks one and is consistent), and the pygame-allowlist at `:349-356` must name
`engine/audio/sfx.py` + `engine/audio/music.py` and state that
`engine/audio/bank.py` is PURE.

---

## 3. File scope + shared-file contract

### 3.1 Files

**New**
- `engine/audio/__init__.py`
- `engine/audio/bank.py`
- `engine/audio/sfx.py`
- `engine/audio/music.py`
- `tools/tests/test_audio_bank.py`
- `tools/tests/test_audio_sfx.py`

**Deleted**
- `engine/audio.py` (becomes the package — delete the file, do not leave a stub
  beside the package directory)

**Modified**
- `conftest.py` — add `"test_audio_bank": "core"` and `"test_audio_sfx": "core"`
  to `TIERS` (`conftest.py:36`), alphabetically beside `"test_audio": "core"`
  at `conftest.py:85`. Omitting this is a hard error (`conftest.py:19`).
- `tools/test_domains.py` — add `"test_audio_bank.py"` and `"test_audio_sfx.py"`
  to the `"engine"` tuple, beside `"test_audio.py"` at `tools/test_domains.py:161`.
  Rule 3 at `tools/test_domains.py:33-35` puts them there (engine-only subject).
- `engine/CLAUDE.md` — see the doc-update note in §2.

**Do NOT touch**: `tools/tests/test_audio.py` (it is the compat pin), any file
under `game/**` or `editor/**`, `requirements.txt`, `data/**`, and
`tools/tests/test_fixture_guard.py` (the new tests read no live `data/`, so they
need no allowlist entry — keep it that way).

**DO NOT CHANGE — the legacy return types stay `None`.** `play_music`,
`stop_music` and `set_volume` return **`None`**, and must keep returning `None`
after the package conversion. Do **not** "harmonize" them to the `bool` the new
calls return: `tools/tests/test_audio.py:23-44` asserts `assertIsNone` on all
three (`:25`, `:29-30`, `:33-34`) and re-calls all three with the mixer torn
down (`:36-44`). That file is edited by nobody and runs in **SD-7's gate as well
as this one**, so a tidy-up here fails SD-7 through no fault of SD-7's. Only the
NEW surface (`init`, `play_slot`, `sfx.*`, `music.*`) is `bool`-returning; the
three legacy names are a frozen boundary, not a style inconsistency.

### 3.2 THE PUBLISHED API — frozen here, coded against sight-unseen by SD-4/5/6/7

Downstream phases import **only** `engine.audio`. Treat every signature below as
a contract: parameter names are keyword-callable exactly as written, and every
**new** mixer-touching function returns a `bool` (`True` = a sound actually
started) and **never raises**. The three **legacy** functions are the exception
and are frozen at `-> None` — see the DO NOT CHANGE note in §3.1.

```python
# ── engine/audio/__init__.py ────────────────────────────────────────────────
# Legacy surface — UNCHANGED, still exactly these three names (game/main.py:67,
# game/ui/cutscene_player.py:16, tools/tests/test_audio.py:13).
# RETURN TYPE FROZEN AT None — never bool. See §3.1 "DO NOT CHANGE".
def play_music(path, loop=True, volume=None) -> None
def stop_music() -> None
def set_volume(v) -> None            # raw pygame.mixer.music.set_volume passthrough

# Submodules re-exported as names: engine.audio.bank / .sfx / .music

def init(data_dir, *, channels: int = 24) -> bool
    """Idempotent. Call once after pygame.init(). Wires the clip root to
    `Path(data_dir) / "audio"` for BOTH buses and sizes the channel pool.
    Returns False (never raises) when the mixer is unavailable; every later
    call then no-ops."""

def play_slot(default_slot, override_slot=None, *, bus: str = "sfx",
              key: str | None = None, rng=None, loop: bool | None = None) -> bool
    """THE call SD-4..SD-7 make. Resolves override→default→silence via
    bank.resolve, picks a clip via bank.pick_clip, routes to the named bus.
    `key` is an opaque cooldown/concurrency bucket (pass the slot path).
    `loop=None` means "use the slot's own `loop` field"."""

def set_master_volume(v: float) -> None   # applies live to a playing music track
def set_bus_volume(bus: str, v: float) -> None  # bus in {"music", "sfx"}
def master_volume() -> float
def bus_volume(bus: str) -> float
def stop_all() -> None                    # stops sfx channels AND music

# ── engine/audio/bank.py  (PURE: no pygame, no module globals) ──────────────
EMPTY_CLIP: dict   # {"file": "", "volume": 1.0, "start": 0.0, "end": 0.0}
EMPTY_SLOT: dict   # {"clips": [], "loop": False, "pick": "random"}
BUSES: tuple       # ("music", "sfx")

def slot_is_empty(slot) -> bool
    """True for None, {}, or a slot whose `clips` list is empty or holds only
    entries with a falsy `file`."""

def resolve(default_slot, override_slot=None) -> dict | None
    """Non-empty override wins; else non-empty default; else None (= silence).
    Never mutates either argument, never merges them field-by-field — a slot is
    an all-or-nothing unit."""

def pick_clip(slot, rng=None, *, counter: int = 0) -> dict | None
    """None for an empty slot. Single clip -> that clip. Otherwise
    slot["pick"] == "sequential" -> clips[counter % len(clips)];
    "random" (or anything else) -> rng.choice(clips) with an INJECTED
    random.Random-compatible rng (module-level `random` is never used here —
    the engine/vfx/emitters.py rule, engine/CLAUDE.md:219-234). rng=None with
    >1 clip returns clips[0]."""

def effective_volume(clip, bus_volume: float = 1.0, master: float = 1.0) -> float
    """master * bus_volume * clip["volume"], clamped to [0.0, 1.0]; a missing
    or non-numeric clip volume reads as 1.0."""

def clip_path(audio_root, clip) -> "pathlib.Path | None"
    """Path(audio_root) / clip["file"]; None for an empty/absent file. Does not
    touch the filesystem."""

def trim_bounds(clip) -> tuple[float, float | None]
    """(start_seconds, end_seconds_or_None) — the `end == 0.0` sentinel maps to
    None ("play to the end"); negative/inverted values normalise to (0.0, None)."""

# ── engine/audio/sfx.py  (pygame.mixer.Sound) ───────────────────────────────
DEFAULT_CHANNELS: int = 24
DEFAULT_COOLDOWN_S: float = 0.05
DEFAULT_MAX_CONCURRENT: int = 4

def init(audio_root, *, channels: int = DEFAULT_CHANNELS) -> bool
def is_ready() -> bool
def start_trim_available() -> bool          # numpy feature-detect result

def play(clip, *, key: str | None = None, loop: bool = False,
         cooldown: float = DEFAULT_COOLDOWN_S,
         max_concurrent: int = DEFAULT_MAX_CONCURRENT,
         now: float | None = None) -> bool

def play_slot(slot, *, key: str | None = None, rng=None,
              loop: bool | None = None, now: float | None = None) -> bool

def set_bus_volume(bus: str, v: float) -> None
def bus_volume(bus: str) -> float
def set_master_volume(v: float) -> None
def master_volume() -> float
def active_count(key: str | None = None) -> int   # live channels, all or per key
def stop_all() -> None
def clear_cache() -> None                          # test/teardown hook

# ── engine/audio/music.py  (pygame.mixer.music — one track at a time) ───────
def init(audio_root) -> bool
def play(clip, *, loop: bool = True, force: bool = False) -> bool
    """No-op returning True when `clip`'s file is already the current track and
    `force` is False (SD-7 requires this: never restart on a phase tick —
    planning/SoundEditorPLAN.md:452-454)."""
def play_slot(slot, *, rng=None, loop: bool | None = None) -> bool
def stop() -> None
def current() -> dict | None                # the playing clip dict, or None
def push(clip, *, loop: bool = False) -> bool
    """Save the current clip on a stack and play `clip` instead (the cutscene
    case, game/ui/cutscene_player.py:60-68)."""
def pop() -> bool
    """Resume the top saved clip; stop() when the stack is empty. Never raises
    on an unbalanced pop."""
def refresh_volume() -> None                # re-apply master*bus to the live track
```

### 3.3 The wiring shape SD-4 will use (described here, NOT written here)

SD-2 writes none of this. It is pinned so SD-4 codes against the same shape:

```python
# game/main.py — import beside the existing `from engine.audio import play_music`
# (game/main.py:67)
import engine.audio as audio

# ... after pygame.init() (game/main.py:747):
audio.init(data_dir)          # returns False on a device-less host; harmless

sounds = GameSounds(...)      # SD-4's dispatcher, built at BOOT, right here

# ... in the gp registry dict (game/main.py:1019):
gp["sfx"] = sounds            # the object that knows slot PATHS
```

**Settled by the coordinator**: `gp["sfx"]` is a `game.sounds.GameSounds`
dispatcher (SD-4's object), **not** the raw `engine.audio` module. It is built
at BOOT, immediately after `engine.audio.init(data_dir)`, and **survives
`teardown_gameplay()`** so main-menu clicks stay audible. It owns the balancing
lookup and the slot-path vocabulary and calls `engine.audio.play_slot(...)`
underneath.

Nothing in that changes SD-2's surface — but it is why `engine.audio`'s state is
module-level and its `init()` is idempotent: a dispatcher that outlives the
gameplay bundle must never be able to leave the engine half half-initialised.
`engine/audio/**` must never learn any slot path, and must never carry a slot
inventory of its own — slot names (including ones added after this brief) live
in `data/` and in SD-4's dispatcher only.

Because `audio.init()` is idempotent and returns `False` rather than raising,
SD-4 needs no guard around it, and headless runs (`max_frames is not None`,
`game/main.py:998`) simply never call `play_slot`.

---

## 4. Exit gate + Quick Test

### Tests to write (BARE MINIMUM — cover the contract, not coverage)

`tools/tests/test_audio_bank.py` (pure, headless, no pygame):
1. `resolve`: non-empty override wins; empty override falls through to the
   default; both empty → `None`.
2. `pick_clip`: a seeded `random.Random` picks deterministically from a 2-clip
   slot; `"sequential"` with `counter` 0/1/2 cycles.
3. `effective_volume`: `0.5 * 0.5 * 0.8` and one clamp case.
4. Purity: a subprocess that imports `engine.audio.bank` and asserts
   `"pygame" not in sys.modules` — copy the shape of
   `tools/tests/test_core.py:278-291`.

`tools/tests/test_audio_sfx.py`:
5. Degradation: after `pygame.mixer.quit()`, `sfx.init(...)`, `sfx.play(clip)`,
   `sfx.play_slot(slot)`, `music.play(clip)`, `music.push`/`pop`, and
   `sfx.stop_all()` all return falsy and never raise; a missing file likewise.
6. Against a patched fake `pygame` (`patch.object(sfx, "pygame", Fake())`):
   the cache loads a given `(file, start, end)` once across two plays; a second
   `play` with the same `key` inside `cooldown` (driving `now=`) is dropped;
   `max_concurrent` caps a burst of 10 plays at 4.
7. Volume: `set_master_volume(0.5)` + `set_bus_volume("sfx", 0.5)` reaches the
   fake channel/Sound as `0.25 × clip volume`.
8. `music.play` of the already-current file is a no-op that does not reload;
   `push` then `pop` restores the previous clip.

Register both modules in `conftest.py` `TIERS` and `tools/test_domains.py`
before running anything (§3.1) — otherwise the suite errors on collection.

### Exit gate (run exactly these — nothing wider)

```
py tools/smoke.py
py -m pytest tools/tests/test_audio.py tools/tests/test_audio_bank.py tools/tests/test_audio_sfx.py -q
py -m pytest tools/tests/test_cutscene_player.py tools/tests/test_tiers.py tools/tests/test_test_domains.py -q
```

The second line's `test_audio.py` is the backwards-compat pin (it must pass
unedited); the third covers the importer and the two registries this phase
perturbs. Zero failures, per `engine/CLAUDE.md:383-385`.

**Do not run** `py tools/testgate.py check`, `--affected`, or a tier sweep
(`-m core` / `-m editor` / `-m meta`) — §"Test Suite Policy" in the root
`CLAUDE.md` scopes those to the main session and a `PreToolUse` hook denies them
from a subagent. The single full gate is the orchestrator's step at handoff.

### Quick Test (in-game — run by the orchestrator or the user, not the coder)

`py game/main.py` → the game boots to the main menu and the existing
`Bass_and_drum_Duo.wav` background track still plays and still loops
(`game/main.py:998-999` is untouched by this phase, so the only way it can
break is the package conversion). If a cutscene is reachable, its companion
audio still plays (still clobbering the music — SD-7 fixes that with
`push`/`pop`; nothing regresses here).

Second check, no audio device required: `py editor/main.py` opens without an
audio exception (the editor runs with `SDL_AUDIODRIVER=dummy` process-wide).
