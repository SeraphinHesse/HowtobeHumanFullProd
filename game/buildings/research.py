"""Research specs — how each building TYPE is earned (Phase 10A).

The declarative table `game/core/levelup.py` rolls level-up options from. Ports
the prototype's hand-written per-type branches in ``_roll_levelup_options`` /
``_apply_levelup_option`` (``src/core/game.py``) into one row per type, so a new
building family (10B-10E) adds a leaf class + a ``RESEARCH`` row and never
reopens the roll.

A spec never stores a gate VALUE — only where in ``buildings.json`` to read it
(``gate_path``). Era gates need no field at all: they resolve from the leaf's
``SUBTREE`` group (``<group>.era_unlock_round``, the one canonical era key).

Import boundary: this module deliberately imports ONLY the leaf classes (which
reach `engine` and nothing else), so ``game/core`` can read the table without
touching ``registry.py`` — registry pulls in ``game.map.tiles``, which pulls
``game.core.balance``, closing an import cycle back through
``game/core/__init__.py``. Hence ``LEAF_CLASSES`` lives HERE and ``registry``
re-exports it as ``BUILDING_CLASSES`` (one source, two names for two callers).
"""
from dataclasses import dataclass

from .defender import Defender
from .musician import Musician

# building_type -> leaf class. Only the 9D leaves; families grow in 10x.
LEAF_CLASSES = {
    "defence": Defender,
    "economic": Musician,
}


@dataclass(frozen=True)
class ResearchSpec:
    """How a building type enters the run, and what gates its unlock reward."""

    starts_unlocked: bool = True    # False -> earned via a level-up unlock reward
    starts_with_tier: int = 1       # 0 -> even tier 1 must be researched
    gate_kind: str = None           # None | "min_village_level" | "min_round"
    gate_path: tuple = ()           # path into buildings.json holding the gate value
    unlock_group: tuple = ()        # types unlocked together (the boost trio)
    unlock_title: str = ""          # UI copy for the unlock card
    unlock_explanation: str = ""


# building_type -> ResearchSpec. Keys must exist in LEAF_CLASSES; an entry
# without a class would offer a level-up card that places nothing.
RESEARCH = {
    "defence": ResearchSpec(),
    "economic": ResearchSpec(),
    # 10B: "aoe_defence": ResearchSpec(
    #          starts_unlocked=False, gate_kind="min_village_level",
    #          gate_path=("DefenceBuildings", "AOEDefence",
    #                     "unlock_min_village_level"),
    #          unlock_title="Unlock Maw Mortar", unlock_explanation="...")
    #      "sun_scorcher": era-gated only (BeamDefence.era_unlock_round = 14)
    # 10C: "painter": gate_path ("EconomyBuildings", "Painters",
    #                            "unlock_min_village_level")
    #      "meditator": starts_with_tier=0 (era-gated, tier 1 is researched)
    # 10D: "boost_speed"/"boost_damage"/"boost_hp": gate_kind="min_round",
    #      gate_path ("BoostBuildings", "globals", "unlock_min_round"),
    #      unlock_group = the trio (one card unlocks all three)
    # 10E: "blocker": no gate;  "wall_builder": starts_with_tier=0
}


def tiers_unlocked_for(state, btype):
    """How many tiers of ``btype`` are researched (1 = starting tier only)."""
    return state.tiers_unlocked.get(btype, 1)


def type_unlocked(state, btype):
    return state.unlocked_buildings.get(btype, True)


def buildable(state, btype):
    """Can this type be placed at all? Needs the type earned AND its first tier
    researched — the prototype's meditator / wall-builder gate (``game.py:648``),
    where the type is "unlocked" but starts at zero researched tiers."""
    return type_unlocked(state, btype) and tiers_unlocked_for(state, btype) >= 1
