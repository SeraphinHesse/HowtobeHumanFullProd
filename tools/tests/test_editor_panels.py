"""Phase 4 acceptance tests: selector + balancing panels + locks
(ED-3, ED-30/31/32).

Same headless conventions as test_editor_viewport.py: QT_QPA_PLATFORM=
offscreen + SDL dummy drivers before any Qt/pygame import, one
QApplication per process. Every test runs against a tempfile COPY of
data/ so panel writes never touch the repo's files — which is why all
editor modules take a data_dir parameter.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
)

from editor import locks
from editor.panels.balancing import BalancingPanel
from editor.panels.selector import _PAYLOAD_ROLE, SelectorPanel
from engine import data_io

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


def read_domain(data_dir, domain):
    return data_io.load_validated(
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


def lock_domain(data_dir, domain, owner_name="featureBuildings"):
    """Simulate /start-domain by another owner (through the validating
    writer — tests obey D-2 too)."""
    doc = read_domain(data_dir, domain)
    doc["_lock"] = {"locked_by": owner_name, "since": "2026-07-03"}
    data_io.write_validated(
        doc,
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


class TempDataCase(unittest.TestCase):
    """Copies data/ into a temp dir so writes never touch the repo, and
    normalizes every domain to UNLOCKED — the repo copy may legitimately be
    locked while a feature branch exists (e.g. the 9A batch), but these
    tests need a known lock state."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        for domain in locks.DOMAINS:
            doc = read_domain(self.data_dir, domain)
            if doc["_lock"] != "UNLOCKED":
                doc["_lock"] = "UNLOCKED"
                data_io.write_validated(
                    doc,
                    self.data_dir / "balancing" / f"{domain}.json",
                    self.data_dir / "schemas" / f"{domain}.schema.json",
                )


class TestLocks(TempDataCase):
    def test_unlocked_domain(self):
        self.assertFalse(locks.is_locked("buildings", self.data_dir))
        self.assertIsNone(locks.owner("buildings", self.data_dir))

    def test_locked_domain(self):
        lock_domain(self.data_dir, "enemies", "featureEnemies")
        self.assertTrue(locks.is_locked("enemies", self.data_dir))
        self.assertEqual(locks.owner("enemies", self.data_dir), "featureEnemies")

    def test_no_force_unlock_api(self):
        """ED-32/T-1: the editor exposes no way to set or clear a lock."""
        for name in dir(locks):
            self.assertNotIn("unlock", name.lower())
            self.assertNotIn("release", name.lower())


class TestSelector(TempDataCase):
    def test_lists_domains_in_d10_order(self):
        panel = SelectorPanel(data_dir=self.data_dir)
        self.assertEqual(panel.domains(), locks.DOMAINS)

    def test_domain_without_file_is_omitted(self):
        (self.data_dir / "balancing" / "map.json").unlink()
        panel = SelectorPanel(data_dir=self.data_dir)
        self.assertEqual(panel.domains(), tuple(d for d in locks.DOMAINS if d != "map"))

    def test_selection_emits_domain_and_is_single(self):
        panel = SelectorPanel(data_dir=self.data_dir)
        seen = []
        panel.domain_selected.connect(seen.append)
        panel.select_domain("enemies")
        panel.select_domain("core")
        self.assertEqual(seen, ["enemies", "core"])
        self.assertEqual(len(panel.selectedItems()), 1)  # ED-3


class TestSelectorTree(TempDataCase):
    """Phase 5 (ED-10/11): the tree grows from the slot registry — category
    roots with group children, ● markers from the manifest. Domain behavior
    (TestSelector above) must survive unchanged."""

    def make(self):
        return SelectorPanel(data_dir=self.data_dir)

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
        panel = self.make()
        self.assertNotIn("vfx", panel.domains())
        self.assertNotIn("deco", panel.domains())
        domains = []
        panel.domain_selected.connect(domains.append)
        panel.select_node("vfx", ("Effects",))   # node exists and is selectable
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


class TestBalancingPanel(TempDataCase):
    def make_panel(self, domain):
        panel = BalancingPanel(data_dir=self.data_dir)
        panel.set_domain(domain)
        return panel

    def test_widgets_generated_from_schema(self):
        """ED-30: int -> spinbox, number -> double spinbox, bool -> checkbox,
        string -> line edit; _lock never appears at any depth; widgets key by
        '/'-joined paths into the 9A nested tree."""
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
        for key in panel._widgets:
            self.assertNotIn("_lock", key)

    def test_selection_switches_panel_content(self):
        """ED-3: the selected tree node drives the form's content."""
        selector = SelectorPanel(data_dir=self.data_dir)
        panel = BalancingPanel(data_dir=self.data_dir)
        selector.domain_selected.connect(panel.set_domain)
        selector.select_domain("buildings")
        self.assertIn("DefenceBuildings/BasicDefence/tiers/0/base_dmg", panel._widgets)
        selector.select_domain("enemies")
        self.assertIn("EnemyTypes/Standard/hp", panel._widgets)
        self.assertNotIn(
            "DefenceBuildings/BasicDefence/tiers/0/base_dmg", panel._widgets
        )

    def test_edit_writes_validated_canonical_file(self):
        """ED-31: a nested widget change -> write_validated -> the correct
        leaf updated in canonical JSON on disk (the 9A Quick Test edit)."""
        panel = self.make_panel("buildings")
        panel._widgets["DefenceBuildings/BasicDefence/tiers/0/base_dmg"].setValue(30)
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(
            on_disk["DefenceBuildings"]["BasicDefence"]["tiers"][0]["base_dmg"], 30
        )
        path = self.data_dir / "balancing" / "buildings.json"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text, data_io.dumps_deterministic(on_disk))

    def test_out_of_range_input_unrepresentable(self):
        """ED-30: the widget clamps to the schema's bounds — invalid values
        cannot even be entered, let alone written."""
        panel = self.make_panel("buildings")
        widget = panel._widgets["DefenceBuildings/BasicDefence/tiers/0/base_dmg"]
        widget.setValue(999999)
        self.assertEqual(widget.value(), 100000)  # schema maximum (x10 scale cap)
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(
            on_disk["DefenceBuildings"]["BasicDefence"]["tiers"][0]["base_dmg"], 100000
        )

    def test_checkbox_writes_typed_value(self):
        panel = self.make_panel("ui")
        panel._widgets["FX/gore_enabled"].setChecked(False)
        self.assertIs(read_domain(self.data_dir, "ui")["FX"]["gore_enabled"], False)

    def test_string_edit_writes_and_empty_is_restored(self):
        """string -> QLineEdit; an empty edit violating minLength is restored
        instead of written (invalid input unrepresentable, ED-30)."""
        panel = self.make_panel("buildings")
        widget = panel._widgets["BuildingsGlobal/random_names/0"]
        widget.setText("Zed")
        widget.editingFinished.emit()
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(on_disk["BuildingsGlobal"]["random_names"][0], "Zed")
        widget.setText("")
        widget.editingFinished.emit()
        self.assertEqual(widget.text(), "Zed")  # restored, nothing written
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(on_disk["BuildingsGlobal"]["random_names"][0], "Zed")

    def test_enum_widget_from_synthetic_domain(self):
        """No live domain carries an enum after 9A; a synthetic schema/data
        pair keeps _make_widget's enum -> QComboBox branch covered."""
        schema = {
            "$id": "synthetic.schema.json",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "properties": {
                "_lock": {"oneOf": [{"const": "UNLOCKED"}]},
                "mode": {
                    "description": "Synthetic enum for widget coverage.",
                    "enum": [1, 2, 4],
                    "type": "integer",
                },
            },
            "required": ["_lock", "mode"],
            "title": "synthetic",
            "type": "object",
        }
        schema_path = self.data_dir / "schemas" / "synthetic.schema.json"
        schema_path.write_text(
            data_io.dumps_deterministic(schema), encoding="utf-8"
        )
        data_io.write_validated(
            {"_lock": "UNLOCKED", "mode": 1},
            self.data_dir / "balancing" / "synthetic.json",
            schema_path,
        )
        panel = self.make_panel("synthetic")
        combo = panel._widgets["mode"]
        self.assertIsInstance(combo, QComboBox)
        combo.setCurrentIndex(combo.findData(4))
        self.assertEqual(read_domain(self.data_dir, "synthetic")["mode"], 4)

    def test_locked_domain_readonly_with_owner_shown(self):
        """ED-32: locked -> every field disabled + owner in the banner."""
        lock_domain(self.data_dir, "buildings", "featureBuildings")
        panel = self.make_panel("buildings")
        for key, widget in panel._widgets.items():
            self.assertFalse(widget.isEnabled(), msg=key)
        self.assertIn("featureBuildings", panel._banner.text())
        self.assertFalse(panel._banner.isHidden())

    def test_unlocked_domain_editable_no_banner(self):
        panel = self.make_panel("buildings")
        for key, widget in panel._widgets.items():
            self.assertTrue(widget.isEnabled(), msg=key)
        self.assertTrue(panel._banner.isHidden())


class TestMainWindowWiring(TempDataCase):
    """End-to-end: shell wires selector -> balancing, initial selection set."""

    def make_window(self):
        from editor.main import MainWindow

        window = MainWindow(data_dir=self.data_dir)
        self.addCleanup(window.close)
        window._timer.stop()  # no frame drive needed here
        return window

    def test_select_and_edit_through_the_shell(self):
        window = self.make_window()
        self.assertEqual(window.balancing.domain, locks.DOMAINS[0])
        window.selector.select_domain("ui")
        self.assertEqual(window.balancing.domain, "ui")
        window.balancing._widgets["Timing/not_enough_love_duration"].setValue(2.5)
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
        preview + ● marker; clear -> grey X returns."""
        from PIL import Image

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


if __name__ == "__main__":
    unittest.main()
