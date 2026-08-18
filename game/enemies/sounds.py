"""game.enemies.sounds — the ONE audio dispatch seam for this package (SD-5).

Four call sites in `game/enemies/` (the death sweep, the two `EnemyCombat`
attack branches, the Digger eruption, and the spawner's wave pop) reach the
mixer only through `play_enemy_sound` below. No file names, no `data/` I/O
and no pygame live in `game/` — this module hands SD-2's `engine.audio` a
pair of slot dicts and lets it do the rest.

**Slot layers.** The global default is `enemies.EnemySounds.<kind>`; the
per-type override is `enemies.EnemyTypes.<STAT_SUBTREE[0]>.sounds.<kind>`.
`clips: []` on the default means silence, `clips: []` on the override means
"inherit the default" — that rule is `engine.audio.bank.resolve`'s, not
ours, and is never re-derived here. (The case split — capital `EnemySounds`
for the globals, lowercase `sounds` under each type — is deliberate, SD-1's;
do not normalise it.)

**Why `STAT_SUBTREE`, never `ETYPE`/`REGISTRY_GROUP`** (D7): `STAT_SUBTREE`
IS the `EnemyTypes` key and already drives every other lookup on an enemy
(`enemy.py:110`). The registry label differs (`Standard -> "Walker"`,
`SiegeCannon -> "Siege Cannon"`, and Tutorial shares "Walker" with
Standard), and `ETYPE` is lowercase and differs again — see
`data/schemas/enemies.schema.json`'s own warning.

Every failure mode is silence, never an exception: an enemy with no
`_balance`, no `sounds` block, no clips, or a host where `sfx.init()` never
ran (SD-4's bootstrap absent, no audio device, `SDL_AUDIODRIVER=dummy`) all
degrade to a no-op. SD-2's per-key cooldown and max-concurrent cap are the
only throttle — a 40-enemy wipe calls `play_enemy_sound` forty times in one
loop on purpose and lets the engine clamp (plan §5).
"""
from engine.audio import bank

#: The `engine.audio.sfx` module, bound on FIRST PLAY, not at import.
#: `engine/audio/sfx.py` imports pygame at ITS module top (SD-2's
#: `patch.object(sfx, "pygame", …)` seam needs that), and `import
#: game.enemies` is pygame-free today — binding eagerly here would drag
#: pygame into every headless combat test through `game/enemies/__init__.py`.
#: `bank` above is SD-2's PURE module and is safe at module scope.
#: Tests monkeypatch this attribute directly (`game.enemies.sounds.sfx =
#: fake`); a non-None value is used as-is and no import ever happens.
sfx = None


def _sfx():
    global sfx
    if sfx is None:
        from engine.audio import sfx as _module

        sfx = _module
    return sfx


DEATH = "death"
ATTACK = "attack"
SPAWN = "spawn"

#: Global-default subtree for every enemy sound.
GLOBAL_KEY = "EnemySounds"
#: Per-type subtree holding the override blocks.
TYPES_KEY = "EnemyTypes"
OVERRIDE_KEY = "sounds"


def type_key(enemy):
    """The `EnemyTypes` key for a live enemy: its class's `STAT_SUBTREE[0]`.
    None when the class carries no subtree (a bare test double)."""
    subtree = getattr(type(enemy), "STAT_SUBTREE", None)
    if not subtree:
        return None
    return subtree[0]


def slot_for(enemy, kind):
    """PURE. The resolved slot dict for `enemy`'s `kind` sound, or None for
    silence. Reads the balancing dict already cached on every enemy
    (`Enemy._balance`, an E-11-legal transient) — no new plumbing, no new
    constructor argument, no host wiring."""
    balance = getattr(enemy, "_balance", None)
    if not isinstance(balance, dict):
        return None
    default_slot = (balance.get(GLOBAL_KEY) or {}).get(kind)
    key = type_key(enemy)
    override_slot = None
    if key is not None:
        block = (balance.get(TYPES_KEY) or {}).get(key) or {}
        override_slot = (block.get(OVERRIDE_KEY) or {}).get(kind)
    return bank.resolve(default_slot, override_slot)


def play_enemy_sound(enemy, kind, *, rng=None):
    """Fire `enemy`'s `kind` sound on the sfx bus. Returns True only when a
    clip actually started; False (never an exception) for every silence and
    every failure mode."""
    try:
        slot = slot_for(enemy, kind)
        if slot is None:
            return False
        # `key` is an opaque cooldown/concurrency bucket — the slot path, so
        # a 40-enemy wipe shares one bucket per (type, kind) and SD-2's cap
        # thins it. SD-5 adds no throttle of its own.
        bucket = "enemies.%s.%s" % (type_key(enemy) or GLOBAL_KEY, kind)
        return bool(_sfx().play_slot(slot, key=bucket, rng=rng))
    except Exception:
        return False
