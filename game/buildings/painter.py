"""Painter — the risky lump-sum economy line (Phase 10C).

Cave Painter -> Maestro -> Art Factory (``EconomyBuildings.Painters``). Ports the
prototype's ``PainterBuilding``: it generates NO per-round yield; instead it
"paints" across ``rounds_to_payout`` survived income phases, pays a large lump
sum, then removes itself and permanently bars its tile from ever hosting another
Painter. Destroyed before payout = nothing gained ("gone for good").

The progress / payout / tile-freeing flow is driven by the payday painter slot
(``game/core/payday.py``) and the used-tile placement gate (``registry.py``) —
exactly like the prototype's ``Game._process_painters`` / ``place_building``. This
leaf owns only its identity, its ``PainterProgress`` state, and the computed
stats read off ``buildings.json``.
"""
from .components import PainterProgress
from .economy import EconomyBuilding


class Painter(EconomyBuilding):
    BUILDING_TYPE = "painter"
    CONTENT_KEY = "painter_building"
    SUBTREE = ("EconomyBuildings", "Painters")
    TIER_SPRITES = ("painter", "painter", "painter")

    def _extra_components(self, tier0):
        return super()._extra_components(tier0) + [PainterProgress()]

    def yield_amount(self):
        """No normal income — a Painter only ever pays its lump sum (prototype
        ``yield_amount = 0`` keeps it out of the income + upkeep sweeps)."""
        return 0

    # -- deferred-payout stats (prototype PainterBuilding) ----------------

    def payout_amount(self):
        """The lump sum paid on completion (base + per in-tier level)."""
        d = self.tier_data()
        return d["base_payout"] + self._lvl_idx * d["payout_per_level"]

    def rounds_to_payout(self):
        """Survived round-end cycles required before the payout (per tier)."""
        return self.tier_data()["rounds_to_payout"]

    def goneforgood(self):
        """Whether a Painter that dies before payout is permanently lost (per
        tier; every current tier is True)."""
        return self.tier_data()["goneforgood"]

    # -- progress cursor (on the PainterProgress component) ----------------

    @property
    def _prog(self):
        return self.get_component(PainterProgress)

    @property
    def progress(self):
        return self._prog.progress

    def is_ready(self):
        """True once enough round-end cycles have been survived to pay out."""
        return self._prog.progress >= self.rounds_to_payout()

    def advance_progress(self):
        """One survived round-end cycle (payday, alive painters only)."""
        self._prog.progress += 1
        return self._prog.progress
