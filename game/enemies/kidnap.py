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
at all.

**The ONE exception is a lethal shot already in flight** when the retag
happened (``ProjectileHoming._impact``): that shot still kills, and this
module owns what "killed carrier" means — ``release_kidnap`` clears the carry
and launches a ``KidnapReturnFlight``, the object that flies the stolen
sprite back to its tile and revives the building there at 1 HP. Nothing else
can damage a carrier, so a NON-lethal in-flight shot is still skipped and
``Health`` is still never partially chipped: a carrier is either untouched or
dead outright.
"""
from engine.core import (
    Component, GameObject, Health, Movement, SpriteAnimator, Transform,
)
from game.map.pathfinder import find_path_to_nearest_spawn

from .components import CARRY_OFFSET_TILES, Kidnap, PathAgent

KIDNAP_ANIM = "kidnap"  # the manifest row name a kidnap-pose sheet carries
# SIMULATION TIMING, not a cosmetic (the AOE_TRAVEL_TIME rule, combat.py):
# the rescued building is dead-and-invisible for exactly this long and comes
# back alive when the flight lands, so the number gates gameplay state, not
# just pixels. Never move it into data/balancing/vfx.json.
RESCUE_FLIGHT_SECONDS = 0.35
RESCUE_TAG = "kidnap_return"  # never "enemy"/"kidnapper" — see Corpse's docstring


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
        # MasterSheetColumnsPLAN B1: the player's swatch pick lives on the
        # building's own animator (`SpriteAnimator.column`, -1 = "no driver")
        # and must ride along too, or the carried sprite silently falls back
        # to the manifest's default colour instead of the one the player chose.
        kidnap.column = b_anim.column
    kidnap.active = True
    kidnap.pending = False
    kidnap._scene = scene
    # The victim itself, as a transient env ref beside `_scene` (E-11 — the
    # JSON-safe COPY of its sprite fields is what the declared fields above
    # hold). Read only by `release_kidnap`, which has to hand the actual
    # building back when the carrier is shot down mid-walk.
    kidnap._victim = building

    pa.blocked = False
    # NE-1: `in_range` is the ranged twin of `blocked` and EnemyCombat reads
    # `blocked or in_range`, so it has to be cleared here too — otherwise a
    # kidnap-capable stand-off type would keep firing all the way home. No
    # shipped type is both today (Sniper is `kidnapping: false`); this is the
    # flag pair staying honest, not a live bug fix.
    pa.in_range = False
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
    path = find_path_to_nearest_spawn(tilemap, col, row, footprint=pa.footprint,
                                      cond_weights=pa._cond_weights)
    if not path:
        scene.despawn(enemy)  # no spawn tile / unreachable -> despawn on the spot
        return
    mv.waypoints = [[float(c), float(r)] for c, r in path]
    mv.index = 1 if len(path) >= 2 else 0  # BP-4 no-rewind rule
    mv.arrived = False

    set_kidnap_pose(enemy, has_kidnap_row=False)  # default pose; the host
    # (main.py) upgrades it to the real "kidnap" row if the sheet has one.
    enemy.tags = ("kidnapper",)


class KidnapReturnFlight(Component):
    """Flies the owner from the dead carrier's spot back to the rescued
    building's tile over ``life`` seconds, then revives the building at 1 HP
    and despawns the owner.

    A straight lerp on the transform, so the generic ``SpriteAnimator`` beside
    it draws the stolen sprite the whole way — no new render path. The clock
    is the speed-scaled sim ``dt`` (the ``Corpse`` fade-clock rule), so the
    flight holds at 1x/1.5x/2x/pause.

    ``_scene``/``_owner``/``_building`` are transient environment refs (E-11
    underscore), wired by ``release_kidnap``.
    """

    from_wx: float = 0.0
    from_wy: float = 0.0
    to_wx: float = 0.0
    to_wy: float = 0.0
    life: float = RESCUE_FLIGHT_SECONDS
    age: float = 0.0

    def on_added(self, owner):
        self._owner = owner
        self._scene = None
        self._building = None

    def update(self, dt):
        self.age += dt
        t = 1.0 if self.life <= 0 else min(1.0, self.age / self.life)
        tf = self._owner.transform
        tf.wx = self.from_wx + (self.to_wx - self.from_wx) * t
        tf.wy = self.from_wy + (self.to_wy - self.from_wy) * t
        if t < 1.0:
            return
        revive_rescued_building(self._building)
        scene = getattr(self, "_scene", None)
        if scene is not None:
            scene.despawn(self._owner)


def revive_rescued_building(building):
    """Bring a rescued building back at **1 HP, with no respawn anim or VFX**
    (user decision) — deliberately NOT ``Building.rebuild``: that full-heals
    and advances the rebirth generation ("<base> the 2nd"), which is payday's
    story for a building that stayed dead. A rescue is the same building,
    scratched. Payday's slot-9 sweep then full-heals it like any other living
    building and appends no ``building_respawn_events`` row, so no respawn VFX
    plays for it either.

    No-op when the building is already alive — payday can legitimately have
    revived it while the flight was still in the air (the carrier's death can
    clear the field, and this object holds nothing open)."""
    if building is None:
        return
    health = building.get_component(Health)
    if health is None or not health.is_dead:
        return
    health.hp = 1


def release_kidnap(scene, enemy):
    """The carrier died mid-walk: end the carry and launch the stolen sprite
    home. Returns the rescued building (``None`` when there is nothing to give
    back — e.g. a carrier with no recorded victim, or a test stub).

    Clearing ``Kidnap.active`` is what stops the carrier drawing the carried
    sprite (``Kidnap.render_items``); the ``KidnapReturn`` spawned here picks
    that exact pixel up and flies it to the building's own tile, where
    ``revive_rescued_building`` brings it back."""
    kidnap = enemy.get_component(Kidnap)
    if kidnap is None or not kidnap.active:
        return None
    building = getattr(kidnap, "_victim", None)
    kidnap.active = False
    if building is None or not kidnap.slot_key:
        return building
    wx, wy = enemy.transform.world_pos
    # The carry offset — start the flight where the sprite was actually drawn.
    from_wx, from_wy = wx - CARRY_OFFSET_TILES, wy + CARRY_OFFSET_TILES
    to_wx, to_wy = building.transform.world_pos
    flight = KidnapReturnFlight(
        from_wx=from_wx, from_wy=from_wy, to_wx=to_wx, to_wy=to_wy,
    )
    obj = GameObject(
        name="kidnap_return",
        tags=(RESCUE_TAG,),
        transform=Transform(wx=from_wx, wy=from_wy,
                            layer=enemy.transform.layer),
        components=[
            SpriteAnimator(slot_key=kidnap.slot_key, animation="idle",
                           fit_tiles=kidnap.fit_tiles, scale=kidnap.scale,
                           column=kidnap.column),
            flight,
        ],
    )
    flight._scene = scene
    flight._building = building
    scene.spawn(obj)
    return building
