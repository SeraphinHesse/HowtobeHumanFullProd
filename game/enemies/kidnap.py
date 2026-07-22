"""Kidnapping — a kidnap-capable enemy's killing blow on a building carries it
home instead of the enemy walking on (Art/enemies).

``begin_kidnap`` is the ONE transition site, called from the combat sweep's
kidnap pass (``combat.py``) the frame ``EnemyCombat`` reports a pending
kidnap (``Kidnap.pending``, armed in ``components.py``). It reuses the
``Corpse`` retag precedent wholesale (``game/enemies/CLAUDE.md``): flipping
the owner's tags ``("enemy", ...) -> ("kidnapper",)`` makes it invisible to
EVERY gameplay query that reads ``by_tag("enemy")`` in one move — the combat
sweep's own target list, the beam's sticky target, the base-arrival sweep,
lightning, the overhead HP bars and the heatmap tracker — with no per-site
"if kidnapping" filter anywhere. A damaged kidnapper therefore shows no HP bar
at all (its ``Health`` is never touched, so this never actually fires).
"""
from engine.core import Movement, SpriteAnimator
from game.map.pathfinder import find_path_to_nearest_spawn

from .components import CARRY_OFFSET_TILES, Kidnap, PathAgent

KIDNAP_ANIM = "kidnap"  # the manifest row name a kidnap-pose sheet carries


def set_kidnap_pose(enemy, has_kidnap_row):
    """Pick the carrying pose. ``True``: play the sheet's own ``kidnap`` row.
    ``False``: freeze on the idle frame — ``anim.set_animation("idle")``
    resets the clock, but ``SpriteAnimator.update`` advances it every frame
    regardless, so ``Kidnap.frozen`` is what actually re-pins it to 0 each
    frame (``Kidnap.update``)."""
    anim = enemy.get_component(SpriteAnimator)
    kidnap = enemy.get_component(Kidnap)
    if anim is None or kidnap is None:
        return
    if has_kidnap_row:
        anim.set_animation(KIDNAP_ANIM)
        kidnap.frozen = False
    else:
        anim.set_animation("idle")
        anim.anim_time_ms = 0.0
        kidnap.frozen = True


def begin_kidnap(scene, tilemap, enemy, building):
    """The ONE transition site. The building's own ``SpriteAnimator`` fields
    are copied onto ``Kidnap`` so the carrier can draw them; the building
    itself is NOT touched — it stays on its tile as a plain dead building and
    revives at payday like any other kill (``Session.on_kidnap``). Its sprite
    vanishes on its own: it is dead by definition here (``Kidnap.pending`` is
    armed by the killing blow) and ``BuildingSprite`` yields no RenderItem
    while its owner is dead. Blanking ``slot_key`` here would survive the
    revive and leave the rebuilt building invisible forever."""
    kidnap = enemy.get_component(Kidnap)
    pa = enemy.get_component(PathAgent)
    mv = enemy.get_component(Movement)

    b_anim = building.get_component(SpriteAnimator)
    if b_anim is not None:
        kidnap.slot_key = b_anim.slot_key
        kidnap.fit_tiles = b_anim.fit_tiles
        kidnap.scale = b_anim.scale
    kidnap.active = True
    kidnap.pending = False
    kidnap._scene = scene

    pa.blocked = False
    pa.carrying = True
    pa._target = None
    pa._wall_target = None
    # Load-bearing: a stale goal_is_base=True would fire a phantom base
    # breach the moment the carrier reaches the spawn tile.
    pa.goal_is_base = False
    pa.repath_on_kill = False
    pa.target_col = pa.target_row = -1

    mv.speed = pa._real_speed  # the enemy was blocked/attacking -> 0.0
    col = round(enemy.transform.wx)
    row = round(enemy.transform.wy)
    path = find_path_to_nearest_spawn(tilemap, col, row, footprint=pa.footprint)
    if not path:
        scene.despawn(enemy)  # no spawn tile / unreachable -> despawn on the spot
        return
    mv.waypoints = [[float(c), float(r)] for c, r in path]
    mv.index = 1 if len(path) >= 2 else 0  # BP-4 no-rewind rule
    mv.arrived = False

    set_kidnap_pose(enemy, has_kidnap_row=False)  # default pose; the host
    # (main.py) upgrades it to the real "kidnap" row if the sheet has one.
    enemy.tags = ("kidnapper",)
