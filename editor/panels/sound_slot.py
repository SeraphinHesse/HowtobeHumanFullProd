"""SoundSlotWidget (SoundEditorPLAN SD-3) — one composite widget for a schema
node marked ``"x-widget": "sound_slot"``.

The balancing panel is a generic schema-walking form generator; a sound slot is
an OBJECT, so without this it would render as a CollapsibleSection of raw
``clips`` / ``loop`` / ``pick`` rows. The ``x-widget`` marker (which SD-1 put
INSIDE ``$defs/sound_slot``, because ``_build_object`` derefs before inspecting
the node) routes it here instead: a clip list with Import… / Use existing… /
Remove, per-clip volume + in/out trim, the slot's loop + pick, and a ▶ preview.

INVARIANTS THIS MODULE KEEPS

* **No second writer, no second dirty set.** Every edit goes through the panel's
  ``stage_value`` / ``staged_value`` seam (the ``vfx_preview.py`` precedent), so
  the dirty dot, Version History and the one Save button need no special case.
* **Nothing is hardcoded that the schema owns.** Spin ranges/decimals come from
  the node's ``minimum``/``maximum``, the pick combo from its ``enum``, tooltips
  from ``description``. SD-1 owns the bounds; ``start``/``end`` are deliberately
  0-3600 s (music runs minutes), so a constant here would be wrong.
* **No slot inventory anywhere.** No slot name, no domain key and neither
  ``Sounds`` nor ``sounds`` spelling appears in this file — the widget is driven
  by the marker and its own path, so a slot added later needs zero edits here.
* **Preview is QtMultimedia, lazily imported** (``thats_my_producer.py:15-32``).
  ``panels/viewport.py`` sets ``SDL_AUDIODRIVER=dummy`` at module level for the
  whole editor process, so ``pygame.mixer`` in the editor is silent by
  construction and must not be used. QtMultimedia loads the platform audio stack
  ON IMPORT, so a module-scope import would break ``editor.main`` on an
  audio-less box. Unlike the easter egg, SD-3 degrades VISIBLY: the ▶ button is
  built disabled with an explanatory tooltip. The player and its ``QAudioOutput``
  are kept alive on ``self`` — a GC'd ``QMediaPlayer`` stops mid-playback.
* **``end: 0.0`` is the SENTINEL for "play to the end"**, never ``null``: a
  nullable node would break the generic form. The widget never writes ``None``,
  never adds a key and never drops one (all three slot keys are ``required``).
* **Dialog construction is split from display**, so no test calls ``exec()``.

EMPTY CLIPS MEAN DIFFERENT THINGS BY LAYER and the tooltip says so: ``clips: []``
on a GLOBAL default is silence; ``clips: []`` on a per-element OVERRIDE means
inherit the default. A designer not told this misreads an empty override as
"silent".
"""
import copy
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import sound_import
from editor.panels.balancing import (
    _NoWheelComboBox,
    _NoWheelDoubleSpinBox,
)

EMPTY_CLIPS_TOOLTIP = (
    "No clips: on a GLOBAL default this means SILENCE; on a per-element "
    "override it means INHERIT the global default."
)

_PREVIEW_UNAVAILABLE = (
    "Preview unavailable: PySide6's QtMultimedia module could not be loaded "
    "on this machine (no platform audio stack)."
)


def _numpy_available():
    """SD-2 ships in-point trim only when numpy is present, so the start spin is
    greyed without it. A LOCAL probe on purpose — SD-3 never imports numpy at
    runtime and never imports ``engine.audio``; this is the one coupling to
    SD-2's behaviour and it stays expressed as a probe, not an import."""
    try:
        import numpy  # noqa: F401
    except Exception:
        return False
    return True


NUMPY_AVAILABLE = _numpy_available()

_START_DISABLED_TOOLTIP = (
    "In-point trim needs numpy, which is not installed — playback starts at the "
    "beginning of the file until it is."
)


def _prop(schema, *keys):
    """A nested property node out of the slot schema, or ``{}``. Never raises:
    this feeds widget construction inside a Qt slot."""
    node = schema or {}
    for key in keys:
        node = (node.get("properties") or {}).get(key) or {}
    return node


class ClipPickerDialog(QDialog):
    """"Use existing…": reference a clip already in ``data/audio/imported/``
    without copying bytes. ``chosen()`` is the model half (the selected
    ``ImportedClip``, None when nothing is picked) so tests never ``exec()``.

    A row whose usage could not be established is labelled "usage unknown" —
    never "unused". Reporting a clip as free-to-delete because a balancing file
    failed to load is the one failure mode that costs a designer their audio.
    """

    def __init__(self, data_dir, docs=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Use an imported sound clip")
        self.resize(560, 420)
        self._clips = sound_import.imported_clips(data_dir, docs)

        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter by name…")
        self._filter.textChanged.connect(self._refill)

        self._list = QListWidget(self)
        self._list.itemDoubleClicked.connect(lambda _i: self.accept())

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=self)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._filter)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._buttons)
        self._refill()

    def visible_clips(self):
        needle = self._filter.text().strip().lower()
        return [c for c in self._clips if not needle or needle in c.name.lower()]

    def chosen(self):
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _refill(self):
        self._list.clear()
        for clip in self.visible_clips():
            label = f"{clip.name}{clip.path.suffix}   {clip.size // 1024} KB"
            if not clip.usage_known:
                label += "   — usage unknown"
            elif not clip.users:
                label += "   — unused"
            else:
                label += f"   — used in {', '.join(clip.users)}"
            item = QListWidgetItem(label, self._list)
            item.setData(Qt.ItemDataRole.UserRole, clip)
        if self._list.count():
            self._list.setCurrentRow(0)


class SoundSlotWidget(QWidget):
    """One sound slot. Reads/writes the WHOLE slot object through the balancing
    panel's staging seam; holds no document of its own."""

    def __init__(self, slot_value, slot_schema, path, panel, data_dir,
                 parent=None):
        super().__init__(parent)
        self._schema = slot_schema or {}
        self._path = path                       # tuple of segments
        self._key = "/".join(path)
        self._panel = panel
        self._data_dir = Path(data_dir)
        self._value = copy.deepcopy(slot_value)
        self._player = None
        self._audio_output = None
        self._clip_rows = []

        self.setToolTip(EMPTY_CLIPS_TOOLTIP)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._clips_box = QVBoxLayout()
        self._layout.addLayout(self._clips_box)

        self._empty_label = QLabel("No clips — " + EMPTY_CLIPS_TOOLTIP, self)
        self._empty_label.setWordWrap(True)
        self._layout.addWidget(self._empty_label)

        buttons = QHBoxLayout()
        self._import_btn = QPushButton("Import…", self)
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._existing_btn = QPushButton("Use existing…", self)
        self._existing_btn.clicked.connect(self._on_use_existing_clicked)
        buttons.addWidget(self._import_btn)
        buttons.addWidget(self._existing_btn)
        buttons.addStretch(1)
        self._layout.addLayout(buttons)

        slot_form = QFormLayout()
        loop_prop = _prop(self._schema, "loop")
        self._loop = QCheckBox(self)
        self._loop.setToolTip(loop_prop.get("description", ""))
        self._loop.setChecked(bool(self._value.get("loop")))
        self._loop.toggled.connect(self._on_loop_toggled)
        slot_form.addRow("loop", self._loop)

        pick_prop = _prop(self._schema, "pick")
        self._pick = _NoWheelComboBox(self)
        self._pick.setToolTip(pick_prop.get("description", ""))
        for option in pick_prop.get("enum", ()):
            self._pick.addItem(str(option), option)
        self._pick.setCurrentIndex(self._pick.findData(self._value.get("pick")))
        self._pick.currentIndexChanged.connect(self._on_pick_changed)
        slot_form.addRow("pick", self._pick)
        self._layout.addLayout(slot_form)

        self._rebuild_clip_rows()

    # -- staging seam --------------------------------------------------------

    def value(self):
        return copy.deepcopy(self._value)

    def set_slot(self, value):
        """Replace the whole slot (Version History's ``_apply_snapshot`` path,
        via ``BalancingPanel._set_widget_value``). Does NOT re-stage — the panel
        has already staged whatever it is pushing in here."""
        if not isinstance(value, dict):
            return
        self._value = copy.deepcopy(value)
        self._loop.blockSignals(True)
        self._loop.setChecked(bool(self._value.get("loop")))
        self._loop.blockSignals(False)
        self._pick.blockSignals(True)
        self._pick.setCurrentIndex(self._pick.findData(self._value.get("pick")))
        self._pick.blockSignals(False)
        self._rebuild_clip_rows()

    def _stage(self):
        """Push the whole slot object into the panel's staged doc — the ONE
        write path from this widget. ``stage_value`` would push the value back
        into this widget too (we ARE the registered widget for this path), so go
        through the panel's ``_commit`` and let it dirty/emit as usual."""
        self._panel._commit(self._key, copy.deepcopy(self._value))

    # -- clip rows -----------------------------------------------------------

    def _clips(self):
        clips = self._value.get("clips")
        if not isinstance(clips, list):
            clips = []
            self._value["clips"] = clips
        return clips

    def _rebuild_clip_rows(self):
        for row in self._clip_rows:
            self._clips_box.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._clip_rows = []
        for i, clip in enumerate(self._clips()):
            row = self._build_clip_row(i, clip)
            self._clips_box.addWidget(row)
            self._clip_rows.append(row)
        self._empty_label.setVisible(not self._clips())

    def _spin(self, prop, value, on_change, enabled=True, tooltip=""):
        spin = _NoWheelDoubleSpinBox(self)
        spin.setRange(float(prop.get("minimum", 0.0)),
                      float(prop.get("maximum", 1e9)))
        spin.setDecimals(3)
        spin.setSingleStep(0.1)
        spin.setValue(float(value or 0.0))
        spin.setToolTip(tooltip or prop.get("description", ""))
        spin.setEnabled(enabled)
        spin.valueChanged.connect(on_change)
        return spin

    def _build_clip_row(self, index, clip):
        clip_schema = _prop(self._schema, "clips").get("items") or {}
        # `clips.items` is a `$ref` into the same schema's $defs; the panel
        # derefs the SLOT for us, so resolve the clip node through the panel's
        # one resolver rather than re-implementing $ref handling here.
        try:
            clip_schema = self._panel._deref(clip_schema)
        except (AttributeError, KeyError, ValueError):
            clip_schema = clip_schema if isinstance(clip_schema, dict) else {}

        row = QFrame(self)
        row.setObjectName(f"soundclip:{self._key}/{index}")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        name = QLabel(str(clip.get("file", "")) or "(no file)", row)
        name.setToolTip(_prop(clip_schema, "file").get("description", ""))
        layout.addWidget(name, 1)

        layout.addWidget(QLabel("vol", row))
        layout.addWidget(self._spin(
            _prop(clip_schema, "volume"), clip.get("volume", 1.0),
            lambda v, i=index: self._on_clip_field(i, "volume", float(v))))

        layout.addWidget(QLabel("in", row))
        start_spin = self._spin(
            _prop(clip_schema, "start"), clip.get("start", 0.0),
            lambda v, i=index: self._on_clip_field(i, "start", float(v)),
            enabled=NUMPY_AVAILABLE,
            tooltip=None if NUMPY_AVAILABLE else _START_DISABLED_TOOLTIP)
        layout.addWidget(start_spin)

        layout.addWidget(QLabel("out", row))
        layout.addWidget(self._spin(
            _prop(clip_schema, "end"), clip.get("end", 0.0),
            lambda v, i=index: self._on_clip_field(i, "end", float(v))))

        preview = QPushButton("▶", row)
        preview.setObjectName(f"soundpreview:{self._key}/{index}")
        preview.setFixedWidth(28)
        if _multimedia_available():
            preview.setToolTip("Preview this clip")
            preview.clicked.connect(lambda _c=False, i=index: self._preview(i))
        else:
            preview.setEnabled(False)
            preview.setToolTip(_PREVIEW_UNAVAILABLE)
        layout.addWidget(preview)

        remove = QPushButton("−", row)
        remove.setObjectName(f"soundremove:{self._key}/{index}")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove this clip from the slot (the file stays on disk)")
        remove.clicked.connect(lambda _c=False, i=index: self.remove_clip(i))
        layout.addWidget(remove)
        return row

    # -- edits ---------------------------------------------------------------

    def _on_loop_toggled(self, checked):
        self._value["loop"] = bool(checked)
        self._stage()

    def _on_pick_changed(self, _index):
        data = self._pick.currentData()
        if data is None:
            return
        self._value["pick"] = data
        self._stage()

    def _on_clip_field(self, index, field, value):
        clips = self._clips()
        if not 0 <= index < len(clips):
            return
        clips[index][field] = value
        self._stage()

    def add_clip(self, ref):
        """Append a clip referencing ``ref``. Every key is written (all four are
        ``required``), defaults straight from the schema's own minima where the
        schema has an opinion, ``end: 0.0`` meaning "play to the end"."""
        clip_schema = _prop(self._schema, "clips").get("items") or {}
        try:
            clip_schema = self._panel._deref(clip_schema)
        except (AttributeError, KeyError, ValueError):
            pass
        max_vol = float(_prop(clip_schema, "volume").get("maximum", 1.0))
        self._clips().append(
            {"file": ref, "volume": max_vol, "start": 0.0, "end": 0.0})
        self._stage()
        self._rebuild_clip_rows()

    def remove_clip(self, index):
        clips = self._clips()
        if not 0 <= index < len(clips):
            return
        clips.pop(index)
        self._stage()
        self._rebuild_clip_rows()

    # -- import / reuse ------------------------------------------------------

    def import_dialog(self):
        """Constructed, not shown — the split that keeps ``exec()`` out of
        tests (the ``sheet_picker`` / ``master_sheet_dialog`` precedent)."""
        patterns = " ".join(f"*{s}" for s in sound_import.AUDIO_SUFFIXES)
        dialog = QFileDialog(self, "Import a sound clip")
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter(f"Audio ({patterns})")
        return dialog

    def _on_import_clicked(self):
        dialog = self.import_dialog()
        if dialog.exec() != QDialog.Accepted:
            return
        files = dialog.selectedFiles()
        if not files:
            return
        self.import_path(files[0])

    def import_path(self, src, transcode=False):
        """Copy ``src`` in and attach it. The testable half of Import…"""
        if sound_import.warn_oversize(src):
            answer = QMessageBox.question(
                self, "Large audio file",
                f"{Path(src).name} is "
                f"{Path(src).stat().st_size // (1024 * 1024)} MB. Imported clips "
                "are committed to the repository. Import it anyway?")
            if answer != QMessageBox.StandardButton.Yes:
                return None
        try:
            ref = sound_import.import_clip(
                self._data_dir, src,
                transcode=transcode and sound_import.transcode_available())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return None
        self.add_clip(ref)
        return ref

    def picker_dialog(self):
        """The "Use existing…" dialog, constructed but not shown. The docs come
        from the PANEL (``sound_usage_docs``) — the one cross-domain loading
        site; this widget never touches ``data/`` itself."""
        docs = None
        try:
            docs = self._panel.sound_usage_docs()
        except Exception:
            docs = None
        return ClipPickerDialog(self._data_dir, docs, self)

    def _on_use_existing_clicked(self):
        dialog = self.picker_dialog()
        if dialog.exec() != QDialog.Accepted:
            return
        clip = dialog.chosen()
        if clip is not None:
            self.add_clip(clip.ref)

    # -- preview -------------------------------------------------------------

    def _preview(self, index):
        """Play the clip at ``index``. Volume and start-trim are applied on a
        best-effort basis: a preview that ignores trim is acceptable, one that
        raises is not — this runs inside a Qt slot."""
        clips = self._clips()
        if not 0 <= index < len(clips):
            return
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except ImportError:
            return
        clip = clips[index]
        path = sound_import.clip_path(self._data_dir, clip.get("file", ""))
        if path is None or not Path(path).exists():
            return
        try:
            player = QMediaPlayer(self)
            audio_output = QAudioOutput(self)
            audio_output.setVolume(float(clip.get("volume", 1.0)))
            player.setAudioOutput(audio_output)
            player.setSource(QUrl.fromLocalFile(str(path)))
            start = float(clip.get("start", 0.0))
            if start > 0:
                player.setPosition(int(start * 1000))
            player.play()
        except Exception:
            return
        # Keep both alive on self — a GC'd QMediaPlayer/QAudioOutput stops
        # mid-playback (thats_my_producer.py:30-32).
        self._player = player
        self._audio_output = audio_output


def _multimedia_available():
    """Whether preview can work at all. Lazy by the same argument as the import
    inside ``_preview``: QtMultimedia loads the platform audio stack on import,
    so this is only ever called while a widget is being built, never at module
    scope."""
    try:
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer  # noqa: F401
    except Exception:
        return False
    return True
