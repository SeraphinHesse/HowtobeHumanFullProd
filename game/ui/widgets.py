"""Shared UI widgets + palette (Phase 9G).

``game/ui`` is pure logic: it emits the engine HUD primitives
(``HudRect``/``HudText``/``HudSprite``/``HudLines`` from ``engine/render/hud.py``)
via ``renderer.submit_hud`` and measures strings with
``engine.render.fonts.TextMetrics`` — it NEVER imports pygame (a purity test
enforces this). Colors mirror the prototype's ``src/core/constants.py`` palette
verbatim; hit-testing is plain rect math so it is fully headless-testable.
"""
from engine.render import HudRect, HudText
from engine.render.fonts import TextMetrics

_METRICS = TextMetrics()

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
C_RANGE_HIGHLIGHT = (180, 40, 40)    # defence attack range
C_PANEL_STONE = (40, 32, 58)         # HUD "stone pill" body
C_PANEL_INSET = (150, 135, 185)

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


def submit_panel(renderer, rect, *, fill=C_UI_PANEL, border=C_UI_BORDER):
    """A filled, bordered panel body."""
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
    """

    def __init__(self, rect, label, font_key="lg", enabled=True):
        self.rect = rect
        self.label = label
        self.font_key = font_key
        self.enabled = enabled
        self.hovered = False
        self.flash = 0.0
        self.flash_label = None

    def hover(self, mx, my):
        self.hovered = self.enabled and contains(self.rect, mx, my)

    def hit(self, mx, my):
        return self.enabled and contains(self.rect, mx, my)

    def start_flash(self, duration, label=None):
        self.flash = duration
        self.flash_label = label

    def update(self, dt):
        if self.flash > 0:
            self.flash = max(0.0, self.flash - dt)
            if self.flash == 0:
                self.flash_label = None

    def submit(self, renderer, *, color=None, text_color=None):
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
        renderer.submit_hud(HudRect((x, y, w, h), fill, border_radius=3))
        renderer.submit_hud(HudRect((x, y, w, h), C_UI_BORDER, border_radius=3,
                                    width=1))
        ty = y + (h - text_h(self.font_key)) // 2
        submit_centered(renderer, label, x + w // 2, ty, self.font_key, tcol)
