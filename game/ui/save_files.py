"""Save Files screen (SaveGamePLAN SG-6).

A full-screen menu in the ``highscores.py`` shape (backdrop -> title -> body
-> BACK button), NOT a modal — reached from the main menu's own SAVE FILES
row and owns its own ``GameState.SAVE_FILES``. Code-only, deliberately (the
``debug_settings.py``/``highscores.py`` precedent): no
``data/ui/screens/save_files.json``, no ``screen_defaults.json`` entry, not
in ``tools/export_ui_layouts.py``'s ``SCREEN_IDS``.

**This screen does NO disk I/O directly for its slot LIST** — the host loads
``scores/saves/index.json`` through ``game.core.savegame`` and hands the
document down via ``set_index`` (the ``Shell.set_highscores`` precedent).
Pin/delete ARE round-tripped through the host, though: `hit()` returns an
action tuple (``("load", slot_id)`` / ``("pin", slot_id)`` /
``("delete", slot_id)`` / ``"back"`` / ``None``) for `main.py` to execute
against ``game.core.savegame``, then call `set_index` again with the fresh
result — this screen never calls `savegame.add_slot`/`set_pinned`/
`remove_slot` itself, keeping `game/ui` IO-free.

**No minimap** (removed after a live-testing report — it was cut from the
save doc/schema/assembly too, not just this screen; see game/CLAUDE.md's
autosave section). Each row shows only the timestamp and round reached.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, submit_centered, submit_text
from . import widgets

_BG = (12, 20, 14)

_ROW_H = 26
_ROW_PAD = 8
_PIN_W, _DEL_W, _BTN_H = 34, 46, 20
_LIST_TOP = 68
_BOTTOM_PAD = 12
_LIST_W = 460

SCREEN_ID = "save_files"


def _format_timestamp(iso_str):
    """``created_at``'s ISO-8601 value (``YYYY-MM-DDTHH:MM:SS``, SG-1's
    ``timespec="seconds"``), for DISPLAY only — the stored value keeps its
    full precision. Reformatted to ``DD-MM-YYYY HH:MM`` (user decisions:
    day-month-year date order, and seconds dropped). Malformed/short input
    (a fixture stub, a future format change) falls back to the raw string
    rather than raising — this is a label, never a parse site."""
    if len(iso_str) < 16 or iso_str[10] != "T":
        return iso_str
    year, month, day = iso_str[0:4], iso_str[5:7], iso_str[8:10]
    return f"{day}-{month}-{year} {iso_str[11:16]}"


class SaveFilesScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        #: The index document the host handed down (``None`` until the first
        #: ``set_index``) and its slots, in creation order (oldest first) —
        #: reversed for display so the newest save is always on top.
        self.index_doc = None
        self.slots = []
        self.scroll_offset = 0
        self.visible_rows = 1
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        #: One (load_btn, pin_btn, del_btn) triple per VISIBLE row, rebuilt
        #: every layout() — the construct-card precedent (dynamic-count
        #: content gets rebuilt, never grown/shrunk in place).
        self._row_buttons = []
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD,
                                      label="SAVE FILES", visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    # -- host-facing ---------------------------------------------------

    def set_index(self, index_doc):
        """Store the save-slot index the host loaded, newest first, and
        rewind to the top. Called every time the screen is opened (the host
        re-reads the file first, so a round-5 autosave taken this session
        shows immediately) and again after a pin/delete round-trips."""
        self.index_doc = index_doc
        self.slots = list(reversed(index_doc["slots"])) if index_doc else []
        self.scroll_offset = 0

    def scroll(self, dy):
        """Move the viewport by ``dy`` ROWS (the ``highscores.py`` contract
        exactly — sign, clamping, ``Shell.handle_scroll`` duck-typing)."""
        limit = max(0, len(self.slots) - self.visible_rows)
        self.scroll_offset = max(0, min(limit, self.scroll_offset + dy))

    # -- layout ----------------------------------------------------------

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
        self._left = view_w // 2 - _LIST_W // 2
        viewport_h = self.back_btn.rect[1] - _BOTTOM_PAD - _LIST_TOP
        self.visible_rows = max(1, viewport_h // _ROW_H)
        self.scroll(0)   # re-clamp: a smaller viewport must not strand the view
        self._build_row_buttons()

    def _build_row_buttons(self):
        """One PIN/DELETE button pair per visible row slot (positional, not
        per-save-id — the row at index i always uses buttons[i], whichever
        slot is currently scrolled into it). The LOAD target is the row
        itself (see hit()), so it needs no Button of its own."""
        right = self._left + _LIST_W
        self._row_buttons = []
        for i in range(self.visible_rows):
            y = _LIST_TOP + i * _ROW_H + (_ROW_H - _BTN_H) // 2
            pin_btn = Button((right - _DEL_W - 4 - _PIN_W, y, _PIN_W, _BTN_H),
                             "PIN", font_key="sm")
            del_btn = Button((right - _DEL_W, y, _DEL_W, _BTN_H),
                             "DEL", font_key="sm")
            self._row_buttons.append((pin_btn, del_btn))

    # -- per-frame ---------------------------------------------------------

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        self.back_btn.enabled = True
        self.back_btn.hover(mx, my, mouse_down)
        self.back_btn.hovered = self.back_btn.hovered and is_visible(self.back_btn)
        self.back_btn.update(dt)
        window = self.slots[self.scroll_offset:
                            self.scroll_offset + self.visible_rows]
        for i, (pin_btn, del_btn) in enumerate(self._row_buttons):
            if i >= len(window):
                continue
            slot = window[i]
            pin_btn.label = "UNPIN" if slot.get("pinned") else "PIN"
            for btn in (pin_btn, del_btn):
                btn.enabled = True
                btn.hover(mx, my, mouse_down)
                btn.update(dt)

    def hit(self, mx, my):
        """``"back"`` / ``("load"|"pin"|"delete", slot_id)`` / ``None``.
        PIN/DELETE are checked BEFORE the row's own load target, since they
        sit visually on top of it."""
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back"})
        if layer_action is not None:
            return layer_action
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        window = self.slots[self.scroll_offset:
                            self.scroll_offset + self.visible_rows]
        for i, (pin_btn, del_btn) in enumerate(self._row_buttons):
            if i >= len(window):
                continue
            slot = window[i]
            if pin_btn.hit(mx, my):
                return ("pin", slot["slot_id"])
            if del_btn.hit(mx, my):
                return ("delete", slot["slot_id"])
            row_top = _LIST_TOP + i * _ROW_H
            if (self._left <= mx <= self._left + _LIST_W
                    and row_top <= my <= row_top + _ROW_H):
                return ("load", slot["slot_id"])
        return None

    def handle_key(self, char, key):
        """``"back"`` (Esc) or ``None``; Up/Down scroll by one row."""
        if key == "escape":
            return "back"
        if key == "up":
            self.scroll(-1)
        elif key == "down":
            self.scroll(1)
        return None

    # -- draw ----------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.back_btn))
        cx = view_w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)

        if not self.slots:
            submit_centered(renderer, "No saves yet.", cx, _LIST_TOP + 10,
                            "md", widgets.C_UI_TEXT_DIM)
            return

        window = self.slots[self.scroll_offset:
                            self.scroll_offset + self.visible_rows]
        for i, slot in enumerate(window):
            y = _LIST_TOP + i * _ROW_H
            label = (f"Round {slot.get('round_num', 0)}  -  "
                    f"{_format_timestamp(slot.get('created_at', ''))}")
            submit_text(renderer, label, (self._left + _ROW_PAD,
                                          y + _ROW_H // 2 - 6), "sm",
                       widgets.C_UI_TEXT)
            pin_btn, del_btn = self._row_buttons[i]
            for btn in (pin_btn, del_btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
        if len(self.slots) > self.visible_rows:
            submit_centered(
                renderer,
                f"{self.scroll_offset + 1}-{self.scroll_offset + len(window)}"
                f" of {len(self.slots)}  -  scroll for more",
                cx, self.back_btn.rect[1] - 11, "sm", widgets.C_UI_TEXT_DIM)
