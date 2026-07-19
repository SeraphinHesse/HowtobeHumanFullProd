"""Main menu screen (Phase 9H).

Pure logic — the top-level menu the shell shows between runs. Ports the
prototype's ``src/ui/main_menu.py`` button set (START NEW GAME / ADD A NAME /
SETTINGS / CREDITS / QUIT) onto the ``game_over.py`` full-screen template: a
solid ``HudRect`` backdrop, a centred title, and a vertical stack of
``widgets.Button`` click targets. ``hit`` returns the prototype's action strings.
The hand-painted background art draws as a full-view ``HudSprite`` from the
``main_menu_bg`` slot (10K, asset-pipeline sourced; letterbox-safe because the
host's SCALED logical surface is what gets letterboxed); the solid fill stays
beneath it as the missing-art fallback.

10L-B: ``ids`` names the fixed widgets (``backdrop``, ``title``, ``subtitle`` +
one button per menu item) so ``data/ui/screens/main_menu.json`` can
reposition/reskin/retext them; ``skinning.apply()`` runs at the end of
``layout()`` and is a no-op with no override (the golden parity pin). An
invisible button (``visible=False``) is neither drawn nor hit-tested.
"""
from types import SimpleNamespace

from engine.render import HudRect, HudSprite

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import C_GOLD, C_UI_TEXT, Button, anim_ms, submit_centered

_BG = (18, 30, 20)
_BG_SLOT = "main_menu_bg"
_TITLE = "HOW TO BE HUMAN"
_SUBTITLE = "defend the munckins"

# (label, action) top-to-bottom
_ITEMS = [
    ("START NEW GAME", "new_game"),
    ("ADD A NAME", "add_name"),
    ("SETTINGS", "settings"),
    ("CREDITS", "credits"),
    ("QUIT", "quit"),
]
# action -> the ids name a designer picks it by (10L-B)
_ACTION_IDS = {
    "new_game": "btn_new_game", "add_name": "btn_add_name",
    "settings": "btn_settings", "credits": "btn_credits", "quit": "btn_quit",
}
_BTN_W, _BTN_H, _GAP = 320, 52, 14

SCREEN_ID = "main_menu"


class MainMenu:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), action)
                        for label, action in _ITEMS]
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        # 10L-B review fix (HIGH 1): static header text. Its own copy is NOT
        # game-state, so — unlike hud.py's dynamic readouts — "label" is a
        # legitimate override field here too.
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=C_UI_TEXT, label=_TITLE,
                                      visible=True)
        self._subtitle = SimpleNamespace(rect=(0, 0, 0, 0), font_key="md",
                                         text_color=C_GOLD, label=_SUBTITLE,
                                         visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        x = view_w // 2 - _BTN_W // 2
        y = view_h // 2 - 60
        for btn, _ in self.buttons:
            btn.rect = (x, y, _BTN_W, _BTN_H)
            y += _BTN_H + _GAP
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, view_h // 2 - 150, 0, 0)
        self._subtitle.rect = (view_w // 2, view_h // 2 - 110, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "subtitle": ("label", self._subtitle),
        }
        for btn, action in self.buttons:
            self.ids[_ACTION_IDS[action]] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn, _ in self.buttons:
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            # 10L-B: an invisible button is never hovered (force it off
            # rather than skip hover() — no stale True can linger).
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        for btn, action in self.buttons:
            if is_visible(btn) and btn.hit(mx, my):
                return action
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        renderer.submit_hud(HudSprite(_BG_SLOT, (0, 0), (view_w, view_h)))
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        if self._subtitle.visible:
            submit_centered(renderer, self._subtitle.label,
                            self._subtitle.rect[0], self._subtitle.rect[1],
                            self._subtitle.font_key, self._subtitle.text_color)
        for btn, _ in self.buttons:
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
