"""地层对比 page: multi-well CrossWell section + tops from prediction facies."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from geoviz import FormationTop

from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui import tokens
from paleo_workbench.viz.hosts.cross_well_host import CrossWellHost
from paleo_workbench.viz.models import VizPayload
from paleo_workbench.workflow.stratigraphy import active_target_horizon
from paleo_workbench.workflow.stratigraphy_correlation import (
    list_well_log_resources,
    load_correlation_wells,
    load_well_tops,
    match_tops_to_wells,
    prediction_bound_well_ids,
    tops_to_intervals,
)


class StratigraphyCorrelationPage(QWidget):
    """Multi-well stratigraphic correlation using geo-viz CrossWell engine."""

    section_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StratigraphyCorrelationPage")
        self._project = None
        self._loaded_names: list[str] = []
        self._manual_link_on = False

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

        # Toolbar: correlation modes and engine interactions
        toolbar = QHBoxLayout()
        toolbar.setSpacing(tokens.SPACE_2)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.browse_btn = QPushButton("浏览")
        self.pick_btn = QPushButton("拾取")
        self.link_btn = QPushButton("连线")
        for btn in (self.browse_btn, self.pick_btn, self.link_btn):
            btn.setObjectName("SecondaryButton")
            btn.setCheckable(True)
            self.mode_group.addButton(btn)
            btn.toggled.connect(self._on_mode_changed)
            toolbar.addWidget(btn)
        self.browse_btn.setChecked(True)

        self.formation_combo = QComboBox()
        self.formation_combo.setEditable(True)
        self.formation_combo.setPlaceholderText("拾取层位")
        self.formation_combo.setMinimumWidth(110)
        self.formation_combo.currentTextChanged.connect(self._on_formation_changed)
        toolbar.addWidget(self.formation_combo)

        self.snap_combo = QComboBox()
        self.snap_combo.addItem("不吸附", "none")
        self.snap_combo.addItem("波峰", "max")
        self.snap_combo.addItem("波谷", "min")
        self.snap_combo.currentIndexChanged.connect(self._on_snap_changed)
        toolbar.addWidget(self.snap_combo)

        self.dtw_btn = QPushButton("DTW 传播")
        self.dtw_btn.setObjectName("SecondaryButton")
        self.dtw_btn.clicked.connect(self._run_dtw)
        toolbar.addWidget(self.dtw_btn)
        self.undo_btn = QPushButton("撤销")
        self.undo_btn.setObjectName("SecondaryButton")
        self.undo_btn.clicked.connect(self._undo_pick)
        toolbar.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("重做")
        self.redo_btn.setObjectName("SecondaryButton")
        self.redo_btn.clicked.connect(self._redo_pick)
        toolbar.addWidget(self.redo_btn)
        self.auto_link_btn = QPushButton("自动连线")
        self.auto_link_btn.setObjectName("SecondaryButton")
        self.auto_link_btn.clicked.connect(self._run_auto_link)
        toolbar.addWidget(self.auto_link_btn)

        self.tops_visible_box = QCheckBox("分层顶线")
        self.tops_visible_box.setChecked(True)
        self.tops_visible_box.toggled.connect(self._on_tops_visible)
        toolbar.addWidget(self.tops_visible_box)

        toolbar.addWidget(QLabel("间距"))
        self.spacing_slider = QSlider(Qt.Orientation.Horizontal)
        self.spacing_slider.setRange(50, 300)
        self.spacing_slider.setValue(150)
        self.spacing_slider.setFixedWidth(90)
        self.spacing_slider.valueChanged.connect(self._on_spacing_changed)
        toolbar.addWidget(self.spacing_slider)
        toolbar.addStretch()
        center_layout.addLayout(toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("StratCrossScrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll_area.setWidget(self.cross_host.widget)

        center_layout.addWidget(self.scroll_area, 1)
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
        track_title = QLabel("轨道显隐")
        track_title.setObjectName("MapDockTitle")
        right.addWidget(track_title)
        self.track_list = QListWidget()
        self.track_list.setObjectName("WorkListWidget")
        self.track_list.itemChanged.connect(self._on_track_item_changed)
        right.addWidget(self.track_list)
        right.addStretch()
        self.export_btn = QPushButton("导出连井 SVG")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.clicked.connect(self._export_section)
        right.addWidget(self.export_btn)
        self.export_tops_btn = QPushButton("导出分层顶 CSV")
        self.export_tops_btn.setObjectName("SecondaryButton")
        self.export_tops_btn.clicked.connect(self._export_tops)
        right.addWidget(self.export_tops_btn)
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

    def _on_mode_changed(self) -> None:
        canvas = self.cross_host.widget
        canvas.pick_mode = self.pick_btn.isChecked()
        want_link = self.link_btn.isChecked()
        if want_link != self._manual_link_on:
            self.cross_host.inner.toggle_manual_link()
            self._manual_link_on = want_link

    def _on_formation_changed(self, text: str) -> None:
        self.cross_host.widget.active_formation = text.strip() or None

    def _on_snap_changed(self) -> None:
        self.cross_host.widget.snap_type = self.snap_combo.currentData()

    def _on_tops_visible(self, checked: bool) -> None:
        self.cross_host.widget.set_tops_visible(checked)

    def _on_spacing_changed(self, value: int) -> None:
        self.cross_host.inner.set_well_spacing(value)

    def _undo_pick(self) -> None:
        self.cross_host.widget.picks_model.undo()

    def _redo_pick(self) -> None:
        self.cross_host.widget.picks_model.redo()

    def _run_auto_link(self) -> None:
        self.cross_host.inner.auto_link()
        self.status_label.setText("已按同名分层自动连线")

    def _run_dtw(self) -> None:
        canvas = self.cross_host.widget
        picks = canvas.picks_model.all_picks()
        if not picks:
            self.status_label.setText("请先在拾取模式下添加一个参考拾取点")
            return
        ref = picks[-1]
        wells = ref.connected_wells()
        if not wells:
            return
        ref_well = wells[0]
        ref_depth = ref.depth_for_well(ref_well)
        created = canvas.propagate_pick_via_dtw(ref_well, ref_depth, ref.formation_name)
        self.status_label.setText(
            f"DTW 已为层位 {ref.formation_name} 生成 {len(created)} 个建议拾取"
            "（点击接受 / 右键拒绝）"
        )

    def _on_track_item_changed(self, item: QListWidgetItem) -> None:
        visible = item.checkState() == Qt.CheckState.Checked
        self.cross_host.inner.set_track_visible_by_label(item.text(), visible)

    def _inject_well_tops(self, names: list[str]) -> list[str]:
        """Inject 井分层 tops into tops model + formation data. Returns notices."""
        canvas = self.cross_host.widget
        canvas.tops_model.clear()
        canvas.picks_model.clear()
        notices: list[str] = []
        if self._project is None:
            return notices
        tops_by_well, warnings = load_well_tops(self._project)
        notices.extend(warnings)
        matched, unmatched = match_tops_to_wells(tops_by_well, names)
        for well, tops in matched.items():
            for top_name, depth in tops:
                canvas.tops_model.add_top(FormationTop(well, top_name, depth))
            self.cross_host.inner.set_formation_data(well, tops_to_intervals(tops))
        if unmatched:
            notices.append("分层井未在剖面中: " + ", ".join(unmatched))
        self.formation_combo.clear()
        self.formation_combo.addItems(canvas.tops_model.formation_names())
        return notices

    def _refresh_track_list(self) -> None:
        self.track_list.blockSignals(True)
        self.track_list.clear()
        seen: list[str] = []
        for canvas in self.cross_host.inner._canvases:
            for track in canvas.tracks:
                label = track.label or ""
                if label and label not in seen:
                    seen.append(label)
        for label in seen:
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.track_list.addItem(item)
        self.track_list.blockSignals(False)

    def _export_tops(self) -> None:
        model = self.cross_host.widget.tops_model
        if not model.all_tops():
            QMessageBox.warning(self, "导出", "没有分层顶数据")
            return
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出分层顶 CSV",
            str(start_dir / "well_tops.csv"),
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            model.save_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")

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
        top_notices = self._inject_well_tops(names)
        self._refresh_track_list()
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
        if top_notices:
            msg += "；" + "；".join(top_notices[:2])
        self.status_label.setText(msg if ok else "加载失败")
        self.section_updated.emit()

    def clear_section(self) -> None:
        self.cross_host.clear()
        canvas = self.cross_host.widget
        canvas.tops_model.clear()
        canvas.picks_model.clear()
        self.formation_combo.clear()
        self.track_list.clear()
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
