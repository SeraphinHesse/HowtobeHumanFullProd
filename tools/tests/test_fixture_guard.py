"""No test reads live ``data/`` unless it is here on purpose — enforced.

Why this test is load-bearing. FP-2 (``planning/completed plans/TestFixturePinningPLAN.md``)
moved every value-asserting test onto the pinned snapshot in
``tools/tests/fixtures/data/`` precisely so a designer editing live data can
never turn the gate red. That repair holds only while nothing quietly writes
``REPO / "data"`` into a new test — which is a one-line habit with years of
muscle memory behind it. Same enforcement shape as ``test_tiers``: the
regression is a hard error naming the offender, not a hope.

A file BELONGS on the allowlist only when live data is its *subject* — it
validates today's tree or drives the real product surface — never because
pinning was inconvenient. Add the entry with its justification.
"""
import re
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: filename -> why it is allowed to read live data/.
ALLOWED = {
    "test_agent_forms.py": "the live form roster IS the dispatch surface",
    "test_asset_anchors.py": "validates the live asset_manifest schema this "
                             "same phase (ESV-1) adds the `anchors` block to "
                             "— same rationale as test_balancing_data.py",
    "test_audio.py": "plays a shipped binary (wav) — not in the JSON fixture",
    "test_bake_ui_sheets.py": "TempDataCase-style copy of the real tree — needs "
                              "the real imported/main_menu_bg.png binary the "
                              "ui_bg_main_menu entry shares, not in the JSON fixture",
    "test_balancing_data.py": "validates the live schema/content pairs (D-12)",
    "test_editor_map_mode.py": "TempDataCase write-isolation on the real tree",
    "test_editor_panels.py": "defines TempDataCase (real tree incl. assets)",
    "test_editor_tutorial_paint.py": "MapModeCase write-isolation on the real "
                                      "tree, same reason as test_editor_map_mode.py",
    "test_editor_run_controls.py": "TempDataCase-style copy of the real tree",
    "test_game_boot.py": "the 'does today's data actually boot' smoke",
    "test_layout_h_invariant.py": "regenerates the committed screen_defaults.json "
                                  "under a simulated font-metric drift (same "
                                  "live-data subject as test_ui_layout_export.py)",
    "test_nine_slice.py": "validates the SHIPPING sprite manifest",
    "test_qt_harness.py": "exercises the TempDataCase copy machinery itself",
    "test_smoke_pairing.py": "schema<->content pairing on the live tree",
    "test_spawnclaude.py": "dispatch rig runs against the live product surface",
    "test_theme_data.py": "same live-data subject as test_layout_h_invariant.py "
                          "(regenerates committed screen_defaults.json under a "
                          "font-size change) plus validates UH-6's own "
                          "ui_screen.schema.json tint property",
    "test_ui_layout_export.py": "diffs the committed screen_defaults.json "
                                "against a fresh regeneration (staleness gate)",
    "test_video_source.py": "plays a shipped binary (mp4) — not in the fixture",
}

#: the ways tests have historically spelled "the repo's live data/".
LIVE_TOKENS = (
    re.compile(r'REPO\s*/\s*"data"'),
    re.compile(r"REPO\s*/\s*'data'"),
    re.compile(r'parents\[2\]\s*/\s*"data"'),
    re.compile(r"\bLIVE_DATA\b"),      # fixture_data's own live handle
)


def scanned_files():
    """Every test module plus the shared harness helpers — except this file,
    whose docstring and token table spell the forbidden patterns."""
    return [p for p in sorted(TESTS_DIR.glob("test_*.py"))
            if p.name != Path(__file__).name] + [TESTS_DIR / "qt_harness.py"]


class TestNoLiveDataOutsideTheAllowlist(unittest.TestCase):
    def test_live_data_reads_are_allowlisted(self):
        offenders = {}
        for path in scanned_files():
            if path.name in ALLOWED:
                continue
            src = path.read_text(encoding="utf-8")
            hits = [pat.pattern for pat in LIVE_TOKENS if pat.search(src)]
            if hits:
                offenders[path.name] = hits
        self.assertEqual(
            offenders, {},
            "\nThese test files read LIVE data/ — a designer edit can turn "
            "the gate red again.\nImport FIXTURE_DATA (or fixture_copy) from "
            "tools.tests.fixture_data instead;\nif live data is genuinely the "
            "test's SUBJECT, add the file to ALLOWED in\n"
            f"{Path(__file__).name} with a one-line justification.\n"
            f"Offenders: {offenders}")

    def test_allowlist_names_only_real_files(self):
        stale = [name for name in ALLOWED
                 if not (TESTS_DIR / name).exists()]
        self.assertEqual(
            stale, [],
            f"ALLOWED names files that no longer exist — prune them: {stale}")

    def test_the_fixture_snapshot_exists_and_is_json_only(self):
        fixture = TESTS_DIR / "fixtures" / "data"
        self.assertTrue((fixture / "balancing" / "core.json").exists(),
                        "the pinned snapshot is missing — run "
                        "`py tools/tests/fixture_data.py --refresh`")
        stray = [p for p in fixture.rglob("*")
                 if p.is_file() and p.suffix != ".json"]
        self.assertEqual(stray, [], f"non-JSON crept into the fixture: {stray}")
