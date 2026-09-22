"""Visualization & Layout Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

from typing import Any

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.planner import TaskNode
from paleo_workbench.agent.registries.template_registry import template_registry


class VisualizationAgent(BaseAgent):
    """Specialized Agent responsible for QGIS layer styling, layout composition, and multi-format vector/raster export."""

    def __init__(self) -> None:
        super().__init__(
            name="viz_agent",
            role="Visualization & Layout Specialist",
            description="Applies symbology color ramps, places cartographic map elements (legend, north arrow, scale bar), and exports publishable maps.",
        )

    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Composing map visualization layout: {task.description}")

        # Selecting a registered template/palette is real; PLACING elements
        # and EXPORTING are not — no composition or render runs here.
        layout = template_registry.get_layout("a4_landscape_standard")
        palette = template_registry.get_palette("sand_ratio_ramp")

        self.log(
            f"Selected template: {layout.name if layout else 'Default'} with "
            f"{len(palette)} color classes — no layout placed, nothing exported (stub)."
        )

        return {
            "status": "success",  # the node ran; no layout/export happened
            "stub": True,
            "layout_template": layout.id if layout else "default",
            "symbology_palette": "sand_ratio_ramp",
            # What the selected template WOULD include — nothing was placed.
            "template_elements": ["main_map", "legend", "north_arrow", "scale_bar", "graticule_grid"],
            "elements_placed": [],
            "export_formats_ready": [],
            "note": "演示占位：仅选择模板与色带，未执行真实排版与导出。",
        }
