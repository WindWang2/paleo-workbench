"""SEG-Y interchange adapter (small/medium volumes only).

This branch explicitly does NOT handle 100GB seismic bodies. The adapter
covers: bounded header inspection (segyio, ignore-geometry + optional
geometry probe), managed/external import recommendations driven by a size
threshold, content fingerprinting, and ROI/window semantics that defer to the
existing transcode/chunked-reader pipeline (`seismic_transcode.py`,
`geoviz_seismic.chunked`) — those are never duplicated here.

There is no SEG-Y *writer* in this repository; export capability is declared
unavailable rather than faked. Derived seismic products are zarr-v3 stores
produced by the existing transcode service (ADR 0061/0062).
"""

from __future__ import annotations

import math
from pathlib import Path

from paleo_workbench.interchange.contracts import (
    CancelToken,
    ExportVerification,
    FormatCapability,
    FormatNotSupportedError,
    ImportExecutionResult,
    ImportPlan,
    InspectionResult,
    NULL_CANCEL,
    VerificationCheck,
    VerificationState,
)
from paleo_workbench.interchange.registry import FormatAdapter

# Managed copy is only recommended below this size; bigger sources should be
# linked externally and ingested through the transcode pipeline.
MANAGED_COPY_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
# Full trace-header geometry probe budget (trace headers only, 240B each).
_GEOMETRY_PROBE_MAX_TRACES = 200_000
_FINGERPRINT_MAX_BYTES = 1024 * 1024 * 1024


def segyio_available() -> bool:
    try:
        import segyio  # noqa: F401
    except Exception:
        return False
    return True


class SegyAdapter(FormatAdapter):
    format_id = "segy"
    display_name = "SEG-Y 地震数据（中小体）"
    extensions = ("sgy", "segy")
    resource_type = "seismic"

    def capability(self) -> FormatCapability:
        return FormatCapability(
            read=True,
            inspect=True,
            import_data=True,
            export=False,
            roundtrip_verify=False,
            notes=(
                "本仓库无 SEG-Y 写出器：导出不可用；派生数据走既有 zarr-v3 转码管线；"
                "100GB 级数据不在本适配器范围"
            ),
        )

    def inspect(self, path: Path) -> InspectionResult:
        path = Path(path)
        result = InspectionResult(format_id=self.format_id, object_type=self.resource_type)
        try:
            result.size_bytes = path.stat().st_size
        except OSError as exc:
            result.ok = False
            result.errors.append(f"无法读取文件状态: {exc}")
            return result
        if result.size_bytes < 3600:
            result.ok = False
            result.errors.append("文件小于 SEG-Y 最小头长度（3600 字节），可能截断")
            return result
        if not segyio_available():
            result.ok = False
            result.errors.append("segyio 不可用，无法解析 SEG-Y")
            return result

        import segyio

        try:
            with segyio.open(str(path), "r", ignore_geometry=True) as segy:
                trace_count = segy.tracecount
                sample_count = len(segy.samples)
                sample_interval_us = int(segy.bin[segyio.BinField.Interval])
                format_code = int(segy.bin[segyio.BinField.Format])
                try:
                    # segyio's Text materializes lazily; str() is the only API
                    # on this version (locally silenced deprecation notice).
                    import warnings as _warnings

                    with _warnings.catch_warnings():
                        _warnings.filterwarnings("ignore", category=DeprecationWarning)
                        text_header = str(segy.text)
                except Exception:
                    text_header = ""
                first = segy.header[0]
                il_first = int(first.get(segyio.TraceField.INLINE_3D, 0))
                xl_first = int(first.get(segyio.TraceField.CROSSLINE_3D, 0))
                # Bounded geometry probe: header reads at spread indices.
                probe_indices = self._probe_indices(trace_count)
                il_values = []
                xl_values = []
                for index in probe_indices:
                    header = segy.header[index]
                    il_values.append(int(header.get(segyio.TraceField.INLINE_3D, 0)))
                    xl_values.append(int(header.get(segyio.TraceField.CROSSLINE_3D, 0)))
                samples_axis = segy.samples
        except Exception as exc:
            result.ok = False
            result.errors.append(f"SEG-Y 解析失败: {exc}")
            return result

        result.metadata = {
            "trace_count": trace_count,
            "sample_count": sample_count,
            "sample_interval_us": sample_interval_us,
            "format_code": format_code,
            "inline_3d_first": il_first,
            "crossline_3d_first": xl_first,
            "geometry_probe": {
                "traces_probed": len(probe_indices),
                "inline_values": il_values,
                "crossline_values": xl_values,
                "inline_varies": len(set(il_values)) > 1,
                "crossline_varies": len(set(xl_values)) > 1,
            },
            "axis_first": float(samples_axis[0]) if sample_count else None,
            "axis_last": float(samples_axis[-1]) if sample_count else None,
            "text_header_preview": text_header[:320],
        }
        # segyio's segy.samples axis stores microseconds — keep the unit label
        # consistent with the stored values (consumers convert for display).
        result.units["twt"] = "us"
        if il_first == 0 and xl_first == 0:
            result.warnings.append("首道 INLINE_3D/CROSSLINE_3D 均为 0：几何信息可能不完整")
        elif not result.metadata["geometry_probe"]["inline_varies"]:
            result.warnings.append("探测范围内 INLINE_3D 无变化：几何完整性存疑")
        estimated_minutes = result.size_bytes / max(1.0, 50 * 1024 * 1024)
        if estimated_minutes > 5:
            result.warnings.append(
                "大体积 SEG-Y：建议通过既有 zarr-v3 转码管线入库而非直接管理拷贝"
            )
        return result

    @staticmethod
    def _probe_indices(trace_count: int) -> list[int]:
        if trace_count <= 0:
            return []
        if trace_count <= 8:
            return list(range(trace_count))
        budget = min(trace_count, _GEOMETRY_PROBE_MAX_TRACES)
        step = max(1, trace_count // min(budget, 64))
        return list(range(0, trace_count, step))[:64]

    def plan_import(self, path, inspection, *, managed=True, asset_name=None, options=None):
        plan = super().plan_import(
            path, inspection, managed=managed, asset_name=asset_name, options=options
        )
        plan.metadata.setdefault("object_type", self.resource_type)
        if inspection.ok:
            if inspection.size_bytes > MANAGED_COPY_MAX_BYTES:
                plan.action = "link_external"
                plan.warnings.append(
                    f"源超过 {MANAGED_COPY_MAX_BYTES // (1024 * 1024)} MiB：建议外部引用 + 既有 zarr-v3 转码管线"
                )
        return plan

    def fingerprint(self, path: Path) -> dict:
        """Streaming content fingerprint within the bounded-size budget."""
        path = Path(path)
        try:
            size = path.stat().st_size
            mtime = path.stat().st_mtime
        except OSError as exc:
            return {"error": str(exc)}
        if size > _FINGERPRINT_MAX_BYTES:
            return {"size_bytes": size, "mtime": mtime, "hash": None,
                    "note": "超过指纹预算：仅记录 size+mtime"}
        from paleo_workbench.catalog.checksum import sha256_file

        return {"size_bytes": size, "mtime": mtime, "hash": sha256_file(path)}

    def import_data(self, path, plan, *, work_dir, catalog, cancel=None, progress=None) -> ImportExecutionResult:
        cancel = cancel or NULL_CANCEL
        cancel.checkpoint()
        progress = progress or (lambda fraction, message="": None)
        source = Path(path)
        if plan.action == "link_external":
            progress(0.2, f"外部引用 SEG-Y: {plan.asset_name}")
            version = catalog.link_external(
                source,
                name=plan.asset_name,
                type=self.resource_type,
                format=source.suffix.lower().lstrip(".") or self.format_id,
                metadata=plan.metadata,
            )
            managed = False
        else:
            progress(0.2, f"导入 SEG-Y: {plan.asset_name}")
            version = catalog.import_raw(
                source,
                name=plan.asset_name,
                type=self.resource_type,
                format=source.suffix.lower().lstrip(".") or self.format_id,
                metadata=plan.metadata,
            )
            managed = True
        return ImportExecutionResult(version_id=version.id, asset_id=version.asset_id, managed=managed)

    def plan_export(self, source_path, target_path, *, options=None):
        raise FormatNotSupportedError(
            "SEG-Y 导出不可用：本仓库无 SEG-Y 写出器；派生数据请使用 zarr-v3 转码管线"
        )

    def verify_output(self, target_path, plan) -> ExportVerification:
        return ExportVerification.unverified("SEG-Y 无导出能力，无需验证")
