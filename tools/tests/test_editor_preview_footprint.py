"""fix-editor-preview-footprint — the last live instance of the
fix-anchor-origin-parity symptom (docs/briefs/fix-editor-preview-footprint.md).

That earlier fix made the editor handle and the game resolve an anchor's
ORIGIN through one shared formula (`engine.render.sprite_anchor_screen`).
It left the entity preview's `RenderItem` and the handle's `_anchor_draw_
params` submitting at the dataclass defaults (`fit_tiles=0.0`, `scale=1.0`)
regardless of what the entity actually is, while the game draws an enemy at
its real footprint fit (`fit_tiles=footprint`, `scale=sprite_scale`,
`game/enemies/enemy.py`). Measured at the time: every slot in `data/` had
`s == 1.0` on both sides EXCEPT `formation_stage_1` (game `s=0.5`, editor
`s=1.0`), so a Formation anchor resolved at HALF its intended distance in
game.

The Formation case writes its OWN manifest entry (metadata only, no PNG), so
its frame size is a test parameter, not live data. It is sized so the fit
factor stays BELOW 1.0 at the Formation's real era-0 footprint — the whole
point is that the two sides agree on a scale that is not the trivial 1.0.
That footprint is 2 since it went per-era; at the old flat 1 a 128px frame
was what produced the `s=0.5` above, and 256 is the same claim at the new
size.

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

from editor import anchor_ops, sprite_fit
from editor.panels.viewport import ViewportPanel
from game.anchors import anchor_world_point


class TestFormationPreviewMatchesGame(TempDataCase):
    """The SCREEN point the editor draws the Formation's `muzzle` handle at
    must equal the SCREEN point the game resolves the same anchor to, at
    the game's real footprint fit."""

    def test_formation_handle_matches_game_at_real_footprint_fit(self):
        slot = "formation_stage_1"
        write_entry(self.data_dir, slot, frame_w=256, frame_h=256,
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
        # designer retunes either knob. The pair is PER-ERA for every type
        # now, and `formation_stage_1` is the FIRST era child group, so the
        # row that answers for it is `eras[0]`.
        enemies_balance = data_io.load_validated(
            self.data_dir / "balancing" / "enemies.json",
            self.data_dir / "schemas" / "enemies.schema.json")
        era0 = enemies_balance["EnemyTypes"]["Formation"]["eras"][0]
        fit_tiles = float(era0["footprint"])
        game_scale = float(era0["sprite_scale"])

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


class TestBossPreviewFitIsPerEra(TempDataCase):
    """BR-5 regression: the Boss's `footprint`/`sprite_scale` moved into its
    per-era `stats[]` rows in BR-1, so `slot_draw_fit`'s flat read raised
    `KeyError` — swallowed by a bare `except Exception`, which silently
    degraded every `boss_era_*` preview to the `(0.0, 1.0)` render defaults
    for four phases. Pinned against a WRITTEN fixture (never live `data/`):
    each era row gets its own footprint, so a slot resolving to the wrong
    row fails just as loudly as one resolving to the defaults."""

    def _write_per_era_boss_fit(self):
        path = self.data_dir / "balancing" / "enemies.json"
        schema = self.data_dir / "schemas" / "enemies.schema.json"
        doc = data_io.load_validated(path, schema)
        rows = doc["EnemyTypes"]["Boss"]["stats"]
        for index, row in enumerate(rows):
            row["footprint"] = index + 1
            row["sprite_scale"] = 1.0 + index / 10.0
        data_io.write_validated(doc, path, schema)
        return len(rows)

    def test_each_boss_era_slot_resolves_its_own_stats_row(self):
        n_eras = self._write_per_era_boss_fit()
        for era in range(n_eras):
            with self.subTest(era=era):
                fit = sprite_fit.slot_draw_fit(
                    self.data_dir, "enemies", f"boss_era_{era}")
                self.assertNotEqual(fit, sprite_fit.DEFAULT_FIT)
                self.assertEqual(fit, (float(era + 1), 1.0 + era / 10.0))

    def test_an_era_shaped_type_reads_its_own_eras_row(self):
        """The `eras[]` half of the same resolution. Every type but the Boss
        keeps its fit there, and `enemy_stage_1_v1` is the Walker's FIRST era
        child — so the answer is `Standard.eras[0]`, not a block-root pair
        (which no longer exists on any type)."""
        fit = sprite_fit.slot_draw_fit(
            self.data_dir, "enemies", "enemy_stage_1_v1")
        enemies = data_io.load_validated(
            self.data_dir / "balancing" / "enemies.json",
            self.data_dir / "schemas" / "enemies.schema.json")
        era0 = enemies["EnemyTypes"]["Standard"]["eras"][0]
        self.assertNotEqual(fit, sprite_fit.DEFAULT_FIT)
        self.assertEqual(fit, (float(era0["footprint"]),
                               float(era0["sprite_scale"])))

    def test_a_formation_era_slot_resolves_its_own_growing_footprint(self):
        """The Formation is the one shipped type whose footprint CHANGES
        across eras, so each of its four era slots must land on its own row —
        exactly the per-slot claim the boss test above makes, on the type
        that actually exercises it. Pinned against the fixture's own rows,
        never a hardcoded curve."""
        enemies = data_io.load_validated(
            self.data_dir / "balancing" / "enemies.json",
            self.data_dir / "schemas" / "enemies.schema.json")
        rows = enemies["EnemyTypes"]["Formation"]["eras"]
        for era in range(4):     # slots.json ships four Formation era groups
            with self.subTest(era=era):
                fit = sprite_fit.slot_draw_fit(
                    self.data_dir, "enemies", f"formation_stage_{era + 1}")
                self.assertEqual(fit, (float(rows[era]["footprint"]),
                                       float(rows[era]["sprite_scale"])))


if __name__ == "__main__":
    unittest.main()
