"""Runtime persistence of the render-backend preference (settings-cut).

The GPU/CPU switch on the settings screen is a **per-machine boot preference**,
not designer content, so — exactly like ``audio_settings.py`` and
``highscores.py`` — the document does NOT live in ``data/``: it is written to
the gitignored ``settings/`` directory at the repo root, while its schema stays
in ``data/schemas/``. The write still goes through
``engine.data_io.write_validated`` (D-3: one write path, canonical formatting).

**Reads never raise.** A missing, unreadable or schema-invalid file returns the
default (one logged warning if a file was actually there) — a corrupt
preference file must never stop the game booting. Writes DO raise on invalid
data (D-2).

**Why this is boot-only.** ``main.py`` builds the frame target, the ``Renderer``
and the ground cache as ONE stack (``_build_render_stack``); swapping it live
would mean destroying the window and every GPU texture under a running world.
So the screen records the choice and says so, and ``main()`` reads it at boot —
and only when nobody asked louder: an explicit ``--backend=gpu``/``surface``
(or ``HTBH_RENDER_BACKEND``) still wins, because a measurement flag that a
saved preference could silently override would make every A/B run a lie.
"""
import logging
from pathlib import Path

from engine import data_io

#: The screen's two positions -> the host's ``_build_render_stack`` choice.
#: "cpu" is the player-facing name for the Surface blitter.
BACKEND_FOR_RENDERER = {"gpu": "gpu", "cpu": "surface"}
#: The inverse, for seeding the screen from a persisted document.
RENDERER_FOR_BACKEND = {"gpu": "gpu", "surface": "cpu", "auto": "gpu"}

#: What an un-persisted machine boots into: "auto" — try the GPU stack, fall
#: back to Surface whole (D8). The screen shows that as GPU, which is what it
#: resolves to everywhere the GPU stack builds.
DEFAULT_BACKEND = "auto"

_log = logging.getLogger(__name__)


def _schema_path(data_dir):
    return Path(data_dir) / "schemas" / "render_settings.schema.json"


def defaults():
    """A fresh document at the shipped choice."""
    return {"backend": DEFAULT_BACKEND}


def default_path(repo_root):
    """The canonical preferences file: ``<repo_root>/settings/render.json``."""
    return Path(repo_root) / "settings" / "render.json"


def load(path, data_dir):
    """Load and validate the render document at ``path``. Never raises."""
    path = Path(path)
    if not path.exists():
        return defaults()
    try:
        return data_io.load_validated(path, _schema_path(data_dir))
    except Exception as exc:                                   # noqa: BLE001
        _log.warning("could not load render settings from %s (%s) — "
                     "falling back to %s", path, exc, DEFAULT_BACKEND)
        return defaults()


def save(doc, path, data_dir):
    """Persist ``doc`` to ``path`` through the validating writer.

    Raises when ``doc`` is not schema-valid (an unknown backend name, a
    missing or unknown key) — nothing is coerced defensively.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _schema_path(data_dir))
    return doc


def from_settings(settings):
    """The persisted document for a ``SessionSettings``-shaped object."""
    return {"backend": BACKEND_FOR_RENDERER[settings.renderer]}


def apply_to_settings(doc, settings):
    """Push a loaded document onto a ``SessionSettings``-shaped object."""
    settings.renderer = RENDERER_FOR_BACKEND[doc["backend"]]
    return settings
