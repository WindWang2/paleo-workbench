"""命令注册表（V5-U6）：Command Palette 的唯一真源。

页面导航、面板显隐、主题/密度、布局 preset、项目动作都注册为
``CommandSpec``；最近使用（QSettings，UI 态而非数据权威，decisions.md
D7）供 palette 置顶。注册幂等：同 id 重复注册即替换（调试级日志）。
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
    """

    id: str
    label: str
    hint: str = ""
    keywords: str = ""
    shortcut_hint: str = ""
    callback: Callable[[], None] | None = None
    #: 分组名（palette 显示顺序：最近使用 → 按 label）
    group: str = ""


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

    def find(self, query: str, *, limit: int = 50) -> list[CommandSpec]:
        """子序列模糊匹配（label → keywords → hint 依次加权）。"""
        text = (query or "").strip().lower()
        specs = self.specs()
        if not text:
            return specs[:limit]
        scored: list[tuple[int, CommandSpec]] = []
        for spec in specs:
            label = spec.label.lower()
            haystacks = (
                label,
                f"{spec.keywords} {spec.hint}".lower(),
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
