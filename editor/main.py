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
import copy
import json
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import shiboken6
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
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

from editor import (
    agent_forms, keybinds, registry_ops, selection, test_report, test_runner,
    theme, theme_ops,
)
from editor.thats_my_producer import show_thats_my_producer
from editor.agent_form_dialog import AgentFormDialog
from editor.map_session import MapSession
from editor.run_controls import RunControls
from editor.settings_dialog import SettingsDialog
from editor.spawnclaude import SpawnClaudeDialog
from editor.ui_screen_session import UIScreenSession, ordered_views
from editor.panels.anchors_panel import AnchorsPanel
from editor.panels.balancing import BalancingPanel
from editor.panels.boss_upgrades import BossUpgradesPanel
from editor.panels.cutscenes import CutscenesPanel
from editor.panels.details import DetailsPanel
from editor.panels.game_theme import GameThemePanel
from editor.panels.level_bar import LevelBar
from editor.panels.map_details import MapDetailsPanel
from editor.panels.master_sheets import MasterSheetsPanel
from editor.panels.palette import PalettePanel
from editor.panels.screen_details import ScreenDetailsPanel
from editor.panels.selector import SelectorPanel
from editor.panels.timeline import TimelinePanel
from editor.panels.tutorial_panel import TutorialPanel
from editor.panels.strings_panel import StringsPanel
from editor.panels.test_run_panel import TestRunPanel
from editor.panels.viewport import ViewportPanel
from editor.panels.vfx_preview import VfxPreviewPanel
from engine import data_io
from engine.render.fonts import configure_fonts
from tools.smoke import validate_data

FRAME_INTERVAL_MS = 16  # ~60fps tick, timer-driven (no busy-spin)
#: UT-2: how long a burst of screen-doc edits settles before the preview is
#: re-recorded. Long enough that a held arrow key or a drag does not spawn a
#: subprocess per event, short enough to read as "it just updates".
_PREVIEW_DEBOUNCE_MS = 300
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "drunken_donuts_logo.png"
PREFS_PATH = REPO / ".editor_prefs.json"


class _TestRunWorker(QObject):
    """Runs ONE `test_runner.TestRun` off the GUI thread (TestRunnerPLAN TR-5).

    The editor's FIRST worker thread. Two rules, and neither is optional:

    1. **A callback in here may do exactly one thing: `emit`.** TR-3 calls
       `on_progress` on THIS thread; touching a QLabel, the panel or the status
       bar from here is a cross-thread widget write, i.e. the classic
       intermittent crash. `MainWindow`'s slots do all the rendering.
    2. **The marshalling is Qt's automatic queued delivery.** These signals are
       connected to `MainWindow` slots with the default `AutoConnection`; since
       the emitter lives on the worker thread and the receiver on the GUI
       thread, Qt queues each emission onto the GUI event loop. Do NOT
       hand-roll it with `QMetaObject.invokeMethod` or `singleShot(0)`, and do
       NOT force `Qt.DirectConnection` (that would run the slot here).

    `shiboken6.isValid(self)` guards every emit — the same guard `RunControls`
    uses for exactly this hazard (a C++ object freed under a live signal).
    """

    progress = Signal(str, int, object, str)  # domain, done, total|None, state
    finished = Signal(object)                 # TR-3 RunResult
    failed = Signal(str)

    def __init__(self, domain=None, factory=None):
        super().__init__()
        self._domain = domain
        self._factory = factory or test_runner.TestRun
        self._run = None

    def run(self):
        try:
            self._run = self._factory(domain=self._domain,
                                      on_progress=self._emit_progress)
            result = self._run.run()
        except Exception as exc:
            if shiboken6.isValid(self):
                self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        if shiboken6.isValid(self):
            self.finished.emit(result)

    def _emit_progress(self, domain, done, total, state):
        if shiboken6.isValid(self):
            self.progress.emit(domain, done, total, state)

    def cancel(self):
        run = self._run
        if run is not None:
            run.cancel()


class MainWindow(QMainWindow):
    def __init__(self, max_frames=None, data_dir=None, prefs_path=None,
                 auto_refresh_layouts=True, preview_renders=None):
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
        self.anchors = AnchorsPanel(data_dir=data_dir)   # ESV-2
        self.levelbar = LevelBar()
        self.palette = PalettePanel(data_dir=data_dir)
        self.map_details = MapDetailsPanel(data_dir=data_dir)
        self.map_session = MapSession(data_dir=data_dir, parent=self)
        self.screen_details = ScreenDetailsPanel(data_dir=data_dir)
        self.screen_session = UIScreenSession(data_dir=data_dir, parent=self)
        self.vfx_preview = VfxPreviewPanel(data_dir=data_dir)
        self.game_theme = GameThemePanel(data_dir=data_dir)  # UH-6: Theme leaf
        self.cutscenes = CutscenesPanel(data_dir=data_dir)  # TU-3: Cutscenes leaf
        self.tutorial_panel = TutorialPanel(data_dir=data_dir)  # TU-4: Tutorial leaf
        self.strings_panel = StringsPanel(data_dir=data_dir)  # Phase C: Strings leaf
        self.timeline = TimelinePanel(data_dir=data_dir)  # TimelinePLAN T5: Timeline leaf
        self.master_sheets = MasterSheetsPanel(data_dir=data_dir)  # MasterSheetColumnsPLAN E5
        self.boss_upgrades = BossUpgradesPanel(data_dir=data_dir)  # BU-5: Bosses leaf
        self._screen_defaults = {}   # cached data/ui/screen_defaults.json (B3)
        self._screen_previews = {}   # cached data/ui/screen_previews.json (UT-2)
        self._preview_dir = None     # UT-2 scratch dir, created on first render
        self._preview_rendered_doc = {}  # the doc the in-flight render draws
        # UH-6/D5 (+ UH-Font-A): configure the engine font cache from
        # data/ui/fonts.json + the active custom font family at boot, same
        # as game/main.py, so screen-mode preview text metrics match the
        # game. Graceful degrade (E-37) — the editor must open on a broken
        # tree; the game's own boot load fails loud instead.
        try:
            configure_fonts(
                theme_ops.load_fonts(self._data_dir),
                font_path=theme_ops.resolve_active_font_path(self._data_dir))
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
        # UT-2: injectable for the same reason auto_refresh_layouts is — the
        # test suite must never spawn a real render subprocess. Defaults to
        # FOLLOWING that flag rather than to True: the two answer the same
        # question ("may this window spawn export subprocesses?"), and every
        # existing test already passes auto_refresh_layouts=False.
        self._preview_renders = (auto_refresh_layouts if preview_renders is None
                                 else preview_renders)
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

        # ESV-2: anchor handles hang off the entity-preview selection, not a
        # new mode — bidirectional sync between the panel's authoritative
        # mapping and the viewport's live drag, mirroring the B4
        # widget_selected pattern below (:154-156).
        self.anchors.mapping_changed.connect(self.viewport.set_anchors)
        self.anchors.anchor_selected.connect(self.viewport.set_selected_anchor)
        self.viewport.anchor_selected.connect(self.anchors.select_anchor)
        self.viewport.anchor_dragged.connect(self.anchors.on_anchor_dragged)
        self.viewport.anchor_drag_finished.connect(self.anchors.on_anchor_drag_finished)

        # tilemap-mode wiring (ED-20): palette state → viewport; picker →
        # palette re-arm; session lifecycle → selector Maps branch
        self.palette.tool_changed.connect(self.viewport.set_tool)
        self.palette.code_armed.connect(self.viewport.arm_code)
        self.palette.deco_armed.connect(self.viewport.arm_deco)
        self.palette.deco_flip_toggled.connect(self.viewport.set_deco_flip)
        self.palette.base_armed.connect(self.viewport.arm_base)
        self.palette.camera_armed.connect(self.viewport.arm_camera)
        self.palette.camera_limit_center_armed.connect(
            self.viewport.arm_camera_limit_center)
        self.palette.start_area_armed.connect(self.viewport.arm_start_area)
        self.palette.tutorial_flute_armed.connect(self.viewport.arm_tutorial_flute)
        self.palette.tutorial_stone_armed.connect(self.viewport.arm_tutorial_stone)
        self.palette.tutorial_unlock_armed.connect(self.viewport.arm_tutorial_unlock)
        self.palette.tutorial_stone_2_armed.connect(
            self.viewport.arm_tutorial_stone_2)
        self.palette.spawn_reserve_armed.connect(self.viewport.arm_spawn_reserve)
        self.palette.reserve_number_changed.connect(
            self.viewport.set_reserve_number)
        self.palette.despawn_armed.connect(self.viewport.arm_despawn)
        self.palette.despawn_number_changed.connect(
            self.viewport.set_despawn_number)
        self.palette.stage_armed.connect(self.viewport.arm_stage)
        self.palette.stage_number_changed.connect(
            self.viewport.set_stage_number)
        self.palette.tile_condition_armed.connect(
            self.viewport.arm_tile_condition)
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
        self.timeline.set_icon_provider(self.viewport.slot_qimage)
        self.viewport.code_picked.connect(self.palette.arm_code)
        self.viewport.reserve_number_picked.connect(
            self.palette.set_reserve_number)
        self.viewport.despawn_number_picked.connect(
            self.palette.set_despawn_number)
        self.viewport.stage_number_picked.connect(
            self.palette.set_stage_number)
        self.viewport.condition_picked.connect(
            self.palette.arm_tile_condition)
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
        # UL-10: the LAYER twin of the line above. One direction only —
        # `screen_details` emits no `layer_selected`, and `select_layer`
        # already blocks the list's own signals, so this cannot loop.
        self.viewport.layer_selected.connect(self.screen_details.select_layer)
        # UL-10: the inspector's preview-state dropdown and the viewport's own
        # float both name ONE state. Both directions are loop-guarded: the
        # viewport's `set_screen_state` early-returns when the name is
        # unchanged, and `sync_layer_state` sets the combo with signals
        # blocked, so neither can bounce the value back.
        self.viewport._state_combo.currentTextChanged.connect(
            self.screen_details.sync_layer_state)
        self.screen_details.layer_state_combo.activated.connect(
            lambda _i: self.viewport.set_screen_state(
                self.screen_details.layer_state_combo.currentData()))

        # ESV-4: vfx preview <-> balancing staging wiring
        self.vfx_preview.set_balancing_panel(self.balancing)
        self.balancing.value_staged.connect(self.vfx_preview.on_balancing_value_staged)
        # VA-7: the panel's roster strip writes slots.json directly (registry
        # edits are structural, not staged values), so the rest of the shell
        # has to re-read it — the DetailsPanel.registry_changed precedent.
        self.vfx_preview.registry_changed.connect(self._reload_registries)

        # Theme wiring (UH-6, D5): the "Theme" leaf -> right_stack; Save ->
        # reconfigure engine.render.fonts in-process + repaint the viewport
        # so previews track the new theme without a restart (chrome theme,
        # editor/theme.py, is untouched by any of this).
        self.selector.theme_selected.connect(self._on_theme_selected)
        self.game_theme.saved.connect(self._on_theme_saved)

        # Cutscenes wiring (TU-3): the "Cutscenes" leaf -> right_stack; reload on
        # entry mirrors Theme's reload-on-entry convention (registry writes are
        # immediate per-action inside the panel, so there is no saved signal here).
        self.selector.cutscenes_selected.connect(self._on_cutscenes_selected)

        # Tutorial wiring (TU-4): the "Tutorial" leaf -> right_stack; reload on
        # entry, the same convention as every other selection-driven panel.
        self.selector.tutorial_selected.connect(self._on_tutorial_selected)
        # Strings wiring (Phase C): the "Strings" leaf -> right_stack. No
        # saved-signal consumer — strings.json is game/ui-owned data with no
        # editor-side reconfigure (the palette.json precedent, see
        # panels/strings_panel.py's module docstring); the game re-reads it
        # at its own next boot.
        self.selector.strings_selected.connect(self._on_strings_selected)
        # Timeline wiring (TimelinePLAN T5): the "Timeline" leaf -> right_stack;
        # reload on entry, the same convention as every other selection-driven
        # panel.
        self.selector.timeline_selected.connect(self._on_timeline_selected)
        # Master Sheets wiring (MasterSheetColumnsPLAN E5): the top-level
        # "Master Sheets" item -> right_stack; reload on entry, the same
        # convention as every other selection-driven panel.
        self.selector.master_sheets_selected.connect(
            self._on_master_sheets_selected)
        # Boss Upgrade Timeline wiring (BossUpgradeTimelinePLAN BU-5): the
        # "Bosses" branch's single leaf -> right_stack; reload on entry, the
        # same convention as every other selection-driven panel.
        self.selector.boss_upgrades_selected.connect(
            self._on_boss_upgrades_selected)

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
        # UT-2: every screen-doc edit re-records the preview against the
        # UNSAVED doc, debounced — `indexChanged` fires on push AND on
        # undo/redo, i.e. exactly the moments the picture goes stale.
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(_PREVIEW_DEBOUNCE_MS)
        self._preview_timer.timeout.connect(self._render_screen_preview)
        self.screen_session.undo_stack.indexChanged.connect(
            self._schedule_preview_render)
        self.run_controls.preview_rendered.connect(self._on_preview_rendered)
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
        self.deco_flip_keybind = loaded["deco_flip"]
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

        self.deco_flip_action = QAction("Deco Mirror Flip", self)
        self.deco_flip_action.setShortcut(QKeySequence(self.deco_flip_keybind))
        self.deco_flip_action.triggered.connect(
            lambda: self.palette.toggle_deco_flip())
        self.addAction(self.deco_flip_action)

        self.settings_action = QAction("Settings", self)
        self.settings_action.setToolTip(
            "Dark mode, undo/redo key swap, tool + brush keybinds")
        agents_toolbar.addAction(self.settings_action)
        self.settings_action.triggered.connect(self._on_settings)

        producer_btn = QPushButton("thats my prod")
        producer_btn.clicked.connect(lambda: show_thats_my_producer(self))
        agents_toolbar.addWidget(producer_btn)

        # TestRunnerPLAN TR-5 (R3): the run window is a POPUP, not a dock, and
        # its button sits immediately after "thats my prod". Pressing it shows
        # the window and starts a FULL run; the editor stays usable meanwhile.
        self.test_run_panel = TestRunPanel(parent=self)
        self.test_run_button = QPushButton("Run tests")
        self.test_run_button.clicked.connect(self._on_show_test_run_panel)
        agents_toolbar.addWidget(self.test_run_button)
        self.test_run_panel.run_requested.connect(self._on_run_tests)
        self._test_thread = None
        self._test_worker = None
        self._test_domain = None   # None == the run in flight is a FULL run

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
        # ESV-2: the asset importer and the anchors panel share index 0 in a
        # small container — indices 1/2 keep their meaning unchanged.
        # ESV-5: the vfx preview joins them as a THIRD child of that same
        # container instead of its own stack page (fixing a pre-existing bug:
        # `_leave_vfx_mode` used to target `self.details`, which was never a
        # stack page at all — a no-op that permanently stranded the importer
        # once a vfx node had ever been selected). A plain QVBoxLayout
        # squeezed the preview's fixed-minimum surface unusably once all
        # three panels could be visible together, so a QSplitter lets the
        # user trade space between them; `right_stack` keeps exactly ONE page
        # for this whole container either way.
        self.details_pane = QWidget()
        details_pane_layout = QVBoxLayout(self.details_pane)
        details_pane_layout.setContentsMargins(0, 0, 0, 0)
        details_pane_splitter = QSplitter(Qt.Orientation.Vertical)
        details_pane_splitter.addWidget(self.details)
        details_pane_splitter.addWidget(self.anchors)
        details_pane_splitter.addWidget(self.vfx_preview)
        details_pane_splitter.setStretchFactor(0, 1)
        details_pane_splitter.setStretchFactor(1, 0)
        details_pane_splitter.setStretchFactor(2, 1)
        details_pane_layout.addWidget(details_pane_splitter)
        self.vfx_preview.setVisible(False)   # ESV-5: hidden outside vfx mode
        self.right_stack.addWidget(self.details_pane)     # index 0: asset import (+ anchors, ESV-2; + vfx preview, ESV-5)
        self.right_stack.addWidget(self.map_details)     # index 1: map lifecycle
        self.right_stack.addWidget(self.screen_details)  # index 2: screen mode (B4)
        self.right_stack.addWidget(self.game_theme)      # index 3: Theme (UH-6)
        self.right_stack.addWidget(self.cutscenes)       # index 4: Cutscenes (TU-3)
        self.right_stack.addWidget(self.tutorial_panel)  # index 5: Tutorial (TU-4)
        self.right_stack.addWidget(self.strings_panel)   # index 6: Strings (Phase C)
        self.right_stack.addWidget(self.timeline)        # index 7: Timeline (TimelinePLAN T5)
        self.right_stack.addWidget(self.master_sheets)   # index 8: Master Sheets (MasterSheetColumnsPLAN E5)
        self.right_stack.addWidget(self.boss_upgrades)   # index 9: Boss Upgrade Timeline (BossUpgradeTimelinePLAN BU-5)

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
        if category_key == "vfx":
            self._enter_vfx_mode()
        else:
            self._leave_vfx_mode()

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
        self.anchors.set_slot(None)   # ESV-2: a stale slot's rows don't live on
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
        self.right_stack.setCurrentWidget(self.details_pane)

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
        self._screen_previews = self._load_screen_previews()
        self.viewport.set_screen_mode(self.screen_session, self._screen_defaults,
                                      self._screen_previews)
        self.screen_details.set_defaults(self._screen_defaults)
        self.anchors.set_slot(None)   # ESV-2: a stale slot's rows don't live on
        self.right_stack.setCurrentWidget(self.screen_details)
        # UT-2: the COMMITTED preview is recorded override-free, so a screen
        # whose saved doc carries overrides opens out of sync (widgets drawn
        # over their recorded selves). One re-record on entry settles it; a
        # screen with an empty doc is already in sync and needs none.
        if self.screen_session.doc:
            self._schedule_preview_render()

    def _leave_screen_mode(self):
        # the session keeps its (possibly dirty) doc — reselecting the same
        # screen returns to it; the prompt only guards opening a DIFFERENT one
        if self.viewport.in_screen_mode():
            self.viewport.set_screen_mode(None)
        self.right_stack.setCurrentWidget(self.details_pane)
        self._screen_mode_entered = False

    def _load_screen_defaults(self):
        """data/ui/screen_defaults.json (B3's exporter output). Missing or
        invalid → {} — screen mode's own E-37 graceful-degrade path handles
        that (a placeholder message, never a raise)."""
        return self._load_generated_ui_doc("screen_defaults")

    def _load_screen_previews(self):
        """data/ui/screen_previews.json (UT-2's recorded draw list). Same
        degrade-to-{} contract as the defaults: a screen with no preview falls
        back to the flat-box rendering, which is exactly the pre-UT-2 look."""
        return self._load_generated_ui_doc("screen_previews")

    # -- UT-2: live screen-preview re-record -------------------------------

    def _schedule_preview_render(self, *_args):
        """Debounce a re-record. Dragging a widget pushes one command per
        release and the spinboxes one per commit, but a designer holding an
        arrow key can fire many — one subprocess per keypress would thrash,
        and only the last doc is worth drawing."""
        if not self._preview_renders or not self.viewport.in_screen_mode():
            return
        self._preview_timer.start()

    def _render_screen_preview(self):
        """Write the open (unsaved) doc to a temp file and have the exporter
        re-record this screen's draw list against it.

        The doc goes out as `{screen_id: doc}` — the same shape
        `ScreenSkinning.from_overrides` takes — so the recorded picture is
        what the GAME would draw with these overrides, not an editor
        approximation of them.
        """
        session = self.screen_session
        if session.doc is None:
            return
        tmp = self._preview_tmpdir()
        overrides = tmp / "overrides.json"
        out = tmp / "screen_previews.json"
        try:
            overrides.write_text(
                json.dumps({session.screen_id: session.doc}), encoding="utf-8")
        except OSError:
            return      # a temp dir we cannot write is not worth a crash
        # Snapshot WHAT we are rendering, not what the doc says when the
        # render finishes — a second edit mid-render must not be mistaken for
        # "already drawn" (viewport._preview_in_sync).
        self._preview_rendered_doc = copy.deepcopy(session.doc)
        self.run_controls.render_preview(overrides, out)

    def _preview_tmpdir(self):
        if self._preview_dir is None:
            self._preview_dir = Path(tempfile.mkdtemp(prefix="htbh-preview-"))
        return self._preview_dir

    def _on_preview_rendered(self, code):
        """The re-record finished. A non-zero exit leaves the previous picture
        up rather than blanking the viewport — a screen mid-edit can be
        momentarily unrenderable, and flashing to empty boxes is worse than a
        frame of stale geometry."""
        if code != 0 or self._preview_dir is None:
            return
        out = self._preview_dir / "screen_previews.json"
        if not out.exists():
            return
        try:
            doc = data_io.load_validated(
                out, self._data_dir / "schemas" / "screen_previews.schema.json")
        except Exception:   # noqa: BLE001 - a bad render degrades, never raises
            return
        self._screen_previews = doc
        self.viewport.refresh_screen_previews(
            doc, recorded_doc=self._preview_rendered_doc)

    def _load_generated_ui_doc(self, stem):
        path = self._data_dir / "ui" / f"{stem}.json"
        schema = self._data_dir / "schemas" / f"{stem}.schema.json"
        if not path.exists():
            return {}
        try:
            return data_io.load_validated(path, schema)
        except Exception:   # noqa: BLE001 - a bad file degrades, never raises
            return {}

    # -- vfx preview mode (ESV-4): a "vfx" tree node selected ----------------

    def _enter_vfx_mode(self):
        self.right_stack.setCurrentWidget(self.details_pane)
        self.vfx_preview.setVisible(True)

    def _leave_vfx_mode(self):
        # the other `_leave_*` handlers already own the stack page (and
        # `_on_node_selected` calls them before this branch runs), so no
        # `right_stack` call is needed here at all — just hide the preview.
        self.vfx_preview.setVisible(False)

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
            self._screen_previews = self._load_screen_previews()
            self.viewport.refresh_screen_defaults(self._screen_defaults)
            self.viewport.refresh_screen_previews(self._screen_previews)
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
    # "vfx" joined in VfxAuthoringPLAN VA-6, and it is the deco/conditions case
    # exactly: each effect's leaf group holds interchangeable art the game
    # rolls between per spawn (random) or indexes by the source's tier/era.
    # It could not be listed before VA-1 restructured that category — the vfx
    # Effects group was FLAT, so `selection.variant_target()` returned None and
    # "+ Variant" would have been a dead button.
    _VARIANT_TARGETS = {"enemies": None, "deco": None, "map": {"Background"},
                        "ui": None, "conditions": None, "vfx": None}
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
        self.anchors.set_slot(slot)

    def _on_manifest_changed(self, _slot_key):
        """Import-panel save/clear: assets reload without a restart (ED-42)
        and the tree's ● markers follow (ED-11). Also drives the map
        palette's brush icons, which have their own (draft-free) provider
        and don't otherwise hear about an import made while a non-map node
        is selected."""
        self.viewport.reload_assets()
        self.selector.refresh_markers()
        self.palette.refresh_icons()
        self.anchors.reload()   # ESV-2: a DetailsPanel save/clear must not
        # leave the anchors panel (or its handle) stale relative to disk.
        # VA-7 follow-up: the vfx preview owns its OWN AssetStore, built at
        # construction, so art imported through the tree's importer never
        # reached it — the preview kept drawing the procedural fallback for a
        # slot that HAD art, which reads as "binding the sprite did nothing".
        # Its own Import button already called this; a save from anywhere else
        # has to as well.
        self.vfx_preview.reload_assets()

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

    # -- the test-run window (TestRunnerPLAN TR-5) -------------------------
    #
    # The shell owns the THREAD; the panel owns the VIEW and the in-flight
    # warning. `_on_test_*` are the only callers of `TestRunPanel.apply_*`, and
    # they run on the GUI thread because Qt queues the worker's signals onto it.

    def _on_show_test_run_panel(self):
        """The "Run tests" toolbar button: pop the window up and start a FULL
        run. Non-modal — the editor stays usable while the run goes."""
        self.test_run_panel.show()
        self.test_run_panel.raise_()
        self.test_run_panel.activateWindow()
        self.test_run_panel.request_run(None)

    def _on_run_tests(self, domain):
        """`TestRunPanel.run_requested` → one worker thread. A second run while
        one is in flight is REFUSED, not queued (the RunControls rule)."""
        if self._test_thread is not None:
            self.statusBar().showMessage("A test run is already in flight", 5000)
            return
        try:
            self._test_domain = domain
            # TR-6: the tree as it is BEFORE the run. `test_report` compares it
            # against the tree at finish and credits the run in the guard's
            # ledger only if they match; None just means "not credited".
            self._test_fingerprint = test_report.run_start_fingerprint()
            self.test_run_panel.begin_run(domain)
            worker = _TestRunWorker(domain)
            thread = QThread(self)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.progress.connect(self._on_test_progress)
            worker.finished.connect(self._on_test_finished)
            worker.failed.connect(self._on_test_failed)
            self._test_worker = worker
            self._test_thread = thread
            thread.start()
        except Exception as exc:   # never raise out of a Qt slot
            self._stop_test_thread()
            self.test_run_panel.apply_failed(str(exc))

    def _on_test_progress(self, domain, done, total, state):
        self.test_run_panel.apply_progress(domain, done, total, state)

    def _on_test_finished(self, result):
        self._stop_test_thread()
        report_path = None
        try:
            report_path = test_report.write_report(
                result,
                started_fingerprint=getattr(self, "_test_fingerprint", None))
        except Exception as exc:
            self.statusBar().showMessage(f"Report not written: {exc}", 8000)
        # Ledger credit for this run is TR-6's, and it hooks into
        # editor/test_report.py (reconciliation R5.2) — NOT here. It gates on a
        # COMPLETED full run with a parsed verdict; a cancelled run and a
        # per-area re-run (`self._test_domain is not None`) record nothing. The
        # only thing the shell contributes is the start fingerprint above.
        self.test_run_panel.apply_finished(result, report_path)

    def _on_test_failed(self, message):
        self._stop_test_thread()
        self.test_run_panel.apply_failed(message)

    def _stop_test_thread(self, cancel=False):
        """Join and drop the worker thread. Safe to call with none running."""
        worker, thread = self._test_worker, self._test_thread
        self._test_worker = self._test_thread = None
        if worker is not None and cancel:
            try:
                worker.cancel()
            except Exception:
                pass
        if thread is not None:
            thread.quit()
            thread.wait(5000)

    def closeEvent(self, event):
        """A live QThread whose QObjects are being deleted is the "Signal source
        has been deleted" class of crash — join it before the window goes."""
        self._stop_test_thread(cancel=True)
        super().closeEvent(event)

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
                self.undo_redo_swapped, self.deco_flip_keybind)
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

    def _on_deco_flip_keybind_changed(self, key):
        self.deco_flip_keybind = key
        self.deco_flip_action.setShortcut(QKeySequence(key))
        self._save_keybinds()

    def _build_settings_dialog(self):
        """Built (and its signals wired) without exec()ing it, so tests can
        drive the dialog's widgets without blocking on a modal event loop."""
        dialog = SettingsDialog(
            theme=self.theme,
            tool_keybinds=self.tool_keybinds,
            brush_keybinds=[self.brush_keybinds[s] for s in keybinds.BRUSH_SLOTS],
            undo_redo_swapped=self.undo_redo_swapped,
            deco_flip_keybind=self.deco_flip_keybind,
            parent=self)
        dialog.theme_toggled.connect(self._on_theme_toggled)
        dialog.tool_keybind_changed.connect(self._on_tool_keybind_changed)
        dialog.brush_keybind_changed.connect(self._on_brush_keybind_changed)
        dialog.undo_redo_swap_changed.connect(self._on_undo_redo_swap_changed)
        dialog.deco_flip_keybind_changed.connect(
            self._on_deco_flip_keybind_changed)
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
        screen-mode preview TEXT tracks the new sizes/font family
        immediately, then repaint — chrome theme (editor/theme.py) is
        untouched by any of this. Palette edits have no separate editor-side
        consumer to reconfigure (game/ui.widgets is game-only — off limits
        to the editor, ED layering rule); the game re-reads palette.json at
        its own next boot. Graceful degrade mirrors the boot-time load
        above (UH-Font-A: `resolve_active_font_path` degrades to None)."""
        try:
            configure_fonts(
                theme_ops.load_fonts(self._data_dir),
                font_path=theme_ops.resolve_active_font_path(self._data_dir))
        except Exception:
            pass
        self.viewport.render_frame()

    # -- Cutscenes panel (TU-3) ------------------------------------------------

    def _on_cutscenes_selected(self):
        """The selector's Cutscenes leaf: reload the registry fresh (same
        reload-on-entry convention as Theme) and show the panel."""
        self.cutscenes.set_registry()
        self.right_stack.setCurrentWidget(self.cutscenes)

    # -- Tutorial panel (TU-4) -------------------------------------------------

    def _on_tutorial_selected(self):
        """The selector's Tutorial leaf: reload fresh from disk (a designer
        may have hand-edited nothing, but this mirrors every other
        selection-driven panel's reload-on-entry convention) and show the
        panel."""
        self.tutorial_panel.set_tutorial()
        self.right_stack.setCurrentWidget(self.tutorial_panel)
    # -- Strings panel (Phase C) -----------------------------------------------

    def _on_strings_selected(self):
        """The selector's Strings leaf: reload the doc fresh (mirrors every
        other selection-driven panel's "reload on entry" convention) and
        show the panel. No saved-signal handler: strings.json has no
        editor-side render consumer to reconfigure (game/ui/strings is
        game-only, off limits to the editor) — see
        panels/strings_panel.py's module docstring."""
        self.strings_panel.set_strings()
        self.right_stack.setCurrentWidget(self.strings_panel)

    # -- Timeline panel (TimelinePLAN T5) --------------------------------------

    def _on_timeline_selected(self):
        """The selector's Timeline leaf: reload fresh from disk (mirrors
        every other selection-driven panel's "reload on entry" convention)
        and show the panel. No saved-signal consumer — progression.json has
        no editor-side render to reconfigure (the strings.json precedent);
        the game re-reads it at its own next boot."""
        self.timeline.set_timeline()
        self.right_stack.setCurrentWidget(self.timeline)

    # -- Master Sheets panel (MasterSheetColumnsPLAN E5) -----------------------

    def _on_master_sheets_selected(self):
        """The selector's Master Sheets item (a TOP-LEVEL item, D9): reload the
        registry fresh from disk — the "reload on entry" convention every other
        selection-driven panel follows — and show the panel."""
        self.master_sheets.reload_sheets()
        self.right_stack.setCurrentWidget(self.master_sheets)

    # -- Boss Upgrade Timeline panel (BossUpgradeTimelinePLAN BU-5) ------------

    def _on_boss_upgrades_selected(self):
        """The selector's Boss Upgrade Timeline leaf (under the top-level
        "Bosses" branch, D11): reload fresh from disk — the "reload on entry"
        convention every other selection-driven panel follows — and show the
        panel. No saved-signal consumer: boss_upgrades.json has no editor-side
        render to reconfigure (the Timeline/strings.json precedent); the game
        re-reads it at its own next boot."""
        self.boss_upgrades.set_boss_upgrades()
        self.right_stack.setCurrentWidget(self.boss_upgrades)

    # -- frame drive ---------------------------------------------------------

    def _tick(self):
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now

        self.viewport.render_frame()
        if self.vfx_preview.isVisible():
            self.vfx_preview.render_frame()
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
