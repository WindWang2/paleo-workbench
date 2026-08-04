"""Main window chrome for Well Log Workstation — L layout (#216–#222)."""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from well_log_workstation.correlation_canvas import CorrelationCanvas
from well_log_workstation.correlation_links import (
    HorizonLink,
    make_horizon_link,
    match_tops_by_name,
)
from well_log_workstation.crs_dialog import CoordinateReferenceDialog
from well_log_workstation.engine_bridge import (
    EngineSubmitError,
    EngineUnavailable,
    create_well_log_view,
    engine_available,
    load_presentation_into_view,
    probe_engine,
    submit_multi_well_presentations,
)
from well_log_workstation.export_plot import (
    ExportError,
    export_presentation_pdf,
    export_presentation_svg,
)
from well_log_workstation.fence_view import FenceView
from well_log_workstation.las_import import LasImportError, import_las_into_workspace
from well_log_workstation.multi_track_canvas import MultiTrackCanvas
from well_log_workstation.plane_map_view import PlaneMapView
from well_log_workstation.plot_document import (
    PlotDocument,
    create_correlation_plot,
    create_fence_3d_plot,
    create_plane_map_plot,
    create_single_well_plot,
    load_plot_document,
    save_plot_document,
)
from well_log_workstation.qt_platform import effective_qt_platform_hint
from well_log_workstation.session_store import HostSessionStore
from well_log_workstation.template_model import (
    HostPresentation,
    PlotTemplate,
    apply_template,
    get_builtin_template,
    list_builtin_templates,
)
from well_log_workstation.three_d_bridge import probe_3d
from well_log_workstation.tops_model import (
    FormationTop,
    TopsError,
    import_tops_from_json_file,
    load_tops_for_well,
    make_stub_tops,
    save_tops_for_well,
)
from well_log_workstation.workspace import (
    Workspace,
    WorkspaceError,
    create_workspace,
    open_workspace,
)


class WellLogWorkstationWindow(QMainWindow):
    """Log-first shell: left tree · center document tabs · right inspector."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("WellLogWorkstationWindow")
        self.setWindowTitle("Well Log Workstation")
        self.resize(1280, 800)

        self._workspace: Workspace | None = None
        self.session = HostSessionStore()
        self._selected_well_id: str | None = None
        self._active_plot_id: str | None = None
        self._active_plot_type: str | None = None
        self._presentation: HostPresentation | None = None
        self._correlation_presentations: list[HostPresentation] = []
        self._correlation_links: list[HorizonLink] = []
        self._link_pick_first: tuple[str, FormationTop] | None = None
        self._active_tops: list[FormationTop] = []
        self._tops_diagnostics: list[str] = []
        self._templates: list[PlotTemplate] = list_builtin_templates()
        # #227: prefer native WellLogView as primary single-well surface when
        # welllog is available. Host MultiTrackCanvas is always the fallback.
        self._prefer_engine_canvas = self._default_prefer_engine()
        self._primary_surface: str = "host"  # "host" | "engine"
        self._engine_last_error: str | None = None

        self._build_menus()
        self._build_body()
        self._build_status()
        self._populate_templates()
        self._refresh_tree()
        self._refresh_tops_list()

    @property
    def workspace(self) -> Workspace | None:
        return self._workspace

    @property
    def active_presentation(self) -> HostPresentation | None:
        return self._presentation

    @property
    def active_plot_id(self) -> str | None:
        return self._active_plot_id

    @property
    def active_plot_type(self) -> str | None:
        return self._active_plot_type

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("文件")
        file_menu.setObjectName("Menu_文件")
        act_new = file_menu.addAction("新建工区…")
        act_new.setObjectName("Action_NewWorkspace")
        act_new.triggered.connect(self._on_new_workspace)
        act_open = file_menu.addAction("打开工区…")
        act_open.setObjectName("Action_OpenWorkspace")
        act_open.triggered.connect(self._on_open_workspace)
        file_menu.addSeparator()
        self._act_import_las = file_menu.addAction("导入 LAS…")
        self._act_import_las.setObjectName("Action_ImportLas")
        self._act_import_las.triggered.connect(self._on_import_las)
        self._act_import_las.setEnabled(False)
        file_menu.addSeparator()
        act_quit = file_menu.addAction("退出")
        act_quit.triggered.connect(self.close)

        plot_menu = bar.addMenu("图件")
        plot_menu.setObjectName("Menu_图件")
        self._act_new_single_plot = plot_menu.addAction("新建单井分析图…")
        self._act_new_single_plot.setObjectName("Action_NewSingleWellPlot")
        self._act_new_single_plot.triggered.connect(self._on_new_single_well_plot)
        self._act_new_single_plot.setEnabled(False)
        self._act_new_correlation = plot_menu.addAction("新建地层对比图…")
        self._act_new_correlation.setObjectName("Action_NewCorrelationPlot")
        self._act_new_correlation.triggered.connect(self._on_new_correlation_plot)
        self._act_new_correlation.setEnabled(False)
        # Phase-2 PR-C: plane_map + fence_3d (section/composite land in
        # later PR-C batches; their menu items are stubs until then).
        self._act_new_plane_map = plot_menu.addAction("新建平面图…")
        self._act_new_plane_map.setObjectName("Action_NewPlaneMapPlot")
        self._act_new_plane_map.triggered.connect(self._on_new_plane_map_plot)
        self._act_new_plane_map.setEnabled(False)
        self._act_new_fence_3d = plot_menu.addAction("新建三维栅状图…")
        self._act_new_fence_3d.setObjectName("Action_NewFence3dPlot")
        self._act_new_fence_3d.triggered.connect(self._on_new_fence_3d_plot)
        self._act_new_fence_3d.setEnabled(False)
        self._act_new_section = plot_menu.addAction("新建油藏剖面…")
        self._act_new_section.setObjectName("Action_NewSectionPlot")
        self._act_new_section.setEnabled(False)  # wired in PR-C3
        self._act_new_composite = plot_menu.addAction("新建油藏综合图…")
        self._act_new_composite.setObjectName("Action_NewCompositePlot")
        self._act_new_composite.setEnabled(False)  # wired in PR-C4
        plot_menu.addSeparator()
        self._act_set_crs = plot_menu.addAction("坐标系设置（CRS）…")
        self._act_set_crs.setObjectName("Action_SetCoordinateReference")
        self._act_set_crs.triggered.connect(self._on_set_coordinate_reference)
        self._act_set_crs.setEnabled(False)
        self._act_auto_links = plot_menu.addAction("按层位名自动连线")
        self._act_auto_links.setObjectName("Action_AutoHorizonLinks")
        self._act_auto_links.triggered.connect(self._on_auto_horizon_links)
        self._act_auto_links.setEnabled(False)
        self._act_clear_links = plot_menu.addAction("清除对比连线")
        self._act_clear_links.setObjectName("Action_ClearHorizonLinks")
        self._act_clear_links.triggered.connect(self._on_clear_horizon_links)
        self._act_clear_links.setEnabled(False)
        self._act_pick_links = plot_menu.addAction("点选层位连线")
        self._act_pick_links.setObjectName("Action_PickHorizonLinks")
        self._act_pick_links.setCheckable(True)
        self._act_pick_links.triggered.connect(self._on_toggle_pick_links)
        self._act_pick_links.setEnabled(False)
        plot_menu.addSeparator()
        self._act_prefer_engine = plot_menu.addAction("优先使用引擎画布")
        self._act_prefer_engine.setObjectName("Action_PreferEngineCanvas")
        self._act_prefer_engine.setCheckable(True)
        self._act_prefer_engine.setChecked(self._prefer_engine_canvas)
        self._act_prefer_engine.triggered.connect(self._on_toggle_prefer_engine)
        self._act_engine_preview = plot_menu.addAction("刷新/打开引擎视图…")
        self._act_engine_preview.setObjectName("Action_EnginePreview")
        self._act_engine_preview.triggered.connect(self._on_engine_preview)
        self._act_engine_preview.setEnabled(False)
        self._act_engine_corr = plot_menu.addAction("引擎对比预览…")
        self._act_engine_corr.setObjectName("Action_EngineCorrelationPreview")
        self._act_engine_corr.triggered.connect(self._on_engine_correlation_preview)
        self._act_engine_corr.setEnabled(False)

        template_menu = bar.addMenu("图版")
        template_menu.setObjectName("Menu_图版")
        self._act_apply_template = template_menu.addAction("应用当前图版到选中井")
        self._act_apply_template.setObjectName("Action_ApplyTemplate")
        self._act_apply_template.triggered.connect(self._on_apply_template)
        self._act_apply_template.setEnabled(False)

        export_menu = bar.addMenu("导出")
        export_menu.setObjectName("Menu_导出")
        self._act_export_svg = export_menu.addAction("导出 SVG…")
        self._act_export_svg.setObjectName("Action_ExportSvg")
        self._act_export_svg.triggered.connect(self._on_export_svg)
        self._act_export_svg.setEnabled(False)
        self._act_export_pdf = export_menu.addAction("导出 PDF…")
        self._act_export_pdf.setObjectName("Action_ExportPdf")
        self._act_export_pdf.triggered.connect(self._on_export_pdf)
        self._act_export_pdf.setEnabled(False)

        tops_menu = bar.addMenu("层位")
        tops_menu.setObjectName("Menu_层位")
        self._act_import_tops = tops_menu.addAction("导入层位 JSON…")
        self._act_import_tops.setObjectName("Action_ImportTops")
        self._act_import_tops.triggered.connect(self._on_import_tops)
        self._act_import_tops.setEnabled(False)
        self._act_stub_tops = tops_menu.addAction("生成示例层位")
        self._act_stub_tops.setObjectName("Action_StubTops")
        self._act_stub_tops.triggered.connect(self._on_stub_tops)
        self._act_stub_tops.setEnabled(False)
        tops_menu.addSeparator()
        self._act_pick_tops = tops_menu.addAction("拾取层位（单击图道）")
        self._act_pick_tops.setObjectName("Action_PickTops")
        self._act_pick_tops.setCheckable(True)
        self._act_pick_tops.triggered.connect(self._on_toggle_pick_tops)
        self._act_pick_tops.setEnabled(False)
        self._act_add_top = tops_menu.addAction("按深度添加层位…")
        self._act_add_top.setObjectName("Action_AddTopByDepth")
        self._act_add_top.triggered.connect(self._on_add_top_by_depth)
        self._act_add_top.setEnabled(False)

        help_menu = bar.addMenu("帮助")
        help_menu.setObjectName("Menu_帮助")
        act_about = help_menu.addAction("关于…")
        act_about.setEnabled(False)

    def _build_body(self) -> None:
        root = QWidget()
        root.setObjectName("ShellRoot")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setObjectName("ShellSplitter")
        split.addWidget(self._build_left())
        split.addWidget(self._build_center())
        split.addWidget(self._build_right())
        split.setSizes([240, 760, 280])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        outer.addWidget(split, 1)

    def _build_left(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("LeftPane")
        layout = QVBoxLayout(pane)
        self.left_title = QLabel("工区")
        self.left_title.setObjectName("LeftPaneTitle")
        layout.addWidget(self.left_title)

        self.workspace_tree = QTreeWidget()
        self.workspace_tree.setObjectName("WorkspaceTree")
        self.workspace_tree.setHeaderLabels(["名称"])
        self.workspace_tree.currentItemChanged.connect(self._on_tree_selection)
        self.workspace_tree.itemDoubleClicked.connect(self._on_tree_double_click)
        layout.addWidget(self.workspace_tree, 1)
        return pane

    def _build_center(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("CenterPane")
        layout = QVBoxLayout(pane)

        self.document_tabs = QTabWidget()
        self.document_tabs.setObjectName("DocumentTabs")
        self.document_tabs.setTabsClosable(False)
        self.document_tabs.setDocumentMode(True)

        host = QWidget()
        host.setObjectName("SingleWellPlotHost")
        hl = QVBoxLayout(host)
        self.plot_caption = QLabel("单井分析图 · 多图道（选择井并应用图版）")
        self.plot_caption.setObjectName("PlotCaption")
        hl.addWidget(self.plot_caption)

        # Host vs engine primary surface (#227)
        self.single_well_stack = QStackedWidget()
        self.single_well_stack.setObjectName("SingleWellStack")
        self.multi_track_canvas = MultiTrackCanvas()
        self.multi_track_canvas.top_pick_requested.connect(self._on_canvas_top_pick)
        self.single_well_stack.addWidget(self.multi_track_canvas)  # index 0 host

        self._engine_page = QWidget()
        self._engine_page.setObjectName("SingleWellEnginePage")
        ep = QVBoxLayout(self._engine_page)
        ep.setContentsMargins(0, 0, 0, 0)
        self.engine_caption = QLabel(
            "引擎画布 · 需 welllog · 应用图版后自动提交 multi-track"
        )
        self.engine_caption.setObjectName("EngineCaption")
        ep.addWidget(self.engine_caption)
        self._engine_view = None  # WellLogView | None
        self._engine_placeholder = QLabel(
            "引擎未激活。勾选「优先使用引擎画布」并应用图版，"
            "或将 welllog 加入 PYTHONPATH。"
        )
        self._engine_placeholder.setObjectName("EnginePlaceholder")
        self._engine_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ep.addWidget(self._engine_placeholder, 1)
        self.single_well_stack.addWidget(self._engine_page)  # index 1 engine page
        hl.addWidget(self.single_well_stack, 1)

        corr_host = QWidget()
        corr_host.setObjectName("CorrelationPlotHost")
        cl = QVBoxLayout(corr_host)
        self.correlation_caption = QLabel(
            "地层对比图-lite · 多井并列 · 共享深度（需 ≥2 口井）"
        )
        self.correlation_caption.setObjectName("CorrelationCaption")
        cl.addWidget(self.correlation_caption)

        self.correlation_stack = QStackedWidget()
        self.correlation_stack.setObjectName("CorrelationStack")
        self.correlation_canvas = CorrelationCanvas()
        self.correlation_canvas.top_clicked.connect(self._on_correlation_top_clicked)
        self.correlation_stack.addWidget(self.correlation_canvas)  # 0 host

        self._corr_engine_page = QWidget()
        self._corr_engine_page.setObjectName("CorrelationEnginePage")
        cel = QVBoxLayout(self._corr_engine_page)
        cel.setContentsMargins(0, 0, 0, 0)
        self.correlation_engine_caption = QLabel(
            "引擎对比画布 · submit_multi_well_section · 共享深度"
        )
        self.correlation_engine_caption.setObjectName("CorrelationEngineCaption")
        cel.addWidget(self.correlation_engine_caption)
        self._corr_engine_placeholder = QLabel(
            "引擎对比未激活。勾选「优先使用引擎画布」并打开对比图。"
        )
        self._corr_engine_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cel.addWidget(self._corr_engine_placeholder, 1)
        self.correlation_stack.addWidget(self._corr_engine_page)  # 1 engine
        cl.addWidget(self.correlation_stack, 1)

        self.document_tabs.addTab(host, "单井分析图（多图道）")
        self.document_tabs.addTab(corr_host, "地层对比图-lite")

        # Phase-2 PR-C: plane_map + fence_3d host surfaces (section/composite
        # tabs are added in later PR-C batches).
        self._plane_map_host = QWidget()
        self._plane_map_host.setObjectName("PlaneMapHost")
        pml = QVBoxLayout(self._plane_map_host)
        self.plane_map_caption = QLabel(
            "平面图 · 井位（需井含 lng/lat/crs）· 按工区坐标系投影"
        )
        self.plane_map_caption.setObjectName("PlaneMapCaption")
        pml.addWidget(self.plane_map_caption)
        self.plane_map_view = PlaneMapView()
        pml.addWidget(self.plane_map_view, 1)
        self.document_tabs.addTab(self._plane_map_host, "平面图")

        self._fence_3d_host = QWidget()
        self._fence_3d_host.setObjectName("Fence3dHost")
        f3l = QVBoxLayout(self._fence_3d_host)
        self.fence_3d_caption = QLabel(
            "三维栅状图 · pyqtgraph 3D · 拖拽旋转 / 滚轮缩放"
        )
        self.fence_3d_caption.setObjectName("Fence3dCaption")
        f3l.addWidget(self.fence_3d_caption)
        self.fence_3d_view = FenceView()
        f3l.addWidget(self.fence_3d_view, 1)
        self.document_tabs.addTab(self._fence_3d_host, "三维栅状图")

        layout.addWidget(self.document_tabs, 1)
        return pane

    def _build_right(self) -> QWidget:
        pane = QWidget()
        pane.setObjectName("RightPane")
        layout = QVBoxLayout(pane)

        layout.addWidget(QLabel("属性 / 图版 / 层位"))
        layout.addWidget(QLabel("图版模板（库 · 只应用）"))
        self.template_list = QListWidget()
        self.template_list.setObjectName("TemplateList")
        self.template_list.currentItemChanged.connect(
            lambda *_: self._sync_apply_enabled()
        )
        layout.addWidget(self.template_list)

        btn_row = QHBoxLayout()
        self.apply_btn = QPushButton("应用到选中井")
        self.apply_btn.setObjectName("Button_ApplyTemplate")
        self.apply_btn.clicked.connect(self._on_apply_template)
        self.apply_btn.setEnabled(False)
        btn_row.addWidget(self.apply_btn)
        layout.addLayout(btn_row)

        layout.addWidget(QLabel("层位"))
        self.tops_list = QListWidget()
        self.tops_list.setObjectName("TopsList")
        self.tops_list.addItem("（无层位）")
        layout.addWidget(self.tops_list)

        layout.addWidget(QLabel("对比连线"))
        self.links_list = QListWidget()
        self.links_list.setObjectName("LinksList")
        self.links_list.addItem("（无连线）")
        layout.addWidget(self.links_list)
        link_btns = QHBoxLayout()
        self.clear_links_btn = QPushButton("清除连线")
        self.clear_links_btn.setObjectName("Button_ClearLinks")
        self.clear_links_btn.clicked.connect(self._on_clear_horizon_links)
        self.clear_links_btn.setEnabled(False)
        self.remove_link_btn = QPushButton("删除选中")
        self.remove_link_btn.setObjectName("Button_RemoveLink")
        self.remove_link_btn.clicked.connect(self._on_remove_selected_link)
        self.remove_link_btn.setEnabled(False)
        link_btns.addWidget(self.clear_links_btn)
        link_btns.addWidget(self.remove_link_btn)
        layout.addLayout(link_btns)

        layout.addStretch(1)
        return pane

    def _build_status(self) -> None:
        status = QStatusBar(self)
        status.setObjectName("MainStatusBar")
        self.setStatusBar(status)
        self._update_status()

    def _populate_templates(self) -> None:
        self.template_list.clear()
        if not self._templates:
            self.template_list.addItem("（无内置图版）")
            return
        for t in self._templates:
            item = QListWidgetItem(t.name)
            item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.template_list.addItem(item)
        self.template_list.setCurrentRow(0)

    def _sync_apply_enabled(self) -> None:
        has_well = self._workspace is not None and self._selected_well_id is not None
        # Session may reload from disk on open; enable if well is in catalog.
        in_catalog = False
        if self._workspace and self._selected_well_id:
            in_catalog = any(
                w.id == self._selected_well_id for w in self._workspace.wells
            )
        ok = (
            has_well
            and in_catalog
            and self.template_list.currentItem() is not None
            and bool(self._templates)
        )
        self.apply_btn.setEnabled(ok)
        self._act_apply_template.setEnabled(ok)
        self._act_new_single_plot.setEnabled(ok)

        n_wells = len(self._workspace.wells) if self._workspace else 0
        can_corr = (
            self._workspace is not None
            and n_wells >= 2
            and self.template_list.currentItem() is not None
            and bool(self._templates)
        )
        self._act_new_correlation.setEnabled(can_corr)

        can_export = self._presentation is not None and self._presentation.track_count > 0
        self._act_export_svg.setEnabled(can_export)
        self._act_export_pdf.setEnabled(can_export)

        can_tops = (
            self._workspace is not None
            and self._selected_well_id is not None
            and any(w.id == self._selected_well_id for w in self._workspace.wells)
        )
        self._act_import_tops.setEnabled(can_tops)
        self._act_stub_tops.setEnabled(can_tops)
        can_pick = (
            can_tops
            and self._presentation is not None
            and self._presentation.well_document_id == self._selected_well_id
        )
        self._act_pick_tops.setEnabled(can_pick)
        self._act_add_top.setEnabled(can_pick)
        if not can_pick and self._act_pick_tops.isChecked():
            self._act_pick_tops.setChecked(False)
            self.multi_track_canvas.set_pick_mode(False)

        self._act_engine_preview.setEnabled(
            self._presentation is not None and self._presentation.curve_track_count > 0
        )
        self._act_engine_corr.setEnabled(
            len(self._correlation_presentations) >= 2
        )
        has_corr = len(self._correlation_presentations) >= 2
        self._act_auto_links.setEnabled(has_corr)
        self._act_pick_links.setEnabled(has_corr)
        has_links = has_corr and len(self._correlation_links) > 0
        self._act_clear_links.setEnabled(has_links)
        self.clear_links_btn.setEnabled(has_links)
        self.remove_link_btn.setEnabled(has_links)
        if not has_corr and self._act_pick_links.isChecked():
            self._act_pick_links.setChecked(False)
            self.correlation_canvas.set_link_pick_mode(False)
            self._link_pick_first = None

    def _update_status(self) -> None:
        hint = effective_qt_platform_hint()
        if self._workspace is None:
            msg = f"Well Log Workstation · 未打开工区 · Qt: {hint}"
        else:
            well = self._selected_well_id or "—"
            tracks = (
                self._presentation.track_count if self._presentation else 0
            )
            corr_n = self.correlation_canvas.column_count()
            plot_kind = self._active_plot_type or "—"
            tops_n = len(self._active_tops)
            surface = self._primary_surface
            msg = (
                f"工区: {self._workspace.name} · "
                f"井 {len(self._workspace.wells)} · "
                f"选中 {well[:8]}… · "
                f"图道 {tracks} · "
                f"层位 {tops_n} · "
                f"对比列 {corr_n} · "
                f"图件 {plot_kind} · "
                f"画布 {surface} · "
                f"Qt: {hint}"
            )
        self.statusBar().showMessage(msg)

    @staticmethod
    def _default_prefer_engine() -> bool:
        import os

        if os.environ.get("WLWS_DISABLE_ENGINE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return False
        if os.environ.get("WLWS_FORCE_HOST_CANVAS", "").strip().lower() in (
            "1",
            "true",
            "yes",
        ):
            return False
        return True

    @property
    def primary_surface(self) -> str:
        """Active single-well surface: ``host`` or ``engine``."""
        return self._primary_surface

    def set_prefer_engine_canvas(self, prefer: bool) -> None:
        """Prefer WellLogView when available; always falls back to host."""
        self._prefer_engine_canvas = bool(prefer)
        if hasattr(self, "_act_prefer_engine"):
            self._act_prefer_engine.setChecked(self._prefer_engine_canvas)
        if self._active_plot_type == "correlation":
            self._sync_primary_correlation_surface()
        else:
            self._sync_primary_single_well_surface()

    def _ensure_engine_view(self, parent: QWidget | None = None) -> Any:
        """Create WellLogView once; optionally reparent onto ``parent`` page."""
        host = parent or self._engine_page
        if self._engine_view is None:
            view = create_well_log_view(host)
            self._engine_view = view
        else:
            view = self._engine_view
            if view.parent() is not host:
                view.setParent(host)
        # Attach to layout of host page
        layout = host.layout()
        if layout is not None:
            # Avoid double-add: only add if not already in this layout
            found = False
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item is not None and item.widget() is view:
                    found = True
                    break
            if not found:
                layout.addWidget(view, 1)
        if host is self._engine_page:
            self._engine_placeholder.hide()
        if host is getattr(self, "_corr_engine_page", None):
            self._corr_engine_placeholder.hide()
        view.show()
        return view

    def _sync_primary_single_well_surface(self) -> None:
        """Show host or engine as primary based on preference + availability."""
        if self._presentation is None:
            self._primary_surface = "host"
            self.single_well_stack.setCurrentIndex(0)
            return

        want_engine = self._prefer_engine_canvas and engine_available()
        # Tops pick mode requires host canvas hit-testing
        if self.multi_track_canvas.pick_mode():
            want_engine = False

        if not want_engine:
            self._primary_surface = "host"
            self.single_well_stack.setCurrentIndex(0)
            return

        try:
            view = self._ensure_engine_view(self._engine_page)
            report = load_presentation_into_view(
                view, self._presentation, tops=self._active_tops
            )
            self._engine_last_error = None
            self._primary_surface = "engine"
            self.single_well_stack.setCurrentIndex(1)
            tracks = report.get("track_count", "?")
            curves = report.get("curve_count", "?")
            cap = probe_engine()
            self.engine_caption.setText(
                f"引擎画布 · {self._presentation.well_name} · "
                f"{cap.detail} · tracks={tracks} curves={curves}"
            )
            if self._presentation.template_name:
                self.plot_caption.setText(
                    f"单井分析图 · {self._presentation.well_name} · "
                    f"{self._presentation.template_name} · "
                    f"{self._presentation.track_count} 图道 · 引擎"
                )
        except (EngineUnavailable, EngineSubmitError, Exception) as exc:  # noqa: BLE001
            self._engine_last_error = str(exc)
            self._primary_surface = "host"
            self.single_well_stack.setCurrentIndex(0)
            self.engine_caption.setText(f"引擎不可用，已回退主机画布 · {exc}")

    def _sync_primary_correlation_surface(self) -> None:
        """Prefer engine multi-well for correlation; fall back to host canvas (#228)."""
        if not self._correlation_presentations:
            self.correlation_stack.setCurrentIndex(0)
            return

        want_engine = self._prefer_engine_canvas and engine_available()
        if not want_engine:
            self._primary_surface = "host"
            self.correlation_stack.setCurrentIndex(0)
            return

        try:
            view = self._ensure_engine_view(self._corr_engine_page)
            tops_cols = self.correlation_canvas.tops_per_column()
            depth = self.correlation_canvas.depth_range()
            report = submit_multi_well_presentations(
                view,
                self._correlation_presentations,
                tops_per_well=tops_cols,
                shared_depth=depth,
                links=self._correlation_links,
            )
            self._engine_last_error = None
            self._primary_surface = "engine"
            self.correlation_stack.setCurrentIndex(1)
            n = report.get("well_count", len(self._correlation_presentations))
            cap = probe_engine()
            self.correlation_engine_caption.setText(
                f"引擎对比 · {n} 井 · 共享深度 · {cap.detail}"
            )
            # Reflect engine mode in host caption too
            base = self.correlation_caption.text()
            if "· 引擎" not in base:
                self.correlation_caption.setText(f"{base} · 引擎")
        except (EngineUnavailable, EngineSubmitError, Exception) as exc:  # noqa: BLE001
            self._engine_last_error = str(exc)
            self._primary_surface = "host"
            self.correlation_stack.setCurrentIndex(0)
            self.correlation_engine_caption.setText(
                f"引擎对比不可用，已回退主机画布 · {exc}"
            )

    def set_workspace(self, ws: Workspace | None) -> None:
        self._workspace = ws
        if ws is None:
            self.session.clear()
            self._selected_well_id = None
            self._active_plot_id = None
            self._active_plot_type = None
            self._presentation = None
            self._correlation_presentations = []
            self._correlation_links = []
            self._active_tops = []
            self._tops_diagnostics = []
            self.multi_track_canvas.set_presentation(None)
            self.multi_track_canvas.set_tops(None)
            self.correlation_canvas.set_columns([])
            self.correlation_canvas.set_links(None)
            self._refresh_links_list()
            self._primary_surface = "host"
            if hasattr(self, "single_well_stack"):
                self.single_well_stack.setCurrentIndex(0)
            if hasattr(self, "correlation_stack"):
                self.correlation_stack.setCurrentIndex(0)
            self.plot_caption.setText("单井分析图 · 多图道（选择井并应用图版）")
            self.correlation_caption.setText(
                "地层对比图-lite · 多井并列 · 共享深度（需 ≥2 口井）"
            )
            self.document_tabs.setTabText(0, "单井分析图（多图道）")
            self.document_tabs.setTabText(1, "地层对比图-lite")
            self.document_tabs.setCurrentIndex(0)
        self._act_import_las.setEnabled(ws is not None)
        # Phase-2 PR-C: new plot-type menu items (fence_3d needs 3D).
        self._act_new_plane_map.setEnabled(ws is not None)
        self._act_new_fence_3d.setEnabled(
            ws is not None and probe_3d().available
        )
        if ws is not None and not probe_3d().available:
            self._act_new_fence_3d.setToolTip(
                "三维栅状图需要 pyqtgraph + OpenGL"
            )
        self._act_set_crs.setEnabled(ws is not None)
        self._refresh_tree()
        self._refresh_tops_list()
        self._sync_apply_enabled()
        self._update_status()
        if ws is not None:
            self.setWindowTitle(f"{ws.name} — Well Log Workstation")
        else:
            self.setWindowTitle("Well Log Workstation")

    def import_las_path(self, las_path: Path | str) -> str:
        if self._workspace is None:
            raise WorkspaceError("请先打开或新建工区")
        result = import_las_into_workspace(self._workspace, las_path)
        self.session.put(result.document)
        self._selected_well_id = result.catalog_well_id
        self._refresh_tree()
        self._select_well_in_tree(result.catalog_well_id)
        self._refresh_tops_list()
        self._sync_apply_enabled()
        self._update_status()
        return result.catalog_well_id

    def load_tops_for_selected_well(self) -> list[FormationTop]:
        """Load tops for selection; update inspector + single-well canvas."""
        return self._load_and_apply_tops(self._selected_well_id)

    def generate_stub_tops_for_well(self, well_id: str) -> list[FormationTop]:
        """Write demo tops from well depth range; show on canvas/inspector."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        doc = self.session.ensure_well_loaded(self._workspace, well_id)
        depth = doc.depth
        if depth.size:
            d0, d1 = float(np.nanmin(depth)), float(np.nanmax(depth))
        else:
            d0, d1 = 0.0, 100.0
        tops = make_stub_tops(d0, d1, unit=doc.depth_unit or "m")
        save_tops_for_well(self._workspace, well_id, tops)
        self._selected_well_id = well_id
        self._apply_tops_to_ui(well_id, tops, [])
        return tops

    def import_tops_json_for_well(
        self, well_id: str, path: Path | str
    ) -> list[FormationTop]:
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        tops, diags = import_tops_from_json_file(self._workspace, well_id, path)
        self._selected_well_id = well_id
        self._apply_tops_to_ui(well_id, tops, diags)
        return tops

    def add_top_at_depth(
        self,
        well_id: str,
        name: str,
        depth: float,
        *,
        color: str = "#c0392b",
        unit: str | None = None,
    ) -> FormationTop:
        """Add a formation top, persist, and refresh inspector/canvas (#226)."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        label = (name or "").strip()
        if not label:
            raise TopsError("层位名称不能为空")
        if not math.isfinite(depth):
            raise TopsError("深度无效")
        tops, diags = load_tops_for_well(self._workspace, well_id)
        depth_unit = unit or "m"
        if self._presentation is not None:
            depth_unit = self._presentation.depth_unit or depth_unit
        top = FormationTop(
            id=str(uuid.uuid4()),
            name=label,
            depth=float(depth),
            unit=depth_unit,
            color=color,
        )
        tops.append(top)
        tops.sort(key=lambda t: t.depth)
        save_tops_for_well(self._workspace, well_id, tops)
        self._selected_well_id = well_id
        self._apply_tops_to_ui(well_id, tops, diags)
        return top

    def _load_and_apply_tops(self, well_id: str | None) -> list[FormationTop]:
        if self._workspace is None or not well_id:
            self._apply_tops_to_ui(None, [], [])
            return []
        try:
            tops, diags = load_tops_for_well(self._workspace, well_id)
        except Exception as exc:  # noqa: BLE001 — degrade, never crash shell
            tops, diags = [], [f"层位加载异常: {exc}"]
        self._apply_tops_to_ui(well_id, tops, diags)
        return tops

    def _apply_tops_to_ui(
        self,
        well_id: str | None,
        tops: list[FormationTop],
        diagnostics: list[str],
    ) -> None:
        self._active_tops = list(tops)
        self._tops_diagnostics = list(diagnostics)
        self._refresh_tops_list_items(tops, diagnostics)
        # Single-well canvas: only if presentation matches this well
        if (
            self._presentation is not None
            and well_id is not None
            and self._presentation.well_document_id == well_id
        ):
            self.multi_track_canvas.set_tops(tops)
            # Refresh engine markers when primary surface is engine
            if self._prefer_engine_canvas and not self.multi_track_canvas.pick_mode():
                self._sync_primary_single_well_surface()
        elif well_id is None:
            self.multi_track_canvas.set_tops(None)
        # Correlation: refresh tops for all columns if open
        if self._correlation_presentations and self._workspace is not None:
            tops_cols: list[list[FormationTop]] = []
            for pres in self._correlation_presentations:
                t, _ = load_tops_for_well(
                    self._workspace, pres.well_document_id
                )
                tops_cols.append(t)
            self.correlation_canvas.set_tops_per_column(tops_cols)
        self._sync_apply_enabled()
        self._update_status()

    def _refresh_tops_list(self) -> None:
        self._load_and_apply_tops(self._selected_well_id)

    def _refresh_tops_list_items(
        self, tops: list[FormationTop], diagnostics: list[str]
    ) -> None:
        self.tops_list.clear()
        if not tops:
            label = "（无层位）"
            if diagnostics:
                label = f"（无层位 · {diagnostics[0][:40]}）"
            self.tops_list.addItem(label)
            return
        for t in tops:
            item = QListWidgetItem(t.display_label())
            item.setData(Qt.ItemDataRole.UserRole, t.id or t.name)
            item.setForeground(Qt.GlobalColor.darkRed)
            self.tops_list.addItem(item)
        if diagnostics:
            for d in diagnostics[:3]:
                hint = QListWidgetItem(f"⚠ {d}")
                hint.setDisabled(True)
                self.tops_list.addItem(hint)

    def _current_template_id(self) -> str | None:
        item = self.template_list.currentItem()
        if item is None:
            return None
        tid = item.data(Qt.ItemDataRole.UserRole)
        return str(tid) if tid else None

    def apply_template_to_well(
        self, well_id: str, template_id: str, *, plot_id: str | None = None
    ) -> HostPresentation:
        """Apply builtin template to a session well; show multi-track plot."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        doc = self.session.ensure_well_loaded(self._workspace, well_id)
        template = get_builtin_template(template_id)
        if template is None:
            raise WorkspaceError(f"未知图版: {template_id}")
        presentation = apply_template(template, doc)
        if presentation.curve_track_count < 1:
            raise WorkspaceError(
                "图版未能绑定任何曲线（检查 LAS 助记符与图版 mnemonics）"
            )
        self._selected_well_id = well_id
        self._presentation = presentation
        self._active_plot_type = "single_well"
        if plot_id is not None:
            self._active_plot_id = plot_id
        self.multi_track_canvas.set_presentation(presentation)
        tops, diags = load_tops_for_well(self._workspace, well_id)
        self._active_tops = tops
        self._tops_diagnostics = diags
        self.multi_track_canvas.set_tops(tops)
        self._refresh_tops_list_items(tops, diags)
        self.plot_caption.setText(
            f"单井分析图 · {presentation.well_name} · "
            f"{presentation.template_name} · "
            f"{presentation.track_count} 图道"
        )
        tab = f"单井·多图道 · {presentation.well_name}"
        if self._active_plot_id:
            tab = f"{tab} · {self._active_plot_id[:8]}"
        self.document_tabs.setTabText(0, tab)
        self.document_tabs.setCurrentIndex(0)
        self._sync_primary_single_well_surface()
        self._sync_apply_enabled()
        self._update_status()
        return presentation

    def create_single_well_plot_document(
        self, well_id: str, template_id: str
    ) -> PlotDocument:
        """Create plots/<id>.json, catalog entry, open multi-track view."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        doc = self.session.ensure_well_loaded(self._workspace, well_id)
        plot = create_single_well_plot(
            self._workspace,
            well_id=well_id,
            well_name=doc.well_name,
            template_id=template_id,
        )
        self._active_plot_id = plot.id
        self._active_plot_type = "single_well"
        self.apply_template_to_well(well_id, template_id, plot_id=plot.id)
        self._refresh_tree()
        return plot

    def create_correlation_plot_document(
        self,
        well_ids: list[str],
        template_id: str,
        *,
        name: str | None = None,
    ) -> PlotDocument:
        """Create plots/<id>.json correlation doc and show shared-depth canvas."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        plot = create_correlation_plot(
            self._workspace,
            well_ids=well_ids,
            template_id=template_id,
            name=name,
        )
        self._active_plot_id = plot.id
        self._active_plot_type = "correlation"
        self._show_correlation(plot)
        self._refresh_tree()
        return plot

    def _show_correlation(self, plot: PlotDocument) -> None:
        """Load wells, apply template per column, shared depth on canvas."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        if not plot.template_id:
            raise WorkspaceError("图件未绑定图版")
        template = get_builtin_template(plot.template_id)
        if template is None:
            raise WorkspaceError(f"未知图版: {plot.template_id}")

        presentations: list[HostPresentation] = []
        tops_cols: list[list[FormationTop]] = []
        all_diags: list[str] = []
        for well_id in plot.well_ids:
            doc = self.session.ensure_well_loaded(self._workspace, well_id)
            pres = apply_template(template, doc)
            if pres.curve_track_count < 1:
                raise WorkspaceError(
                    f"井 {doc.well_name} 图版未能绑定任何曲线"
                )
            presentations.append(pres)
            t, diags = load_tops_for_well(self._workspace, well_id)
            tops_cols.append(t)
            all_diags.extend(diags)

        self._correlation_presentations = presentations
        self._active_plot_id = plot.id
        self._active_plot_type = "correlation"
        if plot.well_ids:
            self._selected_well_id = plot.well_ids[0]
            self._active_tops = tops_cols[0] if tops_cols else []
            self._tops_diagnostics = all_diags
            self._refresh_tops_list_items(self._active_tops, all_diags)
        # Links from document, or auto-match by top name when empty (#229)
        links = list(plot.links)
        if not links:
            tops_by_well = {
                wid: tops_cols[i] for i, wid in enumerate(plot.well_ids)
            }
            links = match_tops_by_name(plot.well_ids, tops_by_well)
            if links:
                plot.links = list(links)
                try:
                    save_plot_document(self._workspace, plot)
                except WorkspaceError:
                    pass
        self._correlation_links = links
        self.correlation_canvas.set_columns(presentations, tops_cols, links)
        self._refresh_links_list()
        names = " · ".join(p.well_name for p in presentations[:4])
        tops_n = sum(len(t) for t in tops_cols)
        self.correlation_caption.setText(
            f"地层对比图-lite · {names} · "
            f"共享深度 · 图版 {template.name} · 层位 {tops_n} · "
            f"连线 {len(links)}"
        )
        tab = f"对比 · {len(presentations)}井"
        if self._active_plot_id:
            tab = f"{tab} · {self._active_plot_id[:8]}"
        self.document_tabs.setTabText(1, tab)
        self.document_tabs.setCurrentIndex(1)
        # Keep template selection in sync
        for i in range(self.template_list.count()):
            item = self.template_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == plot.template_id:
                self.template_list.setCurrentRow(i)
                break
        self._sync_primary_correlation_surface()
        self._sync_apply_enabled()
        self._update_status()

    def _show_plane_map(self, plot: PlotDocument) -> None:
        """Render well positions on the paleo_map canvas (Phase-2 T2)."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        self._active_plot_id = plot.id
        self._active_plot_type = "plane_map"
        self.plane_map_view.set_coordinate(self._workspace.coordinate)
        self.plane_map_view.set_plot_data(self._workspace.wells)
        drawn = len(PlaneMapView.filter_wells_with_coords(self._workspace.wells))
        total = len(self._workspace.wells)
        self.plane_map_caption.setText(
            f"平面图 · 绘制 {drawn}/{total} 口井（含坐标）· "
            f"项目坐标系 {self._workspace.coordinate.project_crs}"
        )
        self.document_tabs.setCurrentWidget(self._plane_map_host)
        self._update_status()

    def _show_fence_3d(self, plot: PlotDocument) -> None:
        """Render the 3D fence surface from well x/y/depth (Phase-2 T6)."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        if not probe_3d().available:
            raise WorkspaceError(
                "三维栅状图需要 pyqtgraph + OpenGL（3D 能力探测失败）"
            )
        self._active_plot_id = plot.id
        self._active_plot_type = "fence_3d"
        wells = []
        for wid in plot.well_ids:
            entry = next(
                (w for w in self._workspace.wells if w.id == wid), None
            )
            if entry is None:
                continue
            doc = self.session.ensure_well_loaded(self._workspace, wid)
            depth = float(np.nanmax(doc.depth)) if doc.depth.size else 1000.0
            # x/y from catalog coords (project CRS), depth from LAS.
            lng = float(entry.lng) if entry.lng is not None else 0.0
            lat = float(entry.lat) if entry.lat is not None else 0.0
            wells.append(
                {"name": entry.name, "x": lng, "y": lat, "depth": depth}
            )
        self.fence_3d_view.set_wells(wells)
        self.fence_3d_caption.setText(
            f"三维栅状图 · {len(wells)} 井 · 拖拽旋转 / 滚轮缩放"
        )
        self.document_tabs.setCurrentWidget(self._fence_3d_host)
        self._update_status()

    def auto_link_correlation_tops(self) -> list[HorizonLink]:
        """Match tops by name across adjacent wells; persist on active plot."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        if len(self._correlation_presentations) < 2:
            raise WorkspaceError("请先打开地层对比图（≥2 井）")
        well_ids = [p.well_document_id for p in self._correlation_presentations]
        tops_by_well: dict[str, list[FormationTop]] = {}
        for i, wid in enumerate(well_ids):
            tops_by_well[wid] = (
                self.correlation_canvas.tops_per_column()[i]
                if i < len(self.correlation_canvas.tops_per_column())
                else []
            )
        links = match_tops_by_name(well_ids, tops_by_well)
        self._set_correlation_links(links, persist=True)
        return links

    def clear_correlation_links(self) -> None:
        """Remove all horizon links from the active correlation plot."""
        self._set_correlation_links([], persist=True)

    def remove_correlation_link(self, link_id: str) -> bool:
        """Remove one link by id; return True if removed."""
        before = len(self._correlation_links)
        kept = [lk for lk in self._correlation_links if lk.id != link_id]
        if len(kept) == before:
            return False
        self._set_correlation_links(kept, persist=True)
        return True

    def create_horizon_link(
        self,
        left_well_id: str,
        left_top: FormationTop,
        right_well_id: str,
        right_top: FormationTop,
        *,
        name: str | None = None,
    ) -> HorizonLink:
        """Manually link two tops on different wells (#231)."""
        if left_well_id == right_well_id:
            raise WorkspaceError("连线两端必须是不同井")
        # Order by column index so left is leftward on canvas
        order = {
            p.well_document_id: i for i, p in enumerate(self._correlation_presentations)
        }
        li = order.get(left_well_id, 0)
        ri = order.get(right_well_id, 1)
        if li > ri:
            left_well_id, right_well_id = right_well_id, left_well_id
            left_top, right_top = right_top, left_top
        try:
            link = make_horizon_link(
                left_well_id, left_top, right_well_id, right_top, name=name
            )
        except ValueError as exc:
            raise WorkspaceError(str(exc)) from exc
        # Avoid exact duplicate ends
        for existing in self._correlation_links:
            if (
                existing.left_well_id == link.left_well_id
                and existing.right_well_id == link.right_well_id
                and abs(existing.left_depth - link.left_depth) < 1e-6
                and abs(existing.right_depth - link.right_depth) < 1e-6
            ):
                return existing
        links = list(self._correlation_links) + [link]
        self._set_correlation_links(links, persist=True)
        return link

    def _set_correlation_links(
        self, links: list[HorizonLink], *, persist: bool
    ) -> None:
        self._correlation_links = list(links)
        self.correlation_canvas.set_links(self._correlation_links)
        self._refresh_links_list()
        if persist and self._workspace is not None and self._active_plot_id:
            try:
                plot = load_plot_document(self._workspace, self._active_plot_id)
                if plot.type == "correlation":
                    plot.links = list(self._correlation_links)
                    save_plot_document(self._workspace, plot)
            except WorkspaceError:
                pass
        cap = self.correlation_caption.text().split(" · 连线")[0]
        self.correlation_caption.setText(
            f"{cap} · 连线 {len(self._correlation_links)}"
        )
        if (
            self._prefer_engine_canvas
            and self._active_plot_type == "correlation"
            and self._correlation_presentations
        ):
            self._sync_primary_correlation_surface()
        self._sync_apply_enabled()
        self._update_status()

    def _refresh_links_list(self) -> None:
        self.links_list.clear()
        if not self._correlation_links:
            self.links_list.addItem("（无连线）")
            return
        # Map well ids to short names when presentations available
        name_by_id = {
            p.well_document_id: p.well_name for p in self._correlation_presentations
        }
        for lk in self._correlation_links:
            left = name_by_id.get(lk.left_well_id, lk.left_well_id[:8])
            right = name_by_id.get(lk.right_well_id, lk.right_well_id[:8])
            label = (
                f"{lk.name}  {left}@{lk.left_depth:g} → "
                f"{right}@{lk.right_depth:g}"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, lk.id)
            self.links_list.addItem(item)

    def open_plot_document(self, plot_id: str) -> PlotDocument:
        """Load plot metadata and open the matching plot-type view."""
        if self._workspace is None:
            raise WorkspaceError("请先打开工区")
        plot = load_plot_document(self._workspace, plot_id)
        # plane_map / composite may legitimately have no wells bound.
        if not plot.well_ids and plot.type not in ("plane_map", "composite"):
            raise WorkspaceError("图件未绑定井")
        if not plot.template_id:
            raise WorkspaceError("图件未绑定图版")

        if plot.type == "correlation":
            self._show_correlation(plot)
            if plot.well_ids:
                self._select_well_in_tree(plot.well_ids[0])
            self._refresh_tree()
            return plot

        if plot.type == "plane_map":
            self._show_plane_map(plot)
            self._refresh_tree()
            return plot

        if plot.type == "fence_3d":
            self._show_fence_3d(plot)
            self._refresh_tree()
            return plot

        if plot.type in ("section", "composite"):
            # Landed in later PR-C batches (PR-C3 / PR-C4).
            raise WorkspaceError(f"图件类型尚未接入: {plot.type}")

        if plot.type != "single_well":
            raise WorkspaceError(f"未知图件类型: {plot.type}")
        well_id = plot.well_ids[0]
        self._active_plot_id = plot.id
        self._active_plot_type = "single_well"
        self._selected_well_id = well_id
        self.apply_template_to_well(well_id, plot.template_id, plot_id=plot.id)
        # Keep template selection in sync
        for i in range(self.template_list.count()):
            item = self.template_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == plot.template_id:
                self.template_list.setCurrentRow(i)
                break
        self._select_well_in_tree(well_id)
        self._refresh_tree()
        return plot

    def export_active_plot_svg(self, path: Path | str) -> Path:
        """Export active single-well multi-track presentation to SVG."""
        if self._presentation is None or self._presentation.track_count < 1:
            raise ExportError("无活动单井分析图可导出（请先应用图版）")
        return export_presentation_svg(self._presentation, path)

    def export_active_plot_pdf(self, path: Path | str) -> Path:
        """Export active single-well multi-track presentation to PDF."""
        if self._presentation is None or self._presentation.track_count < 1:
            raise ExportError("无活动单井分析图可导出（请先应用图版）")
        return export_presentation_pdf(self._presentation, path)

    def open_engine_preview(self) -> dict[str, object]:
        """Force engine primary surface and submit multi-track presentation."""
        if self._presentation is None:
            raise EngineUnavailable("无活动单井图版展示")
        if not engine_available():
            cap = probe_engine()
            raise EngineUnavailable(
                f"WellLogEngine 不可用: {cap.detail}\n"
                "请安装 welllog-engine wheel 或将 build 产物加入 PYTHONPATH。"
            )
        # Temporarily prefer engine even if user had host forced via menu
        prev = self._prefer_engine_canvas
        self._prefer_engine_canvas = True
        self._act_prefer_engine.setChecked(True)
        # Exit pick mode so engine can show
        if self.multi_track_canvas.pick_mode():
            self._act_pick_tops.setChecked(False)
            self.multi_track_canvas.set_pick_mode(False)
        self._sync_primary_single_well_surface()
        self.document_tabs.setCurrentIndex(0)
        self._update_status()
        if self._primary_surface != "engine" or self._engine_view is None:
            self._prefer_engine_canvas = prev
            self._act_prefer_engine.setChecked(prev)
            raise EngineSubmitError(
                self._engine_last_error or "引擎提交失败，已保持主机画布"
            )
        # Re-submit to return report to caller
        return load_presentation_into_view(
            self._engine_view,
            self._presentation,
            tops=self._active_tops,
        )

    def open_engine_correlation_preview(self) -> dict[str, object]:
        """Force engine multi-well surface for the active correlation plot."""
        if len(self._correlation_presentations) < 2:
            raise EngineUnavailable("请先创建/打开 ≥2 井的地层对比图")
        if not engine_available():
            cap = probe_engine()
            raise EngineUnavailable(
                f"WellLogEngine 不可用: {cap.detail}\n"
                "请安装 welllog-engine wheel 或将 build 产物加入 PYTHONPATH。"
            )
        prev = self._prefer_engine_canvas
        self._prefer_engine_canvas = True
        self._act_prefer_engine.setChecked(True)
        self.document_tabs.setCurrentIndex(1)
        self._sync_primary_correlation_surface()
        self._update_status()
        if self._primary_surface != "engine" or self._engine_view is None:
            self._prefer_engine_canvas = prev
            self._act_prefer_engine.setChecked(prev)
            raise EngineSubmitError(
                self._engine_last_error or "引擎对比提交失败，已保持主机画布"
            )
        tops_cols = self.correlation_canvas.tops_per_column()
        depth = self.correlation_canvas.depth_range()
        return submit_multi_well_presentations(
            self._engine_view,
            self._correlation_presentations,
            tops_per_well=tops_cols,
            shared_depth=depth,
            links=self._correlation_links,
        )

    def _select_well_in_tree(self, well_id: str) -> None:
        def walk(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            data = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if data.get("kind") == "well" and data.get("id") == well_id:
                return item
            for i in range(item.childCount()):
                hit = walk(item.child(i))
                if hit is not None:
                    return hit
            return None

        for i in range(self.workspace_tree.topLevelItemCount()):
            hit = walk(self.workspace_tree.topLevelItem(i))
            if hit is not None:
                self.workspace_tree.setCurrentItem(hit)
                return

    def _on_tree_selection(
        self, cur: QTreeWidgetItem | None, _prev: QTreeWidgetItem | None
    ) -> None:
        if cur is None:
            return
        data = cur.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") == "well":
            self._selected_well_id = str(data.get("id"))
            self._refresh_tops_list()
            self._sync_apply_enabled()
            self._update_status()

    def _on_tree_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if data.get("kind") != "plot":
            return
        plot_id = str(data.get("id") or "")
        if not plot_id:
            return
        try:
            self.open_plot_document(plot_id)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "打开图件失败", str(exc))

    def _refresh_tree(self) -> None:
        tree = self.workspace_tree
        tree.clear()
        if self._workspace is None:
            self.left_title.setText("工区")
            root = QTreeWidgetItem(["（未打开工区）"])
            root.addChild(QTreeWidgetItem(["井"]))
            root.addChild(QTreeWidgetItem(["图件"]))
            tree.addTopLevelItem(root)
            tree.expandAll()
            return

        ws = self._workspace
        self.left_title.setText(f"工区 · {ws.name}")
        root = QTreeWidgetItem([ws.name])
        root.setData(0, Qt.ItemDataRole.UserRole, {"kind": "workspace"})

        wells_node = QTreeWidgetItem(["井"])
        wells_node.setData(0, Qt.ItemDataRole.UserRole, {"kind": "wells_folder"})
        for well in ws.wells:
            item = QTreeWidgetItem([well.name])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"kind": "well", "id": well.id, "path": well.path},
            )
            item.setToolTip(0, well.path or well.id)
            wells_node.addChild(item)
        if not ws.wells:
            empty = QTreeWidgetItem(["（无井）"])
            empty.setDisabled(True)
            wells_node.addChild(empty)

        plots_node = QTreeWidgetItem(["图件"])
        plots_node.setData(0, Qt.ItemDataRole.UserRole, {"kind": "plots_folder"})
        for plot in ws.plots:
            label = plot.name
            # Phase-2 PR-C: 6 plot types with Chinese labels (T9).
            type_labels = {
                "single_well": "[单井·多图道]",
                "correlation": "[对比]",
                "section": "[剖面]",
                "plane_map": "[平面图]",
                "fence_3d": "[栅状图]",
                "composite": "[综合图]",
            }
            suffix = type_labels.get(plot.type, "")
            if suffix:
                label = f"{plot.name} {suffix}"
            item = QTreeWidgetItem([label])
            item.setData(
                0,
                Qt.ItemDataRole.UserRole,
                {"kind": "plot", "id": plot.id, "type": plot.type},
            )
            plots_node.addChild(item)
        if not ws.plots:
            empty = QTreeWidgetItem(["（无图件）"])
            empty.setDisabled(True)
            plots_node.addChild(empty)

        root.addChild(wells_node)
        root.addChild(plots_node)
        tree.addTopLevelItem(root)
        tree.expandAll()
        if self._selected_well_id:
            self._select_well_in_tree(self._selected_well_id)

    def _on_new_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择空目录作为新工区")
        if not path:
            return
        try:
            ws = create_workspace(Path(path))
            self.set_workspace(ws)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "新建工区失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "新建工区失败", str(exc))

    def _on_open_workspace(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "打开工区目录")
        if not path:
            return
        try:
            ws = open_workspace(path)
            self.set_workspace(ws)
        except WorkspaceError as exc:
            QMessageBox.warning(self, "打开工区失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "打开工区失败", str(exc))

    def _on_import_las(self) -> None:
        if self._workspace is None:
            QMessageBox.information(self, "导入 LAS", "请先打开或新建工区。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 LAS 文件",
            "",
            "LAS (*.las *.LAS);;All (*.*)",
        )
        if not path:
            return
        try:
            well_id = self.import_las_path(path)
            doc = self.session.get(well_id)
            n_curves = len(doc.curves) if doc else 0
            extra = ""
            if doc and doc.diagnostics:
                extra = "\n\n提示:\n- " + "\n- ".join(doc.diagnostics[:8])
            QMessageBox.information(
                self,
                "导入成功",
                f"已导入井「{doc.well_name if doc else well_id}」\n"
                f"曲线数: {n_curves}\n"
                f"路径: {doc.source_path if doc else ''}"
                f"{extra}\n\n"
                f"请在右栏选择图版并「应用到选中井」以显示多图道。",
            )
        except (LasImportError, WorkspaceError) as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导入 LAS 失败", str(exc))

    def _on_apply_template(self) -> None:
        if self._selected_well_id is None:
            QMessageBox.information(self, "应用图版", "请先在左树选择一口井。")
            return
        template_id = self._current_template_id()
        if not template_id:
            QMessageBox.information(self, "应用图版", "请选择图版模板。")
            return
        try:
            # Update open plot document template if one is active for this well
            if (
                self._active_plot_id
                and self._workspace is not None
            ):
                try:
                    plot = load_plot_document(self._workspace, self._active_plot_id)
                    if plot.well_ids == [self._selected_well_id]:
                        plot.template_id = template_id
                        save_plot_document(self._workspace, plot)
                except WorkspaceError:
                    pass
            pres = self.apply_template_to_well(
                self._selected_well_id,
                template_id,
                plot_id=self._active_plot_id,
            )
            QMessageBox.information(
                self,
                "图版已应用",
                f"井 {pres.well_name}\n"
                f"图版 {pres.template_name}\n"
                f"图道数 {pres.track_count}（曲线道 {pres.curve_track_count}）",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "应用图版失败", str(exc))

    def _on_new_single_well_plot(self) -> None:
        if self._selected_well_id is None:
            QMessageBox.information(self, "新建单井分析图", "请先选择一口井。")
            return
        template_id = self._current_template_id()
        if not template_id:
            QMessageBox.information(self, "新建单井分析图", "请选择图版模板。")
            return
        try:
            plot = self.create_single_well_plot_document(
                self._selected_well_id, template_id
            )
            QMessageBox.information(
                self,
                "图件已创建",
                f"已保存 {plot.path}\n"
                f"井绑定 {', '.join(plot.well_ids)}\n"
                f"图版 {plot.template_id}\n"
                f"双击左树图件可重新打开。",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "新建图件失败", str(exc))

    def _pick_wells_for_correlation(self) -> list[str] | None:
        """Multi-select dialog; returns well ids or None if cancelled."""
        if self._workspace is None or len(self._workspace.wells) < 2:
            return None
        dlg = QDialog(self)
        dlg.setWindowTitle("选择对比井（≥2）")
        dlg.setObjectName("Dialog_PickCorrelationWells")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("按住 Ctrl 多选井；至少 2 口："))
        lst = QListWidget()
        lst.setObjectName("List_CorrelationWells")
        lst.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for well in self._workspace.wells:
            item = QListWidgetItem(well.name)
            item.setData(Qt.ItemDataRole.UserRole, well.id)
            lst.addItem(item)
            item.setSelected(True)
        layout.addWidget(lst)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        ids = [
            str(it.data(Qt.ItemDataRole.UserRole))
            for it in lst.selectedItems()
            if it.data(Qt.ItemDataRole.UserRole)
        ]
        if len(ids) < 2:
            QMessageBox.information(
                self, "新建地层对比图", "请至少选择 2 口井。"
            )
            return None
        return ids

    def _on_new_correlation_plot(self) -> None:
        if self._workspace is None:
            QMessageBox.information(self, "新建地层对比图", "请先打开工区。")
            return
        if len(self._workspace.wells) < 2:
            QMessageBox.information(
                self, "新建地层对比图", "工区至少需要 2 口井。"
            )
            return
        template_id = self._current_template_id()
        if not template_id:
            QMessageBox.information(self, "新建地层对比图", "请选择图版模板。")
            return
        well_ids = self._pick_wells_for_correlation()
        if not well_ids:
            return
        try:
            plot = self.create_correlation_plot_document(well_ids, template_id)
            QMessageBox.information(
                self,
                "对比图已创建",
                f"已保存 {plot.path}\n"
                f"井 {len(plot.well_ids)} 口 · 图版 {plot.template_id}\n"
                f"滚轮缩放 / 拖动平移共享深度。\n"
                f"双击左树图件可重新打开。",
            )
        except (WorkspaceError, ExportError) as exc:
            QMessageBox.warning(self, "新建对比图失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "新建对比图失败", str(exc))

    def _on_new_plane_map_plot(self) -> None:
        """Create + open a plane_map plot (Phase-2 T2 / #246)."""
        if self._workspace is None:
            QMessageBox.information(self, "新建平面图", "请先打开工区。")
            return
        if not self.plane_map_view.mapping_available():
            QMessageBox.warning(
                self, "新建平面图",
                "平面图需要 geoviz mapping 表面（geoviz_paleo_map + CRS helpers）。"
                "请确认 geo-viz-engine 已安装。",
            )
            return
        template_id = self._current_template_id() or "std-gr-rt-den"
        try:
            plot = create_plane_map_plot(
                self._workspace,
                wells=[w.id for w in self._workspace.wells],
                template_id=template_id,
            )
            self._active_plot_id = plot.id
            self._active_plot_type = "plane_map"
            self._show_plane_map(plot)
            self._refresh_tree()
            QMessageBox.information(
                self, "平面图已创建",
                f"已保存 {plot.path}\n"
                f"绘制 {len(PlaneMapView.filter_wells_with_coords(self._workspace.wells))}"
                f"/{len(self._workspace.wells)} 口含坐标井。",
            )
        except (WorkspaceError, ExportError) as exc:
            QMessageBox.warning(self, "新建平面图失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "新建平面图失败", str(exc))

    def _on_new_fence_3d_plot(self) -> None:
        """Create + open a fence_3d plot (Phase-2 T6 / #250)."""
        if self._workspace is None:
            QMessageBox.information(self, "新建三维栅状图", "请先打开工区。")
            return
        if not probe_3d().available:
            cap = probe_3d()
            QMessageBox.warning(
                self, "新建三维栅状图",
                f"三维栅状图需要 pyqtgraph + OpenGL。\n{cap.detail}",
            )
            return
        wells_with_coords = [
            w for w in self._workspace.wells
            if w.lng is not None and w.lat is not None
        ]
        if len(wells_with_coords) < 2:
            QMessageBox.information(
                self, "新建三维栅状图",
                "三维栅状图至少需要 2 口含坐标（lng/lat）的井。",
            )
            return
        template_id = self._current_template_id() or "std-gr-rt-den"
        try:
            plot = create_fence_3d_plot(
                self._workspace,
                well_ids=[w.id for w in wells_with_coords],
                template_id=template_id,
            )
            self._active_plot_id = plot.id
            self._active_plot_type = "fence_3d"
            self._show_fence_3d(plot)
            self._refresh_tree()
            QMessageBox.information(
                self, "三维栅状图已创建",
                f"已保存 {plot.path}\n"
                f"{len(plot.well_ids)} 口井 · 拖拽旋转 / 滚轮缩放。",
            )
        except (WorkspaceError, ExportError) as exc:
            QMessageBox.warning(self, "新建三维栅状图失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "新建三维栅状图失败", str(exc))

    def _on_set_coordinate_reference(self) -> None:
        """Open the CRS trio editor (Phase-2 T2 / #246)."""
        if self._workspace is None:
            QMessageBox.information(self, "坐标系设置", "请先打开工区。")
            return
        dlg = CoordinateReferenceDialog(self._workspace.coordinate, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._workspace.coordinate = dlg.result_coordinate()
        save_workspace(self._workspace)
        # Re-project the active plane map if open.
        if self._active_plot_type == "plane_map":
            self.plane_map_view.set_coordinate(self._workspace.coordinate)
            self.plane_map_view.set_plot_data(self._workspace.wells)
        QMessageBox.information(
            self, "坐标系已更新",
            f"项目坐标系: {self._workspace.coordinate.project_crs}\n"
            f"目标坐标系: {self._workspace.coordinate.target_crs or '—'}\n"
            f"显示坐标系: {self._workspace.coordinate.display_crs}",
        )

    def _on_export_svg(self) -> None:
        if self._presentation is None:
            QMessageBox.information(
                self, "导出 SVG", "请先打开/创建单井分析图并应用图版。"
            )
            return
        default = f"{self._presentation.well_name or 'plot'}.svg"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 SVG",
            default,
            "SVG (*.svg);;All (*.*)",
        )
        if not path:
            return
        try:
            out = self.export_active_plot_svg(path)
            QMessageBox.information(
                self,
                "导出成功",
                f"SVG 已写入:\n{out}\n大小 {out.stat().st_size} 字节",
            )
        except ExportError as exc:
            QMessageBox.warning(self, "导出 SVG 失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导出 SVG 失败", str(exc))

    def _on_export_pdf(self) -> None:
        if self._presentation is None:
            QMessageBox.information(
                self, "导出 PDF", "请先打开/创建单井分析图并应用图版。"
            )
            return
        default = f"{self._presentation.well_name or 'plot'}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 PDF",
            default,
            "PDF (*.pdf);;All (*.*)",
        )
        if not path:
            return
        try:
            out = self.export_active_plot_pdf(path)
            QMessageBox.information(
                self,
                "导出成功",
                f"PDF 已写入:\n{out}\n大小 {out.stat().st_size} 字节",
            )
        except ExportError as exc:
            QMessageBox.warning(self, "导出 PDF 失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导出 PDF 失败", str(exc))

    def _on_import_tops(self) -> None:
        if self._selected_well_id is None or self._workspace is None:
            QMessageBox.information(self, "导入层位", "请先选择一口井。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择层位 JSON",
            "",
            "JSON (*.json);;All (*.*)",
        )
        if not path:
            return
        try:
            tops = self.import_tops_json_for_well(self._selected_well_id, path)
            QMessageBox.information(
                self,
                "层位已导入",
                f"已关联 {len(tops)} 个层位到选中井。\n"
                f"单井/对比图会以虚线标记深度。",
            )
        except (TopsError, WorkspaceError) as exc:
            QMessageBox.warning(self, "导入层位失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "导入层位失败", str(exc))

    def _on_stub_tops(self) -> None:
        if self._selected_well_id is None or self._workspace is None:
            QMessageBox.information(self, "示例层位", "请先选择一口井。")
            return
        try:
            tops = self.generate_stub_tops_for_well(self._selected_well_id)
            QMessageBox.information(
                self,
                "示例层位",
                f"已生成 {len(tops)} 个示例层位（深度均分）。\n"
                f"正式数据请用「导入层位 JSON…」。",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "生成层位失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "生成层位失败", str(exc))

    def _on_auto_horizon_links(self) -> None:
        try:
            links = self.auto_link_correlation_tops()
            QMessageBox.information(
                self,
                "自动连线",
                f"已按层位名生成 {len(links)} 条相邻井连线。\n"
                f"主机画布已绘制；引擎路径将作为 horizon_line 提交。",
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "自动连线失败", str(exc))

    def _on_clear_horizon_links(self) -> None:
        if not self._correlation_links:
            return
        self.clear_correlation_links()
        self.statusBar().showMessage("已清除全部对比连线", 4000)

    def _on_remove_selected_link(self) -> None:
        item = self.links_list.currentItem()
        if item is None:
            QMessageBox.information(self, "删除连线", "请先在右栏选中一条连线。")
            return
        link_id = item.data(Qt.ItemDataRole.UserRole)
        if not link_id:
            return
        if self.remove_correlation_link(str(link_id)):
            self.statusBar().showMessage("已删除选中连线", 4000)

    def _on_toggle_pick_links(self) -> None:
        enabled = self._act_pick_links.isChecked()
        if enabled and len(self._correlation_presentations) < 2:
            self._act_pick_links.setChecked(False)
            QMessageBox.information(self, "点选连线", "请先打开 ≥2 井对比图。")
            return
        self._link_pick_first = None
        self.correlation_canvas.set_pick_highlight(None, None)
        self.correlation_canvas.set_link_pick_mode(enabled)
        # Prefer host stack for hit testing
        if enabled:
            self.correlation_stack.setCurrentIndex(0)
            self.document_tabs.setCurrentIndex(1)
            self.statusBar().showMessage(
                "点选连线：依次点击两口井的层位虚线 · 再次点菜单退出",
                8000,
            )

    def _on_correlation_top_clicked(
        self, well_id: str, top_name: str, depth: float, top_id: str
    ) -> None:
        top = FormationTop(
            name=top_name,
            depth=depth,
            id=top_id or str(uuid.uuid4()),
        )
        if self._link_pick_first is None:
            self._link_pick_first = (well_id, top)
            self.correlation_canvas.set_pick_highlight(well_id, top_name)
            self.statusBar().showMessage(
                f"已选 {top_name}@{depth:g} · 请点击另一口井的层位", 6000
            )
            return
        first_well, first_top = self._link_pick_first
        self._link_pick_first = None
        self.correlation_canvas.set_pick_highlight(None, None)
        if first_well == well_id:
            # Restart with this pick as first
            self._link_pick_first = (well_id, top)
            self.correlation_canvas.set_pick_highlight(well_id, top_name)
            self.statusBar().showMessage(
                "请选择不同井上的层位 · 已将当前点设为起点", 5000
            )
            return
        try:
            link = self.create_horizon_link(first_well, first_top, well_id, top)
            self.statusBar().showMessage(
                f"已连线 {link.name}: {first_top.name} ↔ {top.name}", 5000
            )
        except WorkspaceError as exc:
            QMessageBox.warning(self, "连线失败", str(exc))

    def _on_toggle_prefer_engine(self) -> None:
        self._prefer_engine_canvas = self._act_prefer_engine.isChecked()
        if self._active_plot_type == "correlation":
            self._sync_primary_correlation_surface()
            kind = "对比"
        else:
            self._sync_primary_single_well_surface()
            kind = "单井"
        self._update_status()
        mode = "引擎" if self._primary_surface == "engine" else "主机"
        self.statusBar().showMessage(f"{kind}画布: {mode}", 4000)

    def _on_toggle_pick_tops(self, checked: bool = False) -> None:
        # Prefer checked state from action
        enabled = self._act_pick_tops.isChecked()
        if enabled and (
            self._presentation is None or self._selected_well_id is None
        ):
            self._act_pick_tops.setChecked(False)
            QMessageBox.information(
                self, "拾取层位", "请先应用图版到选中井，再开启拾取。"
            )
            return
        self.multi_track_canvas.set_pick_mode(enabled)
        # Pick needs host canvas; switch stack to host while picking
        self._sync_primary_single_well_surface()
        if enabled:
            self.document_tabs.setCurrentIndex(0)
            self.single_well_stack.setCurrentIndex(0)
            self.statusBar().showMessage(
                "拾取层位：主机画布单击；Shift+单击也可 · 关闭菜单项退出",
                8000,
            )

    def _on_canvas_top_pick(self, depth: float) -> None:
        if self._selected_well_id is None or self._workspace is None:
            return
        if (
            self._presentation is None
            or self._presentation.well_document_id != self._selected_well_id
        ):
            return
        name, ok = QInputDialog.getText(
            self,
            "新建层位",
            f"深度 {depth:.3f} 的层位名称：",
        )
        if not ok:
            return
        try:
            top = self.add_top_at_depth(self._selected_well_id, name, depth)
            self.statusBar().showMessage(
                f"已添加层位 {top.name} @ {top.depth:.3f}", 5000
            )
        except (TopsError, WorkspaceError) as exc:
            QMessageBox.warning(self, "添加层位失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "添加层位失败", str(exc))

    def _on_add_top_by_depth(self) -> None:
        if self._selected_well_id is None or self._presentation is None:
            QMessageBox.information(self, "添加层位", "请先选择井并应用图版。")
            return
        depth, ok = QInputDialog.getDouble(
            self,
            "按深度添加层位",
            "深度：",
            0.0,
            -1e9,
            1e9,
            3,
        )
        if not ok:
            return
        name, ok2 = QInputDialog.getText(self, "新建层位", "层位名称：")
        if not ok2:
            return
        try:
            top = self.add_top_at_depth(self._selected_well_id, name, depth)
            QMessageBox.information(
                self,
                "层位已添加",
                f"{top.display_label()}\n已写入 wells/…/tops.json",
            )
        except (TopsError, WorkspaceError) as exc:
            QMessageBox.warning(self, "添加层位失败", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "添加层位失败", str(exc))

    def _on_engine_preview(self) -> None:
        if self._presentation is None:
            QMessageBox.information(
                self, "引擎预览", "请先应用图版或打开单井分析图。"
            )
            return
        try:
            report = self.open_engine_preview()
            prepared = report.get("render_prepared")
            QMessageBox.information(
                self,
                "引擎预览",
                "已提交多图道 presentation 到 WellLogView（#225）。\n"
                f"render_prepared={prepared} · "
                f"tracks={report.get('track_count')} · "
                f"curves={report.get('curve_count')}\n"
                "主机多图道画布仍为默认路径；无引擎时自动降级。",
            )
        except EngineUnavailable as exc:
            QMessageBox.warning(self, "引擎不可用", str(exc))
        except EngineSubmitError as exc:
            QMessageBox.warning(self, "引擎提交失败", str(exc))

    def _on_engine_correlation_preview(self) -> None:
        if len(self._correlation_presentations) < 2:
            QMessageBox.information(
                self, "引擎对比预览", "请先新建/打开地层对比图（≥2 井）。"
            )
            return
        try:
            report = self.open_engine_correlation_preview()
            QMessageBox.information(
                self,
                "引擎对比预览",
                "已提交 multi-well section（共享深度）。\n"
                f"well_count={report.get('well_count')} · "
                f"render_prepared={report.get('render_prepared')}",
            )
        except EngineUnavailable as exc:
            QMessageBox.warning(self, "引擎不可用", str(exc))
        except EngineSubmitError as exc:
            QMessageBox.warning(self, "引擎提交失败", str(exc))
