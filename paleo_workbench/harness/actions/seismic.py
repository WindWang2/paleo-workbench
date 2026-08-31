"""Seismic-domain harness actions (P2-C).

READ/COMPUTE risk; volumes open through the single ``open_volume`` IO
authority; attribute computation runs through the capability provider
(governor admission + provenance included).
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def _resolve_volume_path(context: ActionContext, raw: str) -> str:
    """Volume paths stay inside the workspace (read boundary).

    Absolute paths must live under the project root; relative paths resolve
    against it. Catalog-managed derived stores (project-relative) fit the
    same rule. This keeps agent-supplied strings from opening arbitrary
    host files.
    """
    from pathlib import Path

    raw_path = Path(raw).expanduser()
    root = Path(context.project_path).parent if context.project_path else Path.cwd()
    if raw_path.is_absolute():
        try:
            resolved = raw_path.resolve()
            resolved.relative_to(root.resolve())
        except ValueError:
            raise PermissionError(
                f"volume path must stay under the project workspace ({root})"
            ) from None
        return str(resolved)
    return str((root / raw_path).resolve())


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="seismic.open_volume",
            description="打开地震体（zarr 生产路径 / RAW SEG-Y 降级浏览），成为会话激活体。",
            handler=_open_volume,
            risk=ActionRisk.COMPUTE,
            category="background.io",
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 64 * 1024**2, "io_weight": 1.5},
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "体数据路径（zarr 目录或 .segy）"},
                    "volume_id": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="seismic.get_slice",
            description="读取激活（或指定）地震体的一条剖面（inline/crossline/timeslice）并返回统计。",
            handler=_get_slice,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "estimated_ram_bytes": 32 * 1024**2, "io_weight": 1.0},
            input_schema={
                "type": "object",
                "properties": {
                    "slice_type": {"type": "string", "enum": ["inline", "crossline", "timeslice"]},
                    "index": {"type": "integer"},
                    "lod": {"type": "integer", "minimum": 0, "maximum": 4},
                },
                "required": ["slice_type", "index"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="seismic.compute_attribute",
            description="对激活（或指定）地震体计算属性体（如 c3 相干），经 provider 执行并登记派生数据。",
            handler=_compute_attribute,
            risk=ActionRisk.COMPUTE,
            category="seismic.attribute",
            resource_profile={"estimated_cpu_cores": 2.0, "estimated_ram_bytes": 1024 * 1024**2, "io_weight": 1.0},
            supports_cancel=True,
            input_schema={
                "type": "object",
                "properties": {
                    "attribute": {"type": "string", "enum": ["c3"], "description": "属性 kernel"},
                    "output_dir": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
    )


def _open_volume(context: ActionContext, parameters: dict) -> dict:
    from geoviz_seismic import open_volume

    path = _resolve_volume_path(context, parameters["path"])
    reader = open_volume(path)
    geometry = reader.geometry
    volume_id = parameters.get("volume_id") or path
    from paleo_workbench.providers.refs import SeismicVolumeRef

    ref = SeismicVolumeRef(
        volume_id=volume_id,
        path=str(path),
        kind="zarr" if str(path).endswith(".zarr") else "segy",
    )
    context.active_volume = ref
    context.extras.setdefault("volume_readers", {})[volume_id] = reader
    return {
        "volume": ref.to_dict(),
        "geometry": {
            "shape": list(geometry.shape),
            "iline_range": [geometry.iline_start, geometry.iline_start + (geometry.shape[0] - 1) * geometry.iline_step]
            if hasattr(geometry, "iline_step")
            else None,
            "xl_range": [geometry.xline_start, geometry.xline_start + (geometry.shape[1] - 1) * geometry.xline_step]
            if hasattr(geometry, "xline_step")
            else None,
        },
    }


def _reader_for(context: ActionContext, parameters: dict) -> tuple[str, Any]:
    readers = context.extras.get("volume_readers") or {}
    volume = context.active_volume
    if not readers and volume is None:
        raise LookupError("no seismic volume open (call seismic.open_volume first)")
    if volume is not None and volume.volume_id in readers:
        return volume.volume_id, readers[volume.volume_id]
    return next(iter(readers.items()))


def _get_slice(context: ActionContext, parameters: dict) -> dict:
    import numpy as np

    _volume_id, reader = _reader_for(context, parameters)
    slice_type = parameters["slice_type"]
    index = int(parameters["index"])
    lod = int(parameters.get("lod", 0))
    kwargs = {"lod": lod} if lod else {}
    if slice_type == "inline":
        array = reader.read_inline(index, **kwargs)
    elif slice_type == "crossline":
        array = reader.read_crossline(index, **kwargs)
    else:
        array = reader.read_timeslice(index, **kwargs)
    finite = array[np.isfinite(array)]
    return {
        "slice_type": slice_type,
        "index": index,
        "lod": lod,
        "shape": list(array.shape),
        "dtype": str(array.dtype),
        "finite_ratio": float(finite.size) / max(1, array.size),
        "min": float(finite.min()) if finite.size else None,
        "max": float(finite.max()) if finite.size else None,
        "mean": float(finite.mean()) if finite.size else None,
        "values": array,  # in-memory payload for verification + callers
    }


def _compute_attribute(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.providers import ProviderContext, execute_provider
    from paleo_workbench.providers.refs import SeismicVolumeRef

    volume = context.active_volume
    if volume is None or not isinstance(volume, SeismicVolumeRef):
        raise LookupError("no active seismic volume (call seismic.open_volume first)")
    from pathlib import Path

    root = Path(context.project_path).parent if context.project_path else None
    output_dir = parameters.get("output_dir")
    if output_dir is not None:
        output_dir = _resolve_volume_path(context, output_dir)
    elif root is not None:
        # Derived outputs land in the workspace artifacts area (never /tmp-only).
        output_dir = str(root / "demo.artifacts" / "derived" / "attr.zarr")
    else:
        import tempfile

        output_dir = str(Path(tempfile.mkdtemp(prefix="p2-attribute-")) / "attr.zarr")
    provider_parameters = {"output_dir": output_dir}
    provider_context = ProviderContext(
        catalog=context.catalog,
        emit_progress=context.progress,
        cancel=context.cancel,
        work_dir=context.extras.get("work_dir"),
    )
    result = execute_provider(
        _registry(),
        f"seismic.attribute.{parameters.get('attribute', 'c3')}",
        inputs={"volume": volume},
        parameters=provider_parameters,
        context=provider_context,
    )
    artifacts = result.to_dict()["artifacts"]
    values = [a.value for a in result.artifacts if a.value is not None]
    return {
        "attribute": parameters.get("attribute", "c3"),
        "artifacts": artifacts,
        "values": values,
        "diagnostics": result.diagnostics,
        "provenance": result.provenance,
    }


def _registry():
    from paleo_workbench.providers import get_provider_registry

    return get_provider_registry()
