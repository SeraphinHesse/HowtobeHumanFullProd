"""engine.audio.bank — PURE slot/clip resolution logic (SD-2).

No pygame, no module-level globals, no filesystem access. Every random
choice takes an injected ``rng`` (the ``engine/vfx/emitters.py`` rule —
``engine/CLAUDE.md:219-234``) so this module is deterministic under test.

A **slot** is ``{"clips": [...], "loop": bool, "pick": "random"|"sequential"}``
and a **clip** is ``{"file": str, "volume": float, "start": float, "end":
float}`` — see ``planning/SoundEditorPLAN.md`` §2.1/§2.2. ``end == 0.0`` is
the "play to the end" sentinel, never ``None``. No game vocabulary lives
here: this module never learns a slot *path*, a balancing key name, or any
element/building/enemy name — it only ever sees the slot/clip dicts
themselves.
"""
from pathlib import Path

EMPTY_CLIP = {"file": "", "volume": 1.0, "start": 0.0, "end": 0.0}
EMPTY_SLOT = {"clips": [], "loop": False, "pick": "random"}
BUSES = ("music", "sfx")


def slot_is_empty(slot):
    """True for None, {}, or a slot whose `clips` list is empty or holds
    only entries with a falsy `file`."""
    if not slot:
        return True
    clips = slot.get("clips") or []
    return not any(c.get("file") for c in clips if isinstance(c, dict))


def resolve(default_slot, override_slot=None):
    """Non-empty override wins; else non-empty default; else None (silence).
    Never mutates either argument, never merges them field-by-field — a slot
    is an all-or-nothing unit."""
    if not slot_is_empty(override_slot):
        return override_slot
    if not slot_is_empty(default_slot):
        return default_slot
    return None


def pick_clip(slot, rng=None, *, counter=0):
    """None for an empty slot. Single clip -> that clip. Otherwise
    slot["pick"] == "sequential" -> clips[counter % len(clips)];
    "random" (or anything else) -> rng.choice(clips) with an injected
    random.Random-compatible rng. rng=None with >1 clip returns clips[0]."""
    if slot_is_empty(slot):
        return None
    clips = [c for c in slot.get("clips") or [] if isinstance(c, dict) and c.get("file")]
    if not clips:
        return None
    if len(clips) == 1:
        return clips[0]
    if slot.get("pick") == "sequential":
        return clips[counter % len(clips)]
    if rng is None:
        return clips[0]
    return rng.choice(clips)


def effective_volume(clip, bus_volume=1.0, master=1.0):
    """master * bus_volume * clip["volume"], clamped to [0.0, 1.0]; a
    missing or non-numeric clip volume reads as 1.0."""
    try:
        clip_vol = float(clip.get("volume", 1.0))
    except (TypeError, ValueError):
        clip_vol = 1.0
    v = master * bus_volume * clip_vol
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def clip_path(audio_root, clip):
    """Path(audio_root) / clip["file"]; None for an empty/absent file. Does
    not touch the filesystem."""
    if not clip:
        return None
    file = clip.get("file")
    if not file:
        return None
    return Path(audio_root) / file


def trim_bounds(clip):
    """(start_seconds, end_seconds_or_None) — the `end == 0.0` sentinel maps
    to None ("play to the end"); negative/inverted values normalise to
    (0.0, None)."""
    if not clip:
        return (0.0, None)
    try:
        start = float(clip.get("start", 0.0))
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(clip.get("end", 0.0))
    except (TypeError, ValueError):
        end = 0.0
    if start < 0.0:
        start = 0.0
    if end <= 0.0:
        return (start, None)
    if end <= start:
        return (0.0, None)
    return (start, end)
