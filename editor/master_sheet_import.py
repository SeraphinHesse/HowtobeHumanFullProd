"""Master-spritesheet import (GpuAndMasterSheetsPLAN M3, D1/D3) — the pure
half of "copy one big multi-character PNG into ``data/sprites/master/`` and
register it in ``data/sprites/master_sheets.json``".

Mirrors ``editor/asset_import.py``'s shape function-for-function (load doc /
write doc / ref helper / import / list) because the two registries are the
same kind of thing: a committed PNG plus metadata, read back by a picker.
Pillow + ``engine.data_io`` only — no Qt, no pygame. In
``test_editor_viewport.TestPurity``'s import list.
``editor/panels/master_sheet_dialog.py`` is its only caller.

WHAT A MASTER SHEET IS. One PNG holding MANY characters' rows stacked in a
single grid. It is not a ``data/slots.json`` slot: it is never previewed,
animated or rendered on its own. A manifest entry links to one by pointing its
``sheet`` at ``master/<id>.png`` and its ``row_start`` at the first row of its
window. The REGISTRY owns the grid (D3) — a linking slot inherits
``frame_w``/``frame_h`` from here and may not override them, so every slot
cutting one master sheet agrees on what row N means.

**``pad_to_frame`` is DELIBERATELY ABSENT** (``editor/asset_import.py:121``).
That helper CENTRES undersized art on a transparent canvas, which is right for
a single-slot sheet and catastrophic here: centring shifts every row by
``(pad - size) // 2`` and silently mis-cuts every ``row_start`` window taken
from the sheet. A master sheet is a grid the designer authored; it is copied
byte-for-byte or not at all. Do not "restore parity" with ``asset_import``.

ORPHANS ARE LEGAL (§9 / ``data/CLAUDE.md``). Nothing here deletes a PNG or an
entry. A master sheet with zero users stays on disk, stays in the registry and
stays listed in the picker — that is how you get it back. Hence no
``unreferenced_sheets`` analogue: nothing collects.
"""
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from editor.asset_import import load_manifest_doc, sheet_users
from engine import data_io

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DATA = REPO / "data"

REGISTRY_SUBPATH = ("sprites", "master_sheets.json")
SCHEMA_SUBPATH = ("schemas", "master_sheets.schema.json")
MASTER_SUBDIR = ("sprites", "master")


class GridInUseError(ValueError):
    """Refusal: a re-import would change ``frame_w``/``frame_h`` on a master
    sheet that manifest entries already cut windows out of (M4 §2.1).

    IT SUBCLASSES ``ValueError`` ON PURPOSE, AND THAT IS LOAD-BEARING.
    ``panels/master_sheet_dialog._on_import_clicked`` already catches
    ``(OSError, ValueError)`` and shows the message in a ``QMessageBox``, so
    this refusal reaches the designer with no dialog edit at all. "Cleaning
    up" the base class to ``Exception`` turns a readable refusal into an
    unhandled crash inside a Qt slot.

    WHY REFUSE. A linking entry stores ``row_start`` — a row index in THIS
    grid. Re-cutting the same PNG at a different frame size silently re-points
    every window at different pixels: wrong art, no error. That is the same
    hazard ``resolve_sheet_id``'s never-overwrite rule exists for, one axis
    over. With ZERO users nothing can be mis-cut, so the rewrite is still
    allowed — that is the "correct a wrong frame_w" flow M3 documented.
    """


def _data_dir(data_dir=None):
    return Path(data_dir) if data_dir is not None else DEFAULT_DATA


def registry_path(data_dir=None):
    """<data_dir>/sprites/master_sheets.json — no I/O."""
    return _data_dir(data_dir).joinpath(*REGISTRY_SUBPATH)


def schema_path(data_dir=None):
    """<data_dir>/schemas/master_sheets.schema.json — no I/O."""
    return _data_dir(data_dir).joinpath(*SCHEMA_SUBPATH)


def master_ref(sheet_id):
    """The canonical PNG path for a master sheet, ``master/<id>.png``.

    A CONSUMER MUST NOT RE-DERIVE THIS. Always read the registry entry's stored
    ``file`` (or the manifest entry's ``sheet``): the engine resolves
    ``sprites_dir / entry.sheet`` verbatim (``engine/assets/store.py``), so a
    path rebuilt from a key is a silently wrong file rather than an error. This
    helper exists for the ONE place that mints the path — the import below."""
    return f"master/{sheet_id}.png"


def load_registry_doc(data_dir=None):
    """The raw master-sheet registry doc, tolerant of a missing/corrupt file
    (E-37 — the pre-import state is normal; the file ships seeded EMPTY). Twin
    of ``asset_import.load_manifest_doc``."""
    try:
        doc = data_io.load_json(registry_path(data_dir))
    except (OSError, ValueError):
        return {"version": 1, "entries": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return doc


def write_registry_doc(data_dir, doc):
    """The ONE master_sheets.json write path (ED-31, through the validating
    writer). Twin of ``asset_import.write_manifest_doc``; no other module in
    this feature may call ``write_validated`` on this file."""
    data_io.write_validated(doc, registry_path(data_dir), schema_path(data_dir))


def frame_bounds(data_dir=None):
    """``(minimum, maximum)`` for frame_w/frame_h, READ FROM THE SCHEMA rather
    than retyped (ED-30: out-of-range input must be unrepresentable in the
    form, and the bound has exactly one home). Falls back to (1, 1024) — the
    schema's own numbers — if the schema is unreadable, so a broken checkout
    degrades to a usable form instead of a crash (E-37)."""
    try:
        schema = data_io.load_json(schema_path(data_dir))
        prop = (schema["properties"]["entries"]["patternProperties"]
                ["^[a-z][a-z0-9_]*$"]["properties"]["frame_w"])
        return int(prop["minimum"]), int(prop["maximum"])
    except (OSError, ValueError, KeyError, TypeError):
        return 1, 1024


def _slugify(name):
    """A lowercase ``[a-z0-9_]`` id matching master_sheets.schema.json's
    ``^[a-z][a-z0-9_]*$`` entry-key pattern. Copied from
    ``editor/font_import.py:20-26`` with the ``font`` prefix changed to
    ``sheet`` — the prefix is what buys the leading-letter guarantee."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"sheet_{slug}" if slug else "sheet"
    return slug


def _unique_id(base_slug, existing):
    if base_slug not in existing:
        return base_slug
    n = 2
    while f"{base_slug}_{n}" in existing:
        n += 1
    return f"{base_slug}_{n}"


def _slug_family(base_slug, existing):
    """``slug``, ``slug_2``, ``slug_3`` … as far as the registry actually goes.

    Stops at the first id NOT in `existing`, which is exactly where
    ``_unique_id`` would mint the next one — so the family scanned and the
    family numbered are the same set."""
    if base_slug not in existing:
        return
    yield base_slug
    n = 2
    while f"{base_slug}_{n}" in existing:
        yield f"{base_slug}_{n}"
        n += 1


def _same_bytes(a, b):
    """True when both paths exist and hold identical bytes (or ARE the same
    file). Master sheets are small enough to compare whole."""
    a, b = Path(a), Path(b)
    try:
        if a.resolve() == b.resolve():
            return True
        return a.read_bytes() == b.read_bytes()
    except OSError:
        return False


def resolve_sheet_id(data_dir, png_path, name):
    """The id ``import_master_sheet`` would use, without writing anything.

    Four cases, in order:

    * the slug is unused              -> the slug;
    * the slug is used and that entry's PNG is BYTE-IDENTICAL to `png_path`
                                      -> reuse it (the re-import case);
    * some LATER member of the slug FAMILY (``<slug>_2``, ``<slug>_3``…) is
      byte-identical                  -> reuse that one, lowest id first;
    * otherwise                       -> uniquify, ``<slug>_2``, ``<slug>_3``…

    The last case is a RULE, not a convenience: a master sheet is linked BY
    PATH from manifest entries, so overwriting ``master/characters.png`` with
    different art would silently re-point every slot already cutting it —
    wrong pixels, no error.

    THE FAMILY SCAN (third case) is what keeps that rule from breeding copies:
    once ``characters_2`` exists, re-importing ITS exact bytes used to compare
    them against ``characters`` only, mismatch, and mint a third identical
    ``characters_3``. The scan is deliberately scoped to the family and NOT to
    every id in the registry: a whole-registry scan would also collapse the
    same PNG imported deliberately under an unrelated display name into one
    entry, which is a different behaviour change and not this phase's call."""
    doc = load_registry_doc(data_dir)
    entries = doc.get("entries") or {}
    slug = _slugify(name)
    if slug not in entries:
        return slug
    sprites = _data_dir(data_dir) / "sprites"
    for sheet_id in _slug_family(slug, entries):
        # A hand-corrupted registry may hold a non-dict entry value. Degrade to
        # "not a re-import" rather than raising: this module's whole load path
        # is E-37 tolerant (see `load_registry_doc`), and the import path must
        # not be the one place a bad JSON value crashes the editor.
        entry = entries[sheet_id]
        existing_file = entry.get("file", "") if isinstance(entry, dict) else ""
        if existing_file and _same_bytes(sprites / existing_file, png_path):
            return sheet_id
    return _unique_id(slug, entries)


def import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h):
    """Copy `png_path` -> ``<data_dir>/sprites/master/<sheet_id>.png`` and
    write its registry entry. Returns the new/reused sheet id.

    `display_name` names the sheet and seeds the id; it falls back to the PNG's
    own stem when blank (``editor/font_import.py:59`` precedent).

    RE-IMPORTING THE SAME PNG reuses the id, leaves the file byte-untouched
    (so ``git status`` stays clean) and REWRITES the entry — that is how a
    designer corrects a wrong ``display_name`` or ``frame_w`` without breeding
    a duplicate file. **While the sheet has ZERO users that still holds
    exactly** (nothing links to it, so nothing can be mis-cut); once manifest
    entries DO link to it, a re-import that changes ``frame_w``/``frame_h``
    raises ``GridInUseError`` instead, naming the slots to fix first (M4
    §2.1). The refusal happens BEFORE the PNG copy and before the registry
    write, so a refused import leaves disk byte-identical."""
    data_dir = _data_dir(data_dir)
    png_path = Path(png_path)
    name = (str(display_name or "").strip() or png_path.stem)
    sheet_id = resolve_sheet_id(data_dir, png_path, name)
    frame_w, frame_h = int(frame_w), int(frame_h)

    doc = load_registry_doc(data_dir)
    doc.setdefault("version", 1)
    doc.setdefault("entries", {})
    existing = doc["entries"].get(sheet_id)
    stored_grid = ((existing.get("frame_w"), existing.get("frame_h"))
                   if isinstance(existing, dict) else None)
    if stored_grid is not None and stored_grid != (frame_w, frame_h):
        # ONE refcount in the editor (`asset_import.sheet_users`), never a
        # second. A non-int stored value compares unequal and lands here too,
        # which is the safe direction: refuse rather than silently re-cut.
        users = sheet_users(load_manifest_doc(data_dir), master_ref(sheet_id))
        if users:
            raise GridInUseError(
                f"'{sheet_id}' is cut at {stored_grid[0]}×{stored_grid[1]} by "
                f"{len(users)} slot(s): {', '.join(users)}. Re-importing it at "
                f"{frame_w}×{frame_h} would re-cut every row window into "
                f"different pixels. Clear or re-point those slots first, then "
                f"import again.")

    destination = data_dir.joinpath(*MASTER_SUBDIR) / f"{sheet_id}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _same_bytes(png_path, destination):
        destination.write_bytes(png_path.read_bytes())

    doc["entries"][sheet_id] = {
        "file": master_ref(sheet_id),
        "display_name": name,
        "frame_w": frame_w,
        "frame_h": frame_h,
    }
    write_registry_doc(data_dir, doc)
    return sheet_id


@dataclass(frozen=True)
class MasterSheet:
    """One registered master spritesheet, as offered by the picker.

    `frame_w`/`frame_h` are the DECLARED grid the registry owns (D3);
    `width`/`height` are the PNG's real pixel size. `users` is empty for an
    ORPHAN — a registered sheet no manifest entry points at. Orphans are listed
    on purpose (§9): it is how you get that art back."""
    sheet_id: str
    ref: str            # "master/<id>.png" — the entry's STORED file, verbatim
    path: Path
    display_name: str
    frame_w: int
    frame_h: int
    width: int
    height: int
    users: tuple        # slot keys pointing at it, sorted

    def grid(self):
        """(cols, rows) at the sheet's OWN declared frame size. No caller may
        supply a frame size — D3 says the master sheet owns the grid and a
        linking slot inherits it, so there is no target size to slice at (and
        hence no ``fits()`` analogue either)."""
        return (self.width // self.frame_w, self.height // self.frame_h)


def master_sheets(data_dir=None):
    """Every entry in the master-sheet registry, annotated with its real pixel
    size and the slots using it.

    SORTED BY ``display_name``, case-insensitively, with the sheet id as the
    tie-break — this list IS what the picker shows, so it is ordered the way a
    designer scans it.

    The REGISTRY is the authority here (unlike ``imported_sheets``, which globs
    the folder): a stray PNG in ``sprites/master/`` is not a master sheet until
    it has an entry. Conversely an entry whose PNG has vanished is SKIPPED, not
    fatal (E-37) — someone deleting a file by hand must not break the picker.
    Pillow only parses the header (``Image.open`` is lazy).

    `users` comes from ``asset_import.sheet_users`` against the manifest read
    ONCE — there is exactly one refcount in the editor, not two."""
    data_dir = _data_dir(data_dir)
    manifest = load_manifest_doc(data_dir)
    entries = (load_registry_doc(data_dir).get("entries") or {})
    sheets = []
    for sheet_id, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        ref = entry.get("file")
        if not isinstance(ref, str):
            continue
        path = data_dir / "sprites" / ref
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, ValueError):
            continue        # a vanished/unreadable PNG is skipped, never fatal
        sheets.append(MasterSheet(
            sheet_id=sheet_id,
            ref=ref,
            path=path,
            display_name=entry.get("display_name", sheet_id),
            frame_w=int(entry.get("frame_w", 1)),
            frame_h=int(entry.get("frame_h", 1)),
            width=width,
            height=height,
            users=sheet_users(manifest, ref)))
    sheets.sort(key=lambda sheet: (sheet.display_name.casefold(),
                                   sheet.sheet_id))
    return sheets
