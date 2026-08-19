"""engine.coords — the coordinate authority (E-1..E-5). Pure Python."""
from pathlib import Path

from .camera import Camera, CameraLimit
from .geometry import Geometry
from .system import FRONT_RANK, CoordinateSystem

__all__ = ["Camera", "CameraLimit", "CoordinateSystem", "FRONT_RANK",
           "Geometry", "load_coordinate_system"]


def load_coordinate_system(data_dir, map_cols=None, map_rows=None,
                           zoom_levels=None, default_zoom=None):
    """Build a CoordinateSystem from data/geometry.json, schema-validated
    (E-1: geometry is data-driven, never hardcoded).

    map_cols/map_rows override geometry.json's dims — Phase 6: each map
    file owns its dimensions (D-20); geometry.json keeps tile pitch and
    zoom levels as global truth plus fallback dims for map-less hosts
    (the editor's entity preview grid).

    zoom_levels/default_zoom override geometry.json's zoom fallback — the
    real zoom tunable lives in the balancing `core` domain's `Camera` group;
    callers (game/editor) pass it here the same way each map passes its own
    cols/rows. When default_zoom is given, the camera opens at it via
    `set_zoom`, which reuses that method's "must be a valid level"
    ValueError as the cross-field check (default_zoom must be a member of
    zoom_levels) — schema for shape, loader for what it can't express."""
    from engine import data_io

    data_dir = Path(data_dir)
    data = data_io.load_validated(
        data_dir / "geometry.json", data_dir / "schemas" / "geometry.schema.json"
    )
    if map_cols is not None:
        data["map_cols"] = map_cols
    if map_rows is not None:
        data["map_rows"] = map_rows
    if zoom_levels is not None:
        data["zoom_levels"] = zoom_levels
    cs = CoordinateSystem(Geometry.from_dict(data))
    if default_zoom is not None:
        cs.set_zoom(default_zoom)
    return cs
