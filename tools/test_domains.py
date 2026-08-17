"""The test-module -> area-of-the-game table — one greppable table, in Python.

Same doctrine as ``tools/ci_shards.py`` and ``conftest.TIERS``: the thing that
decides where a test module belongs lives in a file you can import, diff and
TEST, rather than in a naming convention nobody can check. The editor's test
panel (TestRunnerPLAN TR-3/TR-5) renders ONE ROW PER DOMAIN and attributes each
finished test file to its row through ``domain_for``.

**This is not a test module** despite the ``test_`` prefix — ``pytest.ini`` sets
``testpaths = tools/tests``, so nothing here is collected. The name is the one
the plan gives it (TestRunnerPLAN.md TR-1).

Two rules this table must keep, both enforced by
``tools/tests/test_test_domains.py``:

1. **Every test module is claimed by EXACTLY one domain.** Zero means a new test
   file is invisible in the panel — a row that quietly reads "0 tests" is worse
   than a crash, because it looks like success. Two means the panel counts the
   same file twice and its totals lie.
2. **There is NO catch-all domain.** An unmapped module raises from
   ``domain_for``; it never falls into "other". ``tooling`` is a real domain with
   explicit membership, not a bucket.

TIERS says *how fast / what harness*; DOMAINS says *what area of the game*. They
are different questions and this table must never be derived from that one.

Classification rule — apply in order, first match wins. Write any new module in
by the same rule:

1. predominantly exercises ``editor/**`` (a panel, an editor op, the Qt shell)
   -> ``editor``. An incidental ``from editor import domains`` inside a game
   test does not count; the SUBJECT decides.
2. validates or loads ``data/**`` JSON, a schema, or the slot registry ->
   ``data``.
3. exercises only ``engine/**`` (ECS, coords, tilemap, physics, render
   primitives, assets) -> ``engine``.
4. tests the repo's own scaffolding or developer tooling rather than the game
   (the agent rig, the harness, a ``tools/`` script) -> ``tooling``.
5. otherwise the ``game/`` balancing domain it exercises — ``buildings``,
   ``enemies``, ``map``, ``ui``.

Tie-breakers used when rule 5 is genuinely ambiguous (game/core has no row of
its own, so it splits):

- economy / progression / research / village level -> ``buildings``
- rounds, waves, spawning, combat sim, game over -> ``enemies``
- tiles, unlock, pathing, terrain and TILE art -> ``map``
- HUD, screens, shell, strings, cutscenes, player controls, and the
  presentation layer generally — projectiles, VFX, anchors, sprites -> ``ui``
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tools" / "tests"

#: domain key -> display label. INSERTION ORDER IS PANEL ROW ORDER (TR-5
#: iterates this to build rows), so it reads Vision order with `tooling` last.
#: There is deliberately no separate DOMAIN_ORDER to drift out of sync.
DOMAIN_LABELS = {
    "buildings": "Buildings",
    "enemies": "Enemies",
    "map": "Map",
    "ui": "UI",
    "engine": "Engine",
    "editor": "Editor",
    "data": "Data",
    "tooling": "Tooling & Agents",
}

#: domain key -> the test FILENAMES it owns (".py" included: TR-3 parses pytest
#: node-IDs, which carry the extension). Alphabetical within a domain.
DOMAINS = {
    "buildings": (
        "test_base_building.py",
        "test_boost.py",
        "test_building_movement.py",
        "test_buildings_placement.py",
        "test_buildings_state_in_components.py",
        "test_buildings_tier_math.py",
        "test_defence_aoe_beam.py",
        "test_levelup.py",
        "test_lightning.py",
        "test_painter_meditator.py",
        "test_structure.py",
        "test_xp_curve.py",
    ),
    "enemies": (
        "test_boss.py",
        "test_corpse.py",
        "test_death_spawn.py",
        "test_enemies.py",
        "test_enemy_intro.py",
        "test_kidnap.py",
        "test_phase_loop.py",
        "test_prey_hunting.py",
        "test_scenarios.py",
    ),
    "map": (
        "test_condition_art.py",
        "test_flow_field.py",
        "test_footprint_path.py",
        "test_map_overlays.py",
        "test_pathfinder.py",
        "test_picking.py",
        "test_spawn_deco.py",
        "test_tile_conditions.py",
        "test_tile_runtime.py",
        "test_tile_unlock.py",
        "test_tilemap_model.py",
        "test_wall_render.py",
    ),
    "ui": (
        "test_10j_qol.py",
        "test_beam_crater_sprites.py",
        "test_button_skin.py",
        "test_combat_anchors.py",
        "test_combat_speed.py",
        "test_construct_card.py",
        "test_cutscene_player.py",
        "test_cutscene_session.py",
        "test_digger_telegraphs.py",
        "test_enemy_hp_bars.py",
        "test_esv6_converge.py",
        "test_game_boot.py",
        "test_hp_bar_anchors.py",
        "test_hud_panel.py",
        "test_layout_h_invariant.py",
        "test_life_counters.py",
        "test_names.py",
        "test_player_identity.py",
        "test_projectile_anchored_flight.py",
        "test_projectile_sprites.py",
        "test_right_click_dismiss.py",
        "test_shell.py",
        "test_tutorial_director.py",
        "test_ui_align.py",
        "test_ui_layer_draw.py",
        "test_ui_layers.py",
        "test_ui_layout_export.py",
        "test_ui_min_targets.py",
        "test_ui_skinning.py",
        "test_vfx.py",
        "test_vfx_play_once.py",
        "test_vfx_variants.py",
        "test_building_respawn.py",
        "test_highlight_data.py",
    ),
    "engine": (
        "test_alpha_render.py",
        "test_asset_anchors.py",
        "test_asset_store.py",
        "test_assets_manifest.py",
        "test_audio.py",
        "test_components.py",
        "test_coords.py",
        "test_core.py",
        "test_depth_rank.py",
        "test_era_math.py",
        "test_ground_cache.py",
        "test_hud_items.py",
        "test_hud_render.py",
        "test_movement.py",
        "test_nine_slice.py",
        "test_physics_grid.py",
        "test_physics_occupancy.py",
        "test_placeholder.py",
        "test_range_sensor.py",
        "test_render.py",
        "test_render_backend_parity.py",
        "test_scene_query.py",
        "test_tutorial_engine.py",
        "test_video_playback.py",
        "test_video_source.py",
    ),
    "editor": (
        "test_anchor_origin_parity.py",
        "test_details_panel.py",
        "test_editor_anchors.py",
        "test_editor_asset_import.py",
        "test_editor_map_mode.py",
        "test_editor_panels.py",
        "test_editor_preview_footprint.py",
        "test_editor_run_controls.py",
        "test_editor_selection.py",
        "test_editor_camera_limit_center.py",
        "test_editor_tutorial_paint.py",
        "test_editor_viewport.py",
        "test_master_sheet_import.py",
        "test_registry_ops.py",
        "test_vfx_roster_ops.py",
        "test_vfx_roster_panel.py",
        "test_vfx_highlight_preview.py",
        "test_run_controls.py",
        "test_screen_honest_controls.py",
        "test_ui_layer_ops.py",
        "test_tilemap_ops.py",
        "test_timeline_ops.py",
        "test_timeline_panel.py",
        "test_ui_text_binding.py",
        "test_vfx_preview.py",
        "test_widget_tree.py",
    ),
    "data": (
        "test_assets_registry.py",
        "test_balancing_data.py",
        "test_font_presets.py",
        "test_schema_slot_sync.py",
        "test_strings_data.py",
        "test_theme_data.py",
        "test_tutorial_data.py",
    ),
    "tooling": (
        "test_agent_forms.py",
        "test_bake_ui_sheets.py",
        "test_build_script.py",
        "test_ci_shards.py",
        "test_data_guard.py",
        "test_debug_log.py",
        "test_editor_test_report.py",
        "test_editor_test_run_panel.py",
        "test_editor_test_runner.py",
        "test_fixture_guard.py",
        "test_migration_timeline.py",
        "test_orient_hook.py",
        "test_qa_triage.py",
        "test_qt_harness.py",
        "test_simrun.py",
        "test_smoke_pairing.py",
        "test_spawnclaude.py",
        "test_test_domains.py",
        "test_test_guard.py",
        "test_testgate.py",
        "test_tiers.py",
    ),
}


def _build_index():
    """stem -> domain, built once at import. Loud if the table contradicts itself.

    A module listed twice makes the panel's counts lie, and the caller that hits
    it may never run the suite — so it fails at IMPORT, not at test time.
    """
    index = {}
    for domain, modules in DOMAINS.items():
        for module in modules:
            stem = module[:-3] if module.endswith(".py") else module
            if stem in index:
                raise ValueError(
                    f"{module} is in two domains ({index[stem]} and {domain}) "
                    "in tools/test_domains.py — a module belongs to exactly one")
            index[stem] = domain
    return index


#: stem -> domain key. Keyed on the STEM so both spellings resolve.
_BY_MODULE = _build_index()


def domain_for(module):
    """The domain key for a test module.

    Accepts a stem, a filename, a path-ish string or a Path:
    ``"test_boss"``, ``"test_boss.py"``, ``"tools/tests/test_boss.py"``.

    Raises KeyError for an unmapped module. It never returns a default — a new
    test file that nobody classified must be a hard error, not a silent row.
    """
    stem = Path(module).name
    if stem.endswith(".py"):
        stem = stem[:-3]
    try:
        return _BY_MODULE[stem]
    except KeyError:
        raise KeyError(
            f"{stem} is in no domain: add it to DOMAINS in "
            "tools/test_domains.py (there is no catch-all domain)") from None


def modules_for(domain):
    """The test filenames a domain owns — TR-3's per-area re-run reads this."""
    return DOMAINS[domain]


def _main():
    for key, label in DOMAIN_LABELS.items():
        print(f"{label:<18} {len(DOMAINS[key])}")


if __name__ == "__main__":
    _main()
