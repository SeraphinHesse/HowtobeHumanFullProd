"""engine.audio — headless-safe sound layer (SD-2).

Four modules, mirroring `engine/vfx/`'s shape (pure params/logic split from
the stateful system):

- `bank.py`   PURE. no pygame, no module globals, rng injected. resolve /
              pick / volume math / path + trim helpers.
- `sfx.py`    pygame.mixer.Sound: clip cache, channel pool, cooldown,
              concurrency cap, bus+master volume registry.
- `music.py`  pygame.mixer.music: one streaming track, push/pop stack,
              "already playing = no-op".

Dependency direction is strictly `__init__ -> {music, sfx} -> bank`. `sfx.py`
never imports `music.py`; `music.py` imports `sfx` only to *read* gains.
Nothing in this package imports `game/`, `editor/`, or a balancing loader —
no game vocabulary anywhere here: this module takes bus names (opaque
strings), slot dicts and clip dicts, never a slot *path* or a data/
balancing key name.

**Where the volume state lives.** `sfx.py` owns the single registry
(`_master`, `_bus`) because it is where `init()` and the channel pool live.
`music.py` reads it through `sfx.master_volume()` / `sfx.bus_volume("music")`
when it starts a track and when `music.refresh_volume()` is called. The
fan-out — poking a live music track after a slider move — lives in this
module's `set_bus_volume` / `set_master_volume` wrappers, so a caller makes
exactly one call per slider.

**Legacy vs. new volume API — kept separate.** `set_volume(v)` below is the
raw `pygame.mixer.music.set_volume` passthrough frozen for
`game/main.py`/`game/ui/cutscene_player.py`/`tools/tests/test_audio.py`. The
new bus/master registry is `set_bus_volume`/`set_master_volume`. The two are
never defined in terms of each other.

pygame is allowed here (like the render backend / asset store) — this
package's `sfx.py`/`music.py` are two of the engine's pygame-touching
modules; `bank.py` stays pure so game logic can stay headless via it.

**Why every pygame touch below is a LAZY import.** `sfx.py`/`music.py` each
import pygame at their own module top (the `patch.object(sfx, "pygame", …)`
seam requires it). If THIS file imported them eagerly too, `import
engine.audio.bank` alone would drag pygame in via `engine/audio/__init__.py`
running first — Python always executes a package's `__init__.py` before any
of its submodules, no matter which one you ask for. Deferring both the
`pygame` import (legacy functions) and the `sfx`/`music` imports (new
surface) to each function body keeps `import engine.audio.bank` (and the
`tools/tests/test_audio_bank.py` purity test) pygame-free, while `from
engine.audio import sfx` / `music` — what every caller actually uses —
works exactly as before.
"""
from pathlib import Path

from . import bank

__all__ = [
    "bank",
    "sfx",
    "music",
    "play_music",
    "stop_music",
    "set_volume",
    "init",
    "play_slot",
    "set_master_volume",
    "set_bus_volume",
    "master_volume",
    "bus_volume",
    "stop_all",
]


def __getattr__(name):
    """PEP 562: resolves `engine.audio.sfx` / `engine.audio.music` as
    attributes even when nothing has triggered their lazy import yet (e.g.
    a caller's own `def __init__(self, music=audio.music, ...)` default
    argument, evaluated at ITS module's import time). `import
    engine.audio.bank` alone never triggers this — it imports `bank`
    directly, never looks up `.sfx`/`.music` as attributes of this package
    — so the purity guarantee (`tools/tests/test_audio_bank.py`) is
    unaffected."""
    if name in ("sfx", "music"):
        import importlib

        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(name)


# ── Legacy surface — UNCHANGED. Return type FROZEN at None — never bool. ───
# game/main.py:67, game/ui/cutscene_player.py:16, tools/tests/test_audio.py:13
def play_music(path, loop=True, volume=None):
    """Load and start looping (or one-shot) background music. No-op on any
    error. `volume` in [0.0, 1.0] applied before play when given."""
    try:
        import pygame

        pygame.mixer.music.load(str(path))
        if volume is not None:
            pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play(-1 if loop else 0)
    except Exception:
        pass


def stop_music():
    """Stop playback. No-op if the mixer is unavailable."""
    try:
        import pygame

        pygame.mixer.music.stop()
    except Exception:
        pass


def set_volume(v):
    """Set music volume in [0.0, 1.0]. No-op if the mixer is unavailable."""
    try:
        import pygame

        pygame.mixer.music.set_volume(v)
    except Exception:
        pass


# ── New surface — every mixer-touching call returns bool, never raises. ────
def init(data_dir, *, channels=24):
    """Idempotent. Call once after pygame.init(). Wires the clip root to
    `Path(data_dir) / "audio"` for BOTH buses and sizes the channel pool.
    Returns False (never raises) when the mixer is unavailable; every later
    call then no-ops."""
    from . import music, sfx

    audio_root = Path(data_dir) / "audio"
    ok = sfx.init(audio_root, channels=channels)
    music.init(audio_root)
    return ok


def play_slot(default_slot, override_slot=None, *, bus="sfx", key=None, rng=None, loop=None):
    """THE call downstream phases make. Resolves override->default->silence
    via bank.resolve, picks a clip via bank.pick_clip, routes to the named
    bus. `key` is an opaque cooldown/concurrency bucket (pass the slot
    path). `loop=None` means "use the slot's own `loop` field"."""
    from . import music, sfx

    resolved = bank.resolve(default_slot, override_slot)
    if resolved is None:
        return False
    if bus == "music":
        return music.play_slot(resolved, rng=rng, loop=loop)
    return sfx.play_slot(resolved, key=key, rng=rng, loop=loop)


def set_master_volume(v):
    """Applies live to a playing music track."""
    from . import music, sfx

    sfx.set_master_volume(v)
    music.refresh_volume()


def set_bus_volume(bus, v):
    """`bus` in {"music", "sfx"}."""
    from . import music, sfx

    sfx.set_bus_volume(bus, v)
    if bus == "music":
        music.refresh_volume()


def master_volume():
    from . import sfx

    return sfx.master_volume()


def bus_volume(bus):
    from . import sfx

    return sfx.bus_volume(bus)


def stop_all():
    """Stops sfx channels AND music."""
    from . import music, sfx

    sfx.stop_all()
    music.stop()
