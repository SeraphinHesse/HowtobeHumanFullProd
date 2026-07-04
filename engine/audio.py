"""pygame.mixer music wrapper (prototype src/core/game.py:49-55).

A thin, best-effort music layer: every call is wrapped so ANY failure — no
audio device, mixer not initialised, missing/unsupported file, SDL dummy
audio driver — is swallowed and the call becomes a silent no-op. That keeps
headless/CI runs (SDL_AUDIODRIVER=dummy) and machines without sound from ever
crashing on music. No game vocabulary lives here; the caller passes the path.

pygame is allowed here (like the render backend / asset store) — this is one
of the engine's pygame-touching modules; game logic stays headless via it.
"""
import pygame


def play_music(path, loop=True, volume=None):
    """Load and start looping (or one-shot) background music. No-op on any
    error. `volume` in [0.0, 1.0] applied before play when given."""
    try:
        pygame.mixer.music.load(str(path))
        if volume is not None:
            pygame.mixer.music.set_volume(volume)
        pygame.mixer.music.play(-1 if loop else 0)
    except Exception:
        pass


def stop_music():
    """Stop playback. No-op if the mixer is unavailable."""
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass


def set_volume(v):
    """Set music volume in [0.0, 1.0]. No-op if the mixer is unavailable."""
    try:
        pygame.mixer.music.set_volume(v)
    except Exception:
        pass
