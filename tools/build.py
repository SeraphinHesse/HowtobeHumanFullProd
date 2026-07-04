"""PyInstaller one-folder build (T-4, ED-51).

    py tools/build.py

Validates data/ (fail loud before spending a minute on a broken build — see
tools/smoke.py's validate_data, reused here rather than duplicated), then runs
PyInstaller against game/main.py: one-folder build, data/ bundled alongside
the exe, output at dist/HowToBeHuman/HowToBeHuman.exe (ED-52's launch
target). Never commit build/ or dist/ (gitignored).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def build_command(data_dir=None, dist_dir=None, repo=None):
    repo = Path(repo) if repo is not None else REPO
    data_dir = Path(data_dir) if data_dir is not None else repo / "data"
    dist_dir = Path(dist_dir) if dist_dir is not None else repo / "dist"
    return [
        sys.executable, "-m", "PyInstaller",
        str(repo / "game" / "main.py"),
        "--name", "HowToBeHuman",
        "--onedir",
        "--noconfirm",
        "--distpath", str(dist_dir),
        "--workpath", str(repo / "build"),
        "--add-data", f"{data_dir}{os.pathsep}data",
    ]


def main():
    from tools.smoke import validate_data

    validate_data()
    result = subprocess.run(build_command(), cwd=REPO)
    if result.returncode != 0:
        print("build: FAILED")
        return result.returncode
    print("build: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
