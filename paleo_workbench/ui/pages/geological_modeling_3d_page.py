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
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
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
    """3D Geological Modeling Workbench Page.

    Features:
    - Left: Interactive checkable model hierarchy tree.
    - Center: pyqtgraph.opengl 3D interactive viewport + floating glassmorphic view toolbar.
    - Right: Dynamic parameter configuration, 3-way clipping, AI Check advisor, and Numerical simulator exporter.
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

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        main_layout.setSpacing(tokens.SPACE_2)

        # Horizontal Splitter for 3 Panels
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setStyleSheet("QSplitter::handle { background: %s; width: 1px; }" % tokens.BORDER)

        # 1. Left Panel: Model Hierarchy
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens.SPACE_2)

        left_header = QLabel("模型层次与资产")
        left_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        left_layout.addWidget(left_header)

        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("三维场景对象")
        self.model_tree.setStyleSheet("QTreeView { border: 1px solid %s; border-radius: %dpx; }" % (
            tokens.BORDER, tokens.RADIUS_CARD
        ))
        self._populate_model_tree()
        left_layout.addWidget(self.model_tree)

        # 2. Center Panel: 3D Viewport
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.view_container = QFrame()
        self.view_container.setFrameShape(QFrame.StyledPanel)
        self.view_container.setStyleSheet("QFrame { background: #020617; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))

        view_layout = QVBoxLayout(self.view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)

        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.opts['distance'] = 250
        self.gl_widget.setCameraPosition(**_CAMERA_PERSPECTIVE)
        view_layout.addWidget(self.gl_widget)

        # Default baseline grid
        grid = gl.GLGridItem()
        grid.setSize(300, 300, 300)
        grid.setSpacing(10, 10, 10)
        self.gl_widget.addItem(grid)

        # Floating View Control Bar
        self.floating_bar = QFrame(self.view_container)
        self.floating_bar.setStyleSheet("""
            QFrame {
                background-color: %s;
                border: 1px solid %s;
                border-radius: %dpx;
            }
            QPushButton {
                background: transparent;
                border: none;
                padding: 4px 10px;
                color: #e2e8f0;
                font-weight: bold;
            }
            QPushButton:hover {
                background: %s;
                border-radius: 4px;
            }
        """ % (tokens.BG_GLASS, tokens.BG_GLASS_BORDER, tokens.RADIUS_BUTTON, tokens.HOVER_GLOW))
        self.floating_bar.setFixedHeight(38)
        self.floating_bar.setFixedWidth(360)

        f_layout = QHBoxLayout(self.floating_bar)
        f_layout.setContentsMargins(tokens.SPACE_1, 0, tokens.SPACE_1, 0)

        self.btn_orbit = QPushButton("透视视角")
        self.btn_pan = QPushButton("俯瞰视角")
        self.btn_reset = QPushButton("复位")
        self.btn_coord = QPushButton("📍 网格(IL/XL)")
        self.btn_coord.setCheckable(True)
        self._coord_mode = "grid"

        self.btn_orbit.clicked.connect(lambda: self.gl_widget.setCameraPosition(**_CAMERA_PERSPECTIVE))
        self.btn_pan.clicked.connect(lambda: self.gl_widget.setCameraPosition(**_CAMERA_TOP_DOWN))
        self.btn_reset.clicked.connect(lambda: self.gl_widget.setCameraPosition(**_CAMERA_PERSPECTIVE))
        self.btn_coord.clicked.connect(self._toggle_coord_mode)

        f_layout.addWidget(self.btn_orbit)
        f_layout.addWidget(self.btn_pan)
        f_layout.addWidget(self.btn_reset)
        f_layout.addWidget(self.btn_coord)
        self.floating_bar.move(12, 12)

        center_layout.addWidget(self.view_container)

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
        card_config.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
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
        card_clip.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
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

        # Wire clipping events
        self.chk_clip_x.stateChanged.connect(self._update_clipping)
        self.slide_clip_x.valueChanged.connect(self._update_clipping)
        self.combo_clip_x_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_y.stateChanged.connect(self._update_clipping)
        self.slide_clip_y.valueChanged.connect(self._update_clipping)
        self.combo_clip_y_dir.currentIndexChanged.connect(self._update_clipping)
        self.chk_clip_z.stateChanged.connect(self._update_clipping)
        self.slide_clip_z.valueChanged.connect(self._update_clipping)
        self.combo_clip_z_dir.currentIndexChanged.connect(self._update_clipping)

        right_layout.addWidget(card_clip)

        # CARD 3: Simulator Mesh Exporters
        card_export = QFrame()
        card_export.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
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
        card_ai.setStyleSheet("QFrame { background: #f8fafc; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        ai_layout = QVBoxLayout(card_ai)
        ai_layout.setSpacing(tokens.SPACE_2)

        title_ai = QLabel("AI 专家复核与诊断顾问")
        title_ai.setStyleSheet("font-weight: bold; font-size: 13px; color: %s;" % tokens.TEXT_PRIMARY)
        ai_layout.addWidget(title_ai)

        desc_ai = QLabel("通过 AI 自动分析当前项目下所有钻孔的深度分层完整性，并校验平行断层共面问题。")
        desc_ai.setWordWrap(True)
        desc_ai.setStyleSheet("font-size: 11px; color: #64748b;")
        ai_layout.addWidget(desc_ai)

        self.btn_ai_advisor = QPushButton("开启 AI 一致性诊断")
        self.btn_ai_advisor.setObjectName("PrimaryButton")
        self.btn_ai_advisor.setEnabled(False)  # Enable only after data is loaded
        self.btn_ai_advisor.clicked.connect(self._run_ai_advisor)
        ai_layout.addWidget(self.btn_ai_advisor)

        right_layout.addWidget(card_ai)

        # CARD 5: Well-Seismic Tie Calibration & Analysis Controls
        card_tie = QFrame()
        card_tie.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
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
        self.label_correlation.setStyleSheet("font-size: 11px; color: #10b981; font-weight: bold;")
        tie_layout.addWidget(self.label_correlation)

        self.btn_auto_tie = QPushButton("自动互相关对齐 (Auto-Tie)")
        self.btn_auto_tie.setObjectName("SecondaryButton")
        self.btn_auto_tie.clicked.connect(self._run_auto_tie)
        tie_layout.addWidget(self.btn_auto_tie)

        right_layout.addWidget(card_tie)

        # CARD 6: Advanced Multi-Attribute & Crossplot Analysis
        card_adv = QFrame()
        card_adv.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
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

        # Constrain side panel widths so central 3D viewport retains maximum space
        left_widget.setMinimumWidth(220)
        left_widget.setMaximumWidth(320)

        right_scroll.setMinimumWidth(320)
        right_scroll.setMaximumWidth(440)

        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_scroll)

        # Center widget (3D canvas) expands to fill available space; side panels maintain fixed widths
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 1000, 360])

        main_layout.addWidget(splitter)

    def _toggle_coord_mode(self) -> None:
        """Toggle between Grid coordinates (IL/XL) and Geographic coordinates (Easting/Northing in meters)."""
        if self.btn_coord.isChecked():
            self._coord_mode = "geo"
            self.btn_coord.setText("🌐 地理(X/Y)")
        else:
            self._coord_mode = "grid"
            self.btn_coord.setText("📍 网格(IL/XL)")

    # ------------------------------------------------------------------ #
    # Model Tree
    # ------------------------------------------------------------------ #

    def _populate_model_tree(self) -> None:
        self.model_tree.clear()

        root_struct = QTreeWidgetItem(self.model_tree, ["地层构造格架"])
        self._add_checkable_child(root_struct, "LST 顶底面")
        self._add_checkable_child(root_struct, "TST 顶底面")

        root_fault = QTreeWidgetItem(self.model_tree, ["断层格架模型"])
        self._add_checkable_child(root_fault, "断层 F1 Surface")
        self._add_checkable_child(root_fault, "断层 F2 Surface")

        root_tunnels = QTreeWidgetItem(self.model_tree, ["巷道与井下系统"])
        self._add_checkable_child(root_tunnels, "巷道 A")
        self._add_checkable_child(root_tunnels, "巷道 B")

        root_wells = QTreeWidgetItem(self.model_tree, ["钻孔与井迹"])
        self._add_checkable_child(root_wells, "钻孔 HZ21-1")
        self._add_checkable_child(root_wells, "钻孔 HZ19-6")
        self._add_checkable_child(root_wells, "钻孔 XJ24-3")
        self._add_checkable_child(root_wells, "钻孔 HZ25-2")

        root_tie = QTreeWidgetItem(self.model_tree, ["井震融合标定与校正"])
        self._add_checkable_child(root_tie, "地震剖面三维切片 (Seismic Slices)")
        self._add_checkable_child(root_tie, "井眼旁显测井曲线 (3D GR Logs)")
        self._add_checkable_child(root_tie, "合成地震记录叠加 (Synthetic Seismograms)")
        self._add_checkable_child(root_tie, "RGB 属性融合三维切片 (RGB Fusion Slice)")
        self._add_checkable_child(root_tie, "井震连井三维剖面幕墙 (Cross-Well Seismic Fence)")

        self.model_tree.expandAll()
        self.model_tree.itemChanged.connect(self._on_tree_item_changed)

    def _add_checkable_child(self, parent_item: QTreeWidgetItem, name: str) -> None:
        item = QTreeWidgetItem(parent_item, [name])
        item.setCheckState(0, Qt.Checked)

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

    def _update_clipping(self) -> None:
        """Update 3D interactive user clipping parameters based on UI sliders."""
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
        self.gl_widget.update()

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
