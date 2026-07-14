"""How To Be Human editor — Qt shell (ED-1). Phase 5 scope: selector +
viewport + balancing + details (asset import), selection-driven.

    py editor/main.py

Layout (user-confirmed Phase 5 shape): selector tree (left) | viewport over
[level bar + balancing form] (center) | Details panel (right), in plain
QSplitters — full docking + .editor_prefs.json persistence is ED-1's
eventual shape and lands later.

Selection is composite (ED-3 stays: ONE tree node drives everything, the
dropdown/level bar refine it): the tree selects a category/group node,
which maps 1:1 to a balancing domain where one exists (vfx/deco keep the
last domain); the Details dropdown picks the subcategory (tier) and the
level bar the level; editor.selection resolves the trio to a slot key that
drives the viewport's entity preview and the import context. Import-panel
edits preview live as viewport drafts; a save reloads the viewport's assets
and refreshes the ● markers without a restart (ED-42).

main(max_frames=None) lets the window be driven headlessly under
QT_QPA_PLATFORM=offscreen (mirrors game/main.py's max_frames convention
for tools/smoke.py). Frames are driven by a QTimer — no busy-spin.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from editor import agent_forms, registry_ops, selection, theme
from editor.agent_form_dialog import AgentFormDialog
from editor.map_session import MapSession
from editor.run_controls import RunControls
from editor.spawnclaude import SpawnClaudeDialog
from editor.panels.balancing import BalancingPanel
from editor.panels.details import DetailsPanel
from editor.panels.level_bar import LevelBar
from editor.panels.map_details import MapDetailsPanel
from editor.panels.palette import PalettePanel
from editor.panels.selector import SelectorPanel
from editor.panels.viewport import ViewportPanel
from tools.smoke import validate_data

FRAME_INTERVAL_MS = 16  # ~60fps tick, timer-driven (no busy-spin)
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "drunken_donuts_logo.png"
PREFS_PATH = REPO / ".editor_prefs.json"


class MainWindow(QMainWindow):
    def __init__(self, max_frames=None, data_dir=None, prefs_path=None):
        super().__init__()
        self._prefs_path = Path(prefs_path) if prefs_path is not None else PREFS_PATH
        self.setWindowTitle("How To Be Human — editor")
        self.resize(1280, 720)

        # Brand toolbar: small logo pinned top-left (ED chrome only, no
        # layout impact on the splitters below it).
        brand_toolbar = self.addToolBar("Brand")
        brand_toolbar.setMovable(False)
        brand_toolbar.setFloatable(False)
        brand_logo = QLabel()
        logo_pixmap = QPixmap(str(LOGO_PATH))
        if not logo_pixmap.isNull():
            brand_logo.setPixmap(logo_pixmap.scaledToHeight(
                24, Qt.TransformationMode.SmoothTransformation))
        brand_toolbar.addWidget(brand_logo)

        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"

        self.viewport = ViewportPanel(data_dir=data_dir)
        self.selector = SelectorPanel(data_dir=data_dir)
        self.balancing = BalancingPanel(data_dir=data_dir)
        self.details = DetailsPanel(data_dir=data_dir)
        self.levelbar = LevelBar()
        self.palette = PalettePanel(data_dir=data_dir)
        self.map_details = MapDetailsPanel(data_dir=data_dir)
        self.map_session = MapSession(data_dir=data_dir, parent=self)
        self._node = None   # (category_key, group_path) of the tree selection
        # dirty policy when opening a DIFFERENT map over unsaved edits:
        # "ask" (QMessageBox Save/Discard/Cancel) | "save" | "discard"
        self.dirty_policy = "ask"

        self.selector.domain_selected.connect(self.balancing.set_domain)
        self.selector.node_selected.connect(self._on_node_selected)
        self.selector.map_selected.connect(self._on_map_selected)
        self.selector.add_requested.connect(self._on_add_requested)
        self.details.subcategory_changed.connect(self._on_subcategory_changed)
        self.levelbar.level_changed.connect(self._on_level_changed)
        self.levelbar.add_variant_requested.connect(self._on_add_variant)
        self.levelbar.add_type_requested.connect(self._on_add_prop)
        self.details.draft_changed.connect(self.viewport.set_preview_draft)
        self.details.entry_saved.connect(self._on_manifest_changed)
        self.details.entry_cleared.connect(self._on_manifest_changed)

        # tilemap-mode wiring (ED-20): palette state → viewport; picker →
        # palette re-arm; session lifecycle → selector Maps branch
        self.palette.tool_changed.connect(self.viewport.set_tool)
        self.palette.code_armed.connect(self.viewport.arm_code)
        self.palette.deco_armed.connect(self.viewport.arm_deco)
        self.palette.base_armed.connect(self.viewport.arm_base)
        self.palette.camera_armed.connect(self.viewport.arm_camera)
        self.palette.start_area_armed.connect(self.viewport.arm_start_area)
        self.palette.eye_toggled.connect(self.viewport.set_eye)
        self.palette.grid_toggled.connect(self.viewport.set_grid_lines)
        self.palette.manifest_changed.connect(self._on_manifest_changed)
        self.palette.add_level_requested.connect(self._on_add_level)
        self.palette.add_prop_requested.connect(self._on_add_prop)
        self.palette.add_deco_variant_requested.connect(
            self._on_add_deco_variant)
        self.palette.set_icon_provider(self.viewport.slot_qimage)
        self.viewport.code_picked.connect(self.palette.arm_code)
        self.viewport.cursor_world.connect(self._on_cursor_world)
        self.map_session.map_opened.connect(self._on_session_map_opened)
        self.map_session.active_changed.connect(
            lambda _map_id: self.selector.refresh_maps())
        self.map_details.set_session(self.map_session)
        self.map_details.dirty_resolver = self._resolve_dirty
        self.map_details.map_deleted.connect(self._on_map_deleted)

        # ED-24: THE global undo stack, Ctrl+Z / Ctrl+Y everywhere
        undo = QAction("Undo", self)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.triggered.connect(self.map_session.undo_stack.undo)
        redo = QAction("Redo", self)
        redo.setShortcut(QKeySequence("Ctrl+Y"))
        redo.triggered.connect(self.map_session.undo_stack.redo)
        self.addAction(undo)
        self.addAction(redo)

        # ED-50/51/52: run controls toolbar + console pane (Play/Build output
        # only — spawnclaude gets its own terminal in Phase 8)
        self.run_controls = RunControls(data_dir=data_dir, parent=self)
        self.console = QPlainTextEdit(readOnly=True)
        self.console.setFont(QFont("Consolas", 9))
        console_dock = QDockWidget("Console", self)
        console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, console_dock)

        run_toolbar = self.addToolBar("Run")
        self.play_action = QAction("Play", self)
        self.build_action = QAction("Build", self)
        self.playbuild_action = QAction("Playbuild", self)
        run_toolbar.addAction(self.play_action)
        run_toolbar.addAction(self.build_action)
        run_toolbar.addAction(self.playbuild_action)

        self.play_action.triggered.connect(self._on_play)
        self.build_action.triggered.connect(self.run_controls.build)
        self.playbuild_action.triggered.connect(self.run_controls.playbuild)
        self.run_controls.output.connect(self.console.appendPlainText)
        self.run_controls.launched.connect(self._on_launched)
        self.run_controls.started.connect(self._on_build_started)
        self.run_controls.finished.connect(self._on_build_finished)
        self.run_controls.build_state_changed.connect(
            self._update_playbuild_enabled)
        self._update_playbuild_enabled(self.run_controls.can_playbuild())

        # ED-60/61/62 + AD-3: Spawnclaude — the agent launcher. Opens a claude
        # session in its OWN terminal (not the Console dock): an "Add new X"
        # form (→ /dispatch <handoff>), a small tweak, or a blank admin session.
        # The editor never writes a lock (the branch+lock protocol is suspended).
        agents_toolbar = self.addToolBar("Agents")
        self.spawnclaude_action = QAction("Summon a Drunken Robot", self)
        agents_toolbar.addAction(self.spawnclaude_action)
        self.spawnclaude_action.triggered.connect(self._on_spawnclaude)

        # Chrome theme switch, next to the summon button. Chrome only — the
        # viewport still draws through engine/render (ED-22).
        agents_toolbar.addSeparator()
        self.theme = theme.load_theme(self._prefs_path)
        theme.apply_theme(QApplication.instance(), self.theme)
        self.theme_switch = QCheckBox("Dark mode")
        self.theme_switch.setToolTip("Light / dark editor chrome")
        self.theme_switch.setChecked(self.theme == "dark")
        self.theme_switch.toggled.connect(self._on_theme_toggled)
        agents_toolbar.addWidget(self.theme_switch)

        self.palette.setVisible(False)
        # Height floor so the nested viewport_row can't collapse to 0 when the
        # palette is hidden (entity mode) — otherwise the outer vertical split
        # hands the whole center to the balancing form and the viewport vanishes.
        self.viewport.setMinimumHeight(240)
        viewport_row = QSplitter(Qt.Orientation.Horizontal)
        viewport_row.addWidget(self.palette)
        viewport_row.addWidget(self.viewport)
        viewport_row.setStretchFactor(0, 0)
        viewport_row.setStretchFactor(1, 1)
        viewport_row.setSizes([150, 700])

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.levelbar)
        bottom_layout.addWidget(self.balancing, 1)

        center = QSplitter(Qt.Orientation.Vertical)
        center.addWidget(viewport_row)
        center.addWidget(bottom)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 1)
        center.setCollapsible(0, False)   # never collapse the viewport row
        center.setSizes([520, 200])       # sane initial split (not stretch-only)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.details)      # index 0: asset import
        self.right_stack.addWidget(self.map_details)  # index 1: map lifecycle

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.selector)
        split.addWidget(center)
        split.addWidget(self.right_stack)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([220, 760, 300])
        self.setCentralWidget(split)
        self.statusBar().showMessage("")   # ED-23 world-coordinate readout

        domains = self.selector.domains()
        if domains:
            self.selector.select_domain(domains[0])

        self._max_frames = max_frames
        self.frames = 0
        self._fps_window = 0
        self._fps_elapsed = 0.0
        self._last_tick = time.perf_counter()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_INTERVAL_MS)

    # -- composite slot selection (tree node × subcategory × level) ---------

    def _on_node_selected(self, category_key, group_path):
        self._leave_map_mode()
        self._node = (category_key, tuple(group_path))
        self.details.set_context(category_key, group_path)
        self._refresh_levels()

    # -- tilemap mode (ED-20): map node selected -----------------------------

    def _on_map_selected(self, map_id):
        session = self.map_session
        if session.doc is not None and session.doc.map_id == map_id:
            self._enter_map_mode()   # same doc (possibly dirty): keep edits
            return
        if not self._resolve_dirty():
            # cancelled: put the selection back on the still-open map
            self.selector.select_map(session.doc.map_id)
            return
        session.open(map_id)
        self._enter_map_mode()

    def _enter_map_mode(self):
        self.viewport.set_map_mode(self.map_session)
        self.palette.set_legend(self.map_session.doc.legend)
        # Default to Game-tiles mode; set_mode arms the first zone brush.
        self.palette.set_mode("gametiles")
        self.palette.setVisible(True)
        self.right_stack.setCurrentWidget(self.map_details)
        self.map_details.refresh()

    def _on_map_deleted(self):
        self._leave_map_mode()
        self.selector.refresh_maps()

    def _leave_map_mode(self):
        # the session keeps its (possibly dirty) doc — reselecting the same
        # map returns to it; the prompt only guards opening a DIFFERENT map
        if self.viewport.in_map_mode():
            self.viewport.set_map_mode(None)
        self.palette.setVisible(False)
        self.right_stack.setCurrentWidget(self.details)

    def _resolve_dirty(self):
        """True → proceed (saving first if asked); False → cancel."""
        session = self.map_session
        if not session.dirty:
            return True
        policy = self.dirty_policy
        if policy == "ask":
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"Map {session.doc.map_id!r} has unsaved changes.",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            policy = "save" if answer == QMessageBox.StandardButton.Save \
                else "discard"
        if policy == "save":
            session.save()
        return True

    def _on_session_map_opened(self, map_id):
        """create/duplicate/open: Maps branch follows, node gets selected
        (re-selection of an already-open map short-circuits upstream)."""
        self.selector.refresh_maps()
        if map_id in self.selector.map_ids():
            self.selector.select_map(map_id)

    def _on_cursor_world(self, wx, wy):
        self.statusBar().showMessage(
            f"world ({wx:.2f}, {wy:.2f})   tile ({int(wx // 1)}, {int(wy // 1)})")

    def _on_subcategory_changed(self, _index):
        self._refresh_levels()

    def _on_level_changed(self, _index):
        self._apply_slot()

    def _refresh_levels(self):
        category_key, group_path = self._node
        slots = selection.level_slots(
            self.selector.registry, category_key, group_path,
            self.details.subcategory_index())
        assigned = set(self.viewport.assigned_slots())
        self.levelbar.set_levels(
            slots, assigned,
            can_add=self._variant_target() is not None,
            can_add_type=category_key == self._DECO_CATEGORY)
        self._apply_slot()

    # Which categories offer "+ Variant", and (when not None) WHICH of their
    # leaf subcategories do. A product call kept in the shell — enemy eras and
    # deco types hold interchangeable art, whereas a building tier's levels
    # (lvl1/2/3) are distinct gameplay steps. Under "map" only Background
    # qualifies: a tile_buildable_v2 would silently break the checkerboard
    # `_b` pairing of the zone kinds. For "ui" every leaf subcategory is a SKIN
    # family (Buttons/Button, Panels/Panel, …) — a variant is another skin.
    _VARIANT_TARGETS = {"enemies": None, "deco": None, "map": {"Background"},
                        "ui": None}
    _DECO_CATEGORY = "deco"

    def _variant_target(self):
        """The leaf child-label a new variant would extend for the current
        selection, or None when adding a variant doesn't apply (unsupported
        category or subcategory, flat subgroup, no selection)."""
        if self._node is None:
            return None
        category_key, group_path = self._node
        if category_key not in self._VARIANT_TARGETS:
            return None
        label = selection.variant_target(
            self.selector.registry, category_key, group_path,
            self.details.subcategory_index())
        allowed = self._VARIANT_TARGETS[category_key]
        if label is None or (allowed is not None and label not in allowed):
            return None
        return label

    def _add_variant_slot(self, category_key, group_path, label):
        """Write ONE new variant slot for a (category, subcategory) and return
        its key. Backgrounds are numbered types rather than `_v<k>` variants —
        they get one legend code each, so 'another variant' IS 'another type'."""
        if category_key == "map":
            new_key = registry_ops.add_background_slot(self._data_dir)
            self._bind_background_code(new_key)
            return new_key
        return registry_ops.add_variant(
            self._data_dir, category_key, group_path, label)

    def _on_add_variant(self):
        """+ Variant: append a slot to the selected enemy era / deco type /
        background family in slots.json, reload every cached registry, and
        reselect the new (last) variant so it's ready to import art onto."""
        label = self._variant_target()
        if label is None:
            return
        category_key, group_path = self._node
        subcat_idx = self.details.subcategory_index()
        try:
            new_key = self._add_variant_slot(category_key, group_path, label)
        except (KeyError, OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Could not add variant: {exc}", 5000)
            return
        self._reload_registries()
        self.palette.reload_registry()
        # rebuild the subcategory dropdown against the fresh registry, keep the
        # subcategory, then rebuild the level bar and land on the new variant
        self.details.set_context(category_key, group_path)   # signals blocked
        self.details.select_subcategory(subcat_idx)
        self._refresh_levels()
        self.levelbar.select_last()
        message = f"Added variant {new_key}"
        if category_key == "map" and self.map_session.doc is None:
            message += " — open a map and use '+ Level' to make it paintable"
        self.statusBar().showMessage(message, 5000)

    def _on_add_deco_variant(self, type_label):
        """The map palette's '+ Variant': another sprite variant for the deco
        type the Type: combo shows, armed as the new brush."""
        if not type_label:
            return
        try:
            new_slot = registry_ops.add_deco_variant(self._data_dir, type_label)
        except (KeyError, OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Could not add variant: {exc}", 5000)
            return
        self._reload_registries()
        self.palette.reload_registry()
        self.palette.set_mode("decoration")
        self.palette.arm_deco(new_slot)   # switches the Type: combo for us
        self.statusBar().showMessage(f"Added variant {new_slot}", 5000)

    def _reload_registries(self):
        """Refresh the registry every panel caches, after a slots.json edit."""
        self.selector.reload_registry()
        self.details.reload_registry()
        self.viewport.reload_registry()

    def _bind_background_code(self, slot):
        """Claim a legend code for a new background slot in the OPEN map (an
        undoable command) and refresh the palette's level brushes. Returns the
        code, or None when no map is open — the slot then lives in the registry
        only (art can still be imported onto it; it becomes paintable once a
        map's '+ Level' claims a code for it)."""
        if self.map_session.doc is None:
            return None
        code = self.map_session.push_add_background(slot)
        self.palette.set_legend(self.map_session.doc.legend)
        return code

    def _on_add_level(self):
        """+ Level: add a new background tile type — a fresh slot in slots.json
        plus a new legend code in the OPEN map — then reload every registry,
        rebuild the palette, and arm the new background (grey-X until art is
        imported via 'Import Spritesheet…')."""
        if self.map_session.doc is None:
            return
        try:
            new_slot = registry_ops.add_background_slot(self._data_dir)
        except (KeyError, OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Could not add level: {exc}", 5000)
            return
        self._reload_registries()
        self.palette.reload_registry()
        code = self._bind_background_code(new_slot)
        self.palette.set_mode("background")
        self.palette.arm_code(code)
        self.statusBar().showMessage(f"Added background {new_slot}", 5000)

    def _on_add_prop(self):
        """+ Add Prop / + Type: add a new deco TYPE (its own variant family) to
        slots.json, reload, and select it in whichever panel is showing."""
        try:
            label, new_slot = registry_ops.add_deco_prop(self._data_dir)
        except (KeyError, OSError, ValueError) as exc:
            self.statusBar().showMessage(f"Could not add prop: {exc}", 5000)
            return
        self._reload_registries()
        self.palette.reload_registry()
        if self.viewport.in_map_mode():
            self.palette.set_mode("decoration")
            self.palette.arm_deco(new_slot)   # switches the Type: combo for us
        elif self._node is not None:
            category_key, group_path = self._node
            self.details.set_context(category_key, group_path)
            self.details.select_subcategory_label(label)
            self._refresh_levels()
        self.statusBar().showMessage(f"Added prop type {label}", 5000)

    def _apply_slot(self):
        category_key, group_path = self._node
        slot = selection.resolve_slot(
            self.selector.registry, category_key, group_path,
            self.details.subcategory_index(), self.levelbar.level())
        self.viewport.set_preview_slot(slot)
        self.details.set_slot(slot)

    def _on_manifest_changed(self, _slot_key):
        """Import-panel save/clear: assets reload without a restart (ED-42)
        and the tree's ● markers follow (ED-11). Also drives the map
        palette's brush icons, which have their own (draft-free) provider
        and don't otherwise hear about an import made while a non-map node
        is selected."""
        self.viewport.reload_assets()
        self.selector.refresh_markers()
        self.palette.refresh_icons()

    # -- run controls (ED-50/51/52) ------------------------------------------

    def _on_play(self):
        if self.map_session.dirty:
            self.map_session.save()
        try:
            validate_data(self._data_dir)
        except Exception as exc:
            QMessageBox.critical(self, "Play", f"Data validation failed:\n{exc}")
            return
        self.run_controls.play()

    def _on_launched(self, which, started_ok):
        """Play/Playbuild are detached (fire-and-forget, own GUI window) —
        no tracked process, just a one-line console note."""
        label = "game/main.py" if which == "play" else "HowToBeHuman.exe"
        self.console.appendPlainText(
            f"{which}: launched {label} (detached)" if started_ok
            else f"{which}: FAILED to launch {label}")

    def _on_build_started(self, _which):
        self.build_action.setEnabled(False)

    def _on_build_finished(self, _which, _code):
        self.build_action.setEnabled(True)
        self._update_playbuild_enabled(self.run_controls.can_playbuild())

    def _update_playbuild_enabled(self, can_playbuild):
        self.playbuild_action.setEnabled(can_playbuild)
        self.playbuild_action.setToolTip(
            "" if can_playbuild else
            "Run Build first — no dist/HowToBeHuman/HowToBeHuman.exe found")

    # -- spawnclaude (ED-60/61/62, AD-3) -------------------------------------

    def _on_spawnclaude(self):
        """Open the agent launcher. Form specs (data/agent_forms/*.json) are read
        FRESH on every open, so a newly added form needs no editor restart; each
        one opens a form dialog that writes a handoff and dispatches
        `/dispatch <handoff>`. Small tweak and admin dispatch straight from the
        launcher. Everything runs in its own terminal; the editor writes no lock."""
        dialog = SpawnClaudeDialog(
            data_dir=self._data_dir, repo=REPO, parent=self)
        dialog.exec()

    def _on_add_requested(self, form_id):
        """Selector right-click ("Add New X…") → the agent form for that spec.
        Specs are re-read per open (same fresh-load rule as the launcher), so a
        spec an agent just wrote opens without an editor restart."""
        try:
            spec = next((s for s in agent_forms.load_form_specs(self._data_dir)
                         if s["id"] == form_id), None)
            if spec is None:
                self.statusBar().showMessage(f"No form spec {form_id!r}", 5000)
                return
            AgentFormDialog(spec, data_dir=self._data_dir, repo=REPO,
                            parent=self).exec()
        except Exception as exc:                      # noqa: BLE001
            # A raise out of a Qt slot can abort the process; a right-click must
            # never kill the editor. Same guard as spawnclaude._open_form.
            QMessageBox.critical(self, "Cannot open the form", str(exc))

    # -- theme switch --------------------------------------------------------

    def _on_theme_toggled(self, dark):
        self.theme = theme.apply_theme(
            QApplication.instance(), "dark" if dark else "light")
        try:
            theme.save_theme(self._prefs_path, self.theme)
        except OSError as exc:
            self.statusBar().showMessage(
                f"Theme applied but not saved: {exc}", 5000)

    # -- frame drive ---------------------------------------------------------

    def _tick(self):
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now

        self.viewport.render_frame()
        self.frames += 1
        self._fps_window += 1
        self._fps_elapsed += dt

        if self._fps_elapsed >= 1.0:
            fps = self._fps_window / self._fps_elapsed
            cost_ms = self.viewport.last_frame_ms
            self.setWindowTitle(
                f"How To Be Human — editor — {fps:.1f} fps ({cost_ms:.2f} ms/frame)"
            )
            print(f"editor fps: {fps:.1f}  frame_cost_ms: {cost_ms:.2f}")
            self._fps_window = 0
            self._fps_elapsed = 0.0

        if self._max_frames is not None and self.frames >= self._max_frames:
            QApplication.instance().quit()


def main(max_frames=None):
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(max_frames=max_frames)
    window.show()
    app.exec()
    return window.frames


if __name__ == "__main__":
    main()
