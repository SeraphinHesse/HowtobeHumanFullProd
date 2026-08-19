"""Post-"Start Game" loading screen (feature: loading screen).

Shown while ``game/main.py`` checkpoints ``build_gameplay()`` across several
frames (``GameState.LOADING``, `game/core/phases.py`), between the
"new_game"/"new_game_debug" intents and the run actually starting — and, since
the Continue/Load-Save rework, from the very first frame after those clicks
too, with the save's own disk read deferred into the checkpoint queue so the
screen is up BEFORE any processing begins.

An EXPORTED screen (`tools/export_ui_layouts.py`'s ``SCREEN_IDS``): its two
widgets (``backdrop`` and ``ring``) carry ids, so a designer moves and resizes
the loading ring in the editor like any other screen's widgets, and
`data/ui/screens/loading.json` holds the overrides. It was code-only (no ids
export, no screen doc) until that; the ``ids`` dict was already here, which is
what made the promotion a two-line change on this side.

Deliberately the SAME visuals as the pre-boot loading screen
(`game/main.py`'s `_submit_loading_frame`, shown before the ``Shell`` even
exists): the ``ui_bg_loading`` background slot plus the white
`widgets.submit_progress_ring` ring, reused from the cutscene skip-hold ring.
Both screens now draw through the ONE `submit_ring` below rather than each
composing the ring themselves, so they cannot visually drift apart; the pre-
boot caller gets its geometry from `default_ring_rect`, since it has no
`ScreenSkinning` (or `Shell`) yet to override anything.

The background is drawn directly off `assets`/the slot key (the same E-37
"only if imported" check the pre-boot code uses) rather than through
`ScreenSkinning.submit_background` — that method is the *designer per-screen
override* mechanism (a different screen choosing to borrow this background),
not this screen's own baked-in look.
"""
from types import SimpleNamespace

from engine.render import HudSprite

from .skinning import ScreenSkinning
from . import widgets

BG_SLOT = "ui_bg_loading"
RING_RADIUS = 24
RING_WIDTH = 4

SCREEN_ID = "loading"


def default_ring_rect(view_w, view_h):
    """The ring's un-overridden, centred box. The ONE place it is derived, so
    the pre-boot screen (which has no `ScreenSkinning` to ask) and this
    screen's own `layout` cannot disagree about where the ring sits before a
    designer moves it."""
    cx, cy = view_w // 2, view_h // 2
    side = RING_RADIUS * 2
    return (cx - RING_RADIUS, cy - RING_RADIUS, side, side)


def submit_ring(renderer, ring_rect, progress):
    """The progress ring, from a RECT.

    Rect-driven rather than centre+radius so a designer's override is the
    whole story: moving the ``ring`` widget moves it, resizing it resizes it.
    The radius is half the SMALLER side, so a non-square override still draws
    a circle (centred in its box) instead of an ellipse the line widget cannot
    express anyway."""
    x, y, w, h = ring_rect
    radius = max(1, min(w, h) // 2)
    widgets.submit_progress_ring(
        renderer, x + w // 2, y + h // 2, radius, progress,
        bg=(90, 90, 90), fill=(255, 255, 255), width=RING_WIDTH)


class LoadingScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h))
        self._ring = SimpleNamespace(rect=default_ring_rect(view_w, view_h))
        self.ids = {}
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        self._backdrop.rect = (0, 0, view_w, view_h)
        self._ring.rect = default_ring_rect(view_w, view_h)
        # `panel` (not `bar`): the ring holder carries geometry only — this
        # screen draws the ring itself from its rect — and `panel` is one of
        # the three kinds a designer may also band/decorate. `bar` would claim
        # a live fill ratio that no generic draw could reproduce.
        self.ids = {"backdrop": ("backdrop", self._backdrop),
                    "ring": ("panel", self._ring)}
        self.skinning.apply(self.screen_id, self.ids)

    def submit(self, renderer, assets, view_w, view_h, progress):
        self.layout(view_w, view_h)
        if (assets is not None
                and assets.animation_total_ms(BG_SLOT, "idle") is not None):
            renderer.submit_hud(HudSprite(BG_SLOT, (0, 0), (view_w, view_h)))
        submit_ring(renderer, self._ring.rect, progress)
