"""Template Registry for Paleo AI GIS Harness.

Provides standardized cartographic map layouts, symbology palettes, and geological presets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MapLayoutTemplate:
    id: str
    name: str
    paper_size: str  # A4, A3, A2, A1, A0, Custom
    orientation: str  # landscape, portrait
    margins_mm: tuple[float, float, float, float]  # top, right, bottom, left
    include_legend: bool = True
    include_north_arrow: bool = True
    include_scale_bar: bool = True
    include_grid: bool = True
    include_geological_timescale: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class TemplateRegistry:
    """Registry of standard map composition layouts and geological palettes."""

    def __init__(self) -> None:
        self._layouts: dict[str, MapLayoutTemplate] = {}
        self._palettes: dict[str, list[str]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Standard geological publication layouts
        self.register_layout(
            MapLayoutTemplate(
                id="a4_landscape_standard",
                name="A4 横向标准地学制图模板",
                paper_size="A4",
                orientation="landscape",
                margins_mm=(10.0, 10.0, 15.0, 10.0),
                include_legend=True,
                include_north_arrow=True,
                include_scale_bar=True,
                include_grid=True,
                include_geological_timescale=True,
            )
        )
        self.register_layout(
            MapLayoutTemplate(
                id="a3_landscape_publication",
                name="A3 大幅古地理编图出版模板",
                paper_size="A3",
                orientation="landscape",
                margins_mm=(15.0, 15.0, 20.0, 15.0),
                include_legend=True,
                include_north_arrow=True,
                include_scale_bar=True,
                include_grid=True,
                include_geological_timescale=True,
            )
        )

        # Standard Color Palettes
        self._palettes["geological_lithology"] = [
            "#ffe082",  # Sandstone (Yellow)
            "#a5d6a7",  # Siltstone (Light Green)
            "#b0bec5",  # Mudstone / Shale (Grey)
            "#90caf9",  # Limestone (Light Blue)
            "#ce93d8",  # Dolomite (Purple)
            "#ffab91",  # Conglomerate (Orange/Brown)
        ]
        self._palettes["sand_ratio_ramp"] = [
            "#313695",  # Deep Blue (0.0)
            "#4575b4",
            "#74add1",
            "#abd9e9",
            "#ffffbf",  # Mid (0.5)
            "#fee090",
            "#fdae61",
            "#f46d43",
            "#d73027",  # Red (1.0)
        ]

    def register_layout(self, template: MapLayoutTemplate) -> None:
        # #1185: same-id registration is refused — silent override hides
        # cross-feature collisions.
        if template.id in self._layouts:
            raise ValueError(
                f"map layout template '{template.id}' is already registered; refusing "
                "silent override (pick a unique id)"
            )
        self._layouts[template.id] = template

    def get_layout(self, layout_id: str) -> MapLayoutTemplate | None:
        return self._layouts.get(layout_id)

    def list_layouts(self) -> list[MapLayoutTemplate]:
        return list(self._layouts.values())

    def get_palette(self, name: str) -> list[str]:
        return list(self._palettes.get(name, []))

    def list_palettes(self) -> dict[str, list[str]]:
        return dict(self._palettes)


template_registry = TemplateRegistry()
