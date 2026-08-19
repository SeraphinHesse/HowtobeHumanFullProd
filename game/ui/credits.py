"""Credits screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/credits_menu.py`` static two-column
list verbatim onto the ``game_over.py`` template: role (dim) on the left, name
(bright) on the right, blank tuples inserting a spacer, plus a BACK button.
Non-scrolling.

UT-Credits: the roll itself is DATA — ``data/ui/credits.json``, edited
through the editor's selector ▸ ui ▸ Credits leaf and bound at boot by
``configure_credits`` (the ``strings.py`` pattern). The literal list below is
the unconfigured default, kept equal to the shipped file.

10L-B: ``ids`` names ``backdrop``, ``title`` ("CREDITS") + ``btn_back`` (the
credits ROWS are static content, not individually overridable — same "skip
dynamic content" rule as every other screen's list-shaped body).
"""
from types import SimpleNamespace

from engine.render.fonts import layout_h

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import (
    Button, anim_ms, submit_centered, submit_text
)
from . import widgets
from .strings import T

_BG = (12, 20, 14)

# (role, name) — the DEFAULT roll; "" pair = spacer. Seeded with the shipped
# content so an unconfigured import (bare test/tool construction) renders
# byte-identical output, exactly like `strings.py`'s `_STRINGS` and
# `widgets.configure_palette` — `configure_credits` rebinds it IN PLACE from
# `data/ui/credits.json` at boot (`game/main.py`). Never index this list from
# outside the module: read `credit_rows()`, so nothing holds a stale binding.
_CREDITS = [
    ("Producer", "Seraphin Hesse"),
    ("Game Design Lead", "Fabian Krüger"),
    ("Art Lead", "Hendrik Wagner"),
    ("Programming Lead", "Johann Heinrich"),
    ("", ""),
    ("UI Lead/2D Artist", "Alicia Jaison"),
    ("2D Artist", "Varvara Kozačuk"),
    ("2D Artist", "Jakob Dahlkar"),
    ("", ""),
    ("Game Designer", "Joel Hoch"),
    ("Game Designer", "Benjamin Riese"),
    ("", ""),
    ("Programmer", "Pantelis Charalambous"),
    ("Programmer", "Alfons Kavalic"),
]
_LINE_H = 15
_SPACER_H = 7
_ROWS_TOP = 75      # first row's baseline y, under the title
_ROWS_GAP = 8       # breathing room kept between the last row and BACK

SCREEN_ID = "credits"


def configure_credits(doc):
    """Rebind the credit roll IN PLACE from a loaded ``data/ui/credits.json``
    doc (``{"rows": [{"role": …, "name": …}, …]}``) — the
    ``strings.configure_strings`` / ``widgets.configure_palette`` pattern,
    called at boot from ``game/main.py``.

    Order is the document's order; a row with an empty role AND name is a
    spacer, the same convention the module default already used."""
    _CREDITS[:] = [(row["role"], row["name"]) for row in doc["rows"]]


def credit_rows():
    """The current roll as ``(role, name)`` tuples — the ONE read path, so a
    caller can never hold a reference across a ``configure_credits``."""
    return list(_CREDITS)


def _row_steps(rows, top, bottom):
    """The ``(line, spacer)`` vertical steps that fit ``rows`` between ``top``
    and ``bottom``.

    At the shipped row count nothing shrinks: the literals above are the
    MAXIMUM step, so today's screen renders byte-identically. Add enough
    people and the list would run off the 640x360 surface (UR-2) and under the
    BACK button, so the steps scale down — but never below ``layout_h("md")``,
    the font's own line height (UR-5: a text row step is font-scale, and a
    step smaller than the glyphs just overlaps them). Past THAT floor the list
    genuinely does not fit; a designer sees it in the editor's screen preview,
    which replays this same submit()."""
    lines = sum(1 for role, name in rows if role or name)
    spacers = len(rows) - lines
    total = lines * _LINE_H + spacers * _SPACER_H
    available = bottom - top
    if total <= available or total <= 0:
        return _LINE_H, _SPACER_H
    scale = available / total
    line_floor = layout_h("md")
    return (max(line_floor, int(_LINE_H * scale)),
            max(max(1, line_floor // 2), int(_SPACER_H * scale)))


class CreditsScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD, label="CREDITS",
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        self.back_btn.rect = (view_w // 2 - 50, view_h - 45, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, 35, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_back": ("button", self.back_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.back_btn.enabled = True
        self.back_btn.hover(mx, my, mouse_down)
        self.back_btn.hovered = self.back_btn.hovered and is_visible(self.back_btn)
        self.back_btn.update(dt)

    def hit(self, mx, my):
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back"})
        if layer_action is not None:
            return layer_action
        return ("back" if is_visible(self.back_btn) and self.back_btn.hit(mx, my)
               else None)

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of, t)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        cx = view_w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        rows = credit_rows()
        line_h, spacer_h = _row_steps(
            rows, _ROWS_TOP, self.back_btn.rect[1] - _ROWS_GAP)
        y = _ROWS_TOP
        for role, name in rows:
            if not role and not name:
                y += spacer_h
                continue
            # UT-5: the ROWS are dynamic-count content and get no per-row id
            # (the levelup-option-box / construct-card rule), but each column
            # still resolves through a string template — the `{value}`-shaped
            # `building.stat.value` precedent — so a designer can decorate a
            # column without touching code.
            submit_text(renderer, T("credits.role", role=role), (cx - 20, y),
                        "sm", widgets.C_UI_TEXT_DIM, align="right")
            submit_text(renderer, T("credits.name", name=name), (cx + 20, y),
                        "md", widgets.C_UI_TEXT)
            y += line_h
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of, t)
