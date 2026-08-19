"""Health (E-12): hit points as declared component state.

No gameplay constants here — max_hp/hp values come from the caller (game
code reading data/balancing/). ×10 combat scale is a data concern, not an
engine one.
"""
from .component import Component

# Monotonic per-tag death counters, bumped when a Health crosses from alive to
# dead inside `damage()`. Same shape, and the same reason, as gameobject.py's
# `_TAGS_EPOCH`: a poller that would otherwise sweep every object of a tag on
# EVERY frame just to catch the rare frame where one of them died can instead
# compare a single integer, and pay for the sweep only when it moved. Keyed by
# tag so an enemy dying does not un-gate a building poller.
_DEATH_EPOCHS = {}


def death_epoch(tag):
    """How many `Health.damage()` kills have been recorded for objects carrying
    ``tag``. Monotonic and process-global; a caller only ever compares it with a
    value it read earlier, so a bump from some other scene or session costs that
    caller one redundant sweep and can never hide a death from it.

    NOT a complete death record: it counts the ``damage()`` path only. Anything
    that zeroes ``hp`` by assignment (tests do; no game path does) leaves it
    untouched — so a caller that must not miss such a death keeps one ungated
    sweep on a cold path. See ``game/core/session.py::_award_building_deaths``.
    """
    return _DEATH_EPOCHS.get(tag, 0)


class Health(Component):
    max_hp: int = 1
    hp: int = 1

    def on_added(self, owner):
        """Owner seam (E-12): cached so `damage` can read the owner's tags when
        it kills it. Transient and non-authoritative, hence underscored."""
        self._owner = owner

    @property
    def is_dead(self):
        return self.hp <= 0

    def damage(self, amount):
        was_alive = self.hp > 0
        self.hp = max(0, self.hp - amount)
        if was_alive and self.hp <= 0:
            # Tags are read HERE, not at `on_added`: they are re-assignable at
            # runtime (game/enemies/kidnap.py retags a carrier mid-wave), so the
            # set that matters is the one the object carries as it dies.
            for tag in getattr(getattr(self, "_owner", None), "tags", ()):
                _DEATH_EPOCHS[tag] = _DEATH_EPOCHS.get(tag, 0) + 1

    def heal(self, amount):
        self.hp = min(self.max_hp, self.hp + amount)
