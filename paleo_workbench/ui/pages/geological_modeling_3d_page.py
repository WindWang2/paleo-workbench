"""GeologicalModeling3DPage — premium 3D geological modeling workbench page.

Refactored to import Workers and Dialog from their own modules,
wire the geoviz well-tie / 3D-curve engine APIs into the
3D viewport rendering, and replace the hardcoded auto-tie stub
with a real cross-correlation implementation.
"""
from __future__ import annotations

import logging
import os

import numpy as np

from PySide6.QtCore import QRectF, Qt, QObject, QEvent, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QSlider, QSplitter, QProgressBar,
    QCheckBox, QSpinBox, QDoubleSpinBox, QScrollArea, QFileDialog, QMessageBox,
    QTabWidget, QGroupBox,
)
import pyqtgraph.opengl as gl

from paleo_workbench import tokens
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.joint_host import WellSeismicJointHost
from paleo_workbench.viz.joint_well_pick import (
    WellPickController,
    build_well_screen_geoms,
    pick_well_name,
)
from geoviz import (
    ClippedGLMeshItem,
    ClippedGLVolumeItem,
)
from paleo_workbench.viz.geomodel import analysis
from paleo_workbench.viz.geomodel.models import GridSpec
from paleo_workbench.ui.pages.geological_modeling_workers import (
    GeologicalModelingWorker,
    ExportWorker,
    AdvisorWorker,
    StratalWorker,
)
from paleo_workbench.ui.pages.ai_check_advisor_dialog import AICheckAdvisorDialog
from paleo_workbench.ui.pages.lithology_crossplot_dialog import LithologyCrossplotDialog

logger = logging.getLogger(__name__)


def _opengl_widget_supported() -> bool:
    """True when QOpenGLWidget can be shown on the current Qt platform.

    On the ``offscreen`` platform (headless CI / tests) Qt itself prints
    "QOpenGLWidget is not supported on this platform".  Showing a pyqtgraph
    GLViewWidget there makes Qt deliver paint events with no GL context, and
    pyqtgraph's ``initializeGL`` then crashes on ``self.context()`` returning
    None — which can segfault the process during event processing or teardown.
    ``QOpenGLContext.create()``/``makeCurrent()`` both lie here, so the
    platform chosen via ``QT_QPA_PLATFORM`` is the only reliable signal (the
    same check the 3D tests use, see
    tests/test_geological_modeling_3d_page.py::_opengl_widget_supported).
    """
    return os.environ.get("QT_QPA_PLATFORM", "") != "offscreen"


# ---- Camera Presets (eliminates duplicated lambdas) ----
_CAMERA_PERSPECTIVE = dict(distance=250, elevation=30, azimuth=45)
_CAMERA_TOP_DOWN = dict(distance=250, elevation=90, azimuth=0)


class GeologicalModeling3DPage(QWidget):
    """Well–seismic joint workbench page (nav: 井震联合).

    Features (PRD #120 / ticket #121):
    - Left: Scene tree — geoviz joint layers only.
    - Center: single joint 3D host + toolbar/status + collapsible fence 2D strip.
    - No right rail (modeling/export/AI chrome removed from this page).
    """

    # Cross-page linkage: a well picked in the 3D view is announced by name so
    # other pages (WellLog / Seismic) can sync their selection to it.
    well_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeologicalModeling3DPage")

        # Background threads keeper wrappers
        self._modeling_job = OwnedWorkerJob(self)
        self._export_job = OwnedWorkerJob(self)
        self._advisor_job = OwnedWorkerJob(self)
        self._stratal_job = OwnedWorkerJob(self)
        self.active_items: list[gl.GLGraphicsItem] = []
        self.mesh_items_map: dict[str, list[gl.GLMeshItem]] = {}
        self.bh_raw_data: list[dict] = []
        self.faults_raw_data: list[dict] = []
        # Well-seismic tie 3D overlay items (managed separately for re-generation)
        self._well_curve_items: list[gl.GLLinePlotItem] = []
        self._synthetic_items: list[gl.GLLinePlotItem] = []
        self._seismic_slice_items: list[gl.GLMeshItem] = []

        # Joint analysis host (geoviz) — PRD #85 / #88
        self._project: ProjectDocument | None = None
        # Lineage sources for mesh exports (E7): the input versions declared by
        # the most recent modeling run. Empty for synthetic demo runs (honest:
        # a synthetic grid has no source data to trace back to).
        self._last_modeling_run_inputs: list[str] = []
        self._joint_loaded_once = False
        self._joint_well_visibility_restored = False
        self._joint_widget = None
        self._joint_status = QLabel("")
        self._joint_host = WellSeismicJointHost(self)
        self._joint_host.status_changed.connect(self._on_joint_status)
        self._joint_host.scene_updated.connect(self._on_joint_scene_updated)
        # 3D well pick (#123): two-click → host fence
        self._well_pick = WellPickController()
        self._joint_pick_filter: QObject | None = None
        self._joint_pick_press: tuple[float, float] | None = None
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        main_layout.setSpacing(tokens.SPACE_2)

        # Horizontal splitter: left tree | center joint (no right rail — #121)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setStyleSheet("QSplitter::handle { background: %s; width: 1px; }" % tokens.BORDER)

        # 1. Left Panel: geoviz scene tree only
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens.SPACE_2)

        left_header = QLabel("场景对象")
        left_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        left_layout.addWidget(left_header)

        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("井震联合图层")
        self.model_tree.setStyleSheet("QTreeView { border: 1px solid %s; border-radius: %dpx; }" % (
            tokens.BORDER, tokens.RADIUS_CARD
        ))
        self._populate_model_tree()
        left_layout.addWidget(self.model_tree)

        # Off-layout modeling GL (G1a): keep for legacy modeling helpers; not main viewport
        self.gl_widget = gl.GLViewWidget(self)
        self.gl_widget.hide()
        self.gl_widget.opts["distance"] = 250
        self.gl_widget.setCameraPosition(**_CAMERA_PERSPECTIVE)
        grid = gl.GLGridItem()
        grid.setSize(300, 300, 300)
        grid.setSpacing(10, 10, 10)
        self.gl_widget.addItem(grid)
        self.btn_coord = None  # G1: no grid/geo coord toggle on chrome
        self._coord_mode = "grid"
        self._joint_align_btn = None
        self._joint_3d_panel = None

        # 2. Center column: joint 3D (top) + collapsible joint 2D (bottom) — G1 #106
        center_column = QWidget()
        center_column_layout = QVBoxLayout(center_column)
        center_column_layout.setContentsMargins(0, 0, 0, 0)
        center_column_layout.setSpacing(0)

        self._center_v_split = QSplitter(Qt.Vertical, center_column)
        self._center_v_split.setStyleSheet(
            "QSplitter::handle { background: %s; height: 3px; }" % tokens.BORDER
        )

        # Light chrome around dark 3D host (toolbar/status match app light theme)
        self.view_container = QFrame()
        self.view_container.setFrameShape(QFrame.StyledPanel)
        self.view_container.setStyleSheet(
            "QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }"
            % (tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER)
        )
        view_layout = QVBoxLayout(self.view_container)
        view_layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1)
        view_layout.setSpacing(tokens.SPACE_1)

        # Single-row joint toolbar — light surface (not canvas black)
        self.floating_bar = QFrame()
        self.floating_bar.setObjectName("JointTopToolbar")
        self.floating_bar.setStyleSheet(
            """
            QFrame#JointTopToolbar {
                background: %s;
                border: 1px solid %s;
                border-radius: %dpx;
            }
            QFrame#JointTopToolbar QLabel {
                color: %s;
                background: transparent;
                padding: 0 2px;
            }
            QFrame#JointTopToolbar QPushButton {
                background: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: %dpx;
                padding: 4px 10px;
                font-weight: 600;
            }
            QFrame#JointTopToolbar QPushButton:hover {
                background: %s;
                border-color: %s;
            }
            QFrame#JointTopToolbar QComboBox {
                background: %s;
                color: %s;
                border: 1px solid %s;
                border-radius: %dpx;
                padding: 2px 8px;
                min-height: 24px;
            }
            """
            % (
                tokens.BG_SIDEBAR,
                tokens.BORDER,
                tokens.RADIUS_BUTTON,
                tokens.TEXT_PRIMARY,
                tokens.BG_SEARCH,
                tokens.TEXT_PRIMARY,
                tokens.BORDER,
                tokens.RADIUS_BUTTON,
                tokens.BG_SELECTION,
                tokens.PRIMARY,
                tokens.BG_SIDEBAR,
                tokens.TEXT_PRIMARY,
                tokens.BORDER,
                tokens.RADIUS_BUTTON,
            )
        )
        f_layout = QHBoxLayout(self.floating_bar)
        f_layout.setContentsMargins(tokens.SPACE_2, 4, tokens.SPACE_2, 4)
        f_layout.setSpacing(tokens.SPACE_1)
        f_layout.addWidget(QLabel("域"))
        self._joint_domain = QComboBox()
        self._joint_domain.addItems(["Time", "Depth"])
        self._joint_domain.currentTextChanged.connect(self._on_joint_domain_changed)
        f_layout.addWidget(self._joint_domain)
        self._joint_slice_card_btn = QPushButton("正交切片")
        self._joint_slice_card_btn.setCheckable(True)
        self._joint_slice_card_btn.setChecked(True)
        self._joint_slice_card_btn.setToolTip(
            "设置 Inline、Crossline 与多张 Time 切片"
        )
        f_layout.addWidget(self._joint_slice_card_btn)
        # Professional analysis tab panel (stratal slices / well-tie / facies / export).
        self._joint_analysis_btn = QPushButton("分析")
        self._joint_analysis_btn.setCheckable(True)
        self._joint_analysis_btn.setChecked(False)
        self._joint_analysis_btn.setObjectName("JointAnalysisBtn")
        self._joint_analysis_btn.setToolTip(
            "等时/比例地层切片、井震标定、沉积相、导出与诊断"
        )
        f_layout.addWidget(self._joint_analysis_btn)
        # Interaction mode: pick (default) vs draw-snap (#124)
        f_layout.addWidget(QLabel("交互"))
        self._joint_pick_mode = QComboBox()
        self._joint_pick_mode.setObjectName("JointPickMode")
        self._joint_pick_mode.addItem("选井两点", "pick")
        self._joint_pick_mode.addItem("画线吸附", "draw")
        self._joint_pick_mode.currentIndexChanged.connect(self._on_joint_pick_mode_changed)
        f_layout.addWidget(self._joint_pick_mode)
        f_layout.addWidget(QLabel("井间"))
        self._joint_well_a = QComboBox()
        self._joint_well_b = QComboBox()
        f_layout.addWidget(self._joint_well_a)
        f_layout.addWidget(self._joint_well_b)
        self._joint_fence_btn = QPushButton("井间剖面")
        self._joint_fence_btn.clicked.connect(self._on_joint_fence)
        f_layout.addWidget(self._joint_fence_btn)
        self._joint_del_fence_btn = QPushButton("删 active")
        self._joint_del_fence_btn.setToolTip("删除当前活动井间剖面（保留其它 fence）")
        self._joint_del_fence_btn.clicked.connect(self._on_joint_delete_active_fence)
        f_layout.addWidget(self._joint_del_fence_btn)
        self._joint_add_btn = QPushButton("从工程/数据刷新")
        self._joint_add_btn.setToolTip("重新解析并挂载 SEGY / 井 / tops / LAS（hybrid）")
        self._joint_add_btn.clicked.connect(self._on_joint_add_from_project)
        f_layout.addWidget(self._joint_add_btn)
        f_layout.addSpacing(8)
        self.btn_orbit = QPushButton("透视视角")
        self.btn_pan = QPushButton("俯瞰视角")
        self.btn_reset = QPushButton("复位")
        self.btn_orbit.clicked.connect(lambda: self._apply_joint_camera_preset(_CAMERA_PERSPECTIVE))
        self.btn_pan.clicked.connect(lambda: self._apply_joint_camera_preset(_CAMERA_TOP_DOWN))
        self.btn_reset.clicked.connect(lambda: self._apply_joint_camera_preset(_CAMERA_PERSPECTIVE))
        f_layout.addWidget(self.btn_orbit)
        f_layout.addWidget(self.btn_pan)
        f_layout.addWidget(self.btn_reset)
        f_layout.addStretch()
        view_layout.addWidget(self.floating_bar)
        self._joint_slice_card = self._build_joint_slice_card()
        view_layout.addWidget(self._joint_slice_card)
        # Professional analysis panel — tabbed, toggled by the "分析" button.
        # The tabs reference legacy right-rail controls, so the card is created
        # empty here and populated once the right rail exists (deferred below).
        self._joint_analysis_card = self._build_joint_analysis_card()
        view_layout.addWidget(self._joint_analysis_card)

        # Status row under toolbar — light chrome, not canvas black
        self._joint_status.setWordWrap(True)
        self._joint_status.setObjectName("JointStatusRow")
        self._joint_status.setStyleSheet(
            "QLabel#JointStatusRow {"
            " color: %s; background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 4px 8px; font-size: 11px; }"
            % (tokens.TEXT_SECONDARY, tokens.BG_SEARCH, tokens.BORDER, tokens.RADIUS_BUTTON)
        )
        view_layout.addWidget(self._joint_status)

        self.joint_3d_host = QWidget()
        self.joint_3d_host.setObjectName("Joint3DHost")
        self.joint_3d_host.setStyleSheet(
            "QWidget#Joint3DHost { background: %s; border-radius: %dpx; }"
            % (tokens.BG_CANVAS, tokens.RADIUS_CARD)
        )
        j3_host_layout = QVBoxLayout(self.joint_3d_host)
        j3_host_layout.setContentsMargins(0, 0, 0, 0)
        self._joint_3d_placeholder = QLabel("井震联合 3D（主视口）")
        self._joint_3d_placeholder.setAlignment(Qt.AlignCenter)
        self._joint_3d_placeholder.setWordWrap(True)
        self._joint_3d_placeholder.setStyleSheet(
            "color: %s; padding: 12px; background: transparent;" % tokens.TEXT_ON_CANVAS
        )
        j3_host_layout.addWidget(self._joint_3d_placeholder)
        view_layout.addWidget(self.joint_3d_host, 1)

        self._center_v_split.addWidget(self.view_container)

        # Bottom: collapsible joint fence 2D strip
        self._joint_2d_panel = QFrame()
        self._joint_2d_panel.setObjectName("JointFence2DPanel")
        self._joint_2d_panel.setStyleSheet(
            "QFrame#JointFence2DPanel { background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (tokens.BG_SIDEBAR, tokens.BORDER, tokens.RADIUS_CARD)
        )
        j2_layout = QVBoxLayout(self._joint_2d_panel)
        j2_layout.setContentsMargins(tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1)
        j2_layout.setSpacing(tokens.SPACE_1)
        j2_header = QHBoxLayout()
        self._joint_2d_title = QLabel("井震剖面 (2D)")
        self._joint_2d_title.setStyleSheet(
            "font-weight: 600; color: %s;" % tokens.TEXT_PRIMARY
        )
        j2_header.addWidget(self._joint_2d_title)
        # Time-only chip (#122): 2D always Time even when 3D domain is Depth
        self._joint_2d_time_chip = QLabel("2D: Time")
        self._joint_2d_time_chip.setObjectName("Joint2DTimeChip")
        self._joint_2d_time_chip.setStyleSheet(
            "QLabel#Joint2DTimeChip {"
            " color: %s; background: %s; border: 1px solid %s; border-radius: 999px;"
            " padding: 2px 8px; font-size: 11px; }"
            % (tokens.PRIMARY, tokens.BG_SEARCH, tokens.BORDER)
        )
        j2_header.addWidget(self._joint_2d_time_chip)
        j2_header.addStretch()
        self._joint_color_card_btn = QPushButton("色标")
        self._joint_color_card_btn.setCheckable(True)
        self._joint_color_card_btn.setToolTip("选择地震/GR 色标并调整井轨迹宽度")
        j2_header.addWidget(self._joint_color_card_btn)
        self.btn_toggle_joint_2d = QPushButton("折叠")
        self.btn_toggle_joint_2d.setCheckable(True)
        self.btn_toggle_joint_2d.setChecked(False)
        self.btn_toggle_joint_2d.clicked.connect(self._toggle_joint_2d_panel)
        j2_header.addWidget(self.btn_toggle_joint_2d)
        j2_layout.addLayout(j2_header)

        self._joint_color_card = QFrame()
        self._joint_color_card.setObjectName("JointColorScaleCard")
        self._joint_color_card.setStyleSheet(
            "QFrame#JointColorScaleCard {"
            " background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 4px; }"
            % (tokens.BG_SEARCH, tokens.BORDER, tokens.RADIUS_BUTTON)
        )
        color_layout = QGridLayout(self._joint_color_card)
        color_layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        color_layout.setHorizontalSpacing(tokens.SPACE_2)
        color_layout.setVerticalSpacing(tokens.SPACE_1)
        color_layout.addWidget(QLabel("地震振幅"), 0, 0)
        self._joint_seismic_color = QComboBox()
        self._populate_color_scale_combo(
            self._joint_seismic_color,
            (
                ("蓝—白—红", "blue-white-red", ((33, 102, 172), (255, 255, 255), (178, 24, 43))),
                ("灰度", "gray", ((0, 0, 0), (128, 128, 128), (255, 255, 255))),
                ("红—白—蓝", "red-white-blue", ((178, 24, 43), (255, 255, 255), (33, 102, 172))),
            ),
        )
        color_layout.addWidget(self._joint_seismic_color, 0, 1)
        color_layout.addWidget(QLabel("GR 井轨迹"), 1, 0)
        self._joint_gr_color = QComboBox()
        self._populate_color_scale_combo(
            self._joint_gr_color,
            (
                ("viridis", "viridis", ((68, 1, 84), (33, 145, 140), (253, 231, 37))),
                ("cividis", "cividis", ((0, 34, 78), (122, 123, 120), (254, 232, 56))),
                ("plasma", "plasma", ((13, 8, 135), (204, 71, 120), (240, 249, 33))),
                ("turbo", "turbo", ((48, 18, 59), (26, 228, 182), (234, 42, 20))),
            ),
        )
        color_layout.addWidget(self._joint_gr_color, 1, 1)
        color_layout.addWidget(QLabel("井轨迹宽度"), 0, 2)
        self._joint_well_width = QSpinBox()
        self._joint_well_width.setRange(2, 10)
        self._joint_well_width.setValue(5)
        self._joint_well_width.setSuffix(" px")
        color_layout.addWidget(self._joint_well_width, 0, 3)
        color_layout.setColumnStretch(1, 1)
        color_layout.setColumnStretch(3, 1)
        self._joint_color_card.setVisible(False)
        self._joint_color_card_btn.toggled.connect(
            self._joint_color_card.setVisible
        )
        self._joint_seismic_color.currentIndexChanged.connect(
            self._apply_joint_display_settings
        )
        self._joint_gr_color.currentIndexChanged.connect(
            self._apply_joint_display_settings
        )
        self._joint_well_width.valueChanged.connect(
            self._apply_joint_display_settings
        )
        j2_layout.addWidget(self._joint_color_card)

        self.joint_2d_host = QWidget()
        self.joint_2d_host.setObjectName("Joint2DHost")
        j2_host_layout = QVBoxLayout(self.joint_2d_host)
        j2_host_layout.setContentsMargins(0, 0, 0, 0)
        self._joint_2d_placeholder = QLabel(
            "无活动剖面。加载后将自动建默认井对 fence；"
            "也可在 3D 点选两口井或用顶栏「井间剖面」。"
        )
        self._joint_2d_placeholder.setAlignment(Qt.AlignCenter)
        self._joint_2d_placeholder.setWordWrap(True)
        self._joint_2d_placeholder.setObjectName("Joint2DEmptyHint")
        self._joint_2d_placeholder.setStyleSheet(
            "color: %s; padding: 12px;" % tokens.TEXT_SECONDARY
        )
        j2_host_layout.addWidget(self._joint_2d_placeholder)
        j2_layout.addWidget(self.joint_2d_host, 1)
        self._center_v_split.addWidget(self._joint_2d_panel)
        self._center_v_split.setStretchFactor(0, 3)
        self._center_v_split.setStretchFactor(1, 1)
        self._center_v_split.setSizes([700, 220])
        self._joint_2d_expanded_sizes = [700, 220]

        center_column_layout.addWidget(self._center_v_split)

        # 3. Right Panel: Parameters & Exporters (Scrollable)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setStyleSheet("QScrollArea { border: none; }")

        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(tokens.SPACE_2)

        right_header = QLabel("三维可视化与模拟接口")
        right_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        right_layout.addWidget(right_header)

        # CARD 1: Modeling Config
        card_config = QFrame()
        card_config.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER
        ))
        cfg_layout = QVBoxLayout(card_config)
        cfg_layout.setSpacing(tokens.SPACE_2)

        title_cfg = QLabel("建模计算参数")
        title_cfg.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        cfg_layout.addWidget(title_cfg)

        cfg_layout.addWidget(QLabel("网格密度 (Grid Density)"))
        self.combo_density = QComboBox()
        self.combo_density.addItems(["低精度 (40x40x40)", "中精度 (80x80x80)", "高精度 (120x120x120)"])
        self.combo_density.setCurrentIndex(1)
        cfg_layout.addWidget(self.combo_density)

        cfg_layout.addWidget(QLabel("数据来源"))
        # The 属性插值算法 selector (克里金/SGS/IDW) advertised algorithms that
        # were never executed — removed in the P2 scientific-honesty wave. The
        # current volume/borehole/tunnel/fault data is synthetic demo data.
        self.demo_source_label = QLabel("合成演示数据 (Demo)")
        self.demo_source_label.setObjectName("DemoSourceLabel")
        self.demo_source_label.setStyleSheet(
            "color: #b58900; font-weight: 600;"
        )
        cfg_layout.addWidget(self.demo_source_label)

        cfg_layout.addWidget(QLabel("地层模型不透明度 (Volume Opacity)"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(40)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        cfg_layout.addWidget(self.slider_opacity)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        cfg_layout.addWidget(self.progress_bar)

        self.btn_run = QPushButton("开始三维建模")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_modeling)
        cfg_layout.addWidget(self.btn_run)

        right_layout.addWidget(card_config)

        # CARD 2: 3-Way Interactive Clipping
        card_clip = QFrame()
        card_clip.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER
        ))
        clip_layout = QVBoxLayout(card_clip)
        clip_layout.setSpacing(tokens.SPACE_2)

        title_clip = QLabel("三向交互剖切 (GPU Clipping)")
        title_clip.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        clip_layout.addWidget(title_clip)

        # X-Axis Clip controls
        self.chk_clip_x = QCheckBox("启用 X 轴剖切")
        self.slide_clip_x = QSlider(Qt.Horizontal)
        self.slide_clip_x.setRange(0, 100)
        self.slide_clip_x.setValue(50)
        self.combo_clip_x_dir = QComboBox()
        self.combo_clip_x_dir.addItems(["保留右侧 (x >= val)", "保留左侧 (x <= val)"])
        clip_layout.addWidget(self.chk_clip_x)
        clip_layout.addWidget(self.slide_clip_x)
        clip_layout.addWidget(self.combo_clip_x_dir)

        # Y-Axis Clip controls
        self.chk_clip_y = QCheckBox("启用 Y 轴剖切")
        self.slide_clip_y = QSlider(Qt.Horizontal)
        self.slide_clip_y.setRange(0, 100)
        self.slide_clip_y.setValue(50)
        self.combo_clip_y_dir = QComboBox()
        self.combo_clip_y_dir.addItems(["保留前侧 (y >= val)", "保留后侧 (y <= val)"])
        clip_layout.addWidget(self.chk_clip_y)
        clip_layout.addWidget(self.slide_clip_y)
        clip_layout.addWidget(self.combo_clip_y_dir)

        # Z-Axis Clip controls
        self.chk_clip_z = QCheckBox("启用 Z 轴剖切")
        self.slide_clip_z = QSlider(Qt.Horizontal)
        self.slide_clip_z.setRange(0, 100)
        self.slide_clip_z.setValue(50)
        self.combo_clip_z_dir = QComboBox()
        self.combo_clip_z_dir.addItems(["保留上方 (z >= val)", "保留下方 (z <= val)"])
        clip_layout.addWidget(self.chk_clip_z)
        clip_layout.addWidget(self.slide_clip_z)
        clip_layout.addWidget(self.combo_clip_z_dir)

        # Wire clipping events (helpers retained; card hidden in G1 — #110)
        self.chk_clip_x.stateChanged.connect(self._update_clipping)
        self.slide_clip_x.valueChanged.connect(self._update_clipping)
        self.combo_clip_x_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_y.stateChanged.connect(self._update_clipping)
        self.slide_clip_y.valueChanged.connect(self._update_clipping)
        self.combo_clip_y_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_z.stateChanged.connect(self._update_clipping)
        self.slide_clip_z.valueChanged.connect(self._update_clipping)
        self.combo_clip_z_dir.currentIndexChanged.connect(self._update_clipping)

        self._card_clip = card_clip
        card_clip.hide()
        # G1: do not add clip card to right rail

        # CARD 3: Simulator Mesh Exporters
        card_export = QFrame()
        card_export.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER
        ))
        exp_layout = QVBoxLayout(card_export)
        exp_layout.setSpacing(tokens.SPACE_2)

        title_exp = QLabel("数值模拟分析接口 (Export)")
        title_exp.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        exp_layout.addWidget(title_exp)

        exp_layout.addWidget(QLabel("导出格式"))
        self.combo_export_type = QComboBox()
        self.combo_export_type.addItems(["FLAC3D 角点网格 (*.f3grid)", "Abaqus 有限元网格 (*.inp)"])
        exp_layout.addWidget(self.combo_export_type)

        grid_grid_layout = QHBoxLayout()
        grid_grid_layout.setSpacing(tokens.SPACE_1)

        # NX NY NZ
        vbox_nx = QVBoxLayout()
        vbox_nx.addWidget(QLabel("NX"))
        self.spin_nx = QSpinBox()
        self.spin_nx.setRange(2, 200)
        self.spin_nx.setValue(20)
        vbox_nx.addWidget(self.spin_nx)
        grid_grid_layout.addLayout(vbox_nx)

        vbox_ny = QVBoxLayout()
        vbox_ny.addWidget(QLabel("NY"))
        self.spin_ny = QSpinBox()
        self.spin_ny.setRange(2, 200)
        self.spin_ny.setValue(20)
        vbox_ny.addWidget(self.spin_ny)
        grid_grid_layout.addLayout(vbox_ny)

        vbox_nz = QVBoxLayout()
        vbox_nz.addWidget(QLabel("NZ"))
        self.spin_nz = QSpinBox()
        self.spin_nz.setRange(2, 200)
        self.spin_nz.setValue(15)
        vbox_nz.addWidget(self.spin_nz)
        grid_grid_layout.addLayout(vbox_nz)

        exp_layout.addLayout(grid_grid_layout)

        grid_size_layout = QHBoxLayout()
        grid_size_layout.setSpacing(tokens.SPACE_1)

        # DX DY DZ
        vbox_dx = QVBoxLayout()
        vbox_dx.addWidget(QLabel("DX (m)"))
        self.spin_dx = QDoubleSpinBox()
        self.spin_dx.setRange(0.5, 500.0)
        self.spin_dx.setValue(10.0)
        vbox_dx.addWidget(self.spin_dx)
        grid_size_layout.addLayout(vbox_dx)

        vbox_dy = QVBoxLayout()
        vbox_dy.addWidget(QLabel("DY (m)"))
        self.spin_dy = QDoubleSpinBox()
        self.spin_dy.setRange(0.5, 500.0)
        self.spin_dy.setValue(10.0)
        vbox_dy.addWidget(self.spin_dy)
        grid_size_layout.addLayout(vbox_dy)

        vbox_dz = QVBoxLayout()
        vbox_dz.addWidget(QLabel("DZ (m)"))
        self.spin_dz = QDoubleSpinBox()
        self.spin_dz.setRange(0.5, 500.0)
        self.spin_dz.setValue(8.0)
        vbox_dz.addWidget(self.spin_dz)
        grid_size_layout.addLayout(vbox_dz)

        exp_layout.addLayout(grid_size_layout)

        self.btn_export = QPushButton("导出数值模拟模型")
        self.btn_export.setObjectName("SecondaryButton")
        self.btn_export.clicked.connect(self._export_mesh)
        exp_layout.addWidget(self.btn_export)

        right_layout.addWidget(card_export)

        # CARD 4: Rule-based Consistency Advisor Side Dialog
        card_ai = QFrame()
        card_ai.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SEARCH, tokens.RADIUS_CARD, tokens.BORDER
        ))
        ai_layout = QVBoxLayout(card_ai)
        ai_layout.setSpacing(tokens.SPACE_2)

        title_ai = QLabel("地质数据一致性核复顾问")
        title_ai.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        ai_layout.addWidget(title_ai)

        desc_ai = QLabel("基于规则自动分析当前项目下所有钻孔的深度分层完整性，并校验平行断层共面问题。")
        desc_ai.setWordWrap(True)
        desc_ai.setStyleSheet("font-size: 11px; color: %s;" % tokens.TEXT_SECONDARY)
        ai_layout.addWidget(desc_ai)

        self.btn_ai_advisor = QPushButton("开启一致性诊断")
        self.btn_ai_advisor.setObjectName("PrimaryButton")
        self.btn_ai_advisor.setEnabled(False)  # Enable only after data is loaded
        self.btn_ai_advisor.clicked.connect(self._run_ai_advisor)
        ai_layout.addWidget(self.btn_ai_advisor)

        right_layout.addWidget(card_ai)

        # CARD 5: Well-Seismic Tie Calibration & Analysis Controls
        card_tie = QFrame()
        card_tie.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER
        ))
        tie_layout = QVBoxLayout(card_tie)
        tie_layout.setSpacing(tokens.SPACE_2)

        title_tie = QLabel("井震融合校正 (Well-Seismic Calibration)")
        title_tie.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        tie_layout.addWidget(title_tie)

        tie_layout.addWidget(QLabel("主频 (Wavelet Frequency)"))
        self.slider_wavelet_freq = QSlider(Qt.Horizontal)
        self.slider_wavelet_freq.setRange(10, 80)
        self.slider_wavelet_freq.setValue(35)
        self.slider_wavelet_freq.valueChanged.connect(self._on_tie_params_changed)
        tie_layout.addWidget(self.slider_wavelet_freq)

        tie_layout.addWidget(QLabel("时深时移校正 (T-D Shift Calibration)"))
        self.slider_td_shift = QSlider(Qt.Horizontal)
        self.slider_td_shift.setRange(-50, 50)
        self.slider_td_shift.setValue(0)
        self.slider_td_shift.valueChanged.connect(self._on_tie_params_changed)
        tie_layout.addWidget(self.slider_td_shift)

        self.label_correlation = QLabel("互相关系数 (Cross-Correlation CC): —")
        self.label_correlation.setStyleSheet("font-size: 11px; color: %s; font-weight: bold;" % tokens.SUCCESS)
        tie_layout.addWidget(self.label_correlation)

        self.btn_auto_tie = QPushButton("自动互相关对齐 (Auto-Tie)")
        self.btn_auto_tie.setObjectName("SecondaryButton")
        self.btn_auto_tie.clicked.connect(self._run_auto_tie)
        tie_layout.addWidget(self.btn_auto_tie)

        right_layout.addWidget(card_tie)

        # CARD 6: Advanced Multi-Attribute & Crossplot Analysis
        card_adv = QFrame()
        card_adv.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SIDEBAR, tokens.RADIUS_CARD, tokens.BORDER
        ))
        adv_layout = QVBoxLayout(card_adv)
        adv_layout.setSpacing(tokens.SPACE_2)

        title_adv = QLabel("高级地震与井震综合分析")
        title_adv.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        adv_layout.addWidget(title_adv)

        self.btn_rgb_fusion = QPushButton("生成 RGB 三频率属性融合切片")
        self.btn_rgb_fusion.setObjectName("SecondaryButton")
        self.btn_rgb_fusion.clicked.connect(self._generate_rgb_fusion_slice)
        adv_layout.addWidget(self.btn_rgb_fusion)

        self.btn_cross_fence = QPushButton("生成井震连井三维剖面幕墙")
        self.btn_cross_fence.setObjectName("SecondaryButton")
        self.btn_cross_fence.clicked.connect(self._generate_cross_well_fence)
        adv_layout.addWidget(self.btn_cross_fence)

        self.btn_crossplot = QPushButton("开启波阻抗/GR 岩相交会图分析")
        self.btn_crossplot.setObjectName("PrimaryButton")
        self.btn_crossplot.clicked.connect(self._run_lithology_crossplot)
        adv_layout.addWidget(self.btn_crossplot)

        right_layout.addWidget(card_adv)
        right_layout.addStretch()

        right_scroll.setWidget(right_widget)
        # Off-layout legacy modeling chrome (params/export/AI) — not in page splitter (#121)
        right_scroll.setParent(self)
        right_scroll.hide()
        self._right_rail = right_scroll

        # Now that the legacy right-rail controls exist, populate the analysis
        # tabs (well-tie / facies / export proxy to those controls).
        self._populate_joint_analysis_tabs()

        # Constrain left tree; center takes remaining width
        left_widget.setMinimumWidth(220)
        left_widget.setMaximumWidth(320)

        # Two columns: left tree | center (joint 3D + 2D)
        splitter.addWidget(left_widget)
        splitter.addWidget(center_column)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 1200])
        self._main_splitter = splitter

        main_layout.addWidget(splitter)

    @staticmethod
    def _populate_color_scale_combo(
        combo: QComboBox,
        choices: tuple[
            tuple[str, str, tuple[tuple[int, int, int], ...]], ...
        ],
    ) -> None:
        for label, key, colors in choices:
            pix = QPixmap(72, 14)
            gradient = QLinearGradient(0.0, 0.0, 72.0, 0.0)
            for index, color in enumerate(colors):
                gradient.setColorAt(
                    index / max(len(colors) - 1, 1),
                    QColor(*color),
                )
            painter = QPainter(pix)
            painter.fillRect(QRectF(0, 0, 72, 14), QBrush(gradient))
            painter.end()
            combo.addItem(QIcon(pix), label, key)

    def _toggle_joint_2d_panel(self) -> None:
        """Collapse/expand bottom joint fence 2D strip (#87)."""
        collapsed = self.btn_toggle_joint_2d.isChecked()
        self.joint_2d_host.setVisible(not collapsed)
        self.btn_toggle_joint_2d.setText("展开" if collapsed else "折叠")
        if collapsed:
            self._joint_2d_expanded_sizes = self._center_v_split.sizes()
            total = sum(self._joint_2d_expanded_sizes) or 900
            self._center_v_split.setSizes([max(total - 36, 100), 36])
        else:
            sizes = getattr(self, "_joint_2d_expanded_sizes", None) or [700, 220]
            self._center_v_split.setSizes(sizes)

    def _apply_joint_camera_preset(self, preset: dict) -> None:
        """Map toolbar camera buttons to joint widget public set_camera_pose."""
        if self._joint_widget is None:
            self._ensure_joint_widget()
        w = self._joint_widget
        if w is None:
            return
        set_pose = getattr(w, "set_camera_pose", None)
        if callable(set_pose):
            try:
                set_pose(
                    distance=float(preset.get("distance", 250) or 250),
                    elevation=float(preset.get("elevation", 30) or 30),
                    azimuth=float(preset.get("azimuth", 45) or 45),
                )
            except Exception:
                logger.debug("joint camera preset failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Model Tree
    # ------------------------------------------------------------------ #

    def _populate_model_tree(self) -> None:
        """Build geoviz joint layers only (#121 / #114 C1)."""
        self.model_tree.clear()

        root_joint = QTreeWidgetItem(self.model_tree, ["井震联合 (geoviz)"])
        self._add_checkable_child(root_joint, "地震预览体 (geoviz)")
        self._joint_wells_tree_item = self._add_checkable_child(
            root_joint, "联合井轨迹 (geoviz)"
        )
        self._add_checkable_child(root_joint, "井间剖面 fence (geoviz)")
        self._stratal_tree_item = self._add_checkable_child(
            root_joint, "地层切片体 (geoviz)"
        )
        self._add_checkable_child(root_joint, "井震 3D 视口")
        self._add_checkable_child(root_joint, "井震 2D 剖面条")

        self.model_tree.expandAll()
        if not getattr(self, "_tree_changed_hooked", False):
            self.model_tree.itemChanged.connect(self._on_tree_item_changed)
            self._tree_changed_hooked = True

    def _add_checkable_child(
        self, parent_item: QTreeWidgetItem, name: str
    ) -> QTreeWidgetItem:
        item = QTreeWidgetItem(parent_item, [name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setCheckState(0, Qt.Checked)
        return item

    def _refresh_joint_well_tree(self) -> None:
        """Rebuild per-well checkbox children from the scene presentation model."""
        parent = getattr(self, "_joint_wells_tree_item", None)
        scene = self._joint_host.scene
        if parent is None or scene is None:
            return
        presentations = scene.well_presentations()
        if (
            presentations
            and not self._joint_well_visibility_restored
            and self._project is not None
        ):
            state = getattr(self._project, "joint_analysis", None)
            saved = dict(getattr(state, "well_visibility", None) or {})
            for presentation in presentations:
                if presentation.id in saved:
                    scene.set_well_visibility(
                        presentation.id, bool(saved[presentation.id])
                    )
            if not saved:
                legacy_checks = dict(
                    getattr(state, "tree_checks", None) or {}
                )
                if legacy_checks.get("联合井轨迹 (geoviz)") is False:
                    for presentation in presentations:
                        scene.set_well_visibility(presentation.id, False)
            self._joint_well_visibility_restored = True
            presentations = scene.well_presentations()
        self.model_tree.blockSignals(True)
        try:
            parent.takeChildren()
            for presentation in presentations:
                item = self._add_checkable_child(parent, presentation.display_name)
                item.setData(0, Qt.ItemDataRole.UserRole, presentation.id)
                item.setCheckState(
                    0,
                    Qt.Checked if presentation.visible else Qt.Unchecked,
                )
            parent_state = self._joint_well_parent_state()
            if parent_state is not None:
                parent.setCheckState(0, parent_state)
        finally:
            self.model_tree.blockSignals(False)
        parent.setExpanded(True)

    def _joint_well_parent_state(self):
        """Derive the parent checkbox state from its current well children."""
        parent = getattr(self, "_joint_wells_tree_item", None)
        if parent is None or parent.childCount() == 0:
            return None
        states = [
            parent.child(index).checkState(0)
            for index in range(parent.childCount())
        ]
        if all(state == Qt.Checked for state in states):
            return Qt.Checked
        if all(state == Qt.Unchecked for state in states):
            return Qt.Unchecked
        return Qt.PartiallyChecked

    def set_project(self, project: ProjectDocument | None) -> None:
        self._project = project
        self._joint_well_visibility_restored = False
        # Provenance memory is per-project: never carry the previous project's
        # modeling inputs into the next one's mesh exports.
        self._last_modeling_run_inputs = []
        self._joint_host.set_project(project)
        self._restore_joint_display_settings()
        self._restore_joint_slice_settings()

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Join the page's OwnedWorkerJobs on project switch / app close.

        Mirrors the teardown hook sibling pages expose so AppShell.shutdown_workers
        reclaims the modeling/export/advisor/stratal jobs (and their result
        connections into this page) instead of letting them run against a
        closed catalog/document.
        """
        joined = True
        for job in (self._modeling_job, self._export_job, self._advisor_job, self._stratal_job):
            if not job.shutdown(wait_ms):
                joined = False
        return joined

    def _build_joint_slice_card(self) -> QFrame:
        """Build a one-row control surface for orthogonal slices."""
        card = QFrame()
        card.setObjectName("JointOrthogonalSliceCard")
        card.setMaximumHeight(52)
        card.setStyleSheet(
            "QFrame#JointOrthogonalSliceCard {"
            " background: %s; border: 1px solid %s; border-radius: %dpx;"
            " padding: 3px; }"
            % (tokens.BG_SEARCH, tokens.BORDER, tokens.RADIUS_BUTTON)
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(
            tokens.SPACE_2,
            tokens.SPACE_1,
            tokens.SPACE_2,
            tokens.SPACE_1,
        )
        layout.setSpacing(tokens.SPACE_1)

        layout.addWidget(QLabel("IL"))
        self._joint_inline_slice = QSpinBox()
        self._joint_inline_slice.setRange(0, 0)
        self._joint_inline_slice.setMaximumWidth(92)
        self._joint_inline_slice.setAccessibleName("Inline 切片位置")
        layout.addWidget(self._joint_inline_slice)
        layout.addWidget(QLabel("XL"))
        self._joint_crossline_slice = QSpinBox()
        self._joint_crossline_slice.setRange(0, 0)
        self._joint_crossline_slice.setMaximumWidth(92)
        self._joint_crossline_slice.setAccessibleName(
            "Crossline 切片位置"
        )
        layout.addWidget(self._joint_crossline_slice)

        layout.addSpacing(tokens.SPACE_1)
        layout.addWidget(QLabel("Time"))
        self._joint_time_selector = QComboBox()
        self._joint_time_selector.setMaximumWidth(126)
        self._joint_time_selector.setAccessibleName("活动 Time 切片")
        self._joint_time_selector.setToolTip(
            "选择当前要编辑和交互的 Time 切片"
        )
        layout.addWidget(self._joint_time_selector)
        self._joint_active_time_editor = QDoubleSpinBox()
        self._joint_active_time_editor.setDecimals(3)
        self._joint_active_time_editor.setRange(0.0, 0.0)
        self._joint_active_time_editor.setSuffix(" ms")
        self._joint_active_time_editor.setMaximumWidth(126)
        self._joint_active_time_editor.setAccessibleName(
            "活动 Time 切片时间"
        )
        layout.addWidget(self._joint_active_time_editor)
        self._joint_active_time_visible = QCheckBox("显示")
        self._joint_active_time_visible.setAccessibleName(
            "活动 Time 切片可见性"
        )
        layout.addWidget(self._joint_active_time_visible)
        self._joint_delete_time_slice = QPushButton("删除")
        self._joint_delete_time_slice.setAccessibleName(
            "删除活动 Time 切片"
        )
        layout.addWidget(self._joint_delete_time_slice)

        layout.addSpacing(tokens.SPACE_1)
        layout.addWidget(QLabel("新增"))
        self._joint_new_time = QDoubleSpinBox()
        self._joint_new_time.setDecimals(3)
        self._joint_new_time.setRange(0.0, 0.0)
        self._joint_new_time.setSuffix(" ms")
        self._joint_new_time.setMaximumWidth(126)
        self._joint_new_time.setAccessibleName("新增 Time 切片时间")
        layout.addWidget(self._joint_new_time)
        self._joint_add_time_slice = QPushButton("+")
        self._joint_add_time_slice.setToolTip("添加 Time 切片")
        self._joint_add_time_slice.setAccessibleName("添加 Time 切片")
        layout.addWidget(self._joint_add_time_slice)

        layout.addSpacing(tokens.SPACE_1)
        layout.addWidget(QLabel("透明度"))
        self._joint_time_opacity = QSpinBox()
        self._joint_time_opacity.setRange(10, 100)
        self._joint_time_opacity.setValue(80)
        self._joint_time_opacity.setSuffix("%")
        self._joint_time_opacity.setMaximumWidth(84)
        self._joint_time_opacity.setAccessibleName("Time 切片透明度")
        layout.addWidget(self._joint_time_opacity)

        self._joint_time_domain_note = QLabel("")
        self._joint_time_domain_note.setWordWrap(False)
        self._joint_time_domain_note.setStyleSheet(
            "color: %s; background: transparent;" % tokens.TEXT_SECONDARY
        )
        self._joint_time_domain_note.setToolTip(
            "时间会自动吸附到可显示的 SEG-Y 样点"
        )
        layout.addWidget(self._joint_time_domain_note)
        layout.addStretch(1)

        self._joint_slice_card_btn.toggled.connect(card.setVisible)
        self._joint_inline_slice.valueChanged.connect(
            self._on_joint_inline_slice_changed
        )
        self._joint_crossline_slice.valueChanged.connect(
            self._on_joint_crossline_slice_changed
        )
        self._joint_add_time_slice.clicked.connect(
            self._on_joint_add_time_slice
        )
        self._joint_time_selector.currentIndexChanged.connect(
            self._on_joint_time_selector_changed
        )
        self._joint_active_time_editor.editingFinished.connect(
            self._on_joint_active_time_edited
        )
        self._joint_active_time_visible.toggled.connect(
            self._on_joint_active_time_visibility_changed
        )
        self._joint_delete_time_slice.clicked.connect(
            self._on_joint_delete_active_time_slice
        )
        self._joint_time_opacity.valueChanged.connect(
            self._on_joint_time_opacity_changed
        )
        card.setVisible(True)
        return card

    # ------------------------------------------------------------------
    # Professional analysis card (tabbed: stratal / well-tie / facies / export)
    # ------------------------------------------------------------------

    def _build_joint_analysis_card(self) -> QFrame:
        """Tabbed professional analysis panel, toggled by the "分析" button.

        Groups the stage-2 stratal/proportional-slice feature plus the existing
        well-tie, facies and export/diagnostics flows into one labeled surface,
        without disturbing the deliberately two-column well-seismic workbench
        layout (the legacy right rail stays hidden).
        """
        card = QFrame()
        card.setObjectName("JointAnalysisCard")
        card.setStyleSheet(
            "QFrame#JointAnalysisCard {"
            " background: %s; border: 1px solid %s; border-radius: %dpx; }"
            % (tokens.BG_SIDEBAR, tokens.BORDER, tokens.RADIUS_CARD)
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1, tokens.SPACE_1
        )
        layout.setSpacing(tokens.SPACE_1)

        self._joint_analysis_tabs = QTabWidget()
        self._joint_analysis_tabs.setObjectName("JointAnalysisTabs")
        layout.addWidget(self._joint_analysis_tabs)

        # Tabs are populated lazily (_populate_joint_analysis_tabs) because they
        # reference legacy right-rail controls that are built later in __init__.
        self._stratal_status: QLabel | None = None

        # Hidden until the "分析" button is toggled on.
        card.setVisible(False)
        self._joint_analysis_btn.toggled.connect(card.setVisible)
        return card

    def _populate_joint_analysis_tabs(self) -> None:
        """Add the four analysis tabs. Called after the legacy right rail exists."""
        if self._joint_analysis_tabs.count() > 0:
            return  # already populated
        self._joint_analysis_tabs.addTab(
            self._build_stratal_tab(), "等时切片与属性"
        )
        self._joint_analysis_tabs.addTab(
            self._build_welltie_tab(), "井震标定"
        )
        self._joint_analysis_tabs.addTab(
            self._build_facies_tab(), "沉积相解释"
        )
        self._joint_analysis_tabs.addTab(
            self._build_export_diag_tab(), "导出与诊断"
        )

    def _build_stratal_tab(self) -> QWidget:
        """Stratal / proportional slice controls — the stage-2 demo entry."""
        from paleo_workbench.viz.stratal_adapter import build_stratal_grids

        tab = QWidget()
        form = QGridLayout(tab)
        form.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        form.setHorizontalSpacing(tokens.SPACE_2)
        form.setVerticalSpacing(tokens.SPACE_1)

        hint = QLabel(
            "在两个 horizon 之间生成比例地层切片，沿地层格架揭示沉积相。"
            "无 SEGY 时可用合成演示体预览。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s; font-size: 11px;" % tokens.TEXT_SECONDARY)
        form.addWidget(hint, 0, 0, 1, 3)

        form.addWidget(QLabel("顶部 horizon"), 1, 0)
        self._stratal_top_combo = QComboBox()
        self._stratal_top_combo.setObjectName("StratalTopCombo")
        self._stratal_top_combo.addItem("（未选择）", None)
        form.addWidget(self._stratal_top_combo, 1, 1)
        self._stratal_top_browse = QPushButton("浏览…")
        self._stratal_top_browse.clicked.connect(
            lambda: self._pick_stratal_horizon(self._stratal_top_combo, "顶部 horizon")
        )
        form.addWidget(self._stratal_top_browse, 1, 2)

        form.addWidget(QLabel("底部 horizon"), 2, 0)
        self._stratal_bot_combo = QComboBox()
        self._stratal_bot_combo.setObjectName("StratalBotCombo")
        self._stratal_bot_combo.addItem("（未选择）", None)
        form.addWidget(self._stratal_bot_combo, 2, 1)
        self._stratal_bot_browse = QPushButton("浏览…")
        self._stratal_bot_browse.clicked.connect(
            lambda: self._pick_stratal_horizon(self._stratal_bot_combo, "底部 horizon")
        )
        form.addWidget(self._stratal_bot_browse, 2, 2)

        form.addWidget(QLabel("比例切片"), 3, 0)
        self._stratal_fractions = QComboBox()
        self._stratal_fractions.setObjectName("StratalFractions")
        self._stratal_fractions.addItem("1/4, 1/2, 3/4", (0.25, 0.50, 0.75))
        self._stratal_fractions.addItem("1/3, 2/3", (1 / 3, 2 / 3))
        self._stratal_fractions.addItem("仅 1/2", (0.50,))
        self._stratal_fractions.addItem("顶 + 底", (0.0, 1.0))
        form.addWidget(self._stratal_fractions, 3, 1, 1, 2)

        self._stratal_demo_check = QCheckBox("用合成演示体（无 SEGY 时预览）")
        self._stratal_demo_check.setChecked(False)
        self._stratal_demo_check.setObjectName("StratalDemoCheck")
        form.addWidget(self._stratal_demo_check, 4, 0, 1, 3)

        btn_row = QHBoxLayout()
        self.btn_stratal_generate = QPushButton("生成地层切片")
        self.btn_stratal_generate.setObjectName("StratalGenerateBtn")
        self.btn_stratal_generate.setToolTip(
            "在两个 horizon 之间按比例生成地层切片并叠加到 3D 视口"
        )
        self.btn_stratal_generate.clicked.connect(self._on_generate_stratal_slices)
        btn_row.addWidget(self.btn_stratal_generate)
        self.btn_stratal_clear = QPushButton("清除")
        self.btn_stratal_clear.setObjectName("StratalClearBtn")
        self.btn_stratal_clear.clicked.connect(self._on_clear_stratal_slices)
        btn_row.addWidget(self.btn_stratal_clear)
        form.addLayout(btn_row, 5, 0, 1, 3)

        self._stratal_status = QLabel("尚未生成地层切片")
        self._stratal_status.setWordWrap(True)
        self._stratal_status.setStyleSheet(
            "color: %s; font-size: 11px;" % tokens.TEXT_SECONDARY
        )
        form.addWidget(self._stratal_status, 6, 0, 1, 3)
        form.addWidget(QLabel(""), 7, 0)  # spacer
        form.setRowStretch(7, 1)
        return tab

    def _pick_stratal_horizon(self, combo: QComboBox, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "Horizon (*.dat);;All files (*)"
        )
        if path:
            # Replace any previously chosen path; keep one entry.
            combo.clear()
            combo.addItem(path, path)

    def _on_generate_stratal_slices(self) -> None:
        """Generate stratal/proportional slices in a background worker and
        overlay them in the 3D view.

        Real-data path: parse the two chosen horizon .dat files against the
        loaded survey/volume. Demo path (checkbox or no volume/horizons): load a
        synthetic volume + horizons so the feature is visible even without SEGY.
        Computation runs off the UI thread (StratalWorker); only the renderer
        updates happen here (review finding #8).
        """
        if self._stratal_job.is_running:
            return
        renderer = getattr(self._joint_widget, "renderer", None) \
            if self._joint_widget is not None else None
        demo = self._stratal_demo_check.isChecked()
        fractions = self._stratal_fractions.currentData() or (0.25, 0.50, 0.75)

        if demo:
            # EXPLICIT demo path (checkbox checked): synthetic volume so the
            # feature is visible without SEGY; the status line marks it Demo.
            if renderer is None:
                self._stratal_status.setText("3D 视口尚未就绪，无法预览。")
                return
            self._stratal_status.setText("正在生成演示地层切片…")
            # Parentless on purpose: a parent would make moveToThread in
            # OwnedWorkerJob.start a silent no-op and the computation would
            # run on the GUI thread (review finding #8 regression, C17).
            worker = StratalWorker(
                demo=True, fractions=tuple(fractions)
            )
            self._stratal_job.start(
                worker,
                terminal_signals=(worker.terminal,),
                result_connections=(
                    (worker.completed, self._on_stratal_completed),
                    (worker.failed, self._on_stratal_failed),
                ),
            )
            return

        # Real-data path: no volume available and demo NOT requested → show the
        # unavailable state instead of silently injecting synthetic data
        # (honesty contract: synthetic output only on explicit demo request).
        if renderer is None or not getattr(renderer, "_loaded", False) \
                or renderer.volume_data() is None:
            self._stratal_status.setText(
                "未加载体数据：无法生成地层切片。"
                "可勾选“用合成演示体（无 SEGY 时预览）”查看演示效果。"
            )
            return

        # Real-data path.
        top_path = self._stratal_top_combo.currentData()
        bot_path = self._stratal_bot_combo.currentData()
        if not top_path or not bot_path:
            self._stratal_status.setText("请先选择顶部与底部 horizon 文件。")
            return
        vol = renderer.volume_data()
        scene = self._joint_host.scene
        self._stratal_status.setText("正在计算比例地层切片…")
        # Parentless on purpose: a parent would make moveToThread in
        # OwnedWorkerJob.start a silent no-op and the computation would
        # run on the GUI thread (review finding #8 regression, C17).
        worker = StratalWorker(
            demo=False,
            fractions=tuple(fractions),
            scene=scene,
            volume=vol,
            top_path=top_path,
            bottom_path=bot_path,
        )
        self._stratal_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_stratal_completed),
                (worker.failed, self._on_stratal_failed),
            ),
        )

    def _on_stratal_completed(self, result: dict) -> None:
        """Apply computed stratal surfaces to the renderer (UI thread)."""
        renderer = getattr(self._joint_widget, "renderer", None) \
            if self._joint_widget is not None else None
        if renderer is None:
            self._stratal_status.setText("3D 视口尚未就绪，无法预览。")
            return
        surfaces = result["surfaces"]
        labels = result["labels"]
        if result.get("demo"):
            renderer.load_volume(result["volume"])
        renderer.set_stratal_slices(
            surfaces,
            labels=labels,
            active=max(0, len(surfaces) // 2),
            opacity=0.8,
        )
        if result.get("demo"):
            self._stratal_status.setText(
                "已用合成演示体生成 %d 张比例切片（演示预览模式）。"
                % len(surfaces)
            )
            return
        snap = renderer.get_stratal_slices()
        self._stratal_status.setText(
            "已生成 %d 张比例地层切片（active=%s）。"
            % (len(snap), snap[0][0] if snap else "?")
        )

    def _on_stratal_failed(self, err: str) -> None:
        self._stratal_status.setText(str(err))

    def _on_clear_stratal_slices(self) -> None:
        renderer = getattr(self._joint_widget, "renderer", None) \
            if self._joint_widget is not None else None
        if renderer is not None:
            renderer.clear_stratal_slices()
        self._stratal_status.setText("已清除地层切片。")

    def _build_welltie_tab(self) -> QWidget:
        """Re-surface the existing well-tie controls under a labeled tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        hint = QLabel(
            "井震标定：Ricker 合成记录、互相关自动对齐（Auto-Tie）、时深偏移。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s; font-size: 11px;" % tokens.TEXT_SECONDARY)
        layout.addWidget(hint)
        # Reference the existing controls (built in the legacy right rail) so a
        # single source of truth drives both surfaces. The legacy rail stays
        # hidden; we show lightweight proxies that forward to the same handlers.
        row = QHBoxLayout()
        layout.addLayout(row)
        self._wtie_freq_proxy = QSlider(Qt.Horizontal)
        self._wtie_freq_proxy.setMinimum(self.slider_wavelet_freq.minimum())
        self._wtie_freq_proxy.setMaximum(self.slider_wavelet_freq.maximum())
        self._wtie_freq_proxy.setValue(self.slider_wavelet_freq.value())
        self._wtie_freq_proxy.valueChanged.connect(
            self.slider_wavelet_freq.setValue
        )
        self.slider_wavelet_freq.valueChanged.connect(
            self._wtie_freq_proxy.setValue
        )
        row.addWidget(QLabel("子波频率"))
        row.addWidget(self._wtie_freq_proxy)
        self._wtie_shift_proxy = QSlider(Qt.Horizontal)
        self._wtie_shift_proxy.setMinimum(self.slider_td_shift.minimum())
        self._wtie_shift_proxy.setMaximum(self.slider_td_shift.maximum())
        self._wtie_shift_proxy.setValue(self.slider_td_shift.value())
        self._wtie_shift_proxy.valueChanged.connect(
            self.slider_td_shift.setValue
        )
        self.slider_td_shift.valueChanged.connect(
            self._wtie_shift_proxy.setValue
        )
        row2 = QHBoxLayout()
        layout.addLayout(row2)
        row2.addWidget(QLabel("时深偏移"))
        row2.addWidget(self._wtie_shift_proxy)
        self._wtie_auto_proxy = QPushButton("自动互相关对齐 (Auto-Tie)")
        self._wtie_auto_proxy.clicked.connect(self.btn_auto_tie.click)
        row2.addWidget(self._wtie_auto_proxy)
        self._wtie_corr_label = self.label_correlation
        layout.addWidget(self._wtie_corr_label)
        layout.addStretch(1)
        return tab

    def _build_facies_tab(self) -> QWidget:
        """Depositional facies interpretation entry (RGB blend + crossplot)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        hint = QLabel(
            "沉积相解释：RGB 多属性混色、岩性交会图统计。"
            "（高级分析入口在「高级地震与井震综合分析」卡片中）"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s; font-size: 11px;" % tokens.TEXT_SECONDARY)
        layout.addWidget(hint)
        row = QHBoxLayout()
        layout.addLayout(row)
        self._facies_rgb_proxy = QPushButton("RGB 多属性混色")
        self._facies_rgb_proxy.setToolTip("混合多地震属性以辅助沉积相边界识别")
        self._facies_rgb_proxy.clicked.connect(self.btn_rgb_fusion.click)
        row.addWidget(self._facies_rgb_proxy)
        self._facies_crossplot_proxy = QPushButton("岩性交会图")
        self._facies_crossplot_proxy.clicked.connect(self.btn_crossplot.click)
        row.addWidget(self._facies_crossplot_proxy)
        layout.addStretch(1)
        return tab

    def _build_export_diag_tab(self) -> QWidget:
        """Numerical-simulation export + AI diagnostics under one tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, tokens.SPACE_1
        )
        hint = QLabel(
            "导出与诊断：FLAC3D / Abaqus 数值模拟网格导出，一致性诊断顾问。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: %s; font-size: 11px;" % tokens.TEXT_SECONDARY)
        layout.addWidget(hint)
        row = QHBoxLayout()
        layout.addLayout(row)
        self._diag_export_proxy = QPushButton("导出数值模拟模型")
        self._diag_export_proxy.clicked.connect(self.btn_export.click)
        row.addWidget(self._diag_export_proxy)
        self._diag_ai_proxy = QPushButton("开启一致性诊断")
        self._diag_ai_proxy.clicked.connect(self.btn_ai_advisor.click)
        row.addWidget(self._diag_ai_proxy)
        layout.addStretch(1)
        return tab

    def _restore_joint_slice_settings(self) -> None:
        from geoviz import OrthogonalSliceState, TimeSliceState

        state = (
            getattr(self._project, "joint_analysis", None)
            if self._project is not None
            else None
        )
        if state is None:
            restored = OrthogonalSliceState()
        else:
            restored = OrthogonalSliceState(
                inline_index=getattr(
                    state, "orthogonal_inline_index", None
                ),
                crossline_index=getattr(
                    state, "orthogonal_crossline_index", None
                ),
                time_slices=tuple(
                    TimeSliceState(
                        time_ms=float(item.time_ms),
                        visible=bool(item.visible),
                    )
                    for item in (
                        getattr(state, "time_slices", None) or []
                    )
                ),
                active_time_ms=getattr(
                    state, "active_time_slice_ms", None
                ),
                time_opacity=(
                    int(getattr(state, "time_slice_opacity", 80))
                    / 100.0
                ),
            )
        scene = self._joint_host.scene
        if scene is None:
            # Joint engine failed to construct (e.g. volume unavailable); the
            # deferred set_project binding must not raise here or it aborts
            # DeferredPageBindings.flush and drops sibling page bindings.
            return
        scene.restore_orthogonal_slice_state(restored)
        self._refresh_joint_slice_card()

    def _refresh_joint_slice_card(self) -> None:
        """Refresh controls from the scene-owned slice state."""
        scene = self._joint_host.scene
        if scene is None:
            return
        registration = scene.registration
        state = scene.orthogonal_slice_state
        ready = registration is not None
        time_domain = scene.vertical_domain.value == "time"

        for control in (
            self._joint_inline_slice,
            self._joint_crossline_slice,
            self._joint_time_selector,
            self._joint_active_time_editor,
            self._joint_active_time_visible,
            self._joint_new_time,
            self._joint_time_opacity,
        ):
            control.blockSignals(True)
        try:
            if registration is not None:
                self._joint_inline_slice.setRange(
                    0, max(registration.n_inline - 1, 0)
                )
                self._joint_crossline_slice.setRange(
                    0, max(registration.n_crossline - 1, 0)
                )
                self._joint_inline_slice.setValue(
                    int(state.inline_index or 0)
                )
                self._joint_crossline_slice.setValue(
                    int(state.crossline_index or 0)
                )
                survey = registration.survey
                t_min = float(survey.t0_ms)
                t_max = float(
                    survey.t0_ms
                    + max(survey.n_samples - 1, 0) * survey.dt_ms
                )
                self._joint_new_time.setRange(t_min, t_max)
                self._joint_new_time.setSingleStep(
                    max(float(survey.dt_ms), 0.001)
                )
                self._joint_active_time_editor.setRange(t_min, t_max)
                self._joint_active_time_editor.setSingleStep(
                    max(float(survey.dt_ms), 0.001)
                )
                if state.active_time_ms is not None:
                    self._joint_new_time.setValue(
                        float(state.active_time_ms)
                    )
            self._joint_time_selector.clear()
            active_index = -1
            active_slice = None
            for index, time_slice in enumerate(state.time_slices):
                self._joint_time_selector.addItem(
                    f"{time_slice.time_ms:g} ms",
                    float(time_slice.time_ms),
                )
                if (
                    state.active_time_ms is not None
                    and np.isclose(
                        time_slice.time_ms,
                        state.active_time_ms,
                        atol=1e-7,
                    )
                ):
                    active_index = index
                    active_slice = time_slice
            self._joint_time_selector.setCurrentIndex(active_index)
            if active_slice is not None:
                self._joint_active_time_editor.setValue(
                    float(active_slice.time_ms)
                )
                self._joint_active_time_visible.setChecked(
                    bool(active_slice.visible)
                )
            self._joint_time_opacity.setValue(
                int(round(state.time_opacity * 100))
            )
        finally:
            for control in (
                self._joint_inline_slice,
                self._joint_crossline_slice,
                self._joint_time_selector,
                self._joint_active_time_editor,
                self._joint_active_time_visible,
                self._joint_new_time,
                self._joint_time_opacity,
            ):
                control.blockSignals(False)

        self._joint_inline_slice.setEnabled(ready)
        self._joint_crossline_slice.setEnabled(ready)
        time_ready = ready and time_domain
        self._joint_time_selector.setEnabled(time_ready)
        self._joint_active_time_editor.setEnabled(time_ready)
        self._joint_active_time_visible.setEnabled(time_ready)
        self._joint_delete_time_slice.setEnabled(
            time_ready and len(state.time_slices) > 1
        )
        self._joint_new_time.setEnabled(time_ready)
        self._joint_time_opacity.setEnabled(time_ready)
        self._joint_add_time_slice.setEnabled(
            time_ready and len(state.time_slices) < 8
        )
        if not ready:
            note = "未加载"
        elif not time_domain:
            note = "Depth · Time 已隐藏"
        else:
            note = f"{len(state.time_slices)}/8"
        self._joint_time_domain_note.setText(note)

    def _sync_joint_slice_renderer(self) -> None:
        widget = self._joint_widget
        if widget is not None:
            sync = getattr(widget, "sync_orthogonal_slices", None)
            if callable(sync):
                sync()

    def _on_joint_inline_slice_changed(self, value: int) -> None:
        self._joint_host.scene.set_orthogonal_slice_indices(
            inline_index=int(value)
        )
        self._sync_joint_slice_renderer()

    def _on_joint_crossline_slice_changed(self, value: int) -> None:
        self._joint_host.scene.set_orthogonal_slice_indices(
            crossline_index=int(value)
        )
        self._sync_joint_slice_renderer()

    def _on_joint_add_time_slice(self) -> None:
        scene = self._joint_host.scene
        before = len(scene.orthogonal_slice_state.time_slices)
        try:
            snapped = scene.add_time_slice(self._joint_new_time.value())
        except ValueError as exc:
            self._on_joint_status(str(exc))
            return
        after = len(scene.orthogonal_slice_state.time_slices)
        self._on_joint_status(
            (
                f"已添加 Time 切片 {snapped:g} ms"
                if after > before
                else f"已激活已有 Time 切片 {snapped:g} ms"
            )
        )
        self._refresh_joint_slice_card()
        self._sync_joint_slice_renderer()

    def _on_joint_activate_time_slice(self, time_ms: float) -> None:
        self._joint_host.scene.set_active_time_slice(time_ms)
        self._refresh_joint_slice_card()
        self._sync_joint_slice_renderer()

    def _on_joint_time_selector_changed(self, index: int) -> None:
        time_ms = self._joint_time_selector.itemData(index)
        if time_ms is not None:
            self._on_joint_activate_time_slice(float(time_ms))

    def _on_joint_active_time_edited(self) -> None:
        current_time_ms = self._joint_time_selector.currentData()
        if current_time_ms is not None:
            self._on_joint_edit_time_slice(
                float(current_time_ms),
                self._joint_active_time_editor.value(),
            )

    def _on_joint_active_time_visibility_changed(
        self, visible: bool
    ) -> None:
        time_ms = self._joint_time_selector.currentData()
        if time_ms is not None:
            self._on_joint_time_slice_visibility(
                float(time_ms), visible
            )

    def _on_joint_delete_active_time_slice(self) -> None:
        time_ms = self._joint_time_selector.currentData()
        if time_ms is not None:
            self._on_joint_delete_time_slice(float(time_ms))

    def _on_joint_time_slice_visibility(
        self, time_ms: float, visible: bool
    ) -> None:
        self._joint_host.scene.set_time_slice_visible(time_ms, visible)
        self._sync_joint_slice_renderer()

    def _on_joint_edit_time_slice(
        self, current_time_ms: float, new_time_ms: float
    ) -> None:
        snapped = self._joint_host.scene.update_time_slice(
            current_time_ms, new_time_ms
        )
        self._on_joint_status(f"Time 切片已移动到 {snapped:g} ms")
        self._refresh_joint_slice_card()
        self._sync_joint_slice_renderer()

    def _on_joint_delete_time_slice(self, time_ms: float) -> None:
        if self._joint_host.scene.remove_time_slice(time_ms):
            self._on_joint_status(f"已删除 Time 切片 {time_ms:g} ms")
        self._refresh_joint_slice_card()
        self._sync_joint_slice_renderer()

    def _on_joint_time_opacity_changed(self, value: int) -> None:
        self._joint_host.scene.set_time_slice_opacity(value / 100.0)
        self._sync_joint_slice_renderer()

    def _restore_joint_display_settings(self) -> None:
        state = (
            getattr(self._project, "joint_analysis", None)
            if self._project is not None
            else None
        )
        seismic = getattr(
            state, "seismic_color_scale", "blue-white-red"
        )
        gr = getattr(state, "gr_color_scale", "viridis")
        width = int(getattr(state, "well_width_px", 5))
        controls = (
            self._joint_seismic_color,
            self._joint_gr_color,
            self._joint_well_width,
        )
        for control in controls:
            control.blockSignals(True)
        try:
            seismic_index = self._joint_seismic_color.findData(seismic)
            gr_index = self._joint_gr_color.findData(gr)
            self._joint_seismic_color.setCurrentIndex(
                max(seismic_index, 0)
            )
            self._joint_gr_color.setCurrentIndex(max(gr_index, 0))
            self._joint_well_width.setValue(
                max(2, min(10, width))
            )
        finally:
            for control in controls:
                control.blockSignals(False)
        self._apply_joint_display_settings()

    def _apply_joint_display_settings(self, *_args) -> None:
        scene = self._joint_host.scene
        if scene is None:
            return
        from geoviz import JointDisplaySettings

        settings = JointDisplaySettings(
            seismic_color_scale=str(
                self._joint_seismic_color.currentData()
                or "blue-white-red"
            ),
            gr_color_scale=str(
                self._joint_gr_color.currentData() or "viridis"
            ),
            well_width_px=self._joint_well_width.value(),
        )
        scene.set_display_settings(settings)
        if self._joint_widget is not None:
            self._joint_widget.set_scene(scene)
        profile = getattr(self, "_joint_profile", None)
        if profile is not None:
            profile.set_scene(scene)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._joint_loaded_once and self.isVisible():
            self._joint_loaded_once = True
            self._ensure_joint_widget()
            # Apply tree checks first; domain via preferred_domain so reload
            # does not force Time (code-review Spec fix).
            self._apply_joint_tree_checks_from_project()
            domain = "Time"
            if self._project is not None:
                state = getattr(self._project, "joint_analysis", None)
                domain = getattr(state, "vertical_domain", None) or "Time"
            if hasattr(self, "_joint_domain"):
                self._joint_domain.blockSignals(True)
                idx = self._joint_domain.findText(domain)
                if idx >= 0:
                    self._joint_domain.setCurrentIndex(idx)
                self._joint_domain.blockSignals(False)
            restoring_fence = False
            if self._project is not None:
                state = getattr(self._project, "joint_analysis", None)
                wells = list(getattr(state, "active_fence_wells", None) or [])
                restoring_fence = len(wells) >= 2
            self._joint_host.reload(
                preferred_domain=domain,
                auto_default_fence=not restoring_fence,
            )
            self._restore_joint_fence_from_project()
            self._update_domain_z_guard(domain)

    def collect_joint_analysis_state(self):
        """Snapshot joint UI into project model (no voxels) — #90."""
        from paleo_workbench.project.models import (
            JointAnalysisState,
            JointTimeSliceState,
        )

        checks: dict[str, bool] = {}
        root = self.model_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            if "井震联合" not in group.text(0):
                continue
            for j in range(group.childCount()):
                child = group.child(j)
                checks[child.text(0)] = child.checkState(0) == Qt.Checked
        domain = "Time"
        if hasattr(self, "_joint_domain"):
            domain = self._joint_domain.currentText() or "Time"
        wells: list[str] = []
        if hasattr(self, "_joint_well_a"):
            a = self._joint_well_a.currentData() or self._joint_well_a.currentText()
            b = self._joint_well_b.currentData() or self._joint_well_b.currentText()
            if a and b:
                wells = [str(a), str(b)]
        fence_name = None
        scene = self._joint_host.scene
        if scene is not None and getattr(scene, "fences", None):
            for f in scene.fences:
                if getattr(f, "id", None) == getattr(scene, "active_fence_id", None):
                    fence_name = getattr(f, "name", None) or str(f.id)
                    break
            if fence_name is None and scene.fences:
                fence_name = getattr(scene.fences[0], "name", None)
        paths = self._joint_host.paths
        hints: dict[str, str] = {}
        if paths is not None:
            if paths.segy:
                hints["segy"] = str(paths.segy)
            if paths.well_head:
                hints["well_head"] = str(paths.well_head)
            if paths.td_dir:
                hints["td_dir"] = str(paths.td_dir)
            if paths.tops:
                hints["tops"] = str(paths.tops)
            if paths.horizons:
                # Multi-horizon: pipe-separated absolute paths
                hints["horizons"] = "|".join(str(p) for p in paths.horizons if p)
        slice_state = self._joint_host.scene.orthogonal_slice_state
        return JointAnalysisState(
            tree_checks=checks,
            well_visibility={
                presentation.id: presentation.visible
                for presentation in (
                    scene.well_presentations() if scene is not None else []
                )
            },
            well_identity_asset_id=self._joint_host.well_identity_asset_id,
            well_identity_map=self._joint_host.well_identity_map,
            seismic_color_scale=str(
                self._joint_seismic_color.currentData()
                or "blue-white-red"
            ),
            gr_color_scale=str(
                self._joint_gr_color.currentData() or "viridis"
            ),
            well_width_px=self._joint_well_width.value(),
            orthogonal_inline_index=slice_state.inline_index,
            orthogonal_crossline_index=slice_state.crossline_index,
            time_slices=[
                JointTimeSliceState(
                    time_ms=item.time_ms,
                    visible=item.visible,
                )
                for item in slice_state.time_slices
            ],
            active_time_slice_ms=slice_state.active_time_ms,
            time_slice_opacity=int(
                round(slice_state.time_opacity * 100)
            ),
            vertical_domain=domain,
            active_fence_wells=wells,
            active_fence_name=fence_name,
            path_hints=hints,
        )

    def save_joint_analysis_to_project(self) -> None:
        if self._project is None:
            return
        self._project.joint_analysis = self.collect_joint_analysis_state()

    def _apply_joint_tree_checks_from_project(self) -> None:
        """Restore known geoviz check keys only; unknown keys are ignored (#121)."""
        if self._project is None:
            return
        state = getattr(self._project, "joint_analysis", None)
        if state is None:
            return
        checks = getattr(state, "tree_checks", None) or {}
        if not checks:
            return
        root = self.model_tree.invisibleRootItem()
        self.model_tree.blockSignals(True)
        try:
            for i in range(root.childCount()):
                group = root.child(i)
                if "井震联合" not in group.text(0):
                    continue
                for j in range(group.childCount()):
                    child = group.child(j)
                    name = child.text(0)
                    if name in checks:
                        child.setCheckState(
                            0, Qt.Checked if checks[name] else Qt.Unchecked
                        )
                    # else: unknown / stale keys in `checks` are ignored
        finally:
            self.model_tree.blockSignals(False)
        self._sync_joint_visibility_from_tree()

    def _restore_joint_fence_from_project(self) -> None:
        if self._project is None:
            return
        state = getattr(self._project, "joint_analysis", None)
        wells = list(getattr(state, "active_fence_wells", None) or [])
        if len(wells) >= 2:
            self._joint_host.add_well_to_well_fence(wells[0], wells[1])
            self._select_joint_wells(wells[0], wells[1])

    def _select_joint_wells(self, well_a: str, well_b: str) -> None:
        """Set toolbar combos to a saved well pair without resetting to index 0/1."""
        if not hasattr(self, "_joint_well_a"):
            return
        self._rebuild_joint_well_combos(well_a, well_b)

    def _ensure_joint_widget(self) -> None:
        """Mount WellSeismicJointWidget into joint 3D host (profile may sit in 2D host)."""
        if self._joint_widget is not None:
            return
        if not _opengl_widget_supported():
            # The joint renderer is a GLViewWidget; mounting it on a platform
            # without OpenGL segfaults as soon as Qt paints it. Degrade to the
            # placeholder instead of crashing the whole app.
            self._joint_3d_placeholder.setText(
                "3D 渲染不可用：当前平台不支持 OpenGL（offscreen）"
            )
            return
        if self._joint_host.scene is None:
            self._joint_3d_placeholder.setText(
                f"联合引擎不可用: {self._joint_host.engine_error or 'unknown'}"
            )
            return
        try:
            from geoviz import WellSeismicJointWidget

            self._joint_widget = WellSeismicJointWidget(self.joint_3d_host)
            # Public detach of fence profile into bottom strip
            take = getattr(self._joint_widget, "take_profile_widget", None)
            profile = take() if callable(take) else self._joint_widget.profile_widget
            layout_3d = self.joint_3d_host.layout()
            # Capture the placeholder locally before nulling the attribute: a
            # later exception must still be able to surface on it instead of
            # raising AttributeError on the now-None attribute.
            placeholder = self._joint_3d_placeholder
            if placeholder is not None:
                placeholder.setParent(None)
                self._joint_3d_placeholder = None
            layout_3d.addWidget(self._joint_widget, 1)
            if profile is not None:
                if self._joint_2d_placeholder is not None:
                    self._joint_2d_placeholder.setParent(None)
                    self._joint_2d_placeholder = None
                profile.setParent(self.joint_2d_host)
                self.joint_2d_host.layout().insertWidget(0, profile, 1)
                self._joint_profile = profile
                self._apply_profile_time_only_policy(profile)
            self._install_joint_well_pick()
        except Exception as exc:
            logger.exception("joint widget mount failed")
            if self._joint_3d_placeholder is not None:
                self._joint_3d_placeholder.setText(f"挂载失败: {exc}")

    def _install_joint_well_pick(self) -> None:
        """Install click/drag filter on joint 3D for pick + draw-snap (#123/#124)."""
        if self._joint_pick_filter is not None:
            return
        if self._joint_widget is None:
            return
        renderer = getattr(self._joint_widget, "renderer", None)
        if renderer is None:
            return
        view = getattr(renderer, "_view", None)
        target = view if view is not None else renderer
        page = self

        class _PickFilter(QObject):
            def eventFilter(self, obj, event):  # noqa: N802
                et = event.type()
                if et == QEvent.Type.MouseButtonPress:
                    if event.button() == Qt.MouseButton.LeftButton:
                        pos = event.position() if hasattr(event, "position") else event.pos()
                        sx, sy = float(pos.x()), float(pos.y())
                        page._joint_pick_press = (sx, sy)
                        if page._well_pick.mode == "draw":
                            return page._on_joint_3d_draw_press(sx, sy, target)
                elif et == QEvent.Type.MouseButtonRelease:
                    if event.button() != Qt.MouseButton.LeftButton:
                        return False
                    press = page._joint_pick_press
                    page._joint_pick_press = None
                    pos = event.position() if hasattr(event, "position") else event.pos()
                    sx, sy = float(pos.x()), float(pos.y())
                    if page._well_pick.mode == "draw":
                        return page._on_joint_3d_draw_release(sx, sy, target)
                    if press is None:
                        return False
                    dx, dy = sx - press[0], sy - press[1]
                    if dx * dx + dy * dy > 25:  # drag → leave to orbit camera
                        return False
                    handled = page._on_joint_3d_click(sx, sy, target)
                    return bool(handled)
                elif et == QEvent.Type.KeyPress:
                    if event.key() == Qt.Key.Key_Escape:
                        msg = page._well_pick.on_escape()
                        if msg:
                            page._on_joint_status(msg)
                            return True
                return False

        filt = _PickFilter(self)
        self._joint_pick_filter = filt
        target.installEventFilter(filt)
        # Also filter on renderer widget for keyboard
        if target is not renderer:
            renderer.installEventFilter(filt)
        try:
            target.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        except Exception:
            pass

    def _on_joint_pick_mode_changed(self, _index: int = 0) -> None:
        if not hasattr(self, "_joint_pick_mode"):
            return
        mode = self._joint_pick_mode.currentData()
        if mode is None:
            mode = "pick" if self._joint_pick_mode.currentIndex() == 0 else "draw"
        msg = self._well_pick.set_mode(str(mode))
        if msg:
            self._on_joint_status(msg)

    def _on_joint_delete_active_fence(self) -> None:
        self._joint_host.remove_active_fence()

    def _on_joint_3d_click(self, sx: float, sy: float, view_widget) -> bool:
        """Hit-test wells; two-click builds fence via host. Returns True if consumed."""
        name = self._hit_test_well_at(sx, sy, view_widget)
        if name is None:
            if self._well_pick.half_select is not None:
                self._on_joint_status(self._well_pick.on_blank_click())
                return True
            return False
        self._handle_joint_well_pick(name)
        return True

    def _on_joint_3d_draw_press(self, sx: float, sy: float, view_widget) -> bool:
        """Start drag-line from well head/traj; consume event when started."""
        name = self._hit_test_well_at(sx, sy, view_widget, head_only=False)
        msg = self._well_pick.on_draw_press(name)
        if msg:
            self._on_joint_status(msg)
        return self._well_pick.draw_from is not None

    def _on_joint_3d_draw_release(self, sx: float, sy: float, view_widget) -> bool:
        if self._well_pick.draw_from is None and self._well_pick.mode == "draw":
            return False
        # Prefer well-head snap with larger radius on release
        name = self._hit_test_well_at(
            sx, sy, view_widget, head_only=True, head_radius_px=28.0
        )
        if name is None:
            name = self._hit_test_well_at(sx, sy, view_widget, head_radius_px=20.0)
        status, pair = self._well_pick.on_draw_release(name)
        if status:
            self._on_joint_status(status)
        if pair is not None:
            a, b = pair
            self._joint_host.add_well_to_well_fence(a, b)
            self._select_joint_wells(a, b)
        return True

    def _hit_test_well_at(
        self,
        sx: float,
        sy: float,
        view_widget,
        *,
        head_only: bool = False,
        head_radius_px: float = 16.0,
        traj_radius_px: float = 10.0,
    ) -> str | None:
        scene = self._joint_host.scene
        if scene is None:
            return None
        try:
            trajs = scene.well_trajectories(visible_only=True)
        except Exception:
            return None
        if not trajs:
            return None
        w = float(getattr(view_widget, "width", lambda: 0)() or 0)
        h = float(getattr(view_widget, "height", lambda: 0)() or 0)
        if w <= 0 or h <= 0:
            return None
        try:
            vm = view_widget.viewMatrix()
            pm = view_widget.projectionMatrix()
        except Exception:
            return None

        def w2r(x, y, z):
            return scene.world_to_render_xyz(float(x), float(y), float(z))

        geoms = build_well_screen_geoms(
            trajs,
            world_to_render=w2r,
            view_matrix=vm,
            projection_matrix=pm,
            width=w,
            height=h,
        )
        return pick_well_name(
            sx,
            sy,
            geoms,
            head_radius_px=head_radius_px,
            traj_radius_px=traj_radius_px,
            head_only=head_only,
        )

    def _handle_joint_well_pick(self, name: str) -> None:
        """Apply two-click pick; create fence through host when pair completes."""
        status, pair = self._well_pick.on_well_click(name)
        if status:
            self._on_joint_status(status)
        # Announce the freshly picked well name for cross-page sync.
        if name:
            self.well_selected.emit(name)
        if pair is None:
            return
        a, b = pair
        self._joint_host.add_well_to_well_fence(a, b)
        self._select_joint_wells(a, b)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            msg = self._well_pick.on_escape()
            if msg:
                self._on_joint_status(msg)
                event.accept()
                return
        super().keyPressEvent(event)

    def _apply_profile_time_only_policy(self, profile) -> None:
        """Force 2D fence extract on Time even if scene domain is Depth (#122)."""
        set_dom = getattr(profile, "set_extract_domain", None)
        if not callable(set_dom):
            return
        try:
            from geoviz import VerticalDomain

            set_dom(VerticalDomain.TIME)
        except Exception:
            logger.debug("profile Time-only policy unavailable", exc_info=True)

    def _sync_joint_2d_time_chip(self, domain: str | None = None) -> None:
        """Surface 2D Time-only vs 3D Depth in the bottom strip header."""
        chip = getattr(self, "_joint_2d_time_chip", None)
        if chip is None:
            return
        if domain is None and hasattr(self, "_joint_domain"):
            domain = self._joint_domain.currentText()
        domain = domain or "Time"
        if str(domain).lower().startswith("depth"):
            chip.setText("2D: Time-only · Depth 仅 3D")
            chip.setStyleSheet(
                "QLabel#Joint2DTimeChip {"
                " color: #c2410c; background: #fff7ed; border: 1px solid #fed7aa;"
                " border-radius: 999px; padding: 2px 8px; font-size: 11px; }"
            )
        else:
            chip.setText("2D: Time")
            chip.setStyleSheet(
                "QLabel#Joint2DTimeChip {"
                " color: %s; background: %s; border: 1px solid %s; border-radius: 999px;"
                " padding: 2px 8px; font-size: 11px; }"
                % (tokens.PRIMARY, tokens.BG_SEARCH, tokens.BORDER)
            )

    def _on_joint_status(self, text: str) -> None:
        self._joint_status.setText(text)

    def _on_joint_scene_updated(self) -> None:
        self._apply_joint_display_settings()
        self._ensure_joint_widget()
        if self._joint_widget is not None and self._joint_host.scene is not None:
            self._joint_widget.set_scene(self._joint_host.scene)
            # Profile may have been detached into bottom host
            profile = getattr(self, "_joint_profile", None)
            if profile is not None and hasattr(profile, "set_scene"):
                self._apply_profile_time_only_policy(profile)
                profile.set_scene(self._joint_host.scene)
        self._refresh_joint_well_tree()
        self._fill_joint_well_combos()
        self._sync_joint_visibility_from_tree()
        self._refresh_joint_slice_card()
        warning = self._joint_host.scene.slice_state_warning
        if warning and warning not in self._joint_status.text():
            self._joint_status.setText(
                (self._joint_status.text() + " · " + warning).strip(" ·")
            )
        if hasattr(self, "_joint_domain"):
            self._sync_joint_2d_time_chip(self._joint_domain.currentText())

    def _fill_joint_well_combos(self) -> None:
        if not hasattr(self, "_joint_well_a"):
            return
        # Prefer current selection or project-saved pair over "first two wells"
        prev_a = self._joint_well_a.currentData() or self._joint_well_a.currentText()
        prev_b = self._joint_well_b.currentData() or self._joint_well_b.currentText()
        if self._project is not None:
            state = getattr(self._project, "joint_analysis", None)
            saved = list(getattr(state, "active_fence_wells", None) or [])
            if len(saved) >= 2:
                prev_a, prev_b = saved[0], saved[1]
        self._rebuild_joint_well_combos(str(prev_a), str(prev_b))

    def _rebuild_joint_well_combos(
        self, preferred_a: str, preferred_b: str
    ) -> None:
        """Rebuild both selectors while retaining stable JointWellId choices."""
        options = self._joint_well_options()
        self._joint_well_a.blockSignals(True)
        self._joint_well_b.blockSignals(True)
        self._joint_well_a.clear()
        self._joint_well_b.clear()
        for well_id, display_name in options:
            self._joint_well_a.addItem(display_name, well_id)
            self._joint_well_b.addItem(display_name, well_id)
        ia = self._joint_well_a.findData(preferred_a) if preferred_a else -1
        ib = self._joint_well_b.findData(preferred_b) if preferred_b else -1
        if ia >= 0:
            self._joint_well_a.setCurrentIndex(ia)
        if ib >= 0:
            self._joint_well_b.setCurrentIndex(ib)
        elif len(options) >= 2:
            self._joint_well_b.setCurrentIndex(1)
        self._joint_well_a.blockSignals(False)
        self._joint_well_b.blockSignals(False)

    def _joint_well_options(self) -> list[tuple[str, str]]:
        """Return ``(JointWellId, display label)`` pairs for toolbar controls."""
        scene = self._joint_host.scene
        presentations = scene.well_presentations() if scene is not None else []
        if presentations:
            return [
                (presentation.id, presentation.display_name)
                for presentation in presentations
            ]
        return [
            (str(well_id), str(well_id))
            for well_id in self._joint_host.well_names()
        ]

    def _on_joint_domain_changed(self, text: str) -> None:
        # 3D / scene domain follows toolbar; 2D profile stays Time (#122)
        self._joint_host.set_vertical_domain(text)
        self._update_domain_z_guard(text)
        self._sync_joint_2d_time_chip(text)
        self._refresh_joint_slice_card()
        self._sync_joint_slice_renderer()
        profile = getattr(self, "_joint_profile", None)
        if profile is not None:
            self._apply_profile_time_only_policy(profile)
            if hasattr(profile, "refresh"):
                profile.refresh()
            elif hasattr(profile, "set_scene") and self._joint_host.scene is not None:
                profile.set_scene(self._joint_host.scene)

    def _on_joint_fence(self) -> None:
        if not hasattr(self, "_joint_well_a"):
            return
        self._joint_host.add_well_to_well_fence(
            str(self._joint_well_a.currentData() or self._joint_well_a.currentText()),
            str(self._joint_well_b.currentData() or self._joint_well_b.currentText()),
        )

    def _update_domain_z_guard(self, domain: str) -> None:
        """Warn / soft-hide model volume when joint domain is Time (#97)."""
        is_time = not str(domain).lower().startswith("depth")
        for item in list(getattr(self, "active_items", []) or []):
            name = type(item).__name__
            if "Volume" in name or "volume" in name.lower():
                try:
                    item.setVisible(not is_time)
                except Exception:
                    pass
        if hasattr(self, "_joint_status") and is_time:
            msg = self._joint_status.text() or ""
            note = "竖直域=Time：已弱化深度网格体（Z 语义可能不一致）"
            if note not in msg:
                self._joint_status.setText((msg + " · " + note).strip(" ·"))
        self.gl_widget.update()

    def _align_joint_camera(self) -> None:
        """G1: no modeling camera to copy — apply default joint preset."""
        self._apply_joint_camera_preset(_CAMERA_PERSPECTIVE)

    def _on_joint_add_from_project(self) -> None:
        """Re-resolve hybrid assets (tree add entry point) (#97)."""
        domain = "Time"
        if hasattr(self, "_joint_domain"):
            domain = self._joint_domain.currentText() or "Time"
        self._joint_host.reload(preferred_domain=domain, auto_default_fence=False)
        self._joint_status.setText(
            (self._joint_status.text() or "") + " · 已从工程/数据重新解析联合资产"
        )

    # ------------------------------------------------------------------ #
    # Modeling
    # ------------------------------------------------------------------ #

    def _on_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        logger.info("Setting 3D Volume Item opacity to %s", opacity)
        self.gl_widget.update()

    def _run_modeling(self) -> None:
        if self._modeling_job.is_running:
            return

        self.btn_run.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        density = self.combo_density.currentText()
        # algorithm is a constant label — the synthetic demo volume does not
        # implement 克里金/SGS/IDW interpolation (the dead selector was removed).
        algo = "synthetic_demo"

        worker = GeologicalModelingWorker(density, algo, demo=True)
        worker.progress.connect(self.progress_bar.setValue)

        self._modeling_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_modeling_completed),
                (worker.failed, self._on_modeling_failed),
            ),
            target=density,
        )

    def _on_modeling_completed(self, result: dict) -> None:
        self.bh_raw_data = result["bh_raw"]
        self.faults_raw_data = result["faults_raw"]

        # Honest demo marking (P2): synthetic output is badged in the UI and
        # the modeling action is recorded as a catalog DataRun with an
        # explicit synthetic source — never implied to be real data.
        is_demo = bool(result.get("demo", True))
        if is_demo:
            self.demo_source_label.setText("合成演示数据 (Demo)")
        self._register_modeling_run(result, is_demo=is_demo)

        # Clear existing active GL elements
        for item in self.active_items:
            try:
                self.gl_widget.removeItem(item)
            except Exception:
                pass
        self.active_items.clear()
        self.mesh_items_map.clear()

        # Clear well-seismic overlay items
        self._clear_well_seismic_overlays()

        # 1. Add Volume Item
        vol_data = result["volume_data"]
        self.vol_item = ClippedGLVolumeItem(data=vol_data)
        w, h, d = vol_data.shape
        self.vol_item.translate(-w / 2, -h / 2, -d / 2)
        self.gl_widget.addItem(self.vol_item)
        self.active_items.append(self.vol_item)

        # 2. Add Boreholes
        for bh in result["boreholes"]:
            mesh = ClippedGLMeshItem(vertexes=bh["v"], faces=bh["f"], faceColors=bh["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)

            name = bh["name"]
            if name not in self.mesh_items_map:
                self.mesh_items_map[name] = []
            self.mesh_items_map[name].append(mesh)

        # 3. Add Tunnels
        for tn in result["tunnels"]:
            mesh = ClippedGLMeshItem(vertexes=tn["v"], faces=tn["f"], faceColors=tn["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)
            self.mesh_items_map[tn["name"]] = [mesh]

        # 4. Add Faults
        for flt in result["faults"]:
            mesh = ClippedGLMeshItem(vertexes=flt["v"], faces=flt["f"], faceColors=flt["c"], smooth=True)
            self.gl_widget.addItem(mesh)
            self.active_items.append(mesh)
            self.mesh_items_map[flt["name"]] = [mesh]

        # 5. Generate well-seismic tie 3D overlays
        self._generate_well_curve_overlays()
        self._generate_seismic_slice_overlay()

        # Sync visibility checkboxes
        self._sync_visibility_from_tree()
        # Initialize GPU clipping
        self._update_clipping()

        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.btn_ai_advisor.setEnabled(True)

        logger.info("3D geological modeling successfully updated in viewport.")

    def _modeling_input_version_ids(self, catalog) -> list[str]:
        """Version ids of the seismic / well data the joint scene is built
        from — the honest lineage inputs for the modeling run (empty when the
        demo scene has no project data loaded)."""
        if self._project is None:
            return []
        paths = self._joint_host.paths
        if paths is None:
            return []
        wanted: list[str] = []
        if paths.segy is not None:
            wanted.append(str(paths.segy))
        if paths.well_head is not None:
            wanted.append(str(paths.well_head))
        wanted.extend(str(las) for las in paths.las_files or [])
        if not wanted:
            return []
        try:
            from paleo_workbench.catalog.lifecycle import resource_ids_for_paths

            project_path = getattr(
                getattr(catalog, "service", None), "project_path", None
            )
            resource_ids = resource_ids_for_paths(
                getattr(self._project, "resources", None) or [],
                wanted,
                project_path=project_path,
            )
        except Exception:
            return []
        version_ids: list[str] = []
        for resource_id in resource_ids:
            try:
                ref = catalog.resolve_legacy_resource(resource_id)
            except Exception:
                ref = None
            if ref is not None and ref.version_id not in version_ids:
                version_ids.append(ref.version_id)
        return version_ids

    def _register_modeling_run(self, result: dict, *, is_demo: bool) -> None:
        """Registration seam (P2): record the modeling action as a DataRun.

        The synthetic demo output is in-memory (no payload file yet), so the
        run carries the honest ``source``/``demo`` marking with no version. A
        real-data worker (P3 structural split) passes ``output_path`` so the
        modeled result is also registered as a DERIVED DataVersion. Catalog
        failures never block rendering.
        """
        try:
            from paleo_workbench.catalog import get_catalog

            catalog = get_catalog()
            if catalog is None:
                return
            from paleo_workbench.catalog.lifecycle import register_modeling_run

            run, _version = register_modeling_run(
                name="三维地质建模（合成演示）" if is_demo else "三维地质建模",
                source="synthetic/demo" if is_demo else "real_data",
                demo=is_demo,
                parameters={
                    "density": self.combo_density.currentText(),
                    "algorithm": result.get("algorithm", "synthetic_demo"),
                    "source": "synthetic/demo" if is_demo else "real_data",
                },
                input_version_ids=self._modeling_input_version_ids(catalog),
                catalog=catalog,
            )
            if run is not None:
                # Remember the run's declared inputs so the mesh export below
                # can carry real source lineage (E7).
                self._last_modeling_run_inputs = list(run.input_version_ids or [])
        except Exception:  # noqa: BLE001 — provenance must never block 3D render
            logger.exception("register_modeling_run failed (best-effort)")

    def _on_modeling_failed(self, err: str) -> None:
        self.btn_run.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self, "建模失败", f"三维建模失败: {err}")

    # ------------------------------------------------------------------ #
    # Well-Seismic Tie 3D Overlays
    # ------------------------------------------------------------------ #

    def _clear_well_seismic_overlays(self) -> None:
        """Remove all well-curve and synthetic-trace 3D items from the viewport."""
        for item in self._well_curve_items + self._synthetic_items + self._seismic_slice_items:
            try:
                self.gl_widget.removeItem(item)
            except Exception:
                pass
        self._well_curve_items.clear()
        self._synthetic_items.clear()
        self._seismic_slice_items.clear()

    def _generate_well_curve_overlays(self) -> None:
        """Generate 3D GR log curves and synthetic seismogram traces for all boreholes.

        Pure computation lives in :func:`paleo_workbench.viz.geomodel.analysis.generate_well_curve_overlays`;
        this method only wires the returned data into GL items.
        """
        freq = float(self.slider_wavelet_freq.value())
        td_shift = float(self.slider_td_shift.value())

        for overlay in analysis.generate_well_curve_overlays(self.bh_raw_data, freq, td_shift):
            # GR log offset sideways off the trajectory
            line_item = gl.GLLinePlotItem(
                pos=overlay["curve_pts"], color=(0.2, 1.0, 0.4, 0.9), width=2.0, antialias=True
            )
            self.gl_widget.addItem(line_item)
            self._well_curve_items.append(line_item)

            # Register in mesh_items_map for tree visibility toggle
            key = "井眼旁显测井曲线 (3D GR Logs)"
            if key not in self.mesh_items_map:
                self.mesh_items_map[key] = []
            self.mesh_items_map[key].append(line_item)

            # Synthetic seismogram trace (offset opposite to the GR curve)
            if overlay["syn_curve_pts"] is not None:
                syn_item = gl.GLLinePlotItem(
                    pos=overlay["syn_curve_pts"], color=(1.0, 0.4, 0.2, 0.9), width=2.0, antialias=True
                )
                self.gl_widget.addItem(syn_item)
                self._synthetic_items.append(syn_item)

                syn_key = "合成地震记录叠加 (Synthetic Seismograms)"
                if syn_key not in self.mesh_items_map:
                    self.mesh_items_map[syn_key] = []
                self.mesh_items_map[syn_key].append(syn_item)

    def _generate_seismic_slice_overlay(self) -> None:
        """Generate a synthetic horizontal seismic amplitude slice in the 3D viewport.

        Geometry comes from :func:`paleo_workbench.viz.geomodel.analysis.generate_seismic_slice_overlay`.
        """
        verts, faces, colors = analysis.generate_seismic_slice_overlay()

        slice_item = ClippedGLMeshItem(vertexes=verts, faces=faces, faceColors=colors, smooth=False)
        self.gl_widget.addItem(slice_item)
        self._seismic_slice_items.append(slice_item)
        self.active_items.append(slice_item)

        key = "地震剖面三维切片 (Seismic Slices)"
        self.mesh_items_map[key] = [slice_item]

    # ------------------------------------------------------------------ #
    # Visibility & Clipping
    # ------------------------------------------------------------------ #

    def _sync_visibility_from_tree(self) -> None:
        """Apply model tree checked status to mesh/volume rendering visibilities."""
        root = self.model_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent = root.child(i)
            for j in range(parent.childCount()):
                item = parent.child(j)
                name = item.text(0)
                visible = (item.checkState(0) == Qt.Checked)

                if name in ["LST 顶底面", "TST 顶底面"]:
                    if hasattr(self, "vol_item") and self.vol_item is not None:
                        self.vol_item.setVisible(visible)
                else:
                    gl_items = self.mesh_items_map.get(name, [])
                    for gl_item in gl_items:
                        gl_item.setVisible(visible)
        self.gl_widget.update()

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return

        wells_parent = getattr(self, "_joint_wells_tree_item", None)
        well_id = item.data(0, Qt.ItemDataRole.UserRole)
        if item is wells_parent:
            visible = item.checkState(0) != Qt.Unchecked
            self.model_tree.blockSignals(True)
            try:
                for index in range(item.childCount()):
                    child = item.child(index)
                    child.setCheckState(
                        0, Qt.Checked if visible else Qt.Unchecked
                    )
                    child_id = child.data(0, Qt.ItemDataRole.UserRole)
                    if child_id is not None and self._joint_host.scene is not None:
                        self._joint_host.scene.set_well_visibility(
                            str(child_id), visible
                        )
            finally:
                self.model_tree.blockSignals(False)
            if not visible:
                self._well_pick.clear_half("隐藏全部井 — 已取消半选")
        elif well_id is not None and item.parent() is wells_parent:
            visible = item.checkState(0) == Qt.Checked
            if self._joint_host.scene is not None:
                self._joint_host.scene.set_well_visibility(str(well_id), visible)
            if not visible and str(well_id) in {
                self._well_pick.half_select,
                self._well_pick.draw_from,
            }:
                self._well_pick.clear_half("隐藏已选井 — 已取消半选")
            parent_state = self._joint_well_parent_state()
            if parent_state is not None:
                self.model_tree.blockSignals(True)
                try:
                    wells_parent.setCheckState(0, parent_state)
                finally:
                    self.model_tree.blockSignals(False)
        else:
            # Block signals to prevent recursive checking logic
            self.model_tree.blockSignals(True)
            try:
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, item.checkState(0))
            finally:
                self.model_tree.blockSignals(False)

        self._sync_visibility_from_tree()
        self._sync_joint_visibility_from_tree()

    def _tree_item_checked(self, name: str) -> bool:
        root = self.model_tree.invisibleRootItem()
        for i in range(root.childCount()):
            group = root.child(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.text(0) == name:
                    return child.checkState(0) == Qt.Checked
        return True

    def _sync_joint_visibility_from_tree(self) -> None:
        """Apply geoviz joint tree checks to embedded joint chrome + layers."""
        show_3d = self._tree_item_checked("井震 3D 视口")
        show_2d = self._tree_item_checked("井震 2D 剖面条")
        show_vol = self._tree_item_checked("地震预览体 (geoviz)")
        wells_parent = getattr(self, "_joint_wells_tree_item", None)
        show_wells = (
            wells_parent is None
            or wells_parent.checkState(0) != Qt.Unchecked
        )
        show_fence = self._tree_item_checked("井间剖面 fence (geoviz)")
        show_stratal = self._tree_item_checked("地层切片体 (geoviz)")
        # Sync stratal-plane visibility on the joint renderer.
        renderer = getattr(self._joint_widget, "renderer", None) \
            if self._joint_widget is not None else None
        if renderer is not None and getattr(renderer, "_stratal_surfaces", None):
            renderer.set_stratal_visible(bool(show_stratal))
        if hasattr(self, "joint_3d_host"):
            self.joint_3d_host.setVisible(show_3d or show_vol)
        if hasattr(self, "_joint_2d_panel"):
            self._joint_2d_panel.setVisible(show_2d)
        if hasattr(self, "joint_2d_host"):
            self.joint_2d_host.setVisible(show_2d)
        if self._joint_widget is not None:
            self._joint_widget.setVisible(show_3d or show_vol)
            set_vis = getattr(self._joint_widget, "set_layer_visibility", None)
            if callable(set_vis):
                set_vis(wells=show_wells, fences=show_fence, volume=show_vol)
            profile = getattr(self, "_joint_profile", None)
            if profile is not None:
                profile.setVisible(show_2d and show_fence)
                refresh = getattr(profile, "refresh", None)
                if callable(refresh):
                    refresh()

    def _update_clipping(self) -> None:
        """Legacy modeling-item clip (G1: clip card hidden; not wired to joint)."""
        def val_to_coord(val: int) -> float:
            return -80.0 + (val / 100.0) * 160.0

        x_enabled = self.chk_clip_x.isChecked()
        x_coord = val_to_coord(self.slide_clip_x.value())
        x_dir = 1.0 if self.combo_clip_x_dir.currentIndex() == 0 else -1.0

        y_enabled = self.chk_clip_y.isChecked()
        y_coord = val_to_coord(self.slide_clip_y.value())
        y_dir = 1.0 if self.combo_clip_y_dir.currentIndex() == 0 else -1.0

        z_enabled = self.chk_clip_z.isChecked()
        z_coord = val_to_coord(self.slide_clip_z.value())
        z_dir = 1.0 if self.combo_clip_z_dir.currentIndex() == 0 else -1.0

        for item in self.active_items:
            if hasattr(item, "set_clipping"):
                item.set_clipping('x', x_enabled, x_coord, x_dir)
                item.set_clipping('y', y_enabled, y_coord, y_dir)
                item.set_clipping('z', z_enabled, z_coord, z_dir)
        if self.gl_widget is not None:
            self.gl_widget.update()

    def _apply_clip_to_joint_slices(self) -> None:
        """G1 unwired (#110). Kept for possible G2 geomodel stack."""
        return

    # ------------------------------------------------------------------ #
    # Export
    # ------------------------------------------------------------------ #

    def _export_mesh(self) -> None:
        if self._export_job.is_running:
            return

        sim_type = self.combo_export_type.currentText()
        if "FLAC3D" in sim_type:
            mode = "flac3d"
            suffix = "f3grid"
            filter_str = "FLAC3D grid files (*.f3grid)"
        else:
            mode = "abaqus"
            suffix = "inp"
            filter_str = "Abaqus input files (*.inp)"

        filepath, _ = QFileDialog.getSaveFileName(
            self, "保存数值模拟网格模型", f"geological_numerical_model.{suffix}", filter_str
        )
        if not filepath:
            return

        self.btn_export.setEnabled(False)

        grid_spec = GridSpec(
            nx=self.spin_nx.value(), ny=self.spin_ny.value(), nz=self.spin_nz.value(),
            dx=self.spin_dx.value(), dy=self.spin_dy.value(), dz=self.spin_dz.value(),
        )

        worker = ExportWorker(filepath, mode, grid_spec)
        self._export_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_export_completed),
                (worker.failed, self._on_export_failed),
            ),
            target=filepath
        )

    def _on_export_completed(self, filepath: str) -> None:
        self.btn_export.setEnabled(True)
        self._register_mesh_export(filepath)
        QMessageBox.information(self, "导出成功", f"数值模拟网格模型已成功导出:\n{filepath}")

    def _on_export_failed(self, err: str) -> None:
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "导出失败", f"网格模型导出失败:\n{err}")

    def _register_mesh_export(self, filepath: str) -> None:
        """Best-effort OUTPUT DataVersion registration for FLAC3D/Abaqus mesh
        exports. The OUTPUT carries the current modeling run's declared input
        versions as source lineage (empty for the synthetic demo grid, which
        honestly has no source data); no catalog → no-op."""
        if self._project is None:
            return
        try:
            from paleo_workbench.catalog.lifecycle import register_export_output

            sim_type = self.combo_export_type.currentText()
            fmt = "f3grid" if "FLAC3D" in sim_type else "inp"
            register_export_output(
                name="数值模拟网格模型 export",
                output_path=str(filepath),
                fmt=fmt,
                source_version_ids=list(self._last_modeling_run_inputs),
                linked_id="geological_modeling_3d",
                catalog=None,
            )
        except Exception:
            # Provenance is best-effort; never break the export flow.
            pass

    # ------------------------------------------------------------------ #
    # AI Advisor
    # ------------------------------------------------------------------ #

    def _run_ai_advisor(self) -> None:
        if self._advisor_job.is_running:
            return

        self.btn_ai_advisor.setEnabled(False)
        worker = AdvisorWorker(self.bh_raw_data, self.faults_raw_data)

        self._advisor_job.start(
            worker,
            terminal_signals=(worker.terminal,),
            result_connections=(
                (worker.completed, self._on_advisor_completed),
                (worker.failed, self._on_advisor_failed),
            )
        )

    def _on_advisor_completed(self, bh_report: dict, fault_report: dict) -> None:
        self.btn_ai_advisor.setEnabled(True)
        dialog = AICheckAdvisorDialog(bh_report, fault_report, self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_advisor_failed(self, err: str) -> None:
        self.btn_ai_advisor.setEnabled(True)
        QMessageBox.warning(self, "诊断分析失败", f"一致性复核诊断遇到错误:\n{err}")

    # ------------------------------------------------------------------ #
    # Well-Seismic Tie Calibration
    # ------------------------------------------------------------------ #

    def _on_tie_params_changed(self) -> None:
        """Re-generate well-seismic overlays when frequency or T-D shift changes."""
        freq = self.slider_wavelet_freq.value()
        shift = self.slider_td_shift.value()
        logger.info("Well-Seismic calibration updated: freq=%dHz, shift=%dms", freq, shift)

        if self.bh_raw_data:
            self._clear_well_seismic_overlays()
            self._generate_well_curve_overlays()
            self._generate_seismic_slice_overlay()
            self._sync_visibility_from_tree()
        self.gl_widget.update()

    def _run_auto_tie(self) -> None:
        """Run real cross-correlation auto-tie via ``geoviz.correlate_synthetic_to_trace``.

        The computation lives in
        :func:`paleo_workbench.viz.geomodel.analysis.run_auto_tie`; this method
        only applies the result to the calibration controls.
        """
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载数据。")
            return

        freq = float(self.slider_wavelet_freq.value())
        result = analysis.run_auto_tie(self.bh_raw_data, freq)

        if result is None:
            QMessageBox.warning(self, "标定失败", "无法生成合成地震记录，请检查数据。")
            return

        shift_samples = result["shift_samples"]
        cc = result["cc"]

        self.slider_td_shift.setValue(shift_samples)
        self.label_correlation.setText(f"互相关系数 (Cross-Correlation CC): {cc:.3f}")

        QMessageBox.information(
            self, "自动标定完成",
            f"已完成互相关自动井震标定对齐。\n"
            f"最优时深度转换时移量: {shift_samples:+d} samples\n"
            f"最大互相关系数 CC: {cc:.3f}"
        )

    # ------------------------------------------------------------------ #
    # Advanced Multi-Attribute & Crossplot Analysis
    # ------------------------------------------------------------------ #

    def _generate_rgb_fusion_slice(self) -> None:
        """Generate RGB frequency attribute fusion horizontal slice in 3D viewport.

        Geometry comes from
        :func:`paleo_workbench.viz.geomodel.analysis.generate_rgb_fusion_slice`.
        """
        verts, faces, face_colors = analysis.generate_rgb_fusion_slice()

        rgb_item = ClippedGLMeshItem(vertexes=verts, faces=faces, faceColors=face_colors, smooth=True)
        self.gl_widget.addItem(rgb_item)
        self.active_items.append(rgb_item)

        key = "RGB 属性融合三维切片 (RGB Fusion Slice)"
        self.mesh_items_map[key] = [rgb_item]
        self._sync_visibility_from_tree()
        self.gl_widget.update()

        QMessageBox.information(self, "RGB 融合切片", "RGB 三频率（15Hz/35Hz/55Hz）属性融合三维切片已成功生成并叠加至三维视口！")

    def _generate_cross_well_fence(self) -> None:
        """Generate 3D curtain/fence slice connecting all loaded boreholes.

        Mesh computation lives in
        :func:`paleo_workbench.viz.geomodel.analysis.generate_cross_well_fence`.
        """
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载钻孔数据。")
            return

        mesh = analysis.generate_cross_well_fence(self.bh_raw_data, nz_samples=25)
        if mesh is None:
            return
        verts, faces, colors = mesh

        fence_item = ClippedGLMeshItem(vertexes=verts, faces=faces, faceColors=colors, smooth=True)
        self.gl_widget.addItem(fence_item)
        self.active_items.append(fence_item)

        key = "井震连井三维剖面幕墙 (Cross-Well Seismic Fence)"
        self.mesh_items_map[key] = [fence_item]
        self._sync_visibility_from_tree()
        self.gl_widget.update()

        QMessageBox.information(self, "连井剖面幕墙", f"已成功生成连接 {len(self.bh_raw_data)} 口钻孔的三维剖面幕墙！")

    def _run_lithology_crossplot(self) -> None:
        """Run geoviz.analyze_lithology_crossplot and show the crossplot statistics dialog.

        The sampling + statistics live in
        :func:`paleo_workbench.viz.geomodel.analysis.run_lithology_crossplot`.
        """
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载数据。")
            return

        analysis_result = analysis.run_lithology_crossplot(self.bh_raw_data)

        dialog = LithologyCrossplotDialog(analysis_result, self)
        dialog.exec()

    # ------------------------------------------------------------------ #
    # Cleanup
    # ------------------------------------------------------------------ #

    def __del__(self) -> None:
        # Prevent thread cleanup race conditions on widget disposal
        try:
            self._modeling_job.shutdown()
        except Exception:
            pass
        try:
            self._export_job.shutdown()
        except Exception:
            pass
        try:
            self._advisor_job.shutdown()
        except Exception:
            pass
        try:
            self._stratal_job.shutdown()
        except Exception:
            pass
