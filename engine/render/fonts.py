"""Lazy SysFont("monospace", …) cache + TextMetrics (Phase 9B).

Mirrors the prototype's src/ui/fonts.py size set for the engine HUD pass, so
the render backend can turn HudText items into blitted surfaces and game/ui
can measure strings for layout WITHOUT importing pygame itself (it asks
TextMetrics). pygame.font works headless under SDL dummy; the cache is built
lazily (fonts created on first request) so callers that never draw text pay
nothing, and font.init() is called defensively so construction never crashes.

font_key set: sm/md/lg/xl/xxl mirror the prototype 1:1 (lg/xl/xxl bold), plus
hud_phase/hud_lvl for the phase (bottom-left) and village-level readouts.
"""
import pygame

# font_key -> (point size, bold). Prototype fonts.init() parity for the shared
# set; lg/xl/xxl are bold there, the hud_* corners are not.
_FONT_SPECS = {
    "sm": (9, False),
    "md": (11, False),
    "lg": (13, True),
    "xl": (18, True),
    "xxl": (26, True),
    "hud_phase": (14, False),
    "hud_lvl": (12, False),
}

_FALLBACK_KEY = "md"

# Pinned layout-math heights (Fix 1, phase-10L wave3): CI runs Linux, dev runs
# Windows, and pygame's SysFont ``.size()`` measures glyph heights ±1px
# differently per platform/font-backend. Any LAYOUT POSITION computed from a
# measured text height (a stored widget rect, an id'd anchor, or anything
# that lands in the `test_ui_skinning.py` golden parity stream or
# `tools/export_ui_layouts.py`'s `screen_defaults.json`) must therefore never
# read a LIVE measurement — it has to read a value that is the same on every
# machine that ever runs the game. These are exactly the Windows-measured
# ``TextMetrics().size("Ag", key)[1]`` values already baked into every
# committed artifact (``data/ui/screen_defaults.json``, the test's
# ``_BASELINE``), pinned here so regenerating those artifacts on ANY platform
# reproduces them byte-for-byte. Draw-time-only text metrics (nothing stored,
# nothing captured — e.g. a hover hint's word-wrap width) may keep using
# ``TextMetrics``/``text_h`` directly; only layout math needs `layout_h`.
_LAYOUT_H = {
    "sm": 11,
    "md": 13,
    "lg": 15,
    "xl": 21,
    "xxl": 30,
    "hud_phase": 16,
    "hud_lvl": 14,
}


def layout_h(font_key):
    """The PINNED text height for ``font_key`` — use for every layout
    computation that ends up in a stored holder rect/anchor or a
    parity-captured/exporter-captured primitive stream. Never a live
    ``pygame.font`` measurement (see module docstring/`_LAYOUT_H` above): a
    live value would make `data/ui/screen_defaults.json` and
    `test_ui_skinning.py`'s golden baseline diverge between Windows (where
    they were captured) and Linux (where CI regenerates/checks them). Draw-
    time-only text metrics that never land in a stored rect or a captured
    stream should keep calling `text_h`/`TextMetrics.size` instead — those
    are allowed to track the real font because nothing pins their output.
    Unknown keys fall back to 'md', mirroring `get_font`."""
    key = font_key if font_key in _LAYOUT_H else _FALLBACK_KEY
    return _LAYOUT_H[key]


def configure_fonts(doc, font_path=None):
    """Replace ``_FONT_SPECS``'s entries IN PLACE from a loaded
    ``data/ui/fonts.json`` doc (D5/UH-6): ``{key: {"size": int, "bold":
    bool}}``. The HOST (``game/main.py``) loads + schema-validates the file
    and passes the plain dict — this module stays data-dir-free so bare
    construction (tests/tools) never needs a ``data/`` tree, exactly like
    ``game.ui.skinning.ScreenSkinning.empty()``'s no-disk-I/O precedent.

    Same 7 keys as today's presets — fails loud on a key-set mismatch (a
    renamed/dropped preset would otherwise leave some ``font_key`` silently
    unconfigured, the "no silent break" argument every D5 data file shares).
    Clears ``_cache`` so already-built fonts (sized/sourced from the OLD
    spec) are rebuilt on the next ``get_font`` — a stale cached font would
    otherwise keep drawing at the old size/family until process restart.

    ``font_path`` (UH-Font-A, optional) is an absolute path to a custom
    ``.ttf``/``.otf`` file — a game-wide font family, ORTHOGONAL to the
    per-key size/bold presets above. When set, every ``font_key`` builds via
    ``pygame.font.Font(font_path, size)`` instead of the default
    ``pygame.font.SysFont("monospace", ...)``. ``None`` (the default)
    preserves today's SysFont behavior exactly — this module still never
    touches ``data/`` itself; the HOST resolves ``data/ui/active_font.json``
    + ``data/fonts/font_manifest.json`` to an absolute path or ``None``
    before calling (``game/main.py`` fails loud on a bad reference per D-2;
    the editor's Theme panel degrades per E-37).

    Does NOT touch ``_LAYOUT_H``/``layout_h`` (the pinned cross-platform
    layout invariant, W3-4/UH-6 plan §5): a designer who enlarges a preset
    or swaps the font family changes drawn glyphs only; STORED layout rects
    (screen_defaults.json, every id'd widget rect) are unaffected — text can
    overflow its widget, which is the pinned-layout contract, not a bug (the
    Theme panel says so in a tooltip)."""
    unknown = set(doc) - set(_FONT_SPECS)
    missing = set(_FONT_SPECS) - set(doc)
    if unknown or missing:
        raise ValueError(
            f"fonts.json key set mismatch: missing {sorted(missing)}, "
            f"unknown {sorted(unknown)}")
    for key, spec in doc.items():
        _FONT_SPECS[key] = (spec["size"], spec["bold"])
    global _FONT_PATH
    _FONT_PATH = str(font_path) if font_path is not None else None
    _cache.clear()


_cache = {}
# UH-Font-A: the active custom font FILE (absolute path) or None for the
# SysFont fallback — set only via configure_fonts, never touched elsewhere.
_FONT_PATH = None


def _ensure_init():
    if not pygame.font.get_init():
        pygame.font.init()


def _is_usable(font):
    """A SysFont whose pygame.font session was torn down (a prior pygame.quit)
    raises 'font module quit since font created' on ANY use — even after a fresh
    pygame.init leaves get_init() True. Probe cheaply so ``get_font`` can rebuild
    a stale cache entry (matters when a host re-boots pygame in one process:
    tools tests / smoke run game.main repeatedly)."""
    try:
        font.get_height()
        return True
    except pygame.error:
        return False


def get_font(font_key):
    """Cached font for font_key (created on first use, rebuilt if its pygame
    session died). Unknown keys fall back to 'md', mirroring the prototype's
    fonts.get(). Builds via ``pygame.font.Font(_FONT_PATH, size)`` when a
    custom font family is configured (UH-Font-A), else the original
    ``SysFont("monospace", ...)`` fallback — unchanged when ``_FONT_PATH`` is
    ``None`` (the default / unconfigured state)."""
    _ensure_init()
    key = font_key if font_key in _FONT_SPECS else _FALLBACK_KEY
    font = _cache.get(key)
    if font is not None and not _is_usable(font):
        font = None
    if font is None:
        size, bold = _FONT_SPECS[key]
        if _FONT_PATH is not None:
            font = pygame.font.Font(_FONT_PATH, size)
            font.set_bold(bold)
        else:
            font = pygame.font.SysFont("monospace", size, bold=bold)
        _cache[key] = font
    return font


class TextMetrics:
    """Measures rendered text for HUD layout without blitting — a pure size
    query over the shared font cache (`font.size(text)` → (w, h) in px)."""

    def size(self, text, font_key):
        return get_font(font_key).size(text)
