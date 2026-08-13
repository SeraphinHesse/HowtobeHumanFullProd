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

    Three cases, in order:

    * the slug is unused              -> the slug;
    * the slug is used and that entry's PNG is BYTE-IDENTICAL to `png_path`
                                      -> reuse it (the re-import case);
    * otherwise                       -> uniquify, ``<slug>_2``, ``<slug>_3``…

    The third case is a RULE, not a convenience: a master sheet is linked BY
    PATH from manifest entries, so overwriting ``master/characters.png`` with
    different art would silently re-point every slot already cutting it —
    wrong pixels, no error."""
    doc = load_registry_doc(data_dir)
    entries = doc.get("entries") or {}
    slug = _slugify(name)
    if slug not in entries:
        return slug
    # A hand-corrupted registry may hold a non-dict entry value. Degrade to
    # "not a re-import" rather than raising: this module's whole load path is
    # E-37 tolerant (see `load_registry_doc`), and the import path must not be
    # the one place a bad JSON value crashes the editor.
    entry = entries[slug]
    existing_file = entry.get("file", "") if isinstance(entry, dict) else ""
    existing = _data_dir(data_dir) / "sprites" / existing_file
    if existing_file and _same_bytes(existing, png_path):
        return slug
    return _unique_id(slug, entries)


def import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h):
    """Copy `png_path` -> ``<data_dir>/sprites/master/<sheet_id>.png`` and
    write its registry entry. Returns the new/reused sheet id.

    `display_name` names the sheet and seeds the id; it falls back to the PNG's
    own stem when blank (``editor/font_import.py:59`` precedent).

    RE-IMPORTING THE SAME PNG reuses the id, leaves the file byte-untouched
    (so ``git status`` stays clean) and REWRITES the entry — that is how a
    designer corrects a wrong ``display_name`` or ``frame_w`` without breeding
    a duplicate file. M3 deliberately has no refusal path for a changed grid:
    nothing links a slot to a master sheet until M4."""
    data_dir = _data_dir(data_dir)
    png_path = Path(png_path)
    name = (str(display_name or "").strip() or png_path.stem)
    sheet_id = resolve_sheet_id(data_dir, png_path, name)

    destination = data_dir.joinpath(*MASTER_SUBDIR) / f"{sheet_id}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _same_bytes(png_path, destination):
        destination.write_bytes(png_path.read_bytes())

    doc = load_registry_doc(data_dir)
    doc.setdefault("version", 1)
    doc.setdefault("entries", {})
    doc["entries"][sheet_id] = {
        "file": master_ref(sheet_id),
        "display_name": name,
        "frame_w": int(frame_w),
        "frame_h": int(frame_h),
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
