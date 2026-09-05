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

_registry: weakref.WeakKeyDictionary[QObject, object] = (
    weakref.WeakKeyDictionary()
)

# 密度跟踪的最小高度消费点（弱引用；主题切换统一刷新）
_min_height_widgets: weakref.WeakSet[QObject] = weakref.WeakSet()


def current_density() -> str:
    try:
        return theme_manager.density.value
    except Exception:  # noqa: BLE001 — 无 app 环境回落
        return "comfortable"


def track_control_height(widget: QObject) -> None:
    """按当前密度设置最小控件高度并跟踪（theme_changed 时自动重设）。

    取代 ``setMinimumHeight(tokens.CONTROL_HEIGHT)`` 的 compile-time 快照——
    切换 compact/comfortable 后行高/按钮高度不再错位。
    """
    widget.setMinimumHeight(tokens.control_height(current_density()))
    _min_height_widgets.add(widget)


def _refresh_min_heights() -> None:
    for widget in list(_min_height_widgets):
        try:
            widget.setMinimumHeight(tokens.control_height(current_density()))
        except RuntimeError:
            _min_height_widgets.discard(widget)


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
    # 探活：C++ 对象已随父销毁的 widget（Python wrapper 仍被 registry 里的
    # bound-method 值强引用着）在此出队，绝不再进入 render()/setStyleSheet
    # —— 否则 teardown 阶段 segfault。
    try:
        widget.style()
    except RuntimeError:
        _registry.pop(widget, None)
        return
    try:
        sheet = render()
    except RuntimeError:
        _registry.pop(widget, None)
        return
    if sheet is None:  # metrics-only 注册（bind_metrics），无样式可贴
        return
    set_sheet = getattr(widget, "setStyleSheet", None)
    if set_sheet is not None:
        try:
            set_sheet(sheet)
        except RuntimeError:
            _registry.pop(widget, None)


def bind_metrics(widget: QObject, apply_fn) -> None:
    """注册 metrics 应用函数并立即执行；theme_changed（携带 density）时重跑。

    用于构造时 ``setFixedHeight(tokens.CONTROL_HEIGHT)`` 一类调用点：
    换密度后由 apply_fn 重设实际高度，消除「QSS 缩了、固定值没缩」的错位。
    回调须无捕获地从 ``tokens.density_tokens(current)`` 取值。
    widget 销毁自动注销（与 :func:`bind` 同一弱引用表——apply_fn 返回
    None 时表示本次是 metrics-only 调用，不再 setStyleSheet）。
    """
    _registry[widget] = apply_fn
    try:
        widget.destroyed.connect(lambda _obj=None: _registry.pop(widget, None))
    except RuntimeError:
        pass
    try:
        apply_fn()
    except RuntimeError:
        _registry.pop(widget, None)


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
        except Exception:  # noqa: BLE001 — 单点失败不拖垮广播链
            logging.getLogger(__name__).exception(
                "inline style 重渲染失败（widget=%r）", widget
            )


theme_manager.theme_changed.connect(lambda *_args: repolish_all())
theme_manager.theme_changed.connect(lambda *_args: _refresh_min_heights())
