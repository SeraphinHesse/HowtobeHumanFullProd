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

from engine.render import HudSprite

from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
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
    ("CONTINUE", "continue"),
    ("PLAY DEBUG", "play_debug"),
    ("ADD A NAME", "add_name"),
    ("HIGHSCORES", "highscores"),
    ("SAVE FILES", "save_files"),
    ("SETTINGS", "settings"),
    ("CREDITS", "credits"),
    ("QUIT", "quit"),
]
# slot_key -> the ids name a designer picks it by (10L-B). These are the
# on-disk contract (data/ui/screens/main_menu.json + screen_defaults.json).
_SLOT_IDS = {
    "new_game": "btn_new_game", "continue": "btn_continue",
    "play_debug": "btn_play_debug",
    "add_name": "btn_add_name", "highscores": "btn_highscores",
    "save_files": "btn_save_files",
    "settings": "btn_settings", "credits": "btn_credits", "quit": "btn_quit",
}

_log = logging.getLogger(__name__)
# player-identity: _GAP dropped 7 -> 4 when the HIGHSCORES row landed. Seven
# rows at the old pitch ran the QUIT button to y=348..374 in the shipped
# 640x360 logical surface (data/display.json), i.e. 14px off the bottom of the
# screen — clipped, and its lower half unclickable. At 4 the full stack spans
# 150..356 and fits with room to spare; a matrix that HIDES a row only ever
# makes the stack shorter, so every availability cell fits too.
# (UR-2 halved every number in this note with the logical surface.)
_BTN_W, _BTN_H, _GAP = 160, 26, 4
# debug-mode-telemetry: the small gear sitting beside PLAY DEBUG. It is its
# own action (``"play_debug_settings"``) rather than a mode of the row above,
# so a click on it can never start a run by accident.
_GEAR_ACTION = "play_debug_settings"
_GEAR_ID = "btn_play_debug_settings"
# UR-5: the gear widened 26 -> 30. 405 + 30 = 435, still well inside the 640px
# surface. Its label is font "md", not the Button default "lg": "SET" has no
# words left to cut and measures 31px at "lg" under the SHIPPED pixel font
# (``data/ui/active_font.json`` -> pixel_emulator, wider per glyph than the
# ``SysFont("monospace")`` fallback these constants were authored against),
# i.e. 35 with the 4px label margin in a 30px button. At "md" it needs 27.
# A per-widget drop, deliberately NOT a change to ``data/ui/fonts.json``.
_GEAR_W, _GEAR_GAP = 30, 5
_GEAR_FONT = "md"

SCREEN_ID = "main_menu"


class MainMenu:
    def __init__(self, view_w, view_h, skinning=None, debug_balance=None,
                has_saves=False):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        # player-identity: ``core.json``'s ``Debug`` group. ``None`` (and the
        # empty dict it degrades to) means "both modes available" — every flag
        # is read with ``.get(key, True)``, so a bare construction behaves
        # exactly as it did before this feature.
        self.debug_balance = debug_balance or {}
        # SaveGamePLAN SG-6: whether at least one save slot exists. The host
        # keeps this fresh via ``set_has_saves`` (the same "runtime data the
        # menu needs but does not own" shape as ``Shell.set_highscores`` —
        # this screen does no disk I/O itself). ``False`` (every bare
        # construction, every existing test) hides the CONTINUE row —
        # user decision: hidden entirely, never a disabled/greyed row.
        self.has_saves = has_saves
        self.buttons = [(Button((0, 0, _BTN_W, _BTN_H), label), slot)
                        for label, slot in _ITEMS]
        #: slot_key -> the action ``hit()`` returns, recomputed every
        #: ``layout()`` from the availability matrix.
        self.actions = {slot: slot for _label, slot in _ITEMS}
        self._warned_no_mode = False  # latch: layout() runs every frame
        # debug-mode-telemetry: the PLAY DEBUG gear. Laid out beside its row in
        # ``layout()``; opens the debug-log settings modal (game/ui/
        # debug_settings.py) via the shell.
        self.debug_gear = Button((0, 0, _GEAR_W, _BTN_H), "SET",
                                 font_key=_GEAR_FONT)
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

    def set_has_saves(self, value):
        """Host keeps this fresh (SaveGamePLAN SG-6) — called at boot and
        whenever a save is created/deleted, so CONTINUE's visibility never
        goes stale mid-session (the ``Shell.set_highscores`` shape)."""
        self.has_saves = bool(value)

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
        # SaveGamePLAN SG-6: CONTINUE is hidden entirely with no saves yet
        # (user decision) — set here, before either early return below, so
        # both the debug-only and the fail-safe paths honour it too.
        visible["continue"] = self.has_saves
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
        # SaveGamePLAN SG-6: the row count grew from 7 to up to 9
        # (CONTINUE + SAVE FILES) and now varies with `has_saves` on top of
        # the existing debug-availability variance, so the stack's vertical
        # START is computed from however many rows are ACTUALLY visible this
        # layout, centered in the view, rather than a fixed offset tuned for
        # exactly 7 rows (the old `view_h // 2 - 30`, which a 9-row stack
        # would overflow the 360px logical surface by ~55px). This keeps the
        # stack correctly centered for any row count, past or future.
        visible_count = sum(1 for v in visible.values() if v)
        stack_h = visible_count * _BTN_H + max(0, visible_count - 1) * _GAP
        y = (view_h - stack_h) // 2
        stack_top = y   # title/subtitle position off this, below
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
        # SaveGamePLAN SG-6: positioned relative to the now row-count-
        # dependent `stack_top` (above) instead of the old fixed `view_h //
        # 2 - 75`/`- 55` (tuned for exactly 7 rows), so title/subtitle never
        # overlap the button stack for any visible row count — this is a
        # real position change (not byte-identical to the pre-SG-6 layout)
        # and needs a live look in SG-7's Quick Test, same as the row-count
        # change itself.
        self._title.rect = (view_w // 2, max(10, stack_top - 40), 0, 0)
        self._subtitle.rect = (view_w // 2, max(28, stack_top - 20), 0, 0)
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
        # UL-10: clickable layers first. The retarget table is built from the
        # SAME id/action decoupling ``hit()`` uses below (``_SLOT_IDS`` names
        # the id, ``self.actions`` names what it emits) — never a second copy.
        layer_actions = {_SLOT_IDS[slot]: self.actions.get(slot, slot)
                         for _btn, slot in self.buttons}
        layer_actions[_GEAR_ID] = _GEAR_ACTION
        layer_action = hit_layer(
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, layer_actions)
        if layer_action is not None:
            return layer_action
        # SD-6: `widgets.click` is the ROUTED-click seam — it emits the click
        # sound exactly once. `btn.hit` stays probe-only.
        if widgets.click(self.debug_gear, mx, my):
            return _GEAR_ACTION
        for btn, slot in self.buttons:
            if widgets.click(btn, mx, my):
                # The slot names the id; ``actions`` names what it emits.
                return self.actions.get(slot, slot)
        return None

    def submit(self, renderer, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        # The baked-in hand-painted art is the DEFAULT, not an unconditional
        # overpaint: a designer who skinned the `backdrop` widget in
        # data/ui/screens/main_menu.json picked a different background, and
        # blitting `main_menu_bg` over it on the very next line is what made
        # that choice look like it did nothing.
        if not getattr(self._backdrop, "skin", None):
            renderer.submit_hud(HudSprite(_BG_SLOT, (0, 0), (view_w, view_h),
                                          anim_time_ms=t))
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
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of)
