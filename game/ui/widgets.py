"""Shared UI widgets + palette (Phase 9G).

``game/ui`` is pure logic: it emits the engine HUD primitives
(``HudRect``/``HudText``/``HudSprite``/``HudLines`` from ``engine/render/hud.py``)
via ``renderer.submit_hud`` and measures strings with
``engine.render.fonts.TextMetrics`` — it NEVER imports pygame (a purity test
enforces this). Colors mirror the prototype's ``src/core/constants.py`` palette
verbatim; hit-testing is plain rect math so it is fully headless-testable.

The C_* palette (UH-6, D5) is DATA-BACKED: ``data/ui/palette.json`` ships the
same values as committed content, loaded once at boot (``game/main.py``) and
applied via ``configure_palette`` — the literals below are the unconfigured
fallback (bare test/tool construction stays deterministic; a pin test proves
they equal the stock file). Every consumer reads ``widgets.C_GOLD`` etc. via
attribute access, never ``from .widgets import C_GOLD`` (an early binding a
later ``configure_palette`` rebind cannot reach) — see ``game/ui/CLAUDE.md``.
"""
import math
from types import SimpleNamespace

from engine.render import HudLines, HudRect, HudSprite, HudText
from engine.render.fonts import TextMetrics, layout_h

from . import strings
from .skinning import is_visible

_METRICS = TextMetrics()

# R2 hit seam: host-injected per-pixel alpha test for skinned buttons
_skin_hit_test = None


def set_skin_hit_test(fn):
    """Inject a per-pixel alpha hit-test function (A8, host wiring).
    Signature: fn(slot_key, animation, anim_time_ms, dest_size, rel_xy) -> bool.
    None (the default) means unskinned rects only."""
    global _skin_hit_test
    _skin_hit_test = fn


def anim_ms(clock_s):
    """A screen's float seconds accumulator -> the integer ms a skinned
    HudSprite wants (10L-A). ONE conversion, so no screen re-derives it.
    ``round``, not ``int``: repeated float dt accumulation lands a hair under
    the exact millisecond (10 * 0.1 == 0.9999999999999999) and truncation
    would silently eat a frame's worth of ms — the same class of drift
    Sec 1.5 rules out for per-frame accumulation, just at the read instead."""
    return round(clock_s * 1000)

# -- palette (prototype constants.py, verbatim RGB) -------------------------
C_GOLD = (255, 200, 50)
C_RED = (210, 55, 55)
C_HP_GREEN = (55, 195, 55)
C_HP_RED = (200, 55, 55)
C_GREEN_STAT = (80, 210, 80)
C_UI_PANEL = (42, 34, 68)
C_UI_BORDER = (80, 65, 120)
C_UI_BTN = (75, 60, 115)
C_UI_BTN_HOVER = (110, 90, 160)
C_UI_BTN_ACTIVE = (60, 140, 60)
C_UI_BTN_DISABLED = (50, 45, 70)
C_UI_TEXT = (235, 225, 195)
C_UI_TEXT_DIM = (150, 140, 120)
C_HIGHLIGHT = (255, 230, 60)         # selected tile
C_HIGHLIGHT2 = (255, 180, 60)        # unlock-area tiles
C_TUTORIAL_HIGHLIGHT = (255, 255, 255)  # TU-6: guided-chain highlight (white)
# Building Movement: the "you can move the selected building here" tiles. A
# plain code constant, NOT palette-data-backed — the same deliberate exception
# `C_TUTORIAL_HIGHLIGHT` above is (see `_PALETTE_KEYS`, which both are absent
# from, and game/ui/CLAUDE.md's palette section).
C_MOVE_HIGHLIGHT = (80, 200, 255)    # move-destination tiles (cyan)
C_RANGE_HIGHLIGHT = (180, 40, 40)    # defence attack range
# Construct panel: a tile that already hosted a Painter and paid out, so it
# can never host another one. Same "plain code constant" exception as
# C_MOVE_HIGHLIGHT above.
C_PAINTER_USED = (110, 110, 110)     # grey — barred painter tile
C_PANEL_STONE = (40, 32, 58)         # HUD "stone pill" body
C_PANEL_INSET = (150, 135, 185)
C_PURPLE = (168, 105, 222)           # the house purple (matches the XP bar fill)

# data/ui/palette.json's keys, in the same order as the C_* block above (UH-6,
# D5) — snake_case with the C_ prefix dropped. configure_palette's key ->
# attribute mapping is the mechanical `"C_" + key.upper()`.
_PALETTE_KEYS = (
    "gold", "red", "hp_green", "hp_red", "green_stat", "ui_panel",
    "ui_border", "ui_btn", "ui_btn_hover", "ui_btn_active", "ui_btn_disabled",
    "ui_text", "ui_text_dim", "highlight", "highlight2", "range_highlight",
    "panel_stone", "panel_inset", "purple",
)


def configure_palette(doc):
    """Rebind every C_* module constant IN PLACE from a loaded
    ``data/ui/palette.json`` doc (D5/UH-6) — mirrors
    ``engine.render.fonts.configure_fonts``: the host (``game/main.py``)
    loads + schema-validates the file and passes the plain dict, so this
    module stays data-dir-free (bare construction — tests/tools — never
    needs a ``data/`` tree). Fails loud on an unknown/missing key (same
    "no silent break" argument as ``configure_fonts`` — a renamed/dropped
    key would otherwise leave some C_* constant silently un-rebound).

    Every consumer reads these through ``widgets.C_*`` attribute access
    (never ``from .widgets import C_GOLD``, an early binding a later
    rebind here cannot reach) — see ``game/ui/CLAUDE.md``."""
    unknown = set(doc) - set(_PALETTE_KEYS)
    missing = set(_PALETTE_KEYS) - set(doc)
    if unknown or missing:
        raise ValueError(
            f"palette.json key set mismatch: missing {sorted(missing)}, "
            f"unknown {sorted(unknown)}")
    for key, value in doc.items():
        globals()["C_" + key.upper()] = tuple(value)


# -- 10I: tile-condition labels + colours (prototype building_ui.py:23-27) --
# Shared by the panel badges/tooltips (building_ui) and the map overlays so
# the two surfaces cannot drift. Keyed by the TileCondition NAME (a plain
# string) so this module needs no game.map import. Colors stay code-owned
# (data/ui/palette.json's scope is the C_* block only, D5); the LABEL TEXT
# is Phase C's string-table content instead (data/ui/strings.json's
# widgets.condition.* ids).
_COND_COLORS = {
    "GRASS": (100, 180, 80),
    "MOUNTAIN": (160, 130, 90),
    "POND": (80, 160, 220),
    "FOREST": (70, 160, 70),
}
_COND_LABEL_IDS = {
    "GRASS": "widgets.condition.grass",
    "MOUNTAIN": "widgets.condition.mountain",
    "POND": "widgets.condition.pond",
    "FOREST": "widgets.condition.forest",
}


def cond_label(name):
    """(label, color) for a TileCondition NAME (10I). A FUNCTION, not a
    dict literal (Phase C: same reasoning as hud.py's ``_phase_color`` —
    a dict built at IMPORT time would freeze the pre-``configure_strings``
    fallback text and never see a later rebind; this resolves fresh via
    ``strings.T()`` on every call)."""
    return strings.T(_COND_LABEL_IDS[name]), _COND_COLORS[name]
# -- /10I --


def text_size(text, font_key):
    """(w, h) of ``text`` in the given font — pure metric, no blit."""
    return _METRICS.size(text, font_key)


def text_h(font_key):
    return _METRICS.size("Ag", font_key)[1]


def pretty(slug):
    """``'stone_thrower'`` -> ``'Stone Thrower'`` (building display names)."""
    return slug.replace("_", " ").title()


def wrap_text(text, font_key, max_w, max_lines=None):
    """Greedy word wrap to ``max_w`` pixels. A word longer than the line is not
    broken (it just overhangs). Truncates to ``max_lines`` when given."""
    lines, current = [], ""
    for word in text.split():
        trial = f"{current} {word}" if current else word
        if current and text_size(trial, font_key)[0] > max_w:
            lines.append(current)
            current = word
            if max_lines is not None and len(lines) == max_lines:
                return lines
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def contains(rect, mx, my):
    x, y, w, h = rect
    return x <= mx < x + w and y <= my < y + h


def submit_panel(renderer, rect, *, fill=None, border=None, skin=None,
                 tint=None, anim_ms=0):
    """A filled, bordered panel body. With ``skin`` (a slot key, 10L-A) the
    two flat rects are replaced by one nine-sliced HudSprite covering the same
    rect; ``fill``/``border`` are then ignored and ``tint`` (D6/UH-6 — the
    sheet-multiply color, ``None`` = unchanged) rides along instead. Panels
    carry no interaction state, so they always animate the ``idle`` row.
    Panels are not click targets — no hit-test wiring.

    ``fill``/``border`` default to ``None`` and resolve to the CURRENT
    ``C_UI_PANEL``/``C_UI_BORDER`` inside the body, never as a def-time
    default (UH-6: a default-arg literal is evaluated once at import and
    would never see a later ``configure_palette`` rebind — the one trap
    that survives switching every OTHER reference to attribute access)."""
    if fill is None:
        fill = C_UI_PANEL
    if border is None:
        border = C_UI_BORDER
    if skin:
        x, y, w, h = rect
        renderer.submit_hud(HudSprite(skin, (x, y), (w, h),
                                      animation="idle", anim_time_ms=anim_ms,
                                      tint=tint))
        return
    renderer.submit_hud(HudRect(rect, fill))
    renderer.submit_hud(HudRect(rect, border, width=1))


def submit_text(renderer, text, pos, font_key, color, align="left"):
    renderer.submit_hud(HudText(text, pos, font_key, color, align=align))


def submit_centered(renderer, text, cx, cy, font_key, color):
    """Text centred horizontally on ``cx`` with its top at ``cy``."""
    renderer.submit_hud(HudText(text, (cx, cy), font_key, color, align="center"))


def label_holder(rect=(0, 0, 0, 0), *, text_id=None, label="", font_key="md",
                 text_color=None, align="left", visible=True):
    """A ``label``-kind widget holder for an id'd piece of text (UT-1).

    The ``SimpleNamespace`` shadow object every screen already builds by hand
    for its static titles, with the two UT-1 fields folded in — written once
    here so the ~90 converted call sites do not each restate the field list.

    ``rect`` follows the text-label convention (``game/ui/CLAUDE.md``): an
    ``(x, y, 0, 0)`` ANCHOR POINT, W/H nominal ``0``, computed and STORED in
    ``layout()`` so a rect override moves the text and the exporter reads a
    real position.

    ``text_id`` names a ``data/ui/strings.json`` key: the text is resolved
    through ``T()`` at draw time, so the template is designer-editable and the
    live values stay code-owned. A holder with no ``text_id`` falls back to its
    static ``label`` — the pre-UT-1 behaviour, unchanged.
    """
    return SimpleNamespace(rect=rect, text_id=text_id, label=label,
                           font_key=font_key, text_color=text_color,
                           align=align, visible=visible)


def submit_label(renderer, holder, *, text=None, color=None, align=None, **fmt):
    """Draw an id'd label holder (UT-1) — THE idiom for text a screen names in
    its ``ids`` dict.

    Text comes from ``T(holder.text_id, **fmt)`` when the holder carries a
    ``text_id``, else from its static ``holder.label``. Geometry, font, colour,
    alignment and visibility all come off the holder, i.e. from whatever
    ``ScreenSkinning.apply()`` last wrote onto it — which is why this must be
    called AFTER ``apply()``, like every other override-reading draw.

    ``text`` bypasses both for the handful of runs whose content is authored
    at RUNTIME rather than templated — a building's player-typed name, a live
    text-entry buffer. Those still get an id'd holder (so their position,
    font and colour are designer-owned); only the characters are not the
    designer's to write.

    ``color`` is the code-computed fallback used when no ``text_color``
    override is set (the "``None`` means compute" convention every other
    override key already follows); ``align`` likewise overrides the holder's
    own for a call site that varies it. An empty resolved string draws
    nothing — a hidden or unset label is a no-op, never a blank ``HudText``.
    """
    if not is_visible(holder):
        return
    text_id = getattr(holder, "text_id", None)
    if text is None:
        if text_id:
            text = strings.T(text_id, **fmt)
        else:
            text = getattr(holder, "label", "") or ""
    if not text:
        return
    tcol = getattr(holder, "text_color", None)
    if tcol is None:
        tcol = color if color is not None else C_UI_TEXT
    if align is None:
        align = getattr(holder, "align", "left") or "left"
    rect = holder.rect
    renderer.submit_hud(HudText(text, (rect[0], rect[1]),
                                holder.font_key, tcol, align=align))


def submit_tile_diamond(renderer, col, row, color, width=2):
    """A world-space diamond outline around tile ``(col, row)`` — a selection /
    range / unlock highlight. fix/depth-sorted-world-fills: goes through
    ``Renderer.submit_world_fill`` (world_pos=(col, row), the same anchor a
    building's own ``Transform`` uses), NOT ``submit_overlay_lines`` — this
    sorts into the SAME depth queue as buildings, so it can draw BEHIND a
    building standing on/near this tile instead of always on top of every
    sprite (see ``engine/render/CLAUDE.md``'s "Depth-sorted world fills")."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_world_fill(pts, world_pos=(col, row), border=color,
                               border_width=width)


def submit_tile_diamond_fill(renderer, col, row, rgba, border=None,
                             border_width=2):
    """An alpha-FILLED world-space tile diamond with an optional outline —
    the prototype's SRCALPHA tile overlays (condition tint, RANGE, heatmap,
    tier overview). fix/depth-sorted-world-fills: same
    ``Renderer.submit_world_fill`` mechanism as ``submit_tile_diamond`` above
    — draws behind a building on/near this tile instead of always on top."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_world_fill(pts, world_pos=(col, row), color=rgba,
                               border=border, border_width=border_width)


def submit_ui_box_highlight(renderer, rect, color=None, width=3):
    """A highlight ring around a UI element (card / Confirm / End Turn) —
    the tutorial guided-chain highlight (D8, TU-6). Plain HUD-space rect;
    ``color`` defaults to the CURRENT ``C_TUTORIAL_HIGHLIGHT`` inside the
    body (never as a def-time default — the same UH-6 rebind trap
    ``submit_panel``'s ``fill``/``border`` guards against)."""
    if color is None:
        color = C_TUTORIAL_HIGHLIGHT
    renderer.submit_hud(HudRect(rect, color, width=width))


def submit_tutorial_banner(renderer, text, view_w, view_h, *, pad=12,
                            font_key="lg"):
    """A large, non-interactive, screen-centred banner (TU-8 Fix 2) — the
    ``submit_ui_box_highlight`` sibling for a full text hint (e.g. "right
    click anywhere to close"). A filled ``C_TUTORIAL_HIGHLIGHT`` box with a
    dark border and dark centred text, sized to the text. Deliberately
    carries NO hit-test and consumes no input, UNLIKE ``TutorialMessageScreen``
    — a banner instructing a right-click must never itself swallow it."""
    tw, th = text_size(text, font_key)
    w, h = tw + pad * 2, th + pad * 2
    x, y = (view_w - w) // 2, (view_h - h) // 2
    renderer.submit_hud(HudRect((x, y, w, h), C_TUTORIAL_HIGHLIGHT))
    renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER, width=3))
    submit_centered(renderer, text, view_w // 2, y + pad, font_key,
                    C_UI_PANEL)


def submit_bar(renderer, x, y, w, h, ratio, *, bg, fill, border=None):
    """A horizontal fill bar (HP / lives). ``ratio`` clamped to [0, 1]."""
    ratio = max(0.0, min(1.0, ratio))
    renderer.submit_hud(HudRect((x, y, w, h), bg))
    if ratio > 0:
        renderer.submit_hud(HudRect((x, y, int(w * ratio), h), fill))
    if border is not None:
        renderer.submit_hud(HudRect((x, y, w, h), border, width=1))


def submit_progress_ring(renderer, cx, cy, radius, ratio, *,
                          bg=None, fill=None, width=2, segments=32):
    """A small circular hold-progress indicator (cutscene hold-to-skip): a
    dim full ring plus a bright arc from 12 o'clock clockwise proportional
    to ``ratio`` (clamped to [0, 1]). Composed from ``HudLines`` — no arc/pie
    HUD primitive exists (`engine/render/hud.py`), the same reason
    ``submit_ui_box_highlight``/``submit_tutorial_banner`` above compose
    from existing primitives instead of adding a new engine one. Colors
    default to ``None`` and resolve here, not at def time — the UH-6
    rebind-safety convention every helper in this file follows."""
    if bg is None:
        bg = C_UI_TEXT_DIM
    if fill is None:
        fill = C_GOLD
    ratio = max(0.0, min(1.0, ratio))
    bg_pts = tuple(
        (cx + radius * math.sin(2 * math.pi * i / segments),
         cy - radius * math.cos(2 * math.pi * i / segments))
        for i in range(segments + 1))
    renderer.submit_hud(HudLines(bg_pts, bg, width=width, closed=True))
    if ratio > 0:
        n = max(1, round(segments * ratio))
        arc_pts = tuple(
            (cx + radius * math.sin(2 * math.pi * ratio * i / n),
             cy - radius * math.cos(2 * math.pi * ratio * i / n))
            for i in range(n + 1))
        renderer.submit_hud(HudLines(arc_pts, fill, width=width))


class Button:
    """A rectangular click target that emits its own HUD frame + centred label.

    Pure: ``hit`` is rect math, ``submit`` is HUD primitives. The host feeds
    mouse position through ``hover(mx, my)`` and clicks through ``hit(mx, my)``.
    A ``flash`` timer (set by ``start_flash``) redraws it red — the
    not-enough-love feedback (prototype ``_draw_btn_red``).

    10L-A: an optional ``skin`` (a slot key) swaps the two flat rects for one
    animated, nine-sliced ``HudSprite`` — the centred label is drawn exactly
    the same either way. With no skin the emitted primitives are byte-identical
    to pre-10L (pinned by tools/tests/test_button_skin.py). ``hover`` takes the
    host's held-left-button flag so the widget can report ``pressed``.

    R2 (10L-A): skinned ``hover`` and ``click`` only over drawn pixels (alpha >
    0), via a host-injected seam querying the idle row (`_surface_hit`). The
    seam is unset by default (pure game code); host wires it once at startup
    (`game/main.py`: `widgets.set_skin_hit_test(assets.hit_opaque)`). With no
    seam or no skin, behaves as today (rect test).
    """

    def __init__(self, rect, label, font_key="lg", enabled=True, skin=None):
        self.rect = rect
        self.label = label
        self.font_key = font_key
        self.enabled = enabled
        self.skin = skin          # 10L-A: slot key, or None = flat rects
        self.hovered = False
        self.mouse_down = False   # 10L-A: host's held-left-button flag
        self.flash = 0.0
        self.flash_label = None

    def _surface_hit(self, mx, my):
        """Rect hit-test; if skin + seam exists, delegate to the injected
        alpha test. Canonical-silhouette query: ("idle", 0) only, so cursor
        oscillates over silhouette holes. R2."""
        x, y, w, h = self.rect
        if not contains(self.rect, mx, my):
            return False
        if self.skin is None or _skin_hit_test is None:
            return True
        return _skin_hit_test(self.skin, "idle", 0, (w, h), (mx - x, my - y))

    def hover(self, mx, my, mouse_down=False):
        self.hovered = self.enabled and self._surface_hit(mx, my)
        self.mouse_down = bool(mouse_down)

    @property
    def pressed(self):
        """Held down over this button (10L-A). Never true when disabled —
        ``hovered`` is already gated on ``enabled``."""
        return self.hovered and self.mouse_down

    def hit(self, mx, my):
        """Check if this point is a hit (10L-A: via _surface_hit for R2 seam)."""
        return self.enabled and self._surface_hit(mx, my)

    def start_flash(self, duration, label=None):
        self.flash = duration
        self.flash_label = label

    def update(self, dt):
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt)
            if self.flash == 0:
                self.flash_label = None

    def _state(self):
        """Skin animation row. Same priority as the flat fill selection below,
        so skinned and unskinned never disagree about the button's state
        (plan lines 58-61: flash -> pressed art, disabled -> disabled row)."""
        if self.flash > 0:
            return "pressed"
        if not self.enabled:
            return "disabled"
        if self.pressed:
            return "pressed"
        return "hover" if self.hovered else "idle"

    def submit(self, renderer, *, color=None, text_color=None, anim_ms=0):
        x, y, w, h = self.rect
        if self.flash > 0:
            fill, tcol = C_RED, C_UI_TEXT
            label = self.flash_label or self.label
        elif not self.enabled:
            fill, tcol, label = C_UI_BTN_DISABLED, C_UI_TEXT_DIM, self.label
        else:
            fill = color or (C_UI_BTN_HOVER if self.hovered else C_UI_BTN)
            tcol = text_color or C_UI_TEXT
            label = self.label
        if self.skin:
            # 10L-A: the sprite replaces both rects; ``color`` (a fill
            # override) has nothing to fill and is ignored. Label unchanged.
            # D6/UH-6: ``tint`` (a sheet-multiply color, ``None`` = unchanged)
            # rides along the same setattr an override applies — only a
            # skinned button (or one whose screen doc assigned it) ever
            # carries the attribute, so ``getattr`` covers dynamic
            # (non-id'd) buttons too, which never gain one.
            renderer.submit_hud(HudSprite(self.skin, (x, y), (w, h),
                                          animation=self._state(),
                                          anim_time_ms=anim_ms,
                                          tint=getattr(self, "tint", None)))
        else:
            renderer.submit_hud(HudRect((x, y, w, h), fill, border_radius=3))
            renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER,
                                        border_radius=3, width=1))
        # layout_h, not text_h: this positions every Button label recorded in
        # the parity/exporter streams (engine/render/fonts.py "layout_h").
        ty = y + (h - layout_h(self.font_key)) // 2
        submit_centered(renderer, label, x + w // 2, ty, self.font_key, tcol)
