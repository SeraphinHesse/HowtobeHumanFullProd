"""editor-only flat-rect fallback rendering for UNSKINNED UI-screen widgets
(screen mode, B4; E-37 "degrade to rect"). A widget with no skin assigned
(no per-widget override, no kind-matched screen default) still needs SOME
on-screen representation, so this module re-implements a MINIMAL per-kind
look WITHOUT importing game/ui — root CLAUDE.md forbids editor/ and game/
importing each other. This is an accepted drift (planning/completed plans/UI_EDITOR_PLAN.md):
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


# -- position-only text anchors -------------------------------------------
# A widget whose stored rect is `(x, y, 0, 0)` is an ANCHOR, not a box: the
# game draws text from that point and the extent is whatever the glyphs come
# out as. `screen_defaults.json` is full of them (every hud.py readout, the
# phase banner, boss_cutscene's headline/subtitle, ~40 building_panel stat
# cells). Left as literal zero-area rects they are unclickable, undraggable
# and invisible when selected — the whole "these should be editable widgets"
# complaint. `interaction_rect` gives the EDITOR (and only the editor) a real
# box over such an anchor. The stored rect is never touched: a move still
# writes x/y and leaves w/h at 0, so the game's own layout is unchanged.
_MIN_HIT_W = 18   # logical px — a floor, so an empty/untranslatable anchor
_MIN_HIT_H = 10   # is still a grabbable target rather than a dot


def is_anchor_rect(rect):
    """True when `rect` stores no extent (w or h is 0) — i.e. it is a draw
    ANCHOR, not a box. Such a widget can be moved but not resized: there is
    no stored size for a resize to write."""
    return rect[2] <= 0 or rect[3] <= 0


def resolve_align(spec, override):
    """The alignment `interaction_rect` should measure against (UL-1).

    The designer's OVERRIDE `align` if set (`data/ui/screens/<id>.json`'s
    `widgets.<id>.align`, which the game reads back through
    `widgets.submit_label`), else the DEFAULT recorded in
    `screen_defaults.json` (an editor-only measuring hint the exporter took
    off the code holder), else "left" — `submit_label`'s own fallback.

    `spec` is the widget's `screen_defaults.json` entry, `override` is the
    screen doc's per-widget override dict; both may be `{}`. Without this the
    editor's hit box for a re-aligned position-only anchor lands beside the
    glyphs instead of on them (the `hud.round_label` failure in
    `game/ui/CLAUDE.md`, now reachable from the doc rather than only from
    code)."""
    return (override or {}).get("align") or (spec or {}).get("align", "left")


def interaction_rect(rect, *, text=None, font_key="md", align="left"):
    """The box the editor hit-tests and outlines for a widget at `rect`.

    A widget with a real stored size is returned verbatim — this only ever
    grows a zero-extent axis. The grown size is the measured size of `text`
    (the widget's live template/sample/label, whatever the caller could
    resolve) at `font_key`, floored at a minimum so an anchor with no
    resolvable text is still grabbable. `align` shifts x the way the game's
    own `HudText` align does, so the box lands ON the glyphs rather than
    beside them.

    Pure: `TextMetrics` measures through the engine's font stack with no
    pygame surface, the same call `centered_label_item` already makes."""
    x, y, w, h = rect
    if w > 0 and h > 0:
        return (x, y, w, h)
    text_w = text_h = 0
    if text:
        text_w, text_h = _METRICS.size(str(text), font_key)
    if w <= 0:
        w = max(text_w, _MIN_HIT_W)
    if h <= 0:
        h = max(text_h, _MIN_HIT_H)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    return (x, y, w, h)


def widget_display_name(widget_id, spec):
    """The cosmetic human name for one widget (UH-4, D4): `spec`'s
    `display_name` when present, else the code id itself. `spec` is the
    widget's `screen_defaults.json` entry (a plain dict, possibly `None`/`{}`
    for an id the defaults don't know about — the id is always a safe
    fallback). ONE resolution rule so the widget list and the viewport
    caption can never disagree."""
    if spec:
        name = spec.get("display_name")
        if name:
            return name
    return widget_id
