"""game/music_director.py — SD-7: music arbitration + round/game event stings.

One stream, so music is an **arbitration**, not a set of independent players
(`planning/SoundEditorPLAN.md:165`). This module owns that decision and the
six game one-shots; it owns no bootstrap — `engine.audio.sfx.init()` is
SD-4's, and every call here degrades to a silent no-op when the mixer was
never initialised (SD-2's swallow-and-continue contract).

Two layers, so the tests need no pygame and no mixer:

* **pure decision functions** — `resolve_music_key`, `round_outcome`: stdlib
  plus `game.core.phases` only;
* **`MusicDirector`** — the thin stateful shell that turns a key into an
  `engine.audio` call.

It lives at the `game/` root rather than in `game/core/` (which may not import
pygame — `tools/tests/test_phase_loop.py`) or `game/ui/` (whose purity test
bans a direct pygame import — `tools/tests/test_shell.py`), beside
`game/vfx_misc.py`.

Two things this module deliberately does NOT do:

* **no clip-identity cache.** `engine.audio.music.play` already no-ops on the
  file that is already streaming, so ticking every frame cannot restart the
  stream. A second cache here would duplicate SD-2's contract.
* **no `sfx.init`, no volume maths.** `engine.audio.sfx` owns the bus/master
  registry that `music.py` reads.

Import shape: submodules are imported EXPLICITLY (`from engine.audio import
music`) rather than through `engine.audio.<attr>`. SD-2 made the package's
submodule imports lazy (a PEP 562 `__getattr__`) to keep `bank.py` pygame-free,
so the attribute form resolves at *access* time; the explicit form is
unambiguous and is what this package wants.
"""
from engine.audio import bank
from engine.audio import music as _music
from engine.audio import sfx as _sfx
from game.core.phases import GamePhase, GameState

#: §1.2 priority 3 — the shell states that own the menu track. This is NOT
#: `game/ui/shell.py`'s `_MENU_STATES`: that tuple includes `PAUSED`, and
#: pausing must NOT swap the gameplay track for menu music.
MENU_STATES = frozenset({GameState.MAIN_MENU, GameState.SETTINGS,
                         GameState.CREDITS, GameState.ADD_NAME,
                         GameState.HIGHSCORES})

#: §1.2 priority 2 — hold whatever is streaming. The game-over *sting* is an
#: sfx one-shot played OVER the held track, so it does not contradict this.
HOLD_STATES = frozenset({GameState.PAUSED, GameState.GAME_OVER})

#: Keys whose empty slot falls through to something other than
#: `Music.default` FIRST, nearest-first. `boss_phase` empty -> `combat_phase`;
#: that empty too -> `default`; that empty too -> silence.
MUSIC_FALLBACKS = {"boss_phase": ("combat_phase",)}

COMBAT_PHASES = frozenset({GamePhase.ENEMY, GamePhase.ENEMY_INTRO})
BUILDING_PHASES = frozenset({GamePhase.BUILDING, GamePhase.ROUND_END,
                             GamePhase.LEVELUP, GamePhase.INCOME,
                             GamePhase.BOSS_CUTSCENE})

#: the six `core.Sounds.Game.*` one-shots this phase fires.
GAME_EVENTS = ("game_start", "round_start", "round_win", "round_loss",
               "game_over", "level_up")


def resolve_music_key(shell_state, phase, cutscene_active=False,
                      boss_round=False):
    """The §1.2 priority stack, as one pure function.

    Returns ``"cutscene" | "menu" | "boss_phase" | "combat_phase" |
    "building_phase"``, or ``None`` meaning *hold whatever is playing*
    (PAUSED / GAME_OVER, and any state this arbitration has no opinion about).

    ``boss_round`` only ever upgrades the COMBAT key to ``"boss_phase"``: a
    boss round's building/ROUND_END/BOSS_CUTSCENE phases keep the building
    track (``round_num`` is still pre-increment at ROUND_END, so the host's
    boss flag is still True there — this is the reason the upgrade is scoped
    to the combat branch rather than applied at the top of the stack).
    """
    if cutscene_active or shell_state == GameState.CUTSCENE:
        return "cutscene"
    if shell_state in HOLD_STATES:
        return None
    if shell_state in MENU_STATES:
        return "menu"
    if phase in COMBAT_PHASES:
        return "boss_phase" if boss_round else "combat_phase"
    if phase in BUILDING_PHASES:
        return "building_phase"
    return None


def round_outcome(lives_before, lives_after):
    """``"loss"`` when the round cost a life, else ``"win"`` (§1.3).

    The host reads this on the ROUND_END edge from a `base_lives` delta —
    `game/core` is pygame-pure, so the round machine cannot say it itself
    (the `game/ui/hud.py` lives-by-delta precedent).
    """
    return "loss" if lives_after < lives_before else "win"


def _cutscene_companion_clip(entry):
    """The cutscene entry's own companion audio as a clip dict, or None.

    A cutscene's audio file lives in ``data/video/`` beside its video, while
    every clip path is resolved against ``data/audio/``
    (`engine.audio.bank.clip_path`) — hence the relative hop. Both shipped
    registry entries currently carry ``"audio": null``, so this is the
    forward-compatible branch, not the live one.
    """
    name = (entry or {}).get("audio")
    if not name:
        return None
    return {"file": "../video/" + str(name), "volume": 1.0,
            "start": 0.0, "end": 0.0}


class MusicDirector:
    """Turns (shell state, phase, cutscene) into at most one `engine.audio`
    call per frame, and fires the game-event stings.

    ``enabled=False`` makes EVERY entry point a no-op that touches neither
    `pygame.mixer` nor the filesystem — the seam the retired boot-track block
    used (``max_frames is None``), which is why `tools/smoke.py`'s 5-frame
    headless boot stays silent and fast.

    ``music`` / ``sfx`` are injection points for tests. They default to
    ``None`` and are resolved in ``__init__``, never at ``def`` time.
    """

    def __init__(self, core_balance, *, enabled=True, music=None, sfx=None):
        self._sounds = (core_balance or {}).get("Sounds") or {}
        self.enabled = bool(enabled)
        self._music = _music if music is None else music
        self._sfx = _sfx if sfx is None else sfx
        self._in_cutscene = False
        self._ambient_started = False

    # -- slot lookup -----------------------------------------------------
    def _music_slot(self, key):
        """`Music.<key>` as the OVERRIDE over `Music.default` — SD-2's
        `bank.resolve` implements override -> default -> silence; never
        re-spell that walk here.

        ``boss_phase`` is the one key with a THREE-deep chain (boss ->
        combat -> default), expressed as nested `bank.resolve` calls rather
        than an ad-hoc walk, so "an empty slot inherits" keeps meaning exactly
        what `bank.slot_is_empty` says it means.
        """
        group = self._sounds.get("Music") or {}
        base = group.get("default")
        for fallback in MUSIC_FALLBACKS.get(key, ()):
            base = bank.resolve(base, group.get(fallback))
        return bank.resolve(base, group.get(key))

    def _group_slot(self, group, key):
        return (self._sounds.get(group) or {}).get(key)

    # -- music bus -------------------------------------------------------
    def tick(self, shell_state, phase, cutscene_active=False,
             boss_round=False):
        """One frame of arbitration. A repeat of the current track is
        absorbed by `music.play`, so this is safe to call unconditionally."""
        if not self.enabled:
            return
        key = resolve_music_key(shell_state, phase, cutscene_active,
                                boss_round)
        if key is None or key == "cutscene":
            # None -> hold; "cutscene" -> the push/pop pair owns the bus.
            return
        slot = self._music_slot(key)
        if slot is None:
            self._music.stop()
            return
        self._music.play_slot(slot, loop=True)

    def enter_cutscene(self, entry=None):
        """Stack the phase track under the cutscene's. Idempotent: the host
        calls this on a per-frame branch, and an unmatched second push would
        strand the stack."""
        if not self.enabled or self._in_cutscene:
            return
        self._in_cutscene = True
        clip = _cutscene_companion_clip(entry)
        if clip is None:
            clip = bank.pick_clip(self._music_slot("cutscene"))
        # push() saves the current track even when `clip` is None (silence),
        # so pop() restores symmetrically in every case.
        self._music.push(clip, loop=False)

    def leave_cutscene(self):
        """Resume the stacked track. Sits on the SAME host edge as the
        player's `release()` — including the skip path, which goes through
        that same branch."""
        if not self.enabled or not self._in_cutscene:
            return
        self._in_cutscene = False
        self._music.pop()

    # -- sfx bus ---------------------------------------------------------
    def start_ambient(self, sfx=None):
        """`core.Sounds.Ambient.default` as a looping SFX (decision D6 —
        ambient rides the sfx bus so it coexists with the one music stream).
        Call-once; guarded."""
        if not self.enabled or self._ambient_started:
            return
        self._ambient_started = True
        slot = self._group_slot("Ambient", "default")
        if slot is None:
            return
        (self._sfx if sfx is None else sfx).play_slot(slot, loop=True)

    def play_game_event(self, name, sfx=None):
        """One of `GAME_EVENTS` on the sfx bus. `core.Sounds.Game.*` has no
        override layer — an empty slot is simply silence."""
        if not self.enabled:
            return
        slot = self._group_slot("Game", name)
        if slot is None:
            return
        (self._sfx if sfx is None else sfx).play_slot(slot, loop=False)
