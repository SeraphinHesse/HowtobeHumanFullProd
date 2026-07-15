"""editor-only flat-rect fallback rendering for UNSKINNED UI-screen widgets
(screen mode, B4; E-37 "degrade to rect"). A widget with no skin assigned
(no per-widget override, no kind-matched screen default) still needs SOME
on-screen representation, so this module re-implements a MINIMAL per-kind
look WITHOUT importing game/ui — root CLAUDE.md forbids editor/ and game/
importing each other. This is an accepted drift (planning/UI_EDITOR_PLAN.md):
the two must stay visually aligned by eye + the B2 parity pin, not by
sharing code.

Pure: stdlib + engine.render's frozen HUD dataclasses/TextMetrics only — no
pygame import here, no Qt. Keyed off the six `kind` values pinned by
data/schemas/screen_defaults.schema.json: button, panel, label, backdrop,
bar, field.
"""
from engine.render import HudRect, HudText
from engine.render.fonts import TextMetrics

_METRICS = TextMetrics()

_BORDER_COLOR = (110, 110, 140)
_DEFAULT_TEXT_COLOR = (230, 230, 230)

# Chrome-only fill per kind (an editor preview affordance, not game content)
# — just enough to tell widget kinds apart on a placeholder rect.
_FILL_COLOR = {
    "button": (72, 72, 104),
    "panel": (46, 42, 58),
    "backdrop": (24, 20, 32),
    "bar": (58, 92, 58),
    "field": (40, 40, 54),
}


def centered_label_item(rect, label, font_key, color):
    """A HudText centred on BOTH axes in `rect` — HudText's own
    align='center' only shifts x, so the y half needs the text's own
    measured height (engine.render.fonts.TextMetrics, no pygame surface
    needed). None when `label` is falsy (nothing to draw)."""
    if not label:
        return None
    x, y, w, h = rect
    _, text_h = _METRICS.size(label, font_key)
    return HudText(label, (x + w / 2, y + h / 2 - text_h / 2), font_key,
                  color, align="center")


def fallback_hud_items(rect, kind, label, *, font_key="md", text_color=None,
                       fill=None):
    """[HudRect/HudText, ...] for one widget of `kind` at `rect` (already in
    whatever pixel space the caller wants — screen mode always passes
    SCREEN pixels, see viewport.set_screen_mode/_submit_screen_widget).

    `kind == "label"` draws text only, no box (nothing to border). Every
    other kind draws a filled + 1px-bordered rect plus a centred label when
    one is given. `fill` overrides the kind's default fill (the widget's own
    `color` override, when the designer sets one)."""
    color = tuple(text_color) if text_color is not None else _DEFAULT_TEXT_COLOR
    if kind == "label":
        item = centered_label_item(rect, label, font_key, color)
        return [item] if item is not None else []
    items = [
        HudRect(rect, tuple(fill) if fill is not None
                else _FILL_COLOR.get(kind, _FILL_COLOR["panel"])),
        HudRect(rect, _BORDER_COLOR, width=1),
    ]
    label_item = centered_label_item(rect, label, font_key, color)
    if label_item is not None:
        items.append(label_item)
    return items
