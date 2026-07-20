"""game.anchors — the shared manifest-anchor resolver (ESV-1, §3.3).

Pure module (no pygame): converts a manifest-authored anchor point (D2:
frame-px relative to the sprite anchor, +x right / -y up, measured on the
sheet frame at frame resolution) into a screen offset or a world offset, for
any caller holding an ``AssetStore`` + ``CoordinateSystem`` + an object
carrying a ``SpriteAnimator``.

Two entry points, both degrading to ``(0.0, 0.0)`` when the store, the
animator, the slot, or the named anchor is absent — so a manifest with no
``anchors`` key leaves every caller numerically unchanged:

- ``screen_offset`` — the fit-scaled screen-pixel delta (§1.3 up to the
  screen delta). Used by ``game/ui/effects.py`` for HUD elements (HP bars)
  that are already working in screen space.
- ``world_offset`` — the same delta run back through ``cs.screen_to_world``
  twice (never hand-derived: D2 promises zoom/pan cancel in that
  difference). Used by ``game/enemies/combat.py`` to spawn a projectile at a
  muzzle handle in world (fractional-tile) coords.

``game/ui`` and ``game/enemies`` both import this module rather than each
other — see the ESV-1 brief §3.3 "still forbidden" list.
"""
from engine.core import SpriteAnimator
from engine.render.renderer import fit_factor


def _scale_factor(assets, cs, anim):
    """The same downscale-only footprint fit `_sprite_top` uses (ER-1)."""
    frame_w, _frame_h = assets.frame_size(anim.slot_key)
    return fit_factor(frame_w, cs.geometry.tile_w, anim.fit_tiles) * anim.scale


def screen_offset(assets, cs, obj, name, zoom):
    """(dsx, dsy) screen-pixel offset the anchor `name` draws at for `obj`'s
    sprite at `zoom`. (0.0, 0.0) when `assets`/`cs`/the object's
    `SpriteAnimator`/its slot/the named anchor is missing."""
    if assets is None or cs is None or obj is None:
        return (0.0, 0.0)
    anim = obj.get_component(SpriteAnimator)
    if anim is None or not anim.slot_key:
        return (0.0, 0.0)
    anchor = assets.anchor(anim.slot_key, name)
    if anchor is None:
        return (0.0, 0.0)
    ax, ay = anchor
    if ax == 0 and ay == 0:
        return (0.0, 0.0)
    s = _scale_factor(assets, cs, anim)
    return (ax * s * zoom, ay * s * zoom)


def world_offset(assets, cs, obj, name):
    """(dwx, dwy) world-space (fractional-tile) delta the anchor `name`
    resolves to for `obj`'s sprite — the screen offset above, taken back
    through the coordinate authority as the difference of two
    `cs.screen_to_world` samples (D2: zoom and pan cancel in that
    difference, never restate the iso math). (0.0, 0.0) when `cs` is missing
    or the screen offset itself is zero (no anchor authored, or an anchor
    authored at [0, 0])."""
    if cs is None or obj is None:
        return (0.0, 0.0)
    zoom = cs.camera.zoom
    dsx, dsy = screen_offset(assets, cs, obj, name, zoom)
    if dsx == 0.0 and dsy == 0.0:
        return (0.0, 0.0)
    wx, wy = obj.transform.world_pos
    sx, sy = cs.world_to_screen(wx, wy)
    wx2, wy2 = cs.screen_to_world(sx + dsx, sy + dsy)
    return (wx2 - wx, wy2 - wy)
