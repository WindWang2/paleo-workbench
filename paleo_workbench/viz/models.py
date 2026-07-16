from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

# Workbench viz kinds map 1:1 onto geo-viz-engine product surfaces where possible.
VizKind = Literal[
    "well_log",
    "seismic",
    "map",
    "cross_well",
    "prediction",
    "engine_preview",  # PreparedPreview from GeoVizEngine (plots / tops / TD / SEGY-2D)
    "message",
]


@dataclass(frozen=True)
class VizRef:
    kind: VizKind
    id: str
    path: str = ""
    label: str = ""
    source: str = ""
    # Optional multi-well resource ids for cross_well sections.
    related_ids: tuple[str, ...] = ()


@dataclass
class VizPayload:
    """UI-agnostic payload; hosts apply engine widgets without re-parsing.

    Prefer engine-native handles:
    - ``well_log`` → WellLogData from ``load_las_preview``
    - ``seismic_path`` → ``SeismicView.load_segy`` (true geometry)
    - ``seismic_volume`` → ``load_demo`` fallback / prediction mock
    - ``prepared`` → ``GeoVizEngine.render`` for PreviewKind backends
    """

    kind: VizKind
    label: str
    message: str = ""
    warning: str = ""
    well_log: Any = None
    seismic_volume: np.ndarray | None = None
    seismic_path: str = ""
    map_features: list[dict[str, Any]] | None = None
    map_wells: list[dict[str, Any]] | None = None
    period_name: str = ""
    # Multi-well logs for cross-well host (list of WellLogData).
    well_logs: list[Any] = field(default_factory=list)
    well_names: list[str] = field(default_factory=list)
    # Engine PreparedPreview for plots / formation / SEGY-2D scrub widget.
    prepared: Any = None
