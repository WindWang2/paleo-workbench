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
        self._project: ProjectDocument | None = project
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
        self._project = project
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
        a_sel = self._well_a.currentText()
        b_sel = self._well_b.currentText()
        self._well_a.clear()
        self._well_b.clear()
        names = self._host.well_names()
        self._well_a.addItems(names)
        self._well_b.addItems(names)
        # Preserve the user's selection across scene refreshes (fence creation,
        # LOD refinements re-emit scene_updated); fall back to the original
        # defaults only when the chosen well is no longer present.
        if a_sel in names:
            self._well_a.setCurrentText(a_sel)
        elif names:
            self._well_a.setCurrentIndex(0)
        if b_sel in names:
            self._well_b.setCurrentText(b_sel)
        elif len(names) >= 2:
            self._well_b.setCurrentIndex(1)

    def _on_well_fence(self) -> None:
        self._host.add_well_to_well_fence(
            self._well_a.currentText(), self._well_b.currentText()
        )

    def _on_domain_changed(self, text: str) -> None:
        applied = self._host.set_vertical_domain(text)
        if not applied:
            # Depth refused (no transform): revert the combo to the scene's
            # actual domain instead of showing a state the scene is not in.
            scene = self._host.scene
            actual = (
                "Depth"
                if scene is not None
                and scene.vertical_domain.value.startswith("depth")
                else "Time"
            )
            self._domain.blockSignals(True)
            idx = self._domain.findText(actual)
            if idx >= 0:
                self._domain.setCurrentIndex(idx)
            self._domain.blockSignals(False)

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
            self._register_snapshot_export(target)
            return str(target)
        self._status.setText("快照导出失败")
        return None

    def _loaded_source_resource_ids(self) -> list[str]:
        """Resource ids of the seismic / well data currently loaded into the
        joint scene (lineage sources for the snapshot export).

        Path matching goes through ``resource_ids_for_paths`` so relative
        resource paths resolve against the PROJECT dir (never the process
        CWD); an empty match with loaded paths is logged, not silent."""
        if self._project is None:
            return []
        paths = self._host.paths
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
        from paleo_workbench.catalog.lifecycle import resource_ids_for_paths

        ids = resource_ids_for_paths(
            getattr(self._project, "resources", None) or [],
            wanted,
            project_path=self._catalog_project_path(),
        )
        if not ids:
            logger.warning(
                "well-seismic snapshot export: no project resources matched the "
                "loaded scene paths (%d paths) — OUTPUT lineage will be empty",
                len(wanted),
            )
        return ids

    @staticmethod
    def _catalog_project_path() -> str | None:
        """Project file path from the active catalog service (may be None)."""
        try:
            from paleo_workbench.catalog import get_catalog_service

            service = get_catalog_service()
            if service is not None:
                return str(service.project_path)
        except Exception:
            pass
        return None

    def _register_snapshot_export(self, path: str) -> None:
        """Best-effort OUTPUT DataVersion registration (no catalog → no-op)."""
        if self._project is None:
            return
        try:
            from paleo_workbench.catalog.lifecycle import register_export_output

            register_export_output(
                name="井震联合快照 export",
                output_path=str(path),
                fmt="png",
                source_task_ids=self._loaded_source_resource_ids(),
                linked_id="well_seismic_joint",
                catalog=None,
            )
        except Exception:
            # Provenance is best-effort; never break the export flow.
            pass
