"""Single-frame-vocabulary spritesheet import (ED-20/ED-40 palette import,
tile migration) — the shared half of "copy a PNG in, write a manifest v2
entry" that DOES NOT need DetailsPanel's multi-row RowEditor machinery
because map/deco slots' animation vocabulary (`data/slots.json`) is
`["idle"]` only. Pure Pillow + `engine.data_io`; no Qt, no pygame, so it is
usable from both `editor/panels/palette.py` and `tools/migrate_prototype_assets.py`.
"""
import shutil
from pathlib import Path

from PIL import Image

from engine import data_io


def import_idle_sheet(data_dir, registry, slot_key, png_path):
    """Copy png_path -> data/sprites/imported/<slot_key>.png and write/replace
    its manifest v2 entry as ONE idle row (frames = detected columns of the
    first row; additional detected rows are ignored — idle is the only
    animation these slots ever use). Off-grid sheets crop the remainder,
    same semantics as DetailsPanel's import (warn-but-import is the
    caller's job; this just reports the detected grid). Returns
    (cols, rows). Raises ValueError if the image is smaller than one frame.
    """
    data_dir = Path(data_dir)
    fw, fh = registry.frame_size(slot_key)
    with Image.open(png_path) as image:
        w, h = image.size
    cols, rows = w // fw, h // fh
    if cols < 1 or rows < 1:
        raise ValueError(
            f"image {w}x{h} is smaller than one {fw}x{fh} frame")

    destination = data_dir / "sprites" / "imported" / f"{slot_key}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if Path(png_path).resolve() != destination.resolve():
        shutil.copyfile(png_path, destination)

    manifest_path = data_dir / "sprites" / "asset_manifest.json"
    schema_path = data_dir / "schemas" / "asset_manifest.schema.json"
    try:
        doc = data_io.load_json(manifest_path)
    except (OSError, ValueError):
        doc = {"version": 2, "entries": {}}
    if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
        doc = {"version": 2, "entries": {}}

    doc["entries"][slot_key] = {
        "sheet": f"imported/{slot_key}.png",
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
    data_io.write_validated(doc, manifest_path, schema_path)
    return cols, rows
