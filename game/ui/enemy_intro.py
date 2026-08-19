"""Enemy/boss introduction dialogue window (feature-enemy-intro-dialogue).

A right-docked, vertically-centered panel (the ``BuildingUI`` panel-geometry
precedent, NOT a full-screen dim like Levelup/Boss-cutscene) that slides in +
fades from the right edge of the screen, holds for a designer-tuned duration,
then slides + fades back out — either automatically or via an early manual
close (X button here; Esc / right-click are host-wired in ``game/main.py``,
the same pre-frozen-guard carve-out the cheat menu uses).

State machine: CLOSED (nothing queued) -> OPENING (slide+fade in over
``window.open_seconds``) -> HOLD (fully open, ``window.hold_seconds``
countdown) -> CLOSING (slide+fade out over ``window.close_seconds``) ->
CLOSED. ``open(entry)`` restarts the clock into OPENING for a new entry;
``request_close()`` is the ONE path every manual-close trigger AND the hold
timer's own expiry both funnel through, so a timed and a manual close look
identical. ``entry`` is one raw ``core.json`` ``EnemyIntro.entries[i]`` dict
(``enemy_label``/``round``/``title``/``body``/``sprite_slot``/``sprite_w``/
``sprite_h``, plus the sprite's view controls — ``animation``/``anim_speed``/
``hidden_frames``/``crop_x``/``crop_y``/``crop_w``/``crop_h``/
``sprite_offset_x``/``sprite_offset_y``/``sprite_flip_h``/
``background_tint``, see below) — read-only, never mutated. ``window_balance``
is ``core.json``'s ``EnemyIntro.window`` dict, read fresh every layout/submit
call rather than snapshotted, so every knob stays live-tunable.

The sprite plays as a looping spritesheet animation for the whole time the
window is visible (open+hold+close), driven by its own ``self._clock`` (a
plain float-seconds accumulator, the ``boss_cutscene.py`` pattern — an
independent clock from the world/tilemap's ``SpriteAnimator``), scaled by the
entry's ``anim_speed`` and converted via ``widgets.anim_ms``. ``sprite_slot``
may reference ANY slot in ``data/slots.json`` (not only ``enemies`` art —
regenerate the schema's enum with ``tools/gen_sprite_slot_enum.py`` after
adding a slot); ``animation`` names one of that slot's manifest rows, falling
back to idle at runtime if absent. ``crop_w``/``crop_h`` of ``0`` means no
crop (draw the whole frame); ``hidden_frames`` narrows playback further than
whatever the manifest row's own ``hidden`` list already drops, never widens it
back. ``background_tint``'s alpha channel composes with the window's own
fade.
"""
from types import SimpleNamespace

from engine.render import HudRect, HudSprite
from engine.render.fonts import layout_h

from .skinning import ScreenSkinning, is_visible
from .widgets import Button, contains, submit_centered, submit_panel, wrap_text
from . import widgets

SCREEN_ID = "enemy_intro"

_OPENING, _HOLD, _CLOSING, _CLOSED = "opening", "hold", "closing", "closed"

_CLOSE_BTN_W, _CLOSE_BTN_H = 20, 18
_CLOSE_BTN_MARGIN = 6


def _lerp(a, b, t):
    return a + (b - a) * t


class EnemyIntroWindow:
    def __init__(self, view_w, view_h, window_balance, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self.view_w = view_w
        self.view_h = view_h
        self.window_balance = window_balance
        self.entry = None
        self._phase = _CLOSED
        self._t = 0.0  # seconds elapsed in the current phase
        self._clock = 0.0  # seconds elapsed since open() — the sprite's own
        # animation clock, running continuously across open+hold+close
        # (feature-enemy-intro-dialogue), the boss_cutscene.py precedent.
        self._close_btn = Button((0, 0, _CLOSE_BTN_W, _CLOSE_BTN_H), "X", "md")
        self._panel = SimpleNamespace(rect=(view_w, 0, 0, 0), skin=None)
        self.ids = {}

    @property
    def visible(self):
        return self._phase != _CLOSED

    def open(self, entry):
        """Restart the open animation for ``entry`` — the host calls this
        both for the very first queued entry (on the BUILDING ->
        ENEMY_INTRO phase edge) and for every subsequent queued entry (once
        the previous one finishes closing)."""
        self.entry = entry
        self._phase, self._t = _OPENING, 0.0
        self._clock = 0.0
        self.layout(self.view_w, self.view_h)

    def request_close(self):
        """Jump straight to CLOSING from OPENING or HOLD — the shared path
        for the hold timer expiring AND every manual-close trigger (X / Esc
        / right-click), so they close identically. A no-op once already
        CLOSING or CLOSED."""
        if self._phase in (_OPENING, _HOLD):
            self._phase, self._t = _CLOSING, 0.0

    def layout(self, view_w, view_h):
        self.view_w, self.view_h = view_w, view_h
        w = self.window_balance["width"]
        h = self.window_balance["height"]
        y = (view_h - h) // 2
        x = self._current_x(view_w, w)
        self._panel.rect = (x, y, w, h)
        self._close_btn.rect = (
            x + w - _CLOSE_BTN_W - _CLOSE_BTN_MARGIN, y + _CLOSE_BTN_MARGIN,
            _CLOSE_BTN_W, _CLOSE_BTN_H)
        self.ids = {
            "panel": ("panel", self._panel),
            "close_btn": ("button", self._close_btn),
        }
        self.skinning.apply(self.screen_id, self.ids)

    def _current_x(self, view_w, w):
        closed_x, open_x = view_w, view_w - w
        if self._phase == _OPENING:
            open_s = max(self.window_balance["open_seconds"], 1e-6)
            return _lerp(closed_x, open_x, min(1.0, self._t / open_s))
        if self._phase == _HOLD:
            return open_x
        if self._phase == _CLOSING:
            close_s = max(self.window_balance["close_seconds"], 1e-6)
            return _lerp(open_x, closed_x, min(1.0, self._t / close_s))
        return closed_x

    def _alpha(self):
        if self._phase == _OPENING:
            open_s = max(self.window_balance["open_seconds"], 1e-6)
            return round(255 * min(1.0, self._t / open_s))
        if self._phase == _HOLD:
            return 255
        if self._phase == _CLOSING:
            close_s = max(self.window_balance["close_seconds"], 1e-6)
            return round(255 * (1.0 - min(1.0, self._t / close_s)))
        return 0

    def update(self, dt, mx, my, mouse_down=False):
        if self._phase == _CLOSED:
            return
        self._t += dt
        self._clock += dt
        if (self._phase == _OPENING
                and self._t >= self.window_balance["open_seconds"]):
            self._phase, self._t = _HOLD, 0.0
        elif (self._phase == _HOLD
              and self._t >= self.window_balance["hold_seconds"]):
            self.request_close()
        elif (self._phase == _CLOSING
              and self._t >= self.window_balance["close_seconds"]):
            self._phase, self._t = _CLOSED, 0.0
            self.entry = None
        if self.visible:
            self.layout(self.view_w, self.view_h)
            self._close_btn.hover(mx, my, mouse_down)
            self._close_btn.hovered = (self._close_btn.hovered
                                       and is_visible(self._close_btn))
            # Its own hover/pressed animation clock — the one button in
            # `game/ui` that was never ticked, so its skin rows never played.
            self._close_btn.update(dt)

    def hit(self, mx, my):
        """``True`` on a close-X hit — the only interactive element in this
        panel. The host swallows every other click while this phase holds,
        the Levelup/Boss-cutscene "modal swallows clicks" convention."""
        return (self.visible and is_visible(self._close_btn)
                and contains(self._close_btn.rect, mx, my))

    # -- render -------------------------------------------------------

    def submit(self, renderer, view_w, view_h):
        if not self.visible or self.entry is None:
            return
        self.layout(view_w, view_h)
        t = widgets.anim_ms(self._clock)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of, t)
        alpha = self._alpha()
        x, y, w, h = self._panel.rect
        submit_panel(renderer, (x, y, w, h), skin=self._panel.skin,
                    fill=(*widgets.C_UI_PANEL, alpha),
                    border=(*widgets.C_UI_BORDER, alpha))
        if is_visible(self._close_btn):
            self._close_btn.submit(renderer,
                                   text_color=(*widgets.C_UI_TEXT, alpha))
        cx = x + w // 2
        cursor = y + _CLOSE_BTN_MARGIN + _CLOSE_BTN_H + 12
        entry = self.entry
        sw, sh = entry["sprite_w"], entry["sprite_h"]
        sprite_x = cx - sw // 2 + entry["sprite_offset_x"]
        sprite_y = cursor + entry["sprite_offset_y"]

        bg_r, bg_g, bg_b, bg_a = entry["background_tint"]
        if bg_a > 0:
            renderer.submit_hud(HudRect(
                (sprite_x, sprite_y, sw, sh),
                (bg_r, bg_g, bg_b, round(bg_a * alpha / 255))))

        crop_w, crop_h = entry["crop_w"], entry["crop_h"]
        crop = (entry["crop_x"], entry["crop_y"], crop_w, crop_h) \
            if (crop_w or crop_h) else None
        anim_time_ms = widgets.anim_ms(self._clock * entry["anim_speed"])
        renderer.submit_hud(HudSprite(
            entry["sprite_slot"], (sprite_x, sprite_y), (sw, sh),
            tint=(255, 255, 255, alpha), flip=entry["sprite_flip_h"],
            animation=entry["animation"], anim_time_ms=anim_time_ms,
            crop=crop, hidden_frames=tuple(entry["hidden_frames"])))
        cursor += sh + 12
        submit_centered(renderer, self.entry["title"], cx, cursor, "lg",
                        (*widgets.C_GOLD, alpha))
        cursor += layout_h("lg") + 8
        for line in wrap_text(self.entry["body"], "sm", w - 24, max_lines=12):
            submit_centered(renderer, line, cx, cursor, "sm",
                            (*widgets.C_UI_TEXT, alpha))
            cursor += layout_h("sm") + 2
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of, t)
