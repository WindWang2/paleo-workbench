"""Batch conversion service (I14): bounded, cancellable, failure-isolated.

This is *orchestration only* — every conversion is executed by the existing
adapter/export machinery, and results that belong in the catalog go through
it. There is deliberately no workflow DAG here (that is the Harness branch's
territory); this module is a stable service such a DAG could wrap.

Guarantees:
- bounded concurrency (default 2 workers, IO-bound background lane per
  ADR 0064)
- one failing item never aborts the batch (failure isolation) and never
  corrupts another item's output (atomic writes in the export path)
- cooperative cancellation at item boundaries and inside export checkpoints
- deterministic output naming (sorted stems, collision suffixes -2, -3, ...)
- pre-flight disk estimate before any work starts
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from paleo_workbench.interchange.contracts import (
    CancelToken,
    CancelledError,
    NULL_CANCEL,
    VerificationState,
)
from paleo_workbench.interchange.executor import ExportExecutor
from paleo_workbench.interchange.path_safety import sanitize_filename
from paleo_workbench.interchange.registry import InterchangeRegistry


@dataclass
class ConversionJob:
    source: Path
    target_format: str  # adapter format_id (e.g. "geojson", "csv", "raster", "flac3d_f3grid")
    target_name: str | None = None  # optional file name; default: <stem>.<ext>
    options: dict = field(default_factory=dict)


@dataclass
class BatchItemResult:
    source: str
    target: str = ""
    status: str = "pending"  # "converted" | "failed" | "skipped" | "cancelled"
    detail: str = ""
    duration_ms: int = 0
    verification_state: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "status": self.status,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
            "verification_state": self.verification_state,
        }


@dataclass
class BatchResult:
    results: list[BatchItemResult] = field(default_factory=list)
    cancelled: bool = False
    total_duration_ms: int = 0
    estimated_disk_bytes: int = 0

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for item in self.results:
            counts[item.status] = counts.get(item.status, 0) + 1
        return {
            "total": len(self.results),
            **counts,
            "was_cancelled": self.cancelled,
            "total_duration_ms": self.total_duration_ms,
            "estimated_disk_bytes": self.estimated_disk_bytes,
        }

    def to_dict(self) -> dict:
        return {
            **self.summary(),
            "results": [r.to_dict() for r in self.results],
        }


ProgressFn = Callable[[int, int, str], None]


def _default_progress(done: int, total: int, current: str) -> None:
    return None


class BatchConversionService:
    def __init__(
        self,
        *,
        registry: InterchangeRegistry | None = None,
        max_workers: int = 2,
        catalog=None,
        project=None,
    ) -> None:
        self._registry = registry
        self._max_workers = max(1, min(int(max_workers), 4))
        self._catalog = catalog
        self._project = project

    def registry(self) -> InterchangeRegistry:
        if self._registry is None:
            from paleo_workbench.interchange.adapters import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    # -- planning -----------------------------------------------------------
    def estimate(self, jobs: list[ConversionJob], *, output_dir: Path) -> tuple[int, list[str]]:
        """Return (estimated_disk_bytes, warnings) without converting."""
        total = 0
        warnings: list[str] = []
        for job in jobs:
            adapter = self._adapter_for(job.source, job.target_format)
            if adapter is None:
                warnings.append(f"无法识别: {job.source}")
                continue
            try:
                plan = adapter.plan_export(
                    job.source,
                    self._target_path(job, output_dir),
                    options=job.options,
                )
            except Exception as exc:
                warnings.append(f"{job.source}: {exc}")
                continue
            total += plan.estimated_bytes
        return total, warnings

    # -- execution ----------------------------------------------------------
    def convert(
        self,
        jobs: list[ConversionJob],
        *,
        output_dir: Path,
        cancel: CancelToken | None = None,
        progress: ProgressFn | None = None,
        verify: bool = True,
    ) -> BatchResult:
        cancel = cancel or NULL_CANCEL
        progress = progress or _default_progress
        progress_ok = True  # a failing callback must not lose the batch result

        def safe_progress(done: int, total: int, current: str) -> None:
            nonlocal progress_ok
            if not progress_ok:
                return
            try:
                progress(done, total, current)
            except Exception:
                progress_ok = False

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        result = BatchResult()
        result.estimated_disk_bytes, _ = self.estimate(jobs, output_dir=output_dir)

        # deterministic order: sort by (source path, target name)
        ordered = sorted(jobs, key=lambda j: (str(j.source), j.target_name or ""))
        ordered = self._dedupe_targets(ordered)

        cancel.checkpoint()
        total = len(ordered)
        if total == 0:
            return result
        done = 0

        def run_one(job: ConversionJob) -> BatchItemResult:
            item = BatchItemResult(source=str(job.source))
            item_start = time.monotonic()
            cancel.checkpoint()
            try:
                adapter = self._adapter_for(job.source, job.target_format)
                if adapter is None:
                    item.status = "skipped"
                    item.detail = "无适配器或能力不可用"
                    return item
                target = self._target_path(job, output_dir)
                plan = adapter.plan_export(job.source, target, options=job.options)
                item.target = str(target)
                executor = ExportExecutor(
                    registry=self.registry(),
                    work_dir=output_dir / ".work",
                    catalog=self._catalog,
                    project=self._project,
                )
                _, verification = executor.execute(plan, cancel=cancel, verify=verify)
                item.verification_state = verification.state.value
                # Only FAILED fails the item. With verify=False the output is
                # UNVERIFIED (recorded honestly), which the caller opted into.
                if verification.state is VerificationState.FAILED:
                    item.status = "failed"
                    item.detail = verification.detail or "输出未通过校验"
                else:
                    item.status = "converted"
                    if verification.state is VerificationState.UNVERIFIED and verify:
                        item.detail = verification.detail or "输出未验证（校验器异常）"
            except CancelledError:
                item.status = "cancelled"
                raise
            except Exception as exc:
                item.status = "failed"
                item.detail = str(exc)
            finally:
                item.duration_ms = int((time.monotonic() - item_start) * 1000)
            return item

        if self._max_workers == 1 or total == 1:
            for job in ordered:
                try:
                    result.results.append(run_one(job))
                except CancelledError:
                    result.results.append(BatchItemResult(
                        source=str(job.source), status="cancelled"))
                    if cancel.cancelled:
                        result.cancelled = True
                    # a job-internal CancelledError is failure isolation, not
                    # a batch stop — only a cancelled shared token stops us
                done += 1
                safe_progress(done, total, str(job.source))
                if result.cancelled:
                    for remaining in ordered[done:]:
                        result.results.append(BatchItemResult(
                            source=str(remaining.source), status="cancelled"))
                    break
        else:
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                futures = [pool.submit(run_one, job) for job in ordered]
                for job, future in zip(ordered, futures):
                    try:
                        result.results.append(future.result())
                    except CancelledError:
                        result.results.append(BatchItemResult(
                            source=str(job.source), status="cancelled"))
                        if cancel.cancelled:
                            result.cancelled = True
                    except Exception as exc:  # defensive: isolate everything
                        result.results.append(BatchItemResult(
                            source=str(job.source), status="failed", detail=str(exc)))
                    done += 1
                    safe_progress(done, total, str(job.source))
            if cancel.cancelled:
                result.cancelled = True
                for item in result.results:
                    if item.status == "pending":
                        item.status = "cancelled"
        result.total_duration_ms = int((time.monotonic() - started) * 1000)
        # order results deterministically regardless of completion order
        result.results.sort(key=lambda r: r.source)
        return result

    # -- helpers ------------------------------------------------------------
    def _dedupe_targets(self, ordered: list[ConversionJob]) -> list[ConversionJob]:
        """Deterministic collision-free names: <stem>-2.ext, -3.ext, ..."""
        from dataclasses import replace

        used: set[str] = set()
        result: list[ConversionJob] = []
        for job in ordered:
            base = self._target_path(job, output_dir=Path("."))
            candidate = base
            counter = 1
            while candidate.name.casefold() in used:
                counter += 1
                candidate = base.with_name(f"{base.stem}-{counter}{base.suffix}")
            used.add(candidate.name.casefold())
            result.append(replace(job, target_name=candidate.name))
        return result

    def _adapter_for(self, source: Path, target_format: str):
        adapter = self.registry().get(target_format)
        if adapter is not None and adapter.capability().export:
            return adapter
        return None

    def _target_path(self, job: ConversionJob, output_dir: Path) -> Path:
        adapter = self.registry().get(job.target_format)
        extension = adapter.extensions[0] if adapter and adapter.extensions else "bin"
        if job.target_name:
            name = sanitize_filename(job.target_name)
        else:
            name = f"{Path(job.source).stem}.{extension}"
        return output_dir / name
