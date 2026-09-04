"""Data models for Map Composer layout and cartographic elements."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

COMPOSITION_SCHEMA_VERSION = 2


class ElementType(str, Enum):
    MAIN_MAP = "main_map"
    LEGEND = "legend"
    NORTH_ARROW = "north_arrow"
    SCALE_BAR = "scale_bar"
    GRID = "grid"
    TITLE = "title"
    ANNOTATION = "annotation"
    TIMESCALE = "timescale"
    TEXT = "text"
    IMAGE = "image"
    INSET_MAP = "inset_map"
    STAT_CHART = "stat_chart"
    METADATA = "metadata"
    COLORBAR = "colorbar"
    # B5 专业编图组件：图廓/数据来源/制图责任 + 地质图例符号组。
    NEATLINE = "neatline"
    DATASOURCE = "datasource"
    TIME_CREDITS = "time_credits"
    FAULT_SYMBOLS = "fault_symbols"
    FACIES_LEGEND = "facies_legend"
    LITHOLOGY_LEGEND = "lithology_legend"
    STRAT_LABELS = "strat_labels"


# Serializable property keys per element type. Everything else still round-
# trips (properties is an open dict); this map documents the contract and
# gives templates/factories their vocabulary.
ELEMENT_PROPERTY_KEYS: dict[ElementType, tuple[str, ...]] = {
    ElementType.MAIN_MAP: ("map_document", "layers", "extent", "title"),
    ElementType.LEGEND: ("items",),
    ElementType.NORTH_ARROW: ("label",),
    ElementType.SCALE_BAR: ("length_km", "units"),
    ElementType.GRID: ("spacing_mm", "color", "line_width_mm"),
    ElementType.TITLE: ("text", "font_size", "align"),
    ElementType.ANNOTATION: ("text", "leader", "font_size"),
    ElementType.TIMESCALE: ("stages",),
    ElementType.TEXT: ("text", "font_size", "align", "color"),
    ElementType.IMAGE: ("image_path", "image_data_png_b64", "fit"),
    ElementType.INSET_MAP: ("map_document", "layers", "extent", "locator_scale", "locator_rect"),
    ElementType.STAT_CHART: ("chart_type", "title", "series", "units"),
    ElementType.METADATA: ("fields", "font_size"),
    ElementType.COLORBAR: ("title", "stops", "min", "max", "units", "discrete", "data_binding"),
    ElementType.NEATLINE: ("line_width_mm", "color", "double_line", "inner_gap_mm"),
    ElementType.DATASOURCE: ("title", "text", "font_size"),
    ElementType.TIME_CREDITS: ("text", "font_size"),
    ElementType.FAULT_SYMBOLS: ("title", "items"),
    ElementType.FACIES_LEGEND: ("title", "items"),
    ElementType.LITHOLOGY_LEGEND: ("title", "items"),
    ElementType.STRAT_LABELS: ("text", "font_size"),
}


def _new_element_id() -> str:
    return f"el_{uuid.uuid4().hex[:10]}"


@dataclass
class ComposerElement:
    id: str
    element_type: ElementType
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    z_index: int = 0
    visible: bool = True
    locked: bool = False
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        props: dict[str, Any] = {}
        for key, value in self.properties.items():
            props[key] = _serialize_property_value(value)
        element_type = self.element_type
        raw_type = props.pop("_raw_element_type", None)
        if raw_type is not None and element_type is ElementType.TEXT:
            # Preserve a forward-compat carrier's true type (from_dict).
            element_type_value = str(raw_type)
        else:
            element_type_value = element_type.value
        return {
            "id": self.id,
            "element_type": element_type_value,
            "x_mm": float(self.x_mm),
            "y_mm": float(self.y_mm),
            "width_mm": float(self.width_mm),
            "height_mm": float(self.height_mm),
            "z_index": int(self.z_index),
            "visible": bool(self.visible),
            "locked": bool(self.locked),
            "properties": props,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ComposerElement":
        raw_type = str(payload.get("element_type") or "text")
        try:
            element_type = ElementType(raw_type)
        except ValueError:
            # Forward compatibility: an unknown future type is carried as a
            # plain text element with its raw type recorded, never dropped
            # and never silently relabelled on re-serialization.
            element_type = ElementType.TEXT
        properties = dict(payload.get("properties") or {})
        if element_type is ElementType.TEXT and raw_type != ElementType.TEXT.value:
            properties.setdefault("_raw_element_type", raw_type)
        return cls(
            id=str(payload.get("id") or _new_element_id()),
            element_type=element_type,
            x_mm=float(payload.get("x_mm") or 0.0),
            y_mm=float(payload.get("y_mm") or 0.0),
            width_mm=float(payload.get("width_mm") or 1.0),
            height_mm=float(payload.get("height_mm") or 1.0),
            z_index=int(payload.get("z_index") or 0),
            visible=bool(payload.get("visible", True)),
            # 旧文档没有 locked 字段：缺省即未锁定。
            locked=bool(payload.get("locked", False)),
            properties=properties,
        )


def _serialize_property_value(value: Any) -> Any:
    # Lazy import: models stays importable without the layer package.
    from paleo_workbench.mapping.layers import MapDocument, MapLayer

    if isinstance(value, MapDocument):
        return {"__ref__": "map_document", "id": value.id, "layer_count": len(value.layers)}
    if isinstance(value, MapLayer):
        return {"__ref__": "map_layer", "id": value.id, "layer_type": value.layer_type}
    if isinstance(value, dict):
        return {k: _serialize_property_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [ _serialize_property_value(v) for v in value ]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# Paper sizes in millimetres (portrait short × long edge).
PAPER_SIZES_MM: dict[str, tuple[float, float]] = {
    "A5": (148.0, 210.0),
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "A2": (420.0, 594.0),
    "A1": (594.0, 841.0),
    "A0": (841.0, 1189.0),
}


@dataclass
class MapCompositionDocument:
    id: str
    title: str
    paper_size: str = "A4"  # A4, A3, A2, A1, A0
    orientation: str = "landscape"  # landscape, portrait
    width_mm: float = 297.0
    height_mm: float = 210.0
    dpi: float = 300.0
    elements: list[ComposerElement] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    def get_element(self, elem_id: str) -> ComposerElement | None:
        for elem in self.elements:
            if elem.id == elem_id:
                return elem
        return None

    def add_element(self, element: ComposerElement) -> None:
        self.elements.append(element)
        self.elements.sort(key=lambda e: e.z_index)

    def set_paper(self, paper_size: str, orientation: str) -> None:
        size = PAPER_SIZES_MM.get(str(paper_size).upper())
        if size is None:
            raise ValueError(f"unknown paper size {paper_size!r}")
        short, long = size
        if orientation == "portrait":
            self.width_mm, self.height_mm = short, long
        else:
            self.width_mm, self.height_mm = long, short
        self.paper_size = str(paper_size).upper()
        self.orientation = orientation

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "paper_size": self.paper_size,
            "orientation": self.orientation,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "schema_version": COMPOSITION_SCHEMA_VERSION,
            "elements": [e.to_dict() for e in self.elements],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MapCompositionDocument":
        """Rebuild a composition from its serialized form.

        Forward compatibility: unknown element types, element fields, or
        top-level keys are preserved, not rejected — a newer schema version
        is recorded in ``metadata["schema_version"]`` and live-object
        references (map documents/layers) arrive as stubs the host re-binds.
        """
        paper = str(payload.get("paper_size") or "A4")
        orientation = str(payload.get("orientation") or "landscape")
        doc = cls(
            id=str(payload.get("id") or f"comp_{uuid.uuid4().hex[:10]}"),
            title=str(payload.get("title") or ""),
            paper_size=paper,
            orientation=orientation,
            width_mm=float(payload.get("width_mm") or 297.0),
            height_mm=float(payload.get("height_mm") or 210.0),
            dpi=float(payload.get("dpi") or 300.0),
        )
        for elem_payload in payload.get("elements") or []:
            if isinstance(elem_payload, Mapping):
                doc.elements.append(ComposerElement.from_dict(elem_payload))
        doc.elements.sort(key=lambda e: e.z_index)
        # schema_version lives at top level; metadata stays caller-owned so
        # roundtrips are byte-identical for documents created in-process.
        doc.metadata = dict(payload.get("metadata") or {})
        return doc
