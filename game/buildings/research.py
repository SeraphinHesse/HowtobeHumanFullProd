"""Research specs — how each building TYPE is earned (Phase 10A).

The declarative table `game/core/levelup.py` rolls level-up options from. Ports
the prototype's hand-written per-type branches in ``_roll_levelup_options`` /
``_apply_levelup_option`` (``src/core/game.py``) into one row per type, so a new
building family (10B-10E) adds a leaf class + a ``RESEARCH`` row and never
reopens the roll.

A spec never stores a gate VALUE — only where in ``buildings.json`` to read it
(``gate_path``). Since TimelinePLAN T4, the type's UNLOCK card is gated by
whether it has a Timeline placement at ``tier_index=0``
(``data/balancing/progression.json``, read live via
``game.core.levelup.tier_offerable``/``timeline_level_for`` —
``unlock_min_round`` no longer exists) — unlocking a type makes its tier 1
immediately placeable, so no separate "starts at tier 0" gate exists.
Whether a type starts unlocked is a similar story: ``starts_unlocked_for``
reads it live off the leaf's ``SUBTREE`` group (``<group>.starts_unlocked``) —
a balanceable flag, not a Python default — so a designer can flip which types
are available from round 1 by editing ``buildings.json``, not this file. The
boost trio shares ONE flag at ``BoostBuildings.globals.starts_unlocked``
(``starts_unlocked_path`` overrides the per-leaf default).

Import boundary: this module deliberately imports ONLY the leaf classes (which
reach `engine` and nothing else), so ``game/core`` can read the table without
touching ``registry.py`` — registry pulls in ``game.map.tiles``, which pulls
``game.core.balance``, closing an import cycle back through
``game/core/__init__.py``. Hence ``LEAF_CLASSES`` lives HERE and ``registry``
re-exports it as ``BUILDING_CLASSES`` (one source, two names for two callers).
"""
from dataclasses import dataclass
from functools import reduce

from .aoe_defence import AOEDefenceBuilding
from .boost import BoostDamage, BoostHP, BoostSpeed
from .defender import Defender
from .meditator import Meditator
from .musician import Musician
from .painter import Painter
from .storm_priest import StormPriest
from .structure import Blocker, WallBuilder
from .sun_scorcher import SunScorcher

# building_type -> leaf class. 9D leaves + the 10B defence lines + the 10C
# economy lines + the 10D boost trio; families grow in 10x.
LEAF_CLASSES = {
    "defence": Defender,
    "economic": Musician,
    "aoe_defence": AOEDefenceBuilding,
    "sun_scorcher": SunScorcher,
    "storm_priest": StormPriest,
    "painter": Painter,
    "meditator": Meditator,
    "boost_speed": BoostSpeed,
    "boost_damage": BoostDamage,
    "boost_hp": BoostHP,
    "blocker": Blocker,
    "wall_builder": WallBuilder,
}

# The boost trio unlocks together from a single level-up card AND researches each
# of its later tiers together from a single card; the lead type owns the card copy,
# the other two ride its ``unlock_group``/``tier_group`` (see the RESEARCH rows).
_BOOST_TRIO = ("boost_speed", "boost_damage", "boost_hp")


@dataclass(frozen=True)
class ResearchSpec:
    """How a building type enters the run, and what gates its unlock reward."""

    gate_kind: str = None           # None | "min_village_level"
    gate_path: tuple = ()           # path into buildings.json holding the gate value
    starts_unlocked_path: tuple = ()  # override for starts_unlocked_for's default
    unlock_group: tuple = ()        # types unlocked together (the boost trio)
    unlock_title: str = ""          # UI copy override; default is
                                    # the tier-1 name, wrapped by the UI in
                                    # `levelup.unlock_title` (see levelup)
    unlock_explanation: str = ""
    tier_group: tuple = ()          # types whose TIERS research together (the trio)
    tier_copy_path: tuple = ()      # buildings.json path holding the tier card copy


# building_type -> ResearchSpec. Keys must exist in LEAF_CLASSES; an entry
# without a class would offer a level-up card that places nothing.
RESEARCH = {
    "defence": ResearchSpec(),
    "economic": ResearchSpec(),
    # 10B — the two special defence lines. Both are LOCKED types earned via a
    # level-up unlock card. Maw Mortar is gated by village level (available from
    # level 1, i.e. the first level-up); Sun Scorcher needs no gate_kind — its
    # unlock card is gated by whether BeamDefence's tier 0 has a Timeline
    # placement, read live via tier_offerable (TimelinePLAN T4). (``starts_
    # unlocked`` for both is data, read live from their own SUBTREE group —
    # see ``starts_unlocked_for``.)
    "aoe_defence": ResearchSpec(
        gate_kind="min_village_level",
        gate_path=("DefenceBuildings", "AOEDefence", "unlock_min_village_level"),
        unlock_explanation="An organic mortar that rains splash damage on hordes."),
    "sun_scorcher": ResearchSpec(
        unlock_explanation="A burning beam that ramps up — slow to anger, "
                           "deadly to tanks."),
    # Storm Priest — a LOCKED defence type earned via a level-up unlock card,
    # offered as soon as its tier 0 gets a Timeline placement (no gate_kind,
    # same shape as sun_scorcher above). Placing one is the ONLY way
    # to unlock lightning strikes (game/core/lightning.py.unlock_from_placement,
    # wired by game/ui/building_ui.py._do_place off its "lightning_source" tag).
    "storm_priest": ResearchSpec(
        unlock_explanation="A priest whose presence summons lightning strikes."),
    # 10C — the two economy lines. Painter is a LOCKED type earned via a
    # level-up unlock card gated by village level (available from the first
    # level-up: Painters.unlock_min_village_level = 0). Meditator's type starts
    # locked too (data-driven, see the module docstring); unlocking it makes
    # tier 1 immediately placeable — its unlock card is gated by whether
    # Meditators' tier 0 has a Timeline placement, so no gate_kind is needed here.
    "painter": ResearchSpec(
        gate_kind="min_village_level",
        gate_path=("EconomyBuildings", "Painters", "unlock_min_village_level"),
        unlock_explanation="A risky artist who pays a large lump sum after "
                           "surviving a few rounds — then is gone for good."),
    "meditator": ResearchSpec(),
    # 10D — the boost trio. All three are LOCKED types that unlock TOGETHER from
    # one card; only the LEAD's (boost_speed's) tier-0 Timeline placement is
    # ever consulted by the roll (TimelinePLAN D8). The lead (boost_speed)
    # carries the card copy + is the only one the
    # roll offers an unlock card for; the other two ride its unlock_group (the
    # roll skips non-lead members — see game/core/levelup.py). Their later TIERS
    # work exactly the same way: ``tier_group`` collapses the three per-line tier
    # cards into ONE card that researches tier N for all three at once, whose copy
    # is designer-editable at ``tier_copy_path`` (BoostBuildings.globals'
    # tier_card_titles/tier_card_explanations) since no single line's tier name can
    # title a card that grants all three. All three still need a row so
    # ``tiers_unlocked``/``unlocked_buildings`` stay per-type. They share ONE
    # starts_unlocked flag at
    # BoostBuildings.globals (their own SUBTREE groups are Speed/Damage/HP, so
    # the default derivation would miss it — hence the explicit
    # starts_unlocked_path on all three).
    "boost_speed": ResearchSpec(
        starts_unlocked_path=("BoostBuildings", "globals", "starts_unlocked"),
        unlock_group=_BOOST_TRIO,
        unlock_title="Boost Buildings",
        unlock_explanation="Cheerleaders that buff adjacent defenders — but curse "
                           "their neighbours when they fall.",
        tier_group=_BOOST_TRIO,
        tier_copy_path=("BoostBuildings", "globals")),
    "boost_damage": ResearchSpec(
        starts_unlocked_path=("BoostBuildings", "globals", "starts_unlocked"),
        unlock_group=_BOOST_TRIO,
        tier_group=_BOOST_TRIO),
    "boost_hp": ResearchSpec(
        starts_unlocked_path=("BoostBuildings", "globals", "starts_unlocked"),
        unlock_group=_BOOST_TRIO,
        tier_group=_BOOST_TRIO),
    # 10E — the two passive structure lines. Blocker's Bulwark/Bastion tiers are
    # researched at level-ups, gated by their own Timeline placements; the type
    # itself starts LOCKED (data-driven balance change — the
    # prototype's ``blocker_tiers_unlocked = 1`` is no longer followed) and its
    # unlock card is gated the same way at tier 0. WallBuilder's
    # type also starts locked; unlocking it makes tier 1 immediately placeable —
    # its unlock card is gated by whether its tier 0 has a Timeline placement, so
    # no gate_kind is needed here — identical shape to the Meditator row.
    "blocker": ResearchSpec(),
    "wall_builder": ResearchSpec(),
}


def starts_unlocked_for(btype, buildings_balance):
    """Whether ``btype`` is available from round 1 (data-driven — see the
    module docstring). Reads live off the leaf's own SUBTREE group node
    (``<group>.starts_unlocked``), unless its spec overrides the path (the
    boost trio shares one flag at ``BoostBuildings.globals``)."""
    spec = RESEARCH[btype]
    path = spec.starts_unlocked_path or (
        *LEAF_CLASSES[btype].SUBTREE, "starts_unlocked")
    return reduce(lambda d, k: d[k], path, buildings_balance)


def tiers_unlocked_for(state, btype):
    """How many tiers of ``btype`` are researched (1 = starting tier only)."""
    return state.tiers_unlocked.get(btype, 1)


def type_unlocked(state, btype):
    return state.unlocked_buildings.get(btype, True)


def buildable(state, btype):
    """Can this type be placed at all? Needs the type earned — with
    ``starts_with_tier`` gone, every unlocked type's ``tiers_unlocked_for`` is
    never below 1, so unlocking a type makes its tier 1 immediately placeable
    (no second "research tier 1" card required)."""
    return type_unlocked(state, btype)
