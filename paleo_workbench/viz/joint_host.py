"""Reusable well–seismic joint host (PRD #85 / ticket #86).

Owns hybrid resolve, WellSeismicScene bind, preview volume job, domain, and
fence actions. UI pages (joint page today; modeling page later) only provide
widgets and forward user actions.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path, _repo_root
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
from paleo_workbench.viz.joint_asset_resolver import JointAssetPaths, resolve_joint_assets
from paleo_workbench.viz.joint_well_parsers import load_td_tables, parse_well_heads
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

logger = logging.getLogger(__name__)


class PreviewVolumeWorker(QObject):
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


class WellSeismicJointHost(QObject):
    """Non-UI host for joint scene lifecycle.

    Signals
    -------
    status_changed:
        Human-readable status for chrome labels.
    scene_updated:
        Emitted after scene content changes; listeners should refresh joint widgets.
    """

    status_changed = Signal(str)
    scene_updated = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project: ProjectDocument | None = None
        self._volume_job = OwnedWorkerJob(self)
        self._paths: JointAssetPaths | None = None
        self._survey_meta: dict = {}
        self._scene = None
        self._engine_error: str | None = None

        ensure_geoviz_on_path()
        try:
            from geoviz import WellSeismicScene

            self._scene = WellSeismicScene()
        except Exception as exc:
            logger.exception("joint scene unavailable")
            self._engine_error = str(exc)
            self._scene = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def scene(self):
        return self._scene

    @property
    def paths(self) -> JointAssetPaths | None:
        return self._paths

    @property
    def survey_meta(self) -> dict:
        return dict(self._survey_meta)

    @property
    def engine_error(self) -> str | None:
        return self._engine_error

    def set_project(self, project: ProjectDocument | None) -> None:
        self._project = project

    def well_names(self) -> list[str]:
        if self._scene is None:
            return []
        return list(self._scene.well_trajectories().keys())

    def reload(
        self,
        *,
        preferred_domain: str | None = None,
        auto_default_fence: bool = True,
    ) -> None:
        """Reload hybrid assets into the scene.

        preferred_domain:
            If set ('Time'/'Depth'), applied after survey/wells bind so restore
            is not clobbered by a forced Time default (code-review Spec fix).
        auto_default_fence:
            When False, skip auto well-to-well fence on volume ready (restore path).
        """
        if self._scene is None:
            self.status_changed.emit(
                f"联合场景不可用: {self._engine_error or 'unknown'}"
            )
            return
        self._auto_default_fence = bool(auto_default_fence)
        self._pending_domain = preferred_domain
        repo = _repo_root()
        self._paths = resolve_joint_assets(self._project, repo_root=repo)
        paths = self._paths
        if not paths.has_minimum():
            self.status_changed.emit(
                "空状态：未找到 SEGY 或井位。请在「数据」导入资产，或放置 data/ 演示目录。"
            )
            return
        try:
            self._apply_wells_and_survey(paths)
            self._apply_tops_and_curves(paths)
            # Restore domain after bind (survey apply no longer hard-forces UI domain)
            domain = preferred_domain
            if domain is None and self._project is not None:
                state = getattr(self._project, "joint_analysis", None)
                domain = getattr(state, "vertical_domain", None) if state else None
            if domain:
                self.set_vertical_domain(domain, emit_scene=False)
        except Exception as exc:
            self.status_changed.emit(f"加载失败: {exc}")
            logger.exception("joint load failed")
            return

        if paths.segy is not None:
            self.status_changed.emit(f"正在后台加载预览体… ({paths.segy.name})")
            self._start_volume_worker(str(paths.segy))
        else:
            self.status_changed.emit(f"已加载井/测网（无 SEGY）· 来源={paths.source}")
            self.scene_updated.emit()

    def set_vertical_domain(self, domain: str, *, emit_scene: bool = True) -> None:
        """domain: 'Time' or 'Depth' (case-insensitive prefix)."""
        from geoviz import VerticalDomain, select_depth_transform

        if self._scene is None:
            return
        if str(domain).lower().startswith("depth"):
            self._scene.set_depth_transform(
                select_depth_transform(has_external_volume=False, v0_m_s=3000.0)
            )
            self._scene.set_vertical_domain(VerticalDomain.DEPTH)
            warn = self._scene.depth_transform.approximate_warning or ""
            self.status_changed.emit(f"竖直域=Depth · {warn}")
        else:
            self._scene.set_vertical_domain(VerticalDomain.TIME)
            self.status_changed.emit("竖直域=Time")
        if emit_scene:
            self.scene_updated.emit()

    def add_well_to_well_fence(self, well_a: str, well_b: str, *, name: str | None = None) -> None:
        if self._scene is None:
            return
        a, b = (well_a or "").strip(), (well_b or "").strip()
        if not a or not b or a == b:
            self.status_changed.emit("请选择两口不同井")
            return
        try:
            label = name or f"{a}-{b}"
            self._scene.add_well_to_well_fence([a, b], name=label)
            self.status_changed.emit(f"已创建井间剖面 {a}–{b}")
            self.scene_updated.emit()
        except Exception as exc:
            self.status_changed.emit(f"创建剖面失败: {exc}")

    def shutdown(self) -> None:
        if self._volume_job.is_running:
            self._volume_job.shutdown()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _apply_wells_and_survey(self, paths: JointAssetPaths) -> None:
        from geoviz import (
            align_horizon_corners_to_loader_axes,
            horizon_corners_from_dat,
            survey_corners_from_segy,
        )

        assert self._scene is not None
        # Domain is applied by reload(preferred_domain=...) after this bind.
        self._survey_meta = {}

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

        curves: dict[str, dict[str, tuple]] = {}
        for las_path in paths.las_files[:20]:
            try:
                from geoviz import load_las_preview

                data = load_las_preview(str(las_path), fast=True)
                wname = Path(las_path).stem
                if data is None:
                    continue
                well_curves: dict[str, tuple] = {}
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

    def _start_volume_worker(self, segy_path: str) -> None:
        if self._volume_job.is_running:
            self._volume_job.shutdown()
        worker = PreviewVolumeWorker(segy_path)
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

        if self._scene is None:
            return
        if volume is None:
            self.status_changed.emit(f"预览体加载失败: {warning or 'unknown'}")
            self.scene_updated.emit()
            return
        self._scene.set_volume_access(InMemoryVolumeAccess(volume))
        self._scene.set_preview_mode(True)
        names = list(self._scene.well_trajectories().keys())
        if (
            getattr(self, "_auto_default_fence", True)
            and len(names) >= 2
            and not self._scene.fences
        ):
            try:
                self._scene.add_well_to_well_fence(names[:2], name="默认井间")
            except Exception:
                pass
        src = self._paths.source if self._paths else "?"
        msg = f"已加载预览体 shape={tuple(volume.shape)} · 来源={src}"
        if warning:
            msg += f" · {warning}"
        if self._scene.fences:
            msg += f" · fences={len(self._scene.fences)}"
        self.status_changed.emit(msg)
        self.scene_updated.emit()

    @Slot(str)
    def _on_volume_failed(self, err: str) -> None:
        self.status_changed.emit(f"预览体加载异常: {err}")
        self.scene_updated.emit()
