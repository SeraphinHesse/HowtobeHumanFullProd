"""Pure load/edit/write helpers for the Boss Upgrade Timeline panel
(``data/balancing/boss_upgrades.json`` — BossUpgradeTimelinePLAN BU-5).
Qt-free, pygame-free (``TestPurity``): ``editor/panels/boss_upgrades.py`` is
the only caller, staging every drag-and-drop / inline-text / spinbox edit
into an in-memory doc and calling ``save_boss_upgrades`` only on an explicit
Save. Modelled function-for-function on ``editor/timeline_ops.py``, the
building-unlock Timeline's twin — with ONE capability that panel has no need
of: the CATALOG itself is editable here (``set_catalog_field``), because a
boss upgrade's card title, body text and numeric params are designer content
while a building card's are derived from ``buildings.json``.

The document is two halves (D8):

* ``BossUpgrades.Catalog`` — 12 FIXED named keys, each ``{name, description,
  params}``. The roster is closed (each upgrade needs bespoke game code), so
  nothing here adds or removes an entry; only the three fields are edited.
* ``BossUpgrades.Timeline.milestones`` — a FIXED-length-4 array, each
  ``{slots: [id|null, id|null, id|null], retaliation_bonus_love: int}``.
  Milestones cycle every 4th bossfight (D1).

Two deliberate differences from ``timeline_ops``:

* ``assign_slot`` OVERWRITES SILENTLY (D10) and never checks uniqueness —
  the building Timeline's panel greys out an already-placed card instead,
  which cannot work here: an upgrade dragged from a slot it already occupies
  is the normal way a designer moves it.
* ``validate_uniqueness`` therefore RETURNS a list of double-placed ids
  rather than raising, and ``save_boss_upgrades`` deliberately does not
  consult it — the ``timeline_ops.round_warnings`` stance (warn, don't
  block), not its ``validate_uniqueness`` one. D3's "each upgrade appears in
  at most one slot" is an authoring intent the panel SURFACES; blocking Save
  on it would trap a designer halfway through moving a card between two
  milestones, which is exactly the state silent overwrite exists to allow.
"""
from engine import data_io

from editor import domains

DOMAIN = "boss_upgrades"

# The 4-milestone cycle and the 3 slots per milestone are design decisions
# (D1/D2), fixed by the schema's minItems/maxItems — not designer dials. They
# are named here so the panel builds its grid off ONE source instead of two
# hardcoded loop bounds.
MILESTONE_COUNT = 4
SLOTS_PER_MILESTONE = 3


def boss_upgrades_path(data_dir=None):
    return domains.balancing_path(DOMAIN, data_dir)


def boss_upgrades_schema_path(data_dir=None):
    return domains.schema_path(DOMAIN, data_dir)


def load_boss_upgrades(data_dir=None):
    """``data/balancing/boss_upgrades.json``, schema-validated. Raises on a
    missing/invalid file — the panel opens on this only after its selector
    leaf is selected, so a broken tree should be loud here (the
    ``timeline_ops.load_progression`` precedent); the PANEL catches and shows
    an E-37 placeholder rather than raising out of a Qt slot."""
    return data_io.load_validated(
        boss_upgrades_path(data_dir), boss_upgrades_schema_path(data_dir))


def catalog(doc):
    return doc["BossUpgrades"]["Catalog"]


def upgrade_ids(doc):
    """Every catalog id, sorted — the browse list's order. The roster is
    closed (12 fixed schema keys), so this never varies at runtime."""
    return tuple(sorted(catalog(doc)))


def milestones(doc):
    return doc["BossUpgrades"]["Timeline"]["milestones"]


def milestone_slots(doc, milestone_idx):
    """The 3 slot values of one milestone (ids and/or ``None``)."""
    return tuple(milestones(doc)[milestone_idx]["slots"])


def retaliation_love(doc, milestone_idx):
    return milestones(doc)[milestone_idx]["retaliation_bonus_love"]


# -- staged edits (the panel's ONLY mutation path) --------------------------

def assign_slot(doc, milestone_idx, slot_idx, upgrade_id):
    """Place an upgrade into a milestone slot. **Overwrites silently** (D10)
    — no confirmation, and no uniqueness check: an id already placed
    elsewhere is accepted here and reported by ``validate_uniqueness`` so the
    panel can show it. Raises ``KeyError`` on an unknown upgrade id (the
    schema's slot enum is closed, so writing one would fail validation at
    Save anyway — failing at the drop is the honest place)."""
    if upgrade_id is not None and upgrade_id not in catalog(doc):
        raise KeyError(f"unknown boss upgrade id {upgrade_id!r}")
    milestones(doc)[milestone_idx]["slots"][slot_idx] = upgrade_id


def clear_slot(doc, milestone_idx, slot_idx):
    """Empty a slot without removing it — the array is fixed at 3 (D2), so a
    cleared slot becomes ``None``, never a shorter list."""
    milestones(doc)[milestone_idx]["slots"][slot_idx] = None


def set_retaliation_love(doc, milestone_idx, value):
    """The love a LOST bossfight on this milestone pays (D7 — the sole
    source of truth now that ``enemies.json``'s ``loss_love_reward`` is
    retired)."""
    milestones(doc)[milestone_idx]["retaliation_bonus_love"] = int(value)


def set_catalog_field(doc, upgrade_id, field, value):
    """Edit one catalog field: ``"name"``, ``"description"``, or a key inside
    that upgrade's ``params``. The new capability this panel has and the
    building Timeline's does not.

    **Param values are coerced to the type already in the doc**, not to the
    widget's type: the doc was schema-validated on load, so its own value is
    the authority on whether a param is an integer (``slow_pct``) or a number
    (``duration_seconds``) — and a designer editing an int param through a
    double spin must not silently rewrite it as a float that then fails the
    schema's ``"type": "integer"`` at Save. Bounds are the schema's job and
    are enforced at the WIDGET (``catalog_param_specs``, ED-30) plus by
    ``write_validated`` at Save; nothing is clamped here.

    Raises ``KeyError`` for an unknown upgrade id or an unknown field/param —
    ``params`` is ``additionalProperties: false`` per upgrade, so inventing a
    key would only fail later, at the write."""
    entry = catalog(doc)[upgrade_id]
    if field in ("name", "description"):
        entry[field] = str(value)
        return
    params = entry["params"]
    if field not in params:
        raise KeyError(
            f"{upgrade_id!r} has no param {field!r} "
            f"(it takes {sorted(params) or 'no params'})")
    params[field] = _coerce_like(params[field], value)


def _coerce_like(current, value):
    """``value`` cast to ``current``'s JSON type. ``bool`` is checked before
    ``int`` — it is a subclass of it, and rewriting a flag as 0/1 would be a
    schema violation."""
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        return int(round(float(value)))
    if isinstance(current, float):
        return float(value)
    if isinstance(current, str):
        return str(value)
    return value


# -- read-only views the panel renders from ---------------------------------

def placements(doc):
    """``{upgrade_id: (milestone_idx, slot_idx)}`` for every id currently
    placed anywhere — what the browse list marks "already placed" from.

    An id placed twice (legal at assign time, see ``assign_slot``) maps to
    its LAST placement in reading order; ``validate_uniqueness`` is what
    reports that it happened at all."""
    out = {}
    for milestone_idx, milestone in enumerate(milestones(doc)):
        for slot_idx, upgrade_id in enumerate(milestone["slots"]):
            if upgrade_id is not None:
                out[upgrade_id] = (milestone_idx, slot_idx)
    return out


def validate_uniqueness(doc):
    """Upgrade ids placed in MORE than one slot across the whole timeline
    (D3), sorted — a LIST, never a raise. The panel surfaces these in a
    warning label; ``save_boss_upgrades`` deliberately ignores them (see the
    module docstring). Never mutates ``doc``."""
    seen = set()
    duplicates = set()
    for milestone in milestones(doc):
        for upgrade_id in milestone["slots"]:
            if upgrade_id is None:
                continue
            if upgrade_id in seen:
                duplicates.add(upgrade_id)
            seen.add(upgrade_id)
    return sorted(duplicates)


def catalog_param_specs(data_dir=None):
    """``{upgrade_id: {param_name: {type, minimum, maximum, description}}}``
    read straight off ``boss_upgrades.schema.json`` — the panel's spinbox
    ranges and int-vs-float choice come from here and are never retyped
    (ED-30: invalid input unrepresentable). Params are returned in the
    schema's own key order.

    Reads the SCHEMA, not the doc, so an upgrade whose params object is empty
    (``restock_lives``) is still listed, with no params. Missing bounds
    degrade to ``None`` rather than a guessed default — the panel decides
    what to do with an unbounded param."""
    schema = data_io.load_json(boss_upgrades_schema_path(data_dir))
    entries = (schema["properties"]["BossUpgrades"]["properties"]
               ["Catalog"]["properties"])
    specs = {}
    for upgrade_id, entry in entries.items():
        params = entry["properties"]["params"].get("properties", {})
        specs[upgrade_id] = {
            name: {
                "type": node.get("type", "number"),
                "minimum": node.get("minimum"),
                "maximum": node.get("maximum"),
                "description": node.get("description", ""),
            }
            for name, node in params.items()
        }
    return specs


def retaliation_bounds(data_dir=None):
    """``(minimum, maximum)`` for ``retaliation_bonus_love``, off the schema
    — the same ED-30 rule as ``catalog_param_specs`` (the bounds have exactly
    one home, and it is not this file)."""
    schema = data_io.load_json(boss_upgrades_schema_path(data_dir))
    node = schema["$defs"]["milestone"]["properties"]["retaliation_bonus_love"]
    return node.get("minimum", 0), node.get("maximum", 10000)


# -- save: the ONE write path (ED-31) ---------------------------------------

def save_boss_upgrades(doc, data_dir=None):
    """The ONE ``write_validated`` call site for ``boss_upgrades.json``.
    Raises before touching disk on a schema violation. Does NOT consult
    ``validate_uniqueness`` — see the module docstring."""
    data_io.write_validated(
        doc, boss_upgrades_path(data_dir), boss_upgrades_schema_path(data_dir))
