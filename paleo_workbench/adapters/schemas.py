from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ViewerPayload(BaseModel):
    viewer_type: Literal["well_log", "seismic", "cross_well", "factor_map", "paleo_map"]
    schema_version: str = "1.0"
    resources: list[dict[str, Any]] = Field(default_factory=list)
    layers: list[dict[str, Any]] = Field(default_factory=list)
    style_hints: dict[str, Any] = Field(default_factory=dict)
    crs: str = "EPSG:4326"


class ViewState(BaseModel):
    schema_version: str = "1.0"
    viewport: dict[str, Any] = Field(default_factory=dict)
    selected_ids: list[str] = Field(default_factory=list)
    visible_layers: list[str] = Field(default_factory=list)
    style_overrides: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    path: str
    format: Literal["pdf", "svg", "png", "geojson"]
    dpi: int | None = None
    vector_mode: bool = True
    selected_layers: list[str] = Field(default_factory=list)
    layout_options: dict[str, Any] = Field(default_factory=dict)


class ExportResult(BaseModel):
    output_path: str
    format: Literal["pdf", "svg", "png", "geojson"]
    byte_size: int | None = None
    warnings: list[str] = Field(default_factory=list)
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterError(BaseModel):
    adapter_name: str
    operation: str
    severity: Literal["warning", "error", "critical"]
    message: str
    recoverable: bool = True
    traceback_summary: str | None = None