from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.data_asset_table import RESOURCE_TYPE_LABELS
from paleo_workbench.ui.pages.preview_strategy import (
    preview_for_artifact,
    preview_for_resource,
)


class PdfPreviewPanel(QWidget):
    def __init__(self, document: QPdfDocument, parent=None):
        super().__init__(parent)
        self.setObjectName("PdfPreviewPanel")
        self._document = document
        self._page_index = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        self.image_label = QLabel()
        self.image_label.setObjectName("DataPreviewPdf")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.image_label)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(tokens.SPACE_2)
        self.prev_button = QPushButton("上一页")
        self.prev_button.setObjectName("DataPreviewPdfPrevious")
        self.prev_button.clicked.connect(self.previous_page)
        controls.addWidget(self.prev_button)

        self.page_label = QLabel()
        self.page_label.setObjectName("DataPreviewPdfPageLabel")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        controls.addWidget(self.page_label, 1)

        self.next_button = QPushButton("下一页")
        self.next_button.setObjectName("DataPreviewPdfNext")
        self.next_button.clicked.connect(self.next_page)
        controls.addWidget(self.next_button)
        layout.addLayout(controls)

        self._render_page()

    def next_page(self) -> None:
        if self._page_index < self._document.pageCount() - 1:
            self._page_index += 1
            self._render_page()

    def previous_page(self) -> None:
        if self._page_index > 0:
            self._page_index -= 1
            self._render_page()

    def _render_page(self) -> None:
        image = self._document.render(self._page_index, QSize(420, 560))
        if not image.isNull():
            self.image_label.setPixmap(QPixmap.fromImage(image))
        page_count = self._document.pageCount()
        self.page_label.setText(f"{self._page_index + 1} / {page_count}")
        self.prev_button.setEnabled(self._page_index > 0)
        self.next_button.setEnabled(self._page_index < page_count - 1)


class DataDetailPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataDetailPanel")
        self.setMinimumWidth(240)
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

        state = preview_for_resource(resource)
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

        state = preview_for_artifact(artifact)
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
                widget.setParent(None)
