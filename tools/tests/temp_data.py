"""``TempDataCase`` — a private, writable ``data/`` tree per test.

Lives here rather than in ``test_editor_panels.py`` (where it grew up) because
seven other modules already reached across to import it, and three more had
copy-pasted its ``copytree`` by hand. ``test_editor_panels`` re-exports it, so
no existing import site changed.

WHY THE TEMPLATE. ``setUp`` used to ``copytree`` the live ``data/`` tree per
test — ~73 MB across ~300 files, of which ``audio/`` (46 MB) and ``video/``
(15 MB) are 84% that no editor test reads a byte of. Paid ~450 times over the
editor tier, on a dev box where ``data/`` sits in OneDrive.

So the tree is copied ONCE per process into a pruned template, and each test
copies THAT. Media files are stood in as **empty files with the same names**,
never deleted: directory listings, registry entries, manifest refs and
``exists()`` checks all still see exactly the same tree. Only the bytes are
gone, and only for file types whose bytes are decoded by a media library
nothing in the editor suite invokes. ``test_fixture_guard`` pins that the
template's FILE SET is identical to ``data/``'s, so pruning can never silently
become deleting.

Sprites are deliberately NOT stubbed. PNGs are small, and several tests decode
them for real (``test_bake_ui_sheets`` needs the actual ``main_menu_bg.png``
pixels, and ``pin_slot_rows`` writes real sheets with Pillow).

A test that genuinely needs real media bytes sets ``FULL_ASSETS = True`` on its
class and gets an unpruned copy of the live tree.

WHY NOT HARDLINKS. They look free and are a trap: ``data_io.write_validated``
ends in ``write_text``, which opens the existing inode ``"w"`` and TRUNCATES
it. The first panel save in the first test would corrupt the shared template
for every other test in the process. Only safe once every writer is atomic
(write-temp-then-replace), which is a separate change.
"""
import atexit
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.tests.qt_harness import QtCase

REPO = Path(__file__).resolve().parents[2]
LIVE_DATA = REPO / "data"

#: Suffixes stood in as empty files in the template. Media only — decoded by
#: pygame.mixer / OpenCV, neither of which any editor test drives. Adding an
#: extension here is a real decision: if ANY test decodes those bytes, it must
#: set FULL_ASSETS instead.
STUB_SUFFIXES = frozenset({".wav", ".mp3", ".ogg", ".mp4"})

#: Dropped from every copy (pruned or full). A runtime-populated log, not seed
#: content — the repo's copy can carry real entries from live editor sessions
#: that would otherwise leak into every test's starting state.
DROPPED_DIRS = ("balancing_history",)

_TEMPLATE = None


def _prune(dest):
    """Empty every media file in `dest`, and drop the runtime log dirs."""
    for name in DROPPED_DIRS:
        target = Path(dest) / name
        if target.exists():
            shutil.rmtree(target)
    for path in Path(dest).rglob("*"):
        if path.is_file() and path.suffix.lower() in STUB_SUFFIXES:
            # Truncate in place: the name, the parent dir and the entry in
            # every manifest that references it all survive untouched.
            path.write_bytes(b"")


def template_data():
    """The pruned template tree, built at most once per process.

    Returns the path to a ``data`` directory. Never write to it — it is the
    source every test copies FROM.
    """
    global _TEMPLATE
    if _TEMPLATE is None:
        tmp = tempfile.TemporaryDirectory(prefix="hth-data-template-")
        atexit.register(tmp.cleanup)
        dest = Path(tmp.name) / "data"
        shutil.copytree(LIVE_DATA, dest)
        _prune(dest)
        _TEMPLATE = dest
    return _TEMPLATE


def fresh_data_dir(case, *, full_assets=False):
    """Copy a private ``data/`` tree for `case` and return its path.

    Registers its own cleanup on the TestCase. `full_assets` copies the live
    tree with real media bytes instead of the pruned template.
    """
    tmp = tempfile.TemporaryDirectory()
    case.addCleanup(tmp.cleanup)
    data_dir = Path(tmp.name) / "data"
    if full_assets:
        shutil.copytree(LIVE_DATA, data_dir)
        for name in DROPPED_DIRS:
            target = data_dir / name
            if target.exists():
                shutil.rmtree(target)
    else:
        shutil.copytree(template_data(), data_dir)
    return data_dir


class DataDirCase(unittest.TestCase):
    """A private ``data/`` copy, with no Qt involvement.

    For the non-Qt modules that only ever wanted write isolation
    (``test_timeline_ops``, ``test_game_boot``, ``test_bake_ui_sheets``).
    ``TempDataCase`` is this plus ``QtCase``.
    """

    #: set True on a class that decodes real audio/video bytes.
    FULL_ASSETS = False

    def setUp(self):
        super().setUp()
        self.data_dir = fresh_data_dir(self, full_assets=self.FULL_ASSETS)


class TempDataCase(QtCase, DataDirCase):
    """Copies data/ into a temp dir so writes never touch the repo.

    Inherits QtCase: wrap every widget you build in self.track(...) so it is
    destroyed with the test rather than leaked for the life of the process.
    That contract is NOT optional — Qt's close() only hides, and leaked
    windows are what made the combined suite quadratic (406s split vs 1162s
    combined).
    """

    def unassign_slot(self, *slot_keys):
        """Guarantee each `slot_key` has NO ART AT ALL in the temp copy.

        Never assume a slot is unassigned just because it is TODAY. Art lands
        on slots over time, and a test that picks today's empty slot as its
        "no art here" fixture is a time bomb: commit 2512a84 gave
        painter_t1_lvl1 an `idle` row and silently broke five tests that had
        done exactly that. Pin the fixture instead of inheriting it from
        whatever the artists last imported.

        Dropping the manifest ENTRY is not enough on its own: a slot with no
        entry still resolves art from `imported/<slot>.png`
        (`details.py:_sheet_ref`), so an artist merely dropping a PNG next to
        the key re-arms the slot. 8e0e7d3 added cond_mountain_buildable.png and
        reddened the tint test that way, with no code change anywhere.
        `_rewrite_manifest` deletes the fallback sheet too."""
        self._rewrite_manifest(lambda k: k in slot_keys)

    def unassign_family(self, *prefixes):
        """Empty every slot whose key starts with one of `prefixes`.

        A ● marker on a GROUP node lights up if ANY slot under it has art, so
        emptying one tier of Painter is not enough — all nine painter_* slots
        have sheets. Keying off the prefix means a future painter_t4 is
        covered too, instead of quietly re-reddening the test."""
        self._rewrite_manifest(lambda k: k.startswith(prefixes))

    def pin_slot_rows(self, slot_key, animations, *, frames=4, fps=8,
                      hidden=(), sheet=None):
        """Pin a slot's manifest entry to exactly `animations` (one row each),
        and write a matching synthetic sheet.

        The counterpart to `unassign_slot` for "this slot HAS art of this
        shape". A test that reads the ROW COUNT or the animation names of a
        real slot is asserting what an artist last imported, not what the code
        does: `cff77c7` ("Stonethrower all eras") grew stone_thrower_t1_lvl1
        from 2 rows to 6 and reddened two tests that had nothing to do with
        eras. Supply the state instead of inheriting it.

        Returns the entry dict as written. `hidden` applies to the LAST row
        (the one those tests inspect); `sheet` overrides the ref, which is how
        you pin a shared sheet."""
        from PIL import Image

        from engine.assets import load_registry

        registry = load_registry(self.data_dir)
        frame_w, frame_h = registry.frame_size(slot_key)
        ref = sheet or f"imported/{slot_key}.png"
        png = self.data_dir / "sprites" / ref
        png.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (frames * frame_w, len(animations) * frame_h),
                  (200, 60, 60, 255)).save(png)

        rows = [{"animation": name, "frames": frames, "fps": fps,
                 "hidden": [], "loop_start": 0, "loop_end": 0, "loop_count": 1}
                for name in animations]
        rows[-1]["hidden"] = list(hidden)
        entry = {"sheet": ref, "frame_w": frame_w, "frame_h": frame_h,
                 "offset_x": 0, "offset_y": 0, "rows": rows}

        from engine import data_io

        path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(path)
        doc["entries"][slot_key] = entry
        data_io.write_validated(
            doc, path,
            self.data_dir / "schemas" / "asset_manifest.schema.json")
        return entry

    def _rewrite_manifest(self, should_drop):
        from engine import data_io

        path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(path)
        doc["entries"] = {k: v for k, v in doc["entries"].items()
                          if not should_drop(k)}
        data_io.write_validated(
            doc, path,
            self.data_dir / "schemas" / "asset_manifest.schema.json")
        self._drop_fallback_sheets(doc, should_drop)

    def _drop_fallback_sheets(self, doc, should_drop):
        """Delete `imported/<key>.png` for every selected slot — an entryless
        key is only genuinely empty once its fallback sheet is gone too.

        Selection is over the REGISTRY's slot keys, not the manifest's: the
        whole point is that a slot can carry art with no entry at all. Never
        touches a sheet a SURVIVING entry links to — one PNG can back many
        slots (`editor/panels/CLAUDE.md`, "Use Spritesheet…"), and deleting a
        shared file would silently empty an unrelated slot."""
        from engine.assets import load_registry

        kept_refs = {e.get("sheet") for e in doc["entries"].values()}
        for key in load_registry(self.data_dir).slot_keys():
            if not should_drop(key):
                continue
            ref = f"imported/{key}.png"
            if ref in kept_refs:
                continue
            png = self.data_dir / "sprites" / ref
            if png.exists():
                png.unlink()

    def drop_slot_variants(self, *stems):
        """Strip generated `<stem>_v<N>` variants from the temp slots.json.

        `add_variant` numbers the next variant from what already exists, so any
        test asserting "the next one is _v2" is really asserting "the repo has
        no variants yet" — a fact about live data, not about the code. Pin it:
        strip the variants, and the arithmetic is the test's own."""
        from engine import data_io

        pattern = re.compile(
            r"^(?:%s)_v\d+$" % "|".join(re.escape(s) for s in stems))

        def is_key_list(key, value):
            # "slots" means two things in this file: a category's slot
            # DEFINITIONS (dicts) and a group's slot KEY list (strings). Only
            # the latter is ours.
            return (key == "slots" and isinstance(value, list)
                    and all(isinstance(s, str) for s in value))

        def scrub(node):
            if isinstance(node, dict):
                return {k: ([s for s in v if not pattern.match(s)]
                            if is_key_list(k, v) else scrub(v))
                        for k, v in node.items()}
            if isinstance(node, list):
                return [scrub(item) for item in node]
            return node

        path = self.data_dir / "slots.json"
        data_io.write_validated(
            scrub(data_io.load_json(path)), path,
            self.data_dir / "schemas" / "slots.schema.json")

    def empty_screens(self, *screen_ids):
        """Pin `data/ui/screens/<screen_id>.json` to `{}` in the temp copy —
        the "no override written yet" starting state some UIScreenSession /
        viewport tests assume for their fixture screen. Same "pin, don't
        inherit" rule as `unassign_slot`/`unassign_family`: a screen a
        designer has since styled in the live repo (10L wave 3 baked every
        screen a real skin) must not silently change what these tests start
        from."""
        from engine import data_io

        schema = self.data_dir / "schemas" / "ui_screen.schema.json"
        for screen_id in screen_ids:
            path = self.data_dir / "ui" / "screens" / f"{screen_id}.json"
            data_io.write_validated({}, path, schema)
