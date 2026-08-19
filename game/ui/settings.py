"""Settings screen + session settings (Phase 9H).

``SessionSettings`` is the pure, SESSION-ONLY (never persisted) override store —
seeded from the ``ui`` balancing FX flags at boot, mutated by this screen, read
by the host. ``SettingsScreen`` ports the prototype's ``src/ui/settings_menu.py``
onto the ``game_over.py`` template: a display-mode ``< value >`` cycler, the
GPU/CPU renderer switch, the three SD-6 audio tracks (Master / Music / SFX) and
BACK. Shared by the main-menu and the pause-menu entry points; the shell tracks
which caller BACK returns to.

**The three FX toggles (income floaters / background art / gore) are CUT** from
this screen (settings-cut). The ``SessionSettings`` fields survive — they are
still seeded from ``data/balancing/ui.json``'s ``FX`` block and still read by
``payday.py`` / ``session.py`` / ``main_menu.py`` — so the features stay
designer-tunable in the editor; they are simply no longer player-facing.

**Audio rows are real sliders now** (settings-cut): a taller track with a
draggable MARKER, a ``-``/``+`` step button on either side and a live ``%``
readout. Click-to-set still works exactly as before (SD-6) and additionally
ARMS a drag: ``update()`` keeps writing the level while the button is held and
returns ``"set_volume_live"`` (apply to the buses, do NOT touch disk), then
returns ``"set_volume"`` once on release (apply AND persist). That split is why
a drag does not write ``settings/audio.json`` sixty times a second.

**The renderer switch is a BOOT preference, not a live one.** Swapping the
render stack mid-run would mean tearing down the window, the ground cache and
every GPU texture behind the live world; the switch therefore only records the
choice (host intent ``"set_renderer"`` -> ``game/core/render_settings.py``) and
the row carries a permanent ``settings.renderer_note`` line saying it applies on
the next launch. Nothing about the running frame changes.

10L-B: ``ids`` names ``backdrop``, ``title`` ("SETTINGS") + every button (the
display-mode cycler arrows, SET DEFAULT, the renderer switch, the six volume
step buttons, BACK). An invisible button is neither drawn nor hit-tested.

**SET DEFAULT** persists the currently-selected display mode as the BOOT mode.
This screen stays pure: the button only returns the ``"save_display_default"``
action, and the host writes ``data/display.json`` (the same "anything touching
disk is an intent" rule the rest of the shell follows). ``saved_default`` is
the host-set string of what is on disk today (``None`` = unknown, e.g. a bare
test/exporter construction — then no line is drawn).

The button, its ``default_note`` line and the whole host side of that action
were dead for three phases: the widget was built, positioned, id'd and hovered,
but ``submit()`` never drew it and ``hit()`` had no branch for it, so
``"save_display_default"`` had zero call sites repo-wide even though
``display.schema.json`` documents ``display_mode`` as "the BOOT display mode
the settings screen's SET DEFAULT button persists". It is wired now — and
because the branch is genuinely side-effect-free (unlike the arrows, the
renderer switch and the volume rows, which mutate ``settings`` inside their own
branch), ``btn_set_default`` is the SECOND id a clickable layer may retarget.
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
#: The renderer switch's two positions. "gpu" is the SDL2-texture stack,
#: "cpu" the Surface blitter — the host maps them onto its own
#: ``--backend={gpu,surface}`` choice, which keeps that flag's spelling out of
#: the player-facing screen.
RENDERERS = ("gpu", "cpu")
#: How much one ``-``/``+`` press moves a volume, 0..1.
VOLUME_STEP = 0.05
_BG = (12, 20, 14)

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
#: settings-cut: the per-row step buttons + the ``%`` readout, keyed by the
#: same SessionSettings attr. Ids are siblings of the bar's, so a designer can
#: place a row's five widgets independently (the no-cascade convention).
_VOLUME_MINUS_IDS = {attr: f"btn_{attr}_down"
                     for attr, _t, _l, _b in _VOLUME_ROWS}
_VOLUME_PLUS_IDS = {attr: f"btn_{attr}_up"
                    for attr, _t, _l, _b in _VOLUME_ROWS}
_VOLUME_PCT_IDS = {attr: f"label_{attr}_pct"
                   for attr, _t, _l, _b in _VOLUME_ROWS}

#: How far ABOVE and BELOW its own rect a volume track still answers a click
#: (settings-cut). The 10px track is a DRAW rect; this band is what makes the
#: marker comfortable to grab, and it is never drawn.
_BAR_GRAB_PAD = 5

SCREEN_ID = "settings"


def _clamp01(v):
    return min(1.0, max(0.0, v))


@dataclass
class SessionSettings:
    # Fullscreen is the shipped default (data/display.json's `display_mode`
    # is what the host actually seeds this from at boot; this literal is the
    # bare-construction fallback and matches it).
    display_mode: str = "fullscreen"     # one of DISPLAY_MODES
    # settings-cut: no longer player-facing, still seeded from the `ui` FX
    # block and still read by the game — see the module docstring.
    income_floaters: bool = True
    bg_art: bool = True
    gore: bool = True
    #: settings-cut: one of RENDERERS. A BOOT preference — the host seeds it
    #: from `settings/render.json` and writes it back, and it takes effect on
    #: the next launch, never on this frame.
    renderer: str = "gpu"
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
        # The "what is on disk today" line under the button. Drawn only once
        # the host has set `saved_default` — a bare construction says nothing
        # rather than guessing at a file it has not read.
        self._default_note = label_holder(text_id="settings.saved_default",
                                          font_key="sm")
        # settings-cut: the GPU/CPU switch. One button that reads the current
        # position and flips it — a two-value cycler needs no arrows.
        self.renderer_btn = Button((0, 0, 60, 20), "GPU", font_key="md")
        # feature: rebindable hotkeys — opens Shell.controls_open (the
        # debug_settings_open overlay-flag pattern), not a new GameState.
        self.controls_btn = Button((0, 0, 90, 23), "CONTROLS", font_key="sm")
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
        self._renderer_label = label_holder(text_id="settings.renderer")
        self._renderer_note = label_holder(text_id="settings.renderer_note",
                                           font_key="sm")
        # SD-6: one label holder + one bar holder per audio row. A bar is a
        # plain rect holder (the `hud.xp_bar` shape), registered under kind
        # "bar" — a 10px track with a draggable marker, not a button.
        self._volume_labels = {attr: label_holder(text_id=text_id)
                               for attr, text_id, _lid, _bid in _VOLUME_ROWS}
        self._volume_bars = {attr: SimpleNamespace(rect=(0, 0, 96, 10))
                             for attr, _t, _lid, _bid in _VOLUME_ROWS}
        self._volume_minus = {attr: Button((0, 0, 16, 16), "-", font_key="md")
                              for attr, _t, _lid, _bid in _VOLUME_ROWS}
        self._volume_plus = {attr: Button((0, 0, 16, 16), "+", font_key="md")
                             for attr, _t, _lid, _bid in _VOLUME_ROWS}
        self._volume_pct = {attr: label_holder(text_id="settings.volume_pct",
                                               font_key="sm")
                            for attr, _t, _lid, _bid in _VOLUME_ROWS}
        #: The SessionSettings attr whose track the pointer is currently
        #: dragging, or None. Armed by ``hit()``, released by ``update()``.
        self.dragging = None
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD, label="SETTINGS",
                                      visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)

    # -- geometry ---------------------------------------------------------
    def layout(self, view_w, view_h):
        cx = view_w // 2
        self._cx = cx
        self._top = view_h // 2 - 90
        self._dm_y = self._top + 35                 # display-mode value row
        self.dm_left.rect = (cx - 75, self._dm_y - 3, 20, 20)
        self.dm_right.rect = (cx + 55, self._dm_y - 3, 20, 20)
        # Right of the ">" arrow, clear of the rows below.
        self.default_btn.rect = (cx + 85, self._dm_y - 3, 85, 20)
        # Directly under the button, left-aligned with it.
        self._default_note.rect = (cx + 85, self._dm_y + 20, 0, 0)
        # settings-cut: the renderer row takes the slot the three FX toggles
        # used to open on, and its note line sits to the right of the switch.
        self._renderer_y = self._dm_y + 35
        self._renderer_label.rect = (cx - 165, self._renderer_y, 0, 0)
        self.renderer_btn.rect = (cx - 60, self._renderer_y - 4, 60, 20)
        self._renderer_note.rect = (cx + 10, self._renderer_y, 0, 0)
        # SD-6: three stacked volume rows. The row step is font-scale (never a
        # bare literal) with a floor that clears the 16px step buttons.
        self._slider_y = self._renderer_y + 34
        step = max(22, layout_h("sm") + 10)
        self._volume_row_y = []
        for i, (attr, _text_id, _lid, _bid) in enumerate(_VOLUME_ROWS):
            row_y = self._slider_y + i * step
            self._volume_row_y.append(row_y)
            self._volume_labels[attr].rect = (cx - 165, row_y - 1, 0, 0)
            self._volume_minus[attr].rect = (cx - 60, row_y - 3, 16, 16)
            self._volume_bars[attr].rect = (cx - 38, row_y, 96, 10)
            self._volume_plus[attr].rect = (cx + 62, row_y - 3, 16, 16)
            self._volume_pct[attr].rect = (cx + 84, row_y, 0, 0)
        # Clear of the third (SFX) row. `data/ui/screens/settings.json` authors
        # `btn_back`'s rect and an authored rect WINS, so that doc moved in
        # lockstep with this offset.
        bottom_y = self._volume_row_y[-1] + 40
        self.back_btn.rect = (cx - 50, bottom_y, 100, 23)
        self.controls_btn.rect = (cx + 60, bottom_y, 90, 23)
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
            "btn_renderer": ("button", self.renderer_btn),
            "btn_back": ("button", self.back_btn),
            "btn_controls": ("button", self.controls_btn),
            "dm_label": ("label", self._dm_label),
            "dm_value": ("label", self._dm_value),
            "default_note": ("label", self._default_note),
            "renderer_label": ("label", self._renderer_label),
            "renderer_note": ("label", self._renderer_note),
        }
        for attr, _text_id, label_id, bar_id in _VOLUME_ROWS:
            self.ids[label_id] = ("label", self._volume_labels[attr])
            self.ids[bar_id] = ("bar", self._volume_bars[attr])
            self.ids[_VOLUME_MINUS_IDS[attr]] = ("button",
                                                 self._volume_minus[attr])
            self.ids[_VOLUME_PLUS_IDS[attr]] = ("button",
                                                self._volume_plus[attr])
            self.ids[_VOLUME_PCT_IDS[attr]] = ("label", self._volume_pct[attr])
        self.skinning.apply(self.screen_id, self.ids)

    def _buttons(self):
        yield self.dm_left
        yield self.dm_right
        yield self.default_btn
        yield self.renderer_btn
        for attr, _text_id, _lid, _bid in _VOLUME_ROWS:
            yield self._volume_minus[attr]
            yield self._volume_plus[attr]
        yield self.back_btn
        yield self.controls_btn

    def _grab_rect(self, bar):
        """``bar``'s rect, opened up vertically for hit-testing only."""
        x, y, w, h = bar.rect
        return (x, y - _BAR_GRAB_PAD, w, h + 2 * _BAR_GRAB_PAD)

    def _level_at(self, bar, mx):
        """The 0..1 level the pointer at ``mx`` picks on ``bar``'s track."""
        sx, _sy, sw, _sh = bar.rect
        return 0.0 if sw <= 0 else _clamp01((mx - sx) / sw)

    # -- frame ------------------------------------------------------------
    def update(self, dt, mx, my, mouse_down=False):
        """Advance the screen and, while a volume marker is being DRAGGED,
        return the host action for it: ``"set_volume_live"`` every frame the
        button is held, then ``"set_volume"`` once on release (settings-cut).
        ``None`` otherwise — the pre-drag behaviour for every other frame."""
        self._clock += dt
        self.renderer_btn.label = self.settings.renderer.upper()
        action = None
        if self.dragging is not None:
            attr = self.dragging
            if mouse_down:
                setattr(self.settings, attr,
                        self._level_at(self._volume_bars[attr], mx))
                action = "set_volume_live"
            else:
                self.dragging = None
                action = "set_volume"      # the one write that reaches disk
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)
        return action

    def hit(self, mx, my):
        """Return ``"back"`` / ``"set_display_mode"`` / ``"save_display_default"``
        / ``"set_volume"`` / ``"set_renderer"`` / ``"open_controls"`` (the host
        must apply each of those) or ``None``. An invisible button is never hit
        (10L-B)."""
        # UL-10: clickable layers first. Only BACK and SET DEFAULT are
        # retargetable here — the display-mode arrows, the renderer switch and
        # the volume controls MUTATE ``settings`` inside their own branch, so
        # returning their action string from here would report a change that
        # never happened. A layer aimed at one of them is therefore unroutable
        # and swallows (Ruling 1), which is the honest answer until those
        # branches grow a shared, side-effect-free seam. SET DEFAULT needs no
        # such seam: it mutates nothing, it only names the mode already on
        # ``settings`` as the one to persist.
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of,
            {"btn_back": "back", "btn_set_default": "save_display_default"})
        if layer_action is not None:
            return layer_action
        # SD-6 + settings-cut: the three audio rows. The step buttons move the
        # level by VOLUME_STEP; a click anywhere on the track sets it to where
        # the pointer landed AND arms the drag `update()` continues.
        for attr, _text_id, _lid, _bid in _VOLUME_ROWS:
            minus, plus = self._volume_minus[attr], self._volume_plus[attr]
            if widgets.click(minus, mx, my):
                setattr(self.settings, attr,
                        _clamp01(getattr(self.settings, attr) - VOLUME_STEP))
                return "set_volume"
            if widgets.click(plus, mx, my):
                setattr(self.settings, attr,
                        _clamp01(getattr(self.settings, attr) + VOLUME_STEP))
                return "set_volume"
            bar = self._volume_bars[attr]
            if is_visible(bar) and widgets.contains(self._grab_rect(bar), mx, my):
                setattr(self.settings, attr, self._level_at(bar, mx))
                self.dragging = attr
                return "set_volume"
        if widgets.click(self.back_btn, mx, my):
            return "back"
        if widgets.click(self.controls_btn, mx, my):
            return "open_controls"
        # Pure: the mode to persist is whatever ``settings`` already holds, so
        # this branch writes nothing — the host does, to data/display.json.
        if widgets.click(self.default_btn, mx, my):
            return "save_display_default"
        if widgets.click(self.renderer_btn, mx, my):
            i = RENDERERS.index(self.settings.renderer)
            self.settings.renderer = RENDERERS[(i + 1) % len(RENDERERS)]
            return "set_renderer"
        i = DISPLAY_MODES.index(self.settings.display_mode)
        if widgets.click(self.dm_left, mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i - 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        if widgets.click(self.dm_right, mx, my):
            self.settings.display_mode = DISPLAY_MODES[(i + 1) % len(DISPLAY_MODES)]
            return "set_display_mode"
        return None

    # -- draw -------------------------------------------------------------
    def _submit_volume_row(self, renderer, attr, t):
        bar = self._volume_bars[attr]
        submit_label(renderer, self._volume_labels[attr],
                     color=widgets.C_UI_TEXT)
        level = _clamp01(getattr(self.settings, attr))
        submit_label(renderer, self._volume_pct[attr],
                     color=widgets.C_GOLD, pct=int(round(level * 100)))
        for btn in (self._volume_minus[attr], self._volume_plus[attr]):
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
        if not is_visible(bar):
            return
        sx, sy, sw, sh = bar.rect
        renderer.submit_hud(HudRect(bar.rect, widgets.C_PANEL_STONE))
        renderer.submit_hud(HudRect((sx, sy, int(sw * level), sh),
                                    widgets.C_PURPLE))
        renderer.submit_hud(HudRect(bar.rect, widgets.C_UI_BORDER, width=1))
        # The draggable marker: a handle that stays fully inside the track at
        # both ends, and goes pale while it is the one being held.
        mw, mh = 6, sh + 8
        handle_x = sx + int(round((sw - mw) * level))
        color = widgets.C_UI_TEXT if self.dragging == attr else widgets.C_GOLD
        renderer.submit_hud(HudRect((handle_x, sy - 4, mw, mh), color))

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
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
        if is_visible(self.default_btn):
            self.default_btn.submit(renderer, anim_ms=t,
                                    **button_kwargs(self.default_btn))
        # `saved_default is None` means the host never told us what is on disk
        # (a bare test/exporter construction) — say nothing rather than guess.
        if self.saved_default is not None:
            submit_label(renderer, self._default_note,
                         color=widgets.C_UI_TEXT_DIM,
                         mode=self.saved_default.upper())

        # settings-cut: the renderer switch + its permanent restart warning.
        submit_label(renderer, self._renderer_label, color=widgets.C_UI_TEXT)
        submit_label(renderer, self._renderer_note, color=widgets.C_UI_TEXT_DIM)
        if is_visible(self.renderer_btn):
            self.renderer_btn.submit(renderer, anim_ms=t,
                                     **button_kwargs(self.renderer_btn))

        for attr, _text_id, _lid, _bid in _VOLUME_ROWS:
            self._submit_volume_row(renderer, attr, t)

        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t, **button_kwargs(self.back_btn))
        if is_visible(self.controls_btn):
            self.controls_btn.submit(renderer, anim_ms=t,
                                     **button_kwargs(self.controls_btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
