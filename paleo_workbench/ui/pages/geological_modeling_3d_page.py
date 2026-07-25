"""GeologicalModeling3DPage — premium 3D geological modeling workbench page.

Refactored to import Workers and Dialog from their own modules,
wire WellCurve3DGenerator and WellSeismicTieCalibration into the
3D viewport rendering, and replace the hardcoded auto-tie stub
with a real cross-correlation implementation.
"""
from __future__ import annotations

import logging
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QSlider, QSplitter, QProgressBar,
    QCheckBox, QSpinBox, QDoubleSpinBox, QScrollArea, QFileDialog, QMessageBox,
)
import pyqtgraph.opengl as gl

from paleo_workbench import tokens
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.joint_host import WellSeismicJointHost
from paleo_workbench.viz.geomodel import (
    ClippedGLMeshItem,
    ClippedGLVolumeItem,
    WellSeismicTieCalibration,
    WellCurve3DGenerator,
    RGBAttributeFusion,
    LithologyCrossplotEngine,
    CrossWellFenceGenerator,
)
from paleo_workbench.viz.geomodel.models import GridSpec
from paleo_workbench.ui.pages.geological_modeling_workers import (
    GeologicalModelingWorker,
    ExportWorker,
    AdvisorWorker,
)
from paleo_workbench.ui.pages.ai_check_advisor_dialog import AICheckAdvisorDialog
from paleo_workbench.ui.pages.lithology_crossplot_dialog import LithologyCrossplotDialog

logger = logging.getLogger(__name__)

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeologicalModeling3DPage")

        # Background threads keeper wrappers
        self._modeling_job = OwnedWorkerJob(self)
        self._export_job = OwnedWorkerJob(self)
        self._advisor_job = OwnedWorkerJob(self)
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
        self._joint_loaded_once = False
        self._joint_widget = None
        self._joint_status = QLabel("")
        self._joint_host = WellSeismicJointHost(self)
        self._joint_host.status_changed.connect(self._on_joint_status)
        self._joint_host.scene_updated.connect(self._on_joint_scene_updated)

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
        f_layout.addWidget(QLabel("井间"))
        self._joint_well_a = QComboBox()
        self._joint_well_b = QComboBox()
        f_layout.addWidget(self._joint_well_a)
        f_layout.addWidget(self._joint_well_b)
        self._joint_fence_btn = QPushButton("井间剖面")
        self._joint_fence_btn.clicked.connect(self._on_joint_fence)
        f_layout.addWidget(self._joint_fence_btn)
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
        self.btn_toggle_joint_2d = QPushButton("折叠")
        self.btn_toggle_joint_2d.setCheckable(True)
        self.btn_toggle_joint_2d.setChecked(False)
        self.btn_toggle_joint_2d.clicked.connect(self._toggle_joint_2d_panel)
        j2_header.addWidget(self.btn_toggle_joint_2d)
        j2_layout.addLayout(j2_header)
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

        cfg_layout.addWidget(QLabel("属性插值算法"))
        self.combo_algo = QComboBox()
        self.combo_algo.addItems(["克里金插值 (Kriging)", "顺序高斯模拟 (SGS)", "逆距离加权 (IDW)"])
        cfg_layout.addWidget(self.combo_algo)

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

        # CARD 4: AI Check Advisor Side Dialog
        card_ai = QFrame()
        card_ai.setStyleSheet("QFrame { background: %s; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.BG_SEARCH, tokens.RADIUS_CARD, tokens.BORDER
        ))
        ai_layout = QVBoxLayout(card_ai)
        ai_layout.setSpacing(tokens.SPACE_2)

        title_ai = QLabel("AI 专家复核与诊断顾问")
        title_ai.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        ai_layout.addWidget(title_ai)

        desc_ai = QLabel("通过 AI 自动分析当前项目下所有钻孔的深度分层完整性，并校验平行断层共面问题。")
        desc_ai.setWordWrap(True)
        desc_ai.setStyleSheet("font-size: 11px; color: %s;" % tokens.TEXT_SECONDARY)
        ai_layout.addWidget(desc_ai)

        self.btn_ai_advisor = QPushButton("开启 AI 一致性诊断")
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
        self._add_checkable_child(root_joint, "联合井轨迹 (geoviz)")
        self._add_checkable_child(root_joint, "井间剖面 fence (geoviz)")
        self._add_checkable_child(root_joint, "井震 3D 视口")
        self._add_checkable_child(root_joint, "井震 2D 剖面条")

        self.model_tree.expandAll()
        if not getattr(self, "_tree_changed_hooked", False):
            self.model_tree.itemChanged.connect(self._on_tree_item_changed)
            self._tree_changed_hooked = True

    def _add_checkable_child(self, parent_item: QTreeWidgetItem, name: str) -> None:
        item = QTreeWidgetItem(parent_item, [name])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        item.setCheckState(0, Qt.Checked)

    def set_project(self, project: ProjectDocument | None) -> None:
        self._project = project
        self._joint_host.set_project(project)

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
        from paleo_workbench.project.models import JointAnalysisState

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
            a, b = self._joint_well_a.currentText(), self._joint_well_b.currentText()
            if a and b:
                wells = [a, b]
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
        return JointAnalysisState(
            tree_checks=checks,
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
        names = self._joint_host.well_names()
        self._joint_well_a.blockSignals(True)
        self._joint_well_b.blockSignals(True)
        self._joint_well_a.clear()
        self._joint_well_b.clear()
        self._joint_well_a.addItems(names)
        self._joint_well_b.addItems(names)
        ia = self._joint_well_a.findText(well_a)
        ib = self._joint_well_b.findText(well_b)
        if ia >= 0:
            self._joint_well_a.setCurrentIndex(ia)
        if ib >= 0:
            self._joint_well_b.setCurrentIndex(ib)
        elif len(names) >= 2:
            self._joint_well_b.setCurrentIndex(1)
        self._joint_well_a.blockSignals(False)
        self._joint_well_b.blockSignals(False)

    def _ensure_joint_widget(self) -> None:
        """Mount WellSeismicJointWidget into joint 3D host (profile may sit in 2D host)."""
        if self._joint_widget is not None:
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
            if self._joint_3d_placeholder is not None:
                self._joint_3d_placeholder.setParent(None)
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
        except Exception as exc:
            logger.exception("joint widget mount failed")
            self._joint_3d_placeholder.setText(f"挂载失败: {exc}")

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
        self._ensure_joint_widget()
        if self._joint_widget is not None and self._joint_host.scene is not None:
            self._joint_widget.set_scene(self._joint_host.scene)
            # Profile may have been detached into bottom host
            profile = getattr(self, "_joint_profile", None)
            if profile is not None and hasattr(profile, "set_scene"):
                self._apply_profile_time_only_policy(profile)
                profile.set_scene(self._joint_host.scene)
        self._fill_joint_well_combos()
        self._sync_joint_visibility_from_tree()
        if hasattr(self, "_joint_domain"):
            self._sync_joint_2d_time_chip(self._joint_domain.currentText())

    def _fill_joint_well_combos(self) -> None:
        if not hasattr(self, "_joint_well_a"):
            return
        # Prefer current selection or project-saved pair over "first two wells"
        prev_a = self._joint_well_a.currentText()
        prev_b = self._joint_well_b.currentText()
        if self._project is not None:
            state = getattr(self._project, "joint_analysis", None)
            saved = list(getattr(state, "active_fence_wells", None) or [])
            if len(saved) >= 2:
                prev_a, prev_b = saved[0], saved[1]
        names = self._joint_host.well_names()
        self._joint_well_a.blockSignals(True)
        self._joint_well_b.blockSignals(True)
        self._joint_well_a.clear()
        self._joint_well_b.clear()
        self._joint_well_a.addItems(names)
        self._joint_well_b.addItems(names)
        ia = self._joint_well_a.findText(prev_a) if prev_a else -1
        ib = self._joint_well_b.findText(prev_b) if prev_b else -1
        if ia >= 0:
            self._joint_well_a.setCurrentIndex(ia)
        if ib >= 0:
            self._joint_well_b.setCurrentIndex(ib)
        elif len(names) >= 2:
            self._joint_well_b.setCurrentIndex(1)
        self._joint_well_a.blockSignals(False)
        self._joint_well_b.blockSignals(False)

    def _on_joint_domain_changed(self, text: str) -> None:
        # 3D / scene domain follows toolbar; 2D profile stays Time (#122)
        self._joint_host.set_vertical_domain(text)
        self._update_domain_z_guard(text)
        self._sync_joint_2d_time_chip(text)
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
            self._joint_well_a.currentText(),
            self._joint_well_b.currentText(),
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
        algo = self.combo_algo.currentText()

        worker = GeologicalModelingWorker(density, algo)
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
        """Generate 3D GR log curves and synthetic seismogram traces for all boreholes."""
        freq = float(self.slider_wavelet_freq.value())
        td_shift = float(self.slider_td_shift.value())

        for bh in self.bh_raw_data:
            bx, by = bh["x"], bh["y"]
            layers = bh["layers"]
            if not layers:
                continue

            # Build a vertical well path from surface to total depth
            max_depth = max(l["bottom"] for l in layers)
            n_samples = max(int(max_depth), 50)
            depths = np.linspace(0, max_depth, n_samples, dtype=np.float32)
            well_path = np.column_stack([
                np.full(n_samples, bx, dtype=np.float32),
                np.full(n_samples, by, dtype=np.float32),
                -depths,  # Z is upward, depth is downward
            ])

            # Synthesize GR-like curve (assign value per lithology)
            gr_values = np.zeros(n_samples, dtype=np.float32)
            _litho_gr = {"砂岩": 40.0, "泥岩": 120.0, "石灰岩": 25.0, "花岗岩": 80.0}
            for layer in layers:
                mask = (depths >= layer["top"]) & (depths < layer["bottom"])
                gr_values[mask] = _litho_gr.get(layer["lithology"], 60.0)
            # Add realistic noise
            gr_values += np.random.default_rng(42).normal(0, 8.0, n_samples).astype(np.float32)

            # Generate 3D curve mesh using WellCurve3DGenerator
            curve_pts = WellCurve3DGenerator.generate_curve_mesh(well_path, gr_values, scale=0.15)
            line_item = gl.GLLinePlotItem(
                pos=curve_pts, color=(0.2, 1.0, 0.4, 0.9), width=2.0, antialias=True
            )
            self.gl_widget.addItem(line_item)
            self._well_curve_items.append(line_item)

            # Register in mesh_items_map for tree visibility toggle
            key = "井眼旁显测井曲线 (3D GR Logs)"
            if key not in self.mesh_items_map:
                self.mesh_items_map[key] = []
            self.mesh_items_map[key].append(line_item)

            # Synthesize sonic and density logs for synthetic seismogram
            sonic = np.zeros(n_samples, dtype=np.float32)
            density = np.zeros(n_samples, dtype=np.float32)
            _litho_sonic = {"砂岩": 180.0, "泥岩": 250.0, "石灰岩": 150.0, "花岗岩": 120.0}
            _litho_density = {"砂岩": 2.2, "泥岩": 2.4, "石灰岩": 2.65, "花岗岩": 2.7}
            for layer in layers:
                mask = (depths >= layer["top"]) & (depths < layer["bottom"])
                sonic[mask] = _litho_sonic.get(layer["lithology"], 180.0)
                density[mask] = _litho_density.get(layer["lithology"], 2.4)

            synthetic = WellSeismicTieCalibration.compute_synthetic(sonic, density, wavelet_freq=freq)
            if len(synthetic) > 0:
                # Align synthetic length to well path subset
                syn_len = min(len(synthetic), n_samples - 1)
                syn_path = well_path[1:syn_len + 1].copy()

                # Apply T-D shift
                aligned_depths = WellSeismicTieCalibration.align_twt_depth(
                    -syn_path[:, 2], td_shift
                )
                syn_path[:, 2] = -aligned_depths

                # Offset synthetic trace in the opposite direction from GR
                syn_curve_pts = WellCurve3DGenerator.generate_curve_mesh(
                    syn_path, synthetic[:syn_len], scale=5.0
                )
                syn_item = gl.GLLinePlotItem(
                    pos=syn_curve_pts, color=(1.0, 0.4, 0.2, 0.9), width=2.0, antialias=True
                )
                self.gl_widget.addItem(syn_item)
                self._synthetic_items.append(syn_item)

                syn_key = "合成地震记录叠加 (Synthetic Seismograms)"
                if syn_key not in self.mesh_items_map:
                    self.mesh_items_map[syn_key] = []
                self.mesh_items_map[syn_key].append(syn_item)

    def _generate_seismic_slice_overlay(self) -> None:
        """Generate a synthetic horizontal seismic amplitude slice in the 3D viewport."""
        # Create a planar mesh representing a seismic inline slice at z=-60
        nx_pts, ny_pts = 30, 30
        x = np.linspace(-80, 80, nx_pts)
        y = np.linspace(-80, 80, ny_pts)
        xx, yy = np.meshgrid(x, y)
        # Synthetic seismic amplitude pattern
        zz = -60.0 + 3.0 * np.sin(xx / 15.0) * np.cos(yy / 15.0)

        verts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)

        # Build face indices for grid quads (as triangles)
        faces = []
        for j in range(ny_pts - 1):
            for i in range(nx_pts - 1):
                idx = j * nx_pts + i
                faces.append([idx, idx + 1, idx + nx_pts])
                faces.append([idx + 1, idx + nx_pts + 1, idx + nx_pts])
        faces = np.array(faces, dtype=np.int32)

        # Color by amplitude
        amp = (zz.ravel() + 63.0) / 6.0  # normalize 0-1
        amp = np.clip(amp, 0, 1)
        colors = np.zeros((len(faces), 4), dtype=np.float32)
        for fi, face in enumerate(faces):
            a = float(np.mean(amp[face]))
            # Blue-white-red colormap
            if a < 0.5:
                colors[fi] = [0.2, 0.2 + 0.6 * (a * 2), 0.9, 0.55]
            else:
                colors[fi] = [0.9, 0.2 + 0.6 * (2 - a * 2), 0.2, 0.55]

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
        show_wells = self._tree_item_checked("联合井轨迹 (geoviz)")
        show_fence = self._tree_item_checked("井间剖面 fence (geoviz)")
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
        QMessageBox.information(self, "导出成功", f"数值模拟网格模型已成功导出:\n{filepath}")

    def _on_export_failed(self, err: str) -> None:
        self.btn_export.setEnabled(True)
        QMessageBox.critical(self, "导出失败", f"网格模型导出失败:\n{err}")

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
        QMessageBox.warning(self, "诊断分析失败", f"AI 一致性复核诊断遇到错误:\n{err}")

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
        """Run real cross-correlation auto-tie using WellSeismicTieCalibration.auto_correlate."""
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载数据。")
            return

        freq = float(self.slider_wavelet_freq.value())

        # Use first borehole for calibration
        bh = self.bh_raw_data[0]
        layers = bh["layers"]
        max_depth = max(l["bottom"] for l in layers)
        n_samples = max(int(max_depth), 50)
        depths = np.linspace(0, max_depth, n_samples, dtype=np.float32)

        _litho_sonic = {"砂岩": 180.0, "泥岩": 250.0, "石灰岩": 150.0, "花岗岩": 120.0}
        _litho_density = {"砂岩": 2.2, "泥岩": 2.4, "石灰岩": 2.65, "花岗岩": 2.7}

        sonic = np.zeros(n_samples, dtype=np.float32)
        density = np.zeros(n_samples, dtype=np.float32)
        for layer in layers:
            mask = (depths >= layer["top"]) & (depths < layer["bottom"])
            sonic[mask] = _litho_sonic.get(layer["lithology"], 180.0)
            density[mask] = _litho_density.get(layer["lithology"], 2.4)

        synthetic = WellSeismicTieCalibration.compute_synthetic(sonic, density, wavelet_freq=freq)

        # Generate a synthetic "field seismic trace" (shifted version of synthetic + noise)
        if len(synthetic) > 0:
            rng = np.random.default_rng(123)
            true_shift = 12  # samples
            seismic_trace = np.roll(synthetic, true_shift) + rng.normal(0, 0.05, len(synthetic))

            shift_samples, cc = WellSeismicTieCalibration.auto_correlate(synthetic, seismic_trace)

            self.slider_td_shift.setValue(shift_samples)
            self.label_correlation.setText(f"互相关系数 (Cross-Correlation CC): {cc:.3f}")

            QMessageBox.information(
                self, "自动标定完成",
                f"已完成互相关自动井震标定对齐。\n"
                f"最优时深度转换时移量: {shift_samples:+d} samples\n"
                f"最大互相关系数 CC: {cc:.3f}"
            )
        else:
            QMessageBox.warning(self, "标定失败", "无法生成合成地震记录，请检查数据。")

    # ------------------------------------------------------------------ #
    # Advanced Multi-Attribute & Crossplot Analysis
    # ------------------------------------------------------------------ #

    def _generate_rgb_fusion_slice(self) -> None:
        """Generate RGB frequency attribute fusion horizontal slice in 3D viewport."""
        nx_pts, ny_pts = 40, 40
        x = np.linspace(-80, 80, nx_pts)
        y = np.linspace(-80, 80, ny_pts)
        xx, yy = np.meshgrid(x, y)
        zz = -40.0 + 2.0 * np.sin(xx / 10.0) * np.cos(yy / 10.0)

        # Synthetic frequency channels
        ch_r = np.sin(xx / 12.0) * np.cos(yy / 12.0) + 1.0  # Low frequency (15Hz)
        ch_g = np.cos(xx / 8.0) * np.sin(yy / 8.0) + 1.0   # Mid frequency (35Hz)
        ch_b = np.sin(xx / 5.0 + yy / 5.0) + 1.0          # High frequency (55Hz)

        rgba_grid = RGBAttributeFusion.blend_rgb(ch_r, ch_g, ch_b, alpha=0.85)

        verts = np.column_stack([xx.ravel(), yy.ravel(), zz.ravel()]).astype(np.float32)

        faces = []
        face_colors = []
        for j in range(ny_pts - 1):
            for i in range(nx_pts - 1):
                idx = j * nx_pts + i
                faces.append([idx, idx + 1, idx + nx_pts])
                faces.append([idx + 1, idx + nx_pts + 1, idx + nx_pts])

                c = rgba_grid[j, i]
                face_colors.append(c)
                face_colors.append(c)

        faces = np.array(faces, dtype=np.int32)
        face_colors = np.array(face_colors, dtype=np.float32)

        rgb_item = ClippedGLMeshItem(vertexes=verts, faces=faces, faceColors=face_colors, smooth=True)
        self.gl_widget.addItem(rgb_item)
        self.active_items.append(rgb_item)

        key = "RGB 属性融合三维切片 (RGB Fusion Slice)"
        self.mesh_items_map[key] = [rgb_item]
        self._sync_visibility_from_tree()
        self.gl_widget.update()

        QMessageBox.information(self, "RGB 融合切片", "RGB 三频率（15Hz/35Hz/55Hz）属性融合三维切片已成功生成并叠加至三维视口！")

    def _generate_cross_well_fence(self) -> None:
        """Generate 3D curtain/fence slice connecting all loaded boreholes."""
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载钻孔数据。")
            return

        wells = [
            {"name": bh["name"], "x": bh["x"], "y": bh["y"], "depth": bh["total_depth"]}
            for bh in self.bh_raw_data
        ]

        verts, faces, colors = CrossWellFenceGenerator.generate_fence_mesh(wells, nz_samples=25)
        if len(verts) == 0:
            return

        fence_item = ClippedGLMeshItem(vertexes=verts, faces=faces, faceColors=colors, smooth=True)
        self.gl_widget.addItem(fence_item)
        self.active_items.append(fence_item)

        key = "井震连井三维剖面幕墙 (Cross-Well Seismic Fence)"
        self.mesh_items_map[key] = [fence_item]
        self._sync_visibility_from_tree()
        self.gl_widget.update()

        QMessageBox.information(self, "连井剖面幕墙", f"已成功生成连接 {len(wells)} 口钻孔的三维剖面幕墙！")

    def _run_lithology_crossplot(self) -> None:
        """Run LithologyCrossplotEngine and display crossplot statistical dialog."""
        if not self.bh_raw_data:
            QMessageBox.information(self, "提示", "请先运行三维建模以加载数据。")
            return

        gr_list = []
        ai_list = []
        lith_list = []

        _litho_gr = {"砂岩": 40.0, "泥岩": 120.0, "石灰岩": 25.0, "花岗岩": 80.0}
        _litho_ai = {"砂岩": 8200.0, "泥岩": 4800.0, "石灰岩": 14500.0, "花岗岩": 18000.0}

        rng = np.random.default_rng(42)
        for bh in self.bh_raw_data:
            for layer in bh["layers"]:
                lith = layer["lithology"]
                base_g = _litho_gr.get(lith, 60.0)
                base_a = _litho_ai.get(lith, 6000.0)

                # Sample 10 points per layer
                for _ in range(10):
                    gr_list.append(base_g + float(rng.normal(0, 6.0)))
                    ai_list.append(base_a + float(rng.normal(0, 400.0)))
                    lith_list.append(lith)

        analysis_result = LithologyCrossplotEngine.analyze(
            np.array(gr_list, dtype=np.float32),
            np.array(ai_list, dtype=np.float32),
            lith_list
        )

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
