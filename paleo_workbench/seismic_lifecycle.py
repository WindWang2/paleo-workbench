"""SEG-Y import → background transcode → DERIVED DataVersion lifecycle (#1079).

Wires the production transcoder (#1077) into the data lifecycle on top of
the global scheduler (#1081) and the unified volume API (#1080):

    Import SEG-Y (RAW DataVersion, external or managed)
      └─ start_transcode(raw_version_id)   [auto on bind]
           ├─ UI keeps browsing the RAW via open_volume(segy)  (degraded path)
           ├─ scheduler task "seismic.transcode" (single IO concurrency)
           │    transcode_segy_to_zarr(src, working/store, cancel/resume-safe)
           ├─ DataRun(operation="segy-to-zarr", status running→complete)
           └─ register_derived_store → DERIVED DataVersion (parent = RAW)

Semantics required by #1079 and pinned by tests:
- cancel keeps the partial store; re-submitting the same key RESUMES (the
  transcoder probes completed shards and skips them);
- a re-transcode marks older DERIVED zarr versions ``metadata["stale"]`` —
  nothing is auto-deleted;
- trash/restore of the DERIVED version follow normal DataVersion rules
  (directory payloads move through the project trash dir).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.runtime import TaskHandle, TaskScheduler, TaskSpec

logger = logging.getLogger(__name__)

TRANSCODE_OPERATION = "segy-to-zarr"
TRANSCODE_KIND = "seismic.transcode"

# Notified as f(raw_version_id, raw_payload_path, derived_store_path) when a
# transcode completes (#1079 auto-switch: the seismic view can swap its 2-D
# browsing to the chunked store without user action).
_derived_hooks: list = []


def add_derived_hook(hook) -> None:
    """Register a callable(raw_version_id, raw_path, store_path) invoked after
    each DERIVED store registration. Exceptions in hooks are logged and
    ignored (UI conveniences must never fail the catalog write)."""
    _derived_hooks.append(hook)


def derived_store_for_path(
    catalog: DataCatalogService, segy_path: str | Path
) -> Path | None:
    """Newest non-stale DERIVED zarr store whose RAW payload is *segy_path*."""
    from pathlib import Path as _P

    target = _P(segy_path).resolve()
    try:
        version_id = catalog._index.find_external_by_path(target.as_posix())
    except Exception:
        version_id = None
    if version_id is None:
        # Managed RAW payloads resolve through the document instead.
        for v in catalog.document.versions:
            if v.stage.value == "raw" and not v.trashed and v.path:
                try:
                    if _P(catalog.resolve_path(v)).resolve() == target:
                        version_id = v.id
                        break
                except Exception:
                    continue
    if version_id is None:
        return None
    for v in catalog.document.versions:
        if (
            v.stage.value == "derived"
            and v.format == "zarr-v3"
            and version_id in v.parent_version_ids
            and not v.metadata.get("stale")
            and not v.trashed
        ):
            return Path(catalog.resolve_path(v))
    return None


@dataclass
class TranscodeJob:
    """Live state of one transcode lifecycle (UI-facing)."""

    raw_version_id: str
    store_path: Path
    handle: TaskHandle
    run_id: str


def store_work_path(catalog: DataCatalogService, raw_version_id: str) -> Path:
    """Working location for the chunked store of one RAW version."""
    project_dir = Path(catalog.project_path).expanduser().resolve().parent
    artifacts = project_dir / (Path(catalog.project_path).stem + ".artifacts")
    return artifacts / "working" / "seismic-transcode" / raw_version_id / "store"


class SeismicLifecycleService:
    """Owns transcode jobs for one open project (one instance per project)."""

    def __init__(
        self,
        catalog: DataCatalogService,
        scheduler: TaskScheduler | None = None,
    ):
        self._catalog = catalog
        from paleo_workbench.runtime import get_scheduler

        self._scheduler = scheduler or get_scheduler()
        self._jobs: dict[str, TranscodeJob] = {}  # raw_version_id -> job

    # ------------------------------------------------------------- status --
    def job_for(self, raw_version_id: str) -> TranscodeJob | None:
        return self._jobs.get(raw_version_id)

    def status(self, raw_version_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(raw_version_id)
        if job is None:
            return None
        h = self._scheduler.handle(job.handle.task_id)
        if h is None:
            return {"state": "unknown"}
        return {
            "state": h.state.value,
            "progress": h.progress,
            "message": h.message,
            "error": h.error,
            "run_id": job.run_id,
            "store_path": str(job.store_path),
        }

    # -------------------------------------------------------------- start --
    def start_transcode(
        self,
        raw_version_id: str,
        *,
        params: Any = None,
        workers: int | None = None,
        auto_started: bool = False,
    ) -> TranscodeJob:
        """Queue the background transcode of one RAW SEG-Y version.

        Idempotent per RAW version: an active job returns as-is. The task
        itself resumes from partial stores (transcoder shard probing).
        """
        existing = self._jobs.get(raw_version_id)
        if existing is not None:
            h = self._scheduler.handle(existing.handle.task_id)
            if h is not None and h.state.value in ("queued", "running"):
                return existing
        catalog = self._catalog
        version = catalog.get_version(raw_version_id)
        src = Path(catalog.resolve_path(version))
        if not src.is_file():
            raise FileNotFoundError(
                f"RAW payload for {raw_version_id} not found: {src}"
            )
        store = store_work_path(catalog, raw_version_id)

        run = catalog.register_run(
            TRANSCODE_OPERATION,
            input_version_ids=[raw_version_id],
            parameters={
                "source": src.name,
                "store": str(store),
                "auto_started": auto_started,
            },
            generator="paleo_workbench.seismic_lifecycle",
            status="running",
        )

        def task(ctx):
            from paleo_workbench.seismic_transcode import (
                default_workers,
                transcode_segy_to_zarr,
            )

            store.parent.mkdir(parents=True, exist_ok=True)
            result = transcode_segy_to_zarr(
                src,
                store,
                **({"params": params} if params is not None else {}),
                workers=workers if workers is not None else default_workers(),
                progress=lambda done: ctx.report_progress(done),
                cancel=lambda: ctx.cancelled.is_set(),
            )
            ctx.check_cancelled()
            return {
                "shape": list(result.shape),
                "shards_written": result.stats.shards_written,
                "shards_skipped": result.stats.shards_skipped,
                "throughput_mb_s": result.stats.throughput_mb_s,
            }

        def on_done(stats):
            if stats is not None:
                self._register_derived(raw_version_id, run.id, store, stats)

        def on_fail(exc):
            self._finish_run(run.id, "failed", error=f"{type(exc).__name__}: {exc}")

        def on_cancel():
            self._finish_run(run.id, "cancelled")

        handle = self._scheduler.submit(
            TaskSpec(
                callable=task,
                kind=TRANSCODE_KIND,
                title=f"SEG-Y → Zarr ({raw_version_id})",
                task_key=f"transcode/{raw_version_id}",
                payload={
                    # P2-A: admission estimates for the governor. Transcode
                    # is sequential streaming IO: 1 core of orchestration,
                    # in-flight window bounded by the streaming buffer.
                    "resources": {
                        "estimated_cpu_cores": 1.0,
                        "io_weight": 4.0,
                    }
                },
                on_done=on_done,
                on_fail=on_fail,
                on_cancel=on_cancel,
            )
        )
        job = TranscodeJob(
            raw_version_id=raw_version_id,
            store_path=store,
            handle=handle,
            run_id=run.id,
        )
        self._jobs[raw_version_id] = job
        return job

    # ---------------------------------------------------------- completion --
    def _register_derived(
        self, raw_version_id: str, run_id: str, store: Path, stats: dict
    ) -> None:
        catalog = self._catalog
        self.mark_stale(raw_version_id, reason="re-transcoded")
        version = catalog.register_derived_store(
            name=f"seismic store from {Path(store).name}",
            store_path=store,
            run_id=run_id,
            parent_version_ids=[raw_version_id],
            type="seismic",
            format="zarr-v3",
            version_metadata={
                "source_version_id": raw_version_id,
                "operation": TRANSCODE_OPERATION,
                "shape": stats.get("shape"),
                "throughput_mb_s": stats.get("throughput_mb_s"),
            },
        )
        self._finish_run(
            run_id, "complete", extra={"derived_version_id": version.id}
        )
        logger.info(
            "transcode %s -> derived version %s complete", raw_version_id, version.id
        )
        raw_path = None
        try:
            raw_path = str(catalog.resolve_path(catalog.get_version(raw_version_id)))
        except Exception:
            pass
        for hook in list(_derived_hooks):
            try:
                hook(raw_version_id, raw_path, str(catalog.resolve_path(version)))
            except Exception:
                logger.exception("derived hook failed for %s", raw_version_id)

    def _finish_run(
        self, run_id: str, status: str, *, error: str | None = None, extra: dict | None = None
    ) -> None:
        parameters = dict(extra or {})
        if error:
            parameters["error"] = error
        try:
            self._catalog.update_run_status(run_id, status, extra_parameters=parameters)
        except Exception:
            logger.exception("could not mark transcode run %s %s", run_id, status)

    # --------------------------------------------------------------- stale --
    def mark_stale(self, raw_version_id: str, reason: str) -> int:
        """Flag existing DERIVED zarr versions produced from this RAW as
        stale (kept for lineage; never auto-deleted)."""
        catalog = self._catalog
        marked = 0
        with catalog._lock:
            dirty = []
            for v in catalog.document.versions:
                if (
                    v.stage.value == "derived"
                    and v.format == "zarr-v3"
                    and raw_version_id in v.parent_version_ids
                    and not v.metadata.get("stale")
                ):
                    v.metadata["stale"] = True
                    v.metadata["stale_reason"] = reason
                    dirty.append(v.id)
                    marked += 1
            if marked:
                from paleo_workbench.catalog.db import DirtySet

                catalog._save(DirtySet(versions={vid: None for vid in dirty}))
        return marked

    # -------------------------------------------------------- derived find --
    def derived_version_for(self, raw_version_id: str):
        """Newest non-stale, non-trashed DERIVED zarr version for a RAW."""
        best = None
        for v in self._catalog.document.versions:
            if (
                v.stage.value == "derived"
                and v.format == "zarr-v3"
                and raw_version_id in v.parent_version_ids
                and not v.metadata.get("stale")
                and not v.trashed
            ):
                if best is None or (v.created_at or "") > (best.created_at or ""):
                    best = v
        return best

    def derived_store_path(self, raw_version_id: str) -> Path | None:
        v = self.derived_version_for(raw_version_id)
        if v is None:
            return None
        return Path(self._catalog.resolve_path(v))

    # -------------------------------------------------------------- resume --
    def resume_pending(self) -> int:
        """Re-queue transcodes whose DataRun stayed 'running' (crash/close).

        Called on project open; completed stores skip instantly via shard
        probing, then register their DERIVED version.
        """
        catalog = self._catalog
        resumed = 0
        for run in list(catalog.document.runs):
            if (
                run.operation == TRANSCODE_OPERATION
                and (run.status or "").lower() == "running"
            ):
                for vid in list(run.input_version_ids):
                    try:
                        version = catalog.get_version(vid)
                    except Exception:
                        continue
                    if version.trashed:
                        continue
                    # #1192: a complete non-stale DERIVED means the crash hit
                    # the "store moved, run not yet complete" window — adopt
                    # it instead of re-transcoding (and never stale-mark it).
                    if self._adopt_complete_derived(run.id, vid):
                        continue
                    # close the orphaned run's bookkeeping; the resumed task
                    # finishes with a fresh run
                    self._finish_run(run.id, "cancelled")
                    self.start_transcode(vid)
                    resumed += 1
        return resumed

    def _adopt_complete_derived(self, run_id: str, raw_version_id: str) -> bool:
        """Adopt an intact DERIVED store for an orphaned running run.

        Returns True when adoption happened (caller must not re-transcode):
        the orphaned run is closed as cancelled and the existing DERIVED
        registration stands untouched.
        """
        import json

        try:
            derived = self.derived_version_for(raw_version_id)
            if derived is None:
                return False
            store = self.derived_store_path(raw_version_id)
            if store is None:
                return False
            meta_path = store / "zarr.json"
            meta = json.loads(meta_path.read_text())
            if not isinstance(meta.get("shape"), list) or not meta["shape"]:
                return False
        except Exception:
            return False
        self._finish_run(run_id, "cancelled")
        return True

    # ------------------------------------------------------------- teardown --
    def shutdown_jobs(self) -> None:
        """Cancel still-active transcode tasks (project closing)."""
        for job in list(self._jobs.values()):
            try:
                self._scheduler.cancel(job.handle.task_id)
            except Exception:
                logger.exception("could not cancel transcode job %s", job.raw_version_id)


# ----------------------------------------------------- project-level registry

# One lifecycle service per open project; keyed by resolved project path so
# reopening the same project reuses it and closing tears it down.
_ACTIVE: dict[str, SeismicLifecycleService] = {}


def lifecycle_key(catalog: DataCatalogService) -> str:
    return str(Path(catalog.project_path).expanduser().resolve())


def get_lifecycle_service(catalog: DataCatalogService) -> SeismicLifecycleService:
    key = lifecycle_key(catalog)
    svc = _ACTIVE.get(key)
    if svc is None:
        svc = SeismicLifecycleService(catalog)
        _ACTIVE[key] = svc
        try:
            svc.resume_pending()
        except Exception:
            logger.exception("transcode resume on open failed for %s", key)
    return svc


def shutdown_lifecycle(catalog: DataCatalogService) -> None:
    svc = _ACTIVE.pop(lifecycle_key(catalog), None)
    if svc is not None:
        svc.shutdown_jobs()


def start_attribute_job(
    catalog: DataCatalogService,
    source_version_id: str,
    attribute: str = "c3",
    *,
    scheduler: TaskScheduler | None = None,
) -> TaskHandle:
    """Queue a full-volume attribute job (#1084) over a chunked DERIVED store.

    ``source_version_id`` must resolve to a zarr-v3 store (a transcode
    output). The job streams inline bands through the SAME kernel as ROI
    (#1083) into a fresh attribute store, then registers it as a DERIVED
    DataVersion under DataRun(operation="attribute:<name>"). Resumable:
    completed bands carry marker files and are skipped on re-run.
    """
    from geoviz_seismic import open_volume as _open_volume
    from paleo_workbench.runtime import get_scheduler
    from paleo_workbench.seismic_attributes import VolumeAttributeJob

    sched = scheduler or get_scheduler()
    version = catalog.get_version(source_version_id)
    src_store = Path(catalog.resolve_path(version))
    if not src_store.is_dir():
        raise FileNotFoundError(
            f"attribute source must be a chunked store directory: {src_store}"
        )
    life = get_lifecycle_service(catalog)
    work_root = src_store.parent / f"{src_store.name}.attr-{attribute}"
    reader = _open_volume(src_store)
    job = VolumeAttributeJob(reader, work_root, attribute)

    run = catalog.register_run(
        f"attribute:{attribute}",
        input_version_ids=[source_version_id],
        parameters={"source_store": str(src_store), "attribute": attribute},
        generator="paleo_workbench.seismic_attributes",
        status="running",
    )

    def on_done(stats):
        if stats is None:
            return
        derived = catalog.register_derived_store(
            name=f"{attribute} attribute volume",
            store_path=work_root,
            run_id=run.id,
            parent_version_ids=[source_version_id],
            type="seismic-attribute",
            format="zarr-v3",
            version_metadata={
                "attribute": attribute,
                "source_version_id": source_version_id,
                "shape": stats.get("bands") and list(reader.shape),
            },
        )
        try:
            catalog.update_run_status(
                run.id, "complete", extra_parameters={"derived_version_id": derived.id}
            )
        except Exception:
            logger.exception("attribute run status update failed")
        for hook in list(_derived_hooks):
            try:
                hook(source_version_id, str(src_store), str(catalog.resolve_path(derived)))
            except Exception:
                logger.exception("derived hook failed for attribute %s", attribute)

    def on_fail(exc):
        try:
            catalog.update_run_status(
                run.id, "failed", extra_parameters={"error": f"{type(exc).__name__}: {exc}"}
            )
        except Exception:
            logger.exception("attribute run status update failed")

    def on_cancel():
        try:
            catalog.update_run_status(run.id, "cancelled")
        except Exception:
            logger.exception("attribute run status update failed")

    return sched.submit(
        TaskSpec(
            callable=job.run,
            kind="seismic.attribute",
            title=f"{attribute} full-volume ({source_version_id})",
            task_key=f"attribute/{attribute}/{source_version_id}",
            payload={
                # P2-A: banded attribute jobs are compute-bound with one
                # banded IO stream per band group.
                "resources": {
                    "estimated_cpu_cores": 2.0,
                    "io_weight": 1.0,
                }
            },
            on_done=on_done,
            on_fail=on_fail,
            on_cancel=on_cancel,
        )
    )


def autostart_for_staged(
    staged_items: list[Any],
    asset_id_by_legacy: dict[str, str],
    catalog: DataCatalogService,
) -> list[TranscodeJob]:
    """Auto-start background transcodes for freshly bound SEG-Y surveys
    (#1079: import → background transcode, UI keeps the RAW fallback path).

    ``staged_items`` are :class:`StagedResource` objects whose ``survey`` is
    set; ``asset_id_by_legacy`` maps their resource ids to catalog assets.
    """
    jobs: list[TranscodeJob] = []
    if not staged_items:
        return jobs
    svc = get_lifecycle_service(catalog)
    maps = catalog._ensure_maps()
    for item in staged_items:
        survey = getattr(item, "survey", None)
        if survey is None:
            continue
        asset_id = asset_id_by_legacy.get(getattr(item, "resource_id", ""))
        asset = maps.asset_by_id.get(asset_id) if asset_id else None
        version_id = asset.current_version_id if asset else None
        if version_id is None:
            continue
        try:
            jobs.append(svc.start_transcode(version_id, auto_started=True))
        except Exception:
            logger.exception(
                "auto transcode failed to start for asset %s", asset_id
            )
    return jobs
