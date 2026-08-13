"""pytest wiring: tier markers + the data/ tripwire.

pytest collects unittest.TestCase natively, so adopting it rewrote zero tests.
Two things live here that the tests themselves should not have to know about:

1. TIER MARKERS. Every test module belongs to exactly one tier, declared in
   TIERS below rather than sprinkled across 70 files as decorators. One table
   is greppable, diffable, and cannot drift out of sync with itself.

       py -m pytest -m core        ~40s   every gate
       py -m pytest -m editor             the Qt suites
       py -m pytest -m meta               the agent scaffolding

   There is no `migration` tier any more: the prototype migration is COMPLETE,
   so the parity suite and the one-shot import tool it guarded are gone. CI now
   runs the whole suite — nothing is excluded, and there is no "on demand" tier
   to forget.

   A module missing from TIERS is a hard error, not a silent skip — see
   tools/tests/test_tiers.py. That matters: selecting on markers means an
   unmarked module would simply never run, which is the same class of bug as
   the parity test that silently skipped inside a worktree (TG-2). The fix for
   a trap must not reintroduce the trap.

2. THE data/ TRIPWIRE. The suite must leave data/ byte-identical. Before TG-1
   it did not: leaked Qt widgets outlived their tests and wrote into the repo,
   painting tiles into data/maps/summertest2.json, inventing
   data/maps/uitestexample.json, and appending ui_button_v2 to data/slots.json.
   Nothing was watching, so it went unnoticed for months. Now something is.
"""
import pytest

from tools import data_guard

#: module stem -> tier. Exactly one tier each; test_tiers.py enforces it.
TIERS = {
    # --- meta: the agent scaffolding + test infrastructure -------------------
    # Tests the dispatch rig and the harness, not the game.
    "test_agent_forms": "meta",
    "test_build_script": "meta",
    "test_ci_shards": "meta",  # the CI shard table covers every module once
    "test_data_guard": "meta",
    "test_fixture_guard": "meta",
    "test_orient_hook": "meta",
    "test_qt_harness": "meta",
    "test_smoke_pairing": "meta",
    "test_spawnclaude": "meta",
    "test_test_guard": "meta",   # the PreToolUse hook enforcing the test policy
    "test_test_domains": "meta",   # the test-module -> game-area table
    "test_testgate": "meta",
    "test_tiers": "meta",

    # --- editor: PySide6; the slow tier ------------------------------------
    "test_anchor_origin_parity": "editor",  # fix-anchor-origin-parity: §4.1
    "test_details_panel": "editor",
    "test_editor_anchors": "editor",
    "test_editor_preview_footprint": "editor",  # fix-editor-preview-footprint: §4.1
    "test_editor_asset_import": "editor",
    "test_editor_map_mode": "editor",
    "test_editor_panels": "editor",
    "test_timeline_panel": "editor",  # TimelinePLAN T5: editor/panels/timeline.py
    "test_editor_run_controls": "editor",
    "test_editor_selection": "editor",
    "test_editor_test_run_panel": "editor",  # TR-5: the Qt run window
    "test_editor_camera_limit_center": "editor",
    "test_editor_tutorial_paint": "editor",
    "test_editor_viewport": "editor",
    "test_registry_ops": "editor",
    "test_run_controls": "editor",
    "test_screen_honest_controls": "editor",
    "test_vfx_preview": "editor",

    # --- core: engine + game + data. The 800-odd fast ones ------------------
    "test_10j_qol": "core",
    "test_alpha_render": "core",
    "test_asset_anchors": "core",  # ESV-1: manifest anchors + game.anchors resolver
    "test_asset_store": "core",
    "test_assets_manifest": "core",
    "test_assets_registry": "core",
    "test_audio": "core",
    "test_bake_ui_sheets": "core",  # 10L wave 3: UI sheet baker
    "test_balancing_data": "core",
    "test_base_building": "core",
    "test_beam_crater_sprites": "core",  # vfx-projectile-spritesheets: has-art toggle
    "test_boost": "core",
    "test_boss": "core",
    "test_building_movement": "core",  # Building Movement: move_cost/start_move
    "test_buildings_placement": "core",
    "test_buildings_state_in_components": "core",
    "test_buildings_tier_math": "core",
    "test_button_skin": "core",
    "test_combat_anchors": "core",  # ESV-1: D4 guardrail (muzzle vs. flight timer)
    "test_combat_speed": "core",
    "test_components": "core",
    "test_condition_art": "core",
    "test_construct_card": "core",  # the construct card's widget tree
    "test_coords": "core",
    "test_core": "core",
    "test_corpse": "core",
    "test_cutscene_player": "core",  # TU-5: CutscenePlayer + registry loader
    "test_cutscene_session": "core",  # TU-5: end_turn() pending_cutscene request
    "test_death_spawn": "core",
    "test_debug_log": "core",  # debug mode: recorder + metrics + reports
    "test_defence_aoe_beam": "core",
    "test_digger_telegraphs": "core",  # digger-hop-rework: entry-tile + direction arrows
    "test_editor_test_report": "core",  # TR-4: the report writer is Qt-free (D6)
    "test_editor_test_runner": "core",  # TR-3: the run engine is Qt-free (D6)
    "test_enemies": "core",
    "test_enemy_hp_bars": "core",
    "test_enemy_intro": "core",  # feature-enemy-intro-dialogue: ENEMY_INTRO phase machine
    "test_era_math": "core",  # ES-1: pure era clock / per-era stat + count math
    "test_esv6_converge": "core",  # ESV-6: anchored impact/muzzle VFX (D4 guardrail)
    "test_flow_field": "core",
    "test_footprint_path": "core",
    "test_game_boot": "core",
    "test_ground_cache": "core",
    "test_hp_bar_anchors": "core",  # ESV-1: hp_bar anchor composes with the D3 baseline
    "test_hud_items": "core",
    "test_hud_panel": "core",
    "test_hud_render": "core",
    "test_kidnap": "core",  # Art/enemies: kidnapping
    "test_layout_h_invariant": "core",  # Fix 1 (phase-10L wave3): layout_h pin
    "test_levelup": "core",
    "test_lightning": "core",
    "test_map_overlays": "core",  # MapOverlays: the TIER OVERVIEW toggle pill
    # GpuAndMasterSheetsPLAN M3: editor/master_sheet_import.py + its picker
    # dialog. `editor` because half of it builds Qt widgets.
    "test_master_sheet_import": "editor",
    "test_movement": "core",
    "test_names": "core",
    "test_nine_slice": "core",
    "test_painter_meditator": "core",
    "test_pathfinder": "core",
    "test_phase_loop": "core",
    "test_physics_grid": "core",
    "test_physics_occupancy": "core",
    "test_picking": "core",
    "test_placeholder": "core",
    "test_player_identity": "core",  # player-identity: scores + menu matrix
    "test_prey_hunting": "core",  # Chunk 3/4 prey-hunting + weight profiles
    "test_projectile_anchored_flight": "core",  # feat-projectile-anchored-flight
    "test_qa_triage": "core",  # /datatriage: playtest-session coalescer
    "test_projectile_sprites": "core",  # fix-anchor-offset-and-bullet-sprites Fix 2
    "test_range_sensor": "core",
    "test_render": "core",
    "test_render_backend_parity": "core",
    "test_right_click_dismiss": "core",
    "test_scenarios": "core",
    "test_scene_query": "core",
    "test_schema_slot_sync": "core",  # feature-enemy-intro-dialogue: sprite_slot/animation enum drift
    "test_shell": "core",
    "test_simrun": "core",  # debug mode: the headless balance-sweep runner
    "test_spawn_deco": "core",
    "test_strings_data": "core",  # Phase C: string-table data + T() parity pins
    "test_structure": "core",
    "test_theme_data": "core",  # UH-6: fonts/palette data + tint parity pins
    "test_tile_conditions": "core",
    "test_tile_runtime": "core",
    "test_tile_unlock": "core",
    "test_tilemap_model": "core",
    "test_tilemap_ops": "core",
    "test_tutorial_data": "core",  # TU-1: tutorial script + cutscene registry data
    "test_tutorial_director": "core",  # TU-6: TutorialDirector fake-event chain
    "test_tutorial_engine": "core",  # TU-6: engine.tutorial step-sequencer
    "test_ui_layout_export": "core",  # 10L-B phase B3: layout exporter staleness gate
    "test_ui_min_targets": "core",  # UR-5: click-target floor + static label fit
    "test_ui_skinning": "core",  # 10L-B phase B2: skinning + parity pin
    # UT-1/UT-6: the text_id binding. `editor` because half of it drives a Qt
    # ScreenDetailsPanel against a TempDataCase copy — the pure game-side half
    # (submit_label) rides along rather than living in a second module.
    "test_ui_text_binding": "editor",
    "test_vfx": "core",  # ESV-3a: engine.vfx emitters + the vfx balancing domain
    "test_vfx_play_once": "core",  # ESV-5: PlayOnceVfx + the trigger table
    "test_vfx_variants": "core",  # VA-2: VFX variant selection (engine + game)
    "test_video_playback": "core",
    "test_video_source": "core",
    "test_migration_timeline": "core",  # TimelinePLAN T6: unlock_min_round -> Timeline migration
    "test_timeline_ops": "core",  # TimelinePLAN T5: editor/timeline_ops.py
    "test_wall_render": "core",  # game/map/wall_render.py: the ONE wall emitter
    # UiEditorParentingPLAN P-1: editor/widget_tree.py, the pure parent
    # resolver. Qt-free (like editor/selection.py), but it is an editor module
    # and tracks the editor suites.
    "test_widget_tree": "editor",
    "test_xp_curve": "core",  # TimelinePLAN T3: best-case XP-curve calculator
}


#: tier -> per-test timeout budget, in seconds.
#:
#: Same doctrine as TIERS: one greppable table that cannot drift out of sync
#: with itself, rather than a decorator sprinkled across 120 files. pytest.ini
#: sets the floor (60s); this raises it for the tiers that legitimately need
#: longer. The editor budget is deliberately roomy — the slowest legitimate
#: editor test (TestThemeSwitch, ~23s) could degrade 4x and still not trip it,
#: so a tripped budget means a HANG, not a slow machine.
#:
#: A single genuinely-slow test is raised with a one-line reviewable
#: `@pytest.mark.timeout(n)` on that test. Never widen a whole tier to
#: accommodate one outlier — that de-fangs the other 400.
TIER_TIMEOUTS = {"core": 60, "editor": 120, "meta": 60}


def pytest_collection_modifyitems(config, items):
    """Stamp each test with its module's tier, and that tier's timeout."""
    # Degrade cleanly if pytest-timeout is not installed: the tier markers
    # still apply, and a `timeout` marker with no plugin to read it is inert.
    has_timeout = config.pluginmanager.hasplugin("timeout")
    for item in items:
        tier = TIERS.get(item.path.stem)
        if not tier:
            continue
        item.add_marker(getattr(pytest.mark, tier))
        # Only stamp when the test has no explicit marker of its own — an
        # author's `@pytest.mark.timeout(n)` must win over the tier default.
        if has_timeout and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(TIER_TIMEOUTS[tier]))


@pytest.fixture(scope="session", autouse=True)
def data_stays_clean():
    """The suite must not write into the repo's data/.

    Session-scoped and autouse, so it costs one hash of data/ per worker and
    no test can opt out. Under xdist each worker checks its own view; any
    worker that dirties data/ fails the run.
    """
    before = data_guard.snapshot()
    yield
    problems = data_guard.diff(before, data_guard.snapshot())
    if problems:
        raise AssertionError(
            "the test suite modified the repo's data/ — a test wrote outside "
            "its tempdir copy:\n  " + "\n  ".join(problems))
