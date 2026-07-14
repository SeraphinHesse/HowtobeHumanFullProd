"""Single-frame-vocabulary spritesheet import (ED-20/ED-40 palette import,
tile migration) — the shared half of "copy a PNG in, write a manifest v2
entry" that DOES NOT need DetailsPanel's multi-row RowEditor machinery
because map/deco slots' animation vocabulary (`data/slots.json`) is
`["idle"]` only. Pure Pillow + `engine.data_io`; no Qt, no pygame, so it is
usable from both `editor/panels/palette.py` and `tools/migrate_prototype_assets.py`.

Also the home of the SHEET-SHARING helpers (`imported_sheets`, `sheet_users`,
`unreferenced_sheets`). A manifest entry's `sheet` is a real relative path the
engine resolves as-is (`engine/assets/store.py`: `sprites_dir / entry.sheet`) —
it is NOT derived from the slot key. So two slots may point at ONE PNG (the
DetailsPanel "Use Spritesheet…" link), which is why deleting a slot's art has to
consult a refcount instead of unlinking `imported/<slot>.png` blind.
"""
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from engine import data_io


def sheet_ref(slot_key):
    """The canonical sheet path for art a slot OWNS (D-31). A slot that links
    to another slot's sheet carries that slot's ref instead — always read the
    entry's `sheet` rather than re-deriving it from the key."""
    return f"imported/{slot_key}.png"


def load_manifest_doc(data_dir):
    """The raw manifest v2 doc, tolerant of a missing/corrupt file (E-37 — the
    pre-import state is normal). Shared by the palette import, DetailsPanel and
    the sheet picker so they can't drift."""
    path = Path(data_dir) / "sprites" / "asset_manifest.json"
    try:
        doc = data_io.load_json(path)
    except (OSError, ValueError):
        return {"version": 2, "entries": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        return {"version": 2, "entries": {}}
    return doc


def write_manifest_doc(data_dir, doc):
    """The ONE manifest write path (ED-31, through the validating writer)."""
    data_dir = Path(data_dir)
    data_io.write_validated(
        doc,
        data_dir / "sprites" / "asset_manifest.json",
        data_dir / "schemas" / "asset_manifest.schema.json")


def sheet_users(doc, ref):
    """Slot keys whose manifest entry points at `ref` — the refcount that makes
    Clear safe. Empty ⇒ the PNG is unreferenced and free to delete."""
    entries = (doc or {}).get("entries") or {}
    return tuple(sorted(
        slot for slot, entry in entries.items()
        if isinstance(entry, dict) and entry.get("sheet") == ref))


def unreferenced_sheets(doc, refs):
    """The subset of `refs` no remaining entry in `doc` uses. Pass the sheet the
    cleared entry pointed at PLUS the slot's own-name ref: clearing a linker must
    not delete art its source still needs, and clearing the last user of a shared
    sheet must still collect it."""
    return tuple(ref for ref in dict.fromkeys(refs) if not sheet_users(doc, ref))


@dataclass(frozen=True)
class ImportedSheet:
    """One PNG in data/sprites/imported/, as offered by the "Use Spritesheet…"
    picker. `users` is empty for an ORPHAN — a sheet on disk no entry references
    (a slot that was re-linked away from art it owned). Orphans are listed on
    purpose: it is how you get that art back."""
    ref: str            # "imported/<name>.png" — what goes in the entry
    path: Path
    width: int
    height: int
    users: tuple        # slot keys pointing at it, sorted

    @property
    def name(self):
        return self.path.stem

    def grid(self, frame_w, frame_h):
        """(cols, rows) this sheet slices into at a frame size — 0 on either
        axis means it can't yield a single whole frame."""
        return (self.width // frame_w, self.height // frame_h)

    def fits(self, frame_w, frame_h):
        """True when the sheet divides cleanly into whole frames of this size —
        the picker's default filter, so a 64x32 tile sheet isn't offered for a
        64x96 building slot unless you ask for it."""
        cols, rows = self.grid(frame_w, frame_h)
        return (cols >= 1 and rows >= 1
                and self.width % frame_w == 0 and self.height % frame_h == 0)


def imported_sheets(data_dir):
    """Every PNG already in data/sprites/imported/, newest-import-agnostic and
    sorted by name, each annotated with the slots using it. Reads the manifest
    ONCE. Pillow only parses the header here — `Image.open` is lazy."""
    data_dir = Path(data_dir)
    doc = load_manifest_doc(data_dir)
    sheets = []
    for path in sorted((data_dir / "sprites" / "imported").glob("*.png")):
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (OSError, ValueError):
            continue        # unreadable art is skipped, never fatal (E-37)
        ref = f"imported/{path.name}"
        sheets.append(ImportedSheet(ref=ref, path=path, width=width,
                                    height=height, users=sheet_users(doc, ref)))
    return sheets


def pad_to_frame(image, fw, fh):
    """Grow `image` (a PIL Image) so it is at least one fw x fh frame, with the
    original art CENTRED on a fully transparent canvas. Never upscales, never
    shrinks, never crops. Returns (image, padded: bool) — `padded` False means
    the image already covered a frame in both axes and is byte-untouched.

    Per-axis: an axis that already spans a frame is left alone, so a wide short
    strip pads only vertically and keeps its column count.
    """
    w, h = image.size
    if w >= fw and h >= fh:
        return image, False
    pad_w, pad_h = max(w, fw), max(h, fh)
    canvas = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
    canvas.paste(image.convert("RGBA"), ((pad_w - w) // 2, (pad_h - h) // 2))
    return canvas, True


def import_idle_sheet(data_dir, registry, slot_key, png_path):
    """Copy png_path -> data/sprites/imported/<slot_key>.png and write/replace
    its manifest v2 entry as ONE idle row (frames = detected columns of the
    first row; additional detected rows are ignored — idle is the only
    animation these slots ever use). Off-grid sheets crop the remainder,
    same semantics as DetailsPanel's import (warn-but-import is the
    caller's job; this just reports the detected grid). Art smaller than one
    frame is padded onto a transparent frame-sized canvas and centred (ED-40),
    never rejected and never upscaled. Returns (cols, rows).
    """
    data_dir = Path(data_dir)
    fw, fh = registry.frame_size(slot_key)
    with Image.open(png_path) as image:
        padded, was_padded = pad_to_frame(image, fw, fh)
        w, h = padded.size
    cols, rows = w // fw, h // fh

    destination = data_dir / "sprites" / "imported" / f"{slot_key}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if was_padded:
        padded.save(destination)
    elif Path(png_path).resolve() != destination.resolve():
        # A byte-identical copy — migrate_prototype_assets.py's idempotency
        # depends on an already-big-enough sheet staying untouched.
        shutil.copyfile(png_path, destination)

    doc = load_manifest_doc(data_dir)
    doc["entries"][slot_key] = {
        "sheet": sheet_ref(slot_key),
        "frame_w": fw,
        "frame_h": fh,
        "offset_x": 0,
        "offset_y": 0,
        "rows": [{
            "animation": "idle",
            "frames": cols,
            "fps": 8,
            "hidden": [],
            "loop_start": 0,
            "loop_end": 0,
            "loop_count": 1,
        }],
    }
    write_manifest_doc(data_dir, doc)
    return cols, rows
