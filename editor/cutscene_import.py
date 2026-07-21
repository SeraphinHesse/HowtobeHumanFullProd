"""Pure helpers for the Cutscenes panel (TU-3, D4) —
``data/video/cutscenes.json`` load/write + the video/audio import-copy flow.
Qt-free, pygame-free (the ``editor/asset_import.py`` sibling — in
``test_editor_viewport.TestPurity``'s import list): ``panels/cutscenes.py``
is the only caller.

Registry shape (TU-1): ``id -> {video, audio (nullable), length, trigger}``,
``trigger`` a closed enum (``intro``/``first_end_turn``). This module never
adds or removes an entry — TU-1 owns which ids exist.
"""
import shutil
from pathlib import Path

from engine import data_io

_REGISTRY_FILE = ("video", "cutscenes.json")
_SCHEMA_FILE = "cutscenes.schema.json"

# Display-order pin (the ordered_views()/VIEW_ORDER precedent,
# editor/ui_screen_session.py): data_io.dumps_deterministic sorts keys
# alphabetically, so iterating the doc directly would show the
# "first_end_turn" placeholder row before the seeded "intro" row. A future
# trigger (room to grow — boss, etc.) still displays, appended after these
# two, with no code change (see ordered_entry_ids).
TRIGGER_ORDER = ("intro", "first_end_turn")

# Fallback length-spinbox floor/ceiling used only when the schema declares
# no minimum/maximum for this key.
_FALLBACK_MIN_LENGTH = 0.1
_FALLBACK_MAX_LENGTH = 3600.0


def registry_path(data_dir):
    return Path(data_dir).joinpath(*_REGISTRY_FILE)


def schema_path(data_dir):
    return Path(data_dir) / "schemas" / _SCHEMA_FILE


def load_registry_doc(data_dir):
    """The raw registry doc, tolerant of a missing/corrupt file (E-37 —
    mirrors ``asset_import.load_manifest_doc``). Degrades to ``{}`` rather
    than raising, so the panel can show a placeholder instead of crashing
    out of a constructor/Qt slot."""
    path = registry_path(data_dir)
    try:
        doc = data_io.load_json(path)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict):
        return {}
    return doc


def write_registry_doc(data_dir, doc):
    """The ONE registry write path (ED-31, through the validating writer)."""
    data_dir = Path(data_dir)
    data_io.write_validated(doc, registry_path(data_dir), schema_path(data_dir))


def length_bounds(data_dir):
    """(minimum, maximum) for the ``length`` field, read from the schema
    itself (ED-30) so the panel's spinbox range can never accept an
    out-of-schema value. Falls back to a literal floor/ceiling only if the
    schema declares no bounds for this key."""
    schema = data_io.load_json(schema_path(data_dir))
    length_schema = schema["$defs"]["entry"]["properties"]["length"]
    lo = length_schema.get("minimum", _FALLBACK_MIN_LENGTH)
    hi = length_schema.get("maximum", _FALLBACK_MAX_LENGTH)
    return float(lo), float(hi)


def ordered_entry_ids(doc):
    """Entry ids in the pinned display order (TRIGGER_ORDER first, any
    later addition appended alphabetically after it)."""
    def sort_key(entry_id):
        if entry_id in TRIGGER_ORDER:
            return (TRIGGER_ORDER.index(entry_id), entry_id)
        return (len(TRIGGER_ORDER), entry_id)

    return tuple(sorted(doc.keys(), key=sort_key))


def video_dest(data_dir, cutscene_id, src_path):
    """``data/video/<cutscene_id><suffix>`` — the STEM is always the
    cutscene id, deterministic, never the source filename (the
    ``imported/<slot_key>.png`` rule)."""
    suffix = Path(src_path).suffix
    return Path(data_dir) / "video" / f"{cutscene_id}{suffix}"


def audio_dest(data_dir, cutscene_id, src_path):
    """``data/video/<cutscene_id>_audio<suffix>`` — same determinism rule
    as ``video_dest``, offset by the ``_audio`` marker so the two never
    collide."""
    suffix = Path(src_path).suffix
    return Path(data_dir) / "video" / f"{cutscene_id}_audio{suffix}"


def probe_length_seconds(path):
    """Best-effort video length via OpenCV. Lazy ``import cv2`` (absent ->
    None); every other failure mode (capture won't open, zero/invalid fps)
    also returns None rather than raising — mirrors ``engine/video.py``'s
    graceful-skip contract. A None probe must never block editing; the
    caller's manual spin-box stays authoritative."""
    try:
        import cv2
    except ImportError:
        return None
    try:
        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                return None
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not fps or fps <= 0:
                return None
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            return frame_count / fps
        finally:
            cap.release()
    except Exception:
        return None


def _copy_if_different(src_path, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if Path(src_path).resolve() != dest.resolve():
        shutil.copyfile(src_path, dest)


def import_video(data_dir, cutscene_id, src_path):
    """Copy ``src_path`` -> ``video_dest(...)`` (skip the copy when source
    and destination already resolve to the same file) and probe its
    length. Returns ``(relative_video_filename, length_or_None)`` — the
    caller (the panel) decides whether to overwrite the length field, since
    a failed probe must never clobber a value the designer already typed."""
    dest = video_dest(data_dir, cutscene_id, src_path)
    _copy_if_different(src_path, dest)
    length = probe_length_seconds(dest)
    return dest.name, length


def import_audio(data_dir, cutscene_id, src_path):
    """Copy ``src_path`` -> ``audio_dest(...)`` (ogg/mp3 passthrough, no
    transcoding). Returns the bare destination filename."""
    dest = audio_dest(data_dir, cutscene_id, src_path)
    _copy_if_different(src_path, dest)
    return dest.name


def clear_audio(data_dir, cutscene_id, doc):
    """Delete the file at the entry's current ``audio`` path if it exists
    (no refcount needed, unlike ``asset_import``'s sheet-sharing model — a
    cutscene's audio file is always 1:1-owned by its id) and return the doc
    with ``audio: None`` for that id. The caller (the panel) is what
    actually writes the doc back."""
    data_dir = Path(data_dir)
    entry = doc.get(cutscene_id)
    if isinstance(entry, dict):
        audio_name = entry.get("audio")
        if audio_name:
            path = data_dir / "video" / audio_name
            if path.exists():
                path.unlink()
        entry["audio"] = None
    return doc
