"""Pure ``emit_*(rng, ...) -> objects`` functions (ESV-3a).

Every emitter takes an injected ``rng`` (``random.Random``-compatible:
``uniform``/``randint``/``random``/``choice``) as its first argument — never
the stdlib ``random`` module directly — so the byte-identity contract with
the pre-ESV-3a inline ``random.uniform(...)`` calls is testable with a seeded
``random.Random``.

**Draw order is behaviour** (ported verbatim from ``game/ui/effects.py``):
reproducing the wrong sequence or count of RNG calls per particle changes the
visual character even though every individual call is "correct". Each
function's docstring states its draw order; do not reorder without checking
the ESV-3a brief's table first.

Pure Python — no pygame, no data/ access (D5).
"""
from .particle import GoldHighlight, Particle, Slash


def emit_burst(rng, wx, wy, params):
    """``params.count`` particles from ``(wx, wy)``. Draw order per particle:
    ``uniform(vx)``, ``uniform(vy)`` — 2 calls."""
    particles = []
    for _ in range(params.count):
        vx = rng.uniform(params.vx_min, params.vx_max)
        vy = rng.uniform(params.vy_min, params.vy_max)
        particles.append(Particle(
            wx, wy, vx, vy, params.gravity, params.life, params.ramp,
            size=(params.size_w, params.size_h)))
    return particles


def emit_shards(rng, wx, wy, params):
    """``params.count`` building-death shards from ``(wx, wy)``. Draw order
    per particle: ``uniform(vx)``, ``uniform(vy)``, ``choice(colors)``,
    ``randint(size_w)``, ``randint(size_h)`` — 5 calls. Each shard's ramp is
    a 1-tuple of its own picked colour, held for its whole life (NOT a
    3-stop age ramp like a spark burst)."""
    particles = []
    for _ in range(params.count):
        vx = rng.uniform(params.vx_min, params.vx_max)
        vy = rng.uniform(params.vy_min, params.vy_max)
        color = rng.choice(params.colors)
        size_w = rng.randint(params.size_w_min, params.size_w_max)
        size_h = rng.randint(params.size_h_min, params.size_h_max)
        particles.append(Particle(
            wx, wy, vx, vy, params.gravity, params.life, (color,),
            size=(size_w, size_h)))
    return particles


def emit_muzzle(rng, wx, wy, params, strong=False):
    """``params.count``/``count_strong`` muzzle motes from ``(wx, wy)``.
    Draw order per particle: ``random()`` (the smoke roll), ``uniform(vx)``,
    ``uniform(vy)`` — 3 calls, the smoke roll FIRST. A particle that rolls
    smoke (``random() < params.smoke_chance``) gets a 1-tuple
    ``(params.smoke_color,)`` ramp instead of the 3-stop ``params.ramp``."""
    life = params.life_strong if strong else params.life
    count = params.count_strong if strong else params.count
    particles = []
    for _ in range(count):
        smoke = rng.random() < params.smoke_chance
        vx = rng.uniform(params.vx_min, params.vx_max)
        vy = rng.uniform(params.vy_min, params.vy_max)
        ramp = (params.smoke_color,) if smoke else params.ramp
        particles.append(Particle(
            wx, wy, vx, vy, params.gravity, life, ramp,
            size=(params.size_w, params.size_h)))
    return particles


def emit_slash(rng, wx, wy, large, params):
    """One melee slash at ``(wx, wy)``: ``randint(lines)`` once, then per
    line ``uniform(ox)``, ``uniform(oy)``, ``choice(colors)``. ``large``
    swaps in ``params.size_large`` for ``params.size``."""
    size = params.size_large if large else params.size
    lines = []
    for _ in range(rng.randint(params.lines_min, params.lines_max)):
        ox = rng.uniform(params.ox_min, params.ox_max)
        oy = rng.uniform(params.oy_min, params.oy_max)
        lines.append((ox - size, oy - size, ox + size, oy + size,
                     rng.choice(params.colors)))
    return Slash(wx, wy, params.life, lines)


def emit_gold(col, row, params):
    """A gold tile highlight at ``(col, row)``. No RNG draw."""
    return GoldHighlight(col, row, params.life, params.fade_in, params.hold)
