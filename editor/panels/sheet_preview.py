"""SheetPreview — the importer looking at its own input.

Draws an imported sheet PNG scaled to fit, with the frame grid overlaid, hidden
frames dimmed, each row's static frame outlined and every cell captioned with its
COLUMN index — the same number the row editor's hide checkboxes, static radios and
the manifest's `hidden`/`loop_start`/`loop_end` all speak, so "hide frame 3" needs
no counting. Clicking a cell emits `frame_clicked(row, col)`; DetailsPanel routes
that to the matching RowEditor, so "click the frame you want" is literal.
`interactive=False` gives the sheet picker the same view, read-only.

ED-22 (one render path) is NOT bent here. That rule bans a second Qt-side renderer
of GAME CONTENT — the animated preview stays in the viewport, through
engine/render, exactly as before. This widget inspects a source PNG on disk, the
way a file dialog shows a thumbnail; it resolves no slot, no animation and no
time. The palette's brush icons go the other way (engine-resolved frames via
`viewport.slot_qimage`), but that only ever yields the resolved IDLE frame — it
cannot show an arbitrary frame, let alone the sheet, so it cannot serve here.

Qt-only (QPixmap/QPainter): no pygame, no engine render import.
"""
from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

#: Tallest the preview ever gets — it sits above the row editors and must not
#: crowd them out on a short panel.
MAX_HEIGHT = 240
#: Never magnify past this; pixel art gets blocky fast and the panel is narrow.
MAX_SCALE = 4.0

# Deliberately theme-independent (panels doc): every colour has to stay legible
# on BOTH the light and the dark chrome, so they are drawn OVER the art rather
# than picked from the palette.
CHECKER_LIGHT = QColor(0xB0, 0xB0, 0xB0)
CHECKER_DARK = QColor(0x88, 0x88, 0x88)
CHECKER_PX = 8
GRID_PEN = QColor(0, 0, 0, 110)
HIDDEN_DIM = QColor(0, 0, 0, 150)
STATIC_PEN = QColor(0x2E, 0xC4, 0xFF)
HOVER_TINT = QColor(0xFF, 0xFF, 0xFF, 48)

# The per-cell column number. White on its own dark plate, because it lands on
# arbitrary art: any colour drawn straight onto the frame is invisible against
# some sheet.
LABEL_TEXT = QColor(0xFF, 0xFF, 0xFF)
LABEL_PLATE = QColor(0, 0, 0, 165)
LABEL_PAD = 2
#: Below this cell size the plate would cover the frame it is labelling — drop
#: the numbers instead (the row editor's checkboxes still carry them).
LABEL_MIN_CELL = 16
LABEL_MIN_PX = 8
LABEL_MAX_PX = 12


class SheetPreview(QWidget):
    """set_sheet(png, fw, fh) + set_rows([...]) -> a clickable grid view."""

    frame_clicked = Signal(int, int)     # (row, col)

    def __init__(self, interactive=True, parent=None):
        super().__init__(parent)
        self._interactive = interactive
        self._pixmap = None
        self._frame_w = 1
        self._frame_h = 1
        self._cols = 0
        self._rows = 0
        self._row_state = []     # [{"hidden": set[int], "static_frame": int|None}]
        self._hover = None       # (row, col) under the cursor

        policy = QSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        if interactive:
            self.setMouseTracking(True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    # -- content -------------------------------------------------------------

    def set_sheet(self, png_path, frame_w, frame_h):
        """Show a sheet sliced at frame_w x frame_h. None clears the view. An
        unreadable PNG clears it too — art problems never raise here (E-37)."""
        pixmap = None
        if png_path is not None:
            candidate = QPixmap(str(png_path))
            if not candidate.isNull():
                pixmap = candidate
        self._pixmap = pixmap
        self._frame_w = max(1, int(frame_w))
        self._frame_h = max(1, int(frame_h))
        if pixmap is None:
            self._cols = self._rows = 0
        else:
            self._cols = pixmap.width() // self._frame_w
            self._rows = pixmap.height() // self._frame_h
        self._hover = None
        self.updateGeometry()
        self.update()

    def set_rows(self, row_state):
        """Per sheet row: {"hidden": iterable[int], "static_frame": int|None}.
        Rows past the sheet's row count are ignored, so a stale state can never
        paint outside the grid."""
        self._row_state = [
            {"hidden": set(state.get("hidden") or ()),
             "static_frame": state.get("static_frame")}
            for state in (row_state or ())
        ]
        self.update()

    def has_sheet(self):
        return self._pixmap is not None and self._cols > 0 and self._rows > 0

    # -- geometry ------------------------------------------------------------

    def _scale_for(self, width):
        if not self.has_sheet():
            return 0.0
        sheet_w = self._cols * self._frame_w
        sheet_h = self._rows * self._frame_h
        if sheet_w <= 0 or sheet_h <= 0 or width <= 0:
            return 0.0
        scale = min(width / sheet_w, MAX_HEIGHT / sheet_h, MAX_SCALE)
        return max(scale, 0.0)

    def _scale(self):
        return self._scale_for(self.width())

    def _grid_rect(self):
        """Where the sheet actually lands — centred horizontally, top-aligned."""
        scale = self._scale()
        if scale <= 0:
            return QRect()
        w = round(self._cols * self._frame_w * scale)
        h = round(self._rows * self._frame_h * scale)
        return QRect(max(0, (self.width() - w) // 2), 0, w, h)

    def heightForWidth(self, width):
        scale = self._scale_for(width)
        if scale <= 0:
            return 0
        return round(self._rows * self._frame_h * scale)

    def sizeHint(self):
        return QSize(self.width(), self.heightForWidth(self.width()))

    def cell_at(self, pos):
        """(row, col) under a widget-space point, or None outside the grid."""
        rect = self._grid_rect()
        if rect.isEmpty() or not rect.contains(pos):
            return None
        scale = self._scale()
        col = int((pos.x() - rect.left()) / (self._frame_w * scale))
        row = int((pos.y() - rect.top()) / (self._frame_h * scale))
        if 0 <= row < self._rows and 0 <= col < self._cols:
            return (row, col)
        return None

    def _cell_rect(self, row, col):
        rect = self._grid_rect()
        scale = self._scale()
        left = rect.left() + round(col * self._frame_w * scale)
        top = rect.top() + round(row * self._frame_h * scale)
        right = rect.left() + round((col + 1) * self._frame_w * scale)
        bottom = rect.top() + round((row + 1) * self._frame_h * scale)
        return QRect(left, top, right - left, bottom - top)

    def _state(self, row):
        if 0 <= row < len(self._row_state):
            return self._row_state[row]
        return {"hidden": set(), "static_frame": None}

    # -- painting ------------------------------------------------------------

    def paintEvent(self, _event):
        painter = QPainter(self)
        rect = self._grid_rect()
        if rect.isEmpty():
            return
        self._paint_checker(painter, rect)
        # Nearest-neighbour: this is pixel art, and a smoothed upscale would lie
        # about what the frame actually contains.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        source = QRect(0, 0, self._cols * self._frame_w,
                       self._rows * self._frame_h)
        painter.drawPixmap(rect, self._pixmap, source)
        self._paint_cells(painter)
        self._paint_grid(painter, rect)
        self._paint_labels(painter)

    def _paint_checker(self, painter, rect):
        painter.fillRect(rect, CHECKER_LIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(CHECKER_DARK)
        for y in range(rect.top(), rect.bottom() + 1, CHECKER_PX):
            for x in range(rect.left(), rect.right() + 1, CHECKER_PX):
                if ((x - rect.left()) // CHECKER_PX
                        + (y - rect.top()) // CHECKER_PX) % 2:
                    painter.drawRect(QRect(x, y, CHECKER_PX, CHECKER_PX)
                                     .intersected(rect))
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paint_cells(self, painter):
        for row in range(self._rows):
            state = self._state(row)
            static_frame = state["static_frame"]
            for col in range(self._cols):
                cell = self._cell_rect(row, col)
                if col in state["hidden"]:
                    painter.fillRect(cell, HIDDEN_DIM)
                if self._hover == (row, col):
                    painter.fillRect(cell, HOVER_TINT)
                if static_frame is not None and col == static_frame:
                    painter.setPen(QPen(STATIC_PEN, 2))
                    painter.drawRect(cell.adjusted(1, 1, -1, -1))

    def _paint_grid(self, painter, rect):
        painter.setPen(QPen(GRID_PEN, 1))
        scale = self._scale()
        for col in range(self._cols + 1):
            x = rect.left() + round(col * self._frame_w * scale)
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for row in range(self._rows + 1):
            y = rect.top() + round(row * self._frame_h * scale)
            painter.drawLine(rect.left(), y, rect.right(), y)

    def labels_visible(self):
        """Whether the column numbers fit. A thumbnail-sized cell would be all
        plate and no frame, so below LABEL_MIN_CELL they are dropped — the row
        editor's checkboxes still name every column."""
        scale = self._scale()
        return (self.has_sheet()
                and self._frame_w * scale >= LABEL_MIN_CELL
                and self._frame_h * scale >= LABEL_MIN_CELL)

    def _label_font(self):
        font = QFont(self.font())
        cell_h = self._frame_h * self._scale()
        font.setPixelSize(int(min(LABEL_MAX_PX, max(LABEL_MIN_PX, cell_h / 4))))
        font.setBold(True)
        return font

    def _label_rect(self, cell, metrics, text):
        """The plate for one caption: bottom-centred inside its cell."""
        width = metrics.horizontalAdvance(text) + 2 * LABEL_PAD
        height = metrics.height()
        return QRect(cell.center().x() - width // 2,
                     cell.bottom() - height + 1, width, height)

    def _paint_labels(self, painter):
        if not self.labels_visible():
            return
        font = self._label_font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for row in range(self._rows):
            for col in range(self._cols):
                text = str(col)
                plate = self._label_rect(self._cell_rect(row, col), metrics, text)
                painter.fillRect(plate, LABEL_PLATE)
                painter.setPen(LABEL_TEXT)
                painter.drawText(plate, Qt.AlignmentFlag.AlignCenter, text)

    # -- input ---------------------------------------------------------------

    def mouseMoveEvent(self, event):
        if not self._interactive:
            return
        cell = self.cell_at(event.position().toPoint())
        if cell != self._hover:
            self._hover = cell
            self.update()

    def leaveEvent(self, _event):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        cell = self.cell_at(event.position().toPoint())
        if cell is not None:
            self.frame_clicked.emit(cell[0], cell[1])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.updateGeometry()
