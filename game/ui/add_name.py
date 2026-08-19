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

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import (
    Button, anim_ms, contains, label_holder, submit_centered, submit_label,
    submit_panel, submit_text
)
from . import widgets
from .strings import T

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
        # "ADD NAME" needed 91px in this 80px button under the SHIPPED pixel
        # font (data/ui/active_font.json -> pixel_emulator); "ADD" needs 37,
        # and the screen title already says "ADD A NAME".
        self.add_btn = Button((0, 0, 80, 20), "ADD")
        self.back_btn = Button((0, 0, 65, 20), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._panel = SimpleNamespace(rect=(0, 0, _PW, _PH), skin=None)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xl",
                                      text_color=widgets.C_GOLD, label="ADD A NAME",
                                      visible=True)
        # -- UT-5: the three remaining lines of copy, as id'd label holders.
        # `msg_text`'s CONTENT is runtime-authored (it quotes the name the
        # player typed), so it draws through submit_label's `text=` hatch —
        # the holder still owns position/font/colour, and the three variants
        # themselves are `add_name.msg_*` templates. --
        self._hint = label_holder(text_id="add_name.hint", font_key="sm",
                                  text_color=widgets.C_UI_TEXT_DIM,
                                  align="center")
        self._msg_text = label_holder(font_key="sm", align="center")
        self._pool_text = label_holder(text_id="add_name.pool_count",
                                       font_key="sm",
                                       text_color=widgets.C_UI_TEXT_DIM)
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
        self._hint.rect = (x + _PW // 2, y + 31, 0, 0)
        self._msg_text.rect = (x + _PW // 2, y + 78, 0, 0)
        self._pool_text.rect = (x + 12, y + _PH - 39, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "panel": ("panel", self._panel),
            "title": ("label", self._title),
            "btn_add": ("button", self.add_btn),
            "btn_back": ("button", self.back_btn),
            "hint": ("label", self._hint),
            "msg_text": ("label", self._msg_text),
            "pool_count": ("label", self._pool_text),
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
            self.msg = T("add_name.msg_added", name=stripped)
            self.msg_color = widgets.C_GREEN_STAT
            self.name = ""
        elif not stripped:
            self.msg, self.msg_color = T("add_name.msg_empty"), widgets.C_RED
        else:
            self.msg = T("add_name.msg_duplicate", name=stripped)
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
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back", "btn_add": "add"})
        if layer_action is not None:
            return layer_action
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
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of, t)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        if is_visible(self._panel):
            submit_panel(renderer, self.rect, fill=widgets.C_UI_PANEL,
                        border=widgets.C_UI_BORDER, skin=self._panel.skin,
                        tint=getattr(self._panel, "tint", None), anim_ms=t)
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        submit_label(renderer, self._hint)

        nx, ny, nw, nh = self.name_rect
        renderer.submit_hud(HudRect(self.name_rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect(
            self.name_rect, widgets.C_GOLD if self.editing else widgets.C_UI_BORDER, width=1))
        if self.name or self.editing:
            shown = self.name + ("_" if self.editing else "")
            tcol = widgets.C_UI_TEXT
        else:
            # UT-5: string-table copy, but no id of its own — its position is
            # derived inline from ``name_rect`` and the anchor-rect convention
            # says an id needs a STORED rect first.
            shown = T("add_name.placeholder")
            tcol = widgets.C_UI_TEXT_DIM
        submit_text(renderer, shown, (nx + 4, ny + 4), "md", tcol)

        submit_label(renderer, self._msg_text, text=self.msg or None,
                     color=self.msg_color)
        submit_label(renderer, self._pool_text, count=self.pool_count)

        if is_visible(self.add_btn):
            self.add_btn.submit(renderer, anim_ms=t, **button_kwargs(self.add_btn))
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of, t)
