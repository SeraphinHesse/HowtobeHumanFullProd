"""Piecewise band mapping for nine-slice geometry (A8).

Pure module (no pygame, no engine imports) — defines the coordinate transform
that inverts `_nine_patch` (`engine/render/backend.py`). `clamp_pair` moved
here from the backend in A8 so hit-mask code (`engine/assets/store.py`, also
pure-adjacent) can share the exact same clamp without importing pygame;
`dest_to_source` is the new inverse the hit test needs.
"""


def clamp_pair(a, b, limit):
    """Opposite margins clamped PROPORTIONALLY into `limit`. On overflow
    `a + b == limit` exactly (the centre band vanishes, the corners squeeze).
    THE clamp `_nine_patch` uses (imported, not reimplemented) — this module
    and `engine/render/backend.py` can never drift out of sync on it."""
    a = max(0, a)
    b = max(0, b)
    total = a + b
    if total <= limit:
        return a, b
    if total <= 0:
        return 0, 0
    a2 = a * limit // total
    return a2, limit - a2


def dest_to_source(rel_xy, dest_size, src_size, margins):
    """Map destination screen coords back to source frame coords, inverting
    the nine-patch band layout.

    Args:
        rel_xy: (x, y) in destination space, 0-indexed.
        dest_size: (dw, dh) final blit size in pixels.
        src_size: (sw, sh) source frame size in pixels.
        margins: (left, top, right, bottom) in source frame pixels, or None
            (treated as all-zero, plain scale).

    Returns:
        (sx, sy) -- source frame coords, integers. Never raises: out-of-bounds
        rel_xy will resolve to an edge pixel (the caller must clamp first if
        they want to validate the hit). All inputs are safe: negative margins
        floor to 0; margins larger than source are clamped by the piecewise
        logic.

    Corners map 1:1 (never resampled). Edges stretch on one axis, the centre
    on both. This is the exact inverse of `_nine_patch` in
    engine/render/backend.py.

    Degenerate centre band: if a margin pair clamps to exactly fill the
    SOURCE dimension (`sl + sr == sw`, resp. `st + sb == sh`) while the DEST
    still has a centre band on that axis (`dw > sw`, resp. `dh > sh`),
    `_nine_patch` skips painting that band entirely (its source width/height
    is 0, so the `min(...) <= 0` guard drops it) -- the dest centre band is
    on-screen transparency, not a scaled copy of the source's boundary
    pixel. This function returns an out-of-frame coordinate (`sw`/`sh`) for
    that axis so a bounds-checking caller (`AssetStore.hit_opaque`) reads it
    as a miss, matching what is actually drawn."""
    rel_x, rel_y = rel_xy
    dw, dh = dest_size
    sw, sh = src_size

    if margins is None or all(m == 0 for m in margins):
        # Plain scale -- all bands are the centre band.
        return (rel_x * sw // max(1, dw), rel_y * sh // max(1, dh))

    # Clamp margins to source, then to destination (same as _nine_patch).
    sl, sr = clamp_pair(margins[0], margins[2], sw)
    st, sb = clamp_pair(margins[1], margins[3], sh)
    dl, dr = clamp_pair(sl, sr, dw)
    dt, db = clamp_pair(st, sb, dh)

    # Piecewise column mapping.
    if rel_x < dl:
        # Left corner: map 1:1.
        sx = rel_x
    elif rel_x >= dw - dr:
        # Right corner: map from the trailing edge.
        sx = sw - (dw - rel_x)
    else:
        # Centre column: scale by the band width ratio. Reaching this branch
        # means dl <= rel_x < dw - dr, which implies mid_d (below) > 0 --
        # but mid_s (the SOURCE centre band) can still be 0 if the margins
        # clamped to exactly fill sw. _nine_patch paints nothing there, so
        # signal a miss (sx == sw, out of [0, sw)) instead of resolving to
        # the boundary pixel sl, which IS a painted corner pixel and would
        # falsely read as opaque.
        mid_s = sw - sl - sr
        mid_d = dw - dl - dr
        if mid_s <= 0:
            sx = sw
        else:
            sx = sl + (rel_x - dl) * mid_s // max(1, mid_d)

    # Piecewise row mapping (same pattern).
    if rel_y < dt:
        # Top corner: map 1:1.
        sy = rel_y
    elif rel_y >= dh - db:
        # Bottom corner: map from the trailing edge.
        sy = sh - (dh - rel_y)
    else:
        # Centre row: scale by the band height ratio (same degenerate-band
        # miss signal as the column mapping above).
        mid_s = sh - st - sb
        mid_d = dh - dt - db
        if mid_s <= 0:
            sy = sh
        else:
            sy = st + (rel_y - dt) * mid_s // max(1, mid_d)

    return (sx, sy)
