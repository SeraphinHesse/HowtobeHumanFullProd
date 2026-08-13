"""Live input probe for the render-backend presenter seam (`game/main.py`).

WHY THIS EXISTS. The G4 GPU path shipped with a bug no headless test could
see: every main-menu button was dead on `--backend=gpu` while its hover
animation still worked. Hover and clicking read the mouse from two DIFFERENT
sources — `pygame.mouse.get_pos()` (window pixels) and `event.pos` (already
renderer-logical) — and only one of them needs remapping. Anything that
touches `_GpuPresenter.map_event`, `mouse_pos`, `logical_size` or the display
mode should be re-run through this before it is called done.

WHAT IT DOES. Boots the REAL game with a real window, skips the intro
cutscene, then synthesises OS-level mouse clicks (win32 `SendInput` via
ctypes) at chosen LOGICAL coordinates, and logs each click all the way down
the input path:

    clicker: click logical (320, 163) screen (960, 489) mouse_pos -> (320, 163)
    map_event MouseButtonDown raw (320, 163) -> (320, 163) button 1
    Shell.handle_click (320, 163) state GameState.MAIN_MENU -> intent new_game

`raw -> mapped` differing from `mouse_pos` for the same physical point is the
signature of the double-mapping bug. `intent None` on a click aimed at a
button means the click did not land where the player aimed.

USAGE (needs a real display; win32 only — it drives the OS cursor):

    py tools/probe_gpu_input.py                 # --backend=gpu, default (fullscreen) display mode
    py tools/probe_gpu_input.py surface         # the control run: same clicks, Surface path

It clicks the centre of the first main-menu button, then two rows below it.

KNOWN LIMIT: the `surface` control run is only trustworthy with the display
mode set to WINDOWED. A `pygame.SCALED` fullscreen window reports a size and
position this probe cannot reliably turn back into screen pixels on a
multi-monitor / DPI-scaled desktop, and the synthesised clicks then land off
the window (the log shows `mouse_pos -> (0, 0)`). The GPU path — a standalone
SDL window, which is what this probe exists for — is exact in both modes.

NOT a test — it is not collected by pytest, takes over the screen and the
cursor for ~15 seconds, and asserts nothing. Read the log.
"""
import ctypes
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BACKEND = sys.argv[1] if len(sys.argv) > 1 else "gpu"

import pygame                                                    # noqa: E402
import game.main as gm                                           # noqa: E402
from game.ui import cutscene_player as cp_mod                    # noqa: E402
from game.ui import shell as shell_mod                           # noqa: E402

# The logical points to click: the centre of the START NEW GAME button and the
# two rows under it (main-menu buttons are 26px tall, 30px apart).
CLICK_POINTS = ((320, 163), (320, 193), (320, 223))

_MOUSE_LEFT_DOWN = 0x0002
_MOUSE_LEFT_UP = 0x0004
user32 = ctypes.windll.user32

_presenter = [None]
_shell = [None]


def log(*a):
    print("PROBE", *a, flush=True)


# -- skip the intro cutscene so the probe lands on the main menu -------------
cp_mod.CutscenePlayer.enabled = property(lambda self: False)


# -- instrument the three points on the input path --------------------------
_orig_map = gm._GpuPresenter.map_event


def _map_event(self, event):
    out = _orig_map(self, event)
    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        log("map_event", pygame.event.event_name(event.type),
            "raw", getattr(event, "pos", None),
            "->", getattr(out, "pos", None),
            "button", getattr(out, "button", None))
    return out


gm._GpuPresenter.map_event = _map_event

_orig_click = shell_mod.Shell.handle_click


def _handle_click(self, mx, my):
    intent = _orig_click(self, mx, my)
    log("Shell.handle_click", (mx, my), "state", self.state,
        "-> intent", intent)
    return intent


shell_mod.Shell.handle_click = _handle_click

_orig_shell_init = shell_mod.Shell.__init__


def _shell_init(self, *a, **k):
    _orig_shell_init(self, *a, **k)
    _shell[0] = self


shell_mod.Shell.__init__ = _shell_init


def _clicker():
    time.sleep(5.0)
    presenter = _presenter[0]
    win = getattr(presenter, "_window", None)
    if not hasattr(win, "position"):          # Surface path: the control run
        from pygame._sdl2 import video as sdl2
        win = sdl2.Window.from_display_module()
    px, py = win.position
    sx, sy = win.size
    log("window pos", (px, py), "size", (sx, sy),
        "shell.state", _shell[0].state if _shell[0] else None)
    for lx, ly in CLICK_POINTS:
        wx = px + int(lx * sx / 640)
        wy = py + int(ly * sy / 360)
        user32.SetCursorPos(wx, wy)
        time.sleep(1.0)
        pos = presenter.mouse_pos() if hasattr(presenter, "mouse_pos") else None
        log("clicker: click logical", (lx, ly), "screen", (wx, wy),
            "mouse_pos ->", pos)
        user32.mouse_event(_MOUSE_LEFT_DOWN, 0, 0, 0, 0)
        time.sleep(0.1)
        user32.mouse_event(_MOUSE_LEFT_UP, 0, 0, 0, 0)
        time.sleep(1.2)
        log("   shell.state after ->", _shell[0].state)
    time.sleep(0.5)
    log("clicker: posting QUIT")
    pygame.event.post(pygame.event.Event(pygame.QUIT))


_orig_build = gm._build_render_stack


def _build(*a, **k):
    out = _orig_build(*a, **k)
    _presenter[0] = out[0]
    log("presenter", out[0].name, "|", out[3])
    threading.Thread(target=_clicker, daemon=True).start()
    return out


gm._build_render_stack = _build

if __name__ == "__main__":
    # `backend=` is main()'s own parameter — the --backend flag is parsed only
    # in game/main.py's __main__ block, which this probe replaces.
    gm.main(backend=BACKEND)
