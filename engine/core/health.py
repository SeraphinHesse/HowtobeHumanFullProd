"""Health (E-12): hit points as declared component state.

No gameplay constants here — max_hp/hp values come from the caller (game
code reading data/balancing/). ×10 combat scale is a data concern, not an
engine one.
"""
from .component import Component


class Health(Component):
    max_hp: int = 1
    hp: int = 1

    @property
    def is_dead(self):
        return self.hp <= 0

    def damage(self, amount):
        self.hp = max(0, self.hp - amount)

    def heal(self, amount):
        self.hp = min(self.max_hp, self.hp + amount)
