"""地层对比 page: multi-well CrossWell section + tops from prediction facies.

Dual path (#170): Feature Flag / combo selects Legacy geoviz CrossWell or
WellLogEngine multi-well surface (shared Display Depth + Cross-Well Overlay).
Legacy is never deleted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

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
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from geoviz import FormationTop

from paleo_workbench.resources.export_service import default_export_dir
from paleo_workbench.ui.pages.cross_well_export_dialog import CrossWellExportDialog
from paleo_workbench.ui import tokens
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter
from paleo_workbench.viz import welllog_multi_well_adapter as multi_adapter
from paleo_workbench.viz.hosts.cross_well_host import CrossWellHost
from paleo_workbench.viz.models import VizPayload
from paleo_workbench.viz.stratigraphic_correlation_engine import StratigraphicCorrelationEngine
from paleo_workbench.workflow.stratigraphy import active_target_horizon
from paleo_workbench.workflow.stratigraphy_correlation import (
    list_well_log_resources,
    load_correlation_wells,
    load_well_tops,
    match_tops_to_wells,
    prediction_bound_well_ids,
    tops_to_intervals,
)

BackendName = Literal["legacy", "engine"]


class StratigraphyCorrelationPage(QWidget):
    """Multi-well stratigraphic correlation using geo-viz CrossWell engine."""

    section_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StratigraphyCorrelationPage")
        self._project = None
        self._loaded_names: list[str] = []
        self._loaded_logs: list[Any] = []
        self._loaded_resource_ids: list[str] = []
        self._engine_plan: multi_adapter.MultiWellEnginePlan | None = None
        self._engine_report: dict[str, Any] | None = None
        self._engine_error: str | None = None
        self._engine_view: QWidget | None = None
        self._WellLogView = None
        self._backend: BackendName = (
            "engine" if engine_adapter.welllog_engine_env_enabled() else "legacy"
        )
        self.correlation_engine = StratigraphicCorrelationEngine()

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

        backend_row = QHBoxLayout()
        backend_row.setSpacing(tokens.SPACE_2)
        self.status_label = QLabel("从左侧选择井后加载剖面（复用 CrossWell / DTW 引擎）")
        self.status_label.setObjectName("WorkFieldLabel")
        self.status_label.setWordWrap(True)
        backend_row.addWidget(self.status_label, 1)
        self.backend_combo = QComboBox()
        self.backend_combo.setObjectName("StratBackendCombo")
        self.backend_combo.addItem("Legacy (CrossWell)", "legacy")
        self.backend_combo.addItem("WellLogEngine", "engine")
        self.backend_combo.setCurrentIndex(0 if self._backend == "legacy" else 1)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_combo)
        backend_row.addWidget(self.backend_combo, 0)
        center_layout.addLayout(backend_row)

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

        self.view_stack_host = QFrame()
        self.view_stack_host.setObjectName("StratViewStack")
        self.view_stack = QStackedLayout(self.view_stack_host)
        self.view_stack.setContentsMargins(0, 0, 0, 0)

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
        self.view_stack.addWidget(self.scroll_area)  # 0 legacy

        self.engine_host = QFrame()
        self.engine_host.setObjectName("StratEngineHost")
        engine_layout = QVBoxLayout(self.engine_host)
        engine_layout.setContentsMargins(0, 0, 0, 0)
        self.engine_placeholder = QLabel(
            "WellLogEngine 多井路径未启用或不可用。\n"
            "WellLogEngine 默认启用；安装带 multi-well 的 welllog 绑定，"
            "或设 PALEO_USE_WELLLOG_ENGINE=0 使用 Legacy。"
        )
        self.engine_placeholder.setObjectName("EmptyStateLabel")
        self.engine_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.engine_placeholder.setWordWrap(True)
        engine_layout.addWidget(self.engine_placeholder)
        self.view_stack.addWidget(self.engine_host)  # 1 engine

        center_layout.addWidget(self.view_stack_host, 1)
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
        self.export_btn = QPushButton("导出连井剖面")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.clicked.connect(self._export_section)
        right.addWidget(self.export_btn)
        self.export_tops_btn = QPushButton("导出分层顶 CSV")
        self.export_tops_btn.setObjectName("SecondaryButton")
        self.export_tops_btn.clicked.connect(self._export_tops)
        right.addWidget(self.export_tops_btn)
        # Stage-12: versioned correlation interpretation lifecycle
        self.save_interp_btn = QPushButton("保存解释版本")
        self.save_interp_btn.setObjectName("PrimaryButton")
        self.save_interp_btn.setToolTip("将当前分层顶保存为不可变连井对比解释版本")
        self.save_interp_btn.clicked.connect(self.save_interpretation_version)
        right.addWidget(self.save_interp_btn)
        self.open_interp_btn = QPushButton("打开已保存解释")
        self.open_interp_btn.setObjectName("SecondaryButton")
        self.open_interp_btn.clicked.connect(self.open_saved_interpretation)
        right.addWidget(self.open_interp_btn)
        self.restore_interp_btn = QPushButton("恢复已保存版本")
        self.restore_interp_btn.setObjectName("SecondaryButton")
        self.restore_interp_btn.setToolTip("丢弃未保存编辑，重新加载当前已保存版本")
        self.restore_interp_btn.clicked.connect(self.restore_saved_interpretation)
        right.addWidget(self.restore_interp_btn)
        self.interp_status = QLabel("解释: 未保存")
        self.interp_status.setObjectName("WorkFieldValue")
        self.interp_status.setWordWrap(True)
        right.addWidget(self.interp_status)
        self.clear_btn = QPushButton("清空剖面")
        self.clear_btn.setObjectName("SecondaryButton")
        self.clear_btn.clicked.connect(self.clear_section)
        right.addWidget(self.clear_btn)
        content.addWidget(self.action_panel, 0)
        self._correlation_draft = None
        self._project_path: Path | None = None

        outer.addLayout(content, 1)
        self._probe_engine()
        self._sync_backend_stack()

    def set_project(self, project) -> None:
        self._project = project
        self._refresh_interp_status()

    def set_project_path(self, path) -> None:
        """Project file path used for artifact_dir_for (optional)."""
        self._project_path = Path(path) if path else None

    def backend(self) -> str:
        return self._backend

    def engine_plan(self) -> multi_adapter.MultiWellEnginePlan | None:
        return self._engine_plan

    def engine_report(self) -> dict[str, Any] | None:
        return self._engine_report

    def engine_error(self) -> str | None:
        return self._engine_error

    def set_backend(self, name: str) -> None:
        target: BackendName = "engine" if name == "engine" else "legacy"
        if target == self._backend:
            return
        self._backend = target
        idx = 0 if target == "legacy" else 1
        if self.backend_combo.currentIndex() != idx:
            self.backend_combo.blockSignals(True)
            self.backend_combo.setCurrentIndex(idx)
            self.backend_combo.blockSignals(False)
        self._sync_backend_stack()
        if self._loaded_logs:
            self._reload_current_section()

    def _on_backend_combo(self, _index: int) -> None:
        data = self.backend_combo.currentData()
        self.set_backend("engine" if data == "engine" else "legacy")

    def _probe_engine(self) -> None:
        mod, view_cls, _ = engine_adapter.try_import_welllog()
        self._WellLogView = view_cls
        if view_cls is None:
            self._engine_error = "welllog 绑定未安装"
            return
        if not hasattr(view_cls, "submit_multi_well_section"):
            self._engine_error = "welllog 绑定缺少 submit_multi_well_section"
            self._WellLogView = None

    def _sync_backend_stack(self) -> None:
        self.view_stack.setCurrentIndex(0 if self._backend == "legacy" else 1)
        # Correlation toolbar gestures only apply to Legacy CrossWell.
        interactive = self._backend == "legacy"
        for w in (
            self.browse_btn,
            self.pick_btn,
            self.link_btn,
            self.dtw_btn,
            self.undo_btn,
            self.redo_btn,
            self.auto_link_btn,
            self.tops_visible_box,
            self.spacing_slider,
            self.formation_combo,
            self.snap_combo,
            self.track_list,
        ):
            w.setEnabled(interactive)

    def _ensure_engine_view(self) -> QWidget | None:
        if self._engine_view is not None:
            return self._engine_view
        if self._WellLogView is None:
            return None
        try:
            view = self._WellLogView()
        except Exception as exc:  # noqa: BLE001 — surface to placeholder
            self._engine_error = f"{exc.__class__.__name__}: {exc}"
            return None
        self._engine_view = view
        layout = self.engine_host.layout()
        if layout is not None:
            self.engine_placeholder.hide()
            layout.addWidget(view, 1)
        return view

    def _release_engine_view(self) -> None:
        if self._engine_view is not None:
            clear = getattr(self._engine_view, "clear_multi_well_section", None)
            if callable(clear):
                try:
                    clear()
                except Exception:
                    pass
            engine_adapter.clear_engine_view(self._engine_view)
            layout = self.engine_host.layout()
            if layout is not None:
                layout.removeWidget(self._engine_view)
            self._engine_view.setParent(None)
            self._engine_view.deleteLater()
            self._engine_view = None
        self.engine_placeholder.show()

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
        self.cross_host.inner.set_manual_link(self.link_btn.isChecked())

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
            self.status_label.setText("参考拾取点没有关联井")
            return
        ref_well = wells[0]
        ref_depth = ref.depth_for_well(ref_well)

        # Leverage StratigraphicCorrelationEngine for top depth recommendation & confidence
        rec = self.correlation_engine.recommend_top(
            ref_well=ref_well,
            target_well=wells[1] if len(wells) > 1 else ref_well,
            ref_top_depth=ref_depth,
        )

        created = canvas.propagate_pick_via_dtw(ref_well, ref_depth, ref.formation_name)
        self.status_label.setText(
            f"DTW 已为层位 {ref.formation_name} 生成 {len(created)} 个建议拾取 (置信度: {rec.confidence:.2f})"
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
        for label in self.cross_host.inner.track_labels():
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
        self._register_export(path, fmt="csv", label="分层顶 CSV")
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")

    def _project_file_path(self) -> Path:
        if self._project_path is not None:
            return self._project_path
        root = "."
        if self._project is not None:
            root = getattr(self._project.meta, "project_root", ".") or "."
        return Path(root) / "project.paleo.json"

    def _tops_from_canvas(self) -> list:
        """Collect FormationTop models from the live tops_model (scientific only)."""
        from paleo_workbench.workflow.stratigraphy_models import (
            DepthDomain,
            FormationTop as SciTop,
            CorrelationMethod,
        )

        name_to_id = {
            name: rid
            for name, rid in zip(self._loaded_names, self._loaded_resource_ids)
        }
        out = []
        model = self.cross_host.widget.tops_model
        for t in model.all_tops() or []:
            well = str(getattr(t, "well", "") or getattr(t, "well_name", "") or "")
            marker = str(getattr(t, "name", "") or getattr(t, "top_name", "") or "")
            depth = float(getattr(t, "depth", 0.0) or 0.0)
            out.append(
                SciTop(
                    well_id=name_to_id.get(well, ""),
                    well_name=well,
                    marker=marker,
                    depth=depth,
                    depth_domain=DepthDomain.MD,
                    method=CorrelationMethod.IMPORTED,
                )
            )
        return out

    def _resolve_well_version_ids(self) -> list[str]:
        from paleo_workbench.catalog.lifecycle import resolve_resource_version
        from paleo_workbench.catalog.lifecycle import register_resource_input

        ids: list[str] = []
        if self._project is None:
            return ids
        by_id = {r.id: r for r in self._project.resources}
        for rid in self._loaded_resource_ids:
            ref = resolve_resource_version(rid)
            if ref is None and rid in by_id:
                ref = register_resource_input(by_id[rid])
            if ref is not None:
                ids.append(ref.version_id)
        return ids

    def save_interpretation_version(self) -> None:
        """Persist current tops as immutable correlation interpretation (Stage 12)."""
        if self._project is None:
            QMessageBox.warning(self, "保存解释", "未绑定工程")
            return
        tops = self._tops_from_canvas()
        if not tops and not self._loaded_resource_ids:
            QMessageBox.warning(self, "保存解释", "请先加载连井剖面并确保有分层顶")
            return
        from paleo_workbench.workflow.correlation_lifecycle import (
            new_correlation_draft,
            save_correlation_draft,
        )
        from paleo_workbench.workflow.stratigraphy import active_target_horizon
        from paleo_workbench.workflow.stratigraphy_models import DepthDomain

        well_vids = self._resolve_well_version_ids()
        draft = self._correlation_draft
        if draft is None:
            draft = new_correlation_draft(
                name="连井对比",
                well_resource_ids=list(self._loaded_resource_ids),
                well_version_ids=well_vids,
                tops=tops,
                depth_domain=DepthDomain.MD,
                framework_ref=active_target_horizon(self._project) or "",
            )
        else:
            draft.payload.tops = tops
            draft.payload.well_resource_ids = list(self._loaded_resource_ids)
            draft.payload.well_version_ids = well_vids
            draft.bump()
        self._correlation_draft = draft
        ref, msg = save_correlation_draft(
            draft, self._project, self._project_file_path()
        )
        if msg == "noop_unchanged":
            self.interp_status.setText(
                f"解释: 无变更（保持 {getattr(ref, 'current_version_id', '')}）"
            )
            QMessageBox.information(self, "保存解释", "科学内容未变化，未创建新版本")
            return
        if ref is None:
            QMessageBox.warning(self, "保存解释", f"保存失败: {msg}")
            return
        self.interp_status.setText(
            f"解释: 已保存 {ref.current_version_id or ''}（{msg}）"
        )
        QMessageBox.information(
            self,
            "保存解释",
            f"已保存连井对比版本\n{ref.current_version_id or ''}",
        )
        self.section_updated.emit()

    def open_saved_interpretation(self) -> None:
        """Load latest project correlation interpretation as working copy."""
        if self._project is None:
            QMessageBox.warning(self, "打开解释", "未绑定工程")
            return
        from paleo_workbench.workflow.correlation_lifecycle import (
            restore_draft_from_project_ref,
        )

        draft = restore_draft_from_project_ref(
            self._project, self._project_file_path()
        )
        if draft is None:
            QMessageBox.information(self, "打开解释", "工程中尚无已保存的连井对比解释")
            return
        self._correlation_draft = draft
        self._apply_draft_tops_to_canvas(draft)
        self.interp_status.setText(
            f"解释: 已打开工作副本（父版本 {draft.payload.parent_version_id or '—'}）"
        )
        self.section_updated.emit()

    def restore_saved_interpretation(self) -> None:
        """Discard unsaved draft edits and reload immutable selected version."""
        if self._project is None:
            return
        if self._correlation_draft is not None and self._correlation_draft.dirty:
            ans = QMessageBox.question(
                self,
                "恢复已保存版本",
                "将丢弃未保存的分层编辑，确认？",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        self.open_saved_interpretation()

    def _apply_draft_tops_to_canvas(self, draft) -> None:
        """Push scientific tops into CrossWell tops_model when possible."""
        try:
            canvas = self.cross_host.widget
            canvas.tops_model.clear()
            for t in draft.payload.tops:
                canvas.tops_model.add_top(
                    FormationTop(t.well_name or t.well_id, t.marker, float(t.depth))
                )
            self.formation_combo.clear()
            self.formation_combo.addItems(canvas.tops_model.formation_names())
        except Exception:
            pass

    def _refresh_interp_status(self) -> None:
        if self._project is None:
            self.interp_status.setText("解释: 未绑定工程")
            return
        refs = list(getattr(self._project, "correlation_interpretations", None) or [])
        if not refs:
            self.interp_status.setText("解释: 未保存")
            return
        ref = refs[-1]
        self.interp_status.setText(
            f"解释: 当前 {ref.current_version_id or '—'} / {ref.name}"
        )

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
        self._loaded_logs = list(logs)
        self._loaded_names = list(names)
        self._loaded_resource_ids = list(ids)[: len(logs)]
        ok, top_notices, path_msg = self._apply_loaded_section()
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
        msg = f"已加载 {len(names)} 口井 ({path_msg})"
        if warnings:
            msg += f"；警告 {len(warnings)} 项"
        if top_notices:
            msg += "；" + "；".join(top_notices[:2])
        if self._engine_error and self._backend == "engine":
            msg += f"；Engine: {self._engine_error}"
        self.status_label.setText(msg if ok else "加载失败")
        self.section_updated.emit()

    def _reload_current_section(self) -> None:
        if not self._loaded_logs:
            self._sync_backend_stack()
            return
        ok, _notices, path_msg = self._apply_loaded_section()
        self.status_label.setText(
            f"已切换到 {path_msg}" if ok else f"切换失败: {self._engine_error or path_msg}"
        )

    def _apply_loaded_section(self) -> tuple[bool, list[str], str]:
        """Apply current _loaded_* to the active backend. Returns (ok, notices, path)."""
        logs = self._loaded_logs
        names = self._loaded_names
        ids = self._loaded_resource_ids
        top_notices: list[str] = []
        if self._backend == "engine":
            ok = self._apply_engine_section(logs, names, ids)
            return ok, top_notices, "WellLogEngine"
        payload = VizPayload(
            kind="cross_well",
            label="地层对比",
            well_logs=logs,
            well_names=names,
        )
        ok = self.cross_host.apply(payload)
        if ok:
            top_notices = self._inject_well_tops(names)
            self._refresh_track_list()
            # Keep spacing slider in sync for parity snapshot.
            self.cross_host.inner.set_well_spacing(self.spacing_slider.value())
        # Always build engine plan for parity even on Legacy (dual-path tests).
        self._build_engine_plan_only(logs, names, ids)
        return ok, top_notices, "Legacy"

    def _build_engine_plan_only(
        self, logs: list[Any], names: list[str], resource_ids: list[str]
    ) -> None:
        tops_by_well: dict[str, list[tuple[str, float]]] = {}
        if self._project is not None:
            raw_tops, _ = load_well_tops(self._project)
            matched, _ = match_tops_to_wells(raw_tops, names)
            tops_by_well = matched
        horizon = ""
        if self._project is not None:
            horizon = active_target_horizon(self._project) or ""
        self._engine_plan = multi_adapter.adapt_multi_well_section(
            logs,
            names,
            resource_ids=resource_ids,
            tops_by_well=tops_by_well,
            spacing_px=int(self.spacing_slider.value()),
            datum_mode="horizon" if horizon else "md",
            target_horizon=horizon,
        )

    def _apply_engine_section(
        self, logs: list[Any], names: list[str], resource_ids: list[str]
    ) -> bool:
        self._engine_error = None
        self._engine_report = None
        self._build_engine_plan_only(logs, names, resource_ids)
        plan = self._engine_plan
        if plan is None or not plan.wells:
            self._engine_error = "多井计划为空"
            self.engine_placeholder.setText(
                f"WellLogEngine 无法构建多井计划。\n{self._engine_error}"
            )
            self.engine_placeholder.show()
            return False
        view = self._ensure_engine_view()
        if view is None:
            self._engine_error = self._engine_error or "WellLogView 不可用"
            self.engine_placeholder.setText(
                f"WellLogEngine 不可用。\n{self._engine_error}\n"
                "可切换回 Legacy。"
            )
            self.engine_placeholder.show()
            return False
        try:
            self._engine_report = multi_adapter.submit_multi_well_plan(view, plan)
        except Exception as exc:  # noqa: BLE001
            self._engine_error = f"{exc.__class__.__name__}: {exc}"
            self.engine_placeholder.setText(
                f"WellLogEngine 加载失败。\n{self._engine_error}"
            )
            self.engine_placeholder.show()
            return False
        self.engine_placeholder.hide()
        view.show()
        return True

    def clear_section(self) -> None:
        self.cross_host.clear()
        canvas = self.cross_host.widget
        canvas.tops_model.clear()
        canvas.picks_model.clear()
        self.formation_combo.clear()
        self.track_list.clear()
        self._release_engine_view()
        self._loaded_names = []
        self._loaded_logs = []
        self._loaded_resource_ids = []
        self._engine_plan = None
        self._engine_report = None
        self._engine_error = None
        self.loaded_value.setText("已加载: 0 口井")
        self.tops_value.setText("相/顶: —")
        self.status_label.setText("剖面已清空")

    def _export_section(self) -> None:
        if self._backend == "engine":
            if self._engine_view is None or self._engine_report is None:
                QMessageBox.warning(self, "导出", "请先加载 WellLogEngine 连井剖面")
                return
            # Engine path: grab framebuffer PNG (same limitation as #169 single-well).
            start_dir = default_export_dir(
                Path(self._project.meta.project_root) / "x.paleo.json"
                if self._project and self._project.meta.project_root not in ("", ".")
                else None
            )
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出连井剖面 (Engine PNG)",
                str(start_dir / "cross_well_engine.png"),
                "PNG (*.png)",
            )
            if not path:
                return
            try:
                pix = self._engine_view.grab()
                if pix.isNull() or not pix.save(path, "PNG"):
                    raise RuntimeError("WellLogEngine 抓屏失败")
            except Exception as exc:
                QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
                return
            self._register_export(path, fmt="png", label="连井剖面 (Engine PNG)")
            QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")
            return

        inner = self.cross_host.inner
        if not getattr(inner, "_canvases", None):
            QMessageBox.warning(self, "导出", "请先加载连井剖面")
            return
        dialog = CrossWellExportDialog(self)
        if not dialog.exec():
            return
        opts = dialog.options()
        fmt = opts["fmt"]
        start_dir = default_export_dir(
            Path(self._project.meta.project_root) / "x.paleo.json"
            if self._project and self._project.meta.project_root not in ("", ".")
            else None
        )
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出连井剖面",
            str(start_dir / f"cross_well_correlation.{fmt}"),
            f"{fmt.upper()} (*.{fmt})",
        )
        if not path:
            return
        try:
            inner.export_composite(
                path,
                fmt=fmt,
                dpi=opts["dpi"],
                width_px=opts["width_px"],
                page_size=opts["page_size"],
            )
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"{exc.__class__.__name__}: {exc}")
            return
        self._register_export(path, fmt=fmt, label="连井剖面")
        QMessageBox.information(self, "导出完成", f"已导出: {Path(path).name}")

    def _register_export(
        self, path: str, *, fmt: str, label: str
    ) -> None:
        """Best-effort OUTPUT DataVersion registration for this page's exports.

        The catalog may be absent (no project open) — registration then
        no-ops. Lineage links to the loaded well resources so the exported
        file traces back to the source RAW data.
        """
        if self._project is None:
            return
        try:
            from paleo_workbench.catalog.lifecycle import register_export_output

            register_export_output(
                name=f"{label} export",
                output_path=str(path),
                fmt=fmt,
                source_task_ids=list(self._loaded_resource_ids),
                catalog=None,
            )
        except Exception:
            # Provenance is best-effort; never break the export flow.
            pass
