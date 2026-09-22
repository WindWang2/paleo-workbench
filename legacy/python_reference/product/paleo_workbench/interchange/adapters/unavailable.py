"""Capability-unavailable adapters: formats the repo genuinely cannot serve.

Each declares exactly what is missing so the registry/preflight can report an
honest, actionable answer ("需要 dlisio 依赖" / "无 VTK 读取器") instead of a
silent misclassification or a half-working parser. They never parse.
"""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.interchange.contracts import (
    ExportVerification,
    FormatCapability,
    FormatNotSupportedError,
    InspectionResult,
)
from paleo_workbench.interchange.registry import FormatAdapter


class UnavailableAdapter(FormatAdapter):
    """Base for formats with no reliable dependency/implementation available."""

    unavailable_reason = "不支持"
    resource_type = "unknown"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=False,
            inspect=False,
            import_data=False,
            export=False,
            notes=self.unavailable_reason,
        )

    def inspect(self, path: Path) -> InspectionResult:
        result = InspectionResult(format_id=self.format_id, ok=False, object_type=self.resource_type)
        try:
            result.size_bytes = Path(path).stat().st_size
        except OSError:
            result.size_bytes = 0
        result.errors.append(self.unavailable_reason)
        return result

    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(path, inspection, managed=managed, asset_name=asset_name, options=options)
        plan.action = "unsupported"
        plan.warnings.append(self.unavailable_reason)
        return plan

    def plan_export(self, source_path, target_path, *, options=None):
        raise FormatNotSupportedError(self.unavailable_reason)

    def verify_output(self, target_path, plan) -> ExportVerification:
        return ExportVerification.unverified(self.unavailable_reason)


class DlisAdapter(UnavailableAdapter):
    format_id = "dlis"
    display_name = "DLIS 测井（不可用）"
    extensions = ("dlis", "lis")
    resource_type = "well_log"
    unavailable_reason = (
        "DLIS/LIS 暂不可用：well-log-engine 的 C++ 适配器未暴露 Python 绑定，"
        "且环境无 dlisio 依赖；请先转换 LAS 或等待绑定发布"
    )


class VtkModelAdapter(UnavailableAdapter):
    format_id = "vtk_model"
    display_name = "VTK 模型（不可用）"
    extensions = ("vtk", "vtu", "vtp")
    resource_type = "model"
    unavailable_reason = "VTK 家族暂不可用：仓库无 VTK 读取器/写出器"


class MeshExchangeAdapter(UnavailableAdapter):
    format_id = "mesh_exchange"
    display_name = "OBJ/STL 网格（不可用）"
    extensions = ("obj", "stl")
    resource_type = "model"
    unavailable_reason = "OBJ/STL 暂不可用：仓库无对应读取器/写出器"
