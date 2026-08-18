"""Runtime persistence of the three audio volumes (SD-6).

Volumes are a **per-machine preference**, not designer content, so — exactly
like ``highscores.py`` — the document does NOT live in ``data/``: it is written
to the gitignored ``settings/`` directory at the repo root, while its schema
stays in ``data/schemas/``. The write still goes through
``engine.data_io.write_validated`` (D-3: one write path, canonical formatting).

**Reads never raise.** A missing, unreadable or schema-invalid file returns the
defaults (one logged warning if a file was actually there) — a corrupt
preference file must never stop the game booting. Writes DO raise on invalid
data (D-2).
"""
import logging
from pathlib import Path

from engine import data_io

#: The volume keys, in slider order. Master applies to both buses.
KEYS = ("master", "music", "sfx")

#: The shipped level for each key when nothing has been persisted yet — the
#: same 0.8 ``SessionSettings`` carries as its bare-construction fallback.
DEFAULT_LEVEL = 0.8

_log = logging.getLogger(__name__)


def _schema_path(data_dir):
    return Path(data_dir) / "schemas" / "audio_settings.schema.json"


def defaults():
    """A fresh document at the shipped levels."""
    return {key: DEFAULT_LEVEL for key in KEYS}


def default_path(repo_root):
    """The canonical preferences file: ``<repo_root>/settings/audio.json``."""
    return Path(repo_root) / "settings" / "audio.json"


def load(path, data_dir):
    """Load and validate the audio document at ``path``. Never raises."""
    path = Path(path)
    if not path.exists():
        return defaults()
    try:
        return data_io.load_validated(path, _schema_path(data_dir))
    except Exception as exc:                                   # noqa: BLE001
        _log.warning("could not load audio settings from %s (%s) — "
                     "falling back to the default levels", path, exc)
        return defaults()


def save(doc, path, data_dir):
    """Persist ``doc`` to ``path`` through the validating writer.

    Raises when ``doc`` is not schema-valid (a level outside 0..1, a missing
    or unknown key) — nothing is coerced defensively.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _schema_path(data_dir))
    return doc


def from_settings(settings):
    """The persisted document for a ``SessionSettings``-shaped object."""
    return {"master": float(settings.master_volume),
            "music": float(settings.music_volume),
            "sfx": float(settings.sfx_volume)}


def apply_to_settings(doc, settings):
    """Push a loaded document onto a ``SessionSettings``-shaped object."""
    settings.master_volume = float(doc["master"])
    settings.music_volume = float(doc["music"])
    settings.sfx_volume = float(doc["sfx"])
    return settings
