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
        """Love produced per income phase (prototype ``EconomicBuilding``),
        modified ON READ by the tile condition (10I, prototype
        ``economic_building.py:26-31``): mountain −10% (clamped ≥ 0), pond /
        forest +10%. Every consumer (payday income sweep, HUD income line,
        panel Yield row) sees the modified value. Meditator and Painter
        OVERRIDE this method and take no condition modifier (prototype)."""
        d = self.tier_data()
        y = d["base_yield"] + self._lvl_idx * d["yield_per_level"]
        # -- 10I: tile-condition yield modifiers --
        pen = self._condition_mod("eco_yield_penalty")
        if pen:
            y = max(0, int(y * (1.0 - pen)))
        bonus = self._condition_mod("eco_yield_bonus")
        if bonus:
            y = int(y * (1.0 + bonus))
        # -- /10I --
        return y
