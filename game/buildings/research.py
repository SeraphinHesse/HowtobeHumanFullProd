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

from .aoe_defence import AOEDefenceBuilding
from .boost import BoostDamage, BoostHP, BoostSpeed
from .defender import Defender
from .meditator import Meditator
from .musician import Musician
from .painter import Painter
from .sun_scorcher import SunScorcher

# building_type -> leaf class. 9D leaves + the 10B defence lines + the 10C
# economy lines + the 10D boost trio; families grow in 10x.
LEAF_CLASSES = {
    "defence": Defender,
    "economic": Musician,
    "aoe_defence": AOEDefenceBuilding,
    "sun_scorcher": SunScorcher,
    "painter": Painter,
    "meditator": Meditator,
    "boost_speed": BoostSpeed,
    "boost_damage": BoostDamage,
    "boost_hp": BoostHP,
}

# The boost trio unlocks together from a single level-up card; the lead type owns
# the card copy, the other two ride its ``unlock_group`` (see the RESEARCH rows).
_BOOST_TRIO = ("boost_speed", "boost_damage", "boost_hp")


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
    # 10B — the two special defence lines. Both are LOCKED types earned via a
    # level-up unlock card. Maw Mortar is gated by village level (available from
    # level 1, i.e. the first level-up); Sun Scorcher is era-gated only — the
    # roll resolves its gate from BeamDefence.era_unlock_round (14), so no
    # gate_kind is needed here.
    "aoe_defence": ResearchSpec(
        starts_unlocked=False, gate_kind="min_village_level",
        gate_path=("DefenceBuildings", "AOEDefence", "unlock_min_village_level"),
        unlock_title="Unlock Maw Mortar",
        unlock_explanation="An organic mortar that rains splash damage on hordes."),
    "sun_scorcher": ResearchSpec(
        starts_unlocked=False,
        unlock_title="Unlock Sun Scorcher",
        unlock_explanation="A burning beam that ramps up — slow to anger, "
                           "deadly to tanks."),
    # 10C — the two economy lines. Painter is a LOCKED type earned via a
    # level-up unlock card gated by village level (available from the first
    # level-up: Painters.unlock_min_village_level = 0). Meditator's type is
    # always unlocked but starts at ZERO researched tiers, so its tier 1 must be
    # researched at a level-up; the roll is era-gated from
    # Meditators.era_unlock_round (10), so no gate_kind is needed here.
    "painter": ResearchSpec(
        starts_unlocked=False, gate_kind="min_village_level",
        gate_path=("EconomyBuildings", "Painters", "unlock_min_village_level"),
        unlock_title="Unlock Painter",
        unlock_explanation="A risky artist who pays a large lump sum after "
                           "surviving a few rounds — then is gone for good."),
    "meditator": ResearchSpec(starts_with_tier=0),
    # 10D — the boost trio. All three are LOCKED types that unlock TOGETHER from
    # one round-gated card (round 10, BoostBuildings.globals.unlock_min_round). The
    # lead (boost_speed) carries the card copy + is the only one the roll offers an
    # unlock card for; the other two ride its unlock_group (the roll skips non-lead
    # members — see game/core/levelup.py). All three need a row so each offers its
    # own Supporting Fan->Cheerleader->Drill Sergeant tier cards AFTER unlocking.
    "boost_speed": ResearchSpec(
        starts_unlocked=False, gate_kind="min_round",
        gate_path=("BoostBuildings", "globals", "unlock_min_round"),
        unlock_group=_BOOST_TRIO,
        unlock_title="Unlock Boost Buildings",
        unlock_explanation="Cheerleaders that buff adjacent defenders — but curse "
                           "their neighbours when they fall."),
    "boost_damage": ResearchSpec(
        starts_unlocked=False, gate_kind="min_round",
        gate_path=("BoostBuildings", "globals", "unlock_min_round"),
        unlock_group=_BOOST_TRIO),
    "boost_hp": ResearchSpec(
        starts_unlocked=False, gate_kind="min_round",
        gate_path=("BoostBuildings", "globals", "unlock_min_round"),
        unlock_group=_BOOST_TRIO),
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
