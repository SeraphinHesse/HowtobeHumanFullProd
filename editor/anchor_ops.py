"""editor.anchor_ops (ESV-2 §2.1/§2.3/§2.4) — pure frame-px <-> screen-delta
conversions plus the manifest `anchors` write path. Modelled on
editor/registry_ops.py: stdlib + engine.data_io + editor.asset_import only,
no Qt, no pygame, no game/ import — in TestPurity.

The iso projection itself never appears here. `screen_point`/`frame_px`
operate on an already-resolved SCREEN origin (the caller runs
engine.coords.world_to_screen once to get it, ESV-2 brief §2.3a) and the
caller's own drawn scale `s` (fit_factor * scale) — the algebra below is a
plain multiply/divide, unique to how an anchor maps onto that origin, and
`engine/coords/` stays the sole authority for the iso math it is built on.
"""
from editor import asset_import

_BOUND = 4096   # asset_manifest.schema.json anchors[*] items minimum/maximum


def screen_point(origin, ax, ay, s, zoom):
    """The SCREEN point a frame-px anchor (ax, ay) draws at, given the
    handle `origin` (ESV-2 brief §1.4 — the un-offset frame anchor's own
    screen point) and the caller's resolved draw scale `s`/`zoom`."""
    ox, oy = origin
    return (ox + ax * s * zoom, oy + ay * s * zoom)


def frame_px(origin, sx, sy, s, zoom):
    """Inverse of `screen_point`: the (rounded) frame-px anchor a SCREEN
    point (sx, sy) authors, relative to `origin`. Subtract-and-divide only
    (§2.3b) — screen space is already the space `world_to_screen` produces,
    so there is no iso math to restate here."""
    ox, oy = origin
    ax = round((sx - ox) / (s * zoom))
    ay = round((sy - oy) / (s * zoom))
    return (ax, ay)


def _clamp(value):
    return max(-_BOUND, min(_BOUND, int(round(value))))


def set_anchor(data_dir, slot_key, name, xy):
    """Author one anchor at `xy` (rounded, clamped to the schema bounds) on
    `slot_key`'s manifest entry. Returns True on write; False (no write,
    never raises) when the slot has no manifest entry to attach to — the
    ESV-2 brief §1.6 case-2 "grey-X placeholder" state."""
    doc = asset_import.load_manifest_doc(data_dir)
    entry = doc["entries"].get(slot_key)
    if entry is None:
        return False
    anchors = dict(entry.get("anchors") or {})
    anchors[name] = [_clamp(xy[0]), _clamp(xy[1])]
    entry["anchors"] = anchors
    asset_import.write_manifest_doc(data_dir, doc)
    return True


def clear_anchor(data_dir, slot_key, name):
    """Drop one anchor; drops the whole `anchors` key when it was the last
    one, so the entry returns byte-identical to its pre-anchors form (§1.6).
    Returns True once the slot's entry is confirmed to carry no `name`
    anchor (whether or not it did before — clearing an absent name is a
    no-op, not an error); False (no write) when there is no entry at all."""
    doc = asset_import.load_manifest_doc(data_dir)
    entry = doc["entries"].get(slot_key)
    if entry is None:
        return False
    anchors = dict(entry.get("anchors") or {})
    if name not in anchors:
        return True
    del anchors[name]
    if anchors:
        entry["anchors"] = anchors
    else:
        entry.pop("anchors", None)
    asset_import.write_manifest_doc(data_dir, doc)
    return True
