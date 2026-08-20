"""UT-Credits: data/ui/credits.json + game/ui/credits.py + editor/credits_ops.py.

`test_strings_data.py`'s shape for the credits roll: the UNCONFIGURED module
default must equal the fixture stock content, configuring from that fixture
must be a no-op, and the row-list ops the editor panel is built out of must
behave. Never reads live `data/ui/credits.json` in an assertion — the fixture
below pins TODAY's values independently of the live file (house rule,
tools/tests/test_fixture_guard.py).

Every test that calls `configure_credits` MUST addCleanup-restore the module's
unconfigured state — it mutates a module global, and a leaked configure
poisons any later test in the same process.
"""
import unittest

from editor import credits_ops
from game.ui import credits

# Verbatim from game/ui/credits.py's _CREDITS at the time data/ui/credits.json
# was authored. Hardcoded here (not read from the live file) per house rule.
_FIXTURE_ROWS = [
    ("Producer", "Seraphin Hesse"),
    ("Game Design Lead", "Fabian Krüger"),
    ("Art Lead", "Hendrik Wagner"),
    ("Programming Lead", "Johann Heinrich"),
    ("", ""),
    ("UI Lead/2D Artist", "Alicia Jaison"),
    ("2D Artist", "Varvara Kozačuk"),
    ("2D Artist", "Jakob Dahlkar"),
    ("", ""),
    ("Game Designer", "Joel Hoch"),
    ("Game Designer", "Benjamin Riese"),
    ("", ""),
    ("Programmer", "Pantelis Charalambous"),
    ("Programmer", "Alfons Kavalic"),
]
_FIXTURE_DOC = {"rows": [{"role": role, "name": name}
                         for role, name in _FIXTURE_ROWS]}


class CreditsDefaultsCase(unittest.TestCase):
    def _restore(self):
        snapshot = list(credits._CREDITS)
        self.addCleanup(lambda: credits._CREDITS.__setitem__(
            slice(None), snapshot))

    def test_unconfigured_default_equals_the_fixture(self):
        self.assertEqual(credits.credit_rows(), _FIXTURE_ROWS)

    def test_configuring_from_the_fixture_is_a_no_op(self):
        self._restore()
        credits.configure_credits(_FIXTURE_DOC)
        self.assertEqual(credits.credit_rows(), _FIXTURE_ROWS)

    def test_configure_rebinds_in_place_and_credit_rows_copies(self):
        self._restore()
        credits.configure_credits({"rows": [{"role": "R", "name": "N"}]})
        self.assertEqual(credits.credit_rows(), [("R", "N")])
        rows = credits.credit_rows()
        rows.append(("mutated", "by the caller"))
        self.assertEqual(credits.credit_rows(), [("R", "N")])


class CreditsFitCase(unittest.TestCase):
    """The shipped roll renders at the literal steps; a longer one shrinks
    but never below the font's own line height."""

    def test_shipped_roll_does_not_shrink(self):
        self.assertEqual(
            credits._row_steps(_FIXTURE_ROWS, credits._ROWS_TOP, 307),
            (credits._LINE_H, credits._SPACER_H))

    def test_a_longer_roll_shrinks_and_stays_above_the_font_floor(self):
        from engine.render.fonts import layout_h
        line, spacer = credits._row_steps(_FIXTURE_ROWS * 3,
                                          credits._ROWS_TOP, 307)
        self.assertLess(line, credits._LINE_H)
        self.assertGreaterEqual(line, layout_h("md"))
        self.assertGreaterEqual(spacer, 1)


class CreditsOpsCase(unittest.TestCase):
    def setUp(self):
        self.doc = {"rows": [{"role": "A", "name": "a"},
                             {"role": "", "name": ""},
                             {"role": "B", "name": "b"}]}

    def test_is_spacer_only_when_both_columns_are_empty(self):
        self.assertTrue(credits_ops.is_spacer(self.doc["rows"][1]))
        self.assertFalse(credits_ops.is_spacer(self.doc["rows"][0]))
        self.assertFalse(credits_ops.is_spacer({"role": "C", "name": ""}))

    def test_insert_and_remove(self):
        credits_ops.insert_row(self.doc, 1, credits_ops.new_person("C", "c"))
        self.assertEqual([r["role"] for r in self.doc["rows"]],
                         ["A", "C", "", "B"])
        credits_ops.remove_row(self.doc, 0)
        self.assertEqual([r["role"] for r in self.doc["rows"]],
                         ["C", "", "B"])

    def test_move_clamps_at_both_ends(self):
        self.assertEqual(credits_ops.move_row(self.doc, 0, -1), 0)
        self.assertEqual(credits_ops.move_row(self.doc, 2, 1), 2)
        self.assertEqual([r["role"] for r in self.doc["rows"]],
                         ["A", "", "B"])
        self.assertEqual(credits_ops.move_row(self.doc, 0, 2), 2)
        self.assertEqual([r["role"] for r in self.doc["rows"]],
                         ["", "B", "A"])


if __name__ == "__main__":
    unittest.main()
