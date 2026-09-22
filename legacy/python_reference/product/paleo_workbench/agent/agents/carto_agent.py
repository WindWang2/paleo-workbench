"""Cartography & Single-Factor Mapping Agent for Paleo AI GIS Swarm."""

from __future__ import annotations

from typing import Any
import numpy as np

from paleo_workbench.agent.agents.base import BaseAgent
from paleo_workbench.agent.planner import TaskNode


class CartographyAgent(BaseAgent):
    """Specialized Agent responsible for single-factor surface interpolation, contour generation, and facies boundaries."""

    def __init__(self) -> None:
        super().__init__(
            name="carto_agent",
            role="Cartography & Surface Specialist",
            description="Generates barrier-constrained anisotropic IDW grids, extracts isoline contours, and synthesizes paleofacies regions.",
        )

    def run(self, task: TaskNode, context: dict[str, Any]) -> dict[str, Any]:
        self.log(f"Executing cartographic surface generation: {task.description}")

        target_horizon = task.parameters.get("target_horizon", "T3x")
        factor_type = task.parameters.get("factor_type", "sand_ratio")

        # #1143-extension: demo stub — this grid is a SYNTHETIC analytical
        # surface (smooth trend), not an interpolation of well data. It must
        # never be consumed as a geological result.
        grid_h, grid_w = 50, 50
        x = np.linspace(495000.0, 530000.0, grid_w)
        y = np.linspace(3400000.0, 3430000.0, grid_h)
        xx, yy = np.meshgrid(x, y)

        # Smooth trend + local variation
        grid_values = 0.4 + 0.2 * np.sin((xx - 495000.0) / 10000.0) * np.cos((yy - 3400000.0) / 10000.0)
        grid_values = np.clip(grid_values, 0.05, 0.85)

        self.log(
            f"Generated SYNTHETIC {grid_h}x{grid_w} demo grid for {target_horizon} "
            f"({factor_type}) — not an interpolation of well data (stub)."
        )

        # Contour levels a real workflow would extract (none are extracted here).
        contour_levels = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7]

        return {
            "status": "success",  # the node ran; the grid itself is NOT a result
            "stub": True,
            "target_horizon": target_horizon,
            "factor_type": factor_type,
            "grid_shape": (grid_h, grid_w),
            "grid_source": "synthetic_demo",
            "value_min": float(grid_values.min()),
            "value_max": float(grid_values.max()),
            "contour_levels": contour_levels,
            "grid_data": grid_values,
            "interpolated_from_wells": False,
            "note": "演示占位：网格为合成解析面，未使用井数据插值，不可作为地质成果使用。",
        }
