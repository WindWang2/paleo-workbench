"""StratigraphicCorrelationEngine: Fluent Pipeline Builder unifying multi-well correlation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self
import numpy as np

from paleo_workbench.viz.dtw_log_matcher import AlignmentResult, DTWLogMatcher
from paleo_workbench.viz.formation_top_correlator import (
    FormationTopCorrelator,
    TopRecommendation,
)
from paleo_workbench.viz.well_section_datum import WellSectionDatum


@dataclass
class CorrelationSectionResult:
    """Unified data product output by StratigraphicCorrelationEngine execution."""

    shifts: dict[str, float]
    polygons: list[dict[str, Any]]
    recommendations: dict[str, TopRecommendation]
    alignments: dict[tuple[str, str], AlignmentResult]


class StratigraphicCorrelationEngine:
    """Deep module unifying datum alignment, DTW curve matching, and top correlation via a fluent API."""

    def __init__(
        self,
        datum_engine: WellSectionDatum | None = None,
        dtw_matcher: DTWLogMatcher | None = None,
        top_correlator: FormationTopCorrelator | None = None,
    ) -> None:
        """Initialize the correlation engine with optional sub-engine injection."""
        self._datum_engine = datum_engine or WellSectionDatum()
        self._dtw_matcher = dtw_matcher or DTWLogMatcher()
        self._top_correlator = top_correlator or FormationTopCorrelator(dtw_matcher=self._dtw_matcher)

        self._wells: list[dict[str, Any]] = []
        self._datum_mode: str = "md"
        self._target_horizon: str | None = None
        self._kb_elevations: dict[str, float] = {}
        self._x_positions: dict[str, float] = {}
        self._dtw_window: int | None = None
        self._depth_step: float = 0.5

    def with_wells(self, wells: list[dict[str, Any]]) -> Self:
        """Bind well section data objects to the pipeline."""
        self._wells = wells
        return self

    def with_datum(
        self,
        mode: str = "md",
        target_horizon: str | None = None,
        kb_elevations: dict[str, float] | None = None,
    ) -> Self:
        """Configure vertical datum alignment policy ('md', 'tvdss', or 'horizon')."""
        self._datum_mode = mode
        self._target_horizon = target_horizon
        if kb_elevations is not None:
            self._kb_elevations = kb_elevations
        return self

    def with_layout(self, x_positions: dict[str, float]) -> Self:
        """Configure horizontal X coordinate offsets for wells in cross-section layout."""
        self._x_positions = x_positions
        return self

    def with_dtw_config(self, window: int | None = None, depth_step: float = 0.5) -> Self:
        """Configure Dynamic Time Warping curve matching parameters."""
        self._dtw_window = window
        self._depth_step = depth_step
        return self

    def compute_shifts(self) -> dict[str, float]:
        """Calculate vertical depth shifts for all loaded wells."""
        return self._datum_engine.compute_shifts(
            wells=self._wells,
            mode=self._datum_mode,
            target_horizon=self._target_horizon,
            kb_elevations=self._kb_elevations,
        )

    def align_curves(
        self,
        ref_well: str,
        target_well: str,
        curve_key: str = "GR",
    ) -> AlignmentResult:
        """Compute optimal non-linear DTW curve alignment between two wells."""
        ref_curve = self._get_well_curve(ref_well, curve_key)
        target_curve = self._get_well_curve(target_well, curve_key)
        return self._dtw_matcher.match_curves(ref_curve, target_curve, window=self._dtw_window)

    def recommend_top(
        self,
        ref_well: str,
        target_well: str,
        ref_top_depth: float,
        curve_key: str = "GR",
    ) -> TopRecommendation:
        """Auto-recommend target well formation top depth using DTW curve matching."""
        ref_curve = self._get_well_curve(ref_well, curve_key)
        target_curve = self._get_well_curve(target_well, curve_key)
        return self._top_correlator.recommend_top_depth(
            ref_curve=ref_curve,
            target_curve=target_curve,
            ref_top_depth=ref_top_depth,
            depth_step=self._depth_step,
        )

    def generate_polygons(self, top_names: list[str]) -> list[dict[str, Any]]:
        """Generate inter-well correlation polygon quads across all adjacent wells."""
        shifts = self.compute_shifts()
        all_polygons: list[dict[str, Any]] = []

        for i in range(len(self._wells) - 1):
            w_a = self._wells[i]
            w_b = self._wells[i + 1]
            x_a = self._x_positions.get(w_a.get("name", ""), float(i * 200))
            x_b = self._x_positions.get(w_b.get("name", ""), float((i + 1) * 200))

            polys = self._top_correlator.compute_correlation_polygons(
                well_a=w_a,
                well_b=w_b,
                x_a=x_a,
                x_b=x_b,
                top_names=top_names,
                shifts=shifts,
            )
            all_polygons.extend(polys)

        return all_polygons

    def execute(self, top_names: list[str], curve_key: str = "GR") -> CorrelationSectionResult:
        """Execute the full correlation pipeline and produce unified cross-section assets."""
        shifts = self.compute_shifts()
        polygons = self.generate_polygons(top_names)
        alignments: dict[tuple[str, str], AlignmentResult] = {}
        recommendations: dict[str, TopRecommendation] = {}

        for i in range(len(self._wells) - 1):
            w_a_name = self._wells[i].get("name", "")
            w_b_name = self._wells[i + 1].get("name", "")
            if w_a_name and w_b_name:
                alignments[(w_a_name, w_b_name)] = self.align_curves(w_a_name, w_b_name, curve_key)

        return CorrelationSectionResult(
            shifts=shifts,
            polygons=polygons,
            recommendations=recommendations,
            alignments=alignments,
        )

    def _get_well_curve(self, well_name: str, curve_key: str) -> np.ndarray:
        """Extract curve log array for a named well."""
        for w in self._wells:
            if w.get("name") == well_name:
                curves = w.get("curves", {})
                if curve_key in curves:
                    return np.asarray(curves[curve_key], dtype=np.float64)
        return np.array([], dtype=np.float64)
