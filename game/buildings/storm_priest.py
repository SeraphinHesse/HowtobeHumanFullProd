"""Storm Priest — the Lightning Strike ability's vehicle (Storm Priest rework).

No longer a combatant: it dropped the ``"combat"`` tag, so it never enters the
core combat sweep (``game.enemies.combat.resolve_combat`` selects defenders via
``scene.by_tag("combat")`` — excluding this tag fully deactivates targeting,
firing and combat-driven animation). It keeps its inherited `DefenceBuilding`
components (`Attacker`/`RangeSensor`/`BoostReceiver`) as harmless, inert
leftovers of the shared family.

Its 3 tiers (Storm Acolyte / Storm Priest / Storm High Priest) now directly
drive ``lightning_level`` (max_level 3) instead of a separate love-priced
upgrade: placing it unlocks lightning to L1
(``game.core.lightning.unlock_from_placement``, unchanged), and advancing its
own tier — the player's ordinary building-upgrade panel, paying Storm
Priest's own tier-advance cost — raises ``lightning_level`` to match via
``game.core.lightning.sync_level_from_tier``, called from
``game/ui/building_ui.py``'s tier-advance branch. Only one may ever be placed
in a run (enforced in the construct-panel UI, not here).

Its ``LightningCaster`` component (``game/core/lightning.py``) puppets the
building's own ``SpriteAnimator`` into the "attack" pose whenever
``lightning.strike()`` fires — since it no longer earns that pose through
combat — reverting to "idle" a short time later. ``LightningCaster`` is
imported LAZILY inside ``_extra_components`` (never at module level): a
module-level import would close a real cycle —
``game.buildings.__init__`` -> ``.storm_priest`` -> ``game.core`` (full
package init) -> ``.levelup`` -> ``game.buildings.research`` ->
``.storm_priest`` (still mid-import, ``StormPriest`` not yet defined) — the
same lazy-import discipline ``building.py``'s ``_condition_mod`` already uses
for ``game.map.tiles``.
"""
from .defence import DefenceBuilding


class StormPriest(DefenceBuilding):
    BUILDING_TYPE = "storm_priest"
    CONTENT_KEY = "storm_priest_building"
    SUBTREE = ("DefenceBuildings", "StormPriest")
    TIER_SPRITES = ("storm_priest_i", "storm_priest_ii", "storm_priest_iii")
    EXTRA_TAGS = ("lightning_source",)

    def _extra_components(self, tier0):
        from game.core.lightning import LightningCaster
        return super()._extra_components(tier0) + [LightningCaster()]
