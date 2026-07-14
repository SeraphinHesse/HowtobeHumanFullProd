"""Read/enforce _lock on data/balancing/* (ED-32, D-11) — read-only.

The editor NEVER sets, clears, or force-unlocks a lock: /start-domain is
the only lock and /merge-domain the only unlock (branch+lock protocol,
T-1 — lands in Phase 8). This module only answers "is this domain locked,
and by whom" so the balancing panel can go read-only with the owner shown.

Reads go through engine.data_io.load_validated — the one sanctioned path
to data/ (D-2). Pure Python, no Qt, no pygame.

The domain LIST is derived, not hardcoded (AD-6): `domains(data_dir)` is
slots.json's category order ∩ the categories that have a
data/balancing/<key>.json. A new balancing domain therefore appears in the
selector and the balancing panel the moment its files exist — with zero
editor edits. It is a FUNCTION, not a module constant, because every editor
module is data_dir-injectable (tests run against a temp copy of data/); a
constant derived at import from the repo's own data/ would be silently wrong
for any other tree.
"""
from pathlib import Path

from engine import data_io
from engine.assets import load_registry   # PURE half of engine.assets (no pygame)

REPO = Path(__file__).resolve().parents[1]


def _base(data_dir=None):
    return Path(data_dir) if data_dir is not None else REPO / "data"


def category_keys(data_dir=None, registry=None):
    """Every slots.json category key, in file (D-10 tree) order. Pass an
    already-loaded `registry` to reuse it — load_registry re-parses AND
    re-validates slots.json on every call."""
    if registry is None:
        registry = load_registry(_base(data_dir))
    return tuple(c.key for c in registry.categories())


def domains(data_dir=None, registry=None):
    """Balancing-domain keys: slots.json category order ∩ the categories that
    have a data/balancing/<key>.json (D-10 order). Derived — never hardcode
    this list; a new domain is one that brought its own balancing file.

    `registry` is an optional already-loaded SlotRegistry for that same
    data_dir (callers that just loaded one shouldn't pay for a second parse +
    jsonschema validation of slots.json)."""
    base = _base(data_dir)
    return tuple(key for key in category_keys(base, registry)
                 if balancing_path(key, base).exists())


def is_domain_category(key, data_dir=None):
    """True when a category is INTENDED as a balancing domain — i.e. it has a
    data/schemas/<key>.schema.json. Distinct from `domains()`: a domain whose
    balancing FILE is missing is still an intended domain, and the selector
    omits it whole rather than showing it as an asset-only category (a
    domain_selected on it would drive the balancing panel into a missing
    file). vfx/deco/backgrounds carry no schema — they are asset-only."""
    return schema_path(key, data_dir).exists()


def balancing_path(domain, data_dir=None):
    return _base(data_dir) / "balancing" / f"{domain}.json"


def schema_path(domain, data_dir=None):
    return _base(data_dir) / "schemas" / f"{domain}.schema.json"


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
