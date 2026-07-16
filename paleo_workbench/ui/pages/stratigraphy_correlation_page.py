"""地层对比 page: multi-well CrossWell section + tops from prediction facies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui import tokens
from paleo_workbench.viz.hosts.cross_well_host import CrossWellHost
from paleo_workbench.viz.models import VizPayload
from paleo_workbench.workflow.stratigraphy import active_target_horizon
from paleo_workbench.workflow.stratigraphy_correlation import (
    list_well_log_resources,
    load_correlation_wells,
    prediction_bound_well_ids,
)


class StratigraphyCorrelationPage(QWidget):
    """Multi-well stratigraphic correlation using geo-viz CrossWell engine."""

    section_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StratigraphyCorrelationPage")
        self._project = None
        self._loaded_names: list[str] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_4)

        content = QHBoxLayout()
        content.setSpacing(tokens.SPACE_4)

        # Left: well picker
        self.well_panel = QFrame()
        self.well_panel.setObjectName("StratWellPanel")
        self.well_panel.setFixedWidth(240)
        left = QVBoxLayout(self.well_panel)
        left.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        left.setSpacing(tokens.SPACE_2)
        title = QLabel("对比井选择")
        title.setObjectName("MapDockTitle")
        left.addWidget(title)
        self.horizon_value = QLabel("目标层位: —")
        self.horizon_value.setObjectName("WorkFieldValue")
        left.addWidget(self.horizon_value)
        self.well_list = QListWidget()
        self.well_list.setObjectName("WorkListWidget")
        left.addWidget(self.well_list, 1)
        self.load_btn = QPushButton("加载连井剖面")
        self.load_btn.setObjectName("PrimaryButton")
        self.load_btn.clicked.connect(self.load_section)
        left.addWidget(self.load_btn)
        self.select_bound_btn = QPushButton("选用预测绑定井")
        self.select_bound_btn.setObjectName("SecondaryButton")
        self.select_bound_btn.clicked.connect(self._select_bound_wells)
        left.addWidget(self.select_bound_btn)
        content.addWidget(self.well_panel, 0)

        # Center: CrossWell host
        self.cross_host = CrossWellHost()
        center = QFrame()
        center.setObjectName("StratCrossHost")
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        self.section_title = QLabel("连井地层对比")
        self.section_title.setObjectName("MapDockTitle")
        center_layout.addWidget(self.section_title)
        self.status_label = QLabel("从左侧选择井后加载剖面（复用 CrossWell / DTW 引擎）")
        self.status_label.setObjectName("WorkFieldLabel")
        self.status_label.setWordWrap(True)
        center_layout.addWidget(self.status_label)
        center_layout.addWidget(self.cross_host.widget, 1)
        content.addWidget(center, 1)

        # Right: actions
        self.action_panel = QFrame()
        self.action_panel.setObjectName("StratActionPanel")
        self.action_panel.setFixedWidth(220)
        right = QVBoxLayout(self.action_panel)
        right.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        right.setSpacing(tokens.SPACE_2)
        a_title = QLabel("对比操作")
        a_title.setObjectName("MapDockTitle")
        right.addWidget(a_title)
        self.loaded_value = QLabel("已加载: 0 口井")
        self.loaded_value.setObjectName("WorkFieldValue")
        right.addWidget(self.loaded_value)
        self.tops_value = QLabel("相/顶: —")
        self.tops_value.setObjectName("WorkFieldValue")
        self.tops_value.setWordWrap(True)
        right.addWidget(self.tops_value)
        right.addStretch()
        self.export_btn = QPushButton("导出连井 SVG")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.clicked.connect(self._export_section)
        right.addWidget(self.export_btn)
        self.clear_btn = QPushButton("清空剖面")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.clicked.connect(self.clear_section)
        right.addWidget(self.clear_btn)
        content.addWidget(self.action_panel, 0)

        outer.addLayout(content, 1)

    def set_project(self, project) -> None:
        self._project = project

    def update_state(self, project=None) -> None:
        if project is not None:
            self._project = project
        if self._project is None:
            self.well_list.clear()
            self.horizon_value.setText("目标层位: —")
            return
        horizon = active_target_horizon(self._project) or "—"
        self.horizon_value.setText(f"目标层位: {horizon}")
        self.section_title.setText(f"连井地层对比 · {horizon}" if horizon != "—" else "连井地层对比")

        selected = {
            self.well_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.well_list.count())
            if self.well_list.item(i).checkState() == Qt.CheckState.Checked
        }
        self.well_list.clear()
        for resource in list_well_log_resources(self._project):
            item = QListWidgetItem(resource.name or resource.id)
            item.setData(Qt.ItemDataRole.UserRole, resource.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if resource.id in selected
                else Qt.CheckState.Unchecked
            )
            self.well_list.addItem(item)

    def selected_resource_ids(self) -> list[str]:
        ids: list[str] = []
        for i in range(self.well_list.count()):
            item = self.well_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                rid = item.data(Qt.ItemDataRole.UserRole)
                if rid:
                    ids.append(str(rid))
        return ids

    def _select_bound_wells(self) -> None:
        if self._project is None:
            return
        bound = set(prediction_bound_well_ids(self._project))
        if not bound:
            # Fall back: check first few wells
            for i in range(min(4, self.well_list.count())):
                self.well_list.item(i).setCheckState(Qt.CheckState.Checked)
            return
        for i in range(self.well_list.count()):
            item = self.well_list.item(i)
            rid = item.data(Qt.ItemDataRole.UserRole)
            item.setCheckState(
                Qt.CheckState.Checked if rid in bound else Qt.CheckState.Unchecked
            )

    def load_section(self) -> None:
        if self._project is None:
            QMessageBox.warning(self, "地层对比", "未绑定工程")
            return
        ids = self.selected_resource_ids()
        if not ids:
            # Auto-select up to 4 wells if none checked
            for i in range(min(4, self.well_list.count())):
                self.well_list.item(i).setCheckState(Qt.CheckState.Checked)
            ids = self.selected_resource_ids()
        if not ids:
            QMessageBox.information(self, "地层对比", "工程中没有测井 LAS 资源")
            return
        logs, names, warnings = load_correlation_wells(
            self._project, resource_ids=ids, max_wells=8
        )
        if not logs:
            QMessageBox.warning(
                self,
                "地层对比",
                "未能加载任何井曲线\n" + "\n".join(warnings[:5]),
            )
            return
        payload = VizPayload(
            kind="cross_well",
            label="地层对比",
            well_logs=logs,
            well_names=names,
        )
        ok = self.cross_host.apply(payload)
        self._loaded_names = names
        self.loaded_value.setText(f"已加载: {len(names)} 口井")
        tops_bits = []
        for data, name in zip(logs, names):
            n_facies = len(getattr(data, "facies", None) or [])
            n_litho = len(getattr(data, "lithology", None) or [])
            if n_facies or n_litho:
                tops_bits.append(f"{name}: 相{n_facies}/岩性{n_litho}")
        self.tops_value.setText(
            " · ".join(tops_bits) if tops_bits else "无预测相/岩性 tops（可先运行测井预测）"
        )
        msg = f"已加载 {len(names)} 口井"
        if warnings:
            msg += f"；警告 {len(warnings)} 项"
        self.status_label.setText(msg if ok else "加载失败")
        self.section_updated.emit()

    def clear_section(self) -> None:
        self.cross_host.clear()
        self._loaded_names = []
        self.loaded_value.setText("已加载: 0 口井")
        self.tops_value.setText("相/顶: —")
        self.status_label.setText("剖面已清空")

    def _export_section(self) -> None:
        inner = self.cross_host.inner
        if not getattr(inner, "_canvases", None):
            QMessageBox.warning(self, "导出", "请先加载连井剖面")
            return
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出连井剖面 SVG",
            str(start_dir / "cross_well_correlation.svg"),
            "SVG (*.svg)",
        )
        if not path:
            return
        try:
            inner.export_composite(str(path), fmt="svg")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")
