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
import io
from pathlib import Path

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

# The 7 SHIPPED preset keys, frozen at import BEFORE any configure_fonts call
# (UL-2/D6). ``configure_fonts`` now accepts designer-defined extra keys and
# writes them into ``_FONT_SPECS``, so a LIVE ``set(_FONT_SPECS)`` read inside
# the missing-key check would let a custom key left over from an EARLIER call
# in the same process masquerade as required (tests reconfigure repeatedly).
# This snapshot keeps that check honest: exactly the 7, forever.
_REQUIRED_KEYS = frozenset(_FONT_SPECS)

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

# ...and the 7 keys above, frozen at import: these entries are PINNED and are
# never recomputed, by ``configure_fonts`` or anything else (UL-2/D6 — "the
# seven shipped presets stay exactly as they are, never resized"). Only keys
# OUTSIDE this set get a derived entry (see ``_derive_layout_h``).
_PINNED_LAYOUT_KEYS = frozenset(_LAYOUT_H)

# The sample string the 7 pinned heights were measured from (module docstring
# above: they are Windows ``TextMetrics().size("Ag", key)[1]`` values, done
# once by a human and hardcoded). A derived custom entry reuses it so both
# halves of the table mean the same thing.
_LAYOUT_SAMPLE = "Ag"


def layout_h(font_key):
    """The PINNED text height for ``font_key`` — use for every layout
    computation that ends up in a stored holder rect/anchor or a
    parity-captured/exporter-captured primitive stream. Never a live
    ``pygame.font`` measurement (see module docstring/`_LAYOUT_H` above): a
    live value would make `data/ui/screen_defaults.json` and
    `test_ui_skinning.py`'s golden baseline diverge between Windows (where
    they were captured) and Linux (where CI regenerates/checks them).

    Takes NO ``family`` argument, deliberately (UH-Font-B): a per-text font
    family (``get_font``'s ``family``) changes DRAWN GLYPHS ONLY. Keying
    these heights by family would make every stored widget rect move when a
    designer swaps a family, which is exactly what this table exists to
    prevent — the same contract a preset SIZE change already has (text may
    overflow its widget; the Theme panel says so). Draw-
    time-only text metrics that never land in a stored rect or a captured
    stream should keep calling `text_h`/`TextMetrics.size` instead — those
    are allowed to track the real font because nothing pins their output.
    Unknown keys fall back to 'md', mirroring `get_font`."""
    key = font_key if font_key in _LAYOUT_H else _FALLBACK_KEY
    return _LAYOUT_H[key]


def configure_fonts(doc, font_path=None, family_paths=None):
    """Replace ``_FONT_SPECS``'s entries IN PLACE from a loaded
    ``data/ui/fonts.json`` doc (D5/UH-6): ``{key: {"size": int, "bold":
    bool}}``. The HOST (``game/main.py``) loads + schema-validates the file
    and passes the plain dict — this module stays data-dir-free so bare
    construction (tests/tools) never needs a ``data/`` tree, exactly like
    ``game.ui.skinning.ScreenSkinning.empty()``'s no-disk-I/O precedent.

    The 7 shipped presets (``_REQUIRED_KEYS``) MUST all be present — fails
    loud on a missing one (a renamed/dropped preset would otherwise leave
    some ``font_key`` silently unconfigured, the "no silent break" argument
    every D5 data file shares). EXTRA keys are allowed and additive (UL-2/
    D6): a designer defines their own preset in the editor's Theme panel,
    the schema's ``patternProperties`` validates it, and it lands in
    ``_FONT_SPECS`` next to the 7 like any other ``font_key``.
    Clears ``_cache`` so already-built fonts (sized/sourced from the OLD
    spec) are rebuilt on the next ``get_font`` — a stale cached font would
    otherwise keep drawing at the old size/family until process restart.

    ``font_path`` (UH-Font-A, optional) is an absolute path to a custom
    ``.ttf``/``.otf`` file — a game-wide font family, ORTHOGONAL to the
    per-key size/bold presets above. When set, every ``font_key`` builds
    from that file instead of the default
    ``pygame.font.SysFont("monospace", ...)``. ``None`` (the default)
    preserves today's SysFont behavior exactly — this module still never
    touches ``data/`` itself; the HOST resolves ``data/ui/active_font.json``
    + ``data/fonts/font_manifest.json`` to an absolute path or ``None``
    before calling (``game/main.py`` fails loud on a bad reference per D-2;
    the editor's Theme panel degrades per E-37).

    **The file is READ ONCE, here, into ``_FONT_BYTES``** — ``get_font``
    then builds each size from an ``io.BytesIO`` over those bytes rather
    than from the path. ``pygame.font.Font(<path>, size)`` makes SDL_ttf
    hold that file OPEN for the font object's whole lifetime, and these
    objects live in ``_cache`` until the process exits: on Windows that is
    a hard lock, so the editor would hold the designer's font file hostage
    while it runs and every ``TempDataCase`` teardown would die on
    ``shutil.rmtree`` -> ``PermissionError``. Reading eagerly also moves a
    bad/unreadable file's failure to config time (loud, where the host is
    already validating) instead of the first draw.

    ``family_paths`` (UH-Font-B, optional) is ``{family_id: path}`` for
    EVERY font the host knows about (``data/fonts/font_manifest.json``'s
    entries), so a single text run can ask for a family OTHER than the
    active one — ``get_font(font_key, family=...)``. It is a SUPERSET of
    ``font_path``, not a replacement: ``font_path`` remains "the default
    family", the one every call that names no family gets, and the one
    ``_derive_layout_h`` measures with. Each file is slurped to bytes here
    for the same Windows-file-lock reason as ``font_path`` above; a path
    that cannot be read is DROPPED rather than raised on, because a missing
    family degrades to the default at draw time (the unknown-``font_key``
    -> ``"md"`` grace, one axis over) and the HOST is the layer that fails
    loud on a bad reference (``game/main.py``, D-2).

    Never touches the 7 PINNED ``_LAYOUT_H``/``layout_h`` entries (the
    pinned cross-platform layout invariant, W3-4/UH-6 plan §5): a designer
    who enlarges a shipped preset or swaps the font family changes drawn
    glyphs only; STORED layout rects (screen_defaults.json, every id'd
    widget rect) are unaffected — text can overflow its widget, which is
    the pinned-layout contract, not a bug (the Theme panel says so in a
    tooltip). A DESIGNER-DEFINED key (UL-2/D6) has no pinned entry to
    protect and no committed golden artifact to diverge from, so its
    ``_LAYOUT_H`` entry is DERIVED here — once per call, at config time,
    never measured live at a layout call site (see ``_derive_layout_h``)."""
    missing = _REQUIRED_KEYS - set(doc)
    if missing:
        raise ValueError(
            f"fonts.json key set mismatch: missing {sorted(missing)}")
    for key, spec in doc.items():
        _FONT_SPECS[key] = (spec["size"], spec["bold"])
    global _FONT_PATH, _FONT_BYTES
    _FONT_PATH = str(font_path) if font_path is not None else None
    _FONT_BYTES = Path(_FONT_PATH).read_bytes() if _FONT_PATH is not None else None
    _FAMILY_BYTES.clear()
    for family_id, path in (family_paths or {}).items():
        try:
            _FAMILY_BYTES[family_id] = Path(path).read_bytes()
        except OSError:
            continue
    _cache.clear()
    _derive_layout_h(doc)


def _derive_layout_h(doc):
    """Fill ``_LAYOUT_H`` for every DESIGNER-DEFINED key in ``doc`` (UL-2/
    D6) — the 7 pinned keys are skipped outright, so their hardcoded
    cross-platform values can never be overwritten by a measurement.

    Called at the END of ``configure_fonts`` (after ``_FONT_SPECS``,
    ``_FONT_BYTES`` and the cleared ``_cache`` are in their new state) so
    the measurement sees the font the key will actually draw with, family
    swap included. The height is one ``get_font(key).size("Ag")[1]`` — the
    same measurement a human made once for the pinned 7 — taken ONCE per
    configure call and STORED, never re-measured at a layout call site.
    Re-deriving on every call is deliberate: a custom preset's size is
    designer data that can change between calls, and unlike the 7 it has no
    committed golden artifact (``data/ui/screen_defaults.json``, the
    ``test_ui_skinning.py`` baseline) whose byte-for-byte cross-platform
    reproduction the pin exists to protect.

    A custom key from an EARLIER call that is absent from this ``doc`` is
    left in place rather than swept, mirroring ``_FONT_SPECS``'s own
    write-only update above — the two tables stay in step, and no live read
    of either is ever treated as "what the 7 are" (that is
    ``_REQUIRED_KEYS``/``_PINNED_LAYOUT_KEYS``)."""
    for key in doc:
        if key in _PINNED_LAYOUT_KEYS:
            continue
        _LAYOUT_H[key] = int(get_font(key).size(_LAYOUT_SAMPLE)[1])


_cache = {}
# UH-Font-A: the active custom font FILE (absolute path) or None for the
# SysFont fallback — set only via configure_fonts, never touched elsewhere.
_FONT_PATH = None
# ...and its CONTENT, slurped once by configure_fonts. get_font builds from
# these bytes so no font object ever holds the file open (see the docstring).
_FONT_BYTES = None
# UH-Font-B: family_id -> that family's FILE CONTENT, for the per-text font
# family axis. Populated by configure_fonts from its `family_paths`, read as
# bytes for the same file-lock reason as _FONT_BYTES. A family id absent from
# here is unknown and falls back to the default family (see get_font).
_FAMILY_BYTES = {}


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


def get_font(font_key, family=None):
    """Cached font for (font_key, family) — created on first use, rebuilt if
    its pygame session died. Unknown keys fall back to 'md', mirroring the
    prototype's fonts.get().

    ``family`` (UH-Font-B) is a ``data/fonts/font_manifest.json`` entry id
    naming the font FAMILY this one run draws in — the second, orthogonal
    axis to ``font_key``'s size/bold preset. ``None`` (the default, and what
    every pre-existing call site passes) means the ACTIVE family, i.e.
    exactly today's behaviour: ``_FONT_BYTES`` when ``configure_fonts`` was
    given a ``font_path`` (UH-Font-A), else the original
    ``SysFont("monospace", ...)`` fallback. An UNKNOWN family id degrades to
    that same default rather than raising — a screen doc naming a font the
    manifest no longer carries draws in the default family instead of
    killing the frame, mirroring the unknown-``font_key`` grace above (the
    host is the layer that fails loud on a bad reference: ``game/main.py``,
    D-2).

    Builds from BYTES via ``io.BytesIO``, never a path — see
    ``configure_fonts`` for why (SDL_ttf holds a path-built font's file open
    for its whole lifetime, and these live in ``_cache`` until the process
    exits: a hard lock on Windows)."""
    _ensure_init()
    key = font_key if font_key in _FONT_SPECS else _FALLBACK_KEY
    # Normalize an unknown/absent family to the default BEFORE it reaches the
    # cache key, so a doc naming a deleted font can never grow one cache entry
    # per bad id while drawing identically to the default anyway.
    fam = family if family in _FAMILY_BYTES else None
    cache_key = (key, fam)
    font = _cache.get(cache_key)
    if font is not None and not _is_usable(font):
        font = None
    if font is None:
        size, bold = _FONT_SPECS[key]
        data = _FAMILY_BYTES[fam] if fam is not None else _FONT_BYTES
        if data is not None:
            font = pygame.font.Font(io.BytesIO(data), size)
            font.set_bold(bold)
        else:
            font = pygame.font.SysFont("monospace", size, bold=bold)
        _cache[cache_key] = font
    return font


class TextMetrics:
    """Measures rendered text for HUD layout without blitting — a pure size
    query over the shared font cache (`font.size(text)` → (w, h) in px)."""

    def size(self, text, font_key, family=None):
        return get_font(font_key, family).size(text)
