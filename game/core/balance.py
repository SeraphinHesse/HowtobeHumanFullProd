"""Single validated balancing loader for all six domains (Phase 9D; ESV-3a
added ``vfx``).

Generalises 9C's ``game/map/tile_map.load_map_balance``. Every domain file
``data/balancing/<domain>.json`` validates against
``data/schemas/<domain>.schema.json`` through ``engine.data_io.load_validated``
(fail-loud: schema or JSON errors raise). The loaders return the raw validated
dict; game code reads tunables straight from it (G-7 — no value ever moves into
Python; ``data/`` stays the single source of truth).
"""
from pathlib import Path

from engine import data_io

DOMAINS = ("buildings", "enemies", "map", "ui", "core", "vfx")


def load_balance(data_dir, domain):
    """Load + schema-validate one balancing ``domain`` (one of ``DOMAINS``)."""
    data_dir = Path(data_dir)
    return data_io.load_validated(
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


def load_all(data_dir):
    """Every balancing domain as ``{domain: validated dict}``."""
    return {domain: load_balance(data_dir, domain) for domain in DOMAINS}
