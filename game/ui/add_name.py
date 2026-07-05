"""Add-a-Name screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/add_name_menu.py``: a centred modal
that types a building name for the nameplate random-name pool. The text-entry
state machine is the exact ``building_ui.ConstructPreview.handle_key`` pattern
(return/escape/backspace/printable, max 20 chars). This screen NEVER writes to
disk — it exposes the typed ``name`` and returns action strings; the host does
the ``game.core.append_random_name`` write and reports the outcome back via
``set_result`` (keeping ``game/ui`` pygame-and-IO-free).
"""
from engine.render import HudRect

from .widgets import (
    C_GOLD, C_GREEN_STAT, C_PANEL_STONE, C_RED, C_UI_BORDER, C_UI_PANEL,
    C_UI_TEXT, C_UI_TEXT_DIM, Button, contains, submit_centered, submit_panel,
    submit_text,
)

_MAX_CHARS = 20
_BG = (12, 20, 14)
_PW, _PH = 460, 260


class AddNameScreen:
    def __init__(self, view_w, view_h):
        self.name = ""
        self.editing = True          # focused on open so typing works instantly
        self.msg = ""
        self.msg_color = C_UI_TEXT_DIM
        self.pool_count = 0
        self.add_btn = Button((0, 0, 160, 40), "ADD NAME")
        self.back_btn = Button((0, 0, 130, 40), "BACK")
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        x = view_w // 2 - _PW // 2
        y = view_h // 2 - _PH // 2
        self.rect = (x, y, _PW, _PH)
        self.name_rect = (x + 24, y + 108, _PW - 48, 36)
        self.add_btn.rect = (x + 24, y + _PH - 56, 160, 40)
        self.back_btn.rect = (x + _PW - 24 - 130, y + _PH - 56, 130, 40)

    def reset(self, pool_count=0):
        """Clear the field/feedback — called each time the screen is opened."""
        self.name = ""
        self.editing = True
        self.msg = ""
        self.msg_color = C_UI_TEXT_DIM
        self.pool_count = pool_count

    def set_result(self, added, name, pool_count):
        """Host reports the outcome of a commit attempt so the screen can show
        feedback (added / blank / duplicate) and refresh the pool count."""
        stripped = name.strip()
        if added:
            self.msg, self.msg_color = f"Added '{stripped}'!", C_GREEN_STAT
            self.name = ""
        elif not stripped:
            self.msg, self.msg_color = "Type a name first.", C_RED
        else:
            self.msg = f"'{stripped}' is already in the list."
            self.msg_color = C_GOLD
        self.pool_count = pool_count

    def update(self, dt, mx, my):
        for btn in (self.add_btn, self.back_btn):
            btn.enabled = True
            btn.hover(mx, my)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"back"`` / ``"add"`` / ``"name"`` (box focus) / ``None``."""
        if self.back_btn.hit(mx, my):
            return "back"
        if self.add_btn.hit(mx, my):
            return "add"
        self.editing = contains(self.name_rect, mx, my)  # click toggles focus
        return "name" if self.editing else None

    def handle_key(self, char, key):
        """Return ``"add"`` (Enter) / ``"back"`` (Esc) / ``None``."""
        if not self.editing:
            return None
        if key == "return":
            return "add"
        if key == "escape":
            return "back"
        if key == "backspace":
            self.name = self.name[:-1]
        elif char and char.isprintable() and len(self.name) < _MAX_CHARS:
            self.name += char
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        x, y, w, h = self.rect
        submit_panel(renderer, self.rect, fill=C_UI_PANEL, border=C_UI_BORDER)
        cx = x + w // 2
        submit_centered(renderer, "ADD A NAME", cx, y + 20, "xl", C_GOLD)
        submit_centered(renderer, "Appears on the building-naming dice button.",
                        cx, y + 62, "sm", C_UI_TEXT_DIM)

        nx, ny, nw, nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect, C_GOLD if self.editing else C_UI_BORDER, width=1))
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = C_UI_TEXT
        else:
            shown = "type a name..."
            tcol = C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 8, ny + 9), "md", tcol)

        if self.msg:
            submit_centered(renderer, self.msg, cx, y + 156, "sm", self.msg_color)
        submit_text(renderer, f"Names in pool: {self.pool_count}",
                    (x + 24, y + _PH - 78), "sm", C_UI_TEXT_DIM)

        self.add_btn.submit(renderer)
        self.back_btn.submit(renderer)
