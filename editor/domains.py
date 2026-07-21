"""Domain derivation helpers for data/balancing/* — read-only, pure Python
(no Qt, no pygame). The selector and balancing panel resolve which
categories are balancing domains, and where a domain's data/schema files
live, through this module alone.

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
    file). deco/backgrounds carry no schema — they are asset-only. vfx
    WAS asset-only too, until ESV-3a gave it data/schemas/vfx.schema.json +
    data/balancing/vfx.json — it is a balancing domain now."""
    return schema_path(key, data_dir).exists()


def balancing_path(domain, data_dir=None):
    return _base(data_dir) / "balancing" / f"{domain}.json"


def schema_path(domain, data_dir=None):
    return _base(data_dir) / "schemas" / f"{domain}.schema.json"
