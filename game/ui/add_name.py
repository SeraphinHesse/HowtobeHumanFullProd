"""Add-a-Name screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/add_name_menu.py``: a centred modal
that types a building name for the nameplate random-name pool. The text-entry
state machine is the exact ``building_ui.ConstructPreview.handle_key`` pattern
(return/escape/backspace/printable, max 20 chars). This screen NEVER writes to
disk — it exposes the typed ``name`` and returns action strings; the host does
the ``game.core.append_random_name`` write and reports the outcome back via
``set_result`` (keeping ``game/ui`` pygame-and-IO-free).

10L-B: ``ids`` names ``backdrop``, ``panel`` (already routed through
``submit_panel`` — a skin override works for free), ``title`` ("ADD A NAME"),
``btn_add``, ``btn_back``. An invisible button is neither drawn nor
hit-tested.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, contains, submit_centered, submit_panel, submit_text
)
from . import widgets

_MAX_CHARS = 20
_BG = (12, 20, 14)
_PW, _PH = 230, 130

SCREEN_ID = "add_name"


class AddNameScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.name = ""
        self.editing = True          # focused on open so typing works instantly
        self.msg = ""
        self.msg_color = widgets.C_UI_TEXT_DIM
        self.pool_count = 0
        self.add_btn = Button((0, 0, 80, 20), "ADD NAME")
        self.back_btn = Button((0, 0, 65, 20), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._panel = SimpleNamespace(rect=(0, 0, _PW, _PH), skin=None)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xl",
                                      text_color=widgets.C_GOLD, label="ADD A NAME",
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        x = view_w // 2 - _PW // 2
        y = view_h // 2 - _PH // 2
        self.rect = (x, y, _PW, _PH)
        self.name_rect = (x + 12, y + 54, _PW - 24, 18)
        self.add_btn.rect = (x + 12, y + _PH - 28, 80, 20)
        self.back_btn.rect = (x + _PW - 12 - 65, y + _PH - 28, 65, 20)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._panel.rect = self.rect
        self._title.rect = (x + _PW // 2, y + 10, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "panel": ("panel", self._panel),
            "title": ("label", self._title),
            "btn_add": ("button", self.add_btn),
            "btn_back": ("button", self.back_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)
        self.rect = self._panel.rect  # coherent: a moved panel moves its hit-rect

    def reset(self, pool_count=0):
        """Clear the field/feedback — called each time the screen is opened."""
        self.name = ""
        self.editing = True
        self.msg = ""
        self.msg_color = widgets.C_UI_TEXT_DIM
        self.pool_count = pool_count

    def set_result(self, added, name, pool_count):
        """Host reports the outcome of a commit attempt so the screen can show
        feedback (added / blank / duplicate) and refresh the pool count."""
        stripped = name.strip()
        if added:
            self.msg, self.msg_color = f"Added '{stripped}'!", widgets.C_GREEN_STAT
            self.name = ""
        elif not stripped:
            self.msg, self.msg_color = "Type a name first.", widgets.C_RED
        else:
            self.msg = f"'{stripped}' is already in the list."
            self.msg_color = widgets.C_GOLD
        self.pool_count = pool_count

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn in (self.add_btn, self.back_btn):
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"back"`` / ``"add"`` / ``"name"`` (box focus) / ``None``.
        An invisible button is never hit (10L-B)."""
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        if is_visible(self.add_btn) and self.add_btn.hit(mx, my):
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
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        x, y, w, h = self.rect
        if is_visible(self._panel):
            submit_panel(renderer, self.rect, fill=widgets.C_UI_PANEL,
                        border=widgets.C_UI_BORDER, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None), anim_ms=t)
        cx = x + w // 2
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        submit_centered(renderer, "Appears on the building-naming dice button.",
                        cx, y + 31, "sm", widgets.C_UI_TEXT_DIM)

        nx, ny, nw, nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect, widgets.C_GOLD if self.editing else widgets.C_UI_BORDER, width=1))
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = widgets.C_UI_TEXT
        else:
            shown = "type a name..."
            tcol = widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 4, ny + 4), "md", tcol)

        if self.msg:
            submit_centered(renderer, self.msg, cx, y + 78, "sm", self.msg_color)
        submit_text(renderer, f"Names in pool: {self.pool_count}",
                    (x + 12, y + _PH - 39), "sm", widgets.C_UI_TEXT_DIM)

        if is_visible(self.add_btn):
            self.add_btn.submit(renderer, anim_ms=t, **button_kwargs(self.add_btn))
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
