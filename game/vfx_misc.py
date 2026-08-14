"""vfx_misc — the "misc value" provider registry for VFX variant selection
(VfxAuthoringPLAN VA-2).

A trigger row in ``data/balancing/vfx.json`` can set
``variant_select.mode = "misc"`` and name a ``misc_key``. That key means
nothing on its own: THIS module is where gameplay code later says what it
reads.

    from game import vfx_misc
    vfx_misc.register("weather", lambda: world.weather_index)

Nothing registers a provider today, and that is the point — the designer can
author the key in the editor before the code that feeds it exists. An
unregistered key resolves to 0 (variant 0), so an authored-but-unwired key is
a visible-but-harmless "it always plays the first variant", never a crash and
never a schema migration when the code does arrive.

Deliberately module-level state rather than a member of ``FloaterManager``:
the registrant is gameplay code that has no reference to the FX manager, and a
provider is a property of the RUN, not of one manager instance. ``clear()``
exists so tests do not leak registrations into each other.
"""

_PROVIDERS = {}


def register(key, provider):
    """Bind ``key`` to a zero-argument callable returning an int variant
    index. Re-registering a key replaces it (a run that re-enters setup must
    not stack duplicates). An empty key is refused — ``""`` is what every
    trigger row ships with, meaning "no misc value", and letting it be
    registered would silently turn every un-configured misc row live."""
    if not key:
        raise ValueError("misc provider key must be a non-empty string")
    if not callable(provider):
        raise TypeError(f"provider for {key!r} is not callable")
    _PROVIDERS[key] = provider


def unregister(key):
    """Drop ``key``'s provider if present; a no-op when it is not."""
    _PROVIDERS.pop(key, None)


def clear():
    """Drop every provider (test hygiene / a new run)."""
    _PROVIDERS.clear()


def registered():
    """The bound keys, sorted — for the editor's misc-key completion and for
    tests. Never the live dict, which a caller could mutate behind us."""
    return tuple(sorted(_PROVIDERS))


def resolve(key):
    """``key``'s current int value, or 0.

    Zero is the answer for every failure mode — unregistered key, empty key,
    a provider that raises, a provider returning something non-integer — and
    none of them raise. This is a COSMETIC lever: a bad provider must pick the
    first variant, not take down the frame it was consulted in (E-37, and the
    same argument ``spawn_play_once`` returning None makes for missing art).
    """
    provider = _PROVIDERS.get(key)
    if provider is None:
        return 0
    try:
        return int(provider())
    except Exception:
        return 0
