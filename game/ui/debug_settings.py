"""Debug-mode settings screen (debug-mode-telemetry Phase 5).

The gear beside the main menu's ``PLAY DEBUG`` button opens this modal. It is
``settings.py``'s shape verbatim — a ``< value >`` cycler, a stack of ON/OFF
toggle rows, and BACK — over a session-only settings object the host reads when
it builds the ``DebugRecorder``:

``DebugSettings.level``    1 (the causal trace) or 2 (adds per-tick combat
                          detail). Never 0 — "off" is simply not pressing
                          PLAY DEBUG (a recorder is never constructed at
                          level 0; call sites guard on ``is None``).
``DebugSettings.outputs`` which of the four artifacts ``close()`` writes,
                          as the ``frozenset`` ``DebugRecorder(outputs=...)``
                          takes.

**Code-only, deliberately**: there is no ``data/ui/screens/debug_settings.json``
and no ``data/ui/screen_defaults.json`` entry. An absent override means "code
defaults" (``ScreenSkinning.apply`` is a no-op and id validation stays silent
until the defaults file names a screen), so this screen is skinnable the day
someone exports it and costs ``data/`` nothing today. The ``ids`` dict and the
panel -> button -> text submission order follow ``game/ui/CLAUDE.md`` like every
other screen, so that export is a drop-in.
"""
from dataclasses import dataclass
from types import SimpleNamespace


from game.debug import ALL_OUTPUTS, LEVEL_BASIC, LEVEL_VERBOSE

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, submit_centered, submit_text
from . import widgets

_BG = (12, 14, 22)

#: Selectable recorder levels, in cycler order. 0 is deliberately absent.
LEVELS = (LEVEL_BASIC, LEVEL_VERBOSE)
_LEVEL_LABEL = {
    LEVEL_BASIC: "1 - CAUSAL TRACE",
    LEVEL_VERBOSE: "2 - + COMBAT DETAIL",
}

# (DebugSettings attr, on-screen label) — one toggle row per artifact.
_TOGGLES = [
    ("jsonl", "Event stream (.jsonl)"),
    ("csv", "Per-round table (.csv)"),
    ("md", "Summary (.md)"),
    ("html", "Report (.html)"),
]
# DebugSettings attr -> the id a designer picks that toggle by.
_TOGGLE_IDS = {
    "jsonl": "btn_toggle_jsonl",
    "csv": "btn_toggle_csv",
    "md": "btn_toggle_md",
    "html": "btn_toggle_html",
}

SCREEN_ID = "debug_settings"


@dataclass
class DebugSettings:
    """Session-only (never persisted) debug-recorder options — the
    ``SessionSettings`` precedent. The host reads these when PLAY DEBUG (or the
    cheat-menu arm toggle) constructs a ``DebugRecorder``."""

    level: int = LEVEL_BASIC
    jsonl: bool = True
    csv: bool = True
    md: bool = True
    html: bool = True

    @property
    def outputs(self):
        """The ``DebugRecorder(outputs=...)`` set. Every artifact toggled off
        leaves an empty set, which writes nothing at all — a legitimate
        "record the stream in memory only" choice, not an error."""
        return frozenset(k for k in ALL_OUTPUTS if getattr(self, k))


class DebugSettingsScreen:
    def __init__(self, view_w, view_h, settings, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.settings = settings
        self.level_left = Button((0, 0, 20, 20), "<")
        self.level_right = Button((0, 0, 20, 20), ">")
        self.toggles = [(attr, label, Button((0, 0, 45, 20), "ON"))
                        for attr, label in _TOGGLES]
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD,
                                      label="DEBUG LOG", visible=True)
        self.ids = {}
        self._clock = 0.0  # one anim clock per screen (10L-A)
        self.layout(view_w, view_h)

    # -- layout ------------------------------------------------------------

    def layout(self, view_w, view_h):
        cx = view_w // 2
        self._cx = cx
        self._top = view_h // 2 - 100
        self._level_y = self._top + 35
        self.level_left.rect = (cx - 105, self._level_y - 3, 20, 20)
        self.level_right.rect = (cx + 85, self._level_y - 3, 20, 20)
        y = self._level_y + 35
        self._row_y = []
        for _attr, _label, btn in self.toggles:
            self._row_y.append(y)
            btn.rect = (cx + 50, y - 4, 45, 20)
            y += 28
        self.back_btn.rect = (cx - 50, y + 15, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (cx, self._top, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_level_left": ("button", self.level_left),
            "btn_level_right": ("button", self.level_right),
            "btn_back": ("button", self.back_btn),
        }
        for attr, _label, btn in self.toggles:
            self.ids[_TOGGLE_IDS[attr]] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)

    def _buttons(self):
        yield self.level_left
        yield self.level_right
        for _a, _l, btn in self.toggles:
            yield btn
        yield self.back_btn

    # -- per-frame ---------------------------------------------------------

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for attr, _label, btn in self.toggles:
            btn.label = "ON" if getattr(self.settings, attr) else "OFF"
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """``"back"`` or ``None`` — the cycler and the toggles mutate
        ``settings`` in place (the ``SettingsScreen`` contract). An invisible
        button is never hit (10L-B)."""
        # UL-10: clickable layers first. BACK only, for the same reason as
        # ``settings.py`` — the cycler/toggles mutate inside their branch.
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_back": "back"})
        if layer_action is not None:
            return layer_action
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            return "back"
        i = LEVELS.index(self.settings.level) if self.settings.level in LEVELS else 0
        if is_visible(self.level_left) and self.level_left.hit(mx, my):
            self.settings.level = LEVELS[(i - 1) % len(LEVELS)]
            return None
        if is_visible(self.level_right) and self.level_right.hit(mx, my):
            self.settings.level = LEVELS[(i + 1) % len(LEVELS)]
            return None
        for attr, _label, btn in self.toggles:
            if is_visible(btn) and btn.hit(mx, my):
                setattr(self.settings, attr, not getattr(self.settings, attr))
                return None
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        cx = self._cx
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)

        submit_centered(renderer, "Detail Level", cx, self._level_y - 17, "md",
                        widgets.C_UI_TEXT)
        submit_centered(renderer,
                        _LEVEL_LABEL.get(self.settings.level, "1"), cx,
                        self._level_y, "lg", widgets.C_GOLD)
        if is_visible(self.level_left):
            self.level_left.submit(renderer, anim_ms=t,
                                   **button_kwargs(self.level_left))
        if is_visible(self.level_right):
            self.level_right.submit(renderer, anim_ms=t,
                                    **button_kwargs(self.level_right))

        for (_attr, label, btn), y in zip(self.toggles, self._row_y):
            submit_text(renderer, label, (cx - 105, y), "md", widgets.C_UI_TEXT)
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))

        submit_centered(renderer, "Written to logs/ at the end of the run.", cx,
                        self.back_btn.rect[1] - 13, "sm",
                        widgets.C_UI_TEXT_DIM)
        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.back_btn))
