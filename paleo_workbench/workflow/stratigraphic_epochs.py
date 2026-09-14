"""地层期次目录：项目 horizon 权威 + 内置地质年代方案合并（00-decisions D1）。

期次（epoch）= 编图工作流的时间切片对象，键为项目 horizon 字符串（稳定身份）；
内置地质年代方案（寒武系…第四系，底界年龄 Ma）只用于**识别与排序**——仅当其
名称被项目 horizon 命中时进入目录，绝不虚构项目不存在的期次。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.stratigraphy import (
    active_target_horizon,
    ensure_horizon_catalog,
)


@dataclass(frozen=True)
class StratigraphicEpoch:
    """时间轴上的一个期次刻度。"""

    #: 稳定标识（= 项目 horizon 字符串；切换/写穿都用它）。
    key: str
    #: 显示名（命中内置年代时用年代名，否则原 horizon 文本）。
    label: str
    #: 底界年龄（Ma）；未识别年代为 None（排序时按声明序追加）。
    age_ma: float | None = None


#: 内置地质年代方案（display-only）：label + 底界年龄 Ma，自老到新。
_BUILTIN_PERIODS: tuple[tuple[str, float], ...] = (
    ("震旦系", 635.0),
    ("寒武系", 541.0),
    ("奥陶系", 485.0),
    ("志留系", 444.0),
    ("泥盆系", 419.0),
    ("石炭系", 359.0),
    ("二叠系", 299.0),
    ("三叠系", 252.0),
    ("侏罗系", 201.0),
    ("白垩系", 145.0),
    ("古近系", 66.0),
    ("新近系", 23.0),
    ("第四系", 2.6),
)

BUILTIN_PERIOD_SCHEME: tuple[StratigraphicEpoch, ...] = tuple(
    StratigraphicEpoch(key=label, label=label, age_ma=age)
    for label, age in _BUILTIN_PERIODS
)

_BUILTIN_BY_LABEL: dict[str, float] = dict(_BUILTIN_PERIODS)


def builtin_period_match(name: str) -> tuple[str, float] | None:
    """horizon 文本 → (内置年代名, 底界年龄)；未命中返回 None。

    子串匹配（"寒武系底界" 命中 "寒武系"）；更长年代名优先避免前缀吞并。
    """
    text = str(name or "").strip()
    if not text:
        return None
    for label, age in sorted(_BUILTIN_PERIODS, key=lambda p: -len(p[0])):
        if label in text:
            return label, age
    return None


def build_epoch_catalog(project: ProjectDocument | Any | None) -> list[StratigraphicEpoch]:
    """项目 → 有序期次目录（合并去重；年代可识别者老→新排前，D1）。

    来源顺序（权威优先）：``sequence_boundaries``（空则从数据发现，见
    :func:`ensure_horizon_catalog`）→ PaleoMapDocument.linked_target_horizon →
    FactorMapTask.target_horizon → 当前目标 horizon。
    """
    if project is None:
        return []
    names: list[str] = []

    def _add(name: Any) -> None:
        text = str(name or "").strip()
        if text and text not in names:
            names.append(text)

    try:
        for name in ensure_horizon_catalog(project):
            _add(name)
    except Exception:
        pass  # 目录构建不得因个别工程数据形态中断时间轴
    for doc in getattr(project, "paleomap_documents", None) or []:
        _add(getattr(doc, "linked_target_horizon", ""))
    for task in getattr(project, "factor_map_tasks", None) or []:
        _add(getattr(task, "target_horizon", ""))
    try:
        _add(active_target_horizon(project))
    except Exception:
        pass

    dated: list[StratigraphicEpoch] = []
    undated: list[StratigraphicEpoch] = []
    for name in names:
        match = builtin_period_match(name)
        if match is None:
            undated.append(StratigraphicEpoch(key=name, label=name))
        else:
            label, age = match
            dated.append(StratigraphicEpoch(key=name, label=label, age_ma=age))
    dated.sort(key=lambda e: -e.age_ma)  # 底界年龄大 = 更老 = 排前
    return dated + undated
