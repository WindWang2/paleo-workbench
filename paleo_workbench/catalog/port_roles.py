"""Endpoint role vocabulary for typed lineage ports (V11 docs 06 §2).

Open vocabulary: any role string is legal on a RunPort — these constants
exist so business modules spell the common ports identically instead of
drifting ("well_log" vs "well_logs" vs "logs"). Unknown roles read back
verbatim and group under "other" in UIs.
"""

from __future__ import annotations

# Input-side roles
WELL_LOGS = "well_logs"             # one or more log curve files
SONIC = "sonic"
DENSITY = "density"
GAMMA = "gamma"
RESISTIVITY = "resistivity"
LITHOLOGY = "lithology"
TRAJECTORY = "trajectory"
TOPS = "tops"
TIME_DEPTH = "time_depth"
CHECKSHOT = "checkshot"
SEISMIC_VOLUME = "seismic_volume"
HORIZON = "horizon"
FAULTS = "faults"
CONSTRAINTS = "constraints"
CONSTRAINT_GROUPS = "constraint_groups"
FACTOR_GRIDS = "factor_grids"
BASEMAP = "basemap"
MODEL = "model"
MODEL_VERSION = "model_version"
STRATIGRAPHY = "stratigraphy"

# Output-side roles
PREDICTION = "prediction"
NORMALIZED_LOG = "normalized_log"
FACTOR_GRID = "factor_grid"
FUSION_RESULT = "fusion_result"
MAP_PRODUCT = "map_product"
CORRELATION = "correlation"
CALIBRATED_TD = "calibrated_td"
QC_REPORT = "qc_report"
EXPORT = "export"
INTERPRETATION = "interpretation"

_REGISTRY: dict[str, str] = {}


def _register(*names: str, display: str = "") -> None:
    for name in names:
        _REGISTRY[name] = display or name


_register(WELL_LOGS, display="测井曲线")
_register(SONIC, DENSITY, GAMMA, RESISTIVITY, LITHOLOGY, display="曲线")
_register(TRAJECTORY, display="井斜")
_register(TOPS, display="分层")
_register(TIME_DEPTH, CHECKSHOT, display="时深")
_register(SEISMIC_VOLUME, display="地震体")
_register(HORIZON, display="层位")
_register(FAULTS, display="断层")
_register(CONSTRAINTS, CONSTRAINT_GROUPS, display="制图约束")
_register(FACTOR_GRIDS, FACTOR_GRID, display="因子格网")
_register(BASEMAP, display="底图")
_register(MODEL, MODEL_VERSION, display="模型")
_register(STRATIGRAPHY, display="地层框架")
_register(PREDICTION, display="预测结果")
_register(NORMALIZED_LOG, display="标准化曲线")
_register(FUSION_RESULT, display="融合结果")
_register(MAP_PRODUCT, display="成图产品")
_register(CORRELATION, display="对比成果")
_register(CALIBRATED_TD, display="标定时深")
_register(QC_REPORT, display="QC 报告")
_register(EXPORT, display="导出")
_register(INTERPRETATION, display="解释成果")


def display_for(role: str) -> str:
    """Human label for a port role (verbatim fallback for unknown roles)."""
    return _REGISTRY.get(str(role or ""), str(role or ""))
