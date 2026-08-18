"""BaseBuilding — "the Hole" the enemies attack (Phase 9D).

Untiered and fixed at ``BASE_HP`` (``core.json`` ``TheHole.base_hp``) — the
deliberate NOT-×10 exception, stays 10. It is the pre-seeded occupant of the
base tile (``TileMap`` already marks that tile BUILT + ``base_building``); its
visual comes from the static map render (``doc.base`` slot), so it carries NO
SpriteAnimator — attaching one would double-draw the base sprite. Never revives
(the prototype excludes ``building_type == 'base'`` from the round-end sweep).
"""
from engine.core import GameObject, Health, Transform
from .building import Building
from .components import Nameplate, RoundStats, TierState


class BaseBuilding(Building):
    BUILDING_TYPE = "base"
    CONTENT_KEY = "base_building"

    def __init__(self, col, row, core_balance):
        base_hp = core_balance["TheHole"]["base_hp"]
        components = [
            TierState(building_type=self.BUILDING_TYPE),
            Nameplate(),
            RoundStats(),
            Health(max_hp=base_hp, hp=base_hp),
        ]
        # Bypass Building.__init__ (which resolves a per-tier table the base
        # lacks) and construct the GameObject directly.
        GameObject.__init__(
            self,
            name="base",
            tags=("building", "base"),
            transform=Transform(wx=float(col), wy=float(row)),
            components=components,
        )
        self._balance = core_balance
        self._tiers = ()
        self._col = col
        self._row = row

    # -- untiered overrides ------------------------------------------------

    def max_hp(self):
        return self.get_component(Health).max_hp

    def upgrade_cost(self, run_state=None, boss_upgrades_balance=None):
        # The pair is accepted (and ignored) purely so this override keeps the
        # base signature — the hole is untiered and never priced. BU-3's
        # wall_cost_discount is structure-scoped and could not apply anyway.
        return 0

    def tier_data(self):
        return None

    def at_tier_max(self):
        return True

    def has_next_tier(self):
        return False

    @property
    def level(self):
        return self.get_component(TierState).current_level_in_tier

    def slot_key(self):
        return "base_hole"

    def apply_tier_stats(self):
        """Untiered: HP is fixed at construction; nothing to recompute."""

    def rebuild(self):
        """The base never revives (prototype excludes ``building_type=='base'``
        from the round-end rebuild sweep)."""
