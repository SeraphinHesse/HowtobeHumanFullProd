"""Meditator — the compounding-streak economy line (Phase 10C).

Meditator -> Shaman -> Sun Priest (``EconomyBuildings.Meditators``). Ports the
prototype's ``MeditatorBuilding``: like the Musician it pays love each income
phase, but the payout COMPOUNDS — every consecutive undisturbed income phase
multiplies the running yield by ``streak_growth`` (capped at ``streak_max``
steps). Any damage taken during a round "disturbs" the meditation: the streak
resets to 0 and the next payout falls back to base.

Carries its OWN art slots (``meditator_``/``shaman_``/``sun_priest_``) — the
line used to point at the musician's `flute_player`/`harp_player`/`trio` keys,
and that link is deliberately severed: nothing visual is shared between the two
economy lines any more. The type
is locked until earned via a level-up unlock card, gated by
``Meditators.tiers[0].unlock_min_round`` (10); unlocking it makes tier 1
immediately placeable — no separate "research tier 1" step
(``research.py``'s bare ``ResearchSpec()`` row).

The streak lives on the shared ``YieldEconomy.streak`` component. The prototype
hid the disturbance/advance side-effect inside a ``yield_amount`` property read
once per income phase; here ``yield_amount()`` is PURE (three callers: payday,
the panel, the HUD income readout) and the side-effecting step is
``collect_income`` — called ONLY by the payday income sweep, which passes the
disturbance it derives from ``RoundStats.dmg_taken_last_round``.
"""
from .components import YieldEconomy
from .economy import EconomyBuilding


class Meditator(EconomyBuilding):
    BUILDING_TYPE = "meditator"
    CONTENT_KEY = "meditator_building"
    SUBTREE = ("EconomyBuildings", "Meditators")
    TIER_SPRITES = ("meditator", "shaman", "sun_priest")

    @property
    def streak(self):
        """The current compounding streak (read by the panel)."""
        return self.get_component(YieldEconomy).streak

    def streak_growth(self):
        return self.tier_data()["streak_growth"]

    def streak_max(self):
        return self.tier_data()["streak_max"]

    def _base_yield(self):
        d = self.tier_data()
        return d["base_yield"] + self._lvl_idx * d["yield_per_level"]

    def _yield_for_streak(self, streak):
        """Compounded yield after ``streak`` undisturbed phases (prototype
        ``int(round(base * growth**streak))``)."""
        return int(round(self._base_yield() * (self.streak_growth() ** streak)))

    def yield_amount(self):
        """PURE current payout for the CURRENT streak — safe for the panel + HUD
        (no streak advance). The income sweep uses ``collect_income`` instead."""
        return self._yield_for_streak(self.get_component(YieldEconomy).streak)

    def collect_income(self, disturbed):
        """Income-time payout (payday only): reset the streak if the round was
        disturbed, pay the current streak, then advance it for next phase —
        reproducing the prototype ``yield_amount`` property's read-once
        reset->pay->advance sequence."""
        ye = self.get_component(YieldEconomy)
        if disturbed:
            ye.streak = 0
        payout = self._yield_for_streak(ye.streak)
        if ye.streak < self.streak_max():
            ye.streak += 1
        return payout
