"""WellSeismicJointPage — thin host for 井震联合分析 (#59)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, _repo_root
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths, resolve_joint_assets
from paleo_workbench.viz.joint_segy_survey import (
    horizon_corners_from_dat,
    survey_corners_from_segy,
)
from paleo_workbench.viz.joint_well_parsers import load_td_tables, parse_well_heads
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

logger = logging.getLogger(__name__)


class _PreviewVolumeWorker(QObject):
    """Background downsampled SEGY load (never on UI thread)."""

    finished = Signal(object, str)  # volume ndarray | None, warning/error
    failed = Signal(str)

    def __init__(self, segy_path: str) -> None:
        super().__init__()
        self._path = segy_path

    @Slot()
    def run(self) -> None:
        try:
            vol, warning = load_seismic_volume_from_path(self._path)
            self.finished.emit(vol, warning or "")
        except Exception as exc:
            self.failed.emit(str(exc))


class WellSeismicJointPage(QWidget):
    """Top-level page: hybrid bind + auto-load preview into joint widget."""

    def __init__(self, parent=None, project: ProjectDocument | None = None):
        super().__init__(parent)
        self.setObjectName("WellSeismicJointPage")
        self._project = project
        self._thread: QThread | None = None
        self._worker: _PreviewVolumeWorker | None = None
        self._paths: JointAssetPaths | None = None
        self._scene = None
        self._joint = None
        self._loaded_once = False

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
        try:
            from geoviz import WellSeismicJointWidget, WellSeismicScene

            self._scene = WellSeismicScene()
            self._joint = WellSeismicJointWidget(self)
            outer.addWidget(self._joint, 1)
        except Exception as exc:
            logger.exception("joint widget unavailable")
            self._joint = None
            outer.addWidget(QLabel(f"联合三维引擎不可用: {exc}"), 1)

    def set_project(self, project: ProjectDocument | None) -> None:
        self._project = project

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # Auto-load on first show (wayfinder enter). Skip if widget never polished.
        if not self._loaded_once and self.isVisible():
            self._loaded_once = True
            self.reload()

    def reload(self) -> None:
        """Resolve hybrid assets and auto-load (wayfinder enter path)."""
        if self._scene is None or self._joint is None:
            self._status.setText("联合场景不可用")
            return
        repo = _repo_root()
        self._paths = resolve_joint_assets(self._project, repo_root=repo)
        paths = self._paths
        if not paths.has_minimum():
            self._status.setText(
                "空状态：未找到 SEGY 或井位。请在「数据」导入资产，或放置 data/ 演示目录。"
            )
            return

        try:
            self._apply_wells_and_survey(paths)
        except Exception as exc:
            self._status.setText(f"加载失败: {exc}")
            logger.exception("joint load failed")
            return

        if paths.segy is not None:
            self._status.setText(f"正在后台加载预览体… ({paths.segy.name})")
            self._start_volume_worker(str(paths.segy))
        else:
            self._joint.set_scene(self._scene)
            self._status.setText(
                f"已加载井/测网（无 SEGY）· 来源={paths.source}"
            )

    def _apply_wells_and_survey(self, paths: JointAssetPaths) -> None:
        from geoviz import VerticalDomain

        assert self._scene is not None
        self._scene.set_vertical_domain(VerticalDomain.TIME)

        if paths.segy is not None:
            p1, p2, p3, meta = survey_corners_from_segy(paths.segy)
            self._scene.set_survey_from_corners(
                p1,
                p2,
                p3,
                n_samples=int(meta["n_samples"]),
                dt_ms=float(meta["dt_ms"]),
                t0_ms=float(meta.get("t0_ms", 0.0)),
            )
            # Horizon validate (wayfinder C)
            if paths.horizons:
                corners = horizon_corners_from_dat(paths.horizons[0])
                if corners is not None:
                    ok, msg = self._scene.validate_against_corners(*corners, tol_m=50.0)
                    if not ok:
                        raise RuntimeError(f"测网与层位角点不一致（已中止）: {msg}")

        wells = []
        if paths.well_head is not None:
            wells = parse_well_heads(paths.well_head)
        td_tables = {}
        if paths.td_dir is not None:
            td_tables = load_td_tables(paths.td_dir)
        if wells:
            self._scene.set_wells(wells, td_tables=td_tables)

        # Stash LAS paths on scene for later tickets
        self._scene.las_paths = [str(p) for p in paths.las_files]  # type: ignore[attr-defined]

    def _start_volume_worker(self, segy_path: str) -> None:
        self._cleanup_thread()
        thread = QThread(self)
        worker = _PreviewVolumeWorker(segy_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_volume_ready)
        worker.failed.connect(self._on_volume_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    @Slot(object, str)
    def _on_volume_ready(self, volume, warning: str) -> None:
        from geoviz import InMemoryVolumeAccess

        if self._scene is None or self._joint is None:
            return
        if volume is None:
            self._status.setText(f"预览体加载失败: {warning or 'unknown'}")
            self._joint.set_scene(self._scene)
            return
        self._scene.set_volume_access(InMemoryVolumeAccess(volume))
        self._joint.set_scene(self._scene)
        src = self._paths.source if self._paths else "?"
        msg = f"已加载预览体 shape={tuple(volume.shape)} · 来源={src}"
        if warning:
            msg += f" · {warning}"
        self._status.setText(msg)

    @Slot(str)
    def _on_volume_failed(self, err: str) -> None:
        self._status.setText(f"预览体加载异常: {err}")
        if self._scene is not None and self._joint is not None:
            self._joint.set_scene(self._scene)

    def export_snapshot(self, path: str | None = None) -> str | None:
        """Read-only PNG snapshot of the joint widget (#66)."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        target = path
        if not target:
            target, _ = QFileDialog.getSaveFileName(
                self, "导出快照", "well_seismic_joint.png", "PNG (*.png)"
            )
        if not target:
            return None
        pix = self.grab()
        ok = pix.save(str(target))
        if ok:
            self._status.setText(f"已导出快照: {Path(target).name}")
            return str(target)
        self._status.setText("快照导出失败")
        return None

    def _cleanup_thread(self) -> None:
        if self._thread is not None:
            try:
                self._thread.quit()
                self._thread.wait(1000)
            except Exception:
                pass
            self._thread = None
            self._worker = None
