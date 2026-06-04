from __future__ import annotations

# SPDX-License-Identifier: GPL-3.0-only

import argparse
import io
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path


SIZE_OPTIONS = (16, 24, 32, 48, 64, 128, 256)
DEFAULT_SIZES = {16, 32, 48, 256}
SUPPORTED_SUFFIXES = {".png", ".svg"}
APP_ICON_NAME = "quick-ico-converter.ico"
APP_DESCRIPTION = "Convert PNG and SVG images to ICO."


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


try:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QRect, QThread, Qt, Signal
    from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPalette, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QCheckBox,
        QDialog,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QStyle,
        QStyleOptionButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


def require_qt() -> None:
    if QT_IMPORT_ERROR is not None:
        raise RuntimeError(
            "Quick Icon Converter needs PySide6 for its Qt interface.\n\n"
            "Install it with:\n"
            "python -m pip install PySide6"
        ) from QT_IMPORT_ERROR


def import_pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Quick Icon Converter needs Pillow for image resizing and ICO writing.\n\n"
            "Install it with:\n"
            "python -m pip install Pillow"
        ) from exc
    return Image


def render_svg_to_image(svg_path: Path, size: int):
    require_qt()
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError("The SVG file could not be rendered.")

    Image = import_pillow()
    canvas = QImage(size, size, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)

    painter = QPainter(canvas)
    renderer.render(painter)
    painter.end()

    png_data = QByteArray()
    buffer = QBuffer(png_data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    canvas.save(buffer, "PNG")
    buffer.close()

    png_bytes = bytes(png_data)
    if not png_bytes:
        raise RuntimeError("The SVG file could not be converted to an image.")

    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


def make_square_icon_source(image, size: int):
    Image = import_pillow()
    icon = image.convert("RGBA")
    scale = min(size / icon.width, size / icon.height)
    target_width = max(1, round(icon.width * scale))
    target_height = max(1, round(icon.height * scale))
    icon = icon.resize((target_width, target_height), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - icon.width) // 2
    y = (size - icon.height) // 2
    canvas.alpha_composite(icon, (x, y))
    return canvas


def output_path_for(input_path: Path, size: int, manual_output_dir: Path | None) -> Path:
    output_dir = manual_output_dir if manual_output_dir else input_path.parent / "ico_converted"
    return output_dir / f"{input_path.stem}_{size}x.ico"


def convert_one_size(input_path: Path, output_path: Path, size: int) -> None:
    if not input_path.exists():
        raise RuntimeError("The input file does not exist.")

    suffix = input_path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise RuntimeError("Please choose a PNG or SVG file.")

    Image = import_pillow()
    if suffix == ".svg":
        source = render_svg_to_image(input_path, size)
    else:
        with Image.open(input_path) as image:
            source = image.convert("RGBA")

    icon = make_square_icon_source(source, size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    icon.save(output_path, format="ICO", sizes=[(size, size)])


def human_size(byte_count: int) -> str:
    size = float(byte_count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{byte_count} B"


@dataclass
class QueueFile:
    row: int
    path: Path
    suffix: str
    byte_count: int
    enabled: bool = True
    sizes: set[int] = field(default_factory=lambda: set(DEFAULT_SIZES))


@dataclass(frozen=True)
class ConversionJob:
    row: int
    path: Path
    sizes: tuple[int, ...]


if QT_IMPORT_ERROR is None:

    class QueueWorker(QObject):
        progress = Signal(int, str, int, str)
        finished = Signal(bool, int)

        def __init__(self, jobs: list[ConversionJob], manual_output_dir: Path | None) -> None:
            super().__init__()
            self.jobs = jobs
            self.manual_output_dir = manual_output_dir
            self._condition = threading.Condition()
            self._paused = False
            self._cancelled = False

        def request_pause(self) -> None:
            with self._condition:
                self._paused = True

        def request_resume(self) -> None:
            with self._condition:
                self._paused = False
                self._condition.notify_all()

        def request_cancel(self) -> None:
            with self._condition:
                self._cancelled = True
                self._paused = False
                self._condition.notify_all()

        def _wait_if_paused(self) -> bool:
            with self._condition:
                while self._paused and not self._cancelled:
                    self._condition.wait(0.2)
                return not self._cancelled

        def run(self) -> None:
            error_count = 0
            cancelled = False

            for job in self.jobs:
                remaining = len(job.sizes)
                if not self._wait_if_paused():
                    cancelled = True
                    break

                self.progress.emit(job.row, "Working", remaining, "")
                for size in job.sizes:
                    if not self._wait_if_paused():
                        cancelled = True
                        self.progress.emit(job.row, "Cancelled", remaining, "")
                        break

                    try:
                        convert_one_size(job.path, output_path_for(job.path, size, self.manual_output_dir), size)
                    except Exception as exc:
                        error_count += 1
                        self.progress.emit(job.row, "Error", remaining, str(exc))
                        break

                    remaining -= 1
                    self.progress.emit(job.row, "Working" if remaining else "Done", remaining, "")

                if cancelled:
                    break

            self.finished.emit(cancelled, error_count)


    class CheckBoxHeader(QHeaderView):
        toggled = Signal(bool)

        def __init__(self, parent=None) -> None:
            super().__init__(Qt.Orientation.Horizontal, parent)
            self._state = Qt.CheckState.Unchecked
            self.setSectionsClickable(True)

        def set_check_state(self, state: Qt.CheckState) -> None:
            self._state = state
            self.viewport().update()

        def paintSection(self, painter, rect, logical_index) -> None:
            super().paintSection(painter, rect, logical_index)
            if logical_index != 0:
                return

            option = QStyleOptionButton()
            indicator_size = self.style().pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth, option, self)
            option.rect = QRect(
                rect.x() + (rect.width() - indicator_size) // 2,
                rect.y() + (rect.height() - indicator_size) // 2,
                indicator_size,
                indicator_size,
            )
            option.state = QStyle.StateFlag.State_Enabled
            if self._state == Qt.CheckState.Checked:
                option.state |= QStyle.StateFlag.State_On
            elif self._state == Qt.CheckState.PartiallyChecked:
                option.state |= QStyle.StateFlag.State_NoChange
            else:
                option.state |= QStyle.StateFlag.State_Off
            self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)

        def mousePressEvent(self, event) -> None:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            if self.logicalIndexAt(pos) == 0:
                self.toggled.emit(self._state != Qt.CheckState.Checked)
                event.accept()
                return
            super().mousePressEvent(event)


    class DropTable(QTableWidget):
        files_dropped = Signal(list)

        def __init__(self) -> None:
            super().__init__(0, 8)
            self.setAcceptDrops(True)
            self.setAlternatingRowColors(True)
            self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

            header = CheckBoxHeader(self)
            self.setHorizontalHeader(header)
            self.check_header = header
            self.setHorizontalHeaderLabels(
                ["", "Status", "Remaining", "Sizes", "File name", "Format", "Source size", "Source path"]
            )

            self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(0, 34)
            for column in range(1, 7):
                self.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            self.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)

        def dragEnterEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.files_dropped.emit(paths)
                event.acceptProposedAction()
            else:
                super().dropEvent(event)


    class SizeCheckBox(QCheckBox):
        user_toggled = Signal(bool)

        def __init__(self, text: str) -> None:
            super().__init__(text)
            self.setTristate(True)

        def nextCheckState(self) -> None:
            checked = self.checkState() != Qt.CheckState.Checked
            self.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.user_toggled.emit(checked)


    class IcoMakerWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Quick Icon Converter")
            self.resize(1120, 650)
            self.setAcceptDrops(True)

            self.queue: list[QueueFile] = []
            self.worker: QueueWorker | None = None
            self.thread: QThread | None = None
            self.running = False
            self.paused = False
            self.manual_output_dir: Path | None = None
            self.syncing_sizes = False
            self.syncing_table = False

            self.size_checks: dict[int, QCheckBox] = {}
            self.table = DropTable()
            self.table.files_dropped.connect(self.add_paths)
            self.table.itemChanged.connect(self.table_item_changed)
            self.table.itemSelectionChanged.connect(self.selection_changed)
            self.table.check_header.toggled.connect(self.set_all_queue_enabled)
            self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self.show_table_context_menu)

            self.status_label = QLabel("Ready")
            self.output_edit = QLineEdit()
            self.output_edit.setReadOnly(True)
            self.output_edit.setPlaceholderText(r"Default: each source folder\ico_converted")
            self.start_button = QPushButton("Start")
            self.clear_button = QPushButton("Clear queue")
            self.all_sizes_button = QPushButton("All sizes")
            self.about_button = QPushButton("ⓘ")
            self.drop_hint = QLabel()
            self.preview_label = QLabel("Preview")

            self.build_ui()
            self.install_shortcuts()
            self.sync_size_controls()
            self.update_header_checkbox()

        def build_ui(self) -> None:
            central = QWidget()
            layout = QVBoxLayout(central)
            layout.setContentsMargins(16, 16, 16, 16)
            layout.setSpacing(12)
            self.setCentralWidget(central)

            title = QLabel("Quick Icon Converter")
            title.setStyleSheet("font-size: 28px; font-weight: 700;")
            layout.addWidget(title)

            subtitle = QLabel("Output .ico files will be saved in ico_converted next to each source file unless you choose one output folder.")
            layout.addWidget(subtitle)

            drop_area_row = QHBoxLayout()
            drop_area_row.setSpacing(16)

            drop_frame = QFrame()
            drop_frame.setMinimumHeight(160)
            drop_frame.setFrameShape(QFrame.Shape.NoFrame)
            drop_frame.setStyleSheet(
                "QFrame {"
                "border: 3px dashed palette(mid);"
                "border-radius: 16px;"
                "}"
                "QLabel {"
                "border: none;"
                "}"
            )
            drop_layout = QHBoxLayout(drop_frame)
            drop_layout.setContentsMargins(30, 22, 30, 22)
            drop_layout.setSpacing(24)

            self.drop_hint.setTextFormat(Qt.TextFormat.RichText)
            self.drop_hint.setText(
                "<div style='font-size: 30px; font-weight: 700;'>Drop PNG/SVG files here</div>"
                "<div style='font-size: 18px; font-weight: 400; margin-top: 12px;'>"
                "Dropped files will be added to the queue</div>"
            )
            self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drop_layout.addWidget(self.drop_hint, 1)

            self.preview_label.setFixedSize(160, 160)
            self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_label.setStyleSheet(
                "QLabel {"
                "border: 1px solid palette(mid);"
                "border-radius: 4px;"
                "background: palette(base);"
                "color: palette(mid);"
                "}"
            )
            drop_area_row.addWidget(drop_frame, 1)
            drop_area_row.addWidget(self.preview_label)
            layout.addLayout(drop_area_row)

            add_row = QHBoxLayout()
            browse_button = QPushButton("Browse...")
            paste_button = QPushButton("Paste")
            self.apply_button_style(browse_button)
            self.apply_button_style(paste_button)
            browse_button.clicked.connect(self.browse_files)
            paste_button.clicked.connect(self.paste_files)
            add_row.addWidget(browse_button)
            add_row.addWidget(paste_button)
            add_row.addStretch(1)
            layout.addLayout(add_row)

            size_row = QHBoxLayout()
            size_row.addWidget(QLabel("Sizes for highlighted files:"))
            for size in SIZE_OPTIONS:
                check = SizeCheckBox(f"{size}x")
                check.user_toggled.connect(
                    lambda checked, icon_size=size: self.apply_size_to_selected(icon_size, checked)
                )
                self.size_checks[size] = check
                size_row.addWidget(check)
            self.apply_button_style(self.all_sizes_button)
            self.all_sizes_button.clicked.connect(self.toggle_all_sizes_for_selected)
            size_row.addWidget(self.all_sizes_button)
            size_row.addStretch(1)
            layout.addLayout(size_row)

            output_row = QHBoxLayout()
            output_row.addWidget(QLabel("Output:"))
            output_row.addWidget(self.output_edit, 1)
            choose_output_button = QPushButton("Choose folder...")
            clear_output_button = QPushButton("Use default")
            self.apply_button_style(choose_output_button)
            self.apply_button_style(clear_output_button)
            choose_output_button.clicked.connect(self.choose_output_folder)
            clear_output_button.clicked.connect(self.use_default_output)
            output_row.addWidget(choose_output_button)
            output_row.addWidget(clear_output_button)
            layout.addLayout(output_row)

            layout.addWidget(self.table, 1)

            action_row = QHBoxLayout()
            self.apply_button_style(self.start_button, primary=True)
            self.apply_button_style(self.clear_button)
            self.start_button.clicked.connect(self.start_pause_resume)
            self.clear_button.clicked.connect(self.clear_or_cancel)
            action_row.addWidget(self.start_button)
            action_row.addWidget(self.clear_button)
            action_row.addWidget(self.status_label, 1)
            self.about_button.setFixedSize(28, 28)
            self.about_button.setToolTip("About Quick Icon Converter")
            self.about_button.setFlat(True)
            self.about_button.setStyleSheet("font-size: 20px; font-weight: 700;")
            self.about_button.clicked.connect(self.show_about)
            action_row.addWidget(self.about_button)
            layout.addLayout(action_row)

        def apply_button_style(self, button: QPushButton, primary: bool = False) -> None:
            weight = "700" if primary else "400"
            button.setMinimumHeight(30)
            button.setStyleSheet(
                "QPushButton {"
                "border: 1px solid palette(mid);"
                "border-radius: 5px;"
                "padding: 4px 12px;"
                "background: palette(button);"
                f"font-weight: {weight};"
                "}"
                "QPushButton:hover {"
                "background: palette(alternate-base);"
                "}"
                "QPushButton:pressed {"
                "background: palette(midlight);"
                "}"
                "QPushButton:disabled {"
                "color: palette(mid);"
                "}"
            )

        def install_shortcuts(self) -> None:
            paste_action = QAction("Paste files", self)
            paste_action.setShortcut(QKeySequence.StandardKey.Paste)
            paste_action.triggered.connect(self.paste_files)
            self.addAction(paste_action)

        def browse_files(self) -> None:
            files, _ = QFileDialog.getOpenFileNames(
                self,
                "Choose PNG or SVG files",
                "",
                "Image files (*.png *.svg);;PNG files (*.png);;SVG files (*.svg)",
            )
            self.add_paths(files)

        def paste_files(self) -> None:
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            paths: list[str] = []

            if mime.hasUrls():
                paths.extend(url.toLocalFile() for url in mime.urls() if url.isLocalFile())
            if mime.hasText():
                paths.extend(line.strip().strip('"') for line in mime.text().splitlines() if line.strip())

            self.add_paths(paths)

        def dragEnterEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragEnterEvent(event)

        def dragMoveEvent(self, event) -> None:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                super().dragMoveEvent(event)

        def dropEvent(self, event) -> None:
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.add_paths(paths)
                event.acceptProposedAction()
            else:
                super().dropEvent(event)

        def add_paths(self, paths: list[str]) -> None:
            if self.running:
                self.show_warning("Queue is locked while conversion is running.")
                return

            existing = {item.path.resolve() for item in self.queue}
            added = 0
            skipped = 0
            first_new_row = self.table.rowCount()

            for raw_path in paths:
                path = Path(raw_path).expanduser()
                if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    skipped += 1
                    continue

                resolved = path.resolve()
                if resolved in existing:
                    skipped += 1
                    continue

                item = QueueFile(
                    row=self.table.rowCount(),
                    path=resolved,
                    suffix=path.suffix.lower().lstrip("."),
                    byte_count=path.stat().st_size,
                )
                self.queue.append(item)
                existing.add(resolved)
                self.add_table_row(item)
                added += 1

            if added:
                self.table.clearSelection()
                for row in range(first_new_row, first_new_row + added):
                    self.table.selectRow(row)

            self.status_label.setText(f"Added {added} file(s)" + (f", skipped {skipped}" if skipped else ""))
            self.update_header_checkbox()
            self.sync_size_controls()

        def add_table_row(self, item: QueueFile) -> None:
            self.syncing_table = True
            try:
                row = self.table.rowCount()
                self.table.insertRow(row)

                check_item = QTableWidgetItem("")
                check_item.setFlags(
                    Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                )
                check_item.setCheckState(Qt.CheckState.Checked)
                check_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 0, check_item)

                values = [
                    "Queued",
                    str(len(item.sizes)),
                    self.size_text(item.sizes),
                    item.path.name,
                    item.suffix.upper(),
                    human_size(item.byte_count),
                    str(item.path),
                ]
                for column, value in enumerate(values, start=1):
                    table_item = QTableWidgetItem(value)
                    if column in {1, 2, 3, 5, 6}:
                        table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row, column, table_item)
            finally:
                self.syncing_table = False

        def selected_rows(self) -> list[int]:
            return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

        def selected_queue_items(self) -> list[QueueFile]:
            return [self.queue[row] for row in self.selected_rows() if row < len(self.queue)]

        def selection_changed(self) -> None:
            self.sync_size_controls()
            self.update_preview()

        def size_text(self, sizes: set[int]) -> str:
            return ", ".join(f"{size}x" for size in sorted(sizes)) if sizes else "-"

        def update_row_size_display(self, row: int) -> None:
            item = self.queue[row]
            self.table.item(row, 2).setText(str(len(item.sizes)) if item.enabled else "0")
            self.table.item(row, 3).setText(self.size_text(item.sizes))

        def apply_size_to_selected(self, size: int, checked: bool) -> None:
            if self.syncing_sizes or self.running:
                return

            rows = self.selected_rows()
            if not rows:
                self.sync_size_controls()
                return

            for row in rows:
                if row >= len(self.queue):
                    continue
                if checked:
                    self.queue[row].sizes.add(size)
                else:
                    self.queue[row].sizes.discard(size)
                self.update_row_size_display(row)

            self.sync_size_controls()

        def show_table_context_menu(self, pos) -> None:
            if self.running:
                return

            row = self.table.rowAt(pos.y())
            if row < 0:
                return

            if row not in self.selected_rows():
                self.table.clearSelection()
                self.table.selectRow(row)

            selected_count = len(self.selected_rows())
            menu = QMenu(self)
            delete_action = menu.addAction("Delete selected" if selected_count > 1 else "Delete item")
            action = menu.exec(self.table.viewport().mapToGlobal(pos))
            if action == delete_action:
                self.delete_selected_rows()

        def delete_selected_rows(self) -> None:
            if self.running:
                return

            rows = self.selected_rows()
            if not rows:
                return

            self.syncing_table = True
            try:
                for row in sorted(rows, reverse=True):
                    if row < len(self.queue):
                        del self.queue[row]
                    self.table.removeRow(row)

                for row, item in enumerate(self.queue):
                    item.row = row
            finally:
                self.syncing_table = False

            self.update_header_checkbox()
            self.sync_size_controls()
            self.update_preview()
            self.status_label.setText(f"Deleted {len(rows)} queue item(s)")

        def toggle_all_sizes_for_selected(self) -> None:
            if self.running:
                return

            selected = self.selected_queue_items()
            if not selected:
                return

            all_selected = all(item.sizes == set(SIZE_OPTIONS) for item in selected)
            next_sizes = set() if all_selected else set(SIZE_OPTIONS)
            for item in selected:
                item.sizes = set(next_sizes)
                self.update_row_size_display(item.row)

            self.sync_size_controls()

        def sync_size_controls(self) -> None:
            selected = self.selected_queue_items()
            controls_enabled = bool(selected) and not self.running

            self.syncing_sizes = True
            try:
                for size, check in self.size_checks.items():
                    check.setEnabled(controls_enabled)
                    if not selected:
                        check.setCheckState(Qt.CheckState.Unchecked)
                        continue

                    matches = sum(1 for item in selected if size in item.sizes)
                    if matches == len(selected):
                        check.setCheckState(Qt.CheckState.Checked)
                    elif matches == 0:
                        check.setCheckState(Qt.CheckState.Unchecked)
                    else:
                        check.setCheckState(Qt.CheckState.PartiallyChecked)

                self.all_sizes_button.setEnabled(controls_enabled)
                if selected and all(item.sizes == set(SIZE_OPTIONS) for item in selected):
                    self.all_sizes_button.setText("Clear sizes")
                else:
                    self.all_sizes_button.setText("All sizes")
            finally:
                self.syncing_sizes = False

        def update_preview(self) -> None:
            selected = self.selected_queue_items()
            if not selected:
                self.preview_label.setPixmap(QPixmap())
                self.preview_label.setText("Preview")
                return

            path = selected[0].path
            size = min(self.preview_label.width(), self.preview_label.height()) - 16
            pixmap = self.preview_pixmap(path, size)
            if pixmap.isNull():
                self.preview_label.setPixmap(QPixmap())
                self.preview_label.setText("No preview")
                return

            self.preview_label.setText("")
            self.preview_label.setPixmap(pixmap)

        def preview_pixmap(self, path: Path, size: int) -> QPixmap:
            if path.suffix.lower() == ".svg":
                renderer = QSvgRenderer(str(path))
                if not renderer.isValid():
                    return QPixmap()

                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pixmap)
                renderer.render(painter)
                painter.end()
                return pixmap

            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                return pixmap
            return pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        def table_item_changed(self, item: QTableWidgetItem) -> None:
            if self.syncing_table or item.column() != 0 or item.row() >= len(self.queue):
                return

            self.queue[item.row()].enabled = item.checkState() == Qt.CheckState.Checked
            self.update_row_size_display(item.row())
            self.update_header_checkbox()

        def set_all_queue_enabled(self, enabled: bool) -> None:
            if self.running:
                return

            self.syncing_table = True
            try:
                for row, item in enumerate(self.queue):
                    item.enabled = enabled
                    self.table.item(row, 0).setCheckState(
                        Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
                    )
                    self.update_row_size_display(row)
            finally:
                self.syncing_table = False

            self.update_header_checkbox()

        def update_header_checkbox(self) -> None:
            total = len(self.queue)
            checked = sum(1 for item in self.queue if item.enabled)
            if not total or checked == 0:
                state = Qt.CheckState.Unchecked
            elif checked == total:
                state = Qt.CheckState.Checked
            else:
                state = Qt.CheckState.PartiallyChecked
            self.table.check_header.set_check_state(state)

        def choose_output_folder(self) -> None:
            selected = QFileDialog.getExistingDirectory(self, "Choose output folder")
            if selected:
                self.manual_output_dir = Path(selected)
                self.output_edit.setText(str(self.manual_output_dir))

        def use_default_output(self) -> None:
            self.manual_output_dir = None
            self.output_edit.clear()

        def set_controls_for_run(self, enabled: bool) -> None:
            self.table.setEnabled(enabled)
            self.sync_size_controls()

        def start_pause_resume(self) -> None:
            if self.running and self.worker:
                if self.paused:
                    self.paused = False
                    self.worker.request_resume()
                    self.start_button.setText("Pause")
                    self.clear_button.setText("Clear queue")
                    self.clear_button.setEnabled(False)
                    self.status_label.setText("Running")
                else:
                    self.paused = True
                    self.worker.request_pause()
                    self.start_button.setText("Resume")
                    self.clear_button.setText("Cancel")
                    self.clear_button.setEnabled(True)
                    self.status_label.setText("Paused")
                return

            if not self.queue:
                self.show_warning("Add at least one PNG or SVG file first.")
                return

            jobs = [
                ConversionJob(row=item.row, path=item.path, sizes=tuple(sorted(item.sizes)))
                for item in self.queue
                if item.enabled and item.sizes
            ]
            if not jobs:
                self.show_warning("Tick at least one queue item and assign at least one size.")
                return

            self.start_conversion(jobs)

        def start_conversion(self, jobs: list[ConversionJob]) -> None:
            job_rows = {job.row for job in jobs}
            for item in self.queue:
                if item.row in job_rows:
                    self.table.item(item.row, 1).setText("Queued")
                    self.table.item(item.row, 2).setText(str(len(item.sizes)))
                elif not item.enabled:
                    self.table.item(item.row, 1).setText("Not selected")
                    self.table.item(item.row, 2).setText("0")
                else:
                    self.table.item(item.row, 1).setText("No sizes")
                    self.table.item(item.row, 2).setText("0")

            self.thread = QThread()
            self.worker = QueueWorker(jobs, self.manual_output_dir)
            self.worker.moveToThread(self.thread)
            self.thread.started.connect(self.worker.run)
            self.worker.progress.connect(self.update_row)
            self.worker.finished.connect(self.worker_finished)
            self.worker.finished.connect(self.thread.quit)
            self.thread.finished.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.conversion_thread_finished)
            self.thread.finished.connect(self.thread.deleteLater)

            self.running = True
            self.paused = False
            self.set_controls_for_run(False)
            self.start_button.setText("Pause")
            self.clear_button.setEnabled(False)
            self.status_label.setText("Running")
            self.thread.start()

        def clear_or_cancel(self) -> None:
            if self.running and self.paused and self.worker:
                self.worker.request_cancel()
                self.start_button.setEnabled(False)
                self.clear_button.setEnabled(False)
                self.status_label.setText("Cancelling...")
                return

            if self.running:
                return

            self.queue.clear()
            self.table.setRowCount(0)
            self.update_header_checkbox()
            self.sync_size_controls()
            self.status_label.setText("Queue cleared")

        def update_row(self, row: int, status: str, remaining: int, message: str) -> None:
            if row >= self.table.rowCount():
                return

            self.table.item(row, 1).setText(status if not message else f"{status}: {message}")
            self.table.item(row, 2).setText(str(remaining))
            self.table.scrollToItem(self.table.item(row, 1))

        def worker_finished(self, cancelled: bool, error_count: int) -> None:
            self.running = False
            self.paused = False
            self.set_controls_for_run(True)
            self.start_button.setEnabled(True)
            self.start_button.setText("Start")
            self.clear_button.setEnabled(True)
            self.clear_button.setText("Clear queue")
            self.sync_size_controls()

            if cancelled:
                self.status_label.setText("Cancelled. Queue preserved.")
            elif error_count:
                self.status_label.setText(f"Finished with {error_count} error(s)")
            else:
                self.status_label.setText("Finished")

        def conversion_thread_finished(self) -> None:
            self.worker = None
            self.thread = None

        def show_about(self) -> None:
            dialog = QDialog(self)
            dialog.setWindowTitle("Quick Icon Converter")
            dialog.setMinimumWidth(540)

            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(36, 34, 36, 30)
            layout.setSpacing(22)

            text = QLabel(
                "Quick Icon Converter\n"
                "© 2026 strailico5327\n\n"
                f"{APP_DESCRIPTION}\n\n"
                "Licensed under GNU GPLv3."
            )
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text.setStyleSheet("font-size: 18px;")
            layout.addWidget(text)

            ok_row = QHBoxLayout()
            ok_button = QPushButton("OK")
            self.apply_button_style(ok_button)
            ok_button.setMinimumWidth(72)
            ok_button.clicked.connect(dialog.accept)
            ok_row.addStretch(1)
            ok_row.addWidget(ok_button)
            ok_row.addStretch(1)
            layout.addLayout(ok_row)

            dialog.exec()

        def show_warning(self, text: str) -> None:
            QMessageBox.warning(self, "Quick Icon Converter", text)


def apply_system_theme(app: QApplication) -> None:
    palette = app.palette()
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):
        is_dark = hints.colorScheme() == Qt.ColorScheme.Dark
    else:
        is_dark = palette.color(QPalette.ColorRole.Window).lightness() < 128

    if not is_dark:
        app.setPalette(palette)
        return

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(32, 34, 37))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(238, 238, 238))
    dark.setColor(QPalette.ColorRole.Base, QColor(24, 26, 29))
    dark.setColor(QPalette.ColorRole.AlternateBase, QColor(38, 41, 45))
    dark.setColor(QPalette.ColorRole.ToolTipBase, QColor(238, 238, 238))
    dark.setColor(QPalette.ColorRole.ToolTipText, QColor(24, 26, 29))
    dark.setColor(QPalette.ColorRole.Text, QColor(238, 238, 238))
    dark.setColor(QPalette.ColorRole.Button, QColor(45, 48, 53))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(238, 238, 238))
    dark.setColor(QPalette.ColorRole.Highlight, QColor(57, 120, 190))
    dark.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(dark)


def run_self_test() -> int:
    try:
        import_pillow()
    except RuntimeError as exc:
        print(exc)
        return 2

    try:
        require_qt()
    except RuntimeError as exc:
        print(exc)
        return 2

    print("Self-test passed: Pillow and PySide6 are available.")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert PNG or SVG files to ICO files.")
    parser.add_argument("--self-test", action="store_true", help="check required runtime dependencies")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.self_test:
        return run_self_test()

    require_qt()
    if hasattr(QGuiApplication, "setHighDpiScaleFactorRoundingPolicy"):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Quick Icon Converter")
    icon_path = resource_path(APP_ICON_NAME)
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")
    apply_system_theme(app)

    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda _: apply_system_theme(app))

    window = IcoMakerWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
