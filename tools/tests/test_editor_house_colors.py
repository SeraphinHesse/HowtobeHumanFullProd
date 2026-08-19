"""The three house colours every editor colour picker always offers.

Bare minimum: the table is what the designer asked for, seeding really
reaches Qt's shared custom-colour row, and `pick_color` seeds BEFORE the
dialog opens (which is the whole "always available" promise) while keeping
the `[r, g, b]`-or-None contract its three call sites already spoke.
"""
import unittest
from unittest.mock import patch

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog

from editor import house_colors


class HouseColorTableTests(unittest.TestCase):

    def test_the_three_colors_the_designer_asked_for(self):
        self.assertEqual(
            house_colors.HOUSE_COLORS,
            (("Pink", (0xC6, 0x51, 0x97)),
             ("Orange", (0xCF, 0x57, 0x3C)),
             ("Gold", (0xD5, 0xB7, 0x4D))))


class SeedingTests(QtCase):

    def test_seeding_writes_them_into_the_custom_row(self):
        house_colors.seed_house_colors()
        for offset, (_name, rgb) in enumerate(house_colors.HOUSE_COLORS):
            slot = house_colors._SLOT_BASE + offset
            self.assertEqual(QColorDialog.customColor(slot).getRgb()[:3], rgb)

    def test_reseeding_restores_an_overwritten_slot(self):
        """A designer's own "Add to Custom Colors" can land on our slots;
        the next picker must put them back."""
        QColorDialog.setCustomColor(house_colors._SLOT_BASE, QColor(1, 2, 3))
        house_colors.seed_house_colors()
        self.assertEqual(
            QColorDialog.customColor(house_colors._SLOT_BASE).getRgb()[:3],
            house_colors.HOUSE_COLORS[0][1])

    def test_pick_color_seeds_first_and_returns_the_pick(self):
        order = []
        with patch.object(house_colors, "seed_house_colors",
                          side_effect=lambda: order.append("seed")), \
                patch.object(house_colors.QColorDialog, "getColor",
                             side_effect=lambda *a, **k: (
                                 order.append("dialog") or QColor(9, 8, 7))):
            self.assertEqual(house_colors.pick_color(None, [1, 2, 3]),
                             [9, 8, 7])
        self.assertEqual(order, ["seed", "dialog"])

    def test_cancel_returns_none(self):
        with patch.object(house_colors.QColorDialog, "getColor",
                          return_value=QColor()):
            self.assertIsNone(house_colors.pick_color(None, [1, 2, 3]))


if __name__ == "__main__":
    unittest.main()
