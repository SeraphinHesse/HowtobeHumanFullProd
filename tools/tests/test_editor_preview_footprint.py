"""fix-editor-preview-footprint — the last live instance of the
fix-anchor-origin-parity symptom (docs/briefs/fix-editor-preview-footprint.md).

That earlier fix made the editor handle and the game resolve an anchor's
ORIGIN through one shared formula (`engine.render.sprite_anchor_screen`).
It left the entity preview's `RenderItem` and the handle's `_anchor_draw_
params` submitting at the dataclass defaults (`fit_tiles=0.0`, `scale=1.0`)
regardless of what the entity actually is, while the game draws an enemy at
its real footprint fit (`fit_tiles=footprint`, `scale=sprite_scale`,
`game/enemies/enemy.py`). Measured: every slot in `data/` has `s == 1.0` on
both sides EXCEPT `formation_stage_1` (`frame_w=128`, footprint 1 tile ->
game `s=0.5`, editor `s=1.0`), so a Formation anchor used to resolve at HALF
its intended distance in game.

Same shape as `tools/tests/test_anchor_origin_parity.py`, same rule
(**never assert either side against the function that produced it**): this
compares the editor's REAL draw path (`ViewportPanel._anchor_draw_params` +
`editor.anchor_ops.screen_point`) against the game's REAL resolution path
(`game.anchors.anchor_world_point`, fed the SAME footprint/scale
`game/enemies/enemy.py` would read off `data/balancing/enemies.json` for a
real `Formation`) — two independent call chains, never one computed from
the other.

DELIBERATELY MINIMAL, per the brief's §4: one end-to-end Formation case
only — coverage/edge cases are a separate reviewer pass's job.
"""
import unittest

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6/pygame, which read those vars at import time.
from tools.tests.qt_harness import APP as _APP

from engine.core import GameObject, SpriteAnimator, Transform
from engine import data_io
from tools.tests.test_editor_anchors import write_entry
from tools.tests.test_editor_panels import TempDataCase

from editor import anchor_ops
from editor.panels.viewport import ViewportPanel
from game.anchors import anchor_world_point


class TestFormationPreviewMatchesGame(TempDataCase):
    """The SCREEN point the editor draws the Formation's `muzzle` handle at
    must equal the SCREEN point the game resolves the same anchor to, at
    the game's real footprint fit."""

    def test_formation_handle_matches_game_at_real_footprint_fit(self):
        slot = "formation_stage_1"
        write_entry(self.data_dir, slot, frame_w=128, frame_h=128,
                   anchors={"muzzle": (40, -10)})
        viewport = self.track(ViewportPanel(data_dir=self.data_dir))
        viewport.resize(800, 600)
        viewport.show()
        _APP.processEvents()
        viewport.set_preview_slot(slot)
        _APP.processEvents()

        origin, s, zoom = viewport._anchor_draw_params()
        editor_screen = anchor_ops.screen_point(origin, 40, -10, s, zoom)

        # The game's real construction values for Formation
        # (game/enemies/enemy.py: fit_tiles=footprint, scale=sprite_scale) —
        # read from data, never hardcoded, so this stays honest if the
        # designer retunes either knob.
        enemies_balance = data_io.load_validated(
            self.data_dir / "balancing" / "enemies.json",
            self.data_dir / "schemas" / "enemies.schema.json")
        formation = enemies_balance["EnemyTypes"]["Formation"]
        fit_tiles = float(formation["footprint"])
        game_scale = float(formation["sprite_scale"])

        cs = viewport._coords
        g = cs.geometry
        wx, wy = g.map_cols // 2, g.map_rows // 2   # same tile the preview sits on
        obj = GameObject(
            transform=Transform(wx=wx, wy=wy),
            components=[SpriteAnimator(slot_key=slot, fit_tiles=fit_tiles,
                                       scale=game_scale)])
        point = anchor_world_point(viewport._assets, cs, obj, "muzzle")
        self.assertIsNotNone(point)
        game_screen = cs.world_to_screen(*point)

        self.assertAlmostEqual(editor_screen[0], game_screen[0], places=6)
        self.assertAlmostEqual(editor_screen[1], game_screen[1], places=6)


if __name__ == "__main__":
    unittest.main()
