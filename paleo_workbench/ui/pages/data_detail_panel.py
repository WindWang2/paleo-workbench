from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_asset_table import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.preview_strategy import (
    preview_for_artifact,
    preview_for_resource,
)


class PdfPreviewPanel(QWidget):
    """Detail-card PDF preview with interactive zoom.

    渲染尺寸 = 基准 QSize(420,560) × factor，步进 ×1.25/次，夹紧 10%–800%。
    image_label 置于 QScrollArea 中以支持放大后的平移滚动；翻页保持当前 factor；
    Ctrl+滚轮可缩放（仅影响当前会话）。
    """

    _BASE_SIZE = QSize(420, 560)
    _ZOOM_STEP = 1.25
    _MIN_FACTOR = 0.10
    _MAX_FACTOR = 8.00

    def __init__(self, document: QPdfDocument, parent=None):
        super().__init__(parent)
        self.setObjectName("PdfPreviewPanel")
        self._document = document
        # Take ownership so the document is destroyed with its preview widget
        # (previously parented to the DataDetailPanel and leaked one-per-PDF).
        if document is not None:
            document.setParent(self)
        self._page_index = 0
        self._zoom_factor = 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        self.image_label = QLabel()
        self.image_label.setObjectName("DataPreviewPdf")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("DataPreviewPdfScrollArea")
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(tokens.SPACE_2)
        self.prev_button = QPushButton("上一页")
        self.prev_button.setObjectName("DataPreviewPdfPrevious")
        self.prev_button.clicked.connect(self.previous_page)
        controls.addWidget(self.prev_button)

        self.zoom_out_button = QPushButton("\u2212")
        self.zoom_out_button.setObjectName("SecondaryButton")
        self.zoom_out_button.setToolTip("缩小")
        self.zoom_out_button.clicked.connect(self.zoom_out)
        controls.addWidget(self.zoom_out_button)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("DataPreviewPdfZoomLabel")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        controls.addWidget(self.zoom_label)

        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setObjectName("SecondaryButton")
        self.zoom_in_button.setToolTip("放大")
        self.zoom_in_button.clicked.connect(self.zoom_in)
        controls.addWidget(self.zoom_in_button)

        self.page_label = QLabel()
        self.page_label.setObjectName("DataPreviewPdfPageLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(self.page_label, 1)

        self.next_button = QPushButton("下一页")
        self.next_button.setObjectName("DataPreviewPdfNext")
        self.next_button.clicked.connect(self.next_page)
        controls.addWidget(self.next_button)
        layout.addLayout(controls)

        # Ctrl+wheel zoom: viewport consumes wheel events, filter it.
        self.scroll_area.viewport().installEventFilter(self)

        self._update_zoom_label()
        self._render_page()

    def zoom_in(self) -> None:
        self._set_zoom_factor(self._zoom_factor * self._ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom_factor(self._zoom_factor / self._ZOOM_STEP)

    def _set_zoom_factor(self, factor: float) -> None:
        clamped = max(self._MIN_FACTOR, min(self._MAX_FACTOR, factor))
        # avoid redundant render when already clamped at boundary
        if abs(clamped - self._zoom_factor) < 1e-9:
            self._update_zoom_label()
            return
        self._zoom_factor = clamped
        self._update_zoom_label()
        self._render_page()

    def _update_zoom_label(self) -> None:
        percent = int(round(self._zoom_factor * 100))
        self.zoom_label.setText(f"{percent}%")

    def eventFilter(self, obj, event):  # type: ignore[override]
        try:
            from PySide6.QtCore import QEvent
            if obj is self.scroll_area.viewport() and event.type() == QEvent.Type.Wheel:
                if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                    delta = event.angleDelta().y()
                    if delta > 0:
                        self.zoom_in()
                    elif delta < 0:
                        self.zoom_out()
                    event.accept()
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def next_page(self) -> None:
        if self._document is None:
            return
        try:
            count = self._document.pageCount()
        except Exception:
            return
        if self._page_index < count - 1:
            self._page_index += 1
            self._render_page()

    def previous_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._render_page()

    def _render_page(self) -> None:
        if self._document is None:
            self.page_label.setText(f"{self._page_index + 1} / 0")
            self.prev_button.setEnabled(False)
            self.next_button.setEnabled(False)
            self._update_zoom_label()
            return
        try:
            page_count = self._document.pageCount()
        except Exception:
            page_count = 0
        w = int(round(self._BASE_SIZE.width() * self._zoom_factor))
        h = int(round(self._BASE_SIZE.height() * self._zoom_factor))
        render_size = QSize(max(1, w), max(1, h))
        try:
            image = self._document.render(self._page_index, render_size)
        except Exception:
            image = None
        if image is not None and not image.isNull():
            pix = QPixmap.fromImage(image)
            self.image_label.setPixmap(pix)
            # QLabel size must track pixmap for scrollbars to appear (widgetResizable=False)
            self.image_label.resize(pix.size())
        if page_count <= 0:
            self.page_label.setText(f"{self._page_index + 1} / 0")
        else:
            self.page_label.setText(f"{self._page_index + 1} / {page_count}")
        self.prev_button.setEnabled(self._page_index > 0)
        self.next_button.setEnabled(page_count > 0 and self._page_index < page_count - 1)
        self._update_zoom_label()


class DataDetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataDetailPanel")
        self.setMinimumWidth(240)
        # Project file used to resolve project-RELATIVE resource/artifact paths
        # for preview. Set by the owning DataPage; None keeps legacy behavior.
        self.project_path: Path | None = None
        self.setStyleSheet(
            f"QFrame#DataDetailPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_3)

        self.title_label = QLabel("请选择数据项")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.metadata_layout = QVBoxLayout()
        self.metadata_layout.setSpacing(tokens.SPACE_1)
        layout.addLayout(self.metadata_layout)

        self.preview_title = QLabel("预览")
        self.preview_title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        layout.addWidget(self.preview_title)

        self.preview_layout = QVBoxLayout()
        self.preview_layout.setSpacing(tokens.SPACE_1)
        layout.addLayout(self.preview_layout)
        layout.addStretch()

        self.update_asset(None)

    def update_asset(self, asset: object | None) -> None:
        self._clear_layout(self.metadata_layout)
        self._clear_layout(self.preview_layout)

        if asset is None:
            self.title_label.setText("请选择数据项")
            self._add_muted(self.metadata_layout, "从列表中选择一个数据、成果或文件")
            self.preview_title.setText("预览")
            self._add_muted(self.preview_layout, "暂无预览")
            return

        if isinstance(asset, ResourceItem):
            self._update_resource(asset)
            return

        if isinstance(asset, ExportArtifact):
            self._update_artifact(asset)
            return

        self.title_label.setText("未知数据项")
        self._add_muted(self.metadata_layout, str(asset))

    def _update_resource(self, resource: ResourceItem) -> None:
        self.title_label.setText(resource.name)
        type_label = RESOURCE_TYPE_LABELS.get(resource.type, resource.type)
        rows = [
            ("类型", type_label),
            ("格式", resource.format),
            ("状态", resource.status),
            ("路径", resource.path),
            ("校验", resource.checksum or "—"),
        ]
        for label, value in rows:
            self._add_row(label, value)

        state = preview_for_resource(resource, base_path=self.project_path)
        self.preview_title.setText(state.title)
        if state.mode == "image" and state.image_path:
            if not self._add_image_preview(state.image_path):
                self._add_warning("图片预览加载失败")
            self._add_muted(self.preview_layout, f"图片: {state.image_path}")
        elif state.mode == "pdf" and state.document_path:
            if not self._add_pdf_preview(state.document_path):
                self._add_warning("PDF预览加载失败")
            self._add_muted(self.preview_layout, f"PDF: {state.document_path}")
        elif state.mode in {"text", "table"}:
            for line in state.lines:
                self._add_preview_line(line)
        else:
            for line in state.lines:
                self._add_muted(self.preview_layout, line)
        if state.warning:
            self._add_warning(state.warning)

    def _update_artifact(self, artifact: ExportArtifact) -> None:
        name = artifact.output_path.rsplit("/", 1)[-1] or artifact.output_path
        self.title_label.setText(name)
        rows = [
            ("类型", "成果"),
            ("格式", artifact.format),
            ("路径", artifact.output_path),
            ("关联", artifact.linked_id),
        ]
        for label, value in rows:
            self._add_row(label, value)

        state = preview_for_artifact(artifact, base_path=self.project_path)
        self.preview_title.setText(state.title)
        for line in state.lines:
            self._add_muted(self.preview_layout, line)

    def _add_row(self, label: str, value: str) -> None:
        item = QLabel(f"{label}: {value}")
        item.setWordWrap(True)
        item.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-size: 12px;")
        self.metadata_layout.addWidget(item)

    def show_downstream_impact(self, rows: list[dict] | None) -> None:
        """Append a simple 下游影响 list (Stage-9 freshness, no graph visualizer)."""
        if not rows:
            return
        title = QLabel("下游影响")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600; font-size: 12px;"
        )
        self.metadata_layout.addWidget(title)
        for row in rows[:20]:
            label = row.get("label") or row.get("operation") or "?"
            state = row.get("state_label") or row.get("state") or ""
            line = QLabel(f"· {label} — {state}")
            line.setWordWrap(True)
            color = (
                tokens.WARNING
                if str(row.get("state", "")).upper() == "STALE"
                else tokens.TEXT_SECONDARY
            )
            line.setStyleSheet(f"color: {color}; font-size: 12px;")
            self.metadata_layout.addWidget(line)

    def _add_muted(self, layout: QVBoxLayout, text: str) -> None:
        item = QLabel(text)
        item.setWordWrap(True)
        item.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(item)

    def _add_preview_line(self, text: str) -> None:
        item = QLabel(text)
        item.setWordWrap(True)
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        item.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
            " font-family: Consolas, 'Courier New', monospace;"
        )
        self.preview_layout.addWidget(item)

    def _add_image_preview(self, path: str) -> bool:
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return False
        label = QLabel()
        label.setObjectName("DataPreviewImage")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setPixmap(
            pixmap.scaled(
                220,
                160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_layout.addWidget(label)
        return True

    def _add_pdf_preview(self, path: str) -> bool:
        document = QPdfDocument(self)
        error = document.load(path)
        if error != QPdfDocument.Error.None_:
            return False
        if document.pageCount() <= 0:
            return False
        self.preview_layout.addWidget(PdfPreviewPanel(document))
        return True

    def _add_warning(self, text: str) -> None:
        item = QLabel(text)
        item.setWordWrap(True)
        item.setStyleSheet(f"color: {tokens.WARNING}; font-size: 12px;")
        self.preview_layout.addWidget(item)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
