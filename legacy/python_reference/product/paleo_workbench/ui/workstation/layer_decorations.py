"""图层呈现态聚合（V7 goal §7）：树/检查器共用的装饰真源。

设计约束：

* **纯数据**：不 import Qt——呈现态的计算可全量单测；
* **不建第二权威**：输入全部来自既有权威的**结论**
  （``LayerGroupController.layer_freshness`` / membership 成熟度 /
  ``VectorEditSession`` 会话态）；本模块只定义聚合与呈现次序；
* **词汇单一**：装饰 glyph/label/tone 一律经 ``state_language``
  （freshness/session/maturity 词表），不另造词；
* **诚实**：未知 = 无装饰（显示空白比编造状态更诚实）；缺失图层
  （不在编辑注册表）显式「缺失」。
"""
from __future__ import annotations

from dataclasses import dataclass

from paleo_workbench.ui.workstation.state_language import StateToken, state_token

__all__ = [
    "GroupPresentationSummary",
    "LayerPresentationState",
    "decoration_summary_text",
    "decoration_token",
    "primary_decoration",
    "presentation_state",
]


@dataclass(frozen=True, slots=True)
class LayerPresentationState:
    """一个图层的呈现信号集（全部默认 False/None = 干净）。"""

    editing: bool = False
    dirty: bool = False              # 会话有未保存修改（undo 栈非空）
    stale: bool = False
    missing_input: bool = False      # 新鲜度：输入缺失（error 级）
    superseded: bool = False         # 新鲜度：已被取代
    degraded: bool = False           # 数据源降级（参考图层刷新失败等）
    maturity: str | None = None      # raw/draft/reviewed/frozen/published
    missing: bool = False            # 图层不在编辑注册表（被删除/未落盘）


#: 装饰优先级（前者胜出；状态列只显示一个主信号，hover 显示全部）。
_PRIORITY = (
    "missing",
    "dirty",
    "editing",
    "missing_input",
    "superseded",
    "stale",
    "degraded",
    "frozen",
    "published",
    "reviewed",
)


def _token_for(kind: str, state: LayerPresentationState) -> StateToken | None:
    if kind == "missing":
        return state_token("freshness", "missing")
    if kind == "dirty":
        return state_token("session", "dirty")
    if kind == "editing":
        return state_token("session", "editing")
    if kind == "missing_input":
        return state_token("freshness", "missing_input")
    if kind == "superseded":
        return state_token("freshness", "superseded")
    if kind == "stale":
        return state_token("freshness", "stale")
    if kind == "degraded":
        return state_token("backend", "fallback")
    if kind in ("frozen", "published", "reviewed"):
        return state_token("maturity", kind)
    return None


def primary_decoration(
    state: LayerPresentationState,
) -> tuple[str, StateToken] | None:
    """主装饰（状态列单信号；None = 干净无装饰）。"""
    flags = {
        "missing": state.missing,
        "dirty": state.dirty,
        "editing": state.editing and not state.dirty,
        "missing_input": state.missing_input,
        "superseded": state.superseded,
        "stale": state.stale,
        "degraded": state.degraded,
        "frozen": state.maturity == "frozen",
        "published": state.maturity == "published",
        "reviewed": state.maturity == "reviewed",
    }
    for kind in _PRIORITY:
        if flags.get(kind):
            token = _token_for(kind, state)
            if token is not None:
                return kind, token
    return None


def decoration_token(state: LayerPresentationState) -> StateToken | None:
    """主装饰的词汇 token（glyph+label+tone）。"""
    primary = primary_decoration(state)
    return primary[1] if primary is not None else None


def decoration_summary_text(state: LayerPresentationState) -> str:
    """hover 摘要：全部信号（非仅主信号）拼为「·」分隔文本。"""
    parts: list[str] = []
    if state.missing:
        parts.append("图层不在编辑注册表（缺失）")
    if state.editing and state.dirty:
        parts.append(state_token("session", "dirty").label)
    elif state.editing:
        parts.append(state_token("session", "editing").label)
    if state.missing_input:
        parts.append(state_token("freshness", "missing_input").label)
    if state.superseded:
        parts.append(state_token("freshness", "superseded").label)
    if state.stale:
        parts.append(state_token("freshness", "stale").label)
    if state.degraded:
        parts.append("数据源降级")
    if state.maturity in ("raw", "frozen", "published", "reviewed"):
        parts.append(state_token("maturity", state.maturity).label)
    return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class GroupPresentationSummary:
    """组级真实聚合（goal §7：stale/error/running/pending/published 计数）。

    计数来自 ``LayerGroupController.group_summary`` + 任务/成熟度权威；
    本类只承载与呈现。
    """

    group_id: str
    title: str
    layers: int = 0
    stale: int = 0
    errors: int = 0
    running: int = 0
    pending: int = 0
    frozen: int = 0
    published: int = 0

    @property
    def has_problems(self) -> bool:
        return self.stale > 0 or self.errors > 0

    def summary_text(self) -> str:
        parts = [f"{self.layers} 层"]
        if self.errors:
            parts.append(f"✕ {self.errors}")
        if self.stale:
            parts.append(f"↻ {self.stale}")
        if self.running:
            parts.append(f"▶ {self.running}")
        if self.pending:
            parts.append(f"… {self.pending}")
        if self.frozen:
            parts.append(f"❄ {self.frozen}")
        if self.published:
            parts.append(f"◉ 已发布 {self.published}")
        if not (self.errors or self.stale or self.running or self.pending
                or self.frozen or self.published):
            parts.append("无异常")
        return " · ".join(parts)


def presentation_state(
    *,
    editing: bool = False,
    session_undo_depth: int = 0,
    freshness_status: str | None = None,
    maturity: str | None = None,
    missing: bool = False,
    degraded: bool = False,
) -> LayerPresentationState:
    """从权威结论构造呈现态（宿主适配器的规范入口）。

    ``freshness_status`` 为 ``FreshnessStatus.value``（None = 未知 → 无
    新鲜度信号）；``session_undo_depth>0`` 视为 dirty（会话存在未保存
    修改的既有判据）。
    """
    status = str(freshness_status or "")
    return LayerPresentationState(
        editing=editing,
        dirty=editing and session_undo_depth > 0,
        stale=status == "stale",
        missing_input=status == "missing_input",
        superseded=status == "superseded",
        degraded=degraded,
        maturity=maturity,
        missing=missing,
    )
