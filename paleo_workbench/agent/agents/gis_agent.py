"""Spatial GIS & Topology Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

from typing import Any

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.planner import TaskNode
from paleo_workbench.mapping.topology import repair_invalid_geometry


class GISAgent(BaseAgent):
    """Specialized Agent responsible for GIS spatial analysis, coordinate transformations, and topology verification."""

    def __init__(self) -> None:
        super().__init__(
            name="gis_agent",
            role="Spatial GIS Specialist",
            description="Manages CRS transformations, extracts fault barrier constraints, and ensures topological validity.",
        )

    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Executing spatial GIS analysis: {task.description}")

        # Synthetic fault barriers for domain
        fault_lines = [
            [[500000.0, 3410000.0], [510000.0, 3418000.0], [520000.0, 3422000.0]],
            [[505000.0, 3405000.0], [515000.0, 3412000.0], [525000.0, 3418000.0]],
        ]

        basin_boundary = {
            "type": "Polygon",
            "coordinates": [
                [
                    [495000.0, 3400000.0],
                    [530000.0, 3400000.0],
                    [530000.0, 3430000.0],
                    [495000.0, 3430000.0],
                    [495000.0, 3400000.0],
                ]
            ],
        }

        # Auto-heal boundary topology
        valid_boundary = repair_invalid_geometry(basin_boundary)
        self.log("Basin boundary topology verified and sealed.")

        return {
            "status": "success",
            "crs": "EPSG:4547",
            "fault_barriers": fault_lines,
            "boundary": valid_boundary,
            "barrier_count": len(fault_lines),
        }
