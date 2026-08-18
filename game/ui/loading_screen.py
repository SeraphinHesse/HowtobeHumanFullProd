"""Post-"Start Game" loading screen (feature: loading screen).

Shown while ``game/main.py`` checkpoints ``build_gameplay()`` across several
frames (``GameState.LOADING``, `game/core/phases.py`), between the
"new_game"/"new_game_debug" intents and the run actually starting. Code-only,
the ``debug_settings.py``/``player_intro.py``/``highscores.py`` precedent:
there is no ``data/ui/screens/loading.json`` and no ``screen_defaults.json``
entry — an absent override means "code defaults" — but it still carries an
``ids`` dict so it is a drop-in the day someone exports it.

Deliberately the SAME visuals as the pre-boot loading screen
(`game/main.py`'s `_submit_loading_frame`, shown before the ``Shell`` even
exists): the ``ui_bg_loading`` background slot plus the white
`widgets.submit_progress_ring` ring, reused from the cutscene skip-hold ring.
The ring's style constants live HERE, the one place, and `main.py` imports
them for its pre-boot screen rather than re-declaring them, so the two
screens cannot visually drift apart. The background is drawn directly off
`assets`/the slot key (the same E-37 "only if imported" check the pre-boot
code uses) rather than through `ScreenSkinning.submit_background` — that
method is the *designer per-screen override* mechanism (a different screen
choosing to borrow this background), not this screen's own baked-in look.
"""
from types import SimpleNamespace

from engine.render import HudSprite

from .skinning import ScreenSkinning
from . import widgets

BG_SLOT = "ui_bg_loading"
RING_RADIUS = 24
RING_WIDTH = 4

SCREEN_ID = "loading"


class LoadingScreen:
    def __init__(self, view_w, view_h, skinning=None):
        self.screen_id = SCREEN_ID
        self.skinning = skinning or ScreenSkinning.empty()
        self._backdrop = SimpleNamespace(rect=(0, 0, view_w, view_h))
        self.ids = {}
        self.layout(view_w, view_h)

    def layout(self, view_w, view_h):
        self._backdrop.rect = (0, 0, view_w, view_h)
        self.ids = {"backdrop": ("backdrop", self._backdrop)}
        self.skinning.apply(self.screen_id, self.ids)

    def submit(self, renderer, assets, view_w, view_h, progress):
        self.layout(view_w, view_h)
        if assets.animation_total_ms(BG_SLOT, "idle") is not None:
            renderer.submit_hud(HudSprite(BG_SLOT, (0, 0), (view_w, view_h)))
        cx, cy = view_w // 2, view_h // 2
        widgets.submit_progress_ring(
            renderer, cx, cy, RING_RADIUS, progress,
            bg=(90, 90, 90), fill=(255, 255, 255), width=RING_WIDTH)
