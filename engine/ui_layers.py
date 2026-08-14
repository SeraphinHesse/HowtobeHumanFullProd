"""Pure resolver for a widget's OVERRIDE-doc "layers" (UiLayeredWidgetsPLAN UL-3).

Layers live only in ``data/ui/screens/<id>.json`` (D1) — never in
``screen_defaults.json`` — and each layer's geometry is an OFFSET
``[dx, dy, w, h]`` from the owning widget's already-resolved rect, never an
absolute rect (D2); this module is the single place that offset math happens.
It is pygame-free (D3), like ``engine.coords``/``engine.data_io``/
``engine.tilemap``, so both ``game/`` and ``editor/`` can resolve a layer to
the same rect without importing pygame or each other. **Nothing calls this
module yet** (D5) — UL-4 is what wires a real caller; this phase ships only
the schema key and this pure vocabulary.
"""

__all__ = ["resolve", "ordered", "validate_offsets"]

_APPEARANCE_KEYS = (
    "slot", "text_id", "label", "font", "align", "color", "text_color", "tint",
)


def _state_patch(layer_spec, state):
    """The per-state appearance patch for `state` (UL-5), or ``{}``.

    The D9 fallback rule, in one place: the resolved state key wins when it is
    PRESENT (an explicitly-authored empty patch means "this state looks like
    the base", not "fall through"); an ABSENT key falls back to ``"idle"``;
    an absent/empty ``"states"`` object falls back to no patch at all, i.e.
    the layer's own base appearance stands outright.
    """
    states = layer_spec.get("states") or {}
    if not isinstance(states, dict):
        return {}
    if state in states:
        return states[state] or {}
    return states.get("idle") or {}


def _patch_offset(value, base):
    """A state patch's ``offset``, resolved against the layer's own `base`.

    REPLACES the base offset rather than adding to it (UL-5 §2b), with the
    2-length ``[dx, dy]`` form keeping the base's w/h so it moves the layer
    without resizing it (UL-5 §2a's "size unchanged"). A malformed value
    degrades to `base` rather than raising -- ``validate_offsets``' rule,
    applied to the patch.
    """
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 4):
        return base
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return base
    if len(value) == 2:
        return (value[0], value[1], base[2], base[3])
    return tuple(value)


def resolve(layer_spec, owner_rect, state="idle"):
    """Compute one layer's absolute rect + resolved appearance.

    layer_spec: one entry from a widget's "layers" array (schema:
        data/schemas/ui_screen.schema.json). Every key is optional; absent
        keys degrade per-key rather than raising.
    owner_rect: (x, y, w, h) -- the owning widget's POST-OVERRIDE rect
        (already resolved by whatever placed the widget; this function does
        not know about screen_defaults.json or overrides, only the final
        rect it is handed).
    state: which of the four D9 states ("idle" | "hover" | "pressed" |
        "disabled") the OWNING widget is in. Selects one patch out of the
        entry's "states" sub-object (UL-5) via `_state_patch`'s fallback
        ladder; every key that patch sets overrides this entry's own value
        for THIS resolution only (never mutating `layer_spec`), and every
        key it omits leaves the base value untouched. An entry with no
        "states" key resolves byte-identically to pre-UL-5, whatever
        `state` is passed.

    Returns a dict:
        {
            "rect": (x, y, w, h),      # ints, owner_rect anchored + the
                                        # 0-inherits-owner's-w/h rule (D2)
            "slot": str | None,
            "text_id": str | None,
            "label": str | None,
            "font": str | None,
            "align": str | None,
            "color": tuple | None,
            "text_color": tuple | None,
            "tint": tuple | None,
            "visible": bool,           # default True when absent -- matches
                                        # the per-widget "visible" default
                                        # already implied by the existing
                                        # schema's boolean type with no
                                        # explicit default
        }
    """
    patch = _state_patch(layer_spec, state)

    validated = validate_offsets([layer_spec])[0]
    offset = validated.get("offset", (0, 0, 0, 0))
    dx, dy, w, h = offset
    if "offset" in patch:
        dx, dy, w, h = _patch_offset(patch["offset"], (dx, dy, w, h))

    ow, oh = owner_rect[2], owner_rect[3]
    out_w = ow if w == 0 else w
    out_h = oh if h == 0 else h
    out_x = owner_rect[0] + dx
    out_y = owner_rect[1] + dy
    rect = (out_x, out_y, out_w, out_h)

    out = {"rect": rect}
    for key in _APPEARANCE_KEYS:
        # Shallow merge, patch-wins-per-key: `{**base, **patch}` spelled out
        # key by key so the returned dict keeps its documented shape (a
        # patch's "offset" is geometry, above -- never an appearance key).
        value = patch[key] if key in patch else layer_spec.get(key, None)
        if key in ("color", "text_color", "tint") and value is not None:
            value = tuple(value)
        out[key] = value
    out["visible"] = (patch["visible"] if "visible" in patch
                      else layer_spec.get("visible", True))
    return out


def ordered(layers, band):
    """Filter + order a widget's layers for one paint band.

    layers: the widget's raw "layers" array (list of layer-spec dicts,
        schema: data/schemas/ui_screen.schema.json) -- NOT yet resolved;
        ordered() does not call resolve().
    band: "under" | "over" -- the caller (UL-4, not this phase) paints
        "under" layers before the owner widget and "over" layers after it.

    Selection: an entry matches `band` if entry.get("band", "over") == band.
        Missing "band" key defaults to "over" (an undecorated layer entry
        paints ON TOP of its owner, the visually safer default -- an
        accidentally-omitted band still shows, rather than silently hiding
        behind the owner).

    Ordering: stable sort by entry.get("z", 0) ascending (ties keep source
        order -- Python's sort is already stable).

    Degrade (dangling/duplicate id): if two or more entries in `layers`
        share the same non-empty "id" value, keep the FIRST occurrence (in
        the original `layers` list order, before filtering/sorting) and
        drop the rest, rather than raising. Entries with no "id" key, or an
        empty-string "id", are never deduped against each other or anything
        else (only a non-empty id collision triggers the drop). This
        mirrors editor/widget_tree.py's D5 precedent: a hand-edited doc
        must never hang a paint handler.

    Returns: a new list (does not mutate `layers`), containing only the
        band-matching, deduped entries, sorted by z.
    """
    seen_ids = set()
    deduped = []
    for entry in layers:
        entry_id = entry.get("id", "")
        if entry_id:
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
        deduped.append(entry)

    matched = [entry for entry in deduped if entry.get("band", "over") == band]
    return sorted(matched, key=lambda e: e.get("z", 0))


def validate_offsets(layers):
    """Pure structural check: every entry's "offset" (if present) must be a
    4-element sequence of ints.

    Returns a NEW list, same length and order as `layers`, where each entry
    is either the original dict unchanged (offset absent, or present and
    valid: a sequence of exactly 4 int-typed elements) or a shallow copy of
    the entry with "offset" replaced by (0, 0, 0, 0) (offset present but
    malformed: wrong length, non-sequence, or any element not an int --
    bool is NOT accepted as int here even though Python's bool is an int
    subclass, since a stray true/false in an offset slot is clearly a JSON
    authoring mistake, not a degraded-but-intentional value).

    Does not raise on any input shape, including layers entries that are
    not dicts at all -- a non-dict entry in `layers` is skipped (passed
    through unchanged) since there is nothing to fix on it.
    """
    out = []
    for entry in layers:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        if "offset" not in entry:
            out.append(entry)
            continue
        offset = entry["offset"]
        valid = (
            isinstance(offset, (list, tuple))
            and len(offset) == 4
            and all(isinstance(v, int) and not isinstance(v, bool) for v in offset)
        )
        if valid:
            out.append(entry)
        else:
            fixed = dict(entry)
            fixed["offset"] = (0, 0, 0, 0)
            out.append(fixed)
    return out
