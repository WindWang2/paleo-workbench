"""Algorithm Registry for Paleo AI GIS Harness.

Catalogues computational algorithms, implementation variants, complexity, and performance models.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AlgorithmMetadata:
    id: str
    name: str
    category: str
    description: str
    time_complexity: str
    space_complexity: str
    has_cpp_accel: bool
    supports_gpu: bool
    min_recommended_elements: int = 100


class AlgorithmRegistry:
    """Central registry of analytical and rendering algorithms."""

    def __init__(self) -> None:
        self._algorithms: dict[str, AlgorithmMetadata] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            AlgorithmMetadata(
                id="dtw_curve_matcher",
                name="Dynamic Time Warping Curve Correlation",
                category="well_log",
                description="Non-linear alignment of well log curves (GR/Resistivity/Impedance) across wells.",
                time_complexity="O(N * M)",
                space_complexity="O(N * M)",
                has_cpp_accel=True,
                supports_gpu=False,
            )
        )
        self.register(
            AlgorithmMetadata(
                id="minmax_4pt_downsample",
                name="4-Point Min-Max LOD Curve Downsampling",
                category="well_log",
                description="Peak-preserving 4-point LOD reduction for high-frequency well curves.",
                time_complexity="O(N)",
                space_complexity="O(K)",
                has_cpp_accel=True,
                supports_gpu=False,
            )
        )
        self.register(
            AlgorithmMetadata(
                id="orthogonal_slice_extract",
                name="Fast 3D Orthogonal Seismic Slice Extraction",
                category="seismic",
                description="Zero-copy / OpenMP accelerated 2D slice extraction along Inline/Crossline/Time.",
                time_complexity="O(H * W)",
                space_complexity="O(H * W)",
                has_cpp_accel=True,
                supports_gpu=False,
            )
        )
        self.register(
            AlgorithmMetadata(
                id="seismic_coherence_3d",
                name="3D Seismic Coherence Attribute",
                category="seismic",
                description="Similarity and discontinuity detection across inline/crossline/sample windows.",
                time_complexity="O(I * X * T)",
                space_complexity="O(I * X * T)",
                has_cpp_accel=True,
                supports_gpu=False,
            )
        )
        self.register(
            AlgorithmMetadata(
                id="constrained_idw_interpolation",
                name="Barrier-Constrained Anisotropic IDW Interpolation",
                category="single_factor",
                description="Spatial single-factor surface interpolation with fault barrier blocking and direction corridors.",
                time_complexity="O(N_grid * N_wells)",
                space_complexity="O(N_grid)",
                has_cpp_accel=False,
                supports_gpu=True,
            )
        )
        self.register(
            AlgorithmMetadata(
                id="gauss_divergence_volume_integral",
                name="Watertight Formation Volume Divergence Integral",
                category="geomodel",
                description="Exact 3D reservoir formation volume evaluation via surface polygon flux integrals.",
                time_complexity="O(N_tris)",
                space_complexity="O(N_tris)",
                has_cpp_accel=False,
                supports_gpu=False,
            )
        )

    def register(self, metadata: AlgorithmMetadata) -> None:
        # #1185: same-id registration is refused — silent override hides
        # cross-feature collisions (complexity/perf models would drift).
        if metadata.id in self._algorithms:
            raise ValueError(
                f"algorithm '{metadata.id}' is already registered; refusing silent "
                "override (pick a unique id)"
            )
        self._algorithms[metadata.id] = metadata

    def get(self, algorithm_id: str) -> AlgorithmMetadata | None:
        return self._algorithms.get(algorithm_id)

    def list_all(self, category: str | None = None) -> list[AlgorithmMetadata]:
        if category is None:
            return list(self._algorithms.values())
        return [a for a in self._algorithms.values() if a.category == category]


algorithm_registry = AlgorithmRegistry()
