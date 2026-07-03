"""engine.coords — the coordinate authority (E-1..E-5). Pure Python."""
from pathlib import Path

from .camera import Camera
from .geometry import Geometry
from .system import CoordinateSystem

__all__ = ["Camera", "CoordinateSystem", "Geometry", "load_coordinate_system"]


def load_coordinate_system(data_dir, map_cols=None, map_rows=None):
    """Build a CoordinateSystem from data/geometry.json, schema-validated
    (E-1: geometry is data-driven, never hardcoded).

    map_cols/map_rows override geometry.json's dims — Phase 6: each map
    file owns its dimensions (D-20); geometry.json keeps tile pitch and
    zoom levels as global truth plus fallback dims for map-less hosts
    (the editor's entity preview grid)."""
    from engine import data_io

    data_dir = Path(data_dir)
    data = data_io.load_validated(
        data_dir / "geometry.json", data_dir / "schemas" / "geometry.schema.json"
    )
    if map_cols is not None:
        data["map_cols"] = map_cols
    if map_rows is not None:
        data["map_rows"] = map_rows
    return CoordinateSystem(Geometry.from_dict(data))
