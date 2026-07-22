"""Pure (Qt-free) custom-font import (UH-Font-A): copies a designer's
``.ttf``/``.otf`` into ``data/fonts/imported/`` and appends a
``data/fonts/font_manifest.json`` entry through the validating writer.
Mirrors ``editor/asset_import.py``'s shape ("copy a file in, write a
manifest entry") — slugifies the display name/filename stem instead of any
sprite-specific concept (frame_w/h, rows, animations — none of that applies
to a font file). ``editor/panels/game_theme.py``'s "Import Font…" button is
the only caller. In ``test_editor_viewport.TestPurity``'s import list.
"""
import re
from pathlib import Path

import pygame

from editor import theme_ops

_EXTENSIONS = (".ttf", ".otf")


def _slugify(name):
    """A lowercase ``[a-z0-9_]`` id, matching font_manifest.schema.json's
    ``^[a-z][a-z0-9_]*$`` entry-key pattern."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    if not slug or not slug[0].isalpha():
        slug = f"font_{slug}" if slug else "font"
    return slug


def _unique_id(base_slug, existing):
    if base_slug not in existing:
        return base_slug
    n = 2
    while f"{base_slug}_{n}" in existing:
        n += 1
    return f"{base_slug}_{n}"


def import_font_file(data_dir, ttf_path, display_name=None):
    """Copy ``ttf_path`` -> ``data/fonts/imported/<font_id>.<ext>`` and
    append/replace its ``font_manifest.json`` entry. Validates the file
    actually loads as a font first (a short ``pygame.font.Font`` probe — a
    FORMAT check, not a second render path: it mirrors what
    ``engine/render/fonts.py`` itself does to load a font, ED-22 is about
    drawing game content, not this) and raises ``ValueError`` before
    anything touches disk on a bad file. ``display_name`` defaults to the
    file's stem. Returns the new/reused font id."""
    data_dir = Path(data_dir)
    ttf_path = Path(ttf_path)
    ext = ttf_path.suffix.lower()
    if ext not in _EXTENSIONS:
        raise ValueError(f"unsupported font file type: {ttf_path.suffix!r}")

    pygame.font.init()
    try:
        pygame.font.Font(str(ttf_path), 12)
    except Exception as exc:
        raise ValueError(f"not a usable font file: {ttf_path}") from exc

    name = (display_name or ttf_path.stem).strip() or ttf_path.stem
    doc = theme_ops.load_font_manifest(data_dir)
    font_id = _unique_id(_slugify(name), doc["entries"])

    destination = data_dir / "fonts" / "imported" / f"{font_id}{ext}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(ttf_path.read_bytes())

    doc["entries"][font_id] = {
        "file": f"imported/{font_id}{ext}",
        "display_name": name,
    }
    theme_ops.write_font_manifest(doc, data_dir)
    return font_id
