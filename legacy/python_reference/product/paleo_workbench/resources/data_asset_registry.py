"""DataAssetRegistry: Deep module for data asset classification, scanning, preview, and export.

Centralizes data format classification, directory scanning, format spec registration,
preview parser building, and format export dispatches into a single deep module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.resources.classifier import classify_path as _classify_path
from paleo_workbench.resources.scanner import scan_resources as _scan_resources

if TYPE_CHECKING:
    from paleo_workbench.resources.preview_parsers.models import PreviewResult
    from paleo_workbench.resources.preview_settings import PreviewSettings


@dataclass
class FormatSpec:
    """Single-point registration spec for a data asset format."""

    format_id: str
    extensions: set[str] = field(default_factory=set)
    resource_type: str = "unknown"
    status: str = "indexed"
    preview_parser: Callable[[ResourceItem | ExportArtifact, Any], Any] | None = None
    exporter: Callable[[Any, str, Path], bool] | None = None


class DataAssetRegistry:
    """Deep module managing format specs, path classification, scanning, previews, and exports."""

    def __init__(self) -> None:
        self._format_specs: dict[str, FormatSpec] = {}

    def register_format(self, spec: FormatSpec) -> None:
        """Register a single-point format specification."""
        self._format_specs[spec.format_id.lower()] = spec
        for ext in spec.extensions:
            self._format_specs[ext.lower()] = spec

    def classify_path(self, path: Path) -> tuple[str, str, str]:
        """Classify file path into (resource_type, format, status)."""
        ext = path.suffix.lower().lstrip(".")
        if ext in self._format_specs:
            spec = self._format_specs[ext]
            return spec.resource_type, ext, spec.status
        return _classify_path(path)

    def inspect(self, path: Path) -> tuple[str, str, str]:
        """Inspect and classify file path into (resource_type, format, status). Alias for classify_path."""
        return self.classify_path(path)

    def scan_directory(
        self,
        root: Path,
        project_path: Path | None = None,
        *,
        skip_checksum_over_bytes: int | None = None,
        max_workers: int | None = None,
    ) -> list[ResourceItem]:
        """Scan directory and return list of classified ResourceItems."""
        return _scan_resources(
            root,
            project_path,
            skip_checksum_over_bytes=skip_checksum_over_bytes,
            max_workers=max_workers,
            classify=self.classify_path,
        )

    def parse_preview(
        self,
        asset: ResourceItem | ExportArtifact,
        settings: PreviewSettings,
        project_root: str | Path | None = None,
    ) -> PreviewResult:
        """Parse preview representation for an asset."""
        from paleo_workbench.resources.preview_parsers.registry import default_registry

        fmt = asset.format.lower()
        if fmt in self._format_specs and self._format_specs[fmt].preview_parser is not None:
            return self._format_specs[fmt].preview_parser(asset, settings)  # type: ignore

        registry = default_registry()
        return registry.build_preview(asset, settings, project_root=project_root)

    def export(self, asset: Any, format_id: str, output_path: str | Path) -> bool:
        """Export asset to output path in specified format.

        A registered :class:`FormatSpec` exporter wins; otherwise dispatch
        through the shared converter table (the same one behind
        ``get_available_formats``) so every export path has one
        implementation. Raises :class:`ExportError` when the format has no
        converter (the previous lazy import referenced a name that does not
        exist and would have raised ImportError here).
        """
        from paleo_workbench.resources.exporters import (
            ExportError,
            get_available_formats,
        )

        fmt = (format_id or "").lower()
        spec = self._format_specs.get(fmt)
        if spec is not None and spec.exporter is not None:
            return bool(spec.exporter(asset, format_id, Path(output_path)))

        label = fmt.upper()
        for available, convert_fn in get_available_formats(asset):
            if available == label:
                convert_fn(Path(asset.path), Path(output_path))
                return True
        raise ExportError(f"没有可用于 {label} 的导出器: {getattr(asset, 'format', '?')}")


# ---------------------------------------------------------------------------
# Global Singleton Instance
# ---------------------------------------------------------------------------
data_asset_registry = DataAssetRegistry()
