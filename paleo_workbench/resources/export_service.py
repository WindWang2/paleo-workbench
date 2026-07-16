"""Unified export service: convert assets, grab views, register ExportArtifact."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.project.paths import ensure_artifact_layout, relativize_path
from paleo_workbench.resources.exporters import (
    ExportError,
    extension_for_label,
    get_available_formats,
)
from paleo_workbench.resources.io_registry import TYPE_LABELS, VIEW_EXPORT_FORMATS
from paleo_workbench.workflow.export import record_export


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


def list_view_export_labels() -> list[str]:
    return [spec.label for spec in VIEW_EXPORT_FORMATS]


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
            from paleo_workbench.project.paths import resolve_project_path

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
        artifact.included_map_elements = ["visualization_view"]

    return ExportJobResult(
        success=True,
        output_path=str(output_path),
        format=label,
        artifact=artifact,
        message=f"已导出视图: {output_path.name}",
    )


def _export_widget_png(widget: Any, output_path: Path) -> None:
    # Prefer engine well-log vector export helpers when present.
    try:
        from geoviz import export_png as engine_png

        if hasattr(widget, "paint_all"):
            engine_png(widget, str(output_path))
            return
    except Exception:
        pass
    if not hasattr(widget, "grab"):
        raise ExportError("控件不支持截图导出")
    pixmap = widget.grab()
    if not pixmap.save(str(output_path), "PNG"):
        raise ExportError("PNG 保存失败")


def _export_widget_svg(widget: Any, output_path: Path) -> None:
    try:
        from geoviz import export_svg as engine_svg

        if hasattr(widget, "paint_all"):
            engine_svg(widget, str(output_path))
            return
    except Exception:
        pass
    # Fallback: rasterize then not true SVG — raise to force PNG
    raise ExportError("当前视图不支持 SVG 矢量导出，请改用 PNG")


def _export_widget_pdf(widget: Any, output_path: Path) -> None:
    try:
        from geoviz import export_pdf as engine_pdf

        if hasattr(widget, "paint_all"):
            engine_pdf(widget, str(output_path))
            return
    except Exception:
        pass
    raise ExportError("当前视图不支持 PDF 矢量导出，请改用 PNG")


def default_export_dir(project_path: Path | None) -> Path:
    if project_path is None:
        return Path.home() / "paleo_exports"
    layout = ensure_artifact_layout(project_path)
    exports = layout / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    return exports
