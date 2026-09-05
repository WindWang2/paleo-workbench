"""中央快捷键注册表（V5-U6）。

所有应用级 QShortcut 经 :func:`register_shortcut` 创建（记录 id/键/标签/
回调归属），冲突检测 :func:`conflicts` 报告同一 QKeySequence 的重复注册
（Qt 语义：后注册者先触发；检测只告警不阻断，日志 warning）。
Command Palette 从这里取 shortcut 展示文案。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShortcutSpec:
    id: str
    key: str            # QKeySequence 可解析的字符串（如 "Ctrl+K"）
    label: str          # 展示名（palette / 文档用）


_registry: dict[str, ShortcutSpec] = {}
_shortcuts: dict[str, QShortcut] = {}


def register_shortcut(
    parent: QWidget,
    spec: ShortcutSpec,
    callback: Callable[[], None],
    *,
    enabled_in_text_input: bool = True,
) -> QShortcut:
    """创建 QShortcut 并登记。同 id 重复注册替换旧绑定。"""
    old = _shortcuts.pop(spec.id, None)
    if old is not None:
        # 旧宿主窗口销毁时 C++ 对象可能已被级联删除（多 AppShell 构造的测试）
        try:
            old.setParent(None)
            old.deleteLater()
        except RuntimeError:
            pass
    shortcut = QShortcut(QKeySequence(spec.key), parent)
    shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
    shortcut.activated.connect(callback)
    if not enabled_in_text_input:
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
    _shortcuts[spec.id] = shortcut
    _registry[spec.id] = spec
    _warn_conflicts(spec)
    return shortcut


def register_meta(spec: ShortcutSpec) -> None:
    """仅登记元数据（快捷键由历史代码创建时使用，palette 展示对齐）。"""
    _registry[spec.id] = spec
    _warn_conflicts(spec)


def unregister(spec_id: str) -> None:
    _registry.pop(spec_id, None)
    shortcut = _shortcuts.pop(spec_id, None)
    if shortcut is not None:
        shortcut.setParent(None)
        shortcut.deleteLater()


def all_specs() -> list[ShortcutSpec]:
    return sorted(_registry.values(), key=lambda s: s.key)


def get(spec_id: str) -> ShortcutSpec | None:
    return _registry.get(spec_id)


def conflicts() -> dict[str, list[ShortcutSpec]]:
    """同一键序列的多条注册（id 去重后仍 >1 视为冲突候选）。"""
    by_key: dict[str, list[ShortcutSpec]] = {}
    for spec in _registry.values():
        by_key.setdefault(spec.key, []).append(spec)
    return {key: specs for key, specs in by_key.items() if len(specs) > 1}


def _warn_conflicts(spec: ShortcutSpec) -> None:
    dupes = conflicts().get(spec.key)
    if dupes and len(dupes) > 1:
        logger.warning(
            "快捷键冲突: %s → %s（后注册者优先触发）",
            spec.key,
            ", ".join(s.label for s in dupes),
        )
