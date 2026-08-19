"""vfx_variants — turning a trigger row's ``variant_select`` into one slot key
(VfxAuthoringPLAN VA-2).

This is the GAME half of variant resolution: it owns the mode vocabulary
(``"random"``/``"level"``/``"misc"``), reads a source object's level, and
consults ``game/vfx_misc.py``'s provider registry. The registry mechanics —
which slots are interchangeable, and clamping an index onto them — live in
``engine/vfx/variants.py``, which is kept free of this vocabulary the same way
``engine/vfx/params.py`` is kept free of spark preset names (D5).

``editor/`` mirrors this mapping for its preview rather than importing it
(that package may never import ``game/``) — the sanctioned duplication
``editor/vfx_params.py`` and ``editor/timeline_curve.py`` already are.
"""
from engine.vfx import variants as _variants

RANDOM = "random"
LEVEL = "level"
MISC = "misc"

MODES = (RANDOM, LEVEL, MISC)


def source_level(obj):
    """``obj``'s 0-indexed level for ``LEVEL`` mode, or None.

    A building answers with its GLOBAL level — ``Building.level``, the sum of
    every earlier tier's ``levels`` plus the in-tier level — turned 0-indexed
    here. So variant 1 is tier 1 level 1, variant 2 is tier 1 level 2, …, and
    the first variant past tier 1's last level is tier 2 level 1. **This used
    to read ``TierState.current_tier``**, which meant the art only ever
    changed on a TIER-UP: a designer levelling a building watched three
    level-ups do nothing and reasonably concluded the mode was broken (found
    live, feat-projectile-variant-select). ``Building.level`` is the same
    number the level-up UI shows, so "variant N" now means "level N".

    ``TierState.current_tier`` remains the fallback for an object that
    carries a tier cursor but is not a ``Building`` (a hand-built test
    double); an enemy answers with its ``_enemy_era``. Reading that transient
    (E-11 underscore) is deliberate: it is set on EVERY enemy at construction
    — including the boss, whose public ``era`` property is a different number
    off ``DeathSpawn`` — and the alternative is widening
    ``RunState.*_events`` and the ``resolve_combat`` callbacks to thread a
    level through, which D4 explicitly declines to do for a cosmetic lever.

    None means "no level in hand", which ``resolve`` reads as variant 0 — the
    answer at the five events that carry only a world point (D4).
    """
    if obj is None:
        return None
    # `Building.level` is 1-indexed and GLOBAL (it already composes tier +
    # in-tier level); variants are 0-indexed. Read by duck type rather than
    # isinstance so this module keeps importing only `components` — and an
    # enemy has no `level`, so this branch is buildings-only in practice.
    level = getattr(obj, "level", None)
    if isinstance(level, int) and not isinstance(level, bool):
        return level - 1
    from game.buildings.components import TierState
    getter = getattr(obj, "get_component", None)
    if getter is not None:
        tier_state = getter(TierState)
        if tier_state is not None:
            return tier_state.current_tier
    return getattr(obj, "_enemy_era", None)


def variant_index(mode, *, rng=None, level=None, misc_key="", count=1):
    """The index ``mode`` selects among ``count`` variants.

    ``count`` is passed so RANDOM can draw in range without this function
    needing the slot list. An unrecognised mode reads as 0 rather than
    raising — the schema's enum is the guard, and a cosmetic lever must not
    take down a frame if that guard is ever bypassed (E-37).
    """
    if mode == RANDOM:
        # `rng` is the caller's injected Random, never the stdlib module —
        # the same contract every emitter in engine/vfx keeps, so seeded
        # parity tests stay possible.
        return 0 if rng is None else rng.randrange(count)
    if mode == LEVEL:
        return 0 if level is None else level
    if mode == MISC:
        from game import vfx_misc
        return vfx_misc.resolve(misc_key)
    return 0


def resolve(registry, slot_key, mode, misc_key="", *, rng=None, source=None,
            level=None):
    """The slot key to actually play for ``slot_key`` under ``mode``.

    ``level`` is an already-resolved level, for a call site that knows one
    without holding the object — VA-4's respawn ledger carries the reviving
    building's tier, since payday held the building even though the drain
    does not. It WINS over ``source`` when both are given; neither is the
    common case (five of the ten events have neither, and resolve to variant
    0 under LEVEL mode by D4).

    **A slot with fewer than two variants short-circuits before any mode
    logic runs**, and that is load-bearing, not an optimisation: every vfx
    slot has exactly one variant on landing, so drawing an RNG number here
    would consume from the shared global draw stream and desync every
    downstream roll from what the game did before this feature. VA-2 is a
    no-op only because this branch exists.

    Returns ``slot_key`` unchanged when the registry cannot place it, so a
    caller can always pass the result straight to ``spawn_play_once``.
    """
    if registry is None:
        return slot_key
    variants = _variants.variant_slots(registry, slot_key)
    if len(variants) < 2:
        return variants[0] if variants else slot_key
    if level is None:
        level = source_level(source)
    index = variant_index(mode, rng=rng, level=level, misc_key=misc_key,
                          count=len(variants))
    return _variants.slot_at(variants, index)


def max_variant(registry, slot_key):
    """``slot_key``'s HIGHEST variant — the "max level" art, without a level.

    ``LEVEL`` mode clamps its index to the last variant (``slot_at``), so this
    is what a max-level source would resolve to; it is a separate entry point
    because the Sniper's cosmetic tracer (``game/ui/effects.py``) wants that
    top variant unconditionally rather than one selected off a source object.
    Degrades to ``slot_key`` when the registry is absent or cannot place it,
    exactly like ``resolve`` (E-37)."""
    if registry is None:
        return slot_key
    variants = _variants.variant_slots(registry, slot_key)
    return variants[-1] if variants else slot_key
