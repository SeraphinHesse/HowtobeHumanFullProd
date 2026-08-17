"""Boss upgrade timeline (BossUpgradeTimelinePLAN BU-2) — the effect engine.

Pure logic (no pygame), and — unlike its predecessor ``boss_bonuses.py``, which
reaches for ``game.buildings.components.TierState`` — this module imports
**NOTHING** from ``game.buildings`` or ``game.enemies``. That is a hard rule,
not a preference: it is the ONE place that knows which upgrade ids exist and how
many times each has been picked, and it is read from the round machine, the
cutscene and (in BU-3) a dozen hook sites across every other package. See the
"one-time effects" seam below for how the one effect that genuinely needs
building knowledge gets it without an import.

**Where the numbers live.** Everything is driven by the ``boss_upgrades``
balancing domain (``data/balancing/boss_upgrades.json``, threaded in as
``boss_upgrades_balance``) under a single top-level ``BossUpgrades`` group:

- ``["BossUpgrades"]["Catalog"][upgrade_id]`` -> ``{name, description, params}``
  — the 12 fixed upgrade ids and their editable copy + magnitudes.
- ``["BossUpgrades"]["Timeline"]["milestones"]`` — exactly 4 rows, each
  ``{slots: [id|null, id|null, id|null], retaliation_bonus_love: int}``.

**The cycle (D1).** ``milestone_index(boss_num) == (boss_num - 1) % 4`` — boss 5
repeats milestone 1 verbatim, forever, so the same milestone always re-offers
the identical 3 options. ``boss_num`` is 1-based.

**Picks stack (D4).** The player freely picks 1 of 3 at every bossfight,
independent of prior picks; a persistent %-effect picked twice applies twice
(ADDITIVE), which is why ``RunState.boss_upgrade_stacks`` counts picks rather
than storing a bool. ``stack_count`` is THE read accessor — every hook site
BU-3 wires must go through it, and nothing in this module duplicates that
lookup inline.

**``boss_upgrades_balance is None`` is tolerated everywhere**, the same
"host-set optional, safe when absent" shape ``game/core/levelup.py``'s
``timeline_level_for`` gives ``progression_balance``: a bare ``Session`` a logic
test builds never wires one up, and must not crash — it simply offers nothing
(``[None, None, None]``) and pays no retaliation love (0).

Three of the twelve upgrades are ONE-TIME
---------------------------------------------------------------------------
``ONE_TIME_IDS`` — ``restock_lives`` (#1), ``stone_thrower_sync`` (#9) and
``tile_refund`` (#12) — fire an immediate side effect inside ``apply_pick``.
The other nine are persistent passives: ``apply_pick`` does nothing for them
beyond the stack increment, and their whole implementation is BU-3's hook sites
reading ``stack_count``. This module is the authority on which is which, so
that split is a small hardcoded dispatch table here (``_ONE_TIME_EFFECTS``)
rather than a data flag — the ids are fixed and each needs bespoke code anyway.

**The seam BU-3 plugs into: ``set_one_time_hook``.** ``restock_lives`` and
``tile_refund`` are implementable right here (they touch only ``RunState`` and
``core_balance``). ``stone_thrower_sync`` is not: it must walk every placed
``Defender``, find the highest tier/level, and advance the others through the
normal free tier-advance path — i.e. it needs ``game.buildings``, which this
module may never import. So it goes through an injected callback, the
``game/enemies/components.py::set_damage_hook`` precedent (`game/CLAUDE.md`):

    # in game/main.py's boot (the host may import both packages):
    boss_upgrades.set_one_time_hook("stone_thrower_sync", sync_stone_throwers)

where ``sync_stone_throwers`` is BU-3's new building-sweep helper, imported by
the host from the buildings package.

- Unset by default, so a bare import of this module changes nothing and every
  logic test that never installs a hook sees a harmless no-op.
- Installed by the HOST (``game/main.py``'s boot, beside its other wiring) —
  never by this module and never by ``game/core``, which is what keeps the
  import direction one-way.
- Called as ``fn(state, tilemap, scene)`` AFTER the stack increment and after
  whatever inline effect the id carries, and only when BOTH ``tilemap`` and
  ``scene`` are non-``None`` (``apply_pick``'s two optional trailing params).
  A pick resolved without a world in hand — a headless test, ``tools/simrun``
  before its scene exists — is a silent no-op, never a crash.
- The table is keyed by upgrade id, so it generalises if a later effect needs
  the same treatment — see the next section, which is exactly that.

A PERSISTENT upgrade may ALSO need a one-time PICK-TIME action (BU-3 3.3)
---------------------------------------------------------------------------
``_ONE_TIME_HOOKS`` is looked up by ``apply_pick`` **independently of**
``ONE_TIME_IDS``/``_ONE_TIME_EFFECTS`` — the hook table does not ask, and does
not care, whether the id it is holding a callback for is a one-time upgrade.
That is deliberate, and it is the whole mechanism for the second category:

    a PERSISTENT passive whose effect lives at a hook site, but which needs a
    single SETUP/SNAPSHOT step at the moment it is picked.

Today's one member is ``mortar_slow`` (#3), whose D16 SNAPSHOT semantics mean
only the mortars alive at pick-time ever slow: the host installs a snapshot
function through the SAME call every one-time effect uses —

    boss_upgrades.set_one_time_hook("mortar_slow", snapshot_fn)

— and it stamps ``RunState.mortar_slow_snapshot_ids`` with the ``id()`` of
every placed mortar. The upgrade's actual EFFECT is still an ordinary BU-3 hook
site (``game/enemies/combat.py``'s ``_fire_splash``) reading ``hook_stacks`` and
checking membership of that set; the pick-time hook only fills it.

**No parallel mechanism was added for this, on purpose.** A second table would
be a second answer to "what runs at pick time", with the same signature, the
same host-installs-it rule and the same tilemap/scene guard — so the two
categories share one seam and are told apart by ``ONE_TIME_IDS``, which is
already the authority on which is which. If a future upgrade needs the same
thing, register it here and say so in this section; do not add a third table.

THE BU-3 HOOK THREADING PATTERN (read this before wiring a new hook)
---------------------------------------------------------------------------
A persistent passive's whole implementation is a HOOK SITE somewhere else in
the game reading ``stack_count`` plus its own magnitude out of the catalog.
Those sites (``Building.build_cost``, ``TileMap.unlock_cost``,
``movement.move_time``, ``registry.place_building``, …) are pure functions that
have never seen a ``RunState``, and none of them can reach the balancing
document either. **Every BU-3 hook threads the same optional trailing PAIR, in
this fixed order, and nothing else:**

    def some_hook(…existing args…, run_state=None, boss_upgrades_balance=None):

- Both default ``None`` and the effect applies only when BOTH are non-``None``
  — so every pre-existing caller, every test and every headless tool that does
  not pass them is **byte-identical** to before BU-3. This is the
  ``progression_balance=None`` shape ``game/core/levelup.py`` already uses.
- ``place_building`` is the ONE exception, and only because it already carries
  the RunState under the name ``state``: it grows ``boss_upgrades_balance``
  alone rather than a second, duplicate reference to the same object.
- **At the call site the pair is always spelled off the ``Session``**, which
  holds both:  ``run_state=session.state,
  boss_upgrades_balance=session.boss_upgrades_balance``. ``RunState`` itself
  deliberately does NOT carry a balance reference — it is seeded from balance,
  not a view onto it — so the pair travels together rather than one fetching
  the other.
- **The hook body is one call to** ``hook_stacks`` (or, for a %-off-a-price
  effect, ``discounted``, which wraps it). Never index
  ``state.boss_upgrade_stacks`` or the catalog dict inline: those two readers
  are where the "is it on / how big is it" question is answered, once.
- ``game/buildings/**`` and ``game/map/**`` must import this module **LAZILY,
  inside the function body** — ``game.core.__init__`` imports ``payday``, which
  imports ``game.buildings.movement``, so a module-level import from either
  package closes a real cycle. Same discipline (and same reason) as
  ``Building._condition_mod``'s deferred ``game.map.tiles`` import.
"""

#: The three upgrade ids whose whole effect fires ONCE, at pick time (plan §2:
#: #1, #9, #12). Every other catalog id is a persistent passive whose effect
#: lives entirely at its BU-3 hook site, read through ``stack_count``.
ONE_TIME_IDS = ("restock_lives", "stone_thrower_sync", "tile_refund")

#: ``{upgrade_id: fn(state, tilemap, scene)}`` — the injected impure half of
#: whatever an upgrade has to do AT PICK TIME (see the module docstring's two
#: seam sections). Host-installed via ``set_one_time_hook``; empty by default.
#: Looked up by id alone, so it serves BOTH a one-time effect
#: (``stone_thrower_sync``) and a persistent passive's one-time setup step
#: (``mortar_slow``'s D16 snapshot).
_ONE_TIME_HOOKS = {}


def set_one_time_hook(upgrade_id, fn):
    """Install (or clear, with ``fn=None``) the injected PICK-TIME side of an
    upgrade's effect — the seam for work this pure module may not do itself.

    See the module docstring for the full contract. Two intended callers, both
    installed by the host at boot: ``stone_thrower_sync`` (#9), whose whole
    effect is one-time, and ``mortar_slow`` (#3), a persistent passive that
    needs a one-time SNAPSHOT here (D16). The name says "one-time" because
    what it installs always runs exactly once per pick — not because the
    upgrade behind it has to be one of ``ONE_TIME_IDS``.
    """
    if fn is None:
        _ONE_TIME_HOOKS.pop(upgrade_id, None)
    else:
        _ONE_TIME_HOOKS[upgrade_id] = fn


def milestone_index(boss_num):
    """Which of the 4 authored milestones a boss fight maps to (D1).

    ``boss_num`` is 1-BASED (boss 1 is the first), so boss 1-4 walk milestones
    0-3 and boss 5 repeats milestone 0 verbatim, forever.
    """
    return (boss_num - 1) % 4


def _milestone(boss_upgrades_balance, boss_num):
    """The raw milestone row for ``boss_num``, or ``None`` when no balance is
    loaded (the ``timeline_level_for`` tolerance — see the module docstring)."""
    if boss_upgrades_balance is None:
        return None
    milestones = boss_upgrades_balance["BossUpgrades"]["Timeline"]["milestones"]
    return milestones[milestone_index(boss_num)]


def milestone_slots(boss_upgrades_balance, boss_num):
    """The 3 catalog upgrade ids this boss fight offers (a slot may be
    ``None`` — an empty, still-persisted slot).

    Always 3 entries (D2): ``[None, None, None]`` when no balance is loaded.
    """
    milestone = _milestone(boss_upgrades_balance, boss_num)
    if milestone is None:
        return [None, None, None]
    return list(milestone["slots"])


def retaliation_love(boss_upgrades_balance, boss_num):
    """The love a LOSS against this boss pays back (D7) — the 4-cycle table
    that replaced ``enemies.json``'s per-era ``loss_love_reward``. 0 when no
    balance is loaded."""
    milestone = _milestone(boss_upgrades_balance, boss_num)
    if milestone is None:
        return 0
    return milestone["retaliation_bonus_love"]


def stack_count(state, upgrade_id):
    """How many times ``upgrade_id`` has been picked this run — 0 = inactive.

    THE read accessor: every hook site reads its magnitude multiplier through
    this, never by indexing ``state.boss_upgrade_stacks`` itself.
    """
    return state.boss_upgrade_stacks.get(upgrade_id, 0)


def catalog_params(boss_upgrades_balance, upgrade_id):
    """The designer-authored ``params`` dict for one catalog upgrade.

    ``{}`` when no balance is loaded (the ``timeline_level_for`` tolerance) or
    the id carries no params — so a hook site's ``params.get(key, default)``
    always has something to read. THE param accessor: like ``stack_count``, no
    hook site walks ``["BossUpgrades"]["Catalog"]`` itself.
    """
    if boss_upgrades_balance is None:
        return {}
    catalog = boss_upgrades_balance["BossUpgrades"]["Catalog"]
    return catalog.get(upgrade_id, {}).get("params", {})


def hook_stacks(run_state, boss_upgrades_balance, upgrade_id):
    """``(stacks, params)`` for a BU-3 hook site's optional trailing pair.

    THE one call every hook site opens with (see the module docstring's
    threading-pattern section). Returns ``(0, {})`` — the "this hook is inert"
    answer — whenever the pair is absent (a pre-BU-3 caller, a headless test,
    a bare ``Session`` with no balance wired) or the upgrade has never been
    picked, so the branch a hook site writes is simply ``if n:``.
    """
    if run_state is None or boss_upgrades_balance is None:
        return 0, {}
    n = stack_count(run_state, upgrade_id)
    if n <= 0:
        return 0, {}
    return n, catalog_params(boss_upgrades_balance, upgrade_id)


def discounted(cost, run_state, boss_upgrades_balance, upgrade_id,
               param_key, default_pct, floor=0):
    """``cost`` after ``upgrade_id``'s ADDITIVE per-pick %-reduction (D4).

    The shared reducer behind the two price-cutting passives —
    ``wall_cost_discount`` (#2, ``floor=1``: never free, never negative) and
    ``tile_discount`` (#6, ``floor=0``). Picking an upgrade twice subtracts
    twice the percentage, which is what "stacks additively" means; the floor is
    what keeps a big enough stack from inverting the price.

    ``default_pct`` is the §2 default the shipped catalog seeds, used only if a
    designer has deleted the param key outright. Returns ``cost`` UNCHANGED
    whenever ``hook_stacks`` says the hook is inert.
    """
    n, params = hook_stacks(run_state, boss_upgrades_balance, upgrade_id)
    if not n:
        return cost
    pct = params.get(param_key, default_pct)
    return max(floor, int(cost * (1.0 - n * pct / 100.0)))


def _apply_restock_lives(state, upgrade_id, boss_upgrades_balance,
                         core_balance, tilemap, scene):
    """#1 — refill the hole to its full starting lives, from the SAME
    ``core.json`` key ``RunState.from_balance`` seeds a fresh run with."""
    state.base_lives = core_balance["TheHole"]["base_lives"]


def _apply_stone_thrower_sync(state, upgrade_id, boss_upgrades_balance,
                              core_balance, tilemap, scene):
    """#9 — level every placed stone thrower up to match the best one.

    Deliberately EMPTY here. The sweep walks ``Defender`` instances off the
    tilemap/scene and advances them through the normal free tier-advance path,
    which needs ``game.buildings`` — an import this module may never make. It
    arrives instead through ``set_one_time_hook("stone_thrower_sync", …)``,
    called by ``apply_pick`` right after this (see the module docstring's seam
    section). With no hook installed the pick is a harmless no-op that still
    counts its stack.
    """
    # TODO(BU-3): install the real sweep via set_one_time_hook from the host.


def _apply_tile_refund(state, upgrade_id, boss_upgrades_balance,
                       core_balance, tilemap, scene):
    """#12 — pay back every love spent unlocking tiles so far, through the
    existing clamped ``RunState.add_love``. The accumulator itself is filled at
    the unlock spend site (BU-3)."""
    state.add_love(state.love_spent_on_tiles)


#: The hardcoded ONE-TIME dispatch table (see ``ONE_TIME_IDS``). Every handler
#: takes the full ``apply_pick`` argument set so a later one-time effect can
#: reach whatever it needs without changing the call.
_ONE_TIME_EFFECTS = {
    "restock_lives": _apply_restock_lives,
    "stone_thrower_sync": _apply_stone_thrower_sync,
    "tile_refund": _apply_tile_refund,
}


def apply_pick(state, upgrade_id, boss_upgrades_balance, core_balance,
               tilemap=None, scene=None):
    """Record the player's boss-fight pick and fire its immediate effect.

    ALWAYS increments ``state.boss_upgrade_stacks[upgrade_id]`` — that single
    counter is the whole implementation for the nine persistent passives (D4:
    a repeat pick stacks additively at the hook site).

    For the three ``ONE_TIME_IDS`` it then runs the immediate effect: inline
    for ``restock_lives``/``tile_refund``, and via the injected
    ``set_one_time_hook`` callback for anything that needs ``game.buildings``
    knowledge (``stone_thrower_sync``). ``tilemap``/``scene`` default to
    ``None`` — a pick resolved without a world in hand skips the hook silently.

    **The hook lookup below is NOT gated on ``ONE_TIME_IDS``**, and that is
    load-bearing rather than incidental: it is what lets a PERSISTENT passive
    register a one-time pick-time setup step through the same seam
    (``mortar_slow``'s D16 snapshot — see the module docstring).
    """
    state.boss_upgrade_stacks[upgrade_id] = stack_count(state, upgrade_id) + 1

    effect = _ONE_TIME_EFFECTS.get(upgrade_id)
    if effect is not None:
        effect(state, upgrade_id, boss_upgrades_balance, core_balance,
               tilemap, scene)

    hook = _ONE_TIME_HOOKS.get(upgrade_id)
    if hook is not None and tilemap is not None and scene is not None:
        hook(state, tilemap, scene)
