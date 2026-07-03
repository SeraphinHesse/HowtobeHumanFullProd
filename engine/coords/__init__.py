"""engine.coords — the coordinate authority (E-1..E-5). Pure Python."""
from pathlib import Path

from .camera import Camera
from .geometry import Geometry
from .system import CoordinateSystem

__all__ = ["Camera", "CoordinateSystem", "Geometry", "load_coordinate_system"]


def load_coordinate_system(data_dir):
    """Build a CoordinateSystem from data/geometry.json, schema-validated
    (E-1: geometry is data-driven, never hardcoded)."""
    from engine import data_io

    data_dir = Path(data_dir)
    data = data_io.load_validated(
        data_dir / "geometry.json", data_dir / "schemas" / "geometry.schema.json"
    )
    return CoordinateSystem(Geometry.from_dict(data))
