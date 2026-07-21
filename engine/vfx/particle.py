"""Stateful VFX objects (ESV-3a): a world anchor + a base-zoom pixel offset
integrated over time. Ported verbatim from ``game/ui/effects.py``'s
``_Particle``/``_GoldHighlight``/``_Slash`` (pre-ESV-3a) — only the
constants they used to read from module globals now arrive as constructor
arguments, sourced from ``engine.vfx.params`` dataclasses by the caller.

Pure Python — no pygame, no data/ access (D5).
"""


class Particle(object):
    """One spark/shard/muzzle mote: a world anchor + a base-zoom pixel
    offset integrated with velocity + gravity. ``ramp`` colours by age
    fraction; ``size`` is the base-zoom rect size."""

    __slots__ = ("wx", "wy", "ox", "oy", "vx", "vy", "gravity", "age", "life",
                 "ramp", "size")

    def __init__(self, wx, wy, vx, vy, gravity, life, ramp, size=(2, 2)):
        self.wx = wx
        self.wy = wy
        self.ox = 0.0
        self.oy = 0.0
        self.vx = vx
        self.vy = vy
        self.gravity = gravity
        self.age = 0.0
        self.life = life
        self.ramp = ramp
        self.size = size

    def step(self, dt):
        self.age += dt
        self.vy += self.gravity * dt
        self.ox += self.vx * dt
        self.oy += self.vy * dt

    def color(self):
        frac = min(0.999, self.age / self.life) if self.life else 0.999
        return self.ramp[int(frac * len(self.ramp))]


class GoldHighlight(object):
    """A fading gold diamond on a just-built / tier-advanced tile: fade in,
    hold, fade out. The fade-out duration is DERIVED (``life - fade_in -
    hold``), never stored — a fourth field here would let the three drift
    out of sum (see ``params.GoldParams``)."""

    __slots__ = ("col", "row", "age", "life", "fade_in", "hold")

    def __init__(self, col, row, life, fade_in, hold):
        self.col = col
        self.row = row
        self.age = 0.0
        self.life = life
        self.fade_in = fade_in
        self.hold = hold

    def frac(self):
        if self.age < self.fade_in:
            return self.age / self.fade_in
        if self.age < self.fade_in + self.hold:
            return 1.0
        out = self.life - self.fade_in - self.hold
        return max(0.0, 1.0 - (self.age - self.fade_in - self.hold) / out)


class Slash(object):
    """2-3 diagonal lines over a melee attacker: precomputed once at
    construction (the lines never move relative to the anchor)."""

    __slots__ = ("wx", "wy", "age", "life", "lines")

    def __init__(self, wx, wy, life, lines):
        self.wx = wx
        self.wy = wy
        self.age = 0.0
        self.life = life
        self.lines = lines
