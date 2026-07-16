from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.mapping_helpers import active_map_document
from paleo_workbench.ui.pages.prediction_helpers import active_prediction_task, field_value
from paleo_workbench.viz.models import VizPayload, VizRef


class VisualizationTracePanel(QFrame):
    """Right-hand traceability summary for the composite visualization."""

    refresh_requested = Signal()
    export_requested = Signal(str)  # format label: PNG | SVG | PDF

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VisualizationTracePanel")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)
        title = QLabel("视图追踪")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.task_value = self._add_value(layout, "预测任务", "未选择预测任务")
        self.map_value = self._add_value(layout, "古地理图", "未选择古地理图")
        self.source_value = self._add_value(layout, "来源", "—")
        self.label_value = self._add_value(layout, "标签", "—")
        self.kind_value = self._add_value(layout, "类型", "—")
        self.path_value = self._add_value(layout, "路径/消息", "—")

        layout.addStretch()
        self.refresh_btn = QPushButton("刷新视图")
        self.refresh_btn.setObjectName("SecondaryButton")
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self.refresh_btn)
        self.export_btn = QPushButton("导出当前视图 PNG")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.clicked.connect(lambda: self.export_requested.emit("PNG"))
        layout.addWidget(self.export_btn)
        self.export_svg_btn = QPushButton("导出 SVG")
        self.export_svg_btn.setObjectName("SecondaryButton")
        self.export_svg_btn.clicked.connect(lambda: self.export_requested.emit("SVG"))
        layout.addWidget(self.export_svg_btn)
        self.export_pdf_btn = QPushButton("导出 PDF")
        self.export_pdf_btn.setObjectName("SecondaryButton")
        self.export_pdf_btn.clicked.connect(lambda: self.export_requested.emit("PDF"))
        layout.addWidget(self.export_pdf_btn)
        # Default: PNG only until the page reports active-tab capabilities.
        self.set_export_capabilities({"PNG"})

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setWordWrap(True)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def update_state(self, prediction_tasks: list | tuple | None, map_documents: list | tuple | None) -> None:
        task = active_prediction_task(prediction_tasks)
        document = active_map_document(map_documents)
        self.task_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.map_value.setText(field_value(document, "name", "") or "未选择古地理图")

    def update_ref(self, ref: VizRef | None, payload: VizPayload | None) -> None:
        if ref is None:
            self.source_value.setText("—")
            self.label_value.setText("—")
            self.kind_value.setText("—")
            self.path_value.setText("—")
            return

        self.source_value.setText(ref.source or "—")
        self.label_value.setText(ref.label or (payload.label if payload else "") or "—")
        self.kind_value.setText(ref.kind or "—")

        # Reflect the open asset, not only the global "active" prediction/map.
        if ref.kind == "prediction":
            self.task_value.setText(ref.label or (payload.label if payload else "") or "—")
        if ref.kind == "map":
            self.map_value.setText(ref.label or (payload.label if payload else "") or "—")

        path_or_message = ref.path or ""
        if payload is not None:
            if payload.message:
                path_or_message = payload.message if not path_or_message else f"{path_or_message}\n{payload.message}"
            elif payload.warning and not path_or_message:
                path_or_message = payload.warning
            elif not path_or_message and payload.label:
                path_or_message = payload.label
        self.path_value.setText(path_or_message or "—")

    def set_export_capabilities(self, formats: set[str] | frozenset[str] | list[str]) -> None:
        """Enable PNG/SVG/PDF buttons according to the active tab's honest capabilities."""
        caps = {str(f).upper() for f in (formats or [])}
        self.export_btn.setEnabled("PNG" in caps)
        self.export_svg_btn.setEnabled("SVG" in caps)
        self.export_pdf_btn.setEnabled("PDF" in caps)
        if "SVG" in caps:
            self.export_svg_btn.setToolTip("导出当前 Tab 为 SVG 矢量图")
        else:
            self.export_svg_btn.setToolTip("当前 Tab 不支持 SVG，请切换测井/连井/古地理或改用 PNG")
        if "PDF" in caps:
            self.export_pdf_btn.setToolTip("导出当前 Tab 为 PDF")
        else:
            self.export_pdf_btn.setToolTip("当前 Tab 不支持 PDF，请切换测井/连井/古地理或改用 PNG")
        if "PNG" in caps:
            self.export_btn.setToolTip("导出当前 Tab 截图 PNG")
        else:
            self.export_btn.setToolTip("当前无可导出视图")
