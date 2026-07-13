"""Environment doctor — verifies a machine can actually run the game.

Run it after setup (``py tools/doctor.py``); ``setup.bat`` calls it as its last
step so a partial/conflicting dependency install fails LOUD instead of limping
into the menu and crashing on "new game".

It does three things:
  1. Reports the interpreter (version + path) — catches "pip installed into a
     different Python than ``py`` runs".
  2. Checks every dependency imports, prints its version, and flags the classic
     footgun: plain ``pygame`` installed ALONGSIDE ``pygame-ce`` (they share the
     ``pygame`` import name and a mixed install is subtly broken). Deps are split
     into GAME-required (needed for ``py game/main.py``), EDITOR-required (only
     ``py editor/main.py``), and OPTIONAL — a missing editor dep never blocks the
     game smoke.
  3. Actually builds a fresh game headlessly (the same path "new game" takes,
     including ``BaseBuilding``/``TierState``) so any environment breakage
     reproduces here with a full traceback instead of on the designer's screen.

Pure diagnostics — never modifies anything. Exit code 0 = healthy, 1 = broken.
"""
import importlib
import os
import sys

# Headless BEFORE any pygame import (safe on every OS; matches tools/smoke.py).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Repo root on sys.path so ``import game`` / ``import engine`` work when this is
# run as ``py tools/doctor.py`` from the project root.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# (import name, pip name, layer) — mirrors requirements.txt.
#   "game"     → needed to run py game/main.py (a failure blocks everything)
#   "editor"   → only py editor/main.py (missing = warn, game still fine)
#   "optional" → absent is fine (graceful skip)
_DEPS = [
    ("pygame", "pygame-ce", "game"),
    ("jsonschema", "jsonschema", "game"),
    ("PySide6", "PySide6", "editor"),
    ("PIL", "Pillow", "editor"),
    ("cv2", "opencv-python", "optional"),  # cutscene only; absent = graceful skip
]


def _ok(msg):
    print(f"  [ OK ] {msg}")


def _warn(msg):
    print(f"  [WARN] {msg}")


def _fail(msg):
    print(f"  [FAIL] {msg}")


def _dist_version(name):
    """Installed pip-distribution version, or None (import-name agnostic)."""
    try:
        from importlib import metadata
        return metadata.version(name)
    except Exception:
        return None


def check_interpreter():
    print("Interpreter")
    _ok(f"Python {sys.version.split()[0]}")
    print(f"         {sys.executable}")
    if sys.version_info < (3, 11):
        _fail("Python 3.11+ is required (setup.bat installs 3.13).")
        return False
    return True


def check_dependencies():
    """Returns (game_ok, editor_ok). Prints one line per dependency."""
    print("\nDependencies")
    game_ok = editor_ok = True

    # The pygame / pygame-ce conflict: same import name, mutually exclusive.
    if _dist_version("pygame-ce") and _dist_version("pygame"):
        _fail("BOTH 'pygame' and 'pygame-ce' are installed — they conflict and "
              "corrupt the pygame import. Fix:")
        print("         py -m pip uninstall -y pygame pygame-ce")
        print("         py -m pip install pygame-ce")
        game_ok = False

    for module, pip_name, layer in _DEPS:
        try:
            importlib.import_module(module)
            version = _dist_version(pip_name) or "?"
            _ok(f"{pip_name} ({module}) {version}  [{layer}]")
        except Exception as exc:  # report, never crash the doctor
            if layer == "optional":
                _warn(f"{pip_name} ({module}) missing — optional, skipping.")
            elif layer == "editor":
                _warn(f"{pip_name} ({module}) missing — the EDITOR won't run, "
                      "but the game will. Fix: py -m pip install " + pip_name)
                editor_ok = False
            else:
                _fail(f"{pip_name} ({module}) failed to import: "
                      f"{exc.__class__.__name__}: {exc}")
                print(f"         Fix: py -m pip install {pip_name}")
                game_ok = False
    return game_ok, editor_ok


def check_new_game():
    """Build a game headlessly — the exact path that was crashing on 'new game'."""
    print("\nNew-game smoke (headless)")
    try:
        import game.main as gmain
        gmain.main(max_frames=3, autostart=True)
    except Exception:
        import traceback
        _fail("Building a new game crashed — full traceback below:")
        print()
        traceback.print_exc()
        return False
    _ok("New game built and ran 3 frames.")
    return True


def main():
    print("=" * 60)
    print(" How To Be Human - environment doctor")
    print("=" * 60)

    interp_ok = check_interpreter()
    game_ok, editor_ok = check_dependencies() if interp_ok else (False, False)

    # The smoke is the most informative check — run it whenever the game-layer
    # deps are present, even if editor deps are missing.
    smoke_ok = check_new_game() if (interp_ok and game_ok) else None

    print("\n" + "=" * 60)
    if interp_ok and game_ok and smoke_ok:
        if editor_ok:
            print(" ALL CHECKS PASSED.")
        else:
            print(" GAME OK (editor deps missing - see [WARN] above).")
        print(" Run the game with:  py game\\main.py")
        print("=" * 60)
        return 0

    print(" PROBLEMS FOUND - see [FAIL] lines above. A clean reinstall fixes")
    print(" most dependency breakage:")
    print("   py -m pip uninstall -y pygame pygame-ce")
    print("   py -m pip install --upgrade pip")
    print("   py -m pip install -r requirements.txt")
    print("=" * 60)
    return 1


if __name__ == "__main__":
    sys.exit(main())
