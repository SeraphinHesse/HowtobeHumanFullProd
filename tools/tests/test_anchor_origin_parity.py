"""fix-anchor-origin-parity — the test this shipped bug needed and never had
(docs/briefs/fix-anchor-origin-parity.md §4.1).

The designer's live report: "all vfx regardless how i assign them are not
spawning at the assigned spots i put in the editor." Measured root cause: the
editor draws every anchor handle from the sprite's drawn CENTRE
(`ViewportPanel._anchor_draw_params`); every game consumer used to resolve the
same anchor from a DIFFERENT base (the old `game.anchors.world_offset`'s
`cs.world_to_screen(obj.transform.world_pos)`, missing the `tile_h/2*zoom`
tile-diamond-centre shift and, for a multi-tile footprint, `block_center_
offset` too) — so a handle dragged onto a barrel resolved somewhere else in
game, always, for every anchor. Pre-fix/post-fix numbers are reported by the
executor per the brief's §4, not re-pinned here as a second test — see this
brief's `docs/briefs/fix-anchor-origin-parity.md` §1.

**Never assert either side against the function that produced it** (§1.2 of
the brief — that tautology is how this bug shipped green in the first place):
this test compares the editor's REAL draw path (`ViewportPanel.
_anchor_draw_params` + `editor.anchor_ops.screen_point`) against the game's
REAL resolution path (`cs.world_to_screen(game.anchors.anchor_world_point(
...))`) — two independent call chains that happen to share the same
underlying geometry primitive (`engine.render.sprite_anchor_screen`)
post-fix, never one computed FROM the other.

DELIBERATELY MINIMAL (per the brief's §4): one case only (zoom 1, non-zero
manifest `offset_y`, `fit_tiles=0`) — coverage/edge cases are a separate
reviewer pass's job, not this fix's.
"""
import unittest

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6/pygame, which read those vars at import time.
from tools.tests.qt_harness import APP as _APP

from engine.core import GameObject, SpriteAnimator, Transform
from tools.tests.test_editor_anchors import write_entry
from tools.tests.test_editor_panels import TempDataCase

from editor import anchor_ops
from editor.panels.viewport import ViewportPanel
from game.anchors import anchor_world_point


class TestEditorGameParity(TempDataCase):
    """The SCREEN point the editor draws the handle at must equal the SCREEN
    point the game resolves the same anchor to — computed through the two
    real, independent code paths."""

    def test_nonzero_offset_matches(self):
        slot = "parity_offset_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (40, -10)},
                   offset_x=6, offset_y=-11)
        viewport = self.track(ViewportPanel(data_dir=self.data_dir))
        viewport.resize(800, 600)
        viewport.show()
        _APP.processEvents()
        viewport.set_preview_slot(slot)
        _APP.processEvents()

        origin, s, zoom = viewport._anchor_draw_params()
        editor_screen = anchor_ops.screen_point(origin, 40, -10, s, zoom)

        cs = viewport._coords
        g = cs.geometry
        wx, wy = g.map_cols // 2, g.map_rows // 2   # same tile the preview sits on
        obj = GameObject(
            transform=Transform(wx=wx, wy=wy),
            components=[SpriteAnimator(slot_key=slot, fit_tiles=0.0, scale=1.0)])
        point = anchor_world_point(viewport._assets, cs, obj, "muzzle")
        self.assertIsNotNone(point)
        game_screen = cs.world_to_screen(*point)

        self.assertAlmostEqual(editor_screen[0], game_screen[0], places=6)
        self.assertAlmostEqual(editor_screen[1], game_screen[1], places=6)


if __name__ == "__main__":
    unittest.main()
