"""HomePage — 工区地图 first.

The work-area map (工区地图) is the centerpiece: a real layered map fed by a
pure :mod:`~paleo_workbench.mapping.workarea_map_snapshot` producer through
the renderer-neutral :class:`~paleo_workbench.ui.unified_map_canvas.UnifiedMapCanvas`
(read-only — no tool controller; pan/zoom only).  Start guide, onboarding
report, workflow progress, module relationships and the dashboard cards stay
available around it, so the page contract (``update_state`` + the four
signals) is unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.workarea_map_snapshot import (
    WELLS_FLAGGED_LAYER_ID,
    WELLS_LAYER_ID,
    WORKAREA_LEGEND_ITEMS,
    build_workarea_map_snapshot,
    domain_signature,
    snapshot_has_map_content,
    workarea_crs_warnings,
    workarea_view_extent,
)
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.activity_card import RecentActivityCard
from paleo_workbench.ui.pages.completeness_card import DataCompletenessCard
from paleo_workbench.ui.pages.module_relationship import (
    LegendWidget,
    ModuleRelationshipWidget,
)
from paleo_workbench.ui.pages.workflow_contract_panel import WorkflowContractPanel
from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas

# Sentinel: the map has never been bound (≠ "bound to an empty project").
_MAP_UNBOUND = object()

_SIDE_COLUMN_WIDTH = 340
_SIDE_COLUMN_MIN_WIDTH = 260
_MAP_MIN_HEIGHT = 380


class HomePage(QWidget):
    navigation_requested = Signal(int)
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_requested = Signal()
    # 井位点击 → 数据页定位（well_id）
    well_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        self._project = None
        self._map_snapshot = None
        self._map_signature: object = _MAP_UNBOUND

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll Area to handle smaller screens gracefully
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        main_layout.addWidget(scroll)

        container = QWidget()
        container.setObjectName("HomeContainer")
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        layout.setSpacing(tokens.SPACE_3)

        from paleo_workbench.ui.pages.onboarding_report_card import OnboardingReportCard
        from paleo_workbench.ui.pages.start_guide_card import StartGuideCard

        # ---- centerpiece: work-area map + right-hand onboarding column ----
        # QSplitter: 右侧面板可拖拽调宽（原有固定 340px 改为初始宽）。
        map_row = QSplitter(Qt.Orientation.Horizontal)
        map_row.setChildrenCollapsible(False)

        map_panel = QFrame()
        map_panel.setObjectName("PanelCard")
        map_layout = QVBoxLayout(map_panel)
        map_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        map_layout.setSpacing(tokens.SPACE_2)

        # ⚠ banner for overlays withheld because their CRS frame doesn't
        # match the project — withholding must be visible, never silent (§20).
        self.crs_warning_label = QLabel("")
        self.crs_warning_label.setWordWrap(True)
        self.crs_warning_label.setStyleSheet(
            f"color: {tokens.WARNING}; font-size: {tokens.FONT_SIZE_STATUS}px;"
        )
        self.crs_warning_label.setVisible(False)
        map_layout.addWidget(self.crs_warning_label)

        self.map_stack = QStackedWidget()
        self.map_canvas = UnifiedMapCanvas()
        # Read-only embedding: no tool controller, navigation (pan/zoom) only.
        self.map_canvas.set_overlay_provider(self._map_overlay_state)
        self.map_canvas.map_clicked.connect(self._on_map_clicked)
        self.map_stack.addWidget(self.map_canvas)
        self.map_empty_state = self._build_empty_state()
        self.map_stack.addWidget(self.map_empty_state)
        self.map_stack.setMinimumHeight(_MAP_MIN_HEIGHT)
        map_layout.addWidget(self.map_stack, 1)

        map_row.addWidget(map_panel)

        self._side_column = QWidget()
        side_layout = QVBoxLayout(self._side_column)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(tokens.SPACE_3)
        self.start_guide_card = StartGuideCard()
        self.start_guide_card.new_project_requested.connect(self.new_project_requested.emit)
        self.start_guide_card.open_project_requested.connect(self.open_project_requested.emit)
        self.start_guide_card.open_sample_requested.connect(self.open_sample_requested.emit)
        self.onboarding_report_card = OnboardingReportCard()
        side_layout.addWidget(self.start_guide_card)
        side_layout.addWidget(self.onboarding_report_card)
        side_layout.addStretch(1)
        self._side_column.setMinimumWidth(_SIDE_COLUMN_MIN_WIDTH)
        map_row.addWidget(self._side_column)
        map_row.setStretchFactor(0, 1)
        map_row.setStretchFactor(1, 0)
        map_row.setSizes([900, _SIDE_COLUMN_WIDTH])

        # 上下分割条：工区地图与模块关系图之间可拖拽调整高度。
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setChildrenCollapsible(True)
        v_splitter.addWidget(map_row)

        # Title of the module relationship diagram
        title_container = QHBoxLayout()
        title_container.setContentsMargins(4, 0, 4, 0)

        title_label = QLabel("智能岩相古地理重建系统 - 模块关系图")
        title_label.setStyleSheet(f"""
            font-size: {tokens.FONT_SIZE_TITLE};
            font-weight: {tokens.FONT_WEIGHT_TITLE};
            color: {tokens.PRIMARY};
            font-family: {tokens.FONT_FAMILY};
        """)
        title_container.addWidget(title_label)

        # Add legend widget
        self.legend = LegendWidget()
        title_container.addWidget(self.legend)

        # 关系图区域（标题 + 图）作为竖向分割条的下半部分。
        diagram_panel = QWidget()
        diagram_layout = QVBoxLayout(diagram_panel)
        diagram_layout.setContentsMargins(0, 0, 0, 0)
        diagram_layout.setSpacing(tokens.SPACE_3)
        diagram_layout.addLayout(title_container)

        # Add relationship widget
        self.relationship_widget = ModuleRelationshipWidget()
        self.relationship_widget.setMinimumWidth(1100)
        self.relationship_widget.navigation_requested.connect(self.navigation_requested.emit)
        diagram_layout.addWidget(self.relationship_widget, 1)

        v_splitter.addWidget(diagram_panel)
        v_splitter.setStretchFactor(0, 1)
        v_splitter.setStretchFactor(1, 1)
        v_splitter.setSizes([420, 620])
        layout.addWidget(v_splitter, 1)

        # Set minimum width on container to prevent horizontal compression in scroll area
        container.setMinimumWidth(1140)

        bottom = QHBoxLayout()
        bottom.setSpacing(tokens.SPACE_3)
        self.activity_card = RecentActivityCard()
        self.completeness_card = DataCompletenessCard()
        self.contract_panel = WorkflowContractPanel()
        self.contract_panel.setMinimumWidth(280)
        self.contract_panel.setMaximumHeight(320)
        bottom.addWidget(self.activity_card, 1)
        bottom.addWidget(self.contract_panel, 1)
        bottom.addWidget(self.completeness_card, 0)
        layout.addLayout(bottom, 0)

    # ------------------------------------------------------------------
    # map centerpiece
    # ------------------------------------------------------------------

    def shutdown_workers(self, _wait_ms: int = 3_000) -> bool:
        """Stop the embedded map render backend before teardown (#1120 note).

        Hidden canvases never get a reliable closeEvent; AppShell calls this
        on project switch / exit alongside the other page workers.
        """
        self.map_canvas.shutdown()
        return True

    def _build_empty_state(self) -> QFrame:
        """Inviting empty state shown instead of the map for empty projects."""
        frame = QFrame()
        frame.setObjectName("HomeMapEmptyState")
        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("工区地图")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 18px; font-weight: 600;"
        )
        layout.addWidget(title)

        hint = QLabel(
            "暂无空间数据。导入井位与地震工区后，这里将展示\n工区边界、井位分布与地震测区范围。"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: {tokens.FONT_SIZE_BASE}px;"
        )
        layout.addWidget(hint)
        return frame

    def _map_overlay_state(self) -> dict:
        """Cheap decoration snapshot: title / scale bar / north arrow / legend."""
        return {
            "decorations": {
                "title": "工区地图",
                "elements": ("标题栏", "比例尺", "指北针", "图例"),
                "legend_items": [
                    {"label": label, "color": color} for label, color in WORKAREA_LEGEND_ITEMS
                ],
            }
        }

    def _refresh_map(self, project) -> None:
        """Rebuild the map snapshot only when domain content actually changed.

        ``domain_signature`` is the cheap invalidation key shared with the
        Data page and the Well Location map; keeping it lets pan/zoom state
        and the current frame survive unrelated home refreshes.
        """
        signature = domain_signature(project) if project is not None else None
        if signature == self._map_signature:
            self._update_crs_banner(project)
            return
        self._map_signature = signature
        snapshot = build_workarea_map_snapshot(project)
        self._map_snapshot = snapshot
        self.map_canvas.set_layer_snapshot(snapshot)
        extent = workarea_view_extent(snapshot)
        if extent is not None:
            self.map_canvas.set_extent(extent)
        self.map_stack.setCurrentIndex(0 if snapshot_has_map_content(snapshot) else 1)
        self._update_crs_banner(project)

    def _update_crs_banner(self, project) -> None:
        warnings = workarea_crs_warnings(project)
        self.crs_warning_label.setText("⚠ " + "；".join(warnings) if warnings else "")
        self.crs_warning_label.setVisible(bool(warnings))

    # 命中半径（屏幕像素）：以井符号为圆心的拾取容差
    _WELL_PICK_RADIUS_PX = 16.0

    def _on_map_clicked(self, point) -> None:
        """Left-click on the map: pick the nearest well within tolerance."""
        snapshot = self._map_snapshot
        if snapshot is None:
            return
        try:
            click_screen = self.map_canvas.map_to_screen(
                (float(point[0]), float(point[1]))
            )
        except (TypeError, ValueError, IndexError):
            return
        best_id = ""
        best_dist = self._WELL_PICK_RADIUS_PX
        for layer in snapshot.layers:
            if layer.id not in (WELLS_LAYER_ID, WELLS_FLAGGED_LAYER_ID):
                continue
            for feature in layer.features:
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates")
                if geometry.get("type") != "Point" or not coords:
                    continue
                screen = self.map_canvas.map_to_screen(
                    (float(coords[0]), float(coords[1]))
                )
                dx = screen.x() - click_screen.x()
                dy = screen.y() - click_screen.y()
                dist = (dx * dx + dy * dy) ** 0.5
                if dist <= best_dist:
                    best_dist = dist
                    best_id = str(feature.get("properties", {}).get("well_id") or "")
        if best_id:
            self.well_activated.emit(best_id)

    # ------------------------------------------------------------------
    # page contract
    # ------------------------------------------------------------------

    def update_state(self, state: dict, steps: list, project=None) -> None:
        # UI v2: the module-relationship diagram carries the workflow state;
        # the separate progress strip was removed per product decision.
        self.relationship_widget.update_states(steps)
        self.activity_card.update_state(state, steps)
        self.completeness_card.update_state(state)
        if project is not None:
            self._project = project
        if self._project is not None:
            self.contract_panel.set_project(self._project)
            # Map first incomplete/stale-ish step to a contract if possible
            step_to_contract = {
                "data_check": "data_import",
                "factor_map": "factor_interpolation",
                "prediction": "facies_prediction",
                "map_compile": "paleomap_compile",
                "qc": "quality_control",
                "export": "export",
            }
            for step in steps:
                cid = step_to_contract.get(getattr(step, "step_type", ""))
                if cid and getattr(step, "status", "") in {
                    "pending",
                    "stale",
                    "running",
                    "warning",
                }:
                    self.contract_panel.set_contract_id(cid)
                    break
        # Start guide visibility: no resources and no onboarding report
        resource_counts = state.get("resource_counts") if isinstance(state, dict) else None
        total_resources = 0
        if isinstance(resource_counts, dict):
            try:
                total_resources = sum(int(v) for v in resource_counts.values())
            except Exception:
                total_resources = 0
        onboarding = {}
        proj = project if project is not None else self._project
        if proj is not None:
            onboarding = getattr(proj, "onboarding_report", {}) or {}
        has_report = bool(onboarding)
        if hasattr(self, "start_guide_card"):
            show_guide = (total_resources == 0 and not has_report)
            self.start_guide_card.setVisible(show_guide)
        if hasattr(self, "onboarding_report_card"):
            report = onboarding if has_report else None
            # Also handle project is None case
            if proj is None:
                report = None
            else:
                report = onboarding if has_report else None
            self.onboarding_report_card.set_report(report)
        # The side column yields its width to the map when both cards hide.
        self._side_column.setVisible(
            not self.start_guide_card.isHidden() or not self.onboarding_report_card.isHidden()
        )
        # Work-area map follows the domain document (signature-gated).
        self._refresh_map(proj)
