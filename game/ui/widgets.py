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
from engine.render import HudRect, HudSprite, HudText
from engine.render.fonts import TextMetrics, layout_h

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
C_RANGE_HIGHLIGHT = (180, 40, 40)    # defence attack range
C_PANEL_STONE = (40, 32, 58)         # HUD "stone pill" body
C_PANEL_INSET = (150, 135, 185)

# data/ui/palette.json's keys, in the same order as the C_* block above (UH-6,
# D5) — snake_case with the C_ prefix dropped. configure_palette's key ->
# attribute mapping is the mechanical `"C_" + key.upper()`.
_PALETTE_KEYS = (
    "gold", "red", "hp_green", "hp_red", "green_stat", "ui_panel",
    "ui_border", "ui_btn", "ui_btn_hover", "ui_btn_active", "ui_btn_disabled",
    "ui_text", "ui_text_dim", "highlight", "highlight2", "range_highlight",
    "panel_stone", "panel_inset",
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


HEART = "♥"  # ♥ — the love glyph (SysFont monospace renders it)

# -- 10I: tile-condition labels + colours (prototype building_ui.py:23-27) --
# Shared by the panel badges/tooltips (building_ui) and the map overlays so
# the two surfaces cannot drift. Keyed by the TileCondition NAME (a plain
# string) so this module needs no game.map import.
COND_LABELS = {
    "GRASS": ("Grass", (100, 180, 80)),
    "MOUNTAIN": ("Mountain", (160, 130, 90)),
    "POND": ("Pond", (80, 160, 220)),
    "FOREST": ("Forest", (70, 160, 70)),
}
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


def submit_tile_diamond(renderer, col, row, color, width=2):
    """A world-space diamond outline around tile ``(col, row)`` — a selection /
    range / unlock highlight. Uses the overlay pass (world points, converted via
    coords at flush), the natural fit for iso tile outlines."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_overlay_lines(pts, color, width=width, closed=True)


def submit_tile_diamond_fill(renderer, col, row, rgba, border=None,
                             border_width=2):
    """An alpha-FILLED world-space tile diamond (10J overlay alpha) with an
    optional outline — the prototype's SRCALPHA tile overlays (condition tint,
    RANGE, heatmap)."""
    pts = [(col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)]
    renderer.submit_overlay_polys(pts, rgba)
    if border is not None:
        renderer.submit_overlay_lines(pts, border, width=border_width,
                                      closed=True)


def submit_ui_box_highlight(renderer, rect, color=None, width=3):
    """A highlight ring around a UI element (card / Confirm / End Turn) —
    the tutorial guided-chain highlight (D8, TU-6). Plain HUD-space rect;
    ``color`` defaults to the CURRENT ``C_TUTORIAL_HIGHLIGHT`` inside the
    body (never as a def-time default — the same UH-6 rebind trap
    ``submit_panel``'s ``fill``/``border`` guards against)."""
    if color is None:
        color = C_TUTORIAL_HIGHLIGHT
    renderer.submit_hud(HudRect(rect, color, width=width))


def submit_tutorial_banner(renderer, text, view_w, view_h, *, pad=24,
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
