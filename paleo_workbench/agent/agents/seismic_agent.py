"""Seismic 3D & Horizon Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

from typing import Any

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.planner import TaskNode


class SeismicAgent(BaseAgent):
    """Specialized Agent responsible for seismic volume loading, slicing, and 3D attribute analysis."""

    def __init__(self) -> None:
        super().__init__(
            name="seismic_agent",
            role="Seismic Geophysics Specialist",
            description="Extracts 3D seismic orthogonal slices, calculates coherence attributes, and tracks structural horizons.",
        )

    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Executing seismic volume extraction: {task.description}")

        # #1143-extension: demo stub — NO volume is opened and NO attribute is
        # computed here. The coordinates below are display placeholders, and
        # coherence is explicitly NOT calculated.
        self.log("Seismic stub executed: no volume loaded, no attribute computed.")
        return {
            "status": "success",  # the node ran; nothing was computed
            "stub": True,
            "active_inline": None,
            "active_crossline": None,
            "active_timeslice_ms": None,
            "coherence_calculated": False,
            "volume_loaded": False,
            "note": "演示占位：未加载地震体、未计算相干等属性；坐标字段为空而非虚构值。",
        }
