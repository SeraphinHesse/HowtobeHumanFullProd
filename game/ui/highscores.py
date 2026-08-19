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

**Renaming a row: the screen edits, the HOST writes.** A row can be selected
(click, or Up/Down) and its NAME edited in place — ``player_intro.py``'s
text-entry state machine verbatim (return / escape / backspace / printable,
max 20 chars), with the RENAME button doubling as SAVE while editing. Because
``game/ui`` does no disk I/O, committing does not write: it parks the result on
``pending_rename`` and returns the ``"rename"`` action, which ``Shell`` turns
into the host intent ``"rename_highscore"``; the host calls
``game.core.highscores.rename_entry`` and hands the rewritten document back
through ``set_highscores(doc, keep_view=True)`` — ``keep_view`` because
rewinding to the top after renaming row 40 is exactly the wrong place to leave
the player.

**``self.rows`` carries the DISK INDEX with every row** (``ranked_rows``, not
``ranked``): the table is sorted by ``round_reached`` and the file is in play
order, so a rename addressed by display position would rename the wrong run.
"""
from types import SimpleNamespace

from engine.render import HudRect

from game.core.highscores import ranked_rows

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, contains, submit_centered, submit_text
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

#: Name length cap while renaming — ``player_intro.py``'s ``_MAX_CHARS``, so
#: a name cannot be typed here that the identity prompt could not have typed.
_MAX_CHARS = 20
#: Fill behind the selected row.
_SEL_FILL = (34, 52, 38)

SCREEN_ID = "highscores"


class HighscoresScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        #: The document the host handed down (``None`` until the first
        #: ``set_doc``) and its rows. Rows are ``(disk_index, entry)`` pairs
        #: from ``game.core.highscores.ranked_rows`` — already sorted by
        #: ``round_reached`` DESC, so this screen never re-sorts.
        self.doc = None
        self.rows = []
        #: The plain integer row offset (see the module docstring). The
        #: SCROLLING VERB is the ``scroll()`` METHOD below — the host's
        #: ``Shell.handle_scroll`` duck-types on ``callable(screen.scroll)``.
        self.scroll_offset = 0
        self.visible_rows = 1
        #: Rename state. ``selected`` indexes ``self.rows`` (a DISPLAY row, not
        #: a disk index) or is ``None``; ``editing``/``edit_text`` are the
        #: text-field state machine; ``pending_rename`` is the
        #: ``(disk_index, name)`` the host reads after a ``"rename"`` action.
        self.selected = None
        self.editing = False
        self.edit_text = ""
        self.pending_rename = None
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        self.rename_btn = Button((0, 0, 100, 23), "RENAME")
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

    def set_doc(self, doc, keep_view=False):
        """Store the high-score document the host loaded and rewind to the top.

        Called every time the screen is opened (the host re-reads the file
        first, so a run that just finished appears immediately).

        ``keep_view=True`` keeps the scroll offset and the selected row instead
        — the host passes it when re-handing the SAME document after a rename,
        where jumping back to rank 1 would lose the player's place. A rename
        cannot re-order the table (``name`` is not a sort key), so the
        selection still points at the row it did before."""
        self.doc = doc
        self.rows = ranked_rows(doc)
        self.editing = False
        self.edit_text = ""
        self.pending_rename = None
        if keep_view:
            if self.selected is not None and self.selected >= len(self.rows):
                self.selected = None
            self.scroll(0)          # re-clamp against the new row count
        else:
            self.selected = None
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

    # -- rename ------------------------------------------------------------

    def _row_rect(self, display_row):
        """The full-width band of one VISIBLE display row, or ``None`` when it
        is scrolled out. Anchored on the header rect like every column is, so a
        skinned header still moves the hit-boxes with the table."""
        offset = display_row - self.scroll_offset
        if not 0 <= offset < self.visible_rows:
            return None
        return (self._header.rect[0] - 4,
                self._viewport_top + offset * _ROW_H - 2,
                _TABLE_W + 8, _ROW_H)

    def _row_at(self, mx, my):
        """The display row under the cursor, or ``None``."""
        for i in range(self.scroll_offset,
                       min(len(self.rows), self.scroll_offset + self.visible_rows)):
            rect = self._row_rect(i)
            if rect is not None and contains(rect, mx, my):
                return i
        return None

    def _reveal(self):
        """Scroll the selected row back into the viewport (keyboard nav)."""
        if self.selected is None:
            return
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + self.visible_rows:
            self.scroll_offset = self.selected - self.visible_rows + 1
        self.scroll(0)

    def _move_selection(self, step):
        if not self.rows:
            return
        if self.selected is None:
            self.selected = self.scroll_offset   # first press: the top row
        else:
            self.selected = max(0, min(len(self.rows) - 1,
                                       self.selected + step))
        self._reveal()

    def begin_edit(self):
        """Focus the selected row's NAME for typing. No-op with no selection."""
        if self.selected is None or self.selected >= len(self.rows):
            return
        self.editing = True
        self.edit_text = str(self.rows[self.selected][1].get("name", ""))

    def cancel_edit(self):
        """Abandon the edit; the row keeps the name it had."""
        self.editing = False
        self.edit_text = ""

    def _commit_edit(self):
        """Park ``(disk_index, typed_name)`` for the host and return
        ``"rename"``. The DISK index, never the display row — see the module
        docstring. Normalising a blank name is ``highscores.rename_entry``'s
        job, exactly as ``make_entry`` owns it for a new run."""
        if not self.editing or self.selected is None:
            return None
        disk_index, _entry = self.rows[self.selected]
        self.pending_rename = (disk_index, self.edit_text)
        self.editing = False
        return "rename"

    def _rename_pressed(self):
        """The RENAME/SAVE button: SAVE while editing, else start editing."""
        if self.editing:
            return self._commit_edit()
        self.begin_edit()
        return None

    # -- layout ------------------------------------------------------------

    def layout(self, view_w, view_h):
        self.back_btn.rect = (view_w // 2 - 50, view_h - 45, 100, 23)
        # LEFT of BACK, which keeps its shipped geometry — a second button on
        # this screen must not move the one players already know.
        self.rename_btn.rect = (view_w // 2 - 158, view_h - 45, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, 35, 0, 0)
        self._header.rect = (view_w // 2 - _TABLE_W // 2, _TABLE_TOP,
                             _TABLE_W, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "header": ("label", self._header),
            "btn_rename": ("button", self.rename_btn),
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
        # SAVE while editing, RENAME otherwise — and disabled outright with no
        # row picked, so the button can never commit an empty selection.
        self.rename_btn.label = "SAVE" if self.editing else "RENAME"
        self.rename_btn.enabled = self.selected is not None
        self.back_btn.enabled = True
        for btn in (self.rename_btn, self.back_btn):
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """``"back"``, ``"rename"`` (a commit — read ``pending_rename``) or
        ``None``. An invisible button is never hit (10L-B).

        Clicking a table row SELECTS it; clicking the already-selected row a
        second time starts editing it, and clicking a different row while
        editing abandons the edit (``player_intro``'s click-to-focus, applied
        to rows instead of one fixed box)."""
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of,
            {"btn_back": "back", "btn_rename": "rename"})
        if layer_action == "rename":
            return self._rename_pressed()
        if layer_action is not None:
            return layer_action
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        if is_visible(self.rename_btn) and self.rename_btn.hit(mx, my):
            return self._rename_pressed()
        row = self._row_at(mx, my)
        if row is None:
            return None
        if self.editing:
            if row == self.selected:
                return None          # clicking the row being edited: no change
            self.cancel_edit()
        if row == self.selected:
            self.begin_edit()
        else:
            self.selected = row
        return None

    def handle_key(self, char, key):
        """``"back"`` (Esc), ``"rename"`` (Enter while editing) or ``None``.

        While editing, this is ``player_intro``'s text-entry state machine and
        NOTHING else reaches the table — Esc cancels the edit rather than
        leaving the screen, which is the whole reason it is checked first.
        Otherwise Up/Down move the SELECTION (scrolling to follow it) and Enter
        starts editing the selected row."""
        if self.editing:
            if key == "return":
                return self._commit_edit()
            if key == "escape":
                self.cancel_edit()
                return None
            if key == "backspace":
                self.edit_text = self.edit_text[:-1]
            elif char and char.isprintable() and len(self.edit_text) < _MAX_CHARS:
                self.edit_text += char
            return None
        if key == "escape":
            return "back"
        if key == "return":
            self.begin_edit()
        elif key == "up":
            self._move_selection(-1)
        elif key == "down":
            self._move_selection(1)
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
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        for btn in (self.rename_btn, self.back_btn):
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
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
        for offset, (_disk_index, entry) in enumerate(window):
            i = self.scroll_offset + offset
            picked = i == self.selected
            if picked:
                rect = self._row_rect(i)
                if rect is not None:
                    renderer.submit_hud(HudRect(rect, _SEL_FILL))
                    renderer.submit_hud(HudRect(
                        rect, widgets.C_GOLD if self.editing
                        else widgets.C_UI_BORDER, width=1))
            # The NAME cell is the live text field while this row is edited.
            name = (self.edit_text + "_" if picked and self.editing
                    else str(entry.get("name", "")))
            self._submit_row(renderer, (
                name,
                skill_label(entry.get("skill")),
                str(entry.get("round_reached", 0)),
                str(entry.get("buildings_placed", 0)),
                str(entry.get("enemies_killed", 0)),
            ), y, "md",
                widgets.C_GOLD if picked and self.editing else widgets.C_UI_TEXT)
            y += _ROW_H
        # ONE hint line, and the edit owns it while an edit is live — a player
        # mid-rename needs the keys, not the scroll position.
        if self.editing:
            hint = "[enter] save   [esc] cancel"
        elif self.selected is not None:
            hint = "[enter] rename this run"
        elif len(self.rows) > self.visible_rows:
            hint = (f"{self.scroll_offset + 1}-{self.scroll_offset + len(window)}"
                    f" of {len(self.rows)}  -  scroll for more")
        else:
            hint = None
        if hint:
            submit_centered(renderer, hint, cx, self.back_btn.rect[1] - 11,
                            "sm", widgets.C_UI_TEXT_DIM)
