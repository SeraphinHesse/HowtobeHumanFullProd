"""Phase 4 acceptance tests: selector + balancing panels + domains
(ED-3, ED-30/31).

Same headless conventions as test_editor_viewport.py: QT_QPA_PLATFORM=
offscreen + SDL dummy drivers before any Qt/pygame import, one
QApplication per process. Every test runs against a tempfile COPY of
data/ so panel writes never touch the repo's files — which is why all
editor modules take a data_dir parameter.
"""
import copy
import json
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase
# Re-exported: TempDataCase's home is temp_data.py, but every import site in
# the suite spells it `from tools.tests.test_editor_panels import TempDataCase`.
from tools.tests.temp_data import TempDataCase  # noqa: F401

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from editor import balancing_history, domains, keybinds, theme
from editor.panels.balancing import BalancingPanel, CollapsibleSection
from editor.panels.selector import _PAYLOAD_ROLE, SelectorPanel
from engine import data_io, era_math
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]


def read_domain(data_dir, domain):
    return data_io.load_validated(
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


# TempDataCase grew up in this file, but seven other modules already reached
# across to import it from here and three more had copy-pasted its copytree by
# hand. It now lives in tools/tests/temp_data.py (which also builds the pruned
# session template each copy comes from) and is re-exported here so that every
# existing `from tools.tests.test_editor_panels import TempDataCase` keeps
# working unchanged.


class TestDomainsDerivation(TempDataCase):
    """AD-6: the domain list is DERIVED (slots.json category order ∩ the
    categories with a data/balancing/<key>.json), never hardcoded — a new
    balancing domain reaches the editor with zero editor edits."""

    # ESV-3a promoted "vfx" from an asset-only slots.json category to a real
    # balancing domain (data/balancing/vfx.json + data/schemas/vfx.schema.json)
    # — it now belongs in the CANONICAL tuple, positioned exactly where
    # slots.json's category order puts it: right after "core" (confirmed
    # directly against data/slots.json's categories[] order, never inferred
    # from this file's own prior expectation).
    CANONICAL = ("buildings", "enemies", "map", "ui", "core", "vfx")

    def add_domain_files(self, key):
        """A new balancing domain in the temp tree: schema + content, content
        through the validating writer (tests obey D-2 too)."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{key}.schema.json",
            "type": "object",
            "additionalProperties": False,
            "required": ["enabled"],
            "properties": {
                "enabled": {
                    "description": "Synthetic tunable for derivation coverage.",
                    "type": "boolean",
                },
            },
        }
        schema_path = self.data_dir / "schemas" / f"{key}.schema.json"
        schema_path.write_text(data_io.dumps_deterministic(schema), encoding="utf-8")
        data_io.write_validated(
            {"enabled": True},
            self.data_dir / "balancing" / f"{key}.json",
            schema_path,
        )

    def test_derivation_reproduces_the_canonical_tuple(self):
        self.assertEqual(domains.domains(self.data_dir), self.CANONICAL)

    def test_real_data_dir_derives_the_canonical_tuple(self):
        """No data_dir → the repo's own data/. The regression guard for the
        deleted DOMAINS constant."""
        self.assertEqual(domains.domains(), self.CANONICAL)

    def test_removing_a_balancing_file_drops_the_domain(self):
        (self.data_dir / "balancing" / "map.json").unlink()
        self.assertEqual(
            domains.domains(self.data_dir),
            ("buildings", "enemies", "ui", "core", "vfx"))

    def test_new_balancing_file_adds_a_domain_in_slots_order(self):
        """deco is an asset-only category TODAY (vfx was this class's
        example until ESV-3a promoted it to a real domain — see CANONICAL);
        give deco balancing files and it becomes a domain — positioned where
        slots.json puts it (after vfx), with no editor edit anywhere."""
        self.add_domain_files("deco")
        self.assertEqual(
            domains.domains(self.data_dir), self.CANONICAL + ("deco",))

    def test_selector_picks_up_a_new_domain_with_no_editor_edit(self):
        # "backgrounds", not "deco": SelectorPanel.domains() only walks TOP-
        # LEVEL tree items, and deco's root is nested under "map" (a
        # tree-construction-only choice, see selector.py) — invisible to
        # this check regardless of domain-ness. backgrounds stays top-level.
        self.assertNotIn(
            "backgrounds", self.track(SelectorPanel(data_dir=self.data_dir)).domains())
        self.add_domain_files("backgrounds")
        self.assertIn(
            "backgrounds", self.track(SelectorPanel(data_dir=self.data_dir)).domains())


class TestSelectorContextMenu(TempDataCase):
    """AD-6: right-click a CATEGORY root → one "Add New X…" per form spec whose
    selector_context is that category; empty space → Add New Category. Never
    exec()s a menu (it would block); QAction.trigger() is the test path."""

    def make(self):
        return self.track(SelectorPanel(data_dir=self.data_dir))

    def test_entries_come_from_the_specs_selector_context(self):
        ids = [fid for _label, fid in self.make()._add_entries("enemies")]
        self.assertIn("add-enemy", ids)

    def test_category_menu_emits_the_mapped_form_id(self):
        panel = self.make()
        ids = [fid for _label, fid in panel._add_entries("enemies")]
        menu = panel._context_menu(panel._find_item("enemies", ()))
        self.assertIsNotNone(menu)
        seen = []
        panel.add_requested.connect(seen.append)
        menu.actions()[ids.index("add-enemy")].trigger()
        self.assertEqual(seen, ["add-enemy"])

    def test_empty_space_offers_add_category(self):
        panel = self.make()
        self.assertEqual(
            [fid for _label, fid in panel._add_entries(None)], ["add-category"])
        menu = panel._context_menu(None)
        seen = []
        panel.add_requested.connect(seen.append)
        menu.actions()[0].trigger()
        self.assertEqual(seen, ["add-category"])

    def test_group_and_maps_nodes_offer_no_menu(self):
        panel = self.make()
        group = panel._find_item("enemies", ()).child(0)   # a group node
        self.assertIsNone(panel._context_menu(group))
        self.assertIsNone(panel._context_menu(panel._maps_branch))

    def _category_roots(self, panel):
        """Every CATEGORY ROOT in the tree (payload path == ()), in tree order
        — including the ones nested under "map" (deco/conditions), whose
        payload path is () too."""
        keys, stack = [], [panel.topLevelItem(i)
                           for i in range(panel.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            payload = item.data(0, _PAYLOAD_ROLE)
            if payload is not None and tuple(payload[1]) == ():
                keys.append(payload[0])
            stack.extend(item.child(i) for i in range(item.childCount()))
        return keys

    def _category_without_a_spec(self, panel):
        """A category key that genuinely has NO form spec, DERIVED at runtime
        from the same data/agent_forms/*.json roster the panel consults —
        never a hardcoded example. ("vfx" used to be hardcoded here; then
        add-vfx.json was added and the premise silently became false.)"""
        contexts = set()
        for path in sorted((self.data_dir / "agent_forms").glob("*.json")):
            spec = json.loads(path.read_text(encoding="utf-8"))
            contexts.add(spec.get("selector_context"))
        for key in self._category_roots(panel):
            if key not in contexts:
                return key
        return None

    def test_category_without_a_spec_offers_no_menu(self):
        panel = self.make()
        key = self._category_without_a_spec(panel)
        if key is None:
            self.skipTest(
                "every category in the tree now has a form spec — no spec-less "
                "category left to assert against")
        self.assertEqual(panel._add_entries(key), [])
        self.assertIsNone(panel._context_menu(panel._find_item(key, ())))

    def test_broken_spec_does_not_break_right_click(self):
        """An unhandled exception in a Qt event handler can abort the process:
        a bad spec must degrade to 'no menu', never raise."""
        (self.data_dir / "agent_forms" / "broken.json").write_text(
            "{ not json", encoding="utf-8")
        panel = self.make()
        self.assertEqual(panel._add_entries("enemies"), [])
        self.assertIsNone(panel._context_menu(panel._find_item("enemies", ())))


class TestSelector(TempDataCase):
    def test_lists_domains_in_d10_order(self):
        panel = self.track(SelectorPanel(data_dir=self.data_dir))
        # the LITERAL canonical tuple, not domains.domains(...) — both sides
        # derive now, so comparing them would be a tautology. "vfx" joined
        # (ESV-3a promoted it from asset-only to a real balancing domain).
        self.assertEqual(
            panel.domains(),
            ("buildings", "enemies", "map", "ui", "core", "vfx"))

    def test_domain_without_file_is_omitted(self):
        """A category INTENDED as a domain (it has a schema) whose balancing
        file is gone is omitted WHOLE — not degraded to an asset-only node.
        Every leaf under it emits domain_selected, which would drive the
        balancing panel into a missing file."""
        (self.data_dir / "balancing" / "map.json").unlink()
        panel = self.track(SelectorPanel(data_dir=self.data_dir))
        self.assertEqual(
            panel.domains(), ("buildings", "enemies", "ui", "core", "vfx"))
        with self.assertRaises(KeyError):
            panel._find_item("map", ())   # no node at all, not just no domain

    def test_map_leaf_emits_no_domain_when_map_is_not_a_domain(self):
        """With NEITHER balancing/map.json NOR schemas/map.schema.json, "map"
        is a plain asset-only category: the node is shown (the omission guard
        keys off the schema) and the Maps branch is built — so the map-leaf
        branch of _emit_selection must be gated too, or clicking a map raises
        FileNotFoundError out of BalancingPanel.set_domain inside a Qt slot."""
        (self.data_dir / "balancing" / "map.json").unlink()
        (self.data_dir / "schemas" / "map.schema.json").unlink()
        panel = self.track(SelectorPanel(data_dir=self.data_dir))
        self.assertNotIn("map", panel.domains())
        panel._find_item("map", ())        # shown, not omitted (no schema)

        domains_seen, maps_seen = [], []
        panel.domain_selected.connect(domains_seen.append)
        panel.map_selected.connect(maps_seen.append)
        map_ids = panel.map_ids()
        self.assertTrue(map_ids)           # the Maps branch really is populated
        panel.select_map(map_ids[0])
        self.assertEqual(maps_seen, [map_ids[0]])   # tilemap mode still works
        self.assertEqual(domains_seen, [])          # but NO domain_selected

    def test_selection_emits_domain_and_is_single(self):
        panel = self.track(SelectorPanel(data_dir=self.data_dir))
        seen = []
        panel.domain_selected.connect(seen.append)
        panel.select_domain("enemies")
        panel.select_domain("core")
        self.assertEqual(seen, ["enemies", "core"])
        self.assertEqual(len(panel.selectedItems()), 1)  # ED-3


class TestSelectorTree(TempDataCase):
    """Phase 5 (ED-10/11): the tree grows from the slot registry — category
    roots with group children, ● markers from the manifest. Domain behavior
    (TestSelector above) must survive unchanged.

    Painter is this class's UNASSIGNED example — the node that must NOT carry
    a ● until one is written. Pinned in setUp: it was merely assumed empty,
    then art landed on painter_t1_lvl1, which turned
    test_markers_reflect_migrated_manifest red and quietly made
    test_markers_refresh_after_manifest_write vacuous (it asserts a marker
    APPEARS after a write — which proves nothing if it was there all along)."""

    def setUp(self):
        super().setUp()
        self.unassign_family("painter")   # the group's ● must be off to start

    def make(self):
        return self.track(SelectorPanel(data_dir=self.data_dir))

    def test_tree_stops_at_dropdown_nodes(self):
        panel = self.make()
        panel.select_node("buildings", ("Defender",))
        self.assertEqual(panel.selectedItems()[0].childCount(), 0)  # tiers -> Details
        panel.select_node("map", ("Tiles",))
        self.assertEqual(panel.selectedItems()[0].childCount(), 0)  # families -> Details

    def test_node_selection_emits_payload_and_domain(self):
        panel = self.make()
        nodes, domains = [], []
        panel.node_selected.connect(lambda c, p: nodes.append((c, p)))
        panel.domain_selected.connect(domains.append)
        panel.select_node("buildings", ("Defender",))
        self.assertEqual(nodes[-1], ("buildings", ("Defender",)))
        self.assertEqual(domains[-1], "buildings")
        panel.select_node("enemies", ("Boss",))
        self.assertEqual(domains[-1], "enemies")

    def test_asset_only_categories_exist_but_are_not_domains(self):
        """`vfx` was this class's asset-only example until ESV-3a gave it
        data/balancing/vfx.json + data/schemas/vfx.schema.json, promoting it
        to a real domain (D8 fallout) — `deco` is still asset-only and keeps
        the assertion's meaning intact."""
        panel = self.make()
        self.assertNotIn("deco", panel.domains())
        domains = []
        panel.domain_selected.connect(domains.append)
        panel.select_node("deco", ("Props",))    # node exists and is selectable
        self.assertEqual(domains, [])            # but drives no balancing form

    def test_unknown_node_raises(self):
        with self.assertRaises(KeyError):
            self.make().select_node("buildings", ("No Such Type",))

    def test_deco_is_nested_under_map_not_top_level(self):
        # Phase 6 follow-up: deco reads as part of map editing, so its root
        # is a child of "map" in the TREE only — category_key stays "deco"
        # (selection/DetailsPanel/palette are unaffected).
        panel = self.make()
        top_level_keys = [
            panel.topLevelItem(i).data(0, _PAYLOAD_ROLE)[0]
            for i in range(panel.topLevelItemCount())
        ]
        self.assertNotIn("deco", top_level_keys)
        deco_root = panel._find_item("deco", ())
        map_root = panel._find_item("map", ())
        self.assertIs(deco_root.parent(), map_root)
        # selection/import wiring is untouched: category_key is still "deco"
        panel.select_node("deco", ("Props",))
        self.assertEqual(panel.selectedItems()[0].data(0, _PAYLOAD_ROLE),
                         ("deco", ("Props",)))

    def test_markers_reflect_migrated_manifest(self):
        panel = self.make()
        defender = panel._find_item("buildings", ("Defender",))
        painter = panel._find_item("buildings", ("Painter",))
        root = panel._find_item("buildings", ())
        self.assertTrue(defender.text(0).startswith("● "))   # stone_thrower migrated
        self.assertFalse(painter.text(0).startswith("● "))   # nothing assigned
        self.assertTrue(root.text(0).startswith("● "))

    def test_markers_refresh_after_manifest_write(self):
        panel = self.make()
        manifest_path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(manifest_path)
        doc["entries"]["painter_t1_lvl1"] = {
            "sheet": "imported/painter_t1_lvl1.png",
            "frame_w": 64, "frame_h": 96, "offset_x": 0, "offset_y": 0,
            "rows": [{"animation": "idle", "frames": 1, "fps": 8,
                      "hidden": [], "loop_start": 0, "loop_end": 0,
                      "loop_count": 1}],
        }
        data_io.write_validated(
            doc, manifest_path,
            self.data_dir / "schemas" / "asset_manifest.schema.json")
        panel.refresh_markers()
        painter = panel._find_item("buildings", ("Painter",))
        self.assertTrue(painter.text(0).startswith("● "))

    def test_theme_leaf_is_second_child_and_emits_theme_selected(self):
        """UH-6: "Theme" is a leaf under "ui", right after "Screens" (which
        stays FIRST — the panels-doc invariant), never node_selected."""
        panel = self.make()
        ui_root = panel._find_item("ui", ())
        self.assertEqual(ui_root.child(0).text(0), "Screens")
        self.assertEqual(ui_root.child(1).text(0), "Theme")

        themes, nodes, domains_seen = [], [], []
        panel.theme_selected.connect(lambda: themes.append(True))
        panel.node_selected.connect(lambda c, p: nodes.append((c, p)))
        panel.domain_selected.connect(domains_seen.append)
        panel.select_theme()
        self.assertEqual(themes, [True])
        self.assertEqual(nodes, [])            # never node_selected
        self.assertIn("ui", domains_seen)      # same "ui" domain as Screens

    def test_tutorial_leaf_exists_under_ui_and_emits_tutorial_selected(self):
        """TU-4: "Tutorial" is a leaf under "ui" (order not hardcoded — a
        different phase's own leaf placement is not this test's business),
        never node_selected."""
        panel = self.make()
        ui_root = panel._find_item("ui", ())
        self.assertIsNotNone(panel._tutorial_item)
        self.assertIs(panel._tutorial_item.parent(), ui_root)

        tutorials, nodes, domains_seen = [], [], []
        panel.tutorial_selected.connect(lambda: tutorials.append(True))
        panel.node_selected.connect(lambda c, p: nodes.append((c, p)))
        panel.domain_selected.connect(domains_seen.append)
        panel.select_tutorial()
        self.assertEqual(tutorials, [True])
        self.assertEqual(nodes, [])            # never node_selected
        self.assertIn("ui", domains_seen)      # same "ui" domain as Screens/Theme

    def test_master_sheets_is_a_top_level_item_with_its_own_signal(self):
        """MasterSheetColumnsPLAN E5/D9: "Master Sheets" is a TOP-LEVEL item
        (last one), not a leaf under any category — so it emits its own signal
        and NEITHER node_selected NOR domain_selected: there is no
        "master_sheets" balancing domain to gate one on."""
        panel = self.make()
        last = panel.topLevelItem(panel.topLevelItemCount() - 1)
        self.assertEqual(last.text(0), "Master Sheets")
        self.assertIs(panel._master_sheets_item, last)
        self.assertIsNone(last.parent())
        self.assertNotIn("master_sheets", panel.domains())

        seen, nodes, domains_seen = [], [], []
        panel.master_sheets_selected.connect(lambda: seen.append(True))
        panel.node_selected.connect(lambda c, p: nodes.append((c, p)))
        panel.domain_selected.connect(domains_seen.append)
        panel.select_master_sheets()
        self.assertEqual(seen, [True])
        self.assertEqual(nodes, [])             # never node_selected
        self.assertEqual(domains_seen, [])      # and never domain_selected (D9)


class TestBalancingPanel(TempDataCase):
    def make_panel(self, domain):
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        panel.set_domain(domain)
        return panel

    def test_widgets_generated_from_schema(self):
        """ED-30: int -> spinbox, number -> double spinbox, bool -> checkbox,
        string -> line edit; widgets key by '/'-joined paths into the 9A
        nested tree."""
        panel = self.make_panel("core")
        self.assertIsInstance(panel._widgets["TheHole/base_hp"], QSpinBox)
        panel = self.make_panel("ui")
        self.assertIsInstance(
            panel._widgets["Timing/not_enough_love_duration"], QDoubleSpinBox
        )
        self.assertIsInstance(panel._widgets["FX/gore_enabled"], QCheckBox)
        panel = self.make_panel("buildings")
        self.assertIsInstance(
            panel._widgets["DefenceBuildings/BasicDefence/tiers/0/base_dmg"], QSpinBox
        )
        self.assertIsInstance(
            panel._widgets["BuildingsGlobal/random_names/0"], QLineEdit
        )

    def test_selection_switches_panel_content(self):
        """ED-3: the selected tree node drives the form's content."""
        selector = self.track(SelectorPanel(data_dir=self.data_dir))
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        selector.domain_selected.connect(panel.set_domain)
        selector.select_domain("buildings")
        self.assertIn("DefenceBuildings/BasicDefence/tiers/0/base_dmg", panel._widgets)
        selector.select_domain("enemies")
        self.assertIn("EnemyTypes/Standard/eras/0/stats/hp", panel._widgets)
        self.assertNotIn(
            "DefenceBuildings/BasicDefence/tiers/0/base_dmg", panel._widgets
        )

    def test_edit_writes_validated_canonical_file(self):
        """ED-31: a nested widget change stages in memory + shows a dirty
        dot; only Save Balancing Changes writes the correct leaf to
        canonical JSON on disk (the 9A Quick Test edit, now staged)."""
        panel = self.make_panel("buildings")
        key = "DefenceBuildings/BasicDefence/tiers/0/base_dmg"
        panel._widgets[key].setValue(30)
        before = read_domain(self.data_dir, "buildings")
        self.assertNotEqual(
            before["DefenceBuildings"]["BasicDefence"]["tiers"][0]["base_dmg"], 30
        )
        self.assertFalse(panel._dots[key].isHidden())
        self.assertTrue(panel._save_btn.isEnabled())
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(
            on_disk["DefenceBuildings"]["BasicDefence"]["tiers"][0]["base_dmg"], 30
        )
        path = self.data_dir / "balancing" / "buildings.json"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text, data_io.dumps_deterministic(on_disk))
        self.assertTrue(panel._dots[key].isHidden())
        self.assertFalse(panel._save_btn.isEnabled())

    def test_every_domain_builds_a_form(self):
        """The cheapest possible guard on the recursive walk: a schema node the
        panel has no widget for RAISES, and takes the whole domain's form with it.
        Nothing else in the suite builds every derived domain, so a `oneOf` or a
        type-less node put back into any schema would otherwise ship."""
        for domain in domains.domains(self.data_dir):
            with self.subTest(domain=domain):
                panel = self.make_panel(domain)
                self.assertTrue(panel._widgets)

    def test_enemy_rework_fields_surface_and_are_editable(self):
        """ER-5: footprint / sprite_scale / the whole death_spawn block (including
        the per-era spawns rows) reach the designer as real widgets.

        BR-1 re-anchored the two sizing fields into the Boss's per-era
        ``stats`` rows (plus its shake). The per-era-footprint change then did
        the same for EVERY era-shaped type: ``footprint``/``sprite_scale`` live
        in each type's own ``eras[]`` rows and **have no flat home left**
        (`game/enemies/CLAUDE.md`). This test still named the deleted flat keys
        `EnemyTypes/Standard/footprint`/`sprite_scale` and failed with a bare
        `KeyError` — so the two subtests said "the panel lost these widgets"
        when what had actually happened is that they moved."""
        panel = self.make_panel("enemies")
        for key, kind in (
            ("EnemyTypes/Standard/eras/0/footprint", QSpinBox),
            ("EnemyTypes/Standard/eras/0/sprite_scale", QDoubleSpinBox),
            ("EnemyTypes/Standard/eras/4/footprint", QSpinBox),
            ("EnemyTypes/Boss/stats/0/footprint", QSpinBox),
            ("EnemyTypes/Boss/stats/0/sprite_scale", QDoubleSpinBox),
            ("EnemyTypes/Boss/stats/4/shake/strength", QDoubleSpinBox),
            ("EnemyTypes/Boss/second_phase/enabled", QCheckBox),
            # BR-5: per-era staging rows, not a flat key on the block.
            ("EnemyTypes/Boss/second_phase/staging/0/at_hp_fraction",
             QDoubleSpinBox),
            ("EnemyTypes/Boss/second_phase/staging/4/spawn_delay",
             QDoubleSpinBox),
            ("EnemyTypes/Boss/second_phase/staging/0/delayed_spawns",
             QCheckBox),
            ("EnemyTypes/Boss/second_phase/spawns/0/regular", QSpinBox),
        ):
            with self.subTest(key=key):
                self.assertIsInstance(panel._widgets[key], kind)
                self.assertTrue(panel._widgets[key].isEnabled())

    def test_add_row_appends_a_copy_of_the_last_row(self):
        """ER-5: a 1-row type can be given a per-era spawns table from the panel.
        The new row is a COPY, so it is schema-valid by construction and Save
        cannot be made to write an invalid document."""
        panel = self.make_panel("enemies")
        key = "EnemyTypes/Standard/death_spawn/spawns"
        rows = panel._value_at(key)
        self.assertEqual(len(rows), 1)
        original = copy.deepcopy(rows[0])

        panel._add_array_row(key)

        self.assertEqual(panel._value_at(key), [original, original])
        self.assertTrue(panel._save_btn.isEnabled())          # staged, not written
        self.assertIn(key, panel._dirty)
        self.assertEqual(len(read_domain(self.data_dir, "enemies")
                              ["EnemyTypes"]["Standard"]["death_spawn"]["spawns"]), 1)
        # The new row got real widgets, and editing one writes through on Save.
        panel._widgets[f"{key}/1/regular"].setValue(7)
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "enemies")
        spawns = on_disk["EnemyTypes"]["Standard"]["death_spawn"]["spawns"]
        self.assertEqual(len(spawns), 2)
        self.assertEqual(spawns[1]["regular"], 7)

    def test_remove_row_pops_the_last_row(self):
        panel = self.make_panel("enemies")
        key = "EnemyTypes/Boss/second_phase/spawns"
        self.assertEqual(len(panel._value_at(key)), 5)   # the boss's per-era table
        panel._remove_array_row(key)
        self.assertEqual(len(panel._value_at(key)), 4)
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "enemies")
        self.assertEqual(
            len(on_disk["EnemyTypes"]["Boss"]["second_phase"]["spawns"]), 4)

    def test_editing_a_field_of_a_new_row_does_not_raise(self):
        """The new row's path does not exist in the BASELINE (which still has the
        old length), so the dirty comparison must not walk off the end of it.

        `_commit` is called DIRECTLY here on purpose: driven through the widget's
        signal, Qt swallows the exception and prints it, the value still lands, and
        the test passes while the editor is one unhandled exception from dying — a
        live run is what exposed this.
        """
        panel = self.make_panel("enemies")
        key = "EnemyTypes/Standard/death_spawn/spawns"
        panel._add_array_row(key)
        panel._commit(f"{key}/1/regular", 9)          # must not raise
        self.assertEqual(panel._value_at(f"{key}/1/regular"), 9)
        self.assertIn(f"{key}/1/regular", panel._dirty)

    def test_adding_a_row_then_removing_it_is_clean_again(self):
        """The dirty flag is a whole-subtree comparison against the baseline, so
        an add undone by a remove leaves nothing staged."""
        panel = self.make_panel("enemies")
        key = "EnemyTypes/Standard/death_spawn/spawns"
        panel._add_array_row(key)
        self.assertTrue(panel._save_btn.isEnabled())
        panel._remove_array_row(key)
        self.assertNotIn(key, panel._dirty)
        self.assertFalse(panel._save_btn.isEnabled())

    def test_a_rebuild_keeps_other_pending_dots(self):
        """Adding a row rebuilds the form. A staged edit elsewhere must survive
        that with its dot intact — fresh widgets start with the dot hidden."""
        panel = self.make_panel("enemies")
        edited = "EnemyTypes/Standard/eras/0/stats/hp"
        panel._widgets[edited].setValue(panel._widgets[edited].value() + 1)
        panel._add_array_row("EnemyTypes/Standard/death_spawn/spawns")
        self.assertIn(edited, panel._dirty)
        self.assertFalse(panel._dots[edited].isHidden())

    def _resizable_arrays(self, panel):
        """The array paths that actually grew a + Row button, read off the live
        widget tree via the buttons' objectNames."""
        return {
            b.objectName().removeprefix(BalancingPanel.ROW_ADD)
            for b in panel.findChildren(QPushButton)
            if b.objectName().startswith(BalancingPanel.ROW_ADD)
        }

    def test_only_schema_resizable_arrays_offer_row_buttons(self):
        """minItems == maxItems (the boss's stats/round_counts, every building
        tier list) => NO buttons. That gate is what keeps every form that
        shipped before ER-5 byte-identical; `death_spawn.spawns` and — since
        ES-2 — the variable-length `eras` arrays (minItems 1, no maxItems) are
        what a designer may actually resize, with no editor code at all."""
        panel = self.make_panel("enemies")
        schema = data_io.load_json(
            self.data_dir / "schemas" / "enemies.schema.json")
        boss = schema["properties"]["EnemyTypes"]["properties"]["Boss"]
        counts = boss["properties"]["round_counts"]
        self.assertEqual(counts["minItems"], counts["maxItems"])  # the premise

        resizable = self._resizable_arrays(panel)
        self.assertNotIn("EnemyTypes/Boss/round_counts", resizable)
        self.assertIn("EnemyScaling/eras", resizable)
        self.assertIn("EnemyTypes/Standard/eras", resizable)
        self.assertIn("EnemyTypes/Standard/death_spawn/spawns", resizable)
        self.assertIn("EnemyTypes/Boss/second_phase/spawns", resizable)

    def test_buildings_form_has_no_row_buttons_at_all(self):
        """The regression guard for every other domain: a fixed-length tier list
        must not sprout an add/remove affordance."""
        self.assertEqual(self._resizable_arrays(self.make_panel("buildings")), set())

    def test_era_rows_carry_a_greyed_previous_era_reference(self):
        """ES-5/D9: an era >= 1 stat field shows a disabled, read-only label
        with what that field resolved to on the LAST round of the previous era;
        era 0 has nothing to reference and carries no label."""
        panel = self.make_panel("enemies")
        labels = {
            lab.objectName().removeprefix(BalancingPanel.PREV_REF): lab
            for lab in panel.findChildren(QLabel)
            if lab.objectName().startswith(BalancingPanel.PREV_REF)
        }
        self.assertFalse([k for k in labels if "/eras/0/" in k])  # era 0: none

        doc = read_domain(self.data_dir, "enemies")
        rows = doc["EnemyTypes"]["Standard"]["eras"]
        expected = era_math.prev_era_reference(
            rows, 1, doc["EnemyScaling"]["rounds_per_era"]
        )["stats"]["hp"]
        label = labels["EnemyTypes/Standard/eras/1/stats/hp"]
        self.assertFalse(label.isEnabled())
        self.assertIn(str(expected), label.text())

    def test_out_of_range_input_unrepresentable(self):
        """ED-30: the widget clamps to the schema's bounds — invalid values
        cannot even be entered, let alone written."""
        panel = self.make_panel("buildings")
        widget = panel._widgets["DefenceBuildings/BasicDefence/tiers/0/base_dmg"]
        widget.setValue(999999)
        self.assertEqual(widget.value(), 100000)  # schema maximum (x10 scale cap)
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(
            on_disk["DefenceBuildings"]["BasicDefence"]["tiers"][0]["base_dmg"], 100000
        )

    def test_checkbox_writes_typed_value(self):
        panel = self.make_panel("ui")
        panel._widgets["FX/gore_enabled"].setChecked(False)
        panel.save_changes("Test session")
        self.assertIs(read_domain(self.data_dir, "ui")["FX"]["gore_enabled"], False)

    def test_string_edit_writes_and_empty_is_restored(self):
        """string -> QLineEdit; an empty edit violating minLength is restored
        instead of written (invalid input unrepresentable, ED-30)."""
        panel = self.make_panel("buildings")
        widget = panel._widgets["BuildingsGlobal/random_names/0"]
        widget.setText("Zed")
        widget.editingFinished.emit()
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(on_disk["BuildingsGlobal"]["random_names"][0], "Zed")
        widget.setText("")
        widget.editingFinished.emit()
        self.assertEqual(widget.text(), "Zed")  # restored, nothing written
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(on_disk["BuildingsGlobal"]["random_names"][0], "Zed")

    def test_wheel_over_spinbox_does_not_change_value(self):
        """Mouse-wheel scrolling must never nudge a balancing value."""
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent

        panel = self.make_panel("buildings")
        widget = panel._widgets["DefenceBuildings/BasicDefence/tiers/0/base_dmg"]
        before = widget.value()
        event = QWheelEvent(
            QPointF(0, 0), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False,
        )
        widget.wheelEvent(event)
        self.assertEqual(widget.value(), before)
        self.assertFalse(panel._dirty)

    def test_on_save_is_a_noop_with_no_pending_changes(self):
        """_on_save must not pop the (blocking, modal) name dialog at all
        when there is nothing staged."""
        panel = self.make_panel("core")
        before = read_domain(self.data_dir, "core")
        self.assertFalse(panel._dirty)
        panel._on_save()  # no dirty fields -> returns before building a dialog
        after = read_domain(self.data_dir, "core")
        self.assertEqual(before, after)

    def test_save_meta_dialog_requires_a_name(self):
        """The OK button of the save-session dialog stays disabled until a
        non-blank session name is entered."""
        from editor.panels.balancing import _SaveMetaDialog

        dialog = self.track(_SaveMetaDialog())
        ok_button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        self.assertFalse(ok_button.isEnabled())
        dialog._name.setText("  ")
        self.assertFalse(ok_button.isEnabled())
        dialog._name.setText("My Session")
        self.assertTrue(ok_button.isEnabled())
        self.assertEqual(dialog.session_name(), "My Session")

    def test_enum_widget_from_synthetic_domain(self):
        """No live domain carries an enum after 9A; a synthetic schema/data
        pair keeps _make_widget's enum -> QComboBox branch covered."""
        schema = {
            "$id": "synthetic.schema.json",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "properties": {
                "mode": {
                    "description": "Synthetic enum for widget coverage.",
                    "enum": [1, 2, 4],
                    "type": "integer",
                },
            },
            "required": ["mode"],
            "title": "synthetic",
            "type": "object",
        }
        schema_path = self.data_dir / "schemas" / "synthetic.schema.json"
        schema_path.write_text(
            data_io.dumps_deterministic(schema), encoding="utf-8"
        )
        data_io.write_validated(
            {"mode": 1},
            self.data_dir / "balancing" / "synthetic.json",
            schema_path,
        )
        panel = self.make_panel("synthetic")
        combo = panel._widgets["mode"]
        self.assertIsInstance(combo, QComboBox)
        combo.setCurrentIndex(combo.findData(4))
        panel.save_changes("Test session")
        self.assertEqual(read_domain(self.data_dir, "synthetic")["mode"], 4)

    def test_domain_editable(self):
        panel = self.make_panel("buildings")
        for key, widget in panel._widgets.items():
            self.assertTrue(widget.isEnabled(), msg=key)

    def test_x_toggle_weight_row_pairs_a_checkbox_at_the_sibling_path(self):
        """A `map` weight leaf carrying `x-toggle` gets a QCheckBox registered
        at the resolved sibling path, not at the weight's own path."""
        panel = self.make_panel("map")
        sibling_key = "Pathfinding/content_weight_overwrites/defence_building"
        self.assertIsInstance(panel._widgets[sibling_key], QCheckBox)
        # The 4 non-building content keys carry no x-toggle and stay plain.
        self.assertNotIn(
            "Pathfinding/content_weight_overwrites/buildable_tile", panel._widgets
        )

    def test_toggling_the_paired_checkbox_marks_dirty_and_saves(self):
        """The checkbox commits straight to the sibling's own path through the
        same _commit every widget uses — dirty tracking and Save need no
        special case."""
        panel = self.make_panel("map")
        key = "TileConditions/path_weight_overwritable/forest"
        checkbox = panel._widgets[key]
        before = read_domain(self.data_dir, "map")
        original = before["TileConditions"]["path_weight_overwritable"]["forest"]
        checkbox.setChecked(not original)
        self.assertIn(key, panel._dirty)
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "map")
        self.assertEqual(
            on_disk["TileConditions"]["path_weight_overwritable"]["forest"],
            not original,
        )

    def test_x_paired_object_produces_no_own_collapsible_section(self):
        """`content_weight_overwrites`/`path_weight_overwritable` render ONLY
        inline as paired checkboxes — never as their own section, per the
        `x-paired` annotation."""
        panel = self.make_panel("map")
        titles = {
            s._button.text() for s in panel.findChildren(CollapsibleSection)
        }
        self.assertNotIn("content_weight_overwrites", titles)
        self.assertNotIn("path_weight_overwritable", titles)
        # The plain (unpaired) weight sections still render as usual.
        self.assertIn("content_weights", titles)
        self.assertIn("path_weights", titles)


class TestScalarArrayRowButtons(TempDataCase):
    """feature-enemy-intro-dialogue: ER-5's + / - Row gate generalized to
    arrays of SCALARS. ``EnemyIntro.entries[i].hidden_frames`` (minItems 0, no
    maxItems) is the first such array, and every seeded entry ships it EMPTY —
    the case the object-array version of this gate never had to handle."""

    def make_panel(self, domain):
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        panel.set_domain(domain)
        return panel

    def _row_buttons(self, panel, prefix, key):
        return [
            b for b in panel.findChildren(QPushButton)
            if b.objectName() == f"{prefix}{key}"
        ]

    def test_empty_scalar_array_offers_add_but_not_remove(self):
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        self.assertEqual(panel._value_at(key), [])
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_ADD, key)), 1)
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_REMOVE, key)), 0)

    def test_add_on_empty_array_synthesizes_a_schema_valid_default(self):
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        panel._add_array_row(key)
        self.assertEqual(panel._value_at(key), [0])   # item schema minimum: 0
        self.assertTrue(panel._save_btn.isEnabled())
        self.assertIn(key, panel._dirty)

    def test_add_then_save_round_trips_through_schema_validation(self):
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        panel._add_array_row(key)
        panel._widgets[f"{key}/0"].setValue(3)
        panel.save_changes("Test session")
        on_disk = read_domain(self.data_dir, "core")
        self.assertEqual(
            on_disk["EnemyIntro"]["entries"][0]["hidden_frames"], [3])

    def test_after_one_add_both_buttons_render(self):
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        panel._add_array_row(key)
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_ADD, key)), 1)
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_REMOVE, key)), 1)

    def test_add_then_remove_on_an_empty_array_is_clean_again(self):
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        panel._add_array_row(key)
        panel._remove_array_row(key)
        self.assertEqual(panel._value_at(key), [])
        self.assertNotIn(key, panel._dirty)
        self.assertFalse(panel._save_btn.isEnabled())

    def test_add_copies_the_last_row_once_non_empty(self):
        """Once an array of scalars is non-empty, Add still COPIES the last
        row (the ER-5 object-array rule) rather than resynthesizing a
        default — only a genuinely EMPTY scalar array needs the schema-derived
        default path at all."""
        panel = self.make_panel("core")
        key = "EnemyIntro/entries/0/hidden_frames"
        panel._add_array_row(key)
        panel._widgets[f"{key}/0"].setValue(5)
        panel._add_array_row(key)
        self.assertEqual(panel._value_at(key), [5, 5])

    def test_fixed_length_scalar_array_still_offers_no_buttons(self):
        """Camera.zoom_levels (minItems == maxItems == 3) is the pre-existing
        fixed-length scalar array this change must leave untouched."""
        panel = self.make_panel("core")
        key = "Camera/zoom_levels"
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_ADD, key)), 0)
        self.assertEqual(len(self._row_buttons(panel, BalancingPanel.ROW_REMOVE, key)), 0)


class TestBalancingHistory(TempDataCase):
    """Pure I/O (editor.balancing_history) + panel wiring (Save/Load/Delete)."""

    def test_save_session_appends_newest_first(self):
        first = balancing_history.save_session(
            "core", "First", "", {"a": 1}, self.data_dir
        )
        second = balancing_history.save_session(
            "core", "Second", "desc", {"a": 2}, self.data_dir
        )
        sessions = balancing_history.load_sessions("core", self.data_dir)
        self.assertEqual([s["id"] for s in sessions], [second["id"], first["id"]])
        path = self.data_dir / "balancing_history" / "core.json"
        self.assertTrue(path.exists())

    def test_load_sessions_empty_when_no_file(self):
        self.assertEqual(balancing_history.load_sessions("core", self.data_dir), [])

    def test_delete_session_removes_only_that_entry(self):
        first = balancing_history.save_session(
            "core", "First", "", {"a": 1}, self.data_dir
        )
        second = balancing_history.save_session(
            "core", "Second", "", {"a": 2}, self.data_dir
        )
        balancing_history.delete_session("core", first["id"], self.data_dir)
        sessions = balancing_history.load_sessions("core", self.data_dir)
        self.assertEqual([s["id"] for s in sessions], [second["id"]])

    def test_panel_save_changes_records_history_entry(self):
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        panel.set_domain("core")
        key = "TheHole/base_hp"
        widget = panel._widgets[key]
        widget.setValue(widget.value() + 1)
        panel.save_changes("Bumped base HP", "for testing")
        sessions = balancing_history.load_sessions("core", self.data_dir)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["name"], "Bumped base HP")
        self.assertEqual(
            sessions[0]["snapshot"]["TheHole"]["base_hp"], widget.value()
        )

    def test_apply_snapshot_stages_without_writing(self):
        panel = self.track(BalancingPanel(data_dir=self.data_dir))
        panel.set_domain("core")
        key = "TheHole/base_hp"
        widget = panel._widgets[key]
        original = widget.value()
        entry = balancing_history.save_session(
            "core", "Baseline", "", copy.deepcopy(panel._doc), self.data_dir
        )
        widget.setValue(original + 5)
        panel.save_changes("Bumped")
        on_disk_after_bump = read_domain(self.data_dir, "core")["TheHole"]["base_hp"]
        self.assertEqual(on_disk_after_bump, original + 5)

        panel._apply_snapshot(entry["snapshot"])
        self.assertEqual(widget.value(), original)
        self.assertFalse(panel._dots[key].isHidden())
        # not written yet — disk still shows the bumped value
        self.assertEqual(
            read_domain(self.data_dir, "core")["TheHole"]["base_hp"], original + 5
        )
        panel.save_changes("Reverted")
        self.assertEqual(
            read_domain(self.data_dir, "core")["TheHole"]["base_hp"], original
        )

    def test_save_session_survives_a_concurrent_writer(self):
        """Regression: save_session used to be a bare read-modify-write, so a
        second writer racing between its load() and write() would clobber the
        first writer's just-saved entry (reported as "history gets cleared").
        _history_lock() serializes the critical section; simulate the other
        writer holding the lock during ours and confirm nothing is lost."""
        first = balancing_history.save_session(
            "core", "First", "", {"a": 1}, self.data_dir
        )
        path = self.data_dir / "balancing_history" / "core.json"
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)

        import threading

        release_after = threading.Timer(0.2, lock_path.unlink)
        release_after.start()
        second = balancing_history.save_session(
            "core", "Second", "", {"a": 2}, self.data_dir
        )
        release_after.join()

        sessions = balancing_history.load_sessions("core", self.data_dir)
        self.assertEqual([s["id"] for s in sessions], [second["id"], first["id"]])

    def test_stale_lock_is_reclaimed_not_deadlocked(self):
        path = self.data_dir / "balancing_history" / "core.json"
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        stale_time = time.time() - (balancing_history.STALE_LOCK_SECONDS + 5)
        os.utime(lock_path, (stale_time, stale_time))

        entry = balancing_history.save_session(
            "core", "After stale lock", "", {"a": 1}, self.data_dir
        )
        sessions = balancing_history.load_sessions("core", self.data_dir)
        self.assertEqual([s["id"] for s in sessions], [entry["id"]])
        self.assertFalse(lock_path.exists())


class TestMainWindowWiring(TempDataCase):
    """End-to-end: shell wires selector -> balancing, initial selection set."""

    def make_window(self):
        from editor.main import MainWindow

        window = self.track(
            MainWindow(data_dir=self.data_dir, auto_refresh_layouts=False))
        window._timer.stop()  # no frame drive needed here
        return window

    def test_add_requested_opens_the_form_dialog_for_that_spec(self):
        """AD-6: selector "Add New X…" → MainWindow opens the AgentFormDialog
        for that spec. The real dialog is STUBBED — exec()ing it would block."""
        from editor import main as editor_main

        window = self.make_window()
        seen = []

        class StubDialog:
            def __init__(self, spec, data_dir=None, repo=None, parent=None):
                seen.append((spec["id"], data_dir, repo))

            def exec(self):
                return 0

        original = editor_main.AgentFormDialog
        editor_main.AgentFormDialog = StubDialog
        self.addCleanup(setattr, editor_main, "AgentFormDialog", original)

        window.selector.add_requested.emit("add-enemy")
        self.assertEqual(
            seen, [("add-enemy", self.data_dir, editor_main.REPO)])

        window.selector.add_requested.emit("no-such-form")   # no spec: no crash
        self.assertEqual(len(seen), 1)

    def test_select_and_edit_through_the_shell(self):
        window = self.make_window()
        self.assertEqual(window.balancing.domain, domains.domains(self.data_dir)[0])
        window.selector.select_domain("ui")
        self.assertEqual(window.balancing.domain, "ui")
        window.balancing._widgets["Timing/not_enough_love_duration"].setValue(2.5)
        window.balancing.save_changes("Test session")
        self.assertEqual(
            read_domain(self.data_dir, "ui")["Timing"]["not_enough_love_duration"], 2.5
        )

    def test_slot_selection_flows_through_all_panels(self):
        """Phase 5: tree node + tier dropdown + level bar resolve the slot
        that drives viewport preview and import context (user layout)."""
        window = self.make_window()
        window.selector.select_node("buildings", ("Painter",))
        self.assertEqual(window.balancing.domain, "buildings")   # 1:1 mapping
        self.assertEqual(window.details.slot_key, "painter_t1_lvl1")
        self.assertEqual(window.viewport.preview_slot, "painter_t1_lvl1")
        self.assertEqual(len(window.levelbar._buttons), 3)
        window.levelbar._buttons[1].click()                      # level 2
        self.assertEqual(window.details.slot_key, "painter_t1_lvl2")
        self.assertEqual(window.viewport.preview_slot, "painter_t1_lvl2")
        window.details._subcat_combo.setCurrentIndex(1)          # tier 2
        self.assertEqual(window.details.slot_key, "painter_t2_lvl1")
        window.selector.select_domain("ui")                      # back to a root
        self.assertIsNone(window.viewport.preview_slot)
        self.assertEqual(window.balancing.domain, "ui")

    def test_add_variant_button_only_on_variant_subcategories(self):
        window = self.make_window()
        # a building tier's levels are gameplay steps, not variants
        window.selector.select_node("buildings", ("Painter",))
        self.assertIsNone(window._variant_target())
        self.assertTrue(window.levelbar._add_btn.isHidden())
        # an enemy era exposes the "+ Variant" button (even single-slot eras)
        window.selector.select_node("enemies", ("Walker",))
        window.details.select_subcategory(1)   # Era 2 (one slot)
        self.assertEqual(window._variant_target(), "Era 2")
        self.assertFalse(window.levelbar._add_btn.isHidden())
        self.assertFalse(window.levelbar.isHidden())
        # deco prop types take variants AND new types
        window.selector.select_node("deco", ("Props",))
        window.details.select_subcategory(0)   # Rock
        self.assertEqual(window._variant_target(), "Rock")
        self.assertFalse(window.levelbar._add_type_btn.isHidden())
        # backgrounds take another type; the checkerboard zone kinds do NOT
        window.selector.select_node("map", ("Tiles",))
        window.details.select_subcategory_label("Background")
        self.assertEqual(window._variant_target(), "Background")
        window.details.select_subcategory_label("Buildable")
        self.assertIsNone(window._variant_target())
        self.assertTrue(window.levelbar._add_btn.isHidden())
        self.assertTrue(window.levelbar._add_type_btn.isHidden())

    def test_add_deco_variant_and_type_from_the_tree(self):
        from engine.assets import load_registry

        # Artists add rock variants over time; "the next variant is _v2" is
        # only true if the test strips the accumulated ones first (see
        # drop_slot_variants' docstring — this test is its poster child).
        self.drop_slot_variants("deco_rock")
        window = self.make_window()
        window.selector.select_node("deco", ("Props",))
        window.details.select_subcategory(0)   # Rock: [deco_rock]

        window.levelbar._add_btn.click()       # + Variant
        reg = load_registry(self.data_dir)
        self.assertEqual(reg.group_slots("deco", ("Props", "Rock")),
                         ("deco_rock", "deco_rock_v2"))
        self.assertEqual(window.details.slot_key, "deco_rock_v2")

        before = [c.label for c in reg.group("deco", ("Props",)).children]
        window.levelbar._add_type_btn.click()  # + Type
        reg = load_registry(self.data_dir)
        labels = [c.label for c in reg.group("deco", ("Props",)).children]
        self.assertEqual(labels[:-1], before)
        # a brand-new type, holding its own first (grey-X) variant, selected
        new_slot, = reg.group_slots("deco", ("Props", labels[-1]))
        self.assertTrue(new_slot.startswith("deco_prop_"))
        self.assertEqual(window.details.slot_key, new_slot)

    def test_add_type_button_shown_on_ui_buttons_node(self):
        """+ Type on ui -> Buttons is a SECOND "+ Type" target (the button
        FAMILY affordance) alongside deco; every other ui node stays without
        it, same as any non-deco/non-Buttons category."""
        window = self.make_window()
        window.selector.select_node("ui", ("Buttons",))
        self.assertFalse(window.levelbar._add_type_btn.isHidden())

        window.selector.select_node("ui", ("Backgrounds",))
        self.assertTrue(window.levelbar._add_type_btn.isHidden())

        window.selector.select_node("enemies", ("Walker",))
        self.assertTrue(window.levelbar._add_type_btn.isHidden())

    def test_add_button_type_creates_family_and_refreshes_skin_combos(self):
        """The no-restart pin (§1a): a fresh button family must show up in
        every skin combo without an editor restart — fails red if the
        `screen_details.reload_registry()` wiring line is dropped."""
        window = self.make_window()
        window.selector.select_node("ui", ("Buttons",))

        window._on_add_button_type(name="Tab")   # injected: no modal

        self.assertEqual(
            window.details._subcat_combo.currentText().removeprefix("● "),
            "Tab")
        skin_values = [window.screen_details.skin_combo.itemData(i)
                      for i in range(window.screen_details.skin_combo.count())]
        button_skin_values = [
            window.screen_details.button_skin_combo.itemData(i)
            for i in range(window.screen_details.button_skin_combo.count())]
        self.assertIn("ui_button_tab", skin_values)
        self.assertIn("ui_button_tab", button_skin_values)

    def test_add_button_type_rejection_reports_not_crashes(self):
        window = self.make_window()
        window.selector.select_node("ui", ("Buttons",))
        window._on_add_button_type(name="Tab")

        slots_path = self.data_dir / "slots.json"
        before = slots_path.read_bytes()

        window._on_add_button_type(name="Tab")   # duplicate: no crash
        self.assertIn(
            "Could not add button type",
            window.statusBar().currentMessage())
        self.assertEqual(slots_path.read_bytes(), before)

    def test_add_background_variant_from_the_tree(self):
        from engine.assets import load_registry

        window = self.make_window()
        window.selector.select_node("map", ("Tiles",))
        window.details.select_subcategory_label("Background")
        before = load_registry(self.data_dir).group_slots(
            "map", ("Tiles", "Background"))

        window.levelbar._add_btn.click()       # + Variant == another BG type

        after = load_registry(self.data_dir).group_slots(
            "map", ("Tiles", "Background"))
        self.assertEqual(len(after), len(before) + 1)
        self.assertTrue(after[-1].startswith("tile_background_"))
        # lands on the new slot, ready to import art onto (grey-X until then)
        self.assertEqual(window.details.slot_key, after[-1])

    def test_add_variant_appends_slot_selects_it_and_persists(self):
        from engine.assets import load_registry

        window = self.make_window()
        window.selector.select_node("enemies", ("Walker",))
        window.details.select_subcategory(1)    # Era 2: [enemy_stage_2]
        self.assertEqual(len(window.levelbar._buttons), 1)

        window.levelbar._add_btn.click()        # + Variant

        # slots.json on disk grew, validated
        reg = load_registry(self.data_dir)
        self.assertEqual(
            reg.group_slots("enemies", ("Walker", "Era 2")),
            ("enemy_stage_2", "enemy_stage_2_v2"))
        # the level bar now offers both and lands on the NEW variant, ready to
        # import art onto it (details + viewport follow)
        self.assertEqual(len(window.levelbar._buttons), 2)
        self.assertEqual(window.levelbar.level(), 1)
        self.assertEqual(window.details.slot_key, "enemy_stage_2_v2")
        self.assertEqual(window.viewport.preview_slot, "enemy_stage_2_v2")
        # still on the same era (didn't jump back to Era 1)
        self.assertEqual(window._variant_target(), "Era 2")

    def test_import_save_clear_update_preview_without_restart(self):
        """ED-42 end-to-end: import -> draft preview -> save -> disk-backed
        preview + ● marker; clear -> grey X returns.

        Starts from a genuinely empty Painter slot — pinned, not assumed; the
        whole round trip is only observable if there is no art there to begin
        with."""
        from PIL import Image

        self.unassign_family("painter")   # the ● must start OFF to be earned

        png = Path(self.data_dir) / "incoming.png"
        Image.new("RGBA", (2 * 64, 96), (10, 200, 10, 255)).save(png)

        window = self.make_window()
        window.selector.select_node("buildings", ("Painter",))
        self.assertEqual(window.viewport.preview_animations(), ())

        window.details.import_sheet(png)
        # unsaved draft already previews through the engine pipeline
        self.assertEqual(window.viewport.preview_animations(), ("idle",))
        window.details.save()
        # saved state now comes from disk, not the draft (ED-42, no restart)
        self.assertIsNone(window.viewport._draft)
        self.assertEqual(window.viewport.preview_animations(), ("idle",))
        painter_item = window.selector._find_item("buildings", ("Painter",))
        self.assertTrue(painter_item.text(0).startswith("● "))

        window.details.clear_entry(confirm=False)
        self.assertEqual(window.viewport.preview_animations(), ())
        painter_item = window.selector._find_item("buildings", ("Painter",))
        self.assertFalse(painter_item.text(0).startswith("● "))


class TestGameThemePanel(TempDataCase):
    """UH-6 (D5): the Theme leaf's panel — GameThemePanel. Named to avoid
    colliding with TestThemeSwitch below (editor/theme.py, the Qt chrome
    light/dark switch — a completely different "theme"). Staged edits (the
    balancing.py pattern): every change updates an in-memory doc + a dirty
    dot; ONE Save button is the sole write_validated call site."""

    def make(self):
        from editor.panels.game_theme import GameThemePanel
        return self.track(GameThemePanel(data_dir=self.data_dir))

    def test_font_combo_lists_the_temp_trees_fonts_json_keys(self):
        from editor import theme_ops
        panel = self.make()
        self.assertEqual(
            set(panel._font_widgets), set(theme_ops.font_keys(self.data_dir)))

    def test_edit_gold_save_round_trips_through_write_validated(self):
        from editor import theme_ops
        panel = self.make()
        # isHidden() (not isVisible(), the balancing.py dot test's own
        # convention) — these widgets are never shown in a top-level
        # window, so isVisible() is always False regardless of setVisible.
        self.assertTrue(panel._palette_dots["gold"].isHidden())
        self.assertFalse(panel.save_button.isEnabled())

        with mock.patch(
                "editor.panels.game_theme.QColorDialog.getColor",
                return_value=QColor(1, 2, 3)):
            panel._on_palette_clicked("gold")

        self.assertFalse(panel._palette_dots["gold"].isHidden())
        self.assertTrue(panel.save_button.isEnabled())
        self.assertEqual(panel._palette_doc["gold"], [1, 2, 3])
        # staged only — nothing written yet
        self.assertEqual(theme_ops.load_palette(self.data_dir)["gold"], [255, 200, 50])

        saved = []
        panel.saved.connect(lambda: saved.append(True))
        panel._on_save()

        self.assertEqual(saved, [True])
        self.assertTrue(panel._palette_dots["gold"].isHidden())
        self.assertFalse(panel.save_button.isEnabled())
        on_disk = theme_ops.load_palette(self.data_dir)
        self.assertEqual(on_disk["gold"], [1, 2, 3])
        path = theme_ops.palette_path(self.data_dir)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         data_io.dumps_deterministic(on_disk))

    def test_font_size_edit_stages_and_saves(self):
        from editor import theme_ops
        panel = self.make()
        size_spin, _bold_check = panel._font_widgets["lg"]
        size_spin.setValue(size_spin.value() + 1)
        self.assertFalse(panel._font_dots["lg"].isHidden())
        self.assertTrue(panel.save_button.isEnabled())
        panel._on_save()
        self.assertEqual(
            theme_ops.load_fonts(self.data_dir)["lg"]["size"], size_spin.value())
        self.assertTrue(panel._font_dots["lg"].isHidden())

    def test_preview_never_holds_the_font_file_open(self):
        """UH-Font-A: the Font Family preview must register the font from
        BYTES (``addApplicationFontFromData``), never from its path.

        ``addApplicationFont(<path>)`` looks harmless — it does not lock on
        its own — but the first time Qt's font engine loads a GLYPH from
        that family it opens the file and holds it while the family stays
        registered. On Windows that is a hard lock, so merely building the
        preview left the editor sitting on the designer's font file and
        broke every TempDataCase teardown (``shutil.rmtree`` cannot unlink
        it). The pygame side has the identical trap; see
        ``test_theme_data.TestCustomFontFileIsNeverHeldOpen``.

        The fixture is PINNED, not inherited: this imports its own font and
        makes it active in the temp tree rather than trusting whatever
        ``data/ui/active_font.json`` happens to point at today — the whole
        bug is invisible while that pointer reads ``"default"``."""
        import pygame
        from PySide6.QtGui import QFont, QFontMetrics

        from editor import font_import, theme_ops

        source = Path(pygame.__file__).parent / pygame.font.get_default_font()
        font_id = font_import.import_font_file(
            self.data_dir, source, display_name="Pin Fixture")
        theme_ops.write_active_font({"font_id": font_id}, self.data_dir)
        imported = theme_ops.resolve_active_font_path(self.data_dir)
        self.assertIsNotNone(imported)

        panel = self.make()
        family = panel._family_for_font_id(font_id)
        self.assertIsNotNone(family)
        # Force a real glyph load — registering alone never locked anything.
        QFontMetrics(QFont(family)).horizontalAdvance("Ag")

        os.unlink(imported)   # Windows: raises here if a handle is open.
        self.assertFalse(Path(imported).exists())


class TestCutscenesPanel(TempDataCase):
    """TU-3: the single "Cutscenes" leaf's panel over
    ``data/video/cutscenes.json`` (TU-1's registry). Unlike
    ``GameThemePanel``, every action is an IMMEDIATE write — no staged/
    dirty-dot model."""

    def make(self):
        from editor.panels.cutscenes import CutscenesPanel
        return self.track(CutscenesPanel(data_dir=self.data_dir))

    def _write_src(self, name, content=b"not a real video"):
        path = self.data_dir / name
        path.write_bytes(content)
        return path

    def test_rows_built_in_trigger_order_with_seeded_intro(self):
        panel = self.make()
        self.assertEqual(list(panel._rows), ["intro", "first_end_turn"])
        self.assertEqual(
            panel._rows["intro"]["video_label"].text(), "cutscene.mp4")

    def test_import_video_copies_writes_registry_and_updates_length(self):
        from editor import cutscene_import
        panel = self.make()
        src = self._write_src("incoming.mp4")

        with mock.patch(
                "editor.panels.cutscenes.QFileDialog.getOpenFileName",
                return_value=(str(src), "")), \
             mock.patch(
                "editor.cutscene_import.probe_length_seconds",
                return_value=12.5):
            panel._on_import_video("first_end_turn")

        dest = self.data_dir / "video" / "first_end_turn.mp4"
        self.assertTrue(dest.exists())
        self.assertEqual(dest.read_bytes(), src.read_bytes())
        self.assertEqual(
            panel._rows["first_end_turn"]["video_label"].text(),
            "first_end_turn.mp4")
        self.assertEqual(
            panel._rows["first_end_turn"]["length_spin"].value(), 12.5)

        doc = cutscene_import.load_registry_doc(self.data_dir)
        self.assertEqual(doc["first_end_turn"]["video"], "first_end_turn.mp4")
        self.assertEqual(doc["first_end_turn"]["length"], 12.5)
        path = cutscene_import.registry_path(self.data_dir)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         data_io.dumps_deterministic(doc))

    def test_import_video_cv2_absent_leaves_manual_length_untouched(self):
        from editor import cutscene_import
        panel = self.make()
        src = self._write_src("incoming2.mp4")
        original_length = panel._rows["first_end_turn"]["length_spin"].value()

        with mock.patch(
                "editor.panels.cutscenes.QFileDialog.getOpenFileName",
                return_value=(str(src), "")), \
             mock.patch(
                "editor.cutscene_import.probe_length_seconds",
                return_value=None):
            panel._on_import_video("first_end_turn")

        self.assertEqual(
            panel._rows["first_end_turn"]["length_spin"].value(),
            original_length)
        doc = cutscene_import.load_registry_doc(self.data_dir)
        self.assertEqual(doc["first_end_turn"]["length"], original_length)
        self.assertEqual(doc["first_end_turn"]["video"], "first_end_turn.mp4")

    def test_import_audio_then_clear_round_trips_null(self):
        from editor import cutscene_import
        panel = self.make()
        src = self._write_src("incoming.ogg")

        with mock.patch(
                "editor.panels.cutscenes.QFileDialog.getOpenFileName",
                return_value=(str(src), "")):
            panel._on_import_audio("first_end_turn")

        dest = self.data_dir / "video" / "first_end_turn_audio.ogg"
        self.assertTrue(dest.exists())
        doc = cutscene_import.load_registry_doc(self.data_dir)
        self.assertEqual(doc["first_end_turn"]["audio"], "first_end_turn_audio.ogg")
        self.assertTrue(
            panel._rows["first_end_turn"]["clear_audio_btn"].isEnabled())

        panel._on_clear_audio("first_end_turn")

        self.assertFalse(dest.exists())
        doc = cutscene_import.load_registry_doc(self.data_dir)
        self.assertIsNone(doc["first_end_turn"]["audio"])
        self.assertFalse(
            panel._rows["first_end_turn"]["clear_audio_btn"].isEnabled())


class TestTutorialPanel(TempDataCase):
    """TU-4: the single "Tutorial" leaf's panel over
    ``data/tutorial/tutorial.json`` (TU-1's file). Staged edits (the
    game_theme.py pattern): every change updates an in-memory doc + a dirty
    dot; ONE Save button is the sole write_validated call site. ``steps``
    (and any other TU-1-owned key) must round-trip byte-identical."""

    def make(self):
        from editor.panels.tutorial_panel import TutorialPanel
        return self.track(TutorialPanel(data_dir=self.data_dir))

    def test_loading_populates_both_texts_and_both_flags(self):
        from editor import tutorial_ops
        panel = self.make()
        doc = tutorial_ops.load_tutorial(self.data_dir)
        self.assertEqual(
            panel._message_edits["economy_intro"].toPlainText(),
            doc["messages"]["economy_intro"])
        self.assertEqual(
            panel._message_edits["lives_intro"].toPlainText(),
            doc["messages"]["lives_intro"])
        self.assertEqual(
            panel._flag_checks["skippable"].isChecked(), doc["skippable"])
        self.assertEqual(
            panel._flag_checks["first_loss_costs_life"].isChecked(),
            doc["first_loss_costs_life"])
        self.assertFalse(panel.save_button.isEnabled())

    def test_flag_toggle_stages_dirty_dot_and_saves(self):
        from editor import tutorial_ops
        panel = self.make()
        before = panel._flag_checks["first_loss_costs_life"].isChecked()
        self.assertTrue(panel._dots["first_loss_costs_life"].isHidden())

        panel._flag_checks["first_loss_costs_life"].setChecked(not before)

        self.assertFalse(panel._dots["first_loss_costs_life"].isHidden())
        self.assertTrue(panel.save_button.isEnabled())
        # staged only — nothing written yet
        self.assertEqual(
            tutorial_ops.load_tutorial(self.data_dir)["first_loss_costs_life"],
            before)

        saved = []
        panel.saved.connect(lambda: saved.append(True))
        panel._on_save()

        self.assertEqual(saved, [True])
        self.assertTrue(panel._dots["first_loss_costs_life"].isHidden())
        self.assertFalse(panel.save_button.isEnabled())
        on_disk = tutorial_ops.load_tutorial(self.data_dir)
        self.assertEqual(on_disk["first_loss_costs_life"], not before)
        path = tutorial_ops.tutorial_path(self.data_dir)
        self.assertEqual(path.read_text(encoding="utf-8"),
                         data_io.dumps_deterministic(on_disk))

    def test_message_edit_commits_on_focus_out_and_saves(self):
        from editor import tutorial_ops
        panel = self.make()
        edit = panel._message_edits["economy_intro"]
        edit.setPlainText("a brand new economy message")
        # commit path is manual focus-out (no editingFinished on
        # QPlainTextEdit) — call it directly, the same convention as the
        # balancing.py tests emitting editingFinished directly rather than
        # simulating real OS-level focus loss.
        panel._commit_message("economy_intro")

        self.assertFalse(panel._dots["messages.economy_intro"].isHidden())
        self.assertTrue(panel.save_button.isEnabled())

        panel._on_save()

        doc = tutorial_ops.load_tutorial(self.data_dir)
        self.assertEqual(doc["messages"]["economy_intro"],
                          "a brand new economy message")
        self.assertTrue(panel._dots["messages.economy_intro"].isHidden())

    def test_whitespace_only_commit_is_rejected(self):
        from editor import tutorial_ops
        panel = self.make()
        original = tutorial_ops.load_tutorial(self.data_dir)["messages"]["lives_intro"]
        edit = panel._message_edits["lives_intro"]

        edit.setPlainText("   \n  ")
        panel._commit_message("lives_intro")

        # rejected: field reverts, no dirty dot, Save stays disabled
        self.assertEqual(edit.toPlainText(), original)
        self.assertTrue(panel._dots["messages.lives_intro"].isHidden())
        self.assertFalse(panel.save_button.isEnabled())
        self.assertEqual(
            tutorial_ops.load_tutorial(self.data_dir)["messages"]["lives_intro"],
            original)

    def test_steps_round_trip_byte_identical_after_text_only_edit(self):
        from editor import tutorial_ops
        before = tutorial_ops.load_tutorial(self.data_dir)["steps"]
        panel = self.make()
        edit = panel._message_edits["economy_intro"]
        edit.setPlainText("a different economy message")
        panel._commit_message("economy_intro")
        panel._on_save()

        after = tutorial_ops.load_tutorial(self.data_dir)["steps"]
        self.assertEqual(after, before)


class TestThemeSwitch(TempDataCase):
    """The settings dialog's dark-mode checkbox repaints the app chrome and
    remembers the choice (ED settings panel — moved off the old toolbar
    QCheckBox)."""

    def make_window(self, prefs_path):
        from editor.main import MainWindow

        window = self.track(MainWindow(data_dir=self.data_dir,
                                       prefs_path=prefs_path,
                                       auto_refresh_layouts=False))
        window._timer.stop()
        return window

    def setUp(self):
        super().setUp()
        self.prefs = Path(self.data_dir).parent / ".editor_prefs.json"
        # the theme is application-wide: hand the next test a light app back
        self.addCleanup(theme.apply_theme, QApplication.instance(), "light")

    def is_dark(self):
        window_color = QApplication.instance().palette().color(
            QPalette.ColorRole.Window)
        return window_color.lightness() < 128

    def test_toggle_applies_and_persists(self):
        window = self.make_window(self.prefs)
        dialog = self.track(window._build_settings_dialog())
        self.assertFalse(dialog._dark_box.isChecked())
        self.assertFalse(self.is_dark())

        dialog._dark_box.setChecked(True)
        self.assertEqual(window.theme, "dark")
        self.assertTrue(self.is_dark())
        self.assertEqual(theme.load_theme(self.prefs), "dark")

        dialog._dark_box.setChecked(False)
        self.assertEqual(window.theme, "light")
        self.assertFalse(self.is_dark())
        self.assertEqual(theme.load_theme(self.prefs), "light")

    def test_saved_theme_restored_on_next_launch(self):
        theme.save_theme(self.prefs, "dark")
        window = self.make_window(self.prefs)
        self.assertEqual(window.theme, "dark")
        dialog = self.track(window._build_settings_dialog())
        self.assertTrue(dialog._dark_box.isChecked())
        self.assertTrue(self.is_dark())

    def test_prefs_file_keeps_unrelated_keys(self):
        self.prefs.write_text('{"layout": "abc"}', encoding="utf-8")
        theme.save_theme(self.prefs, "dark")
        prefs = json.loads(self.prefs.read_text(encoding="utf-8"))
        self.assertEqual(prefs, {"layout": "abc", "theme": "dark"})

    def test_unreadable_prefs_fall_back_to_light(self):
        self.prefs.write_text("not json", encoding="utf-8")
        self.assertEqual(theme.load_theme(self.prefs), "light")
        self.assertEqual(theme.load_theme(self.prefs.parent / "nope.json"), "light")


class TestKeybindsPersistence(TempDataCase):
    """editor/keybinds.py — Qt-free load/save, mirrors theme.py's
    read-modify-write + default-backfill contract."""

    def setUp(self):
        super().setUp()
        self.prefs = Path(self.data_dir).parent / ".editor_prefs.json"

    def test_defaults_when_missing(self):
        loaded = keybinds.load_keybinds(self.prefs)
        self.assertEqual(loaded["tools"], keybinds.DEFAULT_TOOL_KEYBINDS)
        self.assertEqual(loaded["brushes"], keybinds.DEFAULT_BRUSH_KEYBINDS)
        self.assertFalse(loaded["undo_redo_swapped"])
        self.assertEqual(loaded["deco_flip"], keybinds.DEFAULT_DECO_FLIP_KEYBIND)

    def test_round_trip_preserves_theme_key(self):
        theme.save_theme(self.prefs, "dark")
        tools = dict(keybinds.DEFAULT_TOOL_KEYBINDS, paint="K")
        brushes = dict(keybinds.DEFAULT_BRUSH_KEYBINDS, brush_1="6")
        keybinds.save_keybinds(self.prefs, tools, brushes, True, "F")

        loaded = keybinds.load_keybinds(self.prefs)
        self.assertEqual(loaded["tools"]["paint"], "K")
        self.assertEqual(loaded["brushes"]["brush_1"], "6")
        self.assertTrue(loaded["undo_redo_swapped"])
        self.assertEqual(loaded["deco_flip"], "F")
        self.assertEqual(theme.load_theme(self.prefs), "dark")   # untouched

    def test_partial_file_backfills_missing_tools(self):
        self.prefs.write_text(
            json.dumps({"keybinds": {"tools": {"paint": "K"}}}),
            encoding="utf-8")
        loaded = keybinds.load_keybinds(self.prefs)
        self.assertEqual(loaded["tools"]["paint"], "K")
        self.assertEqual(loaded["tools"]["erase"],
                         keybinds.DEFAULT_TOOL_KEYBINDS["erase"])

    def test_corrupt_file_falls_back_to_defaults(self):
        self.prefs.write_text("not json", encoding="utf-8")
        loaded = keybinds.load_keybinds(self.prefs)
        self.assertEqual(loaded["tools"], keybinds.DEFAULT_TOOL_KEYBINDS)


class TestSettingsDialog(TempDataCase):
    """The settings dialog rebinds tool/brush keys and the undo/redo swap
    live, updates the window's QActions + palette labels, and persists."""

    def make_window(self):
        from editor.main import MainWindow

        self.prefs = Path(self.data_dir).parent / ".editor_prefs.json"
        window = self.track(MainWindow(data_dir=self.data_dir,
                                       prefs_path=self.prefs,
                                       auto_refresh_layouts=False))
        window._timer.stop()
        return window

    def test_rebinding_a_tool_key_updates_action_label_and_persists(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        dialog._tool_edits["paint"].setKeySequence(QKeySequence("K"))
        dialog._on_tool_key_edited("paint")

        self.assertEqual(window.tool_keybinds["paint"], "K")
        self.assertEqual(window._tool_actions["paint"].shortcut().toString(), "K")
        self.assertEqual(window.palette._tool_buttons["paint"].text(), "Paint (K)")
        self.assertEqual(keybinds.load_keybinds(self.prefs)["tools"]["paint"], "K")

    def test_rebinding_a_brush_key_updates_action_and_persists(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        dialog._brush_edits[0].setKeySequence(QKeySequence("6"))
        dialog._on_brush_key_edited(0)

        self.assertEqual(window.brush_keybinds["brush_1"], "6")
        self.assertEqual(window._brush_actions[0].shortcut().toString(), "6")
        self.assertEqual(
            keybinds.load_keybinds(self.prefs)["brushes"]["brush_1"], "6")

    def test_undo_redo_swap_updates_shortcuts_and_persists(self):
        window = self.make_window()
        self.assertEqual(window.undo_action.shortcut().toString(), "Ctrl+Z")
        self.assertEqual(window.redo_action.shortcut().toString(), "Ctrl+Y")

        dialog = self.track(window._build_settings_dialog())
        dialog._swap_btn.click()

        self.assertTrue(window.undo_redo_swapped)
        self.assertEqual(window.undo_action.shortcut().toString(), "Ctrl+Y")
        self.assertEqual(window.redo_action.shortcut().toString(), "Ctrl+Z")
        self.assertTrue(keybinds.load_keybinds(self.prefs)["undo_redo_swapped"])

    def test_colliding_key_is_rejected_and_reverts(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        # "paint" already owns "B" (default) — binding "erase" to "B" too
        # would leave two QActions sharing one ambiguous shortcut.
        dialog._tool_edits["erase"].setKeySequence(QKeySequence("B"))
        dialog._on_tool_key_edited("erase")

        self.assertEqual(
            dialog._tool_edits["erase"].keySequence().toString(), "N")
        self.assertEqual(window.tool_keybinds["erase"], "N")

    def test_modifier_key_is_rejected(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        dialog._tool_edits["paint"].setKeySequence(QKeySequence("Ctrl+K"))
        dialog._on_tool_key_edited("paint")

        self.assertEqual(
            dialog._tool_edits["paint"].keySequence().toString(), "B")
        self.assertEqual(window.tool_keybinds["paint"], "B")

    def test_rebinding_the_deco_flip_key_updates_action_and_persists(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        dialog._deco_flip_edit.setKeySequence(QKeySequence("F"))
        dialog._on_deco_flip_key_edited()

        self.assertEqual(window.deco_flip_keybind, "F")
        self.assertEqual(window.deco_flip_action.shortcut().toString(), "F")
        self.assertEqual(
            keybinds.load_keybinds(self.prefs)["deco_flip"], "F")

    def test_deco_flip_key_colliding_with_a_tool_key_is_rejected(self):
        window = self.make_window()
        dialog = self.track(window._build_settings_dialog())
        # "paint" already owns "B" (default).
        dialog._deco_flip_edit.setKeySequence(QKeySequence("B"))
        dialog._on_deco_flip_key_edited()

        self.assertEqual(
            dialog._deco_flip_edit.keySequence().toString(),
            keybinds.DEFAULT_DECO_FLIP_KEYBIND)
        self.assertEqual(window.deco_flip_keybind,
                         keybinds.DEFAULT_DECO_FLIP_KEYBIND)

    def test_deco_flip_shortcut_toggles_palette_checkbox(self):
        window = self.make_window()
        self.assertFalse(window.palette._deco_flip_box.isChecked())
        window.deco_flip_action.trigger()
        self.assertTrue(window.palette._deco_flip_box.isChecked())


if __name__ == "__main__":
    unittest.main()
