"""Dialog for creating professional Geological Factor Maps with Kriging and GIS layers."""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.mapping.color_ramps import list_color_ramps
from paleo_workbench.mapping.layers import MapDocument
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.services.geological_mapping_service import (
    DEFAULT_GEOLOGICAL_MAPPING_SERVICE,
    GeologicalMappingService,
)
from paleo_workbench.ui import tokens

logger = logging.getLogger(__name__)


class _FactorMapWorker(QThread):
    """Background worker executing Kriging, Grid generation, and Contouring."""

    finished = Signal(object, object)  # map_doc, task
    failed = Signal(str)

    def __init__(
        self,
        service: GeologicalMappingService,
        project: ProjectDocument,
        params: dict[str, Any],
        parent=None,
    ):
        super().__init__(parent)
        self.service = service
        self.project = project
        self.params = params

    def run(self) -> None:
        try:
            map_doc, task = self.service.create_factor_map(
                self.project,
                factor_name=self.params["factor_name"],
                target_horizon=self.params.get("target_horizon", ""),
                method=self.params.get("method", "kriging"),
                grid_n=self.params.get("grid_n", 50),
                color_ramp=self.params.get("color_ramp"),
                include_grid=self.params.get("include_grid", True),
                include_contours=self.params.get("include_contours", True),
                include_wells=self.params.get("include_wells", True),
                include_polygons=self.params.get("include_polygons", False),
            )
            self.finished.emit(map_doc, task)
        except Exception as exc:
            logger.exception("Factor map generation failed")
            self.failed.emit(str(exc))


class CreateFactorMapDialog(QDialog):
    """Interactive modal dialog for configuring and generating geological factor maps."""

    map_created = Signal(object)  # MapDocument

    def __init__(self, project: ProjectDocument, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.service = DEFAULT_GEOLOGICAL_MAPPING_SERVICE
        self.created_map_doc: MapDocument | None = None
        self._worker: _FactorMapWorker | None = None

        self.setWindowTitle("创建地质单因素图件 (Geological Factor Map)")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(tokens.SPACE_3)

        # Form Group
        form_group = QGroupBox("参数配置", self)
        form_layout = QFormLayout(form_group)

        # Factor selection
        self.factor_combo = QComboBox(self)
        self.factor_combo.addItems([
            "砂岩厚度", "地层厚度", "孔隙度", "渗透率", "TOC", "古水深", "砂地比"
        ])
        form_layout.addRow("地质因素:", self.factor_combo)

        # Horizon selection
        self.horizon_combo = QComboBox(self)
        horizons = []
        if hasattr(project, "stratigraphy") and project.stratigraphy.target_horizon:
            horizons.append(project.stratigraphy.target_horizon)
        horizons.extend(["T1", "T2", "T3", "E1s", "E2s", "E3s", "K1q"])
        self.horizon_combo.addItems(list(dict.fromkeys(horizons)))
        form_layout.addRow("目的层段:", self.horizon_combo)

        # Interpolation method
        self.method_combo = QComboBox(self)
        self.method_combo.addItem("克里金插值 (Ordinary Kriging)", "kriging")
        self.method_combo.addItem("反距离加权 (IDW)", "idw")
        form_layout.addRow("插值算法:", self.method_combo)

        # Grid Resolution
        self.grid_size_spin = QSpinBox(self)
        self.grid_size_spin.setRange(20, 300)
        self.grid_size_spin.setValue(50)
        self.grid_size_spin.setSingleStep(10)
        form_layout.addRow("网格精度 (N×N):", self.grid_size_spin)

        # Color Ramp
        self.ramp_combo = QComboBox(self)
        self.ramp_combo.addItems([
            "porosity", "permeability", "sand_thickness", "thickness", "toc", "water_depth",
            "viridis", "plasma", "magma", "coolwarm", "jet"
        ])
        form_layout.addRow("配色色带:", self.ramp_combo)

        layout.addWidget(form_group)

        # Output Layers Group
        layers_group = QGroupBox("生成图层", self)
        layers_layout = QVBoxLayout(layers_group)
        self.chk_grid = QCheckBox("连续属性栅格图层 (Grid Layer)", self)
        self.chk_grid.setChecked(True)
        self.chk_contour = QCheckBox("等值线矢量图层 (Contour Layer - Marching Squares)", self)
        self.chk_contour.setChecked(True)
        self.chk_wells = QCheckBox("井位及属性标注图层 (Well Point Layer)", self)
        self.chk_wells.setChecked(True)
        self.chk_polygons = QCheckBox("相带划分多边形图层 (Facies Polygon Layer)", self)
        self.chk_polygons.setChecked(False)

        layers_layout.addWidget(self.chk_grid)
        layers_layout.addWidget(self.chk_contour)
        layers_layout.addWidget(self.chk_wells)
        layers_layout.addWidget(self.chk_polygons)
        layout.addWidget(layers_group)

        # Progress bar
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消", self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_create = QPushButton("开始生成图件", self)
        self.btn_create.setObjectName("PrimaryButton")
        self.btn_create.clicked.connect(self._on_create_clicked)
        btn_layout.addWidget(self.btn_create)

        layout.addLayout(btn_layout)

    def _on_create_clicked(self) -> None:
        self.btn_create.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.progress_bar.setVisible(True)

        params = {
            "factor_name": self.factor_combo.currentText(),
            "target_horizon": self.horizon_combo.currentText(),
            "method": self.method_combo.currentData(),
            "grid_n": self.grid_size_spin.value(),
            "color_ramp": self.ramp_combo.currentText(),
            "include_grid": self.chk_grid.isChecked(),
            "include_contours": self.chk_contour.isChecked(),
            "include_wells": self.chk_wells.isChecked(),
            "include_polygons": self.chk_polygons.isChecked(),
        }

        self._worker = _FactorMapWorker(self.service, self.project, params, self)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_finished(self, map_doc: MapDocument, task) -> None:
        self.progress_bar.setVisible(False)
        self.created_map_doc = map_doc
        self.map_created.emit(map_doc)
        QMessageBox.information(
            self,
            "生成完成",
            f"成功生成地质图件：{map_doc.title}\n包含 {len(map_doc.layers)} 个 GIS 图层。",
        )
        self.accept()

    def _on_worker_failed(self, error_msg: str) -> None:
        self.progress_bar.setVisible(False)
        self.btn_create.setEnabled(True)
        self.btn_cancel.setEnabled(True)
        QMessageBox.critical(self, "生成失败", f"地质编图失败：{error_msg}")
