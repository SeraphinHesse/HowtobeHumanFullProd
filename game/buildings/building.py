"""Building — base of the building hierarchy (Phase 9D).

``Building(GameObject)`` holds NO public instance state (engine E-11): every
authoritative value lives in a component (``TierState``, ``Nameplate``,
``RoundStats``, engine ``Health`` / ``SpriteAnimator``, plus family extras).
Balancing lives in ``data/balancing/buildings.json``; each leaf declares a
``SUBTREE`` path into that tree and the base resolves its per-tier table once.

Derived values (max_hp, upgrade_cost, level, …) are COMPUTED methods here from
``TierState`` + the tier table — never stored (prototype ``Building``). The
duck-typed contract the map layer reads (``alive`` / ``building_type`` /
``damage_dealt_last_round``) is exposed as class-level ``@property`` (guard-safe:
the E-11 setattr guard only catches new *instance* attributes).

Leaf classes stay tiny (subtree path, tags, per-tier slot prefixes, component
wiring); families (``EconomyBuilding`` / ``DefenceBuilding``) add their computed
stats and marker components.
"""
from functools import reduce

from engine.core import GameObject, Health, SpriteAnimator, Transform
from .components import BoostReceiver, Nameplate, RoundStats, TierState


def _ordinal(n):
    """1 -> '1st', 2 -> '2nd', 11 -> '11th' (prototype rebirth naming)."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class Building(GameObject):
    # -- class-level identity (families / leaves set these) ----------------
    BUILDING_TYPE = ""        # duck-typed pathfinder key + registry key
    CONTENT_KEY = None        # tile.content_key set at placement (map.json key)
    SUBTREE = ()              # path into the buildings-domain balancing tree
    TIER_SPRITES = ()         # per-tier slot-key prefixes
    EXTRA_TAGS = ()           # family capability tags (e.g. "combat", "economy")

    def __init__(self, col, row, buildings_balance, tier_idx=0):
        tiers = self._resolve_tiers(buildings_balance)
        components = [
            TierState(building_type=self.BUILDING_TYPE, current_tier=tier_idx),
            Nameplate(),
            RoundStats(),
            Health(max_hp=1, hp=1),
            SpriteAnimator(slot_key="", phase_ms=(col * 137 + row * 251) % 2000),
        ]
        components.extend(self._extra_components(tiers[tier_idx]))
        super().__init__(
            name=self.BUILDING_TYPE,
            tags=("building",) + tuple(self.EXTRA_TAGS),
            transform=Transform(wx=float(col), wy=float(row)),
            components=components,
        )
        # Transient caches (E-11 allows underscore attrs; non-authoritative).
        self._balance = buildings_balance
        self._tiers = tiers
        self._col = col
        self._row = row
        # -- 10I: tile-condition snapshot (set by registry.place_building) --
        # Neutral defaults so `create()` previews + headless tests see plain
        # stats: None == unplaced == GRASS-equivalent. (No module-level
        # game.map import here — game/buildings loads inside import chains
        # that also initialise game.map -> game.core -> game.buildings
        # .research, so the enum-key table is looked up lazily in
        # `_condition_mod`.) Conditions are immutable after the map roll, so
        # snapshot == live read (prototype `b.tile_condition`).
        self._tile_condition = None
        self._condition_mods = {}
        # -- /10I --
        self.apply_tier_stats()

    # -- balancing resolution ---------------------------------------------

    @classmethod
    def _resolve_tiers(cls, buildings_balance):
        """The per-tier table for this leaf, dug out of the buildings tree."""
        node = reduce(lambda d, k: d[k], cls.SUBTREE, buildings_balance)
        return node["tiers"]

    def _extra_components(self, tier0):
        """Family hook: components beyond the shared set (defence adds Attacker +
        RangeSensor, economy adds YieldEconomy). ``tier0`` is the tier-0 dict for
        seed values. Base building family adds nothing."""
        return []

    # -- 10I: tile-condition modifier lookup --------------------------------

    def _condition_mod(self, key):
        """The snapshotted tile condition's modifier value for ``key`` (e.g.
        ``def_dmg_penalty``), or 0 — GRASS / unplaced / missing key are all
        neutral. Keeps every family stat formula a one-liner. The enum-key
        table import is deferred (see the ``__init__`` note); it only runs
        after a real snapshot, i.e. once ``game.map`` is fully initialised."""
        if self._tile_condition is None or not self._condition_mods:
            return 0
        from game.map.tiles import CONDITION_MODIFIER_KEY
        ck = CONDITION_MODIFIER_KEY.get(self._tile_condition)
        if ck is None:
            return 0
        return self._condition_mods.get(ck, {}).get(key, 0)

    # -- /10I --

    # -- tier / level cursor ----------------------------------------------

    @property
    def _tier(self):
        return self.get_component(TierState)

    @property
    def _lvl_idx(self):
        """0-indexed level within the current tier (prototype ``lvl_idx``)."""
        return self._tier.current_level_in_tier - 1

    def tier_data(self):
        ts = self._tier
        idx = max(0, min(ts.current_tier, len(self._tiers) - 1))
        return self._tiers[idx]

    @property
    def level(self):
        """Global level = sum of earlier tiers' ``levels`` + in-tier level."""
        ts = self._tier
        before = sum(t["levels"] for t in self._tiers[:ts.current_tier])
        return before + ts.current_level_in_tier

    def at_tier_max(self):
        return self._tier.current_level_in_tier >= self.tier_data()["levels"]

    def tier_number(self):
        """1-indexed current tier (tier 0 -> 1, tier 1 -> 2, …)."""
        return self._tier.current_tier + 1

    def has_next_tier(self):
        return self._tier.current_tier + 1 < len(self._tiers)

    # -- derived stats (prototype formulas; ×10 scale baked into the data) -

    def max_hp(self):
        """Base tier HP, lifted by an adjacent ``boost_hp`` and cut by its
        explosion penalty when a booster on this combat building dies (prototype
        ``update_stats_from_tier``). Non-combat buildings carry no ``BoostReceiver``
        → the plain tier value."""
        d = self.tier_data()
        base = d["base_hp"] + self._lvl_idx * d["hp_per_level"]
        rcv = self.get_component(BoostReceiver)
        if rcv is None:
            return max(1, base)
        return max(1, int(base * (1.0 + rcv.hp_pct)) - rcv.hp_penalty())

    def upgrade_cost(self):
        d = self.tier_data()
        return d["upgrade_cost_base"] + self._lvl_idx * d["upgrade_cost_increment"]

    def upkeep(self):
        return 0

    def build_cost(self):
        return self._tiers[0]["build_cost"]

    def slot_key(self):
        ts = self._tier
        t = ts.current_tier
        if 0 <= t < len(self.TIER_SPRITES):
            return f"{self.TIER_SPRITES[t]}_t{t + 1}_lvl{ts.current_level_in_tier}"
        return ""

    # -- stat application + upgrades (full-heal, prototype-exact) ----------

    def apply_tier_stats(self):
        """Recompute derived stats for the current tier/level and FULL-HEAL:
        the prototype's ``update_stats_from_tier`` sets ``hp = max_hp`` on every
        re-apply, so every upgrade and tier advance restores full HP."""
        health = self.get_component(Health)
        health.max_hp = self.max_hp()
        health.hp = health.max_hp
        anim = self.get_component(SpriteAnimator)
        if anim is not None:
            anim.slot_key = self.slot_key()
        self._on_apply_stats()

    def _on_apply_stats(self):
        """Family hook: extend derived-stat application (defence syncs the
        RangeSensor). Default no-op."""

    def on_placed(self, tilemap):
        """Post-placement hook (called once by ``registry.place_building`` after
        the tile/occupancy/scene wiring). Families that react to placement
        override it: boosters clear a neighbour's explosion debuff / apply their
        flat boost, a WallBuilder raises its perimeter walls. Default no-op."""

    def upgrade(self):
        """Level up within the current tier (never crosses a boundary).
        Full-heals. Returns False if already at the tier's max level."""
        ts = self._tier
        if ts.current_level_in_tier < self.tier_data()["levels"]:
            ts.current_level_in_tier += 1
            self.apply_tier_stats()
            return True
        return False

    def advance_tier(self):
        """Advance to the next tier at level 1. Full-heals. Returns False at the
        final tier (caller handles unlock / currency gating)."""
        ts = self._tier
        if not self.has_next_tier():
            return False
        ts.current_tier += 1
        ts.current_level_in_tier = 1
        self.apply_tier_stats()
        return True

    # -- naming + round-end revive (prototype Building.rebuild) ------------

    def set_name(self, name):
        """Rename and reset the rebirth chain to this name."""
        np = self.get_component(Nameplate)
        np.custom_name = name
        np.rebirth_base = name
        np.rebirth_gen = 0

    def rebuild(self):
        """Round-end full-heal + revive (prototype ``Building.rebuild``). A named
        building reborn from death advances its rebirth generation ("<base> the
        2nd"). ``BaseBuilding`` overrides this to never revive."""
        health = self.get_component(Health)
        if health.is_dead:
            np = self.get_component(Nameplate)
            if np.custom_name:
                base = np.rebirth_base or np.custom_name
                np.rebirth_base = base
                np.rebirth_gen += 1
                np.custom_name = f"{base} the {_ordinal(np.rebirth_gen + 1)}"
        health.hp = health.max_hp

    # -- duck-typed contract read by game/map (guard-safe properties) -----

    @property
    def alive(self):
        return not self.get_component(Health).is_dead

    @property
    def building_type(self):
        return self._tier.building_type

    @property
    def damage_dealt_last_round(self):
        return self.get_component(RoundStats).dmg_dealt_last_round

    @property
    def col(self):
        return self._col

    @property
    def row(self):
        return self._row
