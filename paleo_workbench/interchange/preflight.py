"""Unified import preflight: inspect -> report -> plan.

Preflight is strictly read-only. A failed preflight never creates catalog
assets — the executor only runs on a plan that passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.interchange.contracts import (
    ImportPlan,
    InspectionResult,
    SniffResult,
)
from paleo_workbench.interchange.registry import InterchangeRegistry, sniff_format


@dataclass(frozen=True)
class PreflightIssue:
    severity: str  # "info" | "warning" | "error"
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass
class PreflightReport:
    path: str
    sniff: SniffResult
    adapter_id: str | None
    inspection: InspectionResult | None
    issues: list[PreflightIssue] = field(default_factory=list)
    recommendation: str = "unavailable"  # managed_copy | link_external | unavailable
    estimated_disk_bytes: int = 0

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sniff": {
                "format_id": self.sniff.format_id,
                "confidence": self.sniff.confidence,
                "evidence": self.sniff.evidence,
            },
            "adapter_id": self.adapter_id,
            "inspection": self.inspection.summary() if self.inspection else None,
            "issues": [issue.to_dict() for issue in self.issues],
            "recommendation": self.recommendation,
            "estimated_disk_bytes": self.estimated_disk_bytes,
            "ok": self.ok,
        }


class ImportPreflightService:
    """Detect the real format of a source file and describe what an import
    would do, without touching the project."""

    def __init__(self, registry: InterchangeRegistry | None = None) -> None:
        self._registry = registry

    def registry(self) -> InterchangeRegistry:
        if self._registry is None:
            from paleo_workbench.interchange.adapters import build_default_registry

            self._registry = build_default_registry()
        return self._registry

    def inspect(self, path: Path) -> PreflightReport:
        path = Path(path)
        issues: list[PreflightIssue] = []
        if not path.exists():
            return PreflightReport(
                path=str(path),
                sniff=SniffResult("", "low", "missing-file", path.suffix.lower().lstrip(".")),
                adapter_id=None,
                inspection=None,
                issues=[PreflightIssue("error", "missing-file", "文件不存在")],
            )
        if path.is_dir():
            return PreflightReport(
                path=str(path),
                sniff=SniffResult("", "low", "directory", ""),
                adapter_id=None,
                inspection=None,
                issues=[PreflightIssue("error", "directory", "目录导入请使用批量服务")],
            )

        sniff = sniff_format(path, self.registry())
        extension = path.suffix.lower().lstrip(".")
        adapter = self.registry().get(sniff.format_id) if sniff.determined else None
        if adapter is None:
            adapter = self.registry().adapter_for_extension(path)
            if adapter is not None and sniff.determined and sniff.format_id != adapter.format_id:
                issues.append(
                    PreflightIssue(
                        "error",
                        "extension-content-mismatch",
                        f"扩展名 .{extension} 指向 {adapter.format_id}，但内容嗅探为 "
                        f"{sniff.format_id}（{sniff.evidence}）",
                    )
                )
                adapter = None
            elif adapter is not None and sniff.determined:
                issues.append(
                    PreflightIssue(
                        "info",
                        "sniff-confirmed",
                        f"内容嗅探确认格式 {sniff.format_id}（{sniff.evidence}）",
                    )
                )
        elif extension and extension not in adapter.extensions:
            issues.append(
                PreflightIssue(
                    "warning",
                    "extension-mismatch",
                    f"内容识别为 {sniff.format_id}，但扩展名为 .{extension}",
                )
            )

        if adapter is None:
            issues.append(
                PreflightIssue(
                    "error",
                    "format-unknown",
                    "无法识别格式（无内容特征且扩展名未注册）",
                )
            )
            return PreflightReport(
                path=str(path),
                sniff=sniff,
                adapter_id=None,
                inspection=None,
                issues=issues,
                recommendation="unavailable",
            )

        inspection = adapter.inspect(path)
        for error in inspection.errors:
            issues.append(PreflightIssue("error", "inspect-error", error))
        for warning in inspection.warnings:
            issues.append(PreflightIssue("warning", "inspect-warning", warning))

        capability = adapter.capability()
        if not capability.import_data:
            issues.append(
                PreflightIssue(
                    "error",
                    "import-unavailable",
                    capability.notes or f"{adapter.format_id} 不支持导入",
                )
            )
            recommendation = "unavailable"
        elif not inspection.ok:
            recommendation = "unavailable"
        else:
            recommendation = "managed_copy"
        estimated = inspection.size_bytes if inspection.ok else 0
        return PreflightReport(
            path=str(path),
            sniff=sniff,
            adapter_id=adapter.format_id,
            inspection=inspection,
            issues=issues,
            recommendation=recommendation,
            estimated_disk_bytes=estimated,
        )

    def plan(
        self,
        path: Path,
        *,
        managed: bool | None = None,
        asset_name: str | None = None,
        options: dict | None = None,
    ) -> ImportPlan:
        """Build an executable plan; raises PreflightFailedError when the
        report has errors (callers get a plan or an exception, never both)."""
        from paleo_workbench.interchange.contracts import PreflightFailedError

        path = Path(path)
        report = self.inspect(path)
        if not report.ok or report.adapter_id is None or report.inspection is None:
            errors = [i.message for i in report.issues if i.severity == "error"]
            raise PreflightFailedError(
                "；".join(errors) or "preflight 未通过，无法生成导入计划"
            )
        adapter = self.registry().get(report.adapter_id)
        assert adapter is not None  # report.adapter_id implies registration
        managed_effective = managed if managed is not None else True
        return adapter.plan_import(
            path,
            report.inspection,
            managed=managed_effective,
            asset_name=asset_name,
            options=options,
        )
