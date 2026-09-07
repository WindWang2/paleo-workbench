"""统一状态语言（V6 §5）：全域状态 → glyph+文字+tone 的单一映射。

设计约束：

* **双信号**：每个状态都有 glyph 与文字；tone 只供样式层（badge/徽标）
  使用，绝不是唯一信号（高对比/色弱可读）。
* **诚实未知**：未知值 → 「未知」+ muted；未知类别是编程错误 → KeyError。
* 消费者：状态条工作台段（``workbench_context_text``）、检查器徽标、
  任务中心、Agent 面板。不定义第二套颜色系统——tone 由既有 token/QSS
  消费方解释。
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class StateToken:
    """一个域状态的呈现词汇（glyph 与 label 均为非颜色信号）。"""

    glyph: str
    label: str
    tone: str  # ok | info | warn | error | muted | locked（样式层解释）


_UNKNOWN = StateToken("·", "未知", "muted")

_VOCABULARY: dict[str, dict[str, StateToken]] = {
    "maturity": {
        "raw": StateToken("▣", "RAW 原始", "locked"),
        "derived": StateToken("◈", "派生", "info"),
        "intermediate": StateToken("◇", "中间成果", "info"),
        "output": StateToken("★", "成果", "ok"),
        "working": StateToken("✎", "工作副本", "info"),
        "draft": StateToken("✎", "草稿", "info"),
        "reviewed": StateToken("✓", "已复核", "ok"),
        "frozen": StateToken("❄", "冻结", "locked"),
        "published": StateToken("◉", "已发布", "ok"),
    },
    "freshness": {
        "current": StateToken("✓", "最新", "ok"),
        "stale": StateToken("↻", "已过期", "warn"),
        "missing": StateToken("✕", "缺失", "error"),
        # V7 §7（树装饰）：对齐 dependencies.FreshnessStatus 全集——
        # missing_input/superseded 此前只有域侧中文标签，无 glyph/tone。
        "missing_input": StateToken("✕", "输入缺失", "error"),
        "superseded": StateToken("↻", "已被取代", "warn"),
        "unknown": StateToken("·", "状态未知", "muted"),
    },
    # V7 §7：编辑会话呈现态（图层级 dirty 信号）。
    "session": {
        "editing": StateToken("✎", "编辑中", "info"),
        "dirty": StateToken("✎", "未保存修改", "warn"),
    },
    "editability": {
        "editable": StateToken("✎", "可编辑", "ok"),
        "raw": StateToken("▣", "RAW 不可编辑", "locked"),
        # 「⊘」取代旧 emoji 🔒（goal §7 禁止 emoji；字形+文字双信号保留）。
        "locked": StateToken("⊘", "证据锁定", "locked"),
        "none": StateToken("·", "无编辑目标", "muted"),
    },
    "task": {
        "queued": StateToken("…", "排队中", "muted"),
        "running": StateToken("▶", "运行中", "info"),
        "cancelling": StateToken("⏸", "取消中", "warn"),
        "cancelled": StateToken("■", "已取消", "muted"),
        "failed": StateToken("✕", "失败", "error"),
        "done": StateToken("✓", "完成", "ok"),
    },
    "backend": {
        "native": StateToken("◆", "原生", "ok"),
        "fallback": StateToken("◌", "回退", "warn"),
        "missing": StateToken("✕", "不可用", "error"),
    },
    "permission": {
        "granted": StateToken("✓", "已授权写入", "ok"),
        "read_only": StateToken("▣", "只读会话", "muted"),
    },
}


def state_token(category: str, value: str | None) -> StateToken:
    """查词汇；未知值诚实返回「未知」，未知类别是编程错误（KeyError）。"""
    table = _VOCABULARY[category]  # 未知类别：尽早暴露
    if value is None:
        return _UNKNOWN
    return table.get(str(value), _UNKNOWN)


def workbench_context_text(
    snapshot,
    *,
    layer_name: Callable[[str], str] | None = None,
) -> str:
    """状态条工作台段文案：「阶段 · 编辑目标 · 后端 · 任务」。

    无任务不渲染任务段；被拒编辑目标必须显示原因；回退画布必须可见。
    """
    parts: list[str] = []
    if snapshot.mapping_stage_label:
        parts.append(str(snapshot.mapping_stage_label))
    target = snapshot.active_layer_id
    if target is not None and layer_name is not None:
        name = layer_name(str(target))
        if snapshot.active_layer_editable is False:
            reason = snapshot.active_layer_block_reason or "不可编辑"
            parts.append(f"{name} — {reason}")
        elif snapshot.editing_active:
            parts.append(f"编辑中：{name}")
        else:
            parts.append(f"目标：{name}")
    elif snapshot.active_layer_block_reason and target is None:
        parts.append(str(snapshot.active_layer_block_reason))
    if snapshot.qgis_bridge_available is True:
        parts.append("QGIS 原生")
    elif snapshot.qgis_bridge_available is False:
        parts.append("画布回退（QGIS 桥不可用）")
    if snapshot.running_task_count:
        parts.append(f"任务 ×{int(snapshot.running_task_count)}")
    if not parts:
        parts.append("未打开工程" if not snapshot.project_open else "就绪")
    return " · ".join(parts)
