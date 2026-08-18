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

**Its art tracks the PAINTING, not the upgrade level** (feature: painter
progress art). ``slot_key`` is overridden to key ``_lvl{n}`` off
``PainterProgress.progress`` -- one stage per survived round, so the canvas
visibly fills in -- and the number of stages is per tier (``rounds_to_payout``:
3 / 4 / 6), decoupled from the uniform ``levels`` value of 3 every other line
keys its art off. An un-imported stage backs off to the highest lower stage
that has art (``_resolve_art``), against the imported-slot set the HOST
installs through ``set_art_slots``.
"""
from .components import PainterProgress
from .economy import EconomyBuilding

#: Which ``painter_*`` art slots actually have imported art, or ``None`` when
#: nobody installed the set. THE HOST derives it once at boot from the asset
#: manifest and installs it via :func:`set_art_slots` -- this package may never
#: read the asset layer itself (D6/E-37), the same rule ``game/main.py``'s
#: ``wall_art`` / ``condition_art`` / ``colour_columns`` derivations already
#: follow. Unset (every logic test, every headless boot) means NO fallback:
#: ``slot_key()`` returns its computed key verbatim, exactly as it would have
#: before this feature.
_ART_SLOTS = None


def set_art_slots(slots):
    """Install (or clear, with ``None``) the imported-``painter_*``-slot set.

    A module-level seam rather than a constructor argument, matching
    ``components.set_boss_upgrade_pair`` / ``set_damage_hook``: a Painter is
    built by ``registry.create`` from four call sites that have no business
    knowing about art, and the answer is process-lifetime (art cannot change
    mid-run)."""
    global _ART_SLOTS
    _ART_SLOTS = frozenset(slots) if slots is not None else None


class Painter(EconomyBuilding):
    BUILDING_TYPE = "painter"
    CONTENT_KEY = "painter_building"
    SUBTREE = ("EconomyBuildings", "Painters")
    TIER_SPRITES = ("painter", "painter", "painter")
    # An upgrade buys payout, not visible painting -- so the panel's action
    # button reads INVEST for a Painter (see `Building.ACTION_UPGRADE_KEY`).
    ACTION_UPGRADE_KEY = "building.action.invest"
    ACTION_UPGRADE_MANY_KEY = "building.action.invest_many"

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

    # -- art: the canvas fills in, the upgrade level does NOT show -----------

    def art_stages(self):
        """How many distinct painting stages this tier's art has.

        One per survived round: progress ``0..rounds_to_payout-1`` are the
        stages a player can actually SEE, since the painter is paid out and
        freed the same payday its progress reaches the threshold."""
        return self.rounds_to_payout()

    def slot_key(self):
        """The Painter's art tracks PAINTING PROGRESS, not the upgrade level.

        Deliberately ignores ``TierState.current_level_in_tier`` -- which is
        what every other building keys its ``_lvl{n}`` suffix off
        (``Building.slot_key``). Buying a level on a Painter buys payout, not
        visible work, so it must not repaint the canvas; the panel calls that
        button INVEST for the same reason (``ACTION_UPGRADE_KEY``). The tier
        prefix still comes from ``TIER_SPRITES``, so a tier advance DOES move
        the art -- to the new tier's stage for the progress already painted,
        which is kept across the advance.

        The stage count is per TIER and need not equal the tier's ``levels``
        (3 everywhere): it is ``rounds_to_payout``, i.e. 3 / 4 / 6 today. A
        tier retuned past its declared slots resolves through the same
        fallback an un-imported stage does."""
        tier0 = self._tier.current_tier
        if not (0 <= tier0 < len(self.TIER_SPRITES)):
            return ""
        prefix = self.TIER_SPRITES[tier0]
        stage = max(0, min(self.progress, self.art_stages() - 1))
        return _resolve_art(prefix, tier0 + 1, stage + 1)


def _resolve_art(prefix, tier_no, stage_no):
    """``{prefix}_t{tier_no}_lvl{stage_no}``, backed off to the highest LOWER
    stage that actually has imported art.

    A painting that has no art for stage 5 yet should keep showing stage 4 --
    not a grey X -- so a designer can import the stages one at a time and see
    each appear. The same shape ``game/map/wall_render.py`` uses for era art
    (try the specific key, fall back when the manifest has nothing), just
    walking down instead of falling back once. With no set installed, or with
    nothing in the tier imported at all, the computed key is returned as-is:
    E-37 then draws the placeholder, which is the honest answer."""
    key = f"{prefix}_t{tier_no}_lvl{stage_no}"
    if _ART_SLOTS is None or key in _ART_SLOTS:
        return key
    for lower in range(stage_no - 1, 0, -1):
        candidate = f"{prefix}_t{tier_no}_lvl{lower}"
        if candidate in _ART_SLOTS:
            return candidate
    return key
