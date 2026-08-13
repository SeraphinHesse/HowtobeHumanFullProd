"""The domain table covers every test module exactly once — enforced.

The editor's test panel attributes every finished test file to an area of the
game. That buys a designer a failure they can read, and costs a new way to be
silently wrong: a module no domain claims simply never appears in any row, and a
panel that shows eight green rows says so with total confidence. Same failure
mode as ``test_tiers`` and ``test_ci_shards``, one layer up, so it gets the same
treatment — a hard error naming the offender.

These tests read ``tools/test_domains.py``'s table against the directory
listing. They do not run pytest and do not import Qt or pygame.
"""
import unittest
from pathlib import Path

from tools import test_domains

TESTS_DIR = Path(test_domains.TESTS_DIR)


def _modules():
    """Every collectable test module stem, from disk."""
    return {p.stem for p in TESTS_DIR.glob("test_*.py")}


class TestEveryModuleHasExactlyOneDomain(unittest.TestCase):
    def test_every_module_is_claimed_exactly_once(self):
        counts = {stem: 0 for stem in _modules()}
        for domain, modules in test_domains.DOMAINS.items():
            for module in modules:
                stem = Path(module).stem
                counts[stem] = counts.get(stem, 0) + 1

        never = sorted(s for s in _modules() if counts[s] == 0)
        twice = sorted(s for s, n in counts.items() if n > 1)
        self.assertEqual(
            never, [],
            "these test modules are in no domain, so the editor's test panel "
            f"would never show them and would still read all-green: {never}. "
            "Add each to DOMAINS in tools/test_domains.py.")
        self.assertEqual(
            twice, [],
            "these test modules are in more than one domain, so the panel "
            f"counts them twice and its totals lie: {twice}")

    def test_no_stale_entry(self):
        on_disk = _modules()
        missing = sorted(m for mods in test_domains.DOMAINS.values()
                         for m in mods if Path(m).stem not in on_disk)
        self.assertEqual(missing, [],
                         f"DOMAINS names files that are gone: {missing}")

    def test_no_duplicate_filename_inside_one_domain(self):
        for domain, modules in test_domains.DOMAINS.items():
            self.assertEqual(sorted(modules), sorted(set(modules)),
                             f"duplicate filename in domain {domain}")

    def test_every_domain_names_at_least_one_real_file(self):
        empty = sorted(d for d, mods in test_domains.DOMAINS.items() if not mods)
        self.assertEqual(empty, [],
                         f"these domains would render as blank rows: {empty}")


class TestLabels(unittest.TestCase):
    def test_domains_and_labels_have_the_same_keys(self):
        """A label-less domain renders blank; a domain-less label renders empty."""
        self.assertEqual(sorted(test_domains.DOMAINS),
                         sorted(test_domains.DOMAIN_LABELS))

    def test_every_label_is_a_non_empty_string(self):
        for key, label in test_domains.DOMAIN_LABELS.items():
            self.assertIsInstance(label, str)
            self.assertTrue(label.strip(), f"{key} has a blank label")

    def test_tooling_is_the_last_row(self):
        """Row order is DOMAIN_LABELS' insertion order; tooling reads last."""
        self.assertEqual(list(test_domains.DOMAIN_LABELS)[-1], "tooling")


class TestDomainFor(unittest.TestCase):
    def test_exhaustive_and_consistent(self):
        for stem in sorted(_modules()):
            domain = test_domains.domain_for(stem)
            self.assertIn(domain, test_domains.DOMAINS)
            self.assertIn(f"{stem}.py", test_domains.modules_for(domain))

    def test_spellings_agree(self):
        answers = {
            test_domains.domain_for("test_boss"),
            test_domains.domain_for("test_boss.py"),
            test_domains.domain_for("tools/tests/test_boss.py"),
            test_domains.domain_for(TESTS_DIR / "test_boss.py"),
        }
        self.assertEqual(answers, {"enemies"})

    def test_unknown_module_raises(self):
        """No catch-all: an unclassified module must be loud, not 'other'."""
        with self.assertRaises(KeyError):
            test_domains.domain_for("test_not_a_real_module.py")

    def test_pinned_anchors(self):
        expected = {
            "test_boss.py": "enemies",            # the plan's Quick Test
            "test_editor_map_mode.py": "editor",
            "test_tilemap_model.py": "map",
            "test_buildings_placement.py": "buildings",
            "test_hud_panel.py": "ui",
            "test_components.py": "engine",
            "test_balancing_data.py": "data",
            "test_tiers.py": "tooling",
        }
        got = {m: test_domains.domain_for(m) for m in expected}
        self.assertEqual(got, expected)
