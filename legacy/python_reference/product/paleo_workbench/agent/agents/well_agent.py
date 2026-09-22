"""Well Logging & Stratigraphy Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

from typing import Any
import numpy as np

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.planner import TaskNode
from paleo_workbench.viz.dtw_log_matcher import DTWLogMatcher


class WellAgent(BaseAgent):
    """Specialized Agent responsible for well log analysis, DTW correlation, and formation tops."""

    def __init__(self) -> None:
        super().__init__(
            name="well_agent",
            role="Well Log & Stratigraphy Specialist",
            description="Performs automated well log curve matching, depth normalization, and stratigraphic tops transfer.",
        )
        self.matcher = DTWLogMatcher()

    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Executing well stratigraphy analysis: {task.description}")

        target_horizon = task.parameters.get("target_horizon", "T3x")
        self.log(f"Target formation horizon identified as: {target_horizon}")

        # #1143: demo stub — never fabricate well points. Enumerate the real
        # project wells (identity + location only); no correlation, sand
        # ratio or thickness is computed here.
        project = context.get("project")
        well_points: list[dict[str, Any]] = []
        for well in list(getattr(project, "wells", None) or []):
            x = getattr(well, "project_x", None)
            if x is None:
                x = getattr(well, "surface_x", None)
            y = getattr(well, "project_y", None)
            if y is None:
                y = getattr(well, "surface_y", None)
            well_points.append(
                {
                    "well": str(getattr(well, "name", "") or ""),
                    "x": x,
                    "y": y,
                    "sand_ratio": None,
                    "thickness": None,
                    "qc_flag": "unverified",
                }
            )

        self.log(f"Enumerated {len(well_points)} project wells (uncorrelated stub).")
        return {
            "status": "success",
            "target_horizon": target_horizon,
            "well_points": well_points,
            "correlated_well_count": len(well_points),
            "stub": True,
            "note": "演示占位：仅枚举项目井位，未执行 DTW 对比与砂地比计算。",
        }
