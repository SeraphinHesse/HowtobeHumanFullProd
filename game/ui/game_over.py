"""Game over screen (Phase 9G).

Pure logic. Ports the prototype's ``src/ui/game_over_screen.py``: a full-screen
panel with the title, the run's stats, and a button. Since 9H the button returns
``"main_menu"`` (prototype-exact) — the host tears the dead run down and returns
to the shell's main menu, where START NEW GAME builds a fresh run.

Since settings-cut there are TWO buttons: ``PLAY AGAIN`` returns
``"play_again"`` — the host tears the dead run down and arms a FRESH one
without a detour through the menu (exactly what its MAIN MENU sibling does,
minus ``shell.to_main_menu()``) — and ``MAIN MENU`` is unchanged.

10L-B: ``ids`` names ``backdrop``, ``title`` ("THE COLONY WAS DESTROYED") +
``btn_play_again`` + ``btn_return_to_menu``. An invisible button is neither
drawn nor hit-tested.

UT-5: the three run-stat lines are a FIXED set, so each is an id'd label
holder (``stat_round``/``stat_buildings``/``stat_enemies``) bound to its own
``game_over.*`` string template — the numbers stay code-owned, the wording
and the position do not.
"""
from types import SimpleNamespace


from .skinning import ScreenSkinning, button_kwargs, hit_layer, is_visible
from .widgets import Button, anim_ms, label_holder, submit_centered, submit_label
from . import widgets

_BG = (10, 5, 15)
_TITLE = "THE COLONY WAS DESTROYED"
#: The run-stat rows, top to bottom: (widget id, string id). Their vertical
#: step is the pre-UT-5 literal — the rows are laid out in ``layout()`` and
#: stored, so a rect override moves ONE of them and the others keep their own
#: default anchor (the no-cascade convention).
_STAT_ROWS = (
    ("stat_round", "game_over.round_reached"),
    ("stat_buildings", "game_over.buildings_placed"),
    ("stat_enemies", "game_over.enemies_killed"),
)
_STAT_STEP = 14

SCREEN_ID = "game_over"


class GameOverScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        # Copy, not geometry: "RETURN TO MENU" needs 154px at "lg" under the
        # SHIPPED pixel font (data/ui/active_font.json -> pixel_emulator),
        # which is wider per glyph than the SysFont("monospace") fallback every
        # pixel constant here was authored against. "MAIN MENU" needs 101 in
        # the same 120px box, and matches the pause screen's row verbatim.
        self.button = Button((0, 0, 120, 23), "MAIN MENU", font_key="lg")
        # settings-cut: the restart button, above MAIN MENU because it is the
        # one the player reaches for. "PLAY AGAIN" needs 132px at "lg" under
        # the SHIPPED pixel font, so this box is wider than its sibling's.
        self.play_again_btn = Button((0, 0, 140, 23), "PLAY AGAIN",
                                     font_key="lg")
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h), color=_BG)
        self._title = SimpleNamespace(rect=(0, 0, 0, 0), font_key="xxl",
                                      text_color=widgets.C_RED, label=_TITLE,
                                      visible=True)
        self._stats = {name: label_holder(text_id=text_id, align="center")
                       for name, text_id in _STAT_ROWS}
        self.ids = {}
        self._clock = 0.0  # 10L-A: one anim clock per screen
        self.layout(view_w, view_h)  # lay out now so hit() works before submit()

    def layout(self, view_w, view_h):
        pw, ph = self.play_again_btn.rect[2], self.play_again_btn.rect[3]
        self.play_again_btn.rect = (view_w // 2 - pw // 2, view_h // 2 + 55,
                                    pw, ph)
        w, h = self.button.rect[2], self.button.rect[3]
        self.button.rect = (view_w // 2 - w // 2, view_h // 2 + 84, w, h)
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._title.rect = (view_w // 2, view_h // 2 - 60, 0, 0)
        y = view_h // 2 - 15
        for name, _text_id in _STAT_ROWS:
            self._stats[name].rect = (view_w // 2, y, 0, 0)
            y += _STAT_STEP
        self.ids = {
            "backdrop": ("backdrop", self._backdrop),
            "title": ("label", self._title),
            "btn_play_again": ("button", self.play_again_btn),
            "btn_return_to_menu": ("button", self.button),
        }
        for name, _text_id in _STAT_ROWS:
            self.ids[name] = ("label", self._stats[name])
        self.skinning.apply(self.screen_id, self.ids)

    def update(self, dt, mx, my, mouse_down=False):
        self._clock += dt
        for btn in (self.play_again_btn, self.button):
            btn.enabled = True
            btn.hover(mx, my, mouse_down)
            btn.hovered = btn.hovered and is_visible(btn)
            btn.update(dt)

    def hit(self, mx, my):
        layer_action = hit_layer(  # UL-10: clickable layers first
            self.ids, self.skinning.widgets_spec(self.screen_id), mx, my,
            self.skinning.state_of, {"btn_return_to_menu": "main_menu",
                                     "btn_play_again": "play_again"})
        if layer_action is not None:
            return layer_action
        if is_visible(self.play_again_btn) and self.play_again_btn.hit(mx, my):
            return "play_again"
        return ("main_menu" if is_visible(self.button) and self.button.hit(mx, my)
               else None)

    def submit(self, renderer, state, view_w, view_h):
        self.layout(view_w, view_h)
        t = anim_ms(self._clock)
        self.skinning.submit_background(renderer, self.screen_id, view_w,
                                        view_h, anim_ms=t)
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "under", self.skinning.state_of, t)
        widgets.submit_backdrop(renderer, self._backdrop, anim_ms=t)
        if self._title.visible:
            submit_centered(renderer, self._title.label, self._title.rect[0],
                            self._title.rect[1], self._title.font_key,
                            self._title.text_color)
        submit_label(renderer, self._stats["stat_round"],
                     color=widgets.C_UI_TEXT, n=state.round_num)
        submit_label(renderer, self._stats["stat_buildings"],
                     color=widgets.C_UI_TEXT, count=state.buildings_placed)
        submit_label(renderer, self._stats["stat_enemies"],
                     color=widgets.C_UI_TEXT, count=state.enemies_killed)
        for btn in (self.play_again_btn, self.button):
            if is_visible(btn):
                btn.submit(renderer, anim_ms=t, **button_kwargs(btn))
        self.skinning.submit_layers(renderer, self.screen_id, self.ids,
                                    "over", self.skinning.state_of, t)
