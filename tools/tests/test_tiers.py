"""Every test module carries exactly one tier — enforced, not hoped for.

Why this test is load-bearing. The moment anything SELECTS on markers (a tiered
run while iterating, a future CI split), a module that carries no tier simply
never runs. It does not fail, it does not warn — it vanishes, and its coverage
with it.

That is precisely the bug TG-2 killed: the old prototype-parity suite silently
SKIPPED inside a worktree, so the gate went green having proved nothing. Adding
tiers without this guard would rebuild the same trap out of new parts.
"""
import unittest
from pathlib import Path

from conftest import TIERS

TESTS_DIR = Path(__file__).resolve().parent
VALID_TIERS = {"core", "editor", "meta"}


def discovered_modules():
    return {p.stem for p in TESTS_DIR.glob("test_*.py")}


class TestTierCoverage(unittest.TestCase):
    def test_every_module_has_a_tier(self):
        missing = discovered_modules() - set(TIERS)
        self.assertEqual(
            missing, set(),
            f"these test modules have no tier in conftest.TIERS, so a "
            f"marker-selected run would SILENTLY SKIP them: {sorted(missing)}")

    def test_no_tier_entry_points_at_a_deleted_module(self):
        stale = set(TIERS) - discovered_modules()
        self.assertEqual(
            stale, set(),
            f"conftest.TIERS names modules that no longer exist: {sorted(stale)}")

    def test_every_tier_is_one_of_the_three(self):
        bad = {m: t for m, t in TIERS.items() if t not in VALID_TIERS}
        self.assertEqual(bad, {}, f"unknown tier(s): {bad}")
