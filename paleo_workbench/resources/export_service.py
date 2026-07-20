"""Unified export service: convert assets, grab views, register ExportArtifact."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.project.paths import (
    ensure_artifact_layout,
    relativize_path,
    resolve_project_path,
)
from paleo_workbench.resources.exporters import ExportError, get_available_formats
from paleo_workbench.resources.io_registry import TYPE_LABELS, VIEW_EXPORT_FORMATS
from paleo_workbench.project.artifacts import record_export


@dataclass
class ExportJobResult:
    success: bool
    output_path: str = ""
    format: str = ""
    artifact: ExportArtifact | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)


def list_asset_export_labels(asset: ResourceItem | ExportArtifact) -> list[str]:
    return [label for label, _ in get_available_formats(asset)]


def list_view_export_labels(widget: Any | None = None) -> list[str]:
    """Return export labels for a view widget (or the full catalog when None)."""
    if widget is None:
        return [spec.label for spec in VIEW_EXPORT_FORMATS]
    return sorted(view_export_capabilities(widget), key=_view_format_rank)


def _view_format_rank(label: str) -> int:
    order = {"PNG": 0, "SVG": 1, "PDF": 2}
    return order.get(label.upper(), 99)


def view_export_capabilities(widget: Any | None) -> frozenset[str]:
    """Formats the active visualization surface can honestly export.

    - Well-log canvas (``paint_all``): PNG/SVG/PDF via geoviz_well_log
    - Cross-well composite (``export_composite``): PNG/SVG/PDF
    - Paleo map canvas: PNG/SVG/PDF via professional figure export
    - Everything else (seismic GL, engine preview, empty): PNG grab only
    """
    if widget is None:
        return frozenset()
    target = _resolve_export_target(widget)
    kind = _export_surface_kind(target)
    if kind in {"well_log", "cross_well", "paleo_map"}:
        return frozenset({"PNG", "SVG", "PDF"})
    if hasattr(target, "grab"):
        return frozenset({"PNG"})
    return frozenset()


def _resolve_export_target(widget: Any) -> Any:
    """Prefer the engine surface that owns vector export APIs.

    ``CrossWellCanvas`` wraps ``CrossWellWidget``; export lives on the inner widget.
    """
    if widget is None:
        return None
    if hasattr(widget, "export_composite") or hasattr(widget, "paint_all"):
        return widget
    if _is_paleo_map_canvas(widget):
        return widget
    canvas = getattr(widget, "canvas", None)
    if canvas is not None and (
        hasattr(canvas, "export_composite")
        or hasattr(canvas, "paint_all")
        or _is_paleo_map_canvas(canvas)
    ):
        return canvas
    inner = getattr(widget, "widget", None)
    if inner is not None and (
        hasattr(inner, "export_composite")
        or hasattr(inner, "paint_all")
        or _is_paleo_map_canvas(inner)
    ):
        return inner
    return widget


def _is_paleo_map_canvas(widget: Any) -> bool:
    if widget is None:
        return False
    name = type(widget).__name__
    if name == "PaleoMapCanvas":
        return True
    # Duck-type engine map canvas without hard import.
    return hasattr(widget, "load_features") and hasattr(widget, "_layers")


def _export_surface_kind(widget: Any) -> str:
    if widget is None:
        return "none"
    if hasattr(widget, "paint_all"):
        return "well_log"
    if hasattr(widget, "export_composite"):
        return "cross_well"
    if _is_paleo_map_canvas(widget):
        return "paleo_map"
    return "generic"


def _paleo_map_title(canvas: Any) -> str:
    period = getattr(canvas, "_period_name", None) or getattr(canvas, "period_name", None)
    period = str(period or "").strip()
    if period:
        return f"{period}岩相古地理图"
    return "岩相古地理图"


def export_asset_to_path(
    asset: ResourceItem,
    format_label: str,
    output_path: Path,
    *,
    project: ProjectDocument | None = None,
    project_path: Path | None = None,
    register: bool = True,
) -> ExportJobResult:
    """Run a registered converter and optionally record ExportArtifact."""
    formats = get_available_formats(asset)
    convert_fn = next((fn for lbl, fn in formats if lbl == format_label), None)
    if convert_fn is None:
        return ExportJobResult(
            success=False,
            message=f"资源不支持导出为 {format_label}",
        )
    input_path = Path(asset.path)
    if project_path is not None:
        try:
            input_path = Path(resolve_project_path(str(input_path), project_path))
        except Exception:
            pass
    if not input_path.is_file():
        # Last resort: resolve against CWD for absolute-ish relative paths.
        resolved = input_path.expanduser()
        if not resolved.is_absolute():
            resolved = resolved.resolve()
        input_path = resolved
    if not input_path.is_file():
        return ExportJobResult(success=False, message=f"源文件不存在: {input_path}")
    try:
        convert_fn(input_path, output_path)
    except ExportError as exc:
        return ExportJobResult(success=False, message=str(exc))
    except Exception as exc:
        return ExportJobResult(
            success=False, message=f"导出失败: {exc.__class__.__name__}: {exc}"
        )

    artifact = None
    stored = str(output_path)
    if register and project is not None:
        if project_path is not None:
            stored, _ = relativize_path(str(output_path), project_path)
        artifact = record_export(
            project,
            linked_id=asset.id,
            output_path=stored,
            fmt=format_label.lower(),
            source_task_ids=[],
        )
        artifact.included_map_elements = []
        # stash source name in a free-form way via included list for UI
        artifact.included_map_elements = [f"source:{asset.name}"]

    return ExportJobResult(
        success=True,
        output_path=str(output_path),
        format=format_label,
        artifact=artifact,
        message=f"已导出: {Path(output_path).name}",
    )


def export_project_inventory(
    project: ProjectDocument,
    output_path: Path,
    *,
    project_path: Path | None = None,
    register: bool = True,
) -> ExportJobResult:
    """Export resource + artifact inventory as JSON for handoff / QC."""
    resources = []
    for r in project.resources:
        resources.append(
            {
                "id": r.id,
                "name": r.name,
                "type": r.type,
                "type_label": TYPE_LABELS.get(r.type, r.type),
                "format": r.format,
                "path": r.path,
                "status": r.status,
                "external": r.external,
                "artifact_role": r.artifact_role,
                "tags": list(r.tags or []),
                "parsed_summary": dict(r.parsed_summary or {}),
            }
        )
    artifacts = [
        {
            "id": a.id,
            "linked_id": a.linked_id,
            "format": a.format,
            "output_path": a.output_path,
        }
        for a in project.export_artifacts
    ]
    payload = {
        "project": project.meta.name,
        "region": project.meta.region,
        "resource_count": len(resources),
        "artifact_count": len(artifacts),
        "resources": resources,
        "export_artifacts": artifacts,
    }
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        return ExportJobResult(success=False, message=f"写入清单失败: {exc}")

    artifact = None
    stored = str(output_path)
    if register:
        if project_path is not None:
            stored, _ = relativize_path(str(output_path), project_path)
        artifact = record_export(
            project,
            linked_id=project.meta.name,
            output_path=stored,
            fmt="inventory.json",
            source_task_ids=[],
        )
        artifact.included_map_elements = ["inventory"]

    return ExportJobResult(
        success=True,
        output_path=str(output_path),
        format="INVENTORY",
        artifact=artifact,
        message=f"已导出工程清单: {output_path.name}",
    )


def export_widget_snapshot(
    widget: Any,
    output_path: Path,
    format_label: str = "PNG",
    *,
    project: ProjectDocument | None = None,
    project_path: Path | None = None,
    linked_id: str = "viz_view",
    register: bool = True,
) -> ExportJobResult:
    """Export a QWidget (or engine canvas) to PNG/SVG/PDF when possible."""
    label = format_label.upper()
    fmt = label.lower()
    caps = view_export_capabilities(widget)
    if label not in caps:
        supported = "、".join(sorted(caps, key=_view_format_rank)) or "无"
        return ExportJobResult(
            success=False,
            message=f"当前 Tab 不支持 {label} 导出（可用: {supported}）",
        )
    try:
        if label == "PNG":
            _export_widget_png(widget, output_path)
        elif label == "SVG":
            _export_widget_svg(widget, output_path)
        elif label == "PDF":
            _export_widget_pdf(widget, output_path)
        else:
            return ExportJobResult(success=False, message=f"不支持的视图导出格式: {label}")
    except Exception as exc:
        return ExportJobResult(
            success=False,
            message=f"视图导出失败: {exc.__class__.__name__}: {exc}",
        )

    artifact = None
    stored = str(output_path)
    if register and project is not None:
        if project_path is not None:
            ensure_artifact_layout(project_path)
            stored, _ = relativize_path(str(output_path), project_path)
        artifact = record_export(
            project,
            linked_id=linked_id,
            output_path=stored,
            fmt=fmt,
            source_task_ids=[],
        )
        surface = _export_surface_kind(_resolve_export_target(widget))
        artifact.included_map_elements = ["visualization_view", surface]

    return ExportJobResult(
        success=True,
        output_path=str(output_path),
        format=label,
        artifact=artifact,
        message=f"已导出视图: {output_path.name}",
    )


def _export_widget_png(widget: Any, output_path: Path) -> None:
    target = _resolve_export_target(widget)
    kind = _export_surface_kind(target)
    if kind == "well_log":
        try:
            from geoviz import export_png as engine_png

            engine_png(target, str(output_path))
            return
        except Exception:
            pass
    if kind == "cross_well":
        target.export_composite(str(output_path), fmt="png")
        return
    if kind == "paleo_map":
        _export_paleo_map(target, output_path, "png")
        return
    if not hasattr(target, "grab"):
        raise ExportError("控件不支持截图导出")
    pixmap = target.grab()
    if not pixmap.save(str(output_path), "PNG"):
        raise ExportError("PNG 保存失败")


def _export_widget_svg(widget: Any, output_path: Path) -> None:
    target = _resolve_export_target(widget)
    kind = _export_surface_kind(target)
    if kind == "well_log":
        from geoviz import export_svg as engine_svg

        engine_svg(target, str(output_path))
        return
    if kind == "cross_well":
        target.export_composite(str(output_path), fmt="svg")
        return
    if kind == "paleo_map":
        _export_paleo_map(target, output_path, "svg")
        return
    raise ExportError("当前视图不支持 SVG 矢量导出，请改用 PNG")


def _export_widget_pdf(widget: Any, output_path: Path) -> None:
    target = _resolve_export_target(widget)
    kind = _export_surface_kind(target)
    if kind == "well_log":
        from geoviz import export_pdf as engine_pdf

        engine_pdf(target, str(output_path))
        return
    if kind == "cross_well":
        target.export_composite(str(output_path), fmt="pdf")
        return
    if kind == "paleo_map":
        _export_paleo_map(target, output_path, "pdf")
        return
    raise ExportError("当前视图不支持 PDF 矢量导出，请改用 PNG")


def _export_paleo_map(canvas: Any, output_path: Path, fmt: str) -> None:
    """Use engine professional figure export (title/scale/legend frame)."""
    try:
        from geoviz import export_professional_figure
    except Exception as exc:  # pragma: no cover - import env
        raise ExportError(f"古地理导出模块不可用: {exc}") from exc
    export_professional_figure(
        canvas,
        output_path,
        fmt,  # type: ignore[arg-type]
        title=_paleo_map_title(canvas),
    )


def default_export_dir(project_path: Path | None) -> Path:
    if project_path is None:
        return Path.home() / "paleo_exports"
    layout = ensure_artifact_layout(project_path)
    exports = layout / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    return exports
