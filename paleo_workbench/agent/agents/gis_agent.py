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

        # #1143/#1143-extension: demo stub — these fault barriers are SYNTHETIC
        # demo geometry, not data extracted from any interpreted fault pick.
        # Never present them as project-derived constraints.
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

        # Auto-heal boundary topology — this repair DOES run for real, but on
        # the synthetic demo boundary above; it proves nothing about project data.
        valid_boundary = repair_invalid_geometry(basin_boundary)
        self.log(
            "Demo boundary repaired; NO topology claim is made about project data (stub)."
        )

        return {
            "status": "success",  # the node ran; not a verification verdict
            "stub": True,
            "crs": "EPSG:4547",
            "fault_barriers": fault_lines,
            "fault_barriers_source": "synthetic_demo",
            "boundary": valid_boundary,
            "barrier_count": len(fault_lines),
            "topology_verified": False,
            "note": "演示占位：断层屏障为合成演示几何，边界修复仅作用于该合成边界，未对项目数据做任何拓扑断言。",
        }
