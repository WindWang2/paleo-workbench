"""动态 inline 样式注册表（B1 design system 的一部分）。

问题（#1047 残余 / 审计第 2 条）：``palette_for`` 的暗色覆盖只进 QSS；
105 个文件用 ``tokens.TEXT_PRIMARY`` 等**模块常量**拼 f-string stylesheet，
这些常量永远是 light 值，主题切换后不刷新。把全部调用点迁进 QSS 不现实
（很多是按数据动态生成的 HTML/painter 样式），所以提供显式注册：

    from paleo_workbench.ui import style

    def _render() -> str:
        pal = style.palette()          # 当前主题的语义 token dict
        return f"color: {pal['TEXT_PRIMARY']};"

    style.bind(widget, _render)        # 立即应用 + 主题变化时重渲染

约束：回调必须**无捕获地**从 ``palette()`` 取值（每次重取），widget 销毁
自动注销（destroyed → weakref 出队）。``palette()`` 返回
``tokens.palette_for(theme_manager.current_theme.value)``。
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject

from paleo_workbench import tokens
from paleo_workbench.ui.theme import theme_manager

_registry: "weakref.WeakKeyDictionary[QObject, object]" = (
    weakref.WeakKeyDictionary()
)


def palette() -> dict:
    """Current-theme semantic token vocabulary（每次调用重取，勿缓存）。"""
    return tokens.palette_for(theme_manager.current_theme.value)


def bind(widget: QObject, render) -> None:
    """注册动态 stylesheet 渲染函数并立即应用一次。

    ``render() -> str``（QSS 片段）在每次主题变化时重新求值。非 QSS 场景
    （如 painter/HTML 颜色）可用 :func:`on_theme_change` 订阅重绘。
    """
    _registry[widget] = render
    try:
        widget.destroyed.connect(lambda _obj=None: _registry.pop(widget, None))
    except RuntimeError:
        pass
    _apply(widget)


def _apply(widget: QObject) -> None:
    render = _registry.get(widget)
    if render is None:
        return
    try:
        sheet = render()
    except RuntimeError:
        _registry.pop(widget, None)
        return
    set_sheet = getattr(widget, "setStyleSheet", None)
    if set_sheet is not None:
        set_sheet(sheet)


def on_theme_change(callback) -> None:
    """订阅主题/密度变化。

    注意：连接是**强引用**（Qt 信号表持有 callback），调用方必须在
    接收者销毁时 disconnect，否则泄漏。widget 级样式请优先用
    :func:`bind`（destroyed 自动注销）。
    """
    theme_manager.theme_changed.connect(callback)


def repolish_all() -> None:
    """主题变化时重渲染全部注册的 inline 样式（ThemeManager 接线调用）。

    单个渲染器抛异常只影响它自己（记录后跳过），不得中断整条
    theme_changed 广播链。
    """
    import logging

    for widget in list(_registry.keys()):
        try:
            _apply(widget)
        except Exception:
            logging.getLogger(__name__).exception(
                "inline style 重渲染失败（widget=%r）", widget
            )


theme_manager.theme_changed.connect(lambda *_args: repolish_all())
