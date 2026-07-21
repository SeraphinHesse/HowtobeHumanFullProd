"""CutscenesPanel (TU-3) — the right-pane form shown while the "Cutscenes"
leaf (selector ▸ ui ▸ Cutscenes) is selected: one row per
``data/video/cutscenes.json`` registry entry (TU-1), reached the
selection-driven way (ED-3), third child of "ui" (after "Screens" then
"Theme" — the UH-6 ordering invariant).

Unlike ``GameThemePanel`` (UH-6), edits are NOT staged: every action
(import video, import audio, clear audio, commit a length) is an
immediate ``cutscene_import.write_registry_doc`` call — there is no
multi-field form to batch here, and ``write_validated`` failing loud on a
bad write beats a dirty-dot UI for a 4-field row. No add/remove-row
affordance: TU-1 owns which ids exist.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import cutscene_import
from editor.panels.balancing import _NoWheelDoubleSpinBox

REPO = Path(__file__).resolve().parents[2]

_VIDEO_FILTER = "Video files (*.mp4)"
_AUDIO_FILTER = "Audio files (*.ogg *.mp3)"
_NONE_LABEL = "— none —"


class CutscenesPanel(QWidget):
    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._length_bounds = (0.0, 3600.0)
        self._rows = {}   # cutscene_id -> {video_label, audio_label, clear_audio_btn, length_spin}

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addWidget(self._scroll)

        self.set_registry()

    # -- selection drives content (ED-3) -------------------------------------

    def set_registry(self):
        """(Re)load the registry fresh from disk and rebuild the form —
        called on entry (the "Cutscenes" leaf's selection handler) and by
        ``__init__``. Editor-side graceful degrade (E-37): a missing/
        invalid registry shows a placeholder instead of raising out of a
        constructor/Qt slot. The GAME's own boot load fails loud instead;
        TU-1's own smoke-test validation is what keeps the on-disk file
        schema-valid in the first place."""
        try:
            doc = cutscene_import.load_registry_doc(self._data_dir)
            bounds = cutscene_import.length_bounds(self._data_dir)
        except Exception:
            self._doc = None
            self._show_unavailable()
            return
        if not doc:
            self._doc = None
            self._show_unavailable()
            return
        self._doc = doc
        self._length_bounds = bounds
        self._rebuild_form()

    def _show_unavailable(self):
        self._rows = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/video/cutscenes.json is missing or invalid — nothing to "
            "edit here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)

    def _rebuild_form(self):
        self._rows = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        for cutscene_id in cutscene_import.ordered_entry_ids(self._doc):
            row = self._build_row(cutscene_id)
            form.addRow(cutscene_id, row)
        content_layout.addLayout(form)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)

    # -- row builder ------------------------------------------------------

    def _build_row(self, cutscene_id):
        entry = self._doc[cutscene_id]
        lo, hi = self._length_bounds

        trigger_edit = QLineEdit(entry.get("trigger", ""), self)
        trigger_edit.setReadOnly(True)
        trigger_edit.setEnabled(False)

        video_label = QLabel(entry.get("video") or _NONE_LABEL, self)
        import_video_btn = QPushButton("Import MP4…", self)
        import_video_btn.clicked.connect(
            lambda _checked=False, cid=cutscene_id: self._on_import_video(cid))

        audio_label = QLabel(entry.get("audio") or _NONE_LABEL, self)
        import_audio_btn = QPushButton("Import Audio…", self)
        import_audio_btn.clicked.connect(
            lambda _checked=False, cid=cutscene_id: self._on_import_audio(cid))
        clear_audio_btn = QPushButton("Clear Audio", self)
        clear_audio_btn.setEnabled(entry.get("audio") is not None)
        clear_audio_btn.clicked.connect(
            lambda _checked=False, cid=cutscene_id: self._on_clear_audio(cid))

        length_spin = _NoWheelDoubleSpinBox(self)
        length_spin.setDecimals(1)
        length_spin.setRange(lo, hi)
        length_spin.setValue(entry.get("length", lo))
        length_spin.editingFinished.connect(
            lambda cid=cutscene_id: self._on_length_committed(cid))

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QLabel("trigger:", self))
        row_layout.addWidget(trigger_edit)
        row_layout.addWidget(QLabel("video:", self))
        row_layout.addWidget(video_label, 1)
        row_layout.addWidget(import_video_btn)
        row_layout.addWidget(QLabel("audio:", self))
        row_layout.addWidget(audio_label, 1)
        row_layout.addWidget(import_audio_btn)
        row_layout.addWidget(clear_audio_btn)
        row_layout.addWidget(QLabel("length (s):", self))
        row_layout.addWidget(length_spin)

        self._rows[cutscene_id] = {
            "video_label": video_label,
            "audio_label": audio_label,
            "clear_audio_btn": clear_audio_btn,
            "length_spin": length_spin,
        }
        return row

    # -- actions: every one is an immediate write (no staging) -------------

    def _on_import_video(self, cutscene_id):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose cutscene MP4", "", _VIDEO_FILTER)
        if not path:
            return
        filename, length = cutscene_import.import_video(
            self._data_dir, cutscene_id, path)
        self._doc[cutscene_id]["video"] = filename
        rows = self._rows[cutscene_id]
        rows["video_label"].setText(filename)
        if length is not None:
            self._doc[cutscene_id]["length"] = length
            spin = rows["length_spin"]
            spin.blockSignals(True)
            spin.setValue(length)
            spin.blockSignals(False)
        cutscene_import.write_registry_doc(self._data_dir, self._doc)

    def _on_import_audio(self, cutscene_id):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose companion audio", "", _AUDIO_FILTER)
        if not path:
            return
        filename = cutscene_import.import_audio(self._data_dir, cutscene_id, path)
        self._doc[cutscene_id]["audio"] = filename
        rows = self._rows[cutscene_id]
        rows["audio_label"].setText(filename)
        rows["clear_audio_btn"].setEnabled(True)
        cutscene_import.write_registry_doc(self._data_dir, self._doc)

    def _on_clear_audio(self, cutscene_id):
        self._doc = cutscene_import.clear_audio(self._data_dir, cutscene_id, self._doc)
        rows = self._rows[cutscene_id]
        rows["audio_label"].setText(_NONE_LABEL)
        rows["clear_audio_btn"].setEnabled(False)
        cutscene_import.write_registry_doc(self._data_dir, self._doc)

    def _on_length_committed(self, cutscene_id):
        rows = self._rows[cutscene_id]
        value = rows["length_spin"].value()
        if self._doc[cutscene_id].get("length") == value:
            return
        self._doc[cutscene_id]["length"] = value
        cutscene_import.write_registry_doc(self._data_dir, self._doc)
