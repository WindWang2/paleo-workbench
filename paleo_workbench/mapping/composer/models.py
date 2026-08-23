"""Data models for Map Composer layout and cartographic elements."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ElementType(str, Enum):
    MAIN_MAP = "main_map"
    LEGEND = "legend"
    NORTH_ARROW = "north_arrow"
    SCALE_BAR = "scale_bar"
    GRID = "grid"
    TITLE = "title"
    ANNOTATION = "annotation"
    TIMESCALE = "timescale"


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
    properties: dict[str, Any] = field(default_factory=dict)


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "paper_size": self.paper_size,
            "orientation": self.orientation,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "dpi": self.dpi,
            "elements": [
                {
                    "id": e.id,
                    "element_type": e.element_type.value,
                    "x_mm": e.x_mm,
                    "y_mm": e.y_mm,
                    "width_mm": e.width_mm,
                    "height_mm": e.height_mm,
                    "z_index": e.z_index,
                    "visible": e.visible,
                    "properties": e.properties,
                }
                for e in self.elements
            ],
            "metadata": self.metadata,
        }
