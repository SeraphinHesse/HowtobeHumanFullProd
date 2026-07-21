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
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from editor import agent_forms, keybinds, registry_ops, selection, theme, theme_ops
from editor.thats_my_producer import show_thats_my_producer
from editor.agent_form_dialog import AgentFormDialog
from editor.map_session import MapSession
from editor.run_controls import RunControls
from editor.settings_dialog import SettingsDialog
from editor.spawnclaude import SpawnClaudeDialog
from editor.ui_screen_session import UIScreenSession, ordered_views
from editor.panels.balancing import BalancingPanel
from editor.panels.details import DetailsPanel
from editor.panels.game_theme import GameThemePanel
from editor.panels.level_bar import LevelBar
from editor.panels.map_details import MapDetailsPanel
from editor.panels.palette import PalettePanel
from editor.panels.screen_details import ScreenDetailsPanel
from editor.panels.selector import SelectorPanel
from editor.panels.viewport import ViewportPanel
from engine import data_io
from engine.render.fonts import configure_fonts
from tools.smoke import validate_data

FRAME_INTERVAL_MS = 16  # ~60fps tick, timer-driven (no busy-spin)
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "drunken_donuts_logo.png"
PREFS_PATH = REPO / ".editor_prefs.json"


class MainWindow(QMainWindow):
    def __init__(self, max_frames=None, data_dir=None, prefs_path=None,
                 auto_refresh_layouts=True):
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
        self.screen_details = ScreenDetailsPanel(data_dir=data_dir)
        self.screen_session = UIScreenSession(data_dir=data_dir, parent=self)
        self.game_theme = GameThemePanel(data_dir=data_dir)  # UH-6: Theme leaf
        self._screen_defaults = {}   # cached data/ui/screen_defaults.json (B3)
        # UH-6/D5: configure the engine font cache from data/ui/fonts.json at
        # boot, same as game/main.py, so screen-mode preview text metrics
        # match the game. Graceful {} degrade (E-37) — the editor must open
        # on a broken tree; the game's own boot load fails loud instead.
        try:
            configure_fonts(theme_ops.load_fonts(self._data_dir))
        except Exception:
            pass
        self._node = None   # (category_key, group_path) of the tree selection
        # dirty policy when opening a DIFFERENT map/screen over unsaved edits:
        # "ask" (QMessageBox Save/Discard/Cancel) | "save" | "discard"
        self.dirty_policy = "ask"
        # UH-2: auto-run Refresh Layouts once per screen-mode entry (never on
        # a view/screen switch while already in screen mode). Injectable so
        # tests never spawn a real subprocess.
        self._auto_refresh_layouts = auto_refresh_layouts
        self._screen_mode_entered = False

        self.selector.domain_selected.connect(self.balancing.set_domain)
        self.selector.node_selected.connect(self._on_node_selected)
        self.selector.map_selected.connect(self._on_map_selected)
        self.selector.screen_selected.connect(self._on_screen_selected)
        self.selector.screen_view_selected.connect(self._on_screen_view_selected)
        self.selector.add_requested.connect(self._on_add_requested)
        self.details.subcategory_changed.connect(self._on_subcategory_changed)
        self.levelbar.level_changed.connect(self._on_level_changed)
        self.levelbar.add_variant_requested.connect(self._on_add_variant)
        self.levelbar.add_type_requested.connect(self._on_add_type)
        self.details.draft_changed.connect(self.viewport.set_preview_draft)
        self.details.entry_saved.connect(self._on_manifest_changed)
        self.details.entry_cleared.connect(self._on_manifest_changed)
        # A frame-size override is a slots.json write: every panel's cached
        # registry has to re-read it, exactly like the + Variant writes do.
        self.details.registry_changed.connect(lambda _slot: self._reload_registries())

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
        self.palette.background_slot_armed.connect(
            self._on_background_slot_armed)
        self.palette.set_icon_provider(self.viewport.slot_qimage)
        self.viewport.code_picked.connect(self.palette.arm_code)
        self.viewport.cursor_world.connect(self._on_cursor_world)
        self.map_session.map_opened.connect(self._on_session_map_opened)
        self.map_session.active_changed.connect(
            lambda _map_id: self.selector.refresh_maps())
        self.map_details.set_session(self.map_session)
        self.map_details.dirty_resolver = self._resolve_dirty
        self.map_details.map_deleted.connect(self._on_map_deleted)

        # screen-mode wiring (B4, R3): session lifecycle → screen_details;
        # widget selection is bidirectional (viewport click <-> list click),
        # each side syncing the OTHER without re-emitting (no feedback loop)
        self.screen_details.set_session(self.screen_session)
        self.screen_details.widget_selected.connect(self.viewport.set_selected_widget)
        self.viewport.widget_selected.connect(self.screen_details.select_widget)

        # Theme wiring (UH-6, D5): the "Theme" leaf -> right_stack; Save ->
        # reconfigure engine.render.fonts in-process + repaint the viewport
        # so previews track the new theme without a restart (chrome theme,
        # editor/theme.py, is untouched by any of this).
        self.selector.theme_selected.connect(self._on_theme_selected)
        self.game_theme.saved.connect(self._on_theme_saved)

        # ED-24: THE global undo stack, Ctrl+Z / Ctrl+Y everywhere (order
        # swappable from Settings — _apply_undo_redo_shortcuts sets the
        # actual shortcuts once undo_redo_swapped loads, below). Routes to
        # whichever session is active (map or screen mode, B4).
        self.undo_action = QAction("Undo", self)
        self.undo_action.triggered.connect(self._on_undo)
        self.redo_action = QAction("Redo", self)
        self.redo_action.triggered.connect(self._on_redo)
        self.addAction(self.undo_action)
        self.addAction(self.redo_action)

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
        # B4: re-runs tools/export_ui_layouts.py (B3) — same tracked-QProcess
        # console-streaming path as Build, distinguished by the `which` string.
        self.refresh_layouts_action = QAction("Refresh Layouts", self)
        run_toolbar.addAction(self.play_action)
        run_toolbar.addAction(self.build_action)
        run_toolbar.addAction(self.playbuild_action)
        run_toolbar.addAction(self.refresh_layouts_action)

        self.play_action.triggered.connect(self._on_play)
        self.build_action.triggered.connect(self.run_controls.build)
        self.playbuild_action.triggered.connect(self.run_controls.playbuild)
        self.refresh_layouts_action.triggered.connect(self._on_refresh_layouts)
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

        # Chrome theme + keybinds, next to the summon button. Theme is chrome
        # only — the viewport still draws through engine/render (ED-22).
        agents_toolbar.addSeparator()
        self.theme = theme.load_theme(self._prefs_path)
        theme.apply_theme(QApplication.instance(), self.theme)

        loaded = keybinds.load_keybinds(self._prefs_path)
        self.tool_keybinds = loaded["tools"]
        self.brush_keybinds = loaded["brushes"]
        self.undo_redo_swapped = loaded["undo_redo_swapped"]
        self._apply_undo_redo_shortcuts()

        self._tool_actions = {}
        for name in keybinds.TOOL_NAMES:
            action = QAction(name.title(), self)
            action.setShortcut(QKeySequence(self.tool_keybinds[name]))
            action.triggered.connect(
                lambda _=False, n=name: self.palette.set_tool(n))
            self.addAction(action)
            self._tool_actions[name] = action
        self.palette.set_tool_keybinds(self.tool_keybinds)

        self._brush_actions = []
        for i, slot in enumerate(keybinds.BRUSH_SLOTS):
            action = QAction(f"Brush {i + 1}", self)
            action.setShortcut(QKeySequence(self.brush_keybinds[slot]))
            action.triggered.connect(
                lambda _=False, idx=i: self.palette.arm_gametiles_brush_by_index(idx))
            self.addAction(action)
            self._brush_actions.append(action)
        self.palette.set_brush_keybinds(
            [self.brush_keybinds[slot] for slot in keybinds.BRUSH_SLOTS])

        self.settings_action = QAction("Settings", self)
        self.settings_action.setToolTip(
            "Dark mode, undo/redo key swap, tool + brush keybinds")
        agents_toolbar.addAction(self.settings_action)
        self.settings_action.triggered.connect(self._on_settings)

        producer_btn = QPushButton("thats my prod")
        producer_btn.clicked.connect(lambda: show_thats_my_producer(self))
        agents_toolbar.addWidget(producer_btn)

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
        self.right_stack.addWidget(self.details)         # index 0: asset import
        self.right_stack.addWidget(self.map_details)     # index 1: map lifecycle
        self.right_stack.addWidget(self.screen_details)  # index 2: screen mode (B4)
        self.right_stack.addWidget(self.game_theme)      # index 3: Theme (UH-6)

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
        self._leave_screen_mode()
        self._node = (category_key, tuple(group_path))
        self.details.set_context(category_key, group_path)
        self._refresh_levels()

    # -- tilemap mode (ED-20): map node selected -----------------------------

    def _on_map_selected(self, map_id):
        self._leave_screen_mode()
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

    # -- screen mode (B4, R3): a UI-screen leaf selected ---------------------

    def _in_screen_mode(self):
        return self.viewport.in_screen_mode()

    def _on_screen_selected(self, screen_id):
        self._leave_map_mode()
        session = self.screen_session
        if session.doc is not None and session.screen_id == screen_id:
            session.set_view(self._default_view(screen_id))
            self._enter_screen_mode()   # same doc (possibly dirty): keep edits
            return
        if not self._resolve_dirty(session):
            # cancelled: put the selection back on the still-open screen
            self.selector.select_screen(session.screen_id)
            return
        session.open(screen_id)
        session.set_view(self._default_view(screen_id))
        self._enter_screen_mode()

    def _on_screen_view_selected(self, screen_id, view_id):
        # UH-2: a Screens-branch VIEW leaf (a child of a screen leaf) was
        # selected — identical flow to _on_screen_selected, but the view is
        # the one the user picked, not the screen's default.
        self._leave_map_mode()
        session = self.screen_session
        if session.doc is not None and session.screen_id == screen_id:
            session.set_view(view_id)
            self._enter_screen_mode()   # same doc (possibly dirty): keep edits
            return
        if not self._resolve_dirty(session):
            # cancelled: put the selection back on the still-open screen
            self.selector.select_screen(session.screen_id)
            return
        session.open(screen_id)
        session.set_view(view_id)
        self._enter_screen_mode()

    def _default_view(self, screen_id):
        """The view a bare screen-leaf selection opens: the first view in
        game-mode order if the screen has views (D-3's sorted-keys JSON
        would otherwise alphabetize them), else None (the screen's single
        implicit view — every non-building screen)."""
        views = self._load_screen_defaults().get(screen_id, {}).get("views")
        return ordered_views(views)[0] if views else None

    def _enter_screen_mode(self):
        # ED-42: re-read the manifest on every entry, not just after an
        # import-panel save — a designer who ran the asset importer while
        # this editor instance stayed open (or restored data/sprites/
        # asset_manifest.json from another branch) would otherwise see
        # grey-X/flat-rect skins until an editor restart. Cheap: AssetStore
        # loads sheets lazily, so this is just a fresh manifest read + a
        # fresh AssetStore (engine/assets/CLAUDE.md "no cache invalidation").
        self.viewport.reload_assets()
        # UH-2: auto Refresh Layouts ONCE per screen-mode entry (switching
        # screens/views while already in screen mode does not re-run it).
        # Reuses the tracked export_layouts subprocess — its own
        # completion handler (_on_export_layouts_finished) already refreshes
        # the defaults/status bar; a run already in flight silently refuses
        # the auto-call (run_controls' one-tracked-process rule).
        if self._auto_refresh_layouts and not self._screen_mode_entered:
            self.run_controls.export_layouts()
        self._screen_mode_entered = True
        self._screen_defaults = self._load_screen_defaults()
        self.viewport.set_screen_mode(self.screen_session, self._screen_defaults)
        self.screen_details.set_defaults(self._screen_defaults)
        self.right_stack.setCurrentWidget(self.screen_details)

    def _leave_screen_mode(self):
        # the session keeps its (possibly dirty) doc — reselecting the same
        # screen returns to it; the prompt only guards opening a DIFFERENT one
        if self.viewport.in_screen_mode():
            self.viewport.set_screen_mode(None)
        self.right_stack.setCurrentWidget(self.details)
        self._screen_mode_entered = False

    def _load_screen_defaults(self):
        """data/ui/screen_defaults.json (B3's exporter output). Missing or
        invalid → {} — screen mode's own E-37 graceful-degrade path handles
        that (a placeholder message, never a raise)."""
        path = self._data_dir / "ui" / "screen_defaults.json"
        schema = self._data_dir / "schemas" / "screen_defaults.schema.json"
        if not path.exists():
            return {}
        try:
            return data_io.load_validated(path, schema)
        except Exception:   # noqa: BLE001 - a bad file degrades, never raises
            return {}

    def _on_refresh_layouts(self):
        self.run_controls.export_layouts()

    def _on_export_layouts_finished(self, code):
        if code == 0:
            # the exporter subprocess may have run alongside a fresh asset
            # import, or the manifest may simply be stale in this running
            # editor — refresh it the same way _enter_screen_mode does
            # (ED-42) so "Refresh Layouts" also picks up new skins.
            self.viewport.reload_assets()
            self._screen_defaults = self._load_screen_defaults()
            self.viewport.refresh_screen_defaults(self._screen_defaults)
            self.screen_details.set_defaults(self._screen_defaults)
            self.selector.refresh_screens()
            self.statusBar().showMessage("Layouts refreshed", 5000)
        else:
            self.statusBar().showMessage(
                f"Refresh Layouts failed (exit {code}) — see Console", 8000)

    # -- window-level undo/redo (ED-24): routes to whichever session is
    # active — map mode or screen mode (B4) --------------------------------

    def _active_undo_stack(self):
        if self._in_screen_mode():
            return self.screen_session.undo_stack
        return self.map_session.undo_stack

    def _on_undo(self):
        self._active_undo_stack().undo()

    def _on_redo(self):
        self._active_undo_stack().redo()

    def _resolve_dirty(self, session=None):
        """True → proceed (saving first if asked); False → cancel. Defaults
        to the map session (every pre-B4 call site passes no argument);
        screen mode (B4) reuses it by passing self.screen_session."""
        session = session if session is not None else self.map_session
        is_map = session is self.map_session
        if not session.dirty:
            return True
        policy = self.dirty_policy
        if policy == "ask":
            label = session.doc.map_id if is_map else session.screen_id
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"{'Map' if is_map else 'Screen'} {label!r} has unsaved changes.",
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
            can_add_type=category_key == self._DECO_CATEGORY
            or self._node == self._BUTTON_TYPE_NODE)
        self._apply_slot()

    # Which categories offer "+ Variant", and (when not None) WHICH of their
    # leaf subcategories do. A product call kept in the shell — enemy eras and
    # deco types hold interchangeable art, whereas a building tier's levels
    # (lvl1/2/3) are distinct gameplay steps. Under "map" only Background
    # qualifies: a tile_buildable_v2 would silently break the checkerboard
    # `_b` pairing of the zone kinds. For "ui" every leaf subcategory is a SKIN
    # family (Buttons/Button, Panels/Panel, …) — a variant is another skin.
    # "conditions" is the deco case exactly: each condition's leaf group holds
    # interchangeable art the game rolls between per tile.
    _VARIANT_TARGETS = {"enemies": None, "deco": None, "map": {"Background"},
                        "ui": None, "conditions": None}
    _DECO_CATEGORY = "deco"
    # ui -> Buttons is the second "+ Type" target: a brand-new button FAMILY
    # (its own variant family), not another skin of an existing one.
    _BUTTON_TYPE_NODE = ("ui", ("Buttons",))

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
        self.screen_details.reload_registry()

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

    def _on_background_slot_armed(self, slot):
        """A background variant with no legend code in the open map was
        clicked in the palette: claim a code for it (undoable, like '+
        Level' minus creating a new slot) and arm it. No-op with no map
        open."""
        code = self._bind_background_code(slot)
        if code is not None:
            self.palette.arm_code(code)

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

    def _on_add_type(self):
        """Dispatch the LevelBar's '+ Type' button by current selection:
        ui -> Buttons gets a brand-new button FAMILY (its own variant
        family, `_on_add_button_type`); every other '+ Type' target (deco)
        keeps the existing prop-type behavior (`_on_add_prop`)."""
        if self._node == self._BUTTON_TYPE_NODE:
            self._on_add_button_type()
        else:
            self._on_add_prop()

    def _on_add_button_type(self, name=None):
        """+ Type on ui -> Buttons: add a brand-new button FAMILY (a leaf
        child group under Buttons, ready for its own variants) rather than
        another skin of an existing one. ``name=None`` opens the naming
        dialog; passing ``name=`` is the test seam (same philosophy as
        ``dirty_policy`` / injectable ``detach`` elsewhere — tests never
        exec a modal)."""
        if name is None:
            name = self._prompt_button_type_name()
            if name is None:
                return
        try:
            label, new_slot = registry_ops.add_button_family(
                self._data_dir, name)
        except (KeyError, OSError, ValueError) as exc:
            self.statusBar().showMessage(
                f"Could not add button type: {exc}", 5000)
            return
        self._reload_registries()
        self.details.set_context("ui", ("Buttons",))
        self.details.select_subcategory_label(label)
        self._refresh_levels()
        self.statusBar().showMessage(
            f"Added button type {label} ({new_slot})", 5000)

    def _prompt_button_type_name(self):
        """Modal naming dialog for a new button family: a name field that
        live-previews the derived slot key (`registry_ops.button_family_slot`).
        Returns the typed name, or None if cancelled."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Add button type")
        form = QFormLayout(dialog)
        name_edit = QLineEdit(dialog)
        form.addRow("Type name", name_edit)
        preview = QLabel("", dialog)
        form.addRow("Slot key", preview)

        def update_preview(text):
            try:
                preview.setText(registry_ops.button_family_slot(text))
            except ValueError:
                preview.setText("—")

        name_edit.textChanged.connect(update_preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return name_edit.text()

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

    def _on_build_started(self, which):
        # RunControls tracks Build AND Refresh Layouts (B4) through the same
        # one-at-a-time QProcess + signals — only Build owns the toolbar
        # enable/disable + playbuild-availability dance.
        if which == "build":
            self.build_action.setEnabled(False)

    def _on_build_finished(self, which, code):
        if which == "build":
            self.build_action.setEnabled(True)
            self._update_playbuild_enabled(self.run_controls.can_playbuild())
        elif which == "export_layouts":
            self._on_export_layouts_finished(code)

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

    # -- settings (theme + keybinds) -----------------------------------------

    def _on_theme_toggled(self, dark):
        self.theme = theme.apply_theme(
            QApplication.instance(), "dark" if dark else "light")
        try:
            theme.save_theme(self._prefs_path, self.theme)
        except OSError as exc:
            self.statusBar().showMessage(
                f"Theme applied but not saved: {exc}", 5000)

    def _apply_undo_redo_shortcuts(self):
        undo_key, redo_key = ("Ctrl+Y", "Ctrl+Z") if self.undo_redo_swapped \
            else ("Ctrl+Z", "Ctrl+Y")
        self.undo_action.setShortcut(QKeySequence(undo_key))
        self.redo_action.setShortcut(QKeySequence(redo_key))

    def _save_keybinds(self):
        try:
            keybinds.save_keybinds(
                self._prefs_path, self.tool_keybinds, self.brush_keybinds,
                self.undo_redo_swapped)
        except OSError as exc:
            self.statusBar().showMessage(
                f"Keybind applied but not saved: {exc}", 5000)

    def _on_tool_keybind_changed(self, name, key):
        self.tool_keybinds[name] = key
        self._tool_actions[name].setShortcut(QKeySequence(key))
        self.palette.set_tool_keybinds(self.tool_keybinds)
        self._save_keybinds()

    def _on_brush_keybind_changed(self, index, key):
        slot = keybinds.BRUSH_SLOTS[index]
        self.brush_keybinds[slot] = key
        self._brush_actions[index].setShortcut(QKeySequence(key))
        self.palette.set_brush_keybinds(
            [self.brush_keybinds[s] for s in keybinds.BRUSH_SLOTS])
        self._save_keybinds()

    def _on_undo_redo_swap_changed(self, swapped):
        self.undo_redo_swapped = swapped
        self._apply_undo_redo_shortcuts()
        self._save_keybinds()

    def _build_settings_dialog(self):
        """Built (and its signals wired) without exec()ing it, so tests can
        drive the dialog's widgets without blocking on a modal event loop."""
        dialog = SettingsDialog(
            theme=self.theme,
            tool_keybinds=self.tool_keybinds,
            brush_keybinds=[self.brush_keybinds[s] for s in keybinds.BRUSH_SLOTS],
            undo_redo_swapped=self.undo_redo_swapped,
            parent=self)
        dialog.theme_toggled.connect(self._on_theme_toggled)
        dialog.tool_keybind_changed.connect(self._on_tool_keybind_changed)
        dialog.brush_keybind_changed.connect(self._on_brush_keybind_changed)
        dialog.undo_redo_swap_changed.connect(self._on_undo_redo_swap_changed)
        return dialog

    def _on_settings(self):
        self._build_settings_dialog().exec()

    # -- Theme panel (UH-6, D5) -----------------------------------------------

    def _on_theme_selected(self):
        """The selector's Theme leaf: reload both docs fresh (a designer may
        have hand-edited nothing, but this mirrors every other selection-
        driven panel's "reload on entry" convention) and show the panel."""
        self.game_theme.set_theme()
        self.right_stack.setCurrentWidget(self.game_theme)

    def _on_theme_saved(self):
        """Theme panel Save: reconfigure engine.render.fonts in-process so
        screen-mode preview TEXT tracks the new sizes immediately, then
        repaint — chrome theme (editor/theme.py) is untouched by any of
        this. Palette edits have no separate editor-side consumer to
        reconfigure (game/ui.widgets is game-only — off limits to the
        editor, ED layering rule); the game re-reads palette.json at its
        own next boot. Graceful degrade mirrors the boot-time load above."""
        try:
            configure_fonts(theme_ops.load_fonts(self._data_dir))
        except Exception:
            pass
        self.viewport.render_frame()

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
