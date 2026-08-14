"""Settings screen + session settings (Phase 9H).

``SessionSettings`` is the pure, SESSION-ONLY (never persisted) override store —
seeded from the ``ui`` balancing FX flags at boot, mutated by this screen, read
by the host. ``SettingsScreen`` ports the prototype's ``src/ui/settings_menu.py``
onto the ``game_over.py`` template: a display-mode ``< value >`` cycler, the FX
ON/OFF toggles (income floaters / background art / gore), an inert audio slider
(no audio system yet — drawn, not wired), and BACK. Shared by the main-menu and
the pause-menu entry points; the shell tracks which caller BACK returns to.

10L-B: ``ids`` names ``backdrop``, ``title`` ("SETTINGS") + every button (the
display-mode cycler arrows, SET DEFAULT, the three FX toggles, BACK). An
invisible button is neither drawn nor hit-tested.

**SET DEFAULT** persists the currently-selected display mode as the BOOT mode.
This screen stays pure: the button only returns the ``"save_display_default"``
action, and the host writes ``data/display.json`` (the same "anything touching
disk is an intent" rule the rest of the shell follows). ``saved_default`` is
the host-set string of what is on disk today (``None`` = unknown, e.g. a bare
test/exporter construction — then no line is drawn).
"""
from dataclasses import dataclass
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import (
    Button, anim_ms, label_holder, submit_centered, submit_label
)
from . import widgets

DISPLAY_MODES = ("windowed", "borderless", "fullscreen")
_BG = (12, 20, 14)
# (SessionSettings attr, row-label STRING ID) — the FX toggle rows. UT-5: the
# second element is a `data/ui/strings.json` key now, not the literal copy; it
# is still the tuple's middle element so `screen.toggles`'s (attr, label, btn)
# shape is unchanged for its readers.
_TOGGLES = [
    ("income_floaters", "settings.toggle.income_floaters"),
    ("bg_art", "settings.toggle.bg_art"),
    ("gore", "settings.toggle.gore"),
]
# SessionSettings attr -> the ids name a designer picks that toggle by (10L-B)
_TOGGLE_IDS = {
    "income_floaters": "btn_toggle_income_floaters",
    "bg_art": "btn_toggle_bg_art",
    "gore": "btn_toggle_gore",
}
# UT-5: SessionSettings attr -> the label widget's id (the sibling of the
# button id above — a row's NAME and its ON/OFF control are independently
# placeable, the per-stat rule building_ui.py already follows).
_TOGGLE_LABEL_IDS = {
    "income_floaters": "label_income_floaters",
    "bg_art": "label_bg_art",
    "gore": "label_gore",
}

SCREEN_ID = "settings"


@dataclass
class SessionSettings:
    # Fullscreen is the shipped default (data/display.json's `display_mode`
    # is what the host actually seeds this from at boot; this literal is the
    # bare-construction fallback and matches it).
    display_mode: str = "fullscreen"     # one of DISPLAY_MODES
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
    def __init__(self, view_w, view_h, settings, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.settings = settings
        self.dm_left = Button((0, 0, 20, 20), "<")
        self.dm_right = Button((0, 0, 20, 20), ">")
        # "SET DEFAULT" needed 91px in this 85px button under the SHIPPED
        # pixel font; "DEFAULT" needs 59. The row it sits on already reads
        # "Display mode", so the verb is redundant.
        self.default_btn = Button((0, 0, 85, 20), "DEFAULT", font_key="md")
        # What data/display.json currently boots into; host-set, None = unknown.
        self.saved_default = None
        self.toggles = [(attr, text_id, Button((0, 0, 45, 20), "ON"))
                        for attr, text_id in _TOGGLES]
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        # -- UT-5: every remaining line of copy on this screen, as an id'd
        # label holder. Anchors are stored in layout() (the text-label
        # convention), so the exporter reads a real position and a rect
        # override moves the text. --
        self._dm_label = label_holder(text_id="settings.display_mode",
                                      align="center")
        # The display-mode VALUE is a runtime enum pick, so it goes out
        # through submit_label's `text=` hatch — the holder still owns
        # position/font/colour.
        self._dm_value = label_holder(font_key="lg", align="center")
        self._toggle_labels = {
            attr: label_holder(text_id=text_id) for attr, text_id in _TOGGLES}
        self._audio_label = label_holder(text_id="settings.master_audio")
        self._audio_note = label_holder(text_id="settings.no_audio",
                                        font_key="sm", align="center")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD, label="SETTINGS",
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        cx = view_w // 2
        self._cx = cx
        self._top = view_h // 2 - 90
        self._dm_y = self._top + 35                 # display-mode value row
        self.dm_left.rect = (cx - 75, self._dm_y - 3, 20, 20)
        self.dm_right.rect = (cx + 55, self._dm_y - 3, 20, 20)
        # Right of the ">" arrow, clear of the FX toggle column below.
        self.default_btn.rect = (cx + 85, self._dm_y - 3, 85, 20)
        y = self._dm_y + 35
        self._row_y = []
        for attr, _text_id, btn in self.toggles:
            self._row_y.append(y)
            btn.rect = (cx + 30, y - 4, 45, 20)
            self._toggle_labels[attr].rect = (cx - 75, y, 0, 0)
            y += 28
        self._slider_y = y + 5
        self._slider_rect = (cx - 45, self._slider_y, 90, 6)
        self.back_btn.rect = (cx - 50, y + 35, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (cx, self._top, 0, 0)
        self._dm_label.rect = (cx, self._dm_y - 17, 0, 0)
        self._dm_value.rect = (cx, self._dm_y, 0, 0)
        self._audio_label.rect = (cx - 75, self._slider_y - 12, 0, 0)
        self._audio_note.rect = (cx, self._slider_y + 10, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_dm_left": ("button", self.dm_left),
            "btn_dm_right": ("button", self.dm_right),
            "btn_set_default": ("button", self.default_btn),
            "btn_back": ("button", self.back_btn),
            "dm_label": ("label", self._dm_label),
            "dm_value": ("label", self._dm_value),
            "audio_label": ("label", self._audio_label),
            "audio_note": ("label", self._audio_note),
        }
        for attr, _text_id, btn in self.toggles:
            self.ids[_TOGGLE_IDS[attr]] = ("button", btn)
            self.ids[_TOGGLE_LABEL_IDS[attr]] = ("label",
                                                 self._toggle_labels[attr])
        self.skinning.apply(self.screen_id, self.ids)

    def _buttons(self):
        yield self.dm_left
        yield self.dm_right
        yield self.default_btn
        for _attr, _text_id, btn in self.toggles:
            yield btn
        yield self.back_btn

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for _attr, _text_id, btn in self.toggles:
            btn.label = "ON" if getattr(self.settings, _attr) else "OFF"
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """Return ``"back"`` / ``"set_display_mode"`` (host must apply it) or
        ``None`` (FX toggles mutate ``settings`` in place). An invisible
        button is never hit (10L-B)."""
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        i = DISPLAY_MODES.index(self.settings.display_mode)
        if is_visible(self.dm_left) and self.dm_left.hit(mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i - 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        if is_visible(self.dm_right) and self.dm_right.hit(mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i + 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        for attr, _text_id, btn in self.toggles:
            if is_visible(btn) and btn.hit(mx, my):
                setattr(self.settings, attr, not getattr(self.settings, attr))
                return None
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        cx = self._cx
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)

        submit_label(renderer, self._dm_label, color=widgets.C_UI_TEXT)
        submit_label(renderer, self._dm_value, color=widgets.C_GOLD,
                     text=self.settings.display_mode.upper())
        if is_visible(self.dm_left):
            self.dm_left.submit(renderer, anim_ms=t, **button_kwargs(self.dm_left))
        if is_visible(self.dm_right):
            self.dm_right.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.dm_right))

        for attr, _text_id, btn in self.toggles:
            submit_label(renderer, self._toggle_labels[attr],
                         color=widgets.C_UI_TEXT)
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))

        # inert audio slider (no audio system) — drawn only
        sx, sy, sw, sh = self._slider_rect
        submit_label(renderer, self._audio_label, color=widgets.C_UI_TEXT)
        renderer.submit_hud(HudRect(self._slider_rect, widgets.C_UI_BORDER))
        renderer.submit_hud(HudRect(
            (sx, sy, int(sw * self.settings.volume), sh), widgets.C_UI_BTN))
        submit_label(renderer, self._audio_note, color=widgets.C_UI_TEXT_DIM)

        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
