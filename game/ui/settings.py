"""Settings screen + session settings (Phase 9H).

``SessionSettings`` is the pure, SESSION-ONLY (never persisted) override store —
seeded from the ``ui`` balancing FX flags at boot, mutated by this screen, read
by the host. ``SettingsScreen`` ports the prototype's ``src/ui/settings_menu.py``
onto the ``game_over.py`` template: a display-mode ``< value >`` cycler, the FX
ON/OFF toggles (income floaters / background art / gore), an inert audio slider
(no audio system yet — drawn, not wired), and BACK. Shared by the main-menu and
the pause-menu entry points; the shell tracks which caller BACK returns to.
"""
from dataclasses import dataclass

from engine.render import HudRect

from .widgets import (
    C_GOLD, C_UI_BORDER, C_UI_BTN, C_UI_TEXT, C_UI_TEXT_DIM, Button,
    submit_centered, submit_text,
)

DISPLAY_MODES = ("windowed", "borderless", "fullscreen")
_BG = (12, 20, 14)
# (SessionSettings attr, on-screen label) — the FX toggle rows
_TOGGLES = [
    ("income_floaters", "Income Floaters"),
    ("bg_art", "Background Art"),
    ("gore", "Gore"),
]


@dataclass
class SessionSettings:
    display_mode: str = "windowed"       # one of DISPLAY_MODES
    income_floaters: bool = True
    bg_art: bool = True
    gore: bool = True
    volume: float = 0.8                  # inert (no audio system) — 0..1

    @classmethod
    def from_balance(cls, ui_balance):
        """Seed session overrides from the ``ui`` FX flags (the data defaults)."""
        fx = ui_balance["FX"]
        return cls(
            income_floaters=fx["income_floaters_enabled"],
            bg_art=fx["bg_art"]["enabled"],
            gore=fx["gore_enabled"],
        )


class SettingsScreen:
    def __init__(self, view_w, view_h, settings):
        self.settings = settings
        self.dm_left = Button((0, 0, 40, 40), "<")
        self.dm_right = Button((0, 0, 40, 40), ">")
        self.toggles = [(attr, label, Button((0, 0, 90, 40), "ON"))
                        for attr, label in _TOGGLES]
        self.back_btn = Button((0, 0, 200, 46), "BACK")
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        cx = view_w // 2
        self._cx = cx
        self._top = view_h // 2 - 180
        self._dm_y = self._top + 70                 # display-mode value row
        self.dm_left.rect = (cx - 150, self._dm_y - 6, 40, 40)
        self.dm_right.rect = (cx + 110, self._dm_y - 6, 40, 40)
        y = self._dm_y + 70
        self._row_y = []
        for _attr, _label, btn in self.toggles:
            self._row_y.append(y)
            btn.rect = (cx + 60, y - 8, 90, 40)
            y += 56
        self._slider_y = y + 10
        self._slider_rect = (cx - 90, self._slider_y, 180, 12)
        self.back_btn.rect = (cx - 100, y + 70, 200, 46)

    def _buttons(self):
        yield self.dm_left
        yield self.dm_right
        for _a, _l, btn in self.toggles:
            yield btn
        yield self.back_btn

    def update(self, dt, mx, my):
        for _attr, _label, btn in self.toggles:
            btn.label = "ON" if getattr(self.settings, _attr) else "OFF"
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"back"`` / ``"set_display_mode"`` (host must apply it) or
        ``None`` (FX toggles mutate ``settings`` in place)."""
        if self.back_btn.hit(mx, my):
            return "back"
        i = DISPLAY_MODES.index(self.settings.display_mode)
        if self.dm_left.hit(mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i - 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        if self.dm_right.hit(mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i + 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        for attr, _label, btn in self.toggles:
            if btn.hit(mx, my):
                setattr(self.settings, attr, not getattr(self.settings, attr))
                return None
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        renderer.submit_hud(HudRect((0, 0, view_w, view_h), _BG))
        cx = self._cx
        submit_centered(renderer, "SETTINGS", cx, self._top, "xxl", C_GOLD)

        submit_centered(renderer, "Display Mode", cx, self._dm_y - 34, "md",
                        C_UI_TEXT)
        submit_centered(renderer, self.settings.display_mode.upper(), cx,
                        self._dm_y, "lg", C_GOLD)
        self.dm_left.submit(renderer)
        self.dm_right.submit(renderer)

        for (attr, label, btn), y in zip(self.toggles, self._row_y):
            submit_text(renderer, label, (cx - 150, y), "md", C_UI_TEXT)
            btn.submit(renderer)

        # inert audio slider (no audio system) — drawn only
        sx, sy, sw, sh = self._slider_rect
        submit_text(renderer, "Master Audio", (cx - 150, sy - 24), "md", C_UI_TEXT)
        renderer.submit_hud(HudRect(self._slider_rect, C_UI_BORDER))
        renderer.submit_hud(HudRect(
            (sx, sy, int(sw * self.settings.volume), sh), C_UI_BTN))
        submit_centered(renderer, "(no audio yet)", cx, sy + 20, "sm",
                        C_UI_TEXT_DIM)

        self.back_btn.submit(renderer)
