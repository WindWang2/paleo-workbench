"""WellSeismicJointPage — thin host for 井震联合分析 (#59 / #75 gaps)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench import tokens
from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, _repo_root
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths, resolve_joint_assets
from paleo_workbench.viz.joint_well_parsers import load_td_tables, parse_well_heads
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

logger = logging.getLogger(__name__)


class _PreviewVolumeWorker(QObject):
    """Background downsampled SEGY load (OwnedWorkerJob target)."""

    finished = Signal(object, str)
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
    """Hybrid bind + OwnedWorkerJob preview load + fence toolbar + domain."""

    def __init__(self, parent=None, project: ProjectDocument | None = None):
        super().__init__(parent)
        self.setObjectName("WellSeismicJointPage")
        self._project = project
        self._volume_job = OwnedWorkerJob(self)
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
        if not self._loaded_once and self.isVisible():
            self._loaded_once = True
            self.reload()

    def reload(self) -> None:
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
            self._apply_tops_and_curves(paths)
            self._fill_well_combos()
        except Exception as exc:
            self._status.setText(f"加载失败: {exc}")
            logger.exception("joint load failed")
            return

        if paths.segy is not None:
            self._status.setText(f"正在后台加载预览体… ({paths.segy.name})")
            self._start_volume_worker(str(paths.segy))
        else:
            self._joint.set_scene(self._scene)
            self._status.setText(f"已加载井/测网（无 SEGY）· 来源={paths.source}")

    def _apply_wells_and_survey(self, paths: JointAssetPaths) -> None:
        from geoviz import (
            VerticalDomain,
            align_horizon_corners_to_loader_axes,
            horizon_corners_from_dat,
            survey_corners_from_segy,
        )

        assert self._scene is not None
        self._scene.set_vertical_domain(VerticalDomain.TIME)
        self._domain.blockSignals(True)
        self._domain.setCurrentText("Time")
        self._domain.blockSignals(False)

        if paths.segy is not None:
            p1, p2, p3, meta = survey_corners_from_segy(paths.segy)
            self._survey_meta = meta
            self._scene.set_survey_from_corners(
                p1,
                p2,
                p3,
                n_samples=int(meta["n_samples"]),
                dt_ms=float(meta["dt_ms"]),
                t0_ms=float(meta.get("t0_ms", 0.0)),
            )
            if paths.horizons:
                corners = horizon_corners_from_dat(paths.horizons[0])
                if corners is not None:
                    corners = align_horizon_corners_to_loader_axes(*corners)
                    ok, msg = self._scene.validate_against_corners(
                        *corners, tol_m=50.0, tol_il_xl=1.0
                    )
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
        self._scene.las_paths = [str(p) for p in paths.las_files]

    def _apply_tops_and_curves(self, paths: JointAssetPaths) -> None:
        """Load formation tops (MD→TWT via TD) and best-effort LAS curves."""
        import numpy as np

        assert self._scene is not None
        tops_by_well: dict[str, list[tuple[str, float]]] = {}
        if paths.tops is not None and paths.tops.is_file():
            for line in paths.tops.read_text(encoding="utf-8", errors="replace").splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split()
                if len(parts) < 3:
                    continue
                wname, tname, md_s = parts[0], parts[1], parts[2]
                try:
                    md = float(md_s)
                except ValueError:
                    continue
                # Time domain: convert MD via TD table if present
                z = md
                td_map = {}
                if paths.td_dir is not None:
                    td_map = load_td_tables(paths.td_dir)
                tbl = td_map.get(wname)
                if tbl is not None:
                    z = float(tbl.md_to_time_ms(md))
                tops_by_well.setdefault(wname, []).append((tname, z))
        if tops_by_well:
            self._scene.set_formation_tops(tops_by_well)

        # LAS curves: light parse via geoviz load_las_preview when available
        curves: dict[str, dict[str, tuple]] = {}
        for las_path in paths.las_files[:20]:
            try:
                from geoviz import load_las_preview

                data = load_las_preview(str(las_path), fast=True)
                # expect well name from stem
                wname = Path(las_path).stem
                if data is None:
                    continue
                well_curves: dict[str, tuple] = {}
                # WellLogData-like
                curves_list = getattr(data, "curves", None) or []
                depth = None
                for c in curves_list:
                    name = getattr(c, "name", "") or getattr(c, "mnemonic", "")
                    vals = np.asarray(getattr(c, "values", getattr(c, "data", [])), dtype=float)
                    if name.upper() in {"DEPT", "DEPTH", "MD"}:
                        depth = vals
                if depth is None:
                    continue
                for c in curves_list:
                    name = str(getattr(c, "name", "") or getattr(c, "mnemonic", ""))
                    if name.upper() in {"DEPT", "DEPTH", "MD"}:
                        continue
                    vals = np.asarray(getattr(c, "values", getattr(c, "data", [])), dtype=float)
                    if vals.size == depth.size:
                        well_curves[name] = (depth, vals)
                if well_curves:
                    curves[wname] = well_curves
            except Exception:
                continue
        if curves:
            self._scene.set_well_curves(curves)

    def _fill_well_combos(self) -> None:
        self._well_a.clear()
        self._well_b.clear()
        if self._scene is None:
            return
        names = list(self._scene.well_trajectories().keys())
        self._well_a.addItems(names)
        self._well_b.addItems(names)
        if len(names) >= 2:
            self._well_b.setCurrentIndex(1)

    def _start_volume_worker(self, segy_path: str) -> None:
        if self._volume_job.is_running:
            self._volume_job.shutdown()
        worker = _PreviewVolumeWorker(segy_path)
        self._volume_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_volume_ready),
                (worker.failed, self._on_volume_failed),
            ),
        )

    @Slot(object, str)
    def _on_volume_ready(self, volume, warning: str) -> None:
        from geoviz import InMemoryVolumeAccess

        if self._scene is None or self._joint is None:
            return
        if volume is None:
            self._status.setText(f"预览体加载失败: {warning or 'unknown'}")
            self._joint.set_scene(self._scene)
            return
        # Wayfinder #84: survey already matches loader volume axes; no transpose.
        self._scene.set_volume_access(InMemoryVolumeAccess(volume))
        self._scene.set_preview_mode(True)
        # Auto well-to-well fence for first two wells when possible
        names = list(self._scene.well_trajectories().keys())
        if len(names) >= 2 and not self._scene.fences:
            try:
                self._scene.add_well_to_well_fence(names[:2], name="默认井间")
            except Exception:
                pass
        self._joint.set_scene(self._scene)
        src = self._paths.source if self._paths else "?"
        msg = f"已加载预览体 shape={tuple(volume.shape)} · 来源={src}"
        if warning:
            msg += f" · {warning}"
        if self._scene.fences:
            msg += f" · fences={len(self._scene.fences)}"
        self._status.setText(msg)

    @Slot(str)
    def _on_volume_failed(self, err: str) -> None:
        self._status.setText(f"预览体加载异常: {err}")
        if self._scene is not None and self._joint is not None:
            self._joint.set_scene(self._scene)

    def _on_well_fence(self) -> None:
        if self._scene is None or self._joint is None:
            return
        a, b = self._well_a.currentText(), self._well_b.currentText()
        if not a or not b or a == b:
            self._status.setText("请选择两口不同井")
            return
        try:
            self._scene.add_well_to_well_fence([a, b], name=f"{a}-{b}")
            self._joint.set_scene(self._scene)
            self._status.setText(f"已创建井间剖面 {a}–{b}")
        except Exception as exc:
            self._status.setText(f"创建剖面失败: {exc}")

    def _on_domain_changed(self, text: str) -> None:
        from geoviz import VerticalDomain, select_depth_transform

        if self._scene is None or self._joint is None:
            return
        if text.lower().startswith("depth"):
            self._scene.set_depth_transform(
                select_depth_transform(has_external_volume=False, v0_m_s=3000.0)
            )
            self._scene.set_vertical_domain(VerticalDomain.DEPTH)
            warn = self._scene.depth_transform.approximate_warning or ""
            self._status.setText(f"竖直域=Depth · {warn}")
        else:
            self._scene.set_vertical_domain(VerticalDomain.TIME)
            self._status.setText("竖直域=Time")
        self._joint.set_scene(self._scene)

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
