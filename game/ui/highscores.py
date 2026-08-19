"""High-score table screen (player-identity feature).

A full-screen menu in the ``credits.py``/``main_menu.py`` shape (backdrop ->
title -> body -> BACK button), NOT a modal — it is reached from the main menu's
own ``HIGHSCORES`` row and owns its own ``GameState.HIGHSCORES``.

**This screen does NO disk I/O.** ``game/ui`` is pygame-free AND IO-free (a
purity scan enforces the first, the layering rule the second): the host loads
``scores/highscores.json`` through ``game.core.highscores`` and hands the
document down via ``Shell.set_highscores`` -> ``set_doc``. Importing
``game.core.highscores`` here is only for its PURE ``ranked`` helper (the
sanctioned one-way ``game.ui -> game.core`` direction); ``load_highscores`` /
``append_score`` are never called from this layer.

**Code-only, deliberately** (the ``debug_settings.py`` precedent): there is no
``data/ui/screens/highscores.json`` and no ``data/ui/screen_defaults.json``
entry, and it is not in ``tools/export_ui_layouts.py``'s ``SCREEN_IDS``. An
absent override means "code defaults" (``ScreenSkinning.apply`` no-ops and id
validation stays silent until the defaults file names a screen), so it still
carries a full ``ids`` dict and the panel -> button -> text submission order and
is a drop-in the day someone exports it.

**Scrolling is a plain integer ROW OFFSET, not a generic ScrollView widget.**
One screen does not justify that abstraction, so this plan deliberately does not
add one: ``scroll(dy)`` moves ``scroll_offset`` and clamps it, ``visible_rows``
is computed from the viewport height in ``layout()``, and the header row is
pinned ABOVE the viewport so it never scrolls.
"""
from types import SimpleNamespace


from game.core.highscores import ranked

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, submit_centered, submit_text
from . import widgets

_BG = (12, 20, 14)

#: Skill values are stored snake_case on disk; these are the display strings.
#: Covers ``UNKNOWN_SKILL`` too (an old run, or one that was never asked).
#: ``game/ui/player_intro.py`` imports ``skill_label`` from here so the prompt's
#: option labels and this table's SKILL column can never disagree.
SKILL_LABELS = {
    "never": "NEVER",
    "a_bit": "A BIT",
    "a_lot": "A LOT",
    "developer": "DEVELOPER",
    "unknown": "UNKNOWN",
}


def skill_label(value):
    """The display string for a stored skill value. An unrecognised value
    degrades to a readable upper-cased form rather than vanishing."""
    return SKILL_LABELS.get(value, str(value or "").replace("_", " ").upper())


# Column offsets from the table's left edge. The three numeric columns are
# RIGHT-aligned, so their offset is the column's RIGHT edge.
_TABLE_W = 380
_COL_NAME = 0
_COL_SKILL = 150
_COL_ROUND_R = 260
_COL_BUILT_R = 320
_COL_KILLS_R = 380
_ROW_H = 14
_HEADER_GAP = 15          # header baseline -> first viewport row
_TABLE_TOP = 70
_BOTTOM_PAD = 12          # viewport bottom -> BACK button top

SCREEN_ID = "highscores"


class HighscoresScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        #: The document the host handed down (``None`` until the first
        #: ``set_doc``) and its rows. Rows come from
        #: ``game.core.highscores.ranked`` — already sorted by
        #: ``round_reached`` DESC, so this screen never re-sorts.
        self.doc = None
        self.rows = []
        #: The plain integer row offset (see the module docstring). The
        #: SCROLLING VERB is the ``scroll()`` METHOD below — the host's
        #: ``Shell.handle_scroll`` duck-types on ``callable(screen.scroll)``.
        self.scroll_offset = 0
        self.visible_rows = 1
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD,
                                      label="HIGH SCORES", visible=True)
        # The pinned header row. Its ``rect`` is the table's (x, y) anchor plus
        # the table width — every column, header and body alike, is drawn at a
        # fixed offset from it, so a rect override moves the whole table.
        self._header = SimpleNamespace(rect=(0, 0, _TABLE_W, 0), font_key="sm",
                                       text_color=widgets.C_UI_TEXT_DIM,
                                       visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    # -- host-facing -------------------------------------------------------

    def set_doc(self, doc):
        """Store the high-score document the host loaded and rewind to the top.

        Called every time the screen is opened (the host re-reads the file
        first, so a run that just finished appears immediately)."""
        self.doc = doc
        self.rows = ranked(doc)
        self.scroll_offset = 0

    def scroll(self, dy):
        """Move the viewport by ``dy`` ROWS, clamped so the last page can never
        scroll past the end. Fed by the mouse wheel (``Shell.handle_scroll``)
        and the Up/Down keys.

        **Sign**: POSITIVE ``dy`` moves DOWN the list (a larger offset) — the
        natural row-offset reading. pygame's ``MOUSEWHEEL`` ``event.y`` is
        positive when scrolling UP, so the host negates it."""
        limit = max(0, len(self.rows) - self.visible_rows)
        self.scroll_offset = max(0, min(limit, self.scroll_offset + dy))

    # -- layout ------------------------------------------------------------

    def layout(self, view_w, view_h):
        self.back_btn.rect = (view_w // 2 - 50, view_h - 45, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, 35, 0, 0)
        self._header.rect = (view_w // 2 - _TABLE_W // 2, _TABLE_TOP,
                             _TABLE_W, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "header": ("label", self._header),
            "btn_back": ("button", self.back_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)
        # AFTER apply(), so an overridden header/BACK rect resizes the viewport
        # instead of being ignored.
        self._viewport_top = self._header.rect[1] + _HEADER_GAP
        viewport_h = self.back_btn.rect[1] - _BOTTOM_PAD - self._viewport_top
        self.visible_rows = max(1, viewport_h // _ROW_H)
        self.scroll(0)  # re-clamp: a smaller viewport must not strand the view

    # -- per-frame ---------------------------------------------------------

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.back_btn.enabled = True
        self.back_btn.hover(mx, my, mouse_down)
        self.back_btn.hovered = self.back_btn.hovered and is_visible(self.back_btn)
        self.back_btn.update(dt)

    def hit(self, mx, my):
        """``"back"`` or ``None``. An invisible button is never hit (10L-B)."""
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back"})
        if layer_action is not None:
            return layer_action
        return ("back" if is_visible(self.back_btn) and self.back_btn.hit(mx, my)
                else None)

    def handle_key(self, char, key):
        """``"back"`` (Esc) or ``None``; Up/Down scroll by one row."""
        if key == "escape":
            return "back"
        if key == "up":
            self.scroll(-1)
        elif key == "down":
            self.scroll(1)
        return None

    # -- draw --------------------------------------------------------------

    def _submit_row(self, renderer, cells, y, font_key, color):
        """One table row: NAME / SKILL left-aligned, ROUND / BUILT / KILLS
        right-aligned on their column's right edge."""
        name, skill, rnd, built, kills = cells
        tx = self._header.rect[0]
        submit_text(renderer, name, (tx + _COL_NAME, y), font_key, color)
        submit_text(renderer, skill, (tx + _COL_SKILL, y), font_key, color)
        for text, right in ((rnd, _COL_ROUND_R), (built, _COL_BUILT_R),
                            (kills, _COL_KILLS_R)):
            submit_text(renderer, text, (tx + right, y), font_key, color,
                        align="right")

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.back_btn))
        cx = view_w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        if self._header.visible:
            self._submit_row(renderer,
                             ("NAME", "SKILL", "ROUND", "BUILT", "KILLS"),
                             self._header.rect[1], self._header.font_key,
                             self._header.text_color)

        if not self.rows:
            submit_centered(renderer, "No runs recorded yet.", cx,
                            self._viewport_top + 10, "md",
                            widgets.C_UI_TEXT_DIM)
            return

        y = self._viewport_top
        window = self.rows[self.scroll_offset:self.scroll_offset + self.visible_rows]
        for entry in window:
            self._submit_row(renderer, (
                str(entry.get("name", "")),
                skill_label(entry.get("skill")),
                str(entry.get("round_reached", 0)),
                str(entry.get("buildings_placed", 0)),
                str(entry.get("enemies_killed", 0)),
            ), y, "md", widgets.C_UI_TEXT)
            y += _ROW_H
        if len(self.rows) > self.visible_rows:
            submit_centered(
                renderer,
                f"{self.scroll_offset + 1}-{self.scroll_offset + len(window)}"
                f" of {len(self.rows)}  -  scroll for more",
                cx, self.back_btn.rect[1] - 11, "sm", widgets.C_UI_TEXT_DIM)
