"""``editor/boss_upgrades_ops.py`` + ``editor/panels/boss_upgrades.py``
(BossUpgradeTimelinePLAN BU-5/BU-6, Qt tier).

``test_timeline_panel.py``'s shape one document over: ``TempDataCase`` (a
throwaway copy of ``data/``, so nothing here can write the repo), the panel's
own methods driven directly for most coverage, plus ONE synthetic
``QDropEvent`` exercising the real Qt drop path — a real OS drag cannot be
synthesized under an offscreen ``QApplication``, and a constructed
``QMimeData`` + a direct ``dropEvent`` call is the standard workaround for
that gap.

**The fixture is PINNED, not inherited.** Every case below authors the
milestone grid it measures (``_pin`` empties all four milestones first), for
exactly the reason ``test_timeline_panel``'s own ``setUp`` docstring records:
these tests count placements and read warnings, and the shipped timeline is
designer content that moves.

What this module deliberately does NOT cover: any art/icon path. D9 makes the
cards text-only, and the panel has no ``set_icon_provider`` to stub.
"""
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent

from engine import data_io
from editor import boss_upgrades_ops as ops
from editor.panels.boss_upgrades import (
    BossUpgradesPanel, _DragHandle, _MIME_TYPE, _decode_upgrade,
    _encode_upgrade,
)
from tools.tests.test_editor_panels import TempDataCase


def _drop_event(mime):
    # QDropEvent(pos, actions, mimeData, buttons, modifiers[, type])
    return QDropEvent(
        QPointF(0, 0), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def _empty_milestones(doc):
    """Clear every slot and zero every retaliation value — the authored-from
    state every case below builds on."""
    for milestone in ops.milestones(doc):
        milestone["slots"] = [None, None, None]
        milestone["retaliation_bonus_love"] = 0
    return doc


# ---------------------------------------------------------------------------
# The pure ops (Qt-free — these need no panel at all)
# ---------------------------------------------------------------------------
class TestBossUpgradesOps(TempDataCase):
    def _doc(self):
        return _empty_milestones(ops.load_boss_upgrades(self.data_dir))

    # -- load / save round-trip ------------------------------------------

    def test_load_validates_and_exposes_both_halves(self):
        doc = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(len(ops.catalog(doc)), 12)
        self.assertEqual(len(ops.milestones(doc)), ops.MILESTONE_COUNT)
        for milestone_idx in range(ops.MILESTONE_COUNT):
            self.assertEqual(len(ops.milestone_slots(doc, milestone_idx)),
                             ops.SLOTS_PER_MILESTONE)

    def test_upgrade_ids_are_sorted_and_stable(self):
        doc = ops.load_boss_upgrades(self.data_dir)
        ids = ops.upgrade_ids(doc)
        self.assertEqual(list(ids), sorted(ids))
        self.assertEqual(set(ids), set(ops.catalog(doc)))

    def test_save_round_trips_every_edit(self):
        doc = self._doc()
        ops.assign_slot(doc, 2, 1, "thorns")
        ops.set_retaliation_love(doc, 2, 77)
        ops.set_catalog_field(doc, "thorns", "name", "Spikes")
        ops.save_boss_upgrades(doc, self.data_dir)

        reloaded = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(ops.milestone_slots(reloaded, 2)[1], "thorns")
        self.assertEqual(ops.retaliation_love(reloaded, 2), 77)
        self.assertEqual(ops.catalog(reloaded)["thorns"]["name"], "Spikes")

    def test_save_writes_canonical_json(self):
        doc = self._doc()
        ops.save_boss_upgrades(doc, self.data_dir)
        raw = ops.boss_upgrades_path(self.data_dir).read_text(encoding="utf-8")
        self.assertEqual(raw, data_io.dumps_deterministic(doc))

    def test_save_raises_before_touching_disk_on_a_schema_violation(self):
        doc = self._doc()
        before = ops.boss_upgrades_path(self.data_dir).read_bytes()
        doc["BossUpgrades"]["Timeline"]["milestones"][0][
            "retaliation_bonus_love"] = "lots"
        with self.assertRaises(Exception):
            ops.save_boss_upgrades(doc, self.data_dir)
        self.assertEqual(
            ops.boss_upgrades_path(self.data_dir).read_bytes(), before)

    # -- assign / clear ---------------------------------------------------

    def test_assign_slot_overwrites_SILENTLY(self):
        """D10: no confirmation, no refusal — the building Timeline's rule."""
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 0, 0, "tile_discount")
        self.assertEqual(ops.milestone_slots(doc, 0)[0], "tile_discount")

    def test_assign_slot_accepts_an_id_already_placed_elsewhere(self):
        """A double placement is legal at assign time — moving a card between
        two milestones IS that state, momentarily."""
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 3, 2, "thorns")
        self.assertEqual(ops.validate_uniqueness(doc), ["thorns"])

    def test_assign_slot_rejects_an_unknown_upgrade_id(self):
        doc = self._doc()
        with self.assertRaises(KeyError):
            ops.assign_slot(doc, 0, 0, "not_an_upgrade")

    def test_assign_slot_accepts_none_as_a_clear(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 0, 0, None)
        self.assertIsNone(ops.milestone_slots(doc, 0)[0])

    def test_clear_slot_leaves_the_array_three_long(self):
        doc = self._doc()
        ops.assign_slot(doc, 1, 1, "thorns")
        ops.clear_slot(doc, 1, 1)
        self.assertEqual(ops.milestone_slots(doc, 1), (None, None, None))

    # -- retaliation ------------------------------------------------------

    def test_set_retaliation_love_coerces_to_int(self):
        doc = self._doc()
        ops.set_retaliation_love(doc, 1, 42.0)
        self.assertIsInstance(ops.retaliation_love(doc, 1), int)
        self.assertEqual(ops.retaliation_love(doc, 1), 42)

    def test_retaliation_bounds_come_from_the_schema(self):
        low, high = ops.retaliation_bounds(self.data_dir)
        schema = data_io.load_json(ops.boss_upgrades_schema_path(self.data_dir))
        node = schema["$defs"]["milestone"]["properties"][
            "retaliation_bonus_love"]
        self.assertEqual((low, high), (node["minimum"], node["maximum"]))

    # -- catalog fields ---------------------------------------------------

    def test_set_catalog_field_writes_name_and_description_as_strings(self):
        doc = self._doc()
        ops.set_catalog_field(doc, "thorns", "name", 5)
        ops.set_catalog_field(doc, "thorns", "description", "hurts {x}")
        self.assertEqual(ops.catalog(doc)["thorns"]["name"], "5")
        self.assertEqual(ops.catalog(doc)["thorns"]["description"],
                         "hurts {x}")

    def test_a_param_is_coerced_to_the_TYPE_ALREADY_IN_THE_DOC(self):
        """The doc validated on load, so its own value is the authority on
        int-vs-number — a designer editing an int param through a double spin
        must not silently rewrite it as a float that fails the schema."""
        doc = self._doc()
        params = ops.catalog(doc)["thorns"]["params"]
        self.assertIsInstance(params["reflect_pct"], int)
        ops.set_catalog_field(doc, "thorns", "reflect_pct", 12.7)
        self.assertIsInstance(params["reflect_pct"], int)
        self.assertEqual(params["reflect_pct"], 13)      # int(round(...))

    def test_a_float_param_stays_a_float(self):
        doc = self._doc()
        params = ops.catalog(doc)["mortar_slow"]["params"]
        ops.set_catalog_field(doc, "mortar_slow", "duration_seconds", 3)
        self.assertIsInstance(params["duration_seconds"], float)
        self.assertEqual(params["duration_seconds"], 3.0)

    def test_set_catalog_field_rejects_an_unknown_id_or_param(self):
        doc = self._doc()
        with self.assertRaises(KeyError):
            ops.set_catalog_field(doc, "not_an_upgrade", "name", "x")
        with self.assertRaises(KeyError):
            ops.set_catalog_field(doc, "thorns", "not_a_param", 1)

    def test_a_coerced_param_still_saves(self):
        doc = self._doc()
        ops.set_catalog_field(doc, "thorns", "reflect_pct", 12.7)
        ops.save_boss_upgrades(doc, self.data_dir)   # would raise on a float

    # -- read-only views ---------------------------------------------------

    def test_placements_maps_every_placed_id_to_its_cell(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 2, "thorns")
        ops.assign_slot(doc, 3, 0, "tile_discount")
        self.assertEqual(ops.placements(doc),
                         {"thorns": (0, 2), "tile_discount": (3, 0)})

    def test_placements_is_empty_on_an_empty_grid(self):
        self.assertEqual(ops.placements(self._doc()), {})

    def test_a_double_placement_maps_to_its_LAST_cell(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 2, 1, "thorns")
        self.assertEqual(ops.placements(doc)["thorns"], (2, 1))

    def test_validate_uniqueness_returns_sorted_ids_and_never_raises(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 1, 0, "thorns")
        ops.assign_slot(doc, 0, 1, "tile_discount")
        ops.assign_slot(doc, 2, 0, "tile_discount")
        self.assertEqual(ops.validate_uniqueness(doc),
                         ["thorns", "tile_discount"])

    def test_validate_uniqueness_is_empty_when_every_id_is_placed_once(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 1, 1, "tile_discount")
        self.assertEqual(ops.validate_uniqueness(doc), [])

    def test_validate_uniqueness_never_mutates_the_doc(self):
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 1, 0, "thorns")
        before = data_io.dumps_deterministic(doc)
        ops.validate_uniqueness(doc)
        self.assertEqual(data_io.dumps_deterministic(doc), before)

    def test_SAVE_DOES_NOT_CONSULT_validate_uniqueness(self):
        """D3 warns, it never blocks — the opposite stance from
        ``timeline_ops.validate_uniqueness``. Blocking here would trap a
        designer halfway through moving a card between two milestones, which
        is exactly the state silent overwrite exists to allow."""
        doc = self._doc()
        ops.assign_slot(doc, 0, 0, "thorns")
        ops.assign_slot(doc, 1, 0, "thorns")
        ops.save_boss_upgrades(doc, self.data_dir)      # must not raise
        reloaded = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(ops.validate_uniqueness(reloaded), ["thorns"])

    def test_catalog_param_specs_lists_every_upgrade_off_the_SCHEMA(self):
        specs = ops.catalog_param_specs(self.data_dir)
        doc = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(set(specs), set(ops.catalog(doc)))
        # a param-less upgrade is still listed, with no params
        self.assertEqual(specs["restock_lives"], {})
        reflect = specs["thorns"]["reflect_pct"]
        self.assertEqual(reflect["type"], "integer")
        self.assertIsNotNone(reflect["minimum"])
        self.assertIsNotNone(reflect["maximum"])
        self.assertTrue(reflect["description"])

    def test_param_specs_type_matches_the_docs_own_value_type(self):
        """The panel picks an int spin vs a double spin off the SPEC, and
        `set_catalog_field` coerces off the DOC — a disagreement would make
        one of the two lie."""
        specs = ops.catalog_param_specs(self.data_dir)
        doc = ops.load_boss_upgrades(self.data_dir)
        for upgrade_id, entry in ops.catalog(doc).items():
            for param, value in entry["params"].items():
                with self.subTest(upgrade=upgrade_id, param=param):
                    want = "integer" if isinstance(value, int) else "number"
                    self.assertEqual(specs[upgrade_id][param]["type"], want)


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------
class TestBossUpgradesPanel(TempDataCase):
    def _panel(self):
        """A panel over a PINNED empty grid. Emptying the STAGED doc is the
        fixture; nothing is written until a test calls Save."""
        panel = self.track(BossUpgradesPanel(data_dir=self.data_dir))
        _empty_milestones(panel._doc)
        panel._rebuild_grid()
        panel._refresh_placed_state()
        panel._refresh_warnings()
        panel._dirty = False
        panel.save_button.setEnabled(False)
        return panel

    # -- construction ------------------------------------------------------

    def test_it_builds_one_card_per_catalog_upgrade(self):
        panel = self._panel()
        self.assertEqual(set(panel._cards), set(ops.catalog(panel._doc)))
        self.assertEqual(len(panel._cards), 12)

    def test_it_builds_a_four_by_three_slot_grid(self):
        panel = self._panel()
        self.assertEqual(
            set(panel._slot_widgets),
            {(m, s) for m in range(ops.MILESTONE_COUNT)
             for s in range(ops.SLOTS_PER_MILESTONE)})
        self.assertEqual(set(panel._retaliation_spins),
                         set(range(ops.MILESTONE_COUNT)))

    def test_a_card_exposes_editable_fields_and_schema_ranged_params(self):
        panel = self._panel()
        card = panel._cards["thorns"]
        self.assertEqual(card.name_edit.text(),
                         ops.catalog(panel._doc)["thorns"]["name"])
        spin = card.param_widgets["reflect_pct"]
        spec = ops.catalog_param_specs(self.data_dir)["thorns"]["reflect_pct"]
        self.assertEqual(spin.minimum(), spec["minimum"])
        self.assertEqual(spin.maximum(), spec["maximum"])

    def test_a_param_less_upgrade_builds_no_param_widgets(self):
        self.assertEqual(self._panel()._cards["restock_lives"].param_widgets,
                         {})

    def test_seeding_the_form_never_dirties_the_document(self):
        """The `balancing.py` populate-then-connect rule: merely LOOKING at
        the panel must not enable Save."""
        panel = self.track(BossUpgradesPanel(data_dir=self.data_dir))
        self.assertFalse(panel._dirty)
        self.assertFalse(panel.save_button.isEnabled())

    # -- assignment --------------------------------------------------------

    def test_assign_slot_updates_the_widget_and_the_browse_marker(self):
        panel = self._panel()
        panel.assign_slot(1, 2, "thorns")
        self.assertEqual(panel._slot_widgets[(1, 2)].upgrade_id, "thorns")
        self.assertIn("milestone 2", panel._cards["thorns"].placed_label.text())
        self.assertIn("slot 3", panel._cards["thorns"].placed_label.text())
        self.assertTrue(panel._dirty)
        self.assertTrue(panel.save_button.isEnabled())

    def test_an_unplaced_card_says_so(self):
        self.assertEqual(self._panel()._cards["thorns"].placed_label.text(),
                         "not placed")

    def test_a_placed_card_is_NOT_disabled(self):
        """Unlike the building Timeline: the roster is a fixed 12 and moving
        an upgrade between milestones is the normal gesture."""
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        self.assertTrue(panel._cards["thorns"].isEnabled())

    def test_dropping_onto_an_occupied_slot_overwrites_silently(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        panel.assign_slot(0, 0, "tile_discount")
        self.assertEqual(panel._slot_widgets[(0, 0)].upgrade_id,
                         "tile_discount")
        self.assertEqual(panel._cards["thorns"].placed_label.text(),
                         "not placed")

    def test_a_stale_drop_payload_never_raises_out_of_the_slot(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "not_an_upgrade")     # must not raise
        self.assertIsNone(panel._slot_widgets[(0, 0)].upgrade_id)
        self.assertFalse(panel._dirty)

    def test_clear_slot_empties_the_widget_and_unmarks_the_card(self):
        panel = self._panel()
        panel.assign_slot(2, 1, "thorns")
        panel.clear_slot(2, 1)
        self.assertIsNone(panel._slot_widgets[(2, 1)].upgrade_id)
        self.assertEqual(panel._cards["thorns"].placed_label.text(),
                         "not placed")

    # -- the real Qt drag/drop path ---------------------------------------

    def test_the_drag_handle_carries_the_upgrade_id(self):
        handle = self.track(_DragHandle("thorns"))
        self.assertEqual(handle.upgrade_id, "thorns")
        self.assertEqual(_decode_upgrade(_encode_upgrade("thorns")), "thorns")

    def test_drop_event_on_a_slot_assigns_via_the_real_qt_path(self):
        panel = self._panel()
        slot = panel._slot_widgets[(3, 0)]
        mime = QMimeData()
        mime.setData(_MIME_TYPE, _encode_upgrade("tile_refund"))
        slot.dropEvent(_drop_event(mime))
        self.assertEqual(panel._slot_widgets[(3, 0)].upgrade_id, "tile_refund")
        self.assertEqual(ops.milestone_slots(panel._doc, 3)[0], "tile_refund")
        self.assertTrue(panel._dirty)

    def test_a_drop_of_a_foreign_mime_type_is_ignored(self):
        panel = self._panel()
        slot = panel._slot_widgets[(0, 0)]
        mime = QMimeData()
        mime.setData("text/plain", b"thorns")
        slot.dropEvent(_drop_event(mime))
        self.assertIsNone(panel._slot_widgets[(0, 0)].upgrade_id)
        self.assertFalse(panel._dirty)

    def test_a_drop_onto_a_full_slot_replaces_through_the_qt_path(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        mime = QMimeData()
        mime.setData(_MIME_TYPE, _encode_upgrade("tile_discount"))
        panel._slot_widgets[(0, 0)].dropEvent(_drop_event(mime))
        self.assertEqual(panel._slot_widgets[(0, 0)].upgrade_id,
                         "tile_discount")

    # -- the warnings label -------------------------------------------------

    def test_no_duplicates_hides_the_warning(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        self.assertFalse(panel.warnings_label.isVisible())
        self.assertEqual(panel.warnings_label.text(), "")

    def test_a_double_placement_surfaces_in_the_warning_label(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        panel.assign_slot(2, 2, "thorns")
        self.assertIn("thorns", panel.warnings_label.text())
        self.assertEqual(panel.warnings_label.text().count("thorns"), 1)

    def test_clearing_the_duplicate_clears_the_warning(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        panel.assign_slot(2, 2, "thorns")
        panel.clear_slot(2, 2)
        self.assertEqual(panel.warnings_label.text(), "")

    def test_a_double_placement_never_blocks_save(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        panel.assign_slot(2, 2, "thorns")
        self.assertTrue(panel.save_button.isEnabled())
        panel._on_save()
        self.assertFalse(panel._dirty)
        reloaded = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(ops.validate_uniqueness(reloaded), ["thorns"])

    # -- staged catalog / retaliation edits ---------------------------------

    def test_set_catalog_field_stages_and_refreshes_the_slot_name(self):
        panel = self._panel()
        panel.assign_slot(0, 0, "thorns")
        panel.set_catalog_field("thorns", "name", "Spikes")
        self.assertEqual(ops.catalog(panel._doc)["thorns"]["name"], "Spikes")
        self.assertTrue(panel._dirty)

    def test_set_catalog_field_never_rebuilds_the_card_being_typed_in(self):
        """Rebuilding would destroy the widget the designer is typing into —
        the Timeline panel's `set_level_round` rule."""
        panel = self._panel()
        card = panel._cards["thorns"]
        panel.set_catalog_field("thorns", "name", "Spikes")
        self.assertIs(panel._cards["thorns"], card)

    def test_an_unknown_catalog_field_never_raises_out_of_the_slot(self):
        panel = self._panel()
        panel.set_catalog_field("thorns", "not_a_param", 1)   # must not raise
        self.assertFalse(panel._dirty)

    def test_set_retaliation_love_stages_the_value(self):
        panel = self._panel()
        panel.set_retaliation_love(2, 123)
        self.assertEqual(ops.retaliation_love(panel._doc, 2), 123)
        self.assertTrue(panel._dirty)

    def test_the_retaliation_spins_are_ranged_by_the_schema(self):
        panel = self._panel()
        low, high = ops.retaliation_bounds(self.data_dir)
        for spin in panel._retaliation_spins.values():
            self.assertEqual((spin.minimum(), spin.maximum()), (low, high))

    # -- save ---------------------------------------------------------------

    def test_save_writes_every_staged_edit_and_clears_the_dirty_flag(self):
        panel = self._panel()
        panel.assign_slot(1, 0, "thorns")
        panel.set_retaliation_love(1, 99)
        panel.set_catalog_field("thorns", "reflect_pct", 15)
        panel._on_save()

        self.assertFalse(panel._dirty)
        self.assertFalse(panel.save_button.isEnabled())
        doc = ops.load_boss_upgrades(self.data_dir)
        self.assertEqual(ops.milestone_slots(doc, 1)[0], "thorns")
        self.assertEqual(ops.retaliation_love(doc, 1), 99)
        self.assertEqual(ops.catalog(doc)["thorns"]["params"]["reflect_pct"],
                         15)

    def test_save_emits_saved(self):
        panel = self._panel()
        seen = []
        panel.saved.connect(lambda: seen.append(1))
        panel.assign_slot(0, 1, "thorns")
        panel._on_save()
        self.assertEqual(seen, [1])

    def test_saving_a_clean_panel_is_a_no_op(self):
        panel = self._panel()
        before = ops.boss_upgrades_path(self.data_dir).read_bytes()
        panel._on_save()
        self.assertEqual(
            ops.boss_upgrades_path(self.data_dir).read_bytes(), before)

    def test_reload_after_save_shows_the_written_state(self):
        panel = self._panel()
        panel.assign_slot(2, 2, "tile_refund")
        panel._on_save()
        panel.set_boss_upgrades()          # the leaf's re-entry path
        self.assertEqual(panel._slot_widgets[(2, 2)].upgrade_id, "tile_refund")
        self.assertFalse(panel._dirty)

    # -- E-37: a broken tree degrades, it never raises ----------------------

    def test_a_missing_document_shows_a_placeholder_instead_of_raising(self):
        ops.boss_upgrades_path(self.data_dir).unlink()
        panel = self.track(BossUpgradesPanel(data_dir=self.data_dir))
        self.assertIsNone(panel._doc)
        self.assertEqual(panel._cards, {})
        self.assertEqual(panel._slot_widgets, {})
        self.assertFalse(panel.save_button.isEnabled())
        # ...and every mutation is inert rather than a crash
        panel.assign_slot(0, 0, "thorns")
        panel.clear_slot(0, 0)
        panel.set_retaliation_love(0, 5)
        panel.set_catalog_field("thorns", "name", "x")
        panel._on_save()
        self.assertFalse(panel._dirty)


if __name__ == "__main__":
    import unittest
    unittest.main()
