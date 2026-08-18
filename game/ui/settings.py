"""Settings screen + session settings (Phase 9H).

``SessionSettings`` is the pure, SESSION-ONLY (never persisted) override store —
seeded from the ``ui`` balancing FX flags at boot, mutated by this screen, read
by the host. ``SettingsScreen`` ports the prototype's ``src/ui/settings_menu.py``
onto the ``game_over.py`` template: a display-mode ``< value >`` cycler, the FX
ON/OFF toggles (income floaters / background art / gore), the three SD-6 audio
tracks (Master / Music / SFX — click-to-set, the host applies and persists the
new value on the ``"set_volume"`` action), and BACK. Shared by the main-menu and
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
from engine.render.fonts import layout_h

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
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

# SD-6: the three audio rows, top to bottom. (SessionSettings attr, row-label
# STRING ID, label widget id, bar widget id). The Master row keeps the shipped
# ``audio_label`` id so a designer's existing override still lands on it.
_VOLUME_ROWS = [
    ("master_volume", "settings.master_audio", "audio_label",
     "bar_master_volume"),
    ("music_volume", "settings.music_audio", "label_music_volume",
     "bar_music_volume"),
    ("sfx_volume", "settings.sfx_audio", "label_sfx_volume",
     "bar_sfx_volume"),
]

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
    # SD-6: the three audio levels, 0..1. SESSION fields like every other one
    # here — the persisted document lives outside `data/` and is loaded by the
    # host, which pushes its values in at boot and writes them back on change.
    master_volume: float = 0.8
    music_volume: float = 0.8
    sfx_volume: float = 0.8

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
        # feature: rebindable hotkeys — opens Shell.controls_open (the
        # debug_settings_open overlay-flag pattern), not a new GameState.
        self.controls_btn = Button((0, 0, 90, 23), "CONTROLS", font_key="sm")
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
        # SD-6: one label holder + one bar holder per audio row. A bar is a
        # plain rect holder (the `hud.xp_bar` shape), registered under kind
        # "bar" — it is a 6px track, not a button.
        self._volume_labels = {attr: label_holder(text_id=text_id)
                               for attr, text_id, _lid, _bid in _VOLUME_ROWS}
        self._volume_bars = {attr: SimpleNamespace(rect=(0, 0, 90, 6))
                             for attr, _t, _lid, _bid in _VOLUME_ROWS}
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
        # SD-6: three stacked volume rows. The row step is font-scale (never a
        # bare literal) with a 12px floor — the 6px track plus breathing room.
        self._slider_y = y + 4
        step = max(12, layout_h("sm"))
        self._volume_row_y = []
        for i, (attr, _text_id, _lid, _bid) in enumerate(_VOLUME_ROWS):
            row_y = self._slider_y + i * step
            self._volume_row_y.append(row_y)
            self._volume_bars[attr].rect = (cx - 45, row_y, 90, 6)
            self._volume_labels[attr].rect = (cx - 130, row_y - 3, 0, 0)
        # Clear of the third (SFX) row. `data/ui/screens/settings.json` authors
        # `btn_back`'s rect and an authored rect WINS, so that doc moved in
        # lockstep with this offset (279 -> 296).
        self.back_btn.rect = (cx - 50, y + 52, 100, 23)
        self.controls_btn.rect = (cx + 60, y + 52, 90, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (cx, self._top, 0, 0)
        self._dm_label.rect = (cx, self._dm_y - 17, 0, 0)
        self._dm_value.rect = (cx, self._dm_y, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_dm_left": ("button", self.dm_left),
            "btn_dm_right": ("button", self.dm_right),
            "btn_set_default": ("button", self.default_btn),
            "btn_back": ("button", self.back_btn),
            "btn_controls": ("button", self.controls_btn),
            "dm_label": ("label", self._dm_label),
            "dm_value": ("label", self._dm_value),
        }
        for attr, _text_id, label_id, bar_id in _VOLUME_ROWS:
            self.ids[label_id] = ("label", self._volume_labels[attr])
            self.ids[bar_id] = ("bar", self._volume_bars[attr])
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
        yield self.controls_btn

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
        """Return ``"back"`` / ``"set_display_mode"`` / ``"set_volume"``
        (the host must apply each of those) or
        ``None`` (FX toggles mutate ``settings`` in place). An invisible
        button is never hit (10L-B)."""
        # UL-10: clickable layers first. Only BACK is retargetable here — the
        # display-mode arrows and the FX toggles MUTATE ``settings`` inside
        # their own branch, so returning their action string from here would
        # report a change that never happened. A layer aimed at one of them is
        # therefore unroutable and swallows (Ruling 1), which is the honest
        # answer until those branches grow a shared, side-effect-free seam.
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back"})
        if layer_action is not None:
            return layer_action
        # SD-6: the three volume bars. Click-to-set (no drag — the shell
        # delivers discrete clicks, not a drag stream): the value is the
        # fraction of the track's width the click landed at, clamped.
        for attr, _text_id, _lid, _bid in _VOLUME_ROWS:
            bar = self._volume_bars[attr]
            if is_visible(bar) and widgets.contains(bar.rect, mx, my):
                sx, _sy, sw, _sh = bar.rect
                v = 0.0 if sw <= 0 else (mx - sx) / sw
                setattr(self.settings, attr, min(1.0, max(0.0, v)))
                return "set_volume"
        if widgets.click(self.back_btn, mx, my):
            return "back"
        if widgets.click(self.controls_btn, mx, my):
            return "open_controls"
        i = DISPLAY_MODES.index(self.settings.display_mode)
        if widgets.click(self.dm_left, mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i - 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        if widgets.click(self.dm_right, mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i + 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        for attr, _text_id, btn in self.toggles:
            if widgets.click(btn, mx, my):
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

        # SD-6: Master / Music / SFX, each a label + a click-to-set track.
        for attr, _text_id, _lid, _bid in _VOLUME_ROWS:
            bar = self._volume_bars[attr]
            submit_label(renderer, self._volume_labels[attr],
                         color=widgets.C_UI_TEXT)
            if not is_visible(bar):
                continue
            sx, sy, sw, sh = bar.rect
            level = min(1.0, max(0.0, getattr(self.settings, attr)))
            renderer.submit_hud(HudRect(bar.rect, widgets.C_UI_BORDER))
            renderer.submit_hud(HudRect((sx, sy, int(sw * level), sh),
                                        widgets.C_UI_BTN))

        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
        if is_visible(self.controls_btn):
            self.controls_btn.submit(renderer, anim_ms=t,
                                     **button_kwargs(self.controls_btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
