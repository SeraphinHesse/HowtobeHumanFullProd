"""Main menu screen (Phase 9H).

Pure logic — the top-level menu the shell shows between runs. Ports the
prototype's ``src/ui/main_menu.py`` button set (START NEW GAME / ADD A NAME /
SETTINGS / CREDITS / QUIT) — plus debug-mode-telemetry's PLAY DEBUG row and
its ``SET`` gear (actions ``play_debug`` / ``play_debug_settings``, the latter
opening ``game/ui/debug_settings.py`` via the shell) — onto the
``game_over.py`` full-screen template: a
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

**player-identity: the availability matrix.** ``data/balancing/core.json``'s
``Debug`` group can hide either launcher row (``regular_mode_available`` /
``debug_mode_available``). Because the row a designer SEES and the action it
EMITS must be able to differ, ``self.buttons`` pairs each button with a STABLE
``slot_key`` (the key ``_SLOT_IDS`` looks its widget id up by — an id is the
on-disk contract in ``data/ui/screens/main_menu.json`` and must NEVER swap),
while ``self.actions`` (recomputed in ``layout()``) maps that slot to the action
``hit()`` returns. Regular-off therefore keeps the ``btn_new_game`` id and its
START NEW GAME slot but emits ``"play_debug"`` from it. ``debug_balance=None``
means "both modes available" — today's behaviour, and what every bare
``MainMenu(view_w, view_h)`` construction (the exporter, the golden parity pin)
relies on.
"""
import logging
from types import SimpleNamespace

from engine.render import HudRect, HudSprite

from .skinning import ScreenSkinning, button_kwargs, is_visible
from .widgets import Button, anim_ms, submit_centered
from . import widgets

_BG = (18, 30, 20)
_BG_SLOT = "main_menu_bg"
_TITLE = "HOW TO BE HUMAN"
_SUBTITLE = "defend the munckins"

# (label, slot_key) top-to-bottom. The slot key is STABLE: it names the row's
# widget id and its position in the stack, never the action it emits (see the
# availability matrix in the module docstring).
_ITEMS = [
    ("START NEW GAME", "new_game"),
    ("PLAY DEBUG", "play_debug"),
    ("ADD A NAME", "add_name"),
    ("HIGHSCORES", "highscores"),
    ("SETTINGS", "settings"),
    ("CREDITS", "credits"),
    ("QUIT", "quit"),
]
# slot_key -> the ids name a designer picks it by (10L-B). These are the
# on-disk contract (data/ui/screens/main_menu.json + screen_defaults.json).
_SLOT_IDS = {
    "new_game": "btn_new_game", "play_debug": "btn_play_debug",
    "add_name": "btn_add_name", "highscores": "btn_highscores",
    "settings": "btn_settings", "credits": "btn_credits", "quit": "btn_quit",
}

_log = logging.getLogger(__name__)
# player-identity: _GAP dropped 14 -> 8 when the HIGHSCORES row landed. Seven
# rows at the old pitch ran the QUIT button to y=696..748 in the shipped
# 1280x720 logical surface (data/display.json), i.e. 28px off the bottom of the
# screen — clipped, and its lower half unclickable. At 8 the full stack spans
# 300..712 and fits with room to spare; a matrix that HIDES a row only ever
# makes the stack shorter, so every availability cell fits too.
_BTN_W, _BTN_H, _GAP = 320, 52, 8
# debug-mode-telemetry: the small gear sitting beside PLAY DEBUG. It is its
# own action (``"play_debug_settings"``) rather than a mode of the row above,
# so a click on it can never start a run by accident.
_GEAR_ACTION = "play_debug_settings"
_GEAR_ID = "btn_play_debug_settings"
_GEAR_W, _GEAR_GAP = 52, 10

SCREEN_ID = "main_menu"


class MainMenu:
    def __init__(self, view_w, view_h, skinning=None, debug_balance=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        # player-identity: ``core.json``'s ``Debug`` group. ``None`` (and the
        # empty dict it degrades to) means "both modes available" — every flag
        # is read with ``.get(key, True)``, so a bare construction behaves
        # exactly as it did before this feature.
        self.debug_balance = debug_balance or {}
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), slot)
                        for label, slot in _ITEMS]
        #: slot_key -> the action ``hit()`` returns, recomputed every
        #: ``layout()`` from the availability matrix.
        self.actions = {slot: slot for _label, slot in _ITEMS}
        self._warned_no_mode = False  # latch: layout() runs every frame
        # debug-mode-telemetry: the PLAY DEBUG gear. Laid out beside its row in
        # ``layout()``; opens the debug-log settings modal (game/ui/
        # debug_settings.py) via the shell.
        self.debug_gear = Button((0, 0, _GEAR_W, _BTN_H), "SET")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        # 10L-B review fix (HIGH 1): static header text. Its own copy is NOT
        # game-state, so — unlike hud.py's dynamic readouts — "label" is a
        # legitimate override field here too.
        # The two static labels are the house purple; the buttons keep their
        # own palette colours (deliberate — only the text is retinted).
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_PURPLE, label=_TITLE,
                                      visible=True)
        self._subtitle = SimpleNamespace(rect=(0, 0, 0, 0), font_key="md",
                                         text_color=widgets.C_PURPLE,
                                         label=_SUBTITLE, visible=True)
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def _availability(self):
        """``(visible_by_slot, gear_slot)`` for the current balance flags, with
        ``self.actions`` recomputed. The fail-safe (both modes off) reverts to
        regular-only — never ship a menu with no way to start a game."""
        regular = bool(self.debug_balance.get("regular_mode_available", True))
        debug = bool(self.debug_balance.get("debug_mode_available", True))
        if not regular and not debug:
            if not self._warned_no_mode:
                self._warned_no_mode = True   # latched: layout() runs per frame
                _log.warning(
                    "Debug balancing disables BOTH regular_mode_available and "
                    "debug_mode_available — falling back to regular-only so "
                    "the main menu can still start a game.")
            regular, debug = True, False
        self.actions = {slot: slot for _label, slot in _ITEMS}
        visible = {slot: True for _label, slot in _ITEMS}
        if not debug:
            # No debug launcher at all: the PLAY DEBUG row and the gear go.
            visible["play_debug"] = False
            return visible, None
        if regular:
            return visible, "play_debug"
        # Debug-only: the PLAY DEBUG row is gone, but its ACTION (and the gear)
        # move onto the START NEW GAME slot, whose id/position never changes.
        visible["play_debug"] = False
        self.actions["new_game"] = "play_debug"
        return visible, "new_game"

    def layout(self, view_w, view_h):
        visible, gear_slot = self._availability()
        x = view_w // 2 - _BTN_W // 2
        y = view_h // 2 - 60
        for btn, slot in self.buttons:
            # Set ``visible`` on EVERY row every layout (never only in the
            # hiding branch) so a stale False cannot linger; and advance the
            # cursor ONLY for a visible row, so a hidden row leaves no gap.
            btn.visible = visible[slot]
            if not btn.visible:
                continue
            btn.rect = (x, y, _BTN_W, _BTN_H)
            if slot == gear_slot:
                self.debug_gear.rect = (x + _BTN_W + _GEAR_GAP, y,
                                        _GEAR_W, _BTN_H)
            y += _BTN_H + _GAP
        self.debug_gear.visible = gear_slot is not None
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, view_h // 2 - 150, 0, 0)
        self._subtitle.rect = (view_w // 2, view_h // 2 - 110, 0, 0)
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "subtitle": ("label", self._subtitle),
        }
        for btn, slot in self.buttons:
            self.ids[_SLOT_IDS[slot]] = ("button", btn)
        self.ids[_GEAR_ID] = ("button", self.debug_gear)
        # LAST, so a designer override still wins over the matrix above.
        self.skinning.apply(self.screen_id, self.ids)

    def _all_buttons(self):
        for btn, _ in self.buttons:
            yield btn
        yield self.debug_gear

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn in self._all_buttons():
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            # 10L-B: an invisible button is never hovered (force it off
            # rather than skip hover() — no stale True can linger).
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        if is_visible(self.debug_gear) and self.debug_gear.hit(mx, my):
            return _GEAR_ACTION
        for btn, slot in self.buttons:
            if is_visible(btn) and btn.hit(mx, my):
                # The slot names the id; ``actions`` names what it emits.
                return self.actions.get(slot, slot)
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
        for btn in self._all_buttons():
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
