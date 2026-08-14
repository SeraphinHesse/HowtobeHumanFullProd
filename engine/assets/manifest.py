"""Manifest v2 — pure metadata core (E-35/E-36/E-37). No pygame.

Row semantics are PROTOTYPE-EXACT (behavioral spec:
../HowToBeHuman/ClaudePrototype/HowToBeHuman src/core/sprite_manifest.py):
rows = animations, row 0 = idle (required), per-row fps, hidden frames
dropped AFTER loop expansion, playback = pre-roll -> looped range x count
-> post-roll. Frame timing is a pure function of time (E-36); slicing the
actual pixels happens in engine.assets.store (pygame side).

Tolerance split: `load_manifest` never raises (E-37 — art problems log and
fall back to placeholders); committed manifests are still schema-validated
loudly by tools/smoke.py and every editor write (D-2).
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .types import PLACEHOLDER

log = logging.getLogger(__name__)

IDLE = "idle"

# ESV-1: the six declared anchor names (asset_manifest.schema.json), all
# optional. Fixed order so a parsed entry's `anchors` tuple is deterministic
# regardless of the raw dict's key order.
ANCHOR_NAMES = (
    "muzzle", "impact", "hp_bar", "floater_origin", "status_icon",
    "beam_endpoint",
)


def playback_order(num_frames, hidden=(), loop=None):
    """Ordered frame columns to play for one row (prototype-exact).

    `loop` is None or (loop_start, loop_end, loop_count): frames before
    loop_start play once, loop_start..loop_end (inclusive) repeat
    loop_count times, then loop_end+1..end play once. Hidden indices are
    dropped from the result (after loop expansion)."""
    hidden = set(hidden or [])
    if loop:
        ls, le, lc = loop
        ls = max(0, int(ls))
        le = min(num_frames - 1, int(le))
        lc = max(1, int(lc))
        if ls <= le:
            order = (list(range(0, ls))
                     + list(range(ls, le + 1)) * lc
                     + list(range(le + 1, num_frames)))
        else:
            order = list(range(num_frames))
    else:
        order = list(range(num_frames))
    return [i for i in order if i not in hidden and 0 <= i < num_frames]


def parse_loop(row):
    """(start, end, count) when the row declares a real loop, else None.
    A loop is active only when start and end are both present, count > 1,
    and 0 <= start <= end (prototype `_row_loop` gate)."""
    if "loop_start" not in row or "loop_end" not in row:
        return None
    try:
        ls = int(row["loop_start"])
        le = int(row["loop_end"])
        lc = int(row.get("loop_count", 1))
    except (TypeError, ValueError):
        return None
    if lc > 1 and 0 <= ls <= le:
        return (ls, le, lc)
    return None


@dataclass(frozen=True)
class Track:
    """One playable animation: sheet row band + expanded (col, dur_ms) timeline."""
    row: int
    timeline: tuple
    total_ms: int


@dataclass(frozen=True)
class ManifestEntry:
    slot_key: str
    sheet: str
    frame_w: int
    frame_h: int
    offset_x: int
    offset_y: int
    animations: dict  # {name: Track}, insertion order = row order
    slice: tuple = None   # (left, top, right, bottom) frame-px, or None
    anchors: tuple = None  # ((name, (x, y)), ...) declared-name order, or None
    # Optional per-slot render hint (like `slice`, uninterpreted here): the
    # consumer may draw its own legacy/diagnostic overlay UNDER this art
    # instead of letting the sprite stand alone. Only the game's tile-condition
    # art reads it today; omitted ⇒ False ⇒ byte-identical entry.
    tint_overlay: bool = False
    # First sheet row of this entry's WINDOW (0-based). Lets many slots cut
    # their own row band out of one shared master spritesheet. It is a SLICING
    # concern only: `animations`/`Track.row`/`current_frame` keep meaning
    # "row i of THIS entry's rows[]", and `AssetStore._frame_surface` is the
    # single place the window is applied. Omitted ⇒ 0 ⇒ byte-identical entry.
    row_start: int = 0

    def anchor(self, name):
        """(x, y) frame-px anchor point named `name` (ESV-1), or None when
        there is no `anchors` block or that name was not authored."""
        if self.anchors is None:
            return None
        for n, xy in self.anchors:
            if n == name:
                return xy
        return None


def entry_from_dict(slot_key, raw):
    """Parse one manifest-v2 entry dict. Raises ValueError on anything
    unusable — `load_manifest` is the tolerance layer that catches it."""
    if not isinstance(raw, dict):
        raise ValueError(f"{slot_key}: entry is not an object")
    try:
        sheet = raw["sheet"]
        frame_w = int(raw["frame_w"])
        frame_h = int(raw["frame_h"])
        rows = raw["rows"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{slot_key}: missing/invalid entry field ({exc})")
    if not isinstance(sheet, str) or not sheet:
        raise ValueError(f"{slot_key}: sheet must be a non-empty string")
    if frame_w < 1 or frame_h < 1:
        raise ValueError(f"{slot_key}: frame size must be positive")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{slot_key}: rows must be a non-empty list")

    animations = {}
    for row_idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"{slot_key}: row {row_idx} is not an object")
        animation = str(row.get("animation", IDLE))
        if row_idx == 0 and animation != IDLE:
            raise ValueError(f"{slot_key}: row 0 must be '{IDLE}' (E-35)")
        try:
            num_frames = int(row["frames"])
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"{slot_key}: row {row_idx} has no frame count")
        if num_frames < 1:
            raise ValueError(f"{slot_key}: row {row_idx} frame count < 1")
        try:
            fps = float(row.get("fps", 8)) or 8.0
        except (TypeError, ValueError):
            fps = 8.0
        dur = max(1, int(round(1000.0 / fps)))
        order = playback_order(num_frames, row.get("hidden") or [], parse_loop(row))
        if not order:  # all frames hidden — animation not playable (prototype drops it)
            continue
        timeline = tuple((col, dur) for col in order)
        animations[animation] = Track(
            row=row_idx, timeline=timeline, total_ms=dur * len(timeline))
    if not animations:
        raise ValueError(f"{slot_key}: no visible frames in any row")

    margins = raw.get("slice")
    if margins is not None:
        # a JSON array, never a bare string: "1234" would otherwise iterate into
        # four perfectly valid-looking margins
        if not isinstance(margins, (list, tuple)):
            raise ValueError(f"{slot_key}: slice must be 4 integers")
        try:
            margins = tuple(int(v) for v in margins)
        except (TypeError, ValueError):
            raise ValueError(f"{slot_key}: slice must be 4 integers")
        if len(margins) != 4 or any(v < 0 for v in margins):
            raise ValueError(
                f"{slot_key}: slice must be [left, top, right, bottom], all >= 0")

    raw_anchors = raw.get("anchors")
    anchors = None
    if raw_anchors is not None:
        # a JSON object, never a bare string/array: same defensive shape as
        # `slice` above — a bare "12" would otherwise iterate into two
        # perfectly valid-looking ints.
        if not isinstance(raw_anchors, dict):
            raise ValueError(f"{slot_key}: anchors must be an object")
        unknown = set(raw_anchors) - set(ANCHOR_NAMES)
        if unknown:
            raise ValueError(
                f"{slot_key}: unknown anchor name(s) {sorted(unknown)}")
        parsed = []
        for name in ANCHOR_NAMES:
            if name not in raw_anchors:
                continue
            xy = raw_anchors[name]
            if not isinstance(xy, (list, tuple)):
                raise ValueError(f"{slot_key}: anchors.{name} must be 2 integers")
            try:
                xy = tuple(int(v) for v in xy)
            except (TypeError, ValueError):
                raise ValueError(f"{slot_key}: anchors.{name} must be 2 integers")
            if len(xy) != 2:
                raise ValueError(f"{slot_key}: anchors.{name} must be [x, y]")
            parsed.append((name, xy))
        anchors = tuple(parsed) if parsed else None

    tint_overlay = raw.get("tint_overlay", False)
    if not isinstance(tint_overlay, bool):
        raise ValueError(f"{slot_key}: tint_overlay must be a boolean")

    row_start = raw.get("row_start", 0)
    # Same defensive shape as `slice`/`anchors`: no int() coercion, because
    # True, 3.7 and "3" would all sail through it and silently pick a row the
    # designer never authored. `load_manifest` is the E-37 layer that turns
    # this raise into warn-and-skip-this-entry.
    if isinstance(row_start, bool) or not isinstance(row_start, int):
        raise ValueError(f"{slot_key}: row_start must be an integer")
    if row_start < 0:
        raise ValueError(f"{slot_key}: row_start must be >= 0")

    return ManifestEntry(
        slot_key=slot_key,
        sheet=sheet,
        frame_w=frame_w,
        frame_h=frame_h,
        offset_x=int(raw.get("offset_x", 0)),
        offset_y=int(raw.get("offset_y", 0)),
        animations=animations,
        slice=margins,
        anchors=anchors,
        tint_overlay=tint_overlay,
        row_start=row_start,
    )


class Manifest:
    """Immutable slot -> ManifestEntry mapping with pure time lookup."""

    def __init__(self, entries=None):
        self._entries = dict(entries or {})

    def entry(self, slot_key):
        return self._entries.get(slot_key)

    def slots(self):
        return tuple(self._entries)

    def override(self, slot_key, entry):
        """Copy-with: `entry` replaces the slot's entry (None removes it).
        Used by the editor for live unsaved-draft previews."""
        entries = dict(self._entries)
        if entry is None:
            entries.pop(slot_key, None)
        else:
            entries[slot_key] = entry
        return Manifest(entries)

    def animation_ms(self, slot_key, name):
        """The named animation's total playback duration in ms, or ``None`` when
        the slot or that animation is absent. Unlike ``current_frame`` this does
        NOT fall back to idle — a missing row means the caller has no such
        animation (e.g. no ``death`` track ⇒ despawn instantly, don't linger)."""
        entry = self._entries.get(slot_key)
        if entry is None:
            return None
        track = entry.animations.get(name)
        return track.total_ms if track is not None else None

    def current_frame(self, slot_key, animation, time_ms, phase_ms=0,
                       extra_hidden=None):
        """(sheet_row, sheet_col) for a slot/animation at a time — pure
        function of time (E-36). Missing animation falls back to idle;
        missing slot (or no usable idle) returns PLACEHOLDER.

        `extra_hidden` (optional, a caller-supplied set/iterable of frame
        COLUMN indices) filters the track's own already-baked timeline
        further — a per-CALLER narrowing, never a widening: a column the
        manifest row already hid stays hidden regardless. If filtering would
        drop every frame, the unfiltered timeline is used instead (never
        draws nothing)."""
        entry = self._entries.get(slot_key)
        if entry is None:
            return PLACEHOLDER
        track = entry.animations.get(animation)
        if track is None:
            track = entry.animations.get(IDLE)
        if track is None:
            return PLACEHOLDER
        timeline, total_ms = track.timeline, track.total_ms
        if extra_hidden:
            hidden = set(extra_hidden)
            filtered = tuple((col, dur) for col, dur in timeline
                             if col not in hidden)
            if filtered:
                timeline = filtered
                total_ms = sum(dur for _col, dur in filtered)
        if len(timeline) == 1:
            return (track.row, timeline[0][0])
        elapsed = (int(time_ms) + int(phase_ms)) % total_ms
        acc = 0
        for col, dur in timeline:
            acc += dur
            if elapsed < acc:
                return (track.row, col)
        return (track.row, timeline[-1][0])


def load_manifest(path):
    """Read data/sprites/asset_manifest.json into a Manifest. NEVER raises
    (E-37): absent file -> empty manifest (normal pre-import state); parse
    or shape errors -> warn + empty; a bad entry -> warn + skip that entry."""
    path = Path(path)
    if not path.exists():
        return Manifest()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read manifest %s: %s — using placeholders", path, exc)
        return Manifest()
    if not isinstance(doc, dict) or doc.get("version") != 2 \
            or not isinstance(doc.get("entries"), dict):
        log.warning("manifest %s is not a version-2 manifest — using placeholders", path)
        return Manifest()
    entries = {}
    for slot_key, raw in doc["entries"].items():
        try:
            entries[slot_key] = entry_from_dict(slot_key, raw)
        except ValueError as exc:
            log.warning("manifest entry skipped: %s", exc)
    return Manifest(entries)
