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
                    # close the orphaned run's bookkeeping; the resumed task
                    # finishes with a fresh run
                    self._finish_run(run.id, "cancelled")
                    self.start_transcode(vid)
                    resumed += 1
        return resumed

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
