"""game.anchors — the shared manifest-anchor resolver (fix-anchor-origin-
parity, superseding ESV-1/ESV-6's delta model).

Pure module (no pygame): resolves a manifest-authored anchor point (D2:
frame-px relative to the sprite anchor, +x right / -y up, measured on the
sheet frame at frame resolution) to the ABSOLUTE WORLD POINT it sits at on
the sprite AS DRAWN — through `engine.render.renderer.sprite_anchor_screen`,
the SAME geometry `Renderer.flush` uses to place the sprite, so this and the
renderer can never drift apart.

**Why this replaced the old `screen_offset`/`world_offset` delta model**:
that pair computed a scaled delta from the anchor to the sprite's drawn
CENTRE (correct in isolation), but every caller then added it to a base
point that was NOT the drawn centre — `cs.world_to_screen(obj.transform.
world_pos)` is the entity's ANCHOR TILE corner, `tile_h/2*zoom` (16px at
zoom 1) and a whole `block_center_offset` shift short of the centre `flush`
actually draws on. That is the measured root cause of "VFX/HP bars don't
spawn where the handle was dragged" (docs/briefs/fix-anchor-origin-
parity.md) — fixed here by resolving straight to the correct absolute
point instead of a delta a caller could mis-anchor.

One entry point, degrading to `None` when the store, the animator, the
slot, or the named anchor is absent — the caller's cue to fall back to its
own pre-anchor expression (E-37; "anchor wins outright" otherwise — no
anchor authored means unchanged behaviour, an anchor authored means the
exact handle point, never a nudge on top of a different base).

``game/ui`` and ``game/enemies`` both import this module rather than each
other — see the ESV-1 brief §3.3 "still forbidden" list.
"""
from engine.core import SpriteAnimator
from engine.render.renderer import sprite_anchor_screen


def anchor_world_point(assets, cs, obj, name):
    """World point of `obj`'s `name` anchor ON THE DRAWN SPRITE, or `None`
    when the store/cs/object/animator/slot/anchor is absent. `None` is the
    caller's cue to use its own pre-anchor fallback point (E-37)."""
    if assets is None or cs is None or obj is None:
        return None
    anim = obj.get_component(SpriteAnimator)
    if anim is None or not anim.slot_key:
        return None
    anchor = assets.anchor(anim.slot_key, name)
    if anchor is None:
        return None
    frame_w, _frame_h = assets.frame_size(anim.slot_key)
    offset_xy = assets.offset(anim.slot_key)
    wx, wy = obj.transform.world_pos
    sx, sy = sprite_anchor_screen(
        cs, wx, wy, frame_w, anim.fit_tiles, anim.scale, offset_xy, anchor)
    return cs.screen_to_world(sx, sy)
