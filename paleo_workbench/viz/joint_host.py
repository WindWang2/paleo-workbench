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
from paleo_workbench.viz.joint_well_identity import WellIdentityRegistry
from paleo_workbench.viz.joint_well_parsers import load_td_tables, parse_well_heads
from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

logger = logging.getLogger(__name__)


class PreviewVolumeWorker(QObject):
    """Background progressive LOD brick load (OwnedWorkerJob target).

    Emits ``(volume, warning, generation, lod_level)``. Dense bricks are only
    for GL display; scene slicing uses :class:`SourceBackedVolumeAccess`.
    """

    finished = Signal(object, str, int, int)  # volume, warning, generation, lod
    failed = Signal(str, int)

    def __init__(
        self,
        segy_path: str,
        *,
        generation: int = 0,
        lod: int = 0,
        cancellation_token=None,
    ) -> None:
        super().__init__()
        self._path = segy_path
        self._generation = int(generation)
        self._lod = int(lod)
        self._cancellation_token = cancellation_token

    @Slot()
    def run(self) -> None:
        try:
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            from paleo_workbench.viz.seismic_volume_source import get_shared_seismic_source

            source = get_shared_seismic_source(self._path)
            source.metadata()
            vol, warning = source.read_lod_volume(
                level=self._lod, cancellation_token=self._cancellation_token
            )
            self.finished.emit(vol, warning or "", self._generation, self._lod)
        except Exception as exc:
            try:
                from geoviz import JobCancelled
            except Exception:
                JobCancelled = None
            if JobCancelled is not None and isinstance(exc, JobCancelled):
                # Cooperative cancellation: report and stop — do NOT start the
                # legacy dense fallback read (H10).
                self.failed.emit(f"已取消: {exc}", self._generation)
                return
            try:
                vol, warning = load_seismic_volume_from_path(self._path)
                self.finished.emit(
                    vol, warning or str(exc), self._generation, self._lod
                )
            except Exception as exc2:
                self.failed.emit(str(exc2), self._generation)


class SurveyMetaWorker(QObject):
    """Background SEG-Y survey metadata pass (survey corners + volume meta).

    For 2D lines / non-standard geometry both ``survey_corners_from_segy``
    and ``SeismicVolumeSource.metadata`` perform full trace-header scans
    (several passes over every header); running them on the GUI thread froze
    the joint reload for seconds-to-minutes (C09). The worker runs the two
    scans off-thread; the host caches the result per file identity so
    reloads do not re-scan.
    """

    finished = Signal(object, int)  # payload dict, generation
    failed = Signal(str, int)

    def __init__(
        self,
        segy_path: str,
        *,
        generation: int = 0,
        cancellation_token=None,
    ) -> None:
        super().__init__()
        self._path = str(segy_path)
        self._generation = int(generation)
        self._cancellation_token = cancellation_token

    @Slot()
    def run(self) -> None:
        try:
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            from paleo_workbench.viz.joint_segy_survey import (
                survey_corners_from_segy,
            )
            from paleo_workbench.viz.seismic_volume_source import (
                get_shared_seismic_source,
            )

            source = get_shared_seismic_source(self._path)
            volume_meta = source.metadata()
            if self._cancellation_token is not None:
                self._cancellation_token.raise_if_cancelled()
            p1, p2, p3, meta = survey_corners_from_segy(self._path)
            payload = {
                "p1": p1,
                "p2": p2,
                "p3": p3,
                "corners_meta": meta,
                "volume_meta": volume_meta,
                "source_id": source.source_id,
            }
            self.finished.emit(payload, self._generation)
        except Exception as exc:
            try:
                from geoviz import JobCancelled
            except Exception:  # pragma: no cover - geoviz always present
                JobCancelled = None
            if JobCancelled is not None and isinstance(exc, JobCancelled):
                self.failed.emit(f"已取消: {exc}", self._generation)
            else:
                self.failed.emit(str(exc), self._generation)


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
        self._volume_generation = 0
        self._volume_phase = "EMPTY"
        self._source_backed_access = None
        self._paths: JointAssetPaths | None = None
        self._survey_meta: dict = {}
        self._well_identity_registry: WellIdentityRegistry | None = None
        self._persisted_well_identity_asset_id: str | None = None
        self._persisted_well_identity_map: dict[str, str] = {}
        self._scene = None
        self._engine_error: str | None = None
        # True while an L1 start waits for OwnedWorkerJob.released (see
        # _maybe_start_next_lod).
        self._lod_release_pending = False
        # Survey corners + volume metadata per file identity (source_id), so
        # a reload reuses the one background scan instead of re-scanning (C09).
        self._survey_payload_cache: dict[str, dict] = {}
        # SEG-Y path waiting for OwnedWorkerJob.released before the L0 volume
        # worker starts (survey→volume chaining, see _on_volume_job_released).
        self._pending_l0_start: str | None = None

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
    def well_identity_map(self) -> dict[str, str]:
        if self._well_identity_registry is None:
            return dict(self._persisted_well_identity_map)
        return dict(self._well_identity_registry.entries)

    @property
    def well_identity_asset_id(self) -> str | None:
        if self._well_identity_registry is None:
            return self._persisted_well_identity_asset_id
        return self._well_identity_registry.asset_id

    @property
    def engine_error(self) -> str | None:
        return self._engine_error

    def set_project(self, project: ProjectDocument | None) -> None:
        if project is self._project:
            return
        self._project = project
        # Supersede any in-flight preview load for the previous project.
        self._volume_generation += 1
        self._volume_phase = "EMPTY"
        self._source_backed_access = None
        if self._volume_job.is_running:
            self._volume_job.cancel()
        if self._scene is not None:
            # Prevent the incoming project's saved slice state from being
            # snapped against the previous project's preview cube.
            self._scene.set_volume_access(None)
        state = getattr(project, "joint_analysis", None)
        self._persisted_well_identity_asset_id = getattr(
            state, "well_identity_asset_id", None
        )
        self._persisted_well_identity_map = dict(
            getattr(state, "well_identity_map", None) or {}
        )
        self._well_identity_registry = None

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
        # A replacement project/SEGY must not reconcile saved slice times
        # against the previous preview shape while the new survey is binding.
        self._scene.set_volume_access(None)
        repo = _repo_root()
        self._paths = resolve_joint_assets(self._project, repo_root=repo)
        paths = self._paths
        if not paths.has_minimum():
            self.status_changed.emit(
                "空状态：未找到 SEGY 或井位。请在「数据」导入资产，或放置 data/ 演示目录。"
            )
            return
        if paths.segy is not None:
            # Both SEG-Y metadata scans (survey corners + volume metadata) run
            # in a background worker so the GUI thread never performs full
            # trace-header passes (C09); reloads reuse the cached payload.
            self.status_changed.emit(
                f"正在后台读取 SEG-Y 元数据… ({paths.segy.name})"
            )
            self._ensure_survey_meta(str(paths.segy))
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

        self.status_changed.emit(f"已加载井/测网（无 SEGY）· 来源={paths.source}")
        self.scene_updated.emit()

    def set_vertical_domain(self, domain: str, *, emit_scene: bool = True) -> None:
        """Set scene (3D) vertical domain: 'Time' or 'Depth' (case-insensitive prefix).

        Workbench product policy (#122): the detached 2D fence profile forces
        Time extract via FenceProfile2D.set_extract_domain — this method does
        **not** flip the 2D strip to Depth.
        """
        from geoviz import VerticalDomain, select_depth_transform

        if self._scene is None:
            return
        if str(domain).lower().startswith("depth"):
            self._scene.set_depth_transform(
                select_depth_transform(has_external_volume=False, v0_m_s=3000.0)
            )
            self._scene.set_vertical_domain(VerticalDomain.DEPTH)
            warn = self._scene.depth_transform.approximate_warning or ""
            self.status_changed.emit(f"竖直域=Depth（3D）· 2D 剖面仍 Time · {warn}")
        else:
            self._scene.set_vertical_domain(VerticalDomain.TIME)
            self.status_changed.emit("竖直域=Time")
        if emit_scene:
            self.scene_updated.emit()

    @property
    def auto_default_fence(self) -> bool:
        """Whether reload will auto-create a default well pair fence when empty."""
        return bool(getattr(self, "_auto_default_fence", True))

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

    def remove_active_fence(self) -> None:
        """Delete active fence; leave remaining fences (new active = last)."""
        if self._scene is None:
            return
        remove = getattr(self._scene, "remove_active_fence", None)
        if not callable(remove):
            self.status_changed.emit("引擎不支持删除 fence")
            return
        try:
            ok = bool(remove())
            if not ok:
                self.status_changed.emit("无活动剖面可删")
            else:
                n = len(getattr(self._scene, "fences", []) or [])
                self.status_changed.emit(f"已删 active fence · 剩余 {n}")
            self.scene_updated.emit()
        except Exception as exc:
            self.status_changed.emit(f"删除剖面失败: {exc}")

    def shutdown(self) -> None:
        self._cancel_pending_lod()
        if self._volume_job.is_running:
            self._volume_job.shutdown()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cached_survey_payload(self, segy_path: str) -> dict | None:
        """Reuse the one background scan when the file identity is unchanged."""
        try:
            from paleo_workbench.viz.seismic_volume_source import (
                get_shared_seismic_source,
            )

            source = get_shared_seismic_source(segy_path)
            return self._survey_payload_cache.get(source.source_id)
        except Exception:
            return None

    def _ensure_survey_meta(self, segy_path: str) -> None:
        """Supersede in-flight loads, then scan/cache SEG-Y metadata off-thread."""
        self._cancel_pending_lod()
        if self._volume_job.is_running:
            self._volume_job.shutdown()
        self._volume_generation += 1
        generation = self._volume_generation
        cached = self._cached_survey_payload(segy_path)
        if cached is not None:
            self._on_survey_meta_ready(cached, generation)
            return
        self._volume_phase = "META_LOADING"
        try:
            from geoviz import CancellationToken
        except Exception:  # pragma: no cover - geoviz always present
            CancellationToken = None
        token = CancellationToken() if CancellationToken is not None else None
        worker = SurveyMetaWorker(
            segy_path, generation=generation, cancellation_token=token
        )
        self._volume_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_survey_meta_ready),
                (worker.failed, self._on_survey_meta_failed),
            ),
            cancel=token.cancel if token is not None else None,
        )

    @Slot(object, int)
    def _on_survey_meta_ready(self, payload: dict, generation: int = 0) -> None:
        if self._scene is None:
            return
        if int(generation) != int(self._volume_generation):
            return
        paths = self._paths
        if paths is None or paths.segy is None:
            return
        # Cache per file identity so the next reload skips the header scans.
        try:
            self._survey_payload_cache[str(payload.get("source_id") or "")] = payload
        except Exception:
            pass
        try:
            self._apply_wells_and_survey(paths, payload)
            self._apply_tops_and_curves(paths)
            domain = self._pending_domain
            if domain is None and self._project is not None:
                state = getattr(self._project, "joint_analysis", None)
                domain = getattr(state, "vertical_domain", None) if state else None
            if domain:
                self.set_vertical_domain(domain, emit_scene=False)
        except Exception as exc:
            self.status_changed.emit(f"加载失败: {exc}")
            logger.exception("joint load failed")
            return
        self._chain_volume_start(str(paths.segy))

    @Slot(str, int)
    def _on_survey_meta_failed(self, err: str, generation: int = 0) -> None:
        if int(generation) != int(self._volume_generation):
            return
        self._volume_phase = "META_FAILED"
        self.status_changed.emit(f"SEG-Y 元数据读取失败: {err} · 回退预览体")
        self.scene_updated.emit()
        # Preserve the legacy dense-fallback behavior: still start the L0
        # preview worker, which falls back to a full dense read if needed.
        if self._paths is not None and self._paths.segy is not None:
            self._chain_volume_start(str(self._paths.segy))

    def _chain_volume_start(self, segy_path: str) -> None:
        """Start the L0 volume worker now, or on the job's released signal.

        Result slots (e.g. survey-meta finished/failed) are delivered before
        OwnedWorkerJob.released, so starting the next worker directly would
        collide with the still-live survey thread (C09 chaining race). Defer
        through the released signal — same pattern as the L1 ladder.
        """
        if self._volume_job.is_running:
            if not self._lod_release_pending:
                self._lod_release_pending = True
                self._volume_job.released.connect(self._on_volume_job_released)
            self._pending_l0_start = str(segy_path)
            return
        self._start_volume_worker(str(segy_path))

    def _apply_wells_and_survey(
        self, paths: JointAssetPaths, survey_payload: dict | None = None
    ) -> None:
        from geoviz import (
            align_horizon_corners_to_loader_axes,
            horizon_corners_from_dat,
        )

        assert self._scene is not None
        # Domain is applied by reload(preferred_domain=...) after this bind.
        self._survey_meta = {}

        if paths.segy is not None and survey_payload is not None:
            p1, p2, p3 = survey_payload["p1"], survey_payload["p2"], survey_payload["p3"]
            meta = survey_payload["corners_meta"]
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
            asset_id = paths.well_head_asset_id
            if not asset_id:
                raise RuntimeError("井位资产缺少稳定的项目资源 ID")
            registry = self._well_identity_registry
            if registry is None or registry.asset_id != asset_id:
                registry = WellIdentityRegistry.restore(
                    asset_id=asset_id,
                    persisted_asset_id=self._persisted_well_identity_asset_id,
                    entries=self._persisted_well_identity_map,
                )
            parsed = parse_well_heads(
                paths.well_head,
                identity_registry=registry,
            )
            wells = parsed.wells
            self._well_identity_registry = parsed.identity_registry
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
            # Parse TD tables once for the whole tops file, not once per line.
            td_map: dict = {}
            if paths.td_dir is not None:
                td_map = load_td_tables(paths.td_dir)
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
                if data is None:
                    continue
                wname = str(
                    getattr(data, "well_name", None)
                    or Path(las_path).stem
                )
                well_curves: dict[str, tuple] = {}
                curves_list = getattr(data, "curves", None) or []
                for c in curves_list:
                    name = str(getattr(c, "name", "") or getattr(c, "mnemonic", ""))
                    if name.upper() in {"DEPT", "DEPTH", "MD"}:
                        continue
                    depth = np.asarray(
                        getattr(c, "depth", []), dtype=float
                    )
                    vals = np.asarray(
                        getattr(c, "values", getattr(c, "data", [])),
                        dtype=float,
                    )
                    if vals.size == depth.size:
                        well_curves[name] = (depth, vals)
                if well_curves:
                    curves[wname] = well_curves
            except Exception:
                continue
        if curves:
            self._scene.set_well_curves(curves)

    def _start_volume_worker(self, segy_path: str) -> None:
        """Bind source-backed access (metadata cached from the survey pass), then L0."""
        self._cancel_pending_lod()
        if self._volume_job.is_running:
            self._volume_job.shutdown()
        self._volume_generation += 1
        generation = self._volume_generation

        # Phase 1: metadata + source-backed access. metadata() was already
        # fetched by the survey worker and is cached on the shared source, so
        # this never performs a trace-header scan on the GUI thread (C09).
        try:
            from paleo_workbench.viz.seismic_volume_source import (
                get_shared_seismic_source,
            )
            from paleo_workbench.viz.source_backed_volume_access import (
                SourceBackedVolumeAccess,
            )

            source = get_shared_seismic_source(segy_path)
            meta = source.metadata()
            access = SourceBackedVolumeAccess(source)
            self._source_backed_access = access
            if self._scene is not None:
                self._scene.set_volume_access(access)
                self._scene.set_preview_mode(True)
            self._volume_phase = "METADATA_READY"
            self.status_changed.emit(
                f"元数据就绪 {meta.shape} · 正在加载 L0 预览…"
            )
            self.scene_updated.emit()
        except Exception as exc:
            logger.exception("source-backed bind failed; fallback dense only")
            self._source_backed_access = None
            self.status_changed.emit(f"源访问失败，回退预览体: {exc}")

        # Phase 2: background L0 dense brick for GL.
        self._start_l0_worker(segy_path, generation)

    def _start_l0_worker(self, segy_path: str, generation: int) -> None:
        self._volume_phase = "L0_LOADING"
        try:
            from geoviz import CancellationToken
        except Exception:  # pragma: no cover - geoviz always present
            CancellationToken = None
        token = CancellationToken() if CancellationToken is not None else None
        worker = PreviewVolumeWorker(
            segy_path, generation=generation, lod=0, cancellation_token=token
        )
        self._volume_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_volume_ready),
                (worker.failed, self._on_volume_failed),
            ),
            cancel=token.cancel if token is not None else None,
        )

    def _maybe_start_next_lod(self, segy_path: str, current_lod: int) -> None:
        if current_lod != 0:
            return
        if self._volume_job.is_running:
            # The L0 result slot is queued BEFORE OwnedWorkerJob's queued
            # thread-finished release, so is_running is still True here even
            # though the L0 worker has finished. Defer L1 to that release
            # instead of dropping progressive refinement.
            if not self._lod_release_pending:
                self._lod_release_pending = True
                self._volume_job.released.connect(self._on_volume_job_released)
            return
        self._start_next_lod_worker(segy_path)

    def _cancel_pending_lod(self) -> None:
        if not self._lod_release_pending:
            return
        self._lod_release_pending = False
        try:
            self._volume_job.released.disconnect(self._on_volume_job_released)
        except (RuntimeError, TypeError):
            pass

    def _on_volume_job_released(self) -> None:
        self._cancel_pending_lod()
        if self._volume_job.is_running:
            return
        pending = self._pending_l0_start
        if pending is not None:
            # Survey metadata pass finished: now start the L0 volume worker.
            self._pending_l0_start = None
            self._start_volume_worker(pending)
            return
        if self._volume_phase != "L0_READY" or self._volume_job.is_running:
            return
        if self._paths is None or self._paths.segy is None:
            return
        self._start_next_lod_worker(str(self._paths.segy))

    def _start_next_lod_worker(self, segy_path: str) -> None:
        generation = self._volume_generation
        self._volume_phase = "L1_LOADING"
        self.status_changed.emit("精细化中 (L1)…")
        worker = PreviewVolumeWorker(segy_path, generation=generation, lod=1)
        self._volume_job.start(
            worker,
            terminal_signals=(worker.finished, worker.failed),
            result_connections=(
                (worker.finished, self._on_volume_ready),
                (worker.failed, self._on_volume_failed),
            ),
        )

    @Slot(object, str, int, int)
    def _on_volume_ready(
        self, volume, warning: str, generation: int = 0, lod: int = 0
    ) -> None:
        from geoviz import InMemoryVolumeAccess

        if self._scene is None:
            return
        if int(generation) != int(self._volume_generation):
            return
        if volume is None:
            self._volume_phase = "FAILED"
            self.status_changed.emit(f"预览体加载失败: {warning or 'unknown'}")
            self.scene_updated.emit()
            return

        access = self._source_backed_access
        if access is not None:
            access.set_display_data(volume, lod_level=int(lod), adopt_shape=True)
            # Re-bind same object so registration matches display shape; wells stay.
            self._scene.set_volume_access(access)
            self._scene.set_preview_mode(True)
        else:
            self._scene.set_volume_access(InMemoryVolumeAccess(volume))
            self._scene.set_preview_mode(True)

        self._volume_phase = "L0_READY" if int(lod) == 0 else f"L{int(lod)}_READY"
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
        msg = f"已加载 L{int(lod)} 预览 shape={tuple(volume.shape)} · 来源={src}"
        if warning:
            msg += f" · {warning}"
        if self._scene.fences:
            msg += f" · fences={len(self._scene.fences)}"
        self.status_changed.emit(msg)
        self.scene_updated.emit()

        if int(lod) == 0 and self._paths is not None and self._paths.segy is not None:
            try:
                self._maybe_start_next_lod(str(self._paths.segy), int(lod))
            except Exception:
                logger.debug("L1 schedule skipped", exc_info=True)

    @Slot(str, int)
    def _on_volume_failed(self, err: str, generation: int = 0) -> None:
        if int(generation) != int(self._volume_generation):
            return
        self._volume_phase = "FAILED"
        self.status_changed.emit(f"预览体加载异常: {err}")
        self.scene_updated.emit()
