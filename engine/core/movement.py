"""Movement (E-12/E-30): waypoint-follow component.

Authoritative state lives in declared fields (JSON-safe). update(dt) reads the
owner's Transform, calls the pure ``engine.physics.movement.advance`` step,
and writes the new position back. ``arrived`` flags reaching the END of the
path (like the prototype's ``reached_base``); ``index`` tracks progress along
the way. Pure Python — no pygame.
"""
from engine.physics import movement as _movement

from .component import Component


class Movement(Component):
    waypoints: list = []          # list of [wx, wy] world-space waypoints
    speed: float = 1.0            # tiles per second
    index: int = 0               # waypoint currently pursued
    arrival_threshold: float = 0.06
    arrived: bool = False         # True once the final waypoint is reached

    def on_added(self, owner):
        self._owner = owner  # transient cache of the GameObject we belong to

    def update(self, dt):
        owner = getattr(self, "_owner", None)
        if owner is None or not self.waypoints or self.index >= len(self.waypoints):
            return
        transform = owner.transform
        new_pos, new_index, _arrived_step, reached_end = _movement.advance(
            (transform.wx, transform.wy),
            self.waypoints,
            self.index,
            self.speed,
            dt,
            self.arrival_threshold,
        )
        transform.wx, transform.wy = new_pos
        self.index = new_index
        if reached_end:
            self.arrived = True
