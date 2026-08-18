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
    "test_boss_upgrades.py": "ONE class (TestShippedContent) pins the D1/D2/D3 "
                             "authoring invariants JSON Schema cannot express "
                             "on the LIVE boss_upgrades.json — same live-data "
                             "subject as test_balancing_data.py; every "
                             "behavioural assertion in the module reads a "
                             "hand-pinned balance dict instead",
    "test_construct_card.py": "the card tree it pins must agree with the "
                              "committed screen_defaults.json, which is "
                              "exported from the LIVE tree (same subject as "
                              "test_ui_layout_export.py); its portrait check "
                              "asks whether TODAY's registry covers every "
                              "buildable type",
    "test_editor_map_mode.py": "TempDataCase write-isolation on the real tree",
    "test_editor_panels.py": "defines TempDataCase (real tree incl. assets)",
    "test_editor_camera_limit_center.py": "MapModeCase write-isolation on the "
                                          "real tree, same reason as "
                                          "test_editor_map_mode.py",
    "test_editor_tutorial_paint.py": "MapModeCase write-isolation on the real "
                                      "tree, same reason as test_editor_map_mode.py",
    "test_editor_run_controls.py": "TempDataCase-style copy of the real tree",
    "test_font_presets.py": "the live committed fonts.schema.json IS the "
                            "subject (UL-2 opens it to designer-defined "
                            "presets) — a frozen fixture copy of a schema can "
                            "never catch that schema regressing, same "
                            "rationale as test_balancing_data.py",
    "test_game_boot.py": "the 'does today's data actually boot' smoke",
    "test_layout_h_invariant.py": "regenerates the committed screen_defaults.json "
                                  "under a simulated font-metric drift (same "
                                  "live-data subject as test_ui_layout_export.py)",
    "test_nine_slice.py": "validates the SHIPPING sprite manifest",
    "test_qt_harness.py": "exercises the TempDataCase copy machinery itself",
    "test_schema_slot_sync.py": "the drift check's SUBJECT is whether the "
                                "live committed core.schema.json enum agrees "
                                "with the live slots.json registry (feature-"
                                "enemy-intro-dialogue) — a frozen fixture pair "
                                "could never go stale relative to itself",
    "test_smoke_pairing.py": "schema<->content pairing on the live tree",
    "temp_data.py": "IS the copy machinery — reading live data/ to build the "
                    "pruned template is its entire job",
    "test_spawnclaude.py": "dispatch rig runs against the live product surface",
    "test_theme_data.py": "same live-data subject as test_layout_h_invariant.py "
                          "(regenerates committed screen_defaults.json under a "
                          "font-size change) plus validates UH-6's own "
                          "ui_screen.schema.json tint property",
    "test_timeline_ops.py": "TempDataCase-style copy of the real tree, same "
                            "reason as test_editor_map_mode.py",
    "test_ui_min_targets.py": "installs the SHIPPED font face to measure "
                              "label fit against — the .otf is a binary, so "
                              "data/fonts/ is read live; which face, and every "
                              "geometry number, still come from the pin",
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
            if p.name != Path(__file__).name] + [TESTS_DIR / "qt_harness.py",
                                                 TESTS_DIR / "temp_data.py"]


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

    def test_the_temp_data_template_has_the_same_file_set_as_live_data(self):
        """The pruned template STANDS IN media, it never removes it.

        TempDataCase copies from a session-scoped template that truncates
        .wav/.mp3/.ogg/.mp4 to empty files, so each test copies ~10 MB instead
        of ~73 MB. That is only safe while directory listings, registry
        entries, manifest refs and exists() checks see the identical tree —
        the moment "prune" quietly becomes "delete", a test asserting that a
        slot HAS audio starts passing for the wrong reason. Pin the file set,
        and pin that only the stub suffixes lost their bytes.
        """
        from tools.tests import temp_data

        live_root = temp_data.LIVE_DATA
        template = temp_data.template_data()

        def rel_files(root):
            return {p.relative_to(root) for p in root.rglob("*") if p.is_file()
                    if p.relative_to(root).parts[0] not in temp_data.DROPPED_DIRS}

        live, tmpl = rel_files(live_root), rel_files(template)
        self.assertEqual(
            sorted(live - tmpl), [],
            "the template is MISSING files that live data/ has — pruning has "
            "become deleting")
        self.assertEqual(
            sorted(tmpl - live), [],
            "the template has files live data/ does not")

        # Only the stub suffixes may differ in size, and they must be empty.
        wrong = []
        for rel in sorted(live):
            live_size = (live_root / rel).stat().st_size
            tmpl_size = (template / rel).stat().st_size
            if rel.suffix.lower() in temp_data.STUB_SUFFIXES:
                if tmpl_size != 0:
                    wrong.append((str(rel), "stub is not empty"))
            elif tmpl_size != live_size:
                wrong.append((str(rel), f"{tmpl_size} != {live_size}"))
        self.assertEqual(
            wrong, [],
            "a non-stub file changed size in the template, or a stub kept its "
            f"bytes: {wrong}")

    def test_the_fixture_snapshot_exists_and_is_json_only(self):
        fixture = TESTS_DIR / "fixtures" / "data"
        self.assertTrue((fixture / "balancing" / "core.json").exists(),
                        "the pinned snapshot is missing — run "
                        "`py tools/tests/fixture_data.py --refresh`")
        stray = [p for p in fixture.rglob("*")
                 if p.is_file() and p.suffix != ".json"]
        self.assertEqual(stray, [], f"non-JSON crept into the fixture: {stray}")
