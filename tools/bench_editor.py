"""Time the things the editor test suite pays for per test. A MANUAL tool.

This is never in the gate and never imported by a test — it is the thing you
run when you are about to claim a refactor made something faster, so that the
claim is a number instead of a guess.

    py tools/bench_editor.py                 # everything, 3 reps
    py tools/bench_editor.py --reps 5
    py tools/bench_editor.py --only copy registry

What it measures, and why each one is on the list:

``copy-data``      ``copytree(data/)`` — what ``TempDataCase.setUp`` does once
                   per test. The live tree is ~75 MB, of which audio/video are
                   the overwhelming bulk and no editor test reads a byte.
``copy-template``  the same copy from the pruned session template
                   (``tools/tests/temp_data.py``), which stands media in as
                   empty files of the same name. The pair is the A4 claim.
``load-registry``  ``load_registry(data_dir)`` x10 — roughly what one
                   ``MainWindow.__init__`` does across its panels. Before the
                   A3 validator cache this re-read AND re-``check_schema``'d a
                   36-76 KB schema on every call.
``main-window``    ``MainWindow(data_dir=...)`` construction. The editor tier's
                   dominant cost: ~450 of these across the suite.
``select-map``     ``selector.select_map(...)`` on the starter map.
``destroy``        ``qt_harness.destroy(window)``. On the list because it is
                   NOT optional: Qt's close() only hides, and leaked windows
                   made the combined suite quadratic. Any "amortise the
                   window" idea has to keep paying this.

Absolute numbers are hardware-specific — a cloud runner and a Windows box on
OneDrive are different worlds, and the copy benchmarks especially so. Compare
BEFORE and AFTER on the same machine; never quote one of these as an absolute.
"""
import argparse
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

LIVE_DATA = REPO / "data"


def _timed(fn):
    """Run fn, return (seconds, result)."""
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def _fmt(samples):
    """median (min-max) in ms."""
    ms = [s * 1000 for s in samples]
    return (f"{statistics.median(ms):8.1f} ms   "
            f"(min {min(ms):7.1f}, max {max(ms):7.1f}, n={len(ms)})")


# --------------------------------------------------------------- benchmarks

def bench_copy_data(reps):
    out = []
    for _ in range(reps):
        with tempfile.TemporaryDirectory() as tmp:
            dt, _ = _timed(lambda: shutil.copytree(LIVE_DATA,
                                                   Path(tmp) / "data"))
            out.append(dt)
    return out


def bench_copy_template(reps):
    """The pruned template's per-test copy. Skips cleanly before A4 lands."""
    try:
        from tools.tests.temp_data import template_data
    except ImportError:
        return None
    src = template_data()  # built once; not counted
    out = []
    for _ in range(reps):
        with tempfile.TemporaryDirectory() as tmp:
            dt, _ = _timed(lambda: shutil.copytree(src, Path(tmp) / "data"))
            out.append(dt)
    return out


def bench_load_registry(reps, data_dir):
    from engine.assets.registry import load_registry
    out = []
    for _ in range(reps):
        def ten():
            for _ in range(10):
                load_registry(data_dir)
        dt, _ = _timed(ten)
        out.append(dt)
    return out


def _qt():
    """Import the Qt harness lazily — it constructs a QApplication."""
    from tools.tests import qt_harness
    from editor.main import MainWindow
    return qt_harness, MainWindow


def bench_window(reps, data_dir):
    """Returns (construct, select_map, destroy) sample lists."""
    qt_harness, MainWindow = _qt()
    construct, select, teardown = [], [], []
    for _ in range(reps):
        dt, window = _timed(lambda: MainWindow(data_dir=data_dir))
        construct.append(dt)
        window.resize(1280, 720)
        window.show()

        # "first_light" is the starter map the editor suites pin as their
        # fixture. active_map.json lives in the same folder and is a pointer,
        # not a map, so it is never a valid selection.
        dt, _ = _timed(lambda: window.selector.select_map("first_light"))
        select.append(dt)

        dt, _ = _timed(lambda: qt_harness.destroy(window))
        teardown.append(dt)
    return construct, select, teardown


# -------------------------------------------------------------------- main

ALL = ("copy", "registry", "window")


def _main():
    ap = argparse.ArgumentParser(
        description="Manual editor benchmarks — never part of the gate.")
    ap.add_argument("--reps", type=int, default=3,
                    help="repetitions per benchmark (default 3)")
    ap.add_argument("--only", nargs="+", choices=ALL, default=list(ALL),
                    help=f"run a subset: {' '.join(ALL)}")
    args = ap.parse_args()

    print(f"bench_editor — {args.reps} rep(s) — "
          "RELATIVE numbers only; this machine is not the dev box.\n")
    rows = []

    if "copy" in args.only:
        rows.append(("copy-data", bench_copy_data(args.reps)))
        rows.append(("copy-template", bench_copy_template(args.reps)))

    if "registry" in args.only or "window" in args.only:
        # Every remaining benchmark needs a data dir that is safe to write to.
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            shutil.copytree(LIVE_DATA, data_dir)

            if "registry" in args.only:
                rows.append(("load-registry x10",
                             bench_load_registry(args.reps, data_dir)))
            if "window" in args.only:
                construct, select, teardown = bench_window(args.reps, data_dir)
                rows.append(("main-window", construct))
                rows.append(("select-map", select))
                rows.append(("destroy", teardown))

    for label, samples in rows:
        if samples is None:
            print(f"{label:<20} (not available yet — A4 has not landed)")
        elif not samples:
            print(f"{label:<20} (no samples)")
        else:
            print(f"{label:<20} {_fmt(samples)}")


if __name__ == "__main__":
    _main()
