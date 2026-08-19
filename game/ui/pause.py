"""Pause screen (Phase 9H).

Pure logic. Ports the prototype's ``src/ui/pause_menu.py`` four-button panel
(RESUME / SETTINGS / QUIT TO MENU / QUIT GAME). Drawn OVER the frozen gameplay
(the host freezes the sim in PAUSED). Since 10J the full-screen
``(0, 0, 0, 150)`` alpha dim from the prototype draws behind the panel (the
9H deferral), so the still board reads as paused-in-place.

10L-B: ``ids`` names ``backdrop``, ``title`` ("PAUSED") + one button per row
(the panel body keeps its own fill/border/radius, unskinned — see
``game/ui/CLAUDE.md``). An invisible button is neither drawn nor hit-tested.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, submit_centered
from . import widgets

# (label, action) top-to-bottom
_ITEMS = [
    ("RESUME", "resume"),
    ("SETTINGS", "settings"),
    # "QUIT TO MENU" needed 132px at "lg" in a 120px button under the SHIPPED
    # pixel font; "MAIN MENU" needs 101, and reads the same as game_over.py's
    # button (which took the identical copy fix).
    ("MAIN MENU", "quit_to_menu"),
    ("QUIT GAME", "quit"),
]
_ACTION_IDS = {
    "resume": "btn_resume", "settings": "btn_settings",
    "quit_to_menu": "btn_quit_to_menu", "quit": "btn_quit_game",
}
_PW, _PH = 150, 160
_BTN_W, _BTN_H, _GAP = 120, 23, 6
_TITLE = "PAUSED"

SCREEN_ID = "pause"


class PauseScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), action)
                        for label, action in _ITEMS]
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h),
                                         color=(0, 0, 0, 150))
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xl",
                                      text_color=widgets.C_GOLD, label=_TITLE,
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        px = view_w // 2 - _PW // 2
        py = view_h // 2 - _PH // 2
        self.rect = (px, py, _PW, _PH)
        x = view_w // 2 - _BTN_W // 2
        y = py + 42
        for btn, _ in self.buttons:
            btn.rect = (x, y, _BTN_W, _BTN_H)
            y += _BTN_H + _GAP
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, py + 16, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
        }
        for btn, action in self.buttons:
            self.ids[_ACTION_IDS[action]] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn, _ in self.buttons:
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        # UL-10 reference implementation: a clickable layer is consulted
        # FIRST and falls through unchanged on None. `_ACTION_IDS` reversed
        # is this screen's retarget table — no second copy of the actions.
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of,
            {wid: action for action, wid in _ACTION_IDS.items()})
        if layer_action is not None:
            return layer_action
        # SD-6: the ROUTED-click seam (emits the click sound once); `btn.hit`
        # stays probe-only.
        for btn, action in self.buttons:
            if widgets.click(btn, mx, my):
                return action
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        px, py, pw, ph = self.rect
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        # 10J: the prototype's (0,0,0,150) pause dim over the frozen world
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        renderer.submit_hud(HudRect(self.rect, (24, 20, 40), border_radius=6))
        renderer.submit_hud(HudRect(self.rect, (80, 65, 120), border_radius=6,
                                    width=2))
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        for btn, _ in self.buttons:
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
