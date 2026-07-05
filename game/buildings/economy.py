"""EconomyBuilding — love-yielding building family (Phase 9D).

Musician / Meditator / Painter share this family; 9D ships the Musician. Adds a
``YieldEconomy`` marker component and a computed per-round yield. Meditators'
streak and Painters' deferred payout extend this in 10B/10C.
"""
from .building import Building
from .components import YieldEconomy


class EconomyBuilding(Building):
    CONTENT_KEY = "economic_building"
    EXTRA_TAGS = ("economy",)

    def _extra_components(self, tier0):
        return [YieldEconomy()]

    def yield_amount(self):
        """Love produced per income phase (prototype ``EconomicBuilding``). Tile
        condition + boss modifiers apply on read in the prototype; those land
        with tile conditions (10I) — here it is the flat tier/level value."""
        d = self.tier_data()
        return d["base_yield"] + self._lvl_idx * d["yield_per_level"]
