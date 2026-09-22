"""命令注册表（V5-U6 / V6）：Command Palette 的唯一真源。

页面导航、面板显隐、主题/密度、布局 preset、项目动作都注册为
``CommandSpec``；最近使用（QSettings，UI 态而非数据权威，decisions.md
D7）供 palette 置顶。注册幂等：同 id 重复注册即替换（调试级日志）。

V6 §4 在 spec 上追加**适用性元数据**（context_tags / stages /
requires_write / applicability 谓词）：注册表据 ``UIContextSnapshot``
（鸭子类型：mapping_stage / write_granted / active_* 字段）评估
``CommandAvailability``。无 context 时一律可用——与 V5 行为逐字节兼容。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

SETTINGS_ORG = "PaleoWorkbench"
SETTINGS_APP = "Workstation"
_RECENT_KEY = "ui/recent_commands"
_RECENT_MAX = 8


@dataclass(frozen=True)
class CommandSpec:
    """一条可执行命令（palette 条目）。

    ``keywords`` 为额外匹配词（拼音缩写/英文别名）；``shortcut_hint``
    仅作展示（真源在 ui.shortcuts）。

    V6 适用性字段（全部可选；缺省 = 任何上下文可用，兼容 V5 注册）：

    * ``context_tags``：发现标签（palette 模糊匹配 haystack 的一部分）；
    * ``stages``：编图阶段 value 白名单（空 = 全阶段）；
    * ``requires_write``：需要 Agent/会话 WRITE 授权；
    * ``hidden_when_unavailable``：不可用时从 palette 隐藏（默认保留并
      显示禁用原因——可发现性优先）；
    * ``applicability``：谓词 ``ctx -> None | 原因``；返回人类可读原因
      字符串表示「禁用 + 原因」，None 表示可用。在 stages/权限门之后
      求值（更具体的领域判断拥有最终解释权）。
    """

    id: str
    label: str
    hint: str = ""
    keywords: str = ""
    shortcut_hint: str = ""
    callback: Callable[[], None] | None = None
    #: 分组名（palette 显示顺序：最近使用 → 按 label）
    group: str = ""
    context_tags: tuple[str, ...] = ()
    stages: tuple[str, ...] = ()
    requires_write: bool = False
    hidden_when_unavailable: bool = False
    applicability: Callable[[object], str | None] | None = None


@dataclass(frozen=True)
class CommandAvailability:
    """命令在给定上下文下的可用性（enabled=False 时必须给出原因）。"""

    enabled: bool
    reason: str = ""


def _stage_reason(stages: tuple[str, ...]) -> str:
    # V10 M10：措辞真源 = canonical evaluator（palette 与工具条同一判词；
    # 此前两套文案对同一语义漂移）。
    from paleo_workbench.mapping.tool_availability import stage_whitelist_reason

    return stage_whitelist_reason(stages)


class CommandRegistry:
    """进程级命令注册表（``command_registry`` 单例）。"""

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}
        self._recent: list[str] = []

    # -- registration ---------------------------------------------------------

    def register(self, spec: CommandSpec) -> None:
        if spec.id in self._specs:
            logger.debug("command 重复注册（替换）: %s", spec.id)
        self._specs[spec.id] = spec

    def unregister(self, command_id: str) -> None:
        self._specs.pop(command_id, None)
        if command_id in self._recent:
            self._recent.remove(command_id)

    def clear(self, *, keep_core: bool = True) -> None:
        """清空注册表（测试隔离用）；``keep_core`` 保留 core: 前缀命令。"""
        for command_id in list(self._specs):
            if keep_core and command_id.startswith("core:"):
                continue
            del self._specs[command_id]

    # -- query ----------------------------------------------------------------

    def specs(self) -> list[CommandSpec]:
        return sorted(self._specs.values(), key=lambda s: (s.group, s.label))

    def get(self, command_id: str) -> CommandSpec | None:
        return self._specs.get(command_id)

    def evaluate(
        self, command_id: str, context: object | None
    ) -> CommandAvailability:
        """评估命令在 ``context``（UIContextSnapshot）下的可用性。

        无 ``context`` → 一律可用（V5 兼容路径）。判定顺序：存在性 →
        WRITE 授权 → 阶段白名单 → 领域谓词。禁用必须带人类可读原因。
        """
        spec = self._specs.get(command_id)
        if spec is None:
            return CommandAvailability(False, "未知命令")
        if context is None:
            return CommandAvailability(True)
        if spec.requires_write and not getattr(context, "write_granted", False):
            return CommandAvailability(False, "需要写入授权（当前会话只读）")
        if spec.stages:
            stage = getattr(context, "mapping_stage", None)
            # Fail-closed（review round 1 P2）：阶段未知（provider 故障/无
            # 工程）时阶段限定命令禁用，不放行。
            if stage is None:
                return CommandAvailability(False, "当前编图阶段未知")
            if stage not in spec.stages:
                return CommandAvailability(False, _stage_reason(spec.stages))
        if spec.applicability is not None:
            try:
                reason = spec.applicability(context)
            except Exception:  # noqa: BLE001 — 谓词崩溃按「不可用」处理
                logger.exception("command applicability 谓词异常: %s", command_id)
                return CommandAvailability(False, "无法判定可用性")
            if reason:
                return CommandAvailability(False, str(reason))
        return CommandAvailability(True)

    def find(
        self,
        query: str,
        *,
        limit: int = 50,
        context: object | None = None,
    ) -> list[CommandSpec]:
        """子序列模糊匹配（label → keywords/tags/hint 依次加权）。

        ``context`` 存在时：``hidden_when_unavailable`` 的不可用命令被
        移除，其余保留（palette 渲染禁用原因）——可发现性优先。
        """
        text = (query or "").strip().lower()
        specs = self.specs()
        if context is not None:
            specs = [
                spec
                for spec in specs
                if not (
                    spec.hidden_when_unavailable
                    and not self.evaluate(spec.id, context).enabled
                )
            ]
        if not text:
            return specs[:limit]
        scored: list[tuple[int, CommandSpec]] = []
        for spec in specs:
            label = spec.label.lower()
            haystacks = (
                label,
                f"{spec.keywords} {' '.join(spec.context_tags)} {spec.hint}".lower(),
            )
            score = _subsequence_score(text, haystacks[0])
            if score < 0:
                score = _subsequence_score(text, haystacks[1])
                if score >= 0:
                    score += 10  # 弱匹配降权
            if score >= 0:
                if label.startswith(text):
                    score -= 5  # 前缀命中优先
                scored.append((score, spec))
        scored.sort(key=lambda pair: pair[0])
        return [spec for _score, spec in scored[:limit]]

    # -- recents ---------------------------------------------------------------

    def record_recent(self, command_id: str) -> None:
        if command_id not in self._specs:
            return
        if command_id in self._recent:
            self._recent.remove(command_id)
        self._recent.insert(0, command_id)
        del self._recent[_RECENT_MAX:]
        self._save_recent()

    def recent_specs(self) -> list[CommandSpec]:
        return [self._specs[cid] for cid in self._recent if cid in self._specs]

    def load_recent(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        stored = settings.value(_RECENT_KEY, []) or []
        if isinstance(stored, str):
            stored = [stored]
        self._recent = [str(cid) for cid in stored][: _RECENT_MAX]

    def _save_recent(self) -> None:
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.setValue(_RECENT_KEY, self._recent)


def _subsequence_score(needle: str, haystack: str) -> int:
    """子序列命中返回起始索引（越小越优），未命中返回 -1。"""
    index = 0
    start = -1
    for char in needle:
        if char.isspace():
            continue
        found = haystack.find(char, index)
        if found < 0:
            return -1
        if start < 0:
            start = found
        index = found + 1
    return max(start, 0)


command_registry = CommandRegistry()
