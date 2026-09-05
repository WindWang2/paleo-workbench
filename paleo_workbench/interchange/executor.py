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
            raise ValueError(f"计划标记为不可导入: {plan.source_path}")
        adapter = self.registry().get(plan.format_id)
        if adapter is None:
            raise ValueError(f"未知适配器: {plan.format_id}")
        cancel.checkpoint()
        progress(0.0, f"开始导入: {plan.asset_name}")
        result = adapter.import_data(
            Path(plan.source_path),
            plan,
            work_dir=self._work_directory(),
            catalog=self._catalog,
            cancel=cancel,
            progress=progress,
        )
        progress(1.0, f"导入完成: {plan.asset_name}")
        return result

    def close(self) -> None:
        if self._owns_work_dir and self._work_dir is not None:
            shutil.rmtree(self._work_dir, ignore_errors=True)
            self._work_dir = None
            self._owns_work_dir = False


class ExportExecutor:
    """Executes :class:`ExportPlan` instances: export then structural verify.

    ``UNVERIFIED`` is passed through honestly — callers and reports must never
    render it as Verified.
    """

    def __init__(self, *, registry: InterchangeRegistry | None = None, work_dir: Path | None = None) -> None:
        self._registry = registry
        self._work_dir = work_dir

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
        progress(1.0, f"导出结束: {verification.state.value}")
        return target, verification

    def _workdir(self) -> Path:
        import tempfile

        if self._work_dir is None:
            self._work_dir = Path(tempfile.mkdtemp(prefix="paleo-export-"))
        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir
