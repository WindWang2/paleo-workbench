"""AlgorithmSpec registry — 算法能力唯一权威（V9 ADR-5）。

此前算法能力知识散落 ≥5 处（UI 标签表、engine id 映射、capabilities 矩阵、
对话框硬编码、harness 默认列表），且没有任何地方声明
schema/不确定度/CRS/约束支持。本模块收敛为单一注册表：

* ``algorithm_id`` = engine id（kriging/idw/constrained_idw/spline/
  directional/linear/nearest/rbf + factor_fusion）；
* ``aliases`` 覆盖 UI 中文标签与历史写法（canonical 解析）；
* ``supported_constraints`` 投影自 :mod:`constraint_capabilities`
  （engine 约束词汇，约束产品负责地质词汇→engine 词汇映射）；
* ``produces_uncertainty``/``requires_crs``/``requires_unit``/
  ``supports_cancel`` 为显式声明，UI/Agent/Workflow 不再手写判断。

职责边界（goal §32）：Algorithm Library = how to compute；
Template Library（mapping/geological_pipeline/templates）= how to present。
本注册表绝不描述制图模板。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.workflow.constraint_capabilities import (
    ConstraintKind,
    Support,
    capabilities_for_method,
)


@dataclass(frozen=True)
class AlgorithmSpec:
    """一个科学算法的能力声明。"""

    algorithm_id: str
    family: str  # "interpolation" | "fusion"
    display_label: str
    aliases: tuple[str, ...] = ()
    #: UI 方法列表标签（历史值保持不变——tokens.INTERPOLATION_METHODS 派生源）。
    ui_label: str = ""
    #: 轻量参数 schema（JSON-schema 子集；供 UI/harness 校验，不承载科学）。
    parameter_schema: dict[str, Any] = field(default_factory=dict)
    #: 约束支持（engine 词汇；由 constraint_capabilities 权威投影）。
    supported_constraints: dict[str, tuple[str, str]] = field(default_factory=dict)
    supports_cancel: bool = True
    #: 插值/融合是否要求输入声明 CRS（未声明绝不猜测——诚实拒绝/降级）。
    requires_crs: bool = True
    requires_unit: bool = False
    produces_uncertainty: bool = False
    #: 后端（engine/库实现标识）。
    backend: str = ""
    prerequisites: tuple[str, ...] = ()
    notes: str = ""

    def constraint_support(self, kind: ConstraintKind) -> tuple[Support, str]:
        raw = self.supported_constraints.get(kind.value)
        if raw is None:
            return Support.UNSUPPORTED, "not consumed by this method"
        return Support(raw[0]), raw[1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm_id": self.algorithm_id,
            "family": self.family,
            "display_label": self.display_label,
            "ui_label": self.ui_label or self.display_label,
            "aliases": list(self.aliases),
            "parameter_schema": dict(self.parameter_schema),
            "supported_constraints": {
                kind: list(entry) for kind, entry in self.supported_constraints.items()
            },
            "supports_cancel": self.supports_cancel,
            "requires_crs": self.requires_crs,
            "requires_unit": self.requires_unit,
            "produces_uncertainty": self.produces_uncertainty,
            "backend": self.backend,
            "prerequisites": list(self.prerequisites),
        }


def _from_capabilities(
    algorithm_id: str,
    label: str,
    *,
    aliases: tuple[str, ...] = (),
    ui_label: str = "",
    parameter_schema: dict[str, Any] | None = None,
    produces_uncertainty: bool = False,
    backend: str = "",
    notes: str = "",
) -> AlgorithmSpec:
    try:
        caps = capabilities_for_method(algorithm_id)
    except KeyError:
        caps = None
    support = {}
    if caps is not None:
        for kind, (level, note) in caps.support.items():
            support[kind.value] = (level.value, note)
    return AlgorithmSpec(
        algorithm_id=algorithm_id,
        family="interpolation",
        display_label=label,
        aliases=aliases,
        ui_label=ui_label or label,
        parameter_schema=parameter_schema or {},
        supported_constraints=support,
        produces_uncertainty=produces_uncertainty,
        backend=backend,
        prerequisites=tuple(caps.prerequisites) if caps else (),
        notes=notes,
    )


#: UI 方法列表顺序（tokens.INTERPOLATION_METHODS 的注册表权威来源）。
UI_INTERPOLATION_METHODS: tuple[str, ...] = (
    "kriging", "idw", "constrained_idw", "spline", "directional",
)

ALGORITHMS: dict[str, AlgorithmSpec] = {
    spec.algorithm_id: spec
    for spec in (
        _from_capabilities(
            "kriging", "克里金",
            ui_label="克里金",
            aliases=("克里金", "克里金(MVP·线性)", "ordinary_kriging", "ok"),
            parameter_schema={
                "type": "object",
                "properties": {
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 2000},
                    "variogram_model": {
                        "type": "string",
                        "enum": ["spherical", "exponential", "gaussian"],
                    },
                },
            },
            produces_uncertainty=True,  # kriging variance grid
            backend="kriging",
        ),
        _from_capabilities(
            "idw", "IDW 反距离加权",
            ui_label="IDW",
            aliases=("IDW", "反距离加权", "IDW反距离加权"),
            parameter_schema={
                "type": "object",
                "properties": {
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 2000},
                    "power": {"type": "number", "minimum": 0.5, "maximum": 8.0},
                },
            },
            backend="idw",
        ),
        _from_capabilities(
            "constrained_idw", "约束IDW",
            ui_label="约束IDW",
            aliases=("约束IDW", "约束反距离加权", "constrained idw"),
            parameter_schema={
                "type": "object",
                "properties": {
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 2000},
                    "power": {"type": "number", "minimum": 0.5, "maximum": 8.0},
                },
            },
            backend="constrained_idw",
        ),
        _from_capabilities(
            "spline", "样条 (CloughTocher)",
            ui_label="样条",
            aliases=("样条", "spline", "cubic", "样条插值"),
            backend="cubic",
        ),
        _from_capabilities(
            "directional", "方向趋势",
            ui_label="方向趋势",
            aliases=("方向趋势", "方向趋势面", "directional trend"),
            parameter_schema={
                "type": "object",
                "properties": {
                    "azimuth_deg": {"type": "number", "minimum": 0, "maximum": 360},
                    "semi_major": {"type": "number", "exclusiveMinimum": 0},
                    "semi_minor": {"type": "number", "exclusiveMinimum": 0},
                },
            },
            backend="directional",
        ),
        _from_capabilities("linear", "线性插值", aliases=("线性插值", "linear")),
        _from_capabilities("nearest", "最近邻", aliases=("最近邻", "nearest")),
        _from_capabilities("rbf", "RBF 多二次", aliases=("RBF", "rbf", "RBF 多二次")),
        AlgorithmSpec(
            algorithm_id="factor_fusion",
            family="fusion",
            display_label="多因素证据融合",
            aliases=("factor_fusion", "融合", "多因素融合", "weighted_evidence"),
            parameter_schema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["weighted_evidence", "rule_based"],
                    },
                    "class_thresholds": {"type": "array", "items": {"type": "number"}},
                },
            },
            # 融合的约束支持=空（约束在插值阶段消费；融合输入是 factor grids）。
            supported_constraints={},
            requires_crs=True,  # P0-5：混合声明纪律拒绝；全未声明 qc 降级
            produces_uncertainty=True,  # confidence grid + 方差传播（有方差输入时）
            backend="factor_fusion",
            notes="不确定性=coverage×agreement 置信格 + 公共支撑方差传播",
        ),
    )
}


def _rebuild_alias_index() -> None:
    _ALIAS_INDEX.clear()
    for spec in ALGORITHMS.values():
        _ALIAS_INDEX[spec.algorithm_id.lower()] = spec.algorithm_id
        for alias in spec.aliases:
            _ALIAS_INDEX[alias.lower()] = spec.algorithm_id


def register_algorithm(spec: AlgorithmSpec) -> None:
    """注册（或替换）算法声明（测试/扩展用）；别名索引同步重建。"""
    ALGORITHMS[spec.algorithm_id] = spec
    _rebuild_alias_index()


def get_algorithm(algorithm_id: str) -> AlgorithmSpec | None:
    return ALGORITHMS.get(str(algorithm_id or "").strip())


#: 别名 → algorithm_id（注册时经 _rebuild_alias_index 重建）。
_ALIAS_INDEX: dict[str, str] = {}
_rebuild_alias_index()


def canonical_algorithm_id(label_or_id: str) -> str:
    """任意 UI 标签/历史写法/engine id → 规范 algorithm_id。

    无法识别 → ValueError（不静默回退到默认方法——那正是词表漂移的来源）。
    """
    text = str(label_or_id or "").strip()
    if not text:
        raise ValueError("empty algorithm reference")
    resolved = _ALIAS_INDEX.get(text.lower())
    if resolved is None:
        raise ValueError(f"unknown algorithm: {label_or_id!r}")
    return resolved


def display_label(algorithm_id: str) -> str:
    spec = get_algorithm(canonical_algorithm_id(algorithm_id))
    return spec.display_label if spec else str(algorithm_id)


def ui_interpolation_methods() -> list[str]:
    """UI 方法列表（中文标签，按注册表顺序）——tokens 表的权威来源。"""
    return [
        (ALGORITHMS[a].ui_label or ALGORITHMS[a].display_label)
        for a in UI_INTERPOLATION_METHODS
        if a in ALGORITHMS
    ]


def interpolation_algorithm_labels() -> dict[str, str]:
    """UI 标签 → algorithm_id（供既有 label→engine 映射统一派生）。"""
    return {
        (ALGORITHMS[a].ui_label or ALGORITHMS[a].display_label): a
        for a in UI_INTERPOLATION_METHODS
        if a in ALGORITHMS
    }
