"""Read/enforce _lock on data/balancing/* (ED-32, D-11) — read-only.

The editor NEVER sets, clears, or force-unlocks a lock: /start-domain is
the only lock and /merge-domain the only unlock (branch+lock protocol,
T-1 — lands in Phase 8). This module only answers "is this domain locked,
and by whom" so the balancing panel can go read-only with the owner shown.

Reads go through engine.data_io.load_validated — the one sanctioned path
to data/ (D-2). Pure Python, no Qt, no pygame.
"""
from pathlib import Path

from engine import data_io

REPO = Path(__file__).resolve().parents[1]

DOMAINS = ("buildings", "enemies", "map", "ui", "core")  # canonical D-10 order


def balancing_path(domain, data_dir=None):
    base = Path(data_dir) if data_dir is not None else REPO / "data"
    return base / "balancing" / f"{domain}.json"


def schema_path(domain, data_dir=None):
    base = Path(data_dir) if data_dir is not None else REPO / "data"
    return base / "schemas" / f"{domain}.schema.json"


def lock_info(domain, data_dir=None):
    """The raw _lock value: \"UNLOCKED\" or {locked_by, since} (D-11)."""
    return data_io.load_validated(
        balancing_path(domain, data_dir), schema_path(domain, data_dir)
    )["_lock"]


def is_locked(domain, data_dir=None):
    return lock_info(domain, data_dir) != "UNLOCKED"


def owner(domain, data_dir=None):
    info = lock_info(domain, data_dir)
    return None if info == "UNLOCKED" else info["locked_by"]


def since(domain, data_dir=None):
    info = lock_info(domain, data_dir)
    return None if info == "UNLOCKED" else info["since"]
