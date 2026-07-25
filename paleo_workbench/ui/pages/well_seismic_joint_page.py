"""WellSeismicJointPage — thin UI shell over WellSeismicJointHost (#86 / #85)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.joint_host import WellSeismicJointHost

logger = logging.getLogger(__name__)


class WellSeismicJointPage(QWidget):
    """Toolbar + joint widget; all scene lifecycle is on the host."""

    def __init__(self, parent=None, project: ProjectDocument | None = None):
        super().__init__(parent)
        self.setObjectName("WellSeismicJointPage")
        self._loaded_once = False
        self._host = WellSeismicJointHost(self)
        self._host.set_project(project)
        self._host.status_changed.connect(self._on_status)
        self._host.scene_updated.connect(self._on_scene_updated)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(tokens.SPACE_2)

        header = QHBoxLayout()
        self._title = QLabel("井震联合分析")
        self._title.setStyleSheet(
            f"font-size: 16px; font-weight: 600; color: {tokens.TEXT_PRIMARY};"
        )
        header.addWidget(self._title)
        header.addStretch()

        self._domain = QComboBox()
        self._domain.addItems(["Time", "Depth"])
        self._domain.currentTextChanged.connect(self._on_domain_changed)
        header.addWidget(QLabel("竖直域"))
        header.addWidget(self._domain)

        self._well_a = QComboBox()
        self._well_b = QComboBox()
        header.addWidget(QLabel("井间"))
        header.addWidget(self._well_a)
        header.addWidget(self._well_b)
        self._fence_btn = QPushButton("井间剖面")
        self._fence_btn.clicked.connect(self._on_well_fence)
        header.addWidget(self._fence_btn)

        self._reload_btn = QPushButton("重新加载")
        self._reload_btn.clicked.connect(self.reload)
        header.addWidget(self._reload_btn)
        self._snapshot_btn = QPushButton("导出快照")
        self._snapshot_btn.clicked.connect(self.export_snapshot)
        header.addWidget(self._snapshot_btn)
        outer.addLayout(header)

        self._status = QLabel("就绪")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; padding: 4px;")
        outer.addWidget(self._status)

        ensure_geoviz_on_path()
        self._joint = None
        if self._host.scene is not None:
            try:
                from geoviz import WellSeismicJointWidget

                self._joint = WellSeismicJointWidget(self)
                outer.addWidget(self._joint, 1)
            except Exception as exc:
                logger.exception("joint widget unavailable")
                outer.addWidget(QLabel(f"联合三维引擎不可用: {exc}"), 1)
        else:
            outer.addWidget(
                QLabel(f"联合三维引擎不可用: {self._host.engine_error or 'unknown'}"),
                1,
            )

    def set_project(self, project: ProjectDocument | None) -> None:
        self._host.set_project(project)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._loaded_once and self.isVisible():
            self._loaded_once = True
            self.reload()

    def reload(self) -> None:
        self._host.reload()
        self._fill_well_combos()

    def _on_status(self, text: str) -> None:
        self._status.setText(text)

    def _on_scene_updated(self) -> None:
        if self._joint is not None and self._host.scene is not None:
            self._joint.set_scene(self._host.scene)
        self._fill_well_combos()

    def _fill_well_combos(self) -> None:
        self._well_a.clear()
        self._well_b.clear()
        names = self._host.well_names()
        self._well_a.addItems(names)
        self._well_b.addItems(names)
        if len(names) >= 2:
            self._well_b.setCurrentIndex(1)

    def _on_well_fence(self) -> None:
        self._host.add_well_to_well_fence(
            self._well_a.currentText(), self._well_b.currentText()
        )

    def _on_domain_changed(self, text: str) -> None:
        self._host.set_vertical_domain(text)

    def export_snapshot(self, path: str | None = None) -> str | None:
        from PySide6.QtWidgets import QFileDialog

        target = path
        if not target:
            target, _ = QFileDialog.getSaveFileName(
                self, "导出快照", "well_seismic_joint.png", "PNG (*.png)"
            )
        if not target:
            return None
        ok = self.grab().save(str(target))
        if ok:
            self._status.setText(f"已导出快照: {Path(target).name}")
            return str(target)
        self._status.setText("快照导出失败")
        return None
