from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

VizKind = Literal["well_log", "seismic", "map", "prediction", "message"]


@dataclass(frozen=True)
class VizRef:
    kind: VizKind
    id: str
    path: str = ""
    label: str = ""
    source: str = ""


@dataclass
class VizPayload:
    kind: VizKind
    label: str
    message: str = ""
    warning: str = ""
    well_log: Any = None  # WellLogData | None
    seismic_volume: np.ndarray | None = None
    map_features: list[dict[str, Any]] | None = None
    map_wells: list[dict[str, Any]] | None = None
    period_name: str = ""
