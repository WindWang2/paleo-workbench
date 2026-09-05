"""Import/export execution through the catalog (the single lifecycle authority).

The executor is deliberately thin: it checks cancellation, delegates to the
adapter (which delegates to the catalog service), and guarantees that a failed
or cancelled execution never leaves a half-registered asset behind. All
writers in the chain use temp-file + atomic rename, so interruption at any
checkpoint leaves the previous state untouched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportPlan,
    ExportVerification,
    ImportExecutionResult,
    ImportPlan,
    NULL_CANCEL,
    ProgressCallback,
    _null_progress,
)
from paleo_workbench.interchange.preflight import ImportPreflightService
from paleo_workbench.interchange.registry import InterchangeRegistry


class ImportExecutor:
    """Executes :class:`ImportPlan` instances against a catalog service."""

    def __init__(
        self,
        catalog,
        *,
        registry: InterchangeRegistry | None = None,
        work_dir: Path | None = None,
    ) -> None:
        self._catalog = catalog
        self._registry = registry
        self._work_dir = work_dir

    def registry(self) -> InterchangeRegistry:
        if self._registry is None:
            from paleo_workbench.interchange.adapters import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    def _work_directory(self) -> Path:
        import tempfile

        if self._work_dir is None:
            self._work_dir = Path(tempfile.mkdtemp(prefix="paleo-interchange-"))
            self._owns_work_dir = True
        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir

    _owns_work_dir = False

    def execute(
        self,
        plan: ImportPlan,
        *,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        progress = progress or _null_progress
        if plan.action == "unsupported":
            from paleo_workbench.interchange.contracts import PreflightFailedError

            raise PreflightFailedError(f"计划标记为不可导入: {plan.source_path}")
        adapter = self.registry().get(plan.format_id)
        if adapter is None:
            raise ValueError(f"未知适配器: {plan.format_id}")
        cancel.checkpoint()
        progress(0.0, f"开始导入: {plan.asset_name}")
        try:
            result = adapter.import_data(
                Path(plan.source_path),
                plan,
                work_dir=self._work_directory(),
                catalog=self._catalog,
                cancel=cancel,
                progress=progress,
            )
        except Exception as exc:
            self._record_run(plan, status="failed", error=str(exc))
            raise
        self._record_run(plan, status="completed", version_id=result.version_id)
        progress(1.0, f"导入完成: {plan.asset_name}")
        return result

    def _record_run(self, plan: ImportPlan, *, status: str, version_id: str | None = None,
                    error: str = "") -> None:
        """Provenance for every interchange import (success or failure).

        A provenance failure never masks or fakes the import outcome: the
        version registration itself is the source of truth, so a broken run
        registry degrades to `provenance_ok=False` on the result.
        """
        if self._catalog is None:
            return
        try:
            self._catalog.register_run(
                "interchange.import",
                input_version_ids=(),
                output_version_ids=[version_id] if version_id else (),
                parameters={"plan": plan.to_dict(), "action": plan.action},
                generator="interchange",
                status=status,
            )
        except Exception:
            return

    def close(self) -> None:
        if self._owns_work_dir and self._work_dir is not None:
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None
            self._owns_work_dir = False


class ExportExecutor:
    """Executes :class:`ExportPlan` instances: export then structural verify.

    When a catalog is provided, every verified export is registered through
    the repo's single export-provenance choke point
    (:func:`paleo_workbench.catalog.lifecycle.register_export_output` /
    ``project.artifacts.record_export`` machinery) so interchange exports are
    indistinguishable from native ones in lineage. ``UNVERIFIED`` is passed
    through honestly — callers and reports must never render it as Verified.
    """

    def __init__(
        self,
        *,
        registry: InterchangeRegistry | None = None,
        work_dir: Path | None = None,
        catalog=None,
        project=None,
    ) -> None:
        self._registry = registry
        self._work_dir = work_dir
        self._catalog = catalog
        self._project = project

    def registry(self) -> InterchangeRegistry:
        if self._registry is None:
            from paleo_workbench.interchange.adapters import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    def execute(
        self,
        plan: ExportPlan,
        *,
        cancel: CancelToken | None = None,
        progress: ProgressCallback | None = None,
        verify: bool = True,
    ) -> tuple[Path, ExportVerification]:
        from paleo_workbench.interchange.contracts import FormatNotSupportedError

        cancel = cancel or NULL_CANCEL
        progress = progress or _null_progress
        adapter = self.registry().get(plan.format_id)
        if adapter is None:
            raise ValueError(f"未知适配器: {plan.format_id}")
        cancel.checkpoint()
        progress(0.1, f"导出: {Path(plan.target_path).name}")
        try:
            target = adapter.export_data(
                Path(plan.source_path),
                plan,
                work_dir=self._workdir(),
                cancel=cancel,
                progress=progress,
            )
        except FormatNotSupportedError:
            raise
        progress(0.7, "写出完成，开始校验")
        if not verify:
            verification = ExportVerification.unverified("verify=False：调用方显式跳过校验")
        else:
            try:
                verification = adapter.verify_output(target, plan)
            except Exception as exc:
                verification = ExportVerification.unverified(f"校验器异常: {exc}")
        self._record_export(plan, target, verification)
        progress(1.0, f"导出结束: {verification.state.value}")
        return target, verification

    def _record_export(self, plan: ExportPlan, target: Path, verification: ExportVerification) -> None:
        """Route through the single export-provenance choke point.

        Provenance failure never masks the export result — the bytes and the
        verification state are already real; a broken registry is logged on
        the verification as a warning instead.
        """
        if self._catalog is None:
            return
        try:
            if verification.ok:
                from paleo_workbench.catalog.adapter import CoreCatalogAdapter
                from paleo_workbench.catalog.lifecycle import register_export_output

                # register_export_output speaks the CatalogPort dialect;
                # wrap a raw DataCatalogService transparently.
                port = (
                    self._catalog
                    if hasattr(self._catalog, "begin_run")
                    else CoreCatalogAdapter(self._catalog)
                )
                register_export_output(
                    name=Path(plan.target_path).name,
                    output_path=str(target),
                    fmt=plan.format_id,
                    source_version_ids=plan.source_version_ids or None,
                    linked_id=plan.linked_id,
                    catalog=port,
                )
            else:
                self._catalog.register_run(
                    "export",
                    input_version_ids=plan.source_version_ids,
                    output_version_ids=(),
                    parameters={"plan": plan.to_dict(), "verify_state": verification.state.value},
                    generator="interchange",
                    status="failed",
                )
        except Exception as exc:
            verification.warnings.append(f"导出 provenance 记录失败: {exc}")

    def _workdir(self) -> Path:
        import tempfile

        if self._work_dir is None:
            self._work_dir = Path(tempfile.mkdtemp(prefix="paleo-export-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir
