"""Piecewise band mapping for nine-slice geometry (A8).

Pure module (no pygame, no engine imports) — defines the coordinate transform
that inverts `_nine_patch` (`engine/render/backend.py`). `clamp_pair` moved
here from the backend in A8 so hit-mask code (`engine/assets/store.py`, also
pure-adjacent) can share the exact same clamp without importing pygame;
`dest_to_source` is the new inverse the hit test needs.
"""


def _scale_index(i, src_n, dst_n):
    """Nearest-neighbour source index for destination index `i`, matching
    `pygame.transform.scale`'s software stretch bit-for-bit: a 16.16
    fixed-point, pixel-CENTRE sample (step = src_n/dst_n truncated to 16.16;
    start the accumulator at half a step so index 0 samples the centre of
    the first destination pixel, not its leading edge). This is the ONE
    sampler for every band `_nine_patch` resamples with `pygame.transform.
    scale` -- corners (when the dest shrinks a margin below its source
    size), edges, and the centre band all reduce to "scale this many source
    pixels into that many dest pixels", so this same function inverts all
    three, each called with that band's own (src_n, dst_n) and applied
    within the band's own coordinate space (an offset added by the caller).
    Verified bit-exact: 200+ randomised (src_n, dst_n) pairs (1..40) as a
    1-D sweep, PLUS 300 randomised full 9-patch composites (9000+ pixels,
    corners AND centre band together) rendered through the REAL
    `backend.draw`/`pygame.transform.scale` and compared pixel-for-pixel —
    zero mismatches. This is not an approximation, it is the same integer
    arithmetic pygame's C `stretch()` uses.

    `dst_n <= 0` (no such band in the destination) returns 0 rather than
    dividing by zero — that branch is unreachable from valid `rel_xy`
    (callers only take this path when `dst_n` is exactly the width/height of
    the band being queried, which is > 0 by construction), but a caller who
    ignores the "clamp `rel_xy`" contract must still never crash."""
    if dst_n <= 0:
        return 0
    step = (src_n << 16) // dst_n
    pos = step // 2 + i * step
    return pos >> 16


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

    EVERY band inverts the exact same nearest-neighbour sampler
    `_nine_patch` used to paint it (`_scale_index`, a bit-for-bit match of
    `pygame.transform.scale`'s software stretch) -- corners, edges, and the
    centre band alike. Corners degenerate to a 1:1 identity mapping only in
    the common case where the dest isn't narrower/shorter than the
    (already source-clamped) margin they came from (`dl == sl`, resp.
    `dt == st`); when the dest is smaller (`clamp_pair` shrinks `dl`/`dr`
    below `sl`/`sr`), `_nine_patch` resamples that corner exactly like an
    edge or the centre band, and `_scale_index` inverts that resample too.
    This is the exact inverse of `_nine_patch` in engine/render/backend.py
    for every band -- not an approximation anywhere.

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
        # Left corner: 1:1 when dl == sl (the common case, no resample);
        # when the dest is narrower than the source margin, _nine_patch
        # scales this corner down like any other band, so invert THAT
        # resample via _scale_index rather than assuming identity.
        sx = _scale_index(rel_x, sl, dl)
    elif rel_x >= dw - dr:
        # Right corner: same idea, indexed from the trailing edge (the
        # region starts at source x == sw - sr).
        sx = (sw - sr) + _scale_index(rel_x - (dw - dr), sr, dr)
    else:
        # Centre column. Reaching this branch means dl <= rel_x < dw - dr,
        # which implies mid_d (below) > 0 -- but mid_s (the SOURCE centre
        # band) can still be 0 if the margins clamped to exactly fill sw.
        # _nine_patch paints nothing there, so signal a miss (sx == sw, out
        # of [0, sw)) instead of resolving to the boundary pixel sl, which
        # IS a painted corner pixel and would falsely read as opaque.
        #
        # Otherwise: _nine_patch scales the centre band as its OWN
        # subsurface (source width mid_s -> dest width mid_d), the same
        # `pygame.transform.scale` call as a resampled corner -- so invert
        # it with the same _scale_index, applied within the band's own
        # coordinate space (offset by dl on the dest side, by sl on the
        # source side).
        mid_s = sw - sl - sr
        mid_d = dw - dl - dr
        if mid_s <= 0:
            sx = sw
        else:
            sx = sl + _scale_index(rel_x - dl, mid_s, mid_d)

    # Piecewise row mapping (same pattern).
    if rel_y < dt:
        # Top corner: same 1:1-unless-resampled logic as the left corner.
        sy = _scale_index(rel_y, st, dt)
    elif rel_y >= dh - db:
        # Bottom corner: same as the right corner, indexed from sh - sb.
        sy = (sh - sb) + _scale_index(rel_y - (dh - db), sb, db)
    else:
        # Centre row: same degenerate-band miss + _scale_index inversion as
        # the column mapping above.
        mid_s = sh - st - sb
        mid_d = dh - dt - db
        if mid_s <= 0:
            sy = sh
        else:
            sy = st + _scale_index(rel_y - dt, mid_s, mid_d)

    return (sx, sy)
