"""GeologicalModeling3DPage — premium 3D geological modeling workbench page."""
from __future__ import annotations

import logging
import numpy as np
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QComboBox, QSlider, QSplitter, QProgressBar,
)
import pyqtgraph.opengl as gl

from paleo_workbench import tokens
from geoviz_seismic.renderer_3d import DualGLVolumeItem, Renderer3DLODManager

logger = logging.getLogger(__name__)


class GeologicalModeling3DPage(QWidget):
    """3D Geological Modeling Workbench Page.

    Features:
    - Left: Model Hierarchy Tree
    - Center: pyqtgraph.opengl 3D interactive viewport + floating toolbar
    - Right: Parameter Configuration & Run Panel
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeologicalModeling3DPage")
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
        main_layout.setSpacing(tokens.SPACE_2)
        
        # Horizontal Splitter for Left, Center, Right panels
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setStyleSheet("QSplitter::handle { background: %s; width: 1px; }" % tokens.BORDER)
        
        # 1. Left Panel (Hierarchy & Assets)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(tokens.SPACE_2)
        
        left_header = QLabel("模型树 & 资产")
        left_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        left_layout.addWidget(left_header)
        
        self.model_tree = QTreeWidget()
        self.model_tree.setHeaderLabel("三维地质模型")
        self.model_tree.setStyleSheet("QTreeView { border-radius: %dpx; }" % tokens.RADIUS_CARD)
        self._populate_model_tree()
        left_layout.addWidget(self.model_tree)
        
        # 2. Center Panel (3D Canvas + Floating Toolbar)
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        
        # 3D Viewport container
        self.view_container = QFrame()
        self.view_container.setFrameShape(QFrame.StyledPanel)
        self.view_container.setStyleSheet("QFrame { background: #020617; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        
        view_layout = QVBoxLayout(self.view_container)
        view_layout.setContentsMargins(0, 0, 0, 0)
        
        # pyqtgraph GL View Widget
        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.opts['distance'] = 300
        view_layout.addWidget(self.gl_widget)
        
        # Add grid lines and dummy volume item
        grid = gl.GLGridItem()
        grid.setSize(200, 200, 200)
        grid.setSpacing(10, 10, 10)
        self.gl_widget.addItem(grid)
        
        # Dummy volume model
        vol_data = np.zeros((100, 100, 100), dtype=np.float32)
        self.vol_item = DualGLVolumeItem(data=vol_data)
        self.gl_widget.addItem(self.vol_item)
        
        # Floating Glassmorphic Toolbar inside center view
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
                padding: 4px;
            }
            QPushButton:hover {
                background: %s;
                border-radius: 4px;
            }
        """ % (tokens.BG_GLASS, tokens.BG_GLASS_BORDER, tokens.RADIUS_BUTTON, tokens.HOVER_GLOW))
        self.floating_bar.setFixedHeight(38)
        self.floating_bar.setFixedWidth(200)
        
        f_layout = QHBoxLayout(self.floating_bar)
        f_layout.setContentsMargins(tokens.SPACE_1, 0, tokens.SPACE_1, 0)
        
        self.btn_orbit = QPushButton("旋转")
        self.btn_pan = QPushButton("平移")
        self.btn_sculpt = QPushButton("雕刻")
        f_layout.addWidget(self.btn_orbit)
        f_layout.addWidget(self.btn_pan)
        f_layout.addWidget(self.btn_sculpt)
        
        # Place floating bar at top-center of view container
        self.floating_bar.move(10, 10)
        
        center_layout.addWidget(self.view_container)
        
        # 3. Right Panel (Parameter & Run)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(tokens.SPACE_2)
        
        right_header = QLabel("建模参数面板")
        right_header.setStyleSheet("font-size: %s; font-weight: %s; color: %s;" % (
            tokens.FONT_SIZE_TITLE, tokens.FONT_WEIGHT_TITLE, tokens.TEXT_PRIMARY
        ))
        right_layout.addWidget(right_header)
        
        # Configuration Card
        config_card = QFrame()
        config_card.setStyleSheet("QFrame { background: #ffffff; border-radius: %dpx; border: 1px solid %s; }" % (
            tokens.RADIUS_CARD, tokens.BORDER
        ))
        cc_layout = QVBoxLayout(config_card)
        cc_layout.setSpacing(tokens.SPACE_2)
        
        cc_layout.addWidget(QLabel("网格密度 (Grid Density)"))
        self.combo_density = QComboBox()
        self.combo_density.addItems(["低 (100x100x100)", "中 (200x200x200)", "高 (400x400x400)"])
        cc_layout.addWidget(self.combo_density)
        
        cc_layout.addWidget(QLabel("属性插值算法"))
        self.combo_algo = QComboBox()
        self.combo_algo.addItems(["克里金插值 (Kriging)", "顺序高斯模拟 (SGS)", "逆距离加权 (IDW)"])
        cc_layout.addWidget(self.combo_algo)
        
        cc_layout.addWidget(QLabel("模型透明度 (Opacity)"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(50)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        cc_layout.addWidget(self.slider_opacity)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        cc_layout.addWidget(self.progress_bar)
        
        self.btn_run = QPushButton("开始三维建模")
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.clicked.connect(self._run_modeling)
        cc_layout.addWidget(self.btn_run)
        
        cc_layout.addStretch()
        right_layout.addWidget(config_card)
        
        # Add widgets to splitter
        splitter.addWidget(left_widget)
        splitter.addWidget(center_widget)
        splitter.addWidget(right_widget)
        
        # Give more stretch weight to center canvas
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        
        main_layout.addWidget(splitter)

    def _populate_model_tree(self) -> None:
        root_struct = QTreeWidgetItem(self.model_tree, ["地层构造格架"])
        root_struct.addChild(QTreeWidgetItem(["LST 顶底面"]))
        root_struct.addChild(QTreeWidgetItem(["TST 顶底面"]))
        
        root_fault = QTreeWidgetItem(self.model_tree, ["断层格架模型"])
        root_fault.addChild(QTreeWidgetItem(["断层 F1 Surface"]))
        root_fault.addChild(QTreeWidgetItem(["断层 F2 Surface"]))
        
        root_prop = QTreeWidgetItem(self.model_tree, ["储层属性实体"])
        root_prop.addChild(QTreeWidgetItem(["孔隙度体模型 (Porosity)"]))
        root_prop.addChild(QTreeWidgetItem(["砂体发育概率模型"]))
        
        self.model_tree.expandAll()

    def _on_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        logger.info(f"Setting 3D Volume Item opacity to {opacity}")

    def _run_modeling(self) -> None:
        logger.info("Executing 3D geological modeling algorithm...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(30)
        self.btn_run.setEnabled(False)
