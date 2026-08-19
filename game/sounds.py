"""game/sounds.py — SD-4: the GAME half of "which sound does this event play".

The pure half lives in `engine/audio/` (`bank.py` knows about slots, clips and
volume math; `sfx.py` owns the mixer). This module is the only place the words
``"placement"`` / ``"upgrade"`` / ``"buy_plot"`` and the ``SUBTREE`` family
lookup exist — `engine/` must never branch on a building-type string (D5,
layering). Same split as `vfx_variants.py` / `vfx_misc.py` against
`engine/vfx/`.

**Every play is exactly one call** to `engine.audio.play_slot(default_slot,
override_slot, bus=..., key=..., rng=...)`. This module computes the two slot
dicts and the key string and NOTHING else: it does not import pygame, does not
resolve file paths, does not own volume, and never calls `bank.resolve` itself
— the override->default->silence rule (§2.1) is the engine's, and re-deriving
"is this slot empty" here would be a second, drifting copy of it.

**Lifetime: built ONCE at boot (`game/main.py`, next to the balancing loads)
and never rebuilt or cleared** — not by `teardown_gameplay()`, not between
runs. `gp["sfx"]` is therefore non-None for the whole process, which is what
lets the main menu, Settings and the game-over screen click audibly before any
run exists. The object holds no run state: two balancing dicts, an RNG, and two
`id()`-keyed watcher caches that self-evict every frame (the
`FloaterManager.watch_enemies` pattern), so a torn-down world's ids drain on
the next run's first frame.

**Silence is a first-class outcome.** An unfilled slot, a missing balancing
node, a building with no ``SUBTREE``, a machine with no audio device — all are
a silent return, never a crash and never a log line. `play_slot` returning
False is the NORMAL answer here, not an error.
"""
import engine.audio as _engine_audio

#: the six building-event kinds, i.e. the leaf keys under both
#: `buildings.BuildingsGlobal.Sounds` and every family's `sounds` node.
BUILDING_KINDS = ("placement", "selection", "upgrade", "death", "attack",
                  "upkeep_boost")
#: the two map-event kinds under `map.Sounds`.
MAP_KINDS = ("buy_plot", "tile_placement")

# -- The key case is SPLIT, and that is INTENTIONAL, not a typo. -------------
# SD-1 shipped capital `Sounds` on the domain-global node
# (`buildings.BuildingsGlobal.Sounds.<kind>`), matching the group naming of
# every other `BuildingsGlobal` child, and lowercase `sounds` on each of the 12
# leaf families (`DefenceBuildings.BasicDefence.sounds.<kind>`), matching the
# leaf families' own field naming. `_family_sounds()` reads the LOWERCASE key;
# `_global_sounds()` reads the CAPITAL one. Do not "correct" either to match
# the other — the data would stop resolving.
_GLOBAL_NODE = "BuildingsGlobal"
_GLOBAL_KEY = "Sounds"   # capital: domain-global
_FAMILY_KEY = "sounds"   # lowercase: per-family override
_MAP_KEY = "Sounds"      # capital: map domain global


def _dict(value):
    """`value` when it is a dict, else `{}` — the one None-safety helper."""
    return value if isinstance(value, dict) else {}


class GameSounds:
    """Game-side sound dispatcher. One instance, process lifetime.

    `audio` is injected purely so tests can hand in a recorder; production
    always uses the `engine.audio` package. `rng` is threaded to
    `bank.pick_clip` for multi-clip slots (seed it in tests — the standing
    determinism rule).
    """

    def __init__(self, buildings_balance, map_balance, *,
                 audio=_engine_audio, rng=None):
        self._buildings = _dict(buildings_balance)
        self._map = _dict(map_balance)
        self._audio = audio
        self._rng = rng
        # id(building) -> last seen value; both self-evict in `watch()`.
        self._building_alive = {}
        self._attack_cooldowns = {}

    # -- slot lookup --------------------------------------------------------

    def _global_sounds(self):
        """The `buildings.BuildingsGlobal.Sounds` node (CAPITAL key)."""
        return _dict(_dict(self._buildings.get(_GLOBAL_NODE)).get(_GLOBAL_KEY))

    def _family_sounds(self, building):
        """The building family's `sounds` node (LOWERCASE key) — `{}` when the
        building has no ``SUBTREE``, the path does not resolve, or the family
        carries no sounds node. THE single place the per-family JSON shape is
        known."""
        node = self._buildings
        for key in getattr(building, "SUBTREE", ()) or ():
            node = _dict(node).get(key)
            if node is None:
                return {}
        return _dict(_dict(node).get(_FAMILY_KEY))

    # -- the one play seam --------------------------------------------------

    def _play(self, default_slot, override_slot, key):
        """One `play_slot` call, degrade-never-raise (the `FloaterManager._play`
        contract). Returns the engine's bool; False is normal."""
        try:
            return bool(self._audio.play_slot(
                default_slot, override_slot, bus="sfx", key=key,
                rng=self._rng))
        except Exception:       # a sound must never take down the frame
            return False

    def play_building_event(self, kind, building=None):
        """One of `BUILDING_KINDS`, resolved family-override -> global default
        -> silence BY THE ENGINE. Also the `BuildingUI.on_sound` callback."""
        if kind not in BUILDING_KINDS:
            return False
        return self._play(self._global_sounds().get(kind),
                          self._family_sounds(building).get(kind),
                          "buildings.%s.%s.%s" % (_GLOBAL_NODE, _GLOBAL_KEY,
                                                  kind))

    def play_map_event(self, kind):
        """One of `MAP_KINDS`. The map domain has no per-element override
        layer, so the default is the only layer."""
        if kind not in MAP_KINDS:
            return False
        return self._play(_dict(self._map.get(_MAP_KEY)).get(kind), None,
                          "map.%s.%s" % (_MAP_KEY, kind))

    # -- per-frame watchers -------------------------------------------------

    def watch(self, scene):
        """Called every frame from the host, right after
        `FloaterManager.watch_enemies`. Two edge detectors in one sweep:

        - **death**: a non-base building whose ``alive`` flipped True->False
          this frame (mirrors `FloaterManager.watch_buildings`).
        - **attack**: an `Attacker.cooldown` that RESET (grew) since last
          frame — the same cadence detector `watch_enemies` uses for enemies.
          The shot seam `resolve_combat(on_defender_fire=...)` carries only
          ``(wx, wy)`` — no shooter, hence no family — and is deliberately NOT
          widened, so the watcher is what yields the building OBJECT the
          per-family override needs.

        No extra rate limit lives here: SD-2's per-slot cooldown and
        max-concurrent cap, bucketed by the `key=` string, are what keep a wipe
        or a firing line from turning to mud.
        """
        from game.buildings.components import Attacker

        seen = set()
        for b in scene.by_tag("building"):
            key = id(b)
            seen.add(key)
            if getattr(b, "building_type", None) != "base":
                alive = bool(getattr(b, "alive", True))
                was_alive = self._building_alive.get(key, True)
                self._building_alive[key] = alive
                if was_alive and not alive:
                    self.play_building_event("death", b)
            get = getattr(b, "get_component", None)
            at = get(Attacker) if get is not None else None
            if at is None:
                continue
            last = self._attack_cooldowns.get(key)
            self._attack_cooldowns[key] = at.cooldown
            if last is not None and at.cooldown > last:
                self.play_building_event("attack", b)
        # drop stale ids so a long run (or a torn-down world) can't grow these
        # unbounded — the `watch_enemies` eviction, and the reason the object
        # can safely outlive a run.
        if len(self._building_alive) > 2 * len(seen) + 16:
            self._building_alive = {k: v for k, v in
                                    self._building_alive.items() if k in seen}
        if len(self._attack_cooldowns) > 2 * len(seen) + 16:
            self._attack_cooldowns = {k: v for k, v in
                                      self._attack_cooldowns.items()
                                      if k in seen}

    # -- payday -------------------------------------------------------------

    def payday(self, state, tilemap):
        """Called on the INCOME phase edge, right after
        `FloaterManager.begin_payout`. Plays `upkeep_boost` **at most once per
        distinct building family per payday**, in first-seen ledger order —
        never once per building.

        The two ledgers are read from the HOST side, by coordinate: the
        `"upkeep"`-tagged rows of ``state.income_events``
        (``(col, row, amount, tag)``) and every row of ``state.boost_events``
        (``(col, row, text)``). Nothing is added inside `game/core/payday.py`
        — its ordering is prototype-exact and sacrosanct.

        "Family" here is the building's full ``SUBTREE`` tuple, i.e. the same
        node `_family_sounds` overrides from — deduping any coarser would make
        two leaf families with different override clips share one play.
        """
        rows = []
        for ev in getattr(state, "income_events", None) or ():
            if len(ev) >= 4 and ev[3] == "upkeep":
                rows.append((ev[0], ev[1]))
        for ev in getattr(state, "boost_events", None) or ():
            if len(ev) >= 2:
                rows.append((ev[0], ev[1]))
        get = getattr(tilemap, "get", None)
        if get is None:
            return
        played = set()
        for col, row in rows:
            b = getattr(get(col, row), "occupant", None)
            if b is None:
                continue
            family = tuple(getattr(b, "SUBTREE", ()) or ())
            if family in played:
                continue
            played.add(family)
            self.play_building_event("upkeep_boost", b)
