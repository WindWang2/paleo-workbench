from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.models import PreviewResult
from paleo_workbench.resources.preview_parsers.table_parsers import parse_error_preview, safe_stat

if TYPE_CHECKING:
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

try:
    import segyio
except ImportError:  # pragma: no cover
    segyio = None


def field_value(container, key) -> object:
    if key is None or container is None:
        return None
    getter = getattr(container, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            pass
    try:
        return container[key]
    except Exception:
        return None


def segy_preview(resource: ResourceItem, settings: PreviewSettings) -> PreviewResult:
    del settings
    import paleo_workbench.ui.pages.preview_provider as preview_provider
    segyio_obj = getattr(preview_provider, "segyio", None) or segyio
    if segyio_obj is None:
        return parse_error_preview(resource, "SEG-Y 预览依赖不可用")

    path = Path(resource.path)
    try:
        with segyio_obj.open(str(path), "r", ignore_geometry=True) as cube:
            trace_count = int(getattr(cube, "tracecount", 0) or 0)
            _samples = getattr(cube, "samples", None)
            sample_count = len(_samples) if _samples is not None else 0
            interval = field_value(
                getattr(cube, "bin", {}),
                getattr(segyio_obj.BinField, "Interval", None),
            )
            first_header = field_value(getattr(cube, "header", {}), 0) or {}
            inline = field_value(
                first_header,
                getattr(segyio_obj.TraceField, "INLINE_3D", None),
            )
            crossline = field_value(
                first_header,
                getattr(segyio_obj.TraceField, "CROSSLINE_3D", None),
            )
    except Exception as exc:
        return parse_error_preview(resource, f"SEG-Y 预览失败: {exc.__class__.__name__}")

    summary_rows = [
        ("道数", str(trace_count)),
        ("采样点", str(sample_count)),
    ]
    if interval is not None:
        summary_rows.append(("采样间隔", f"{interval} us"))
    table_rows = []
    if inline is not None:
        table_rows.append(("Inline", str(inline)))
    if crossline is not None:
        table_rows.append(("Crossline", str(crossline)))

    volume = None
    volume_warning = ""
    try:
        # Deferred: pulls in segyio/engine stack; keep lazy.
        from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path
        volume, load_warning = load_seismic_volume_from_path(str(path))
        if load_warning:
            volume_warning = str(load_warning)
    except Exception as exc:
        # The 3-D entry silently vanished when the volume loader failed
        # while the metadata summary stayed green (#897): surface the
        # failure class instead.
        volume_warning = f"三维体加载失败: {exc.__class__.__name__}"

    warning_parts = [p for p in (volume_warning,) if p]
    return PreviewResult(
        mode="seismic",
        title=resource.name,
        path=resource.path,
        revision=safe_stat(path),
        format=resource.format,
        status=resource.status,
        type_label=resource.type,
        summary_rows=tuple(summary_rows),
        table_headers=("字段", "值"),
        table_rows=tuple(table_rows),
        seismic_volume=volume,
        warning="; ".join(warning_parts),
    )
