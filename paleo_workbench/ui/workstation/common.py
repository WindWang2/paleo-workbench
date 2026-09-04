"""工作站图标：SVG 按语义色染色（B1 主题感知）。

默认色取**当前主题**的 TEXT_SECONDARY（此前硬编码 light 值，暗色主题下图
标偏暗）；主题切换时缓存失效重染。DPR 感知：按设备像素比出图避免 HiDPI
发糊（此前固定 48×48 逻辑像素）。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QGuiApplication

_ICONS_DIR = Path(__file__).parents[1] / "assets" / "icons"

_ICON_CACHE: dict[tuple[str, str, float], QIcon] = {}

_FALLBACK_COLOR = "#53616c"


def _default_icon_color() -> str:
    """Current theme's secondary text color (paint-time, never cached)."""
    try:
        from paleo_workbench.ui.theme import theme_manager
        from paleo_workbench import tokens

        palette = tokens.palette_for(theme_manager.current_theme.value)
        return str(palette.get("TEXT_SECONDARY", _FALLBACK_COLOR))
    except Exception:
        return _FALLBACK_COLOR


def _clear_icon_cache(*_args) -> None:
    _ICON_CACHE.clear()


def install_theme_hook() -> None:
    """订阅主题变化清空染色缓存（幂等，入口层调用一次）。"""
    try:
        from paleo_workbench.ui.theme import theme_manager

        theme_manager.theme_changed.connect(_clear_icon_cache)
    except Exception:
        pass


def workstation_icon(name: str, color: str = "") -> QIcon:
    """Return a repository-owned icon tinted with a semantic color.

    ``color`` 为空时用当前主题的 TEXT_SECONDARY；显式传入语义色
    （如 ``tokens.PRIMARY``）保持不变。
    """
    tint = str(color) or _default_icon_color()
    ratio = 1.0
    try:
        app = QGuiApplication.instance()
        if app is not None:
            ratio = max(1.0, float(app.devicePixelRatio()))
    except (RuntimeError, TypeError):
        ratio = 1.0
    key = (name, tint, ratio)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    path = _ICONS_DIR / name
    icon = QIcon()
    if path.exists():
        source = QIcon(str(path))
        base = QSize(48, 48)
        pixmap = source.pixmap(base)
        pixmap.setDevicePixelRatio(ratio)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(tint))
        painter.end()
        icon = QIcon(pixmap)
    _ICON_CACHE[key] = icon
    return icon
