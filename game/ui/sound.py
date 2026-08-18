"""UI sound seam (SD-6) — pure, host-injected sink.

``game/ui`` is pygame-free (a source-scan ``TestPurity`` enforces it), and
``engine.audio`` imports pygame, so this module **never** imports it. Instead
the host injects a *sink* at boot — the same pattern
``widgets.set_skin_hit_test`` already uses one file over.

The sink receives a **slot dict** (``{"clips": [...], "loop": ..., "pick":
...}``) and a bus name, never a resolved clip: picking and playback belong to
``engine/audio`` and to the game-side dispatcher behind the injected adapter in
``game/main.py``, which is the only module allowed to touch either.

Every entry point is a **no-op** when no sink is installed or the named slot is
missing/empty, so ``tools/smoke.py``, every headless test and every bare screen
construction stay silent and crash-free.
"""

#: Host-injected ``fn(slot_dict, bus) -> None``. ``None`` = silent (default).
_sink = None
#: ``ui_balance["Sounds"]`` (SD-1's subtree), or ``{}`` when unconfigured.
_sounds = {}

#: The bus every UI sound rides on.
SFX_BUS = "sfx"


def set_sink(fn):
    """Install the host's playback adapter (``None`` restores silence)."""
    global _sink
    _sink = fn


def configure(ui_sounds):
    """Bind the ``ui`` balancing ``Sounds`` subtree (``None`` = silence)."""
    global _sounds
    _sounds = dict(ui_sounds or {})


def reset():
    """Drop both the sink and the slot table (test hygiene)."""
    global _sink, _sounds
    _sink = None
    _sounds = {}


def _emit(slot, bus):
    """Hand one slot to the sink, if there is one and the slot has clips."""
    if _sink is None or not slot or not slot.get("clips"):
        return False
    _sink(slot, bus)
    return True


def clip_slot(ref):
    """Wrap ONE clip reference (a path relative to ``data/audio/``) as a
    single-clip slot — the shape a per-widget ``sound`` override plays."""
    return {"clips": [{"file": ref, "volume": 1.0, "start": 0.0, "end": 0.0}],
            "loop": False, "pick": "random"}


def play_slot(name, bus=SFX_BUS):
    """Play the named ``ui.Sounds`` slot. Missing/empty slot = no-op."""
    return _emit(_sounds.get(name), bus)


def play_click(widget=None):
    """The button-click sound for ``widget``.

    A widget carrying a non-empty ``sound`` override (a clip path relative to
    ``data/audio/``, threaded onto the widget by ``ScreenSkinning.apply``'s
    generic setattr loop) plays THAT clip; everything else plays
    ``ui.Sounds.button_click``.
    """
    ref = getattr(widget, "sound", None) if widget is not None else None
    if ref:
        return _emit(clip_slot(ref), SFX_BUS)
    return play_slot("button_click")


def play_not_enough_love():
    """The refused-purchase sound (the ``NOT ENOUGH LOVE`` flash's twin)."""
    return play_slot("not_enough_love")
