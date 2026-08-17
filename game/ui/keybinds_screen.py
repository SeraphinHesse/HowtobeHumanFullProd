"""Rebindable-hotkeys screen (feature: rebindable hotkeys).

Lists 16 of the 18 actions in ``data/balancing/ui.json``'s ``Keybindings``
group (the designer-editable defaults) with their current key and a REBIND
button per row, in TWO columns (16 rows in one column would run off the
640x360 logical surface) — ``toggle_cheat_menu`` and ``quick_skip_combat`` are
deliberately EXCLUDED from ``ACTIONS`` (cut from this screen on request): both
keep working exactly as before, dispatched through ``key_bindings`` in
``game/main.py`` same as any other action, they are just not surfaced as
player-rebindable here — the same treatment Esc/F12 already get, chosen so a
hidden dev feature (the cheat menu) and a testing convenience (quick-skip)
don't advertise themselves in player-facing Settings. Reached from Settings
via the CONTROLS button
(``game/ui/settings.py``), opened as a ``Shell``-level overlay flag
(``Shell.controls_open``) exactly like ``debug_settings_open`` — see that
screen's docstring for why an overlay flag rather than a new ``GameState``.

Rebinding is NOT applied here: this screen only tracks WHICH row is armed
(``capturing``) and displays the shared ``bindings`` dict the host owns.
Actually validating a keypress (Esc cancels, a collision flashes, otherwise
the key is written into ``bindings`` and persisted to
``scores/keybindings.json``) is ``game/main.py``'s job — the same "screen is
pygame-free, host does the pygame + disk parts" split ``debug_settings.py``'s
toggles use. ``bindings`` is a plain shared dict (the ``SessionSettings``
precedent): the host mutates it in place via ``engine.input.rebind``, and
this screen simply reads whatever is there each frame.

Code-only screen, the ``debug_settings.py`` precedent: no
``data/ui/screens/keybinds.json``, no ``screen_defaults.json`` entry, not in
``tools/export_ui_layouts.py``'s ``SCREEN_IDS``. Row labels are plain code
text for the same reason ``debug_settings.py``'s are — a screen reachable
from exactly one place, matching that precedent rather than the
string-table migration (UT-5) scoped to the original + wave-3 screens.
"""
from types import SimpleNamespace

from engine.render import HudRect

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import Button, anim_ms, submit_centered, submit_text
from . import widgets

_BG = (12, 20, 14)

#: (action name, on-screen label) — the rebindable-AND-shown gameplay
#: actions, in display order (first `_ROWS_PER_COL` go in the left column,
#: the rest in the right — see `layout()`). A subset of
#: ``data/balancing/ui.json``'s ``Keybindings`` group's 18 keys (see the
#: module docstring for the two deliberately-omitted ones); every action name
#: here must still match ``engine.input``'s callers in ``game/main.py`` and a
#: ``Keybindings`` key exactly.
ACTIONS = [
    ("move_up", "Move Up"),
    ("move_down", "Move Down"),
    ("move_left", "Move Left"),
    ("move_right", "Move Right"),
    ("end_turn", "End Turn"),
    ("combat_speed_1", "Combat Speed 1x"),
    ("combat_speed_2", "Combat Speed 1.5x"),
    ("combat_speed_3", "Combat Speed 2x"),
    ("confirm_purchase", "Confirm/Upgrade"),
    ("toggle_heatmap", "Toggle Heatmap"),
    ("toggle_range", "Toggle Range"),
    ("toggle_tier_overview", "Toggle Tiers"),
    ("toggle_drag_select", "Drag Select"),
    ("zoom_level_1", "Zoom Level 1"),
    ("zoom_level_2", "Zoom Level 2"),
    ("zoom_level_3", "Zoom Level 3"),
]

#: Two columns keep 12 rows readable on the 640x360 logical surface — see
#: `layout()`. `-(-len(ACTIONS) // 2)` is ceil-division with no `math` import.
_ROWS_PER_COL = -(-len(ACTIONS) // 2)

_FLASH_DUR = 1.5

SCREEN_ID = "keybinds"


def display_key(key):
    """``"ctrl+l"`` -> ``"CTRL+L"`` — the on-screen form of a binding string."""
    return key.upper()


class KeybindsScreen:
    def __init__(self, view_w, view_h, bindings, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        #: shared dict the host owns and mutates in place (the
        #: ``SessionSettings`` precedent) — this screen never writes to it.
        self.bindings = bindings
        #: action name currently awaiting a keypress, or ``None``. Set by a
        #: REBIND click; cleared by the host on Esc/collision/success.
        self.capturing = None
        self.rows = [(action, label, Button((0, 0, 60, 18), "REBIND",
                                            font_key="sm"))
                    for action, label in ACTIONS]
        self.back_btn = Button((0, 0, 100, 23), "BACK")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_GOLD,
                                      label="CONTROLS", visible=True)
        self.ids = {}
        self._clock = 0.0  # one anim clock per screen (10L-A)
        self.layout(view_w, view_h)

    # -- layout ------------------------------------------------------------

    def layout(self, view_w, view_h):
        cx = view_w // 2
        self._cx = cx
        self._top = view_h // 2 - 150
        top_y = self._top + 40
        # Two columns (12 rows would run off a single 640x360 column) — left
        # column's label/key/button sit left of centre, right column mirrors
        # it right of centre, both growing downward from the same top_y.
        col_x = ((cx - 300, cx - 170, cx - 150),   # (label, key, button) x
                (cx + 40, cx + 170, cx + 190))
        self._row_xy = []
        for i, (_action, _label, btn) in enumerate(self.rows):
            col, row_in_col = divmod(i, _ROWS_PER_COL)
            label_x, key_x, btn_x = col_x[col]
            y = top_y + row_in_col * 22
            self._row_xy.append((label_x, key_x, y))
            btn.rect = (btn_x, y - 3, 60, 18)
        bottom_y = top_y + _ROWS_PER_COL * 22
        self.back_btn.rect = (cx - 50, bottom_y + 12, 100, 23)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (cx, self._top, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_back": ("button", self.back_btn),
        }
        for action, _label, btn in self.rows:
            self.ids[f"btn_rebind_{action}"] = ("button", btn)
        self.skinning.apply(self.screen_id, self.ids)

    def _buttons(self):
        for _a, _l, btn in self.rows:
            yield btn
        yield self.back_btn

    # -- per-frame -----------------------------------------------------------

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for action, _label, btn in self.rows:
            if btn.flash <= 0:
                btn.label = "PRESS A KEY" if self.capturing == action else "REBIND"
        for btn in self._buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        """``"back"`` or ``None``. Clicking a row's REBIND button arms
        ``capturing`` for that action — the actual keypress is handled by the
        host (``main.py``), not here. An invisible button is never hit
        (10L-B)."""
        if is_visible(self.back_btn) and self.back_btn.hit(mx, my):
            self.capturing = None
            return "back"
        for action, _label, btn in self.rows:
            if is_visible(btn) and btn.hit(mx, my):
                self.capturing = action
                return None
        return None

    def stop_capture(self):
        """The host calls this on Esc or on a successful rebind."""
        self.capturing = None

    def flash_conflict(self):
        """The host calls this when the just-captured key is already bound to
        another action — flashes the armed row's REBIND button red and drops
        capture (the player tries again from a fresh click)."""
        self._flash_armed_row("IN USE")

    def flash_unbindable(self):
        """The host calls this when the just-pressed key has no representable
        binding (an arrow key, Tab, Shift, an F-key, ...) — previously a
        silent no-op that left the row stuck showing "PRESS A KEY" forever
        with no feedback at all (bug: the WASD rows looked broken to a player
        who instinctively tried an arrow key, since arrow keys are reserved
        as the always-on panning alias and were never a legal binding target
        — see ``game/CLAUDE.md``'s WASD section). Same flash-and-drop-capture
        shape as ``flash_conflict``, distinct message."""
        self._flash_armed_row("CAN'T BIND THAT KEY")

    def _flash_armed_row(self, message):
        for action, _label, btn in self.rows:
            if action == self.capturing:
                btn.start_flash(_FLASH_DUR, message)
                break
        self.capturing = None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w, view_h)
        renderer.submit_hud(HudRect(self._backdrop.rect, self._backdrop.color))
        cx = self._cx
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)

        for (action, label, btn), (label_x, key_x, y) in zip(
                self.rows, self._row_xy):
            submit_text(renderer, label, (label_x, y), "sm", widgets.C_UI_TEXT)
            submit_text(renderer, display_key(self.bindings.get(action, "")),
                       (key_x, y), "sm", widgets.C_GOLD)
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))

        if is_visible(self.back_btn):
            self.back_btn.submit(renderer, anim_ms=t,
                                 **button_kwargs(self.back_btn))
