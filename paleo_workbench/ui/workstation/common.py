"""工作站图标：SVG 按语义色染色（B1 主题感知）。

默认色取**当前主题**的 TEXT_SECONDARY（此前硬编码 light 值，暗色主题下图
标偏暗）；主题切换时缓存失效重染。DPR 感知：按设备像素比出图避免 HiDPI
发糊（此前固定 48×48 逻辑像素）。
"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QGuiApplication

_ICONS_DIR = Path(__file__).parents[1] / "assets" / "icons"
_MAP_ICONS_DIR = _ICONS_DIR / "map"

_ICON_CACHE: dict[tuple[str, str, float], QIcon] = {}

_FALLBACK_COLOR = "#53616c"

# 单色（可染色）判定缓存：svg 文件名 → 是否全部为无彩灰色系。
_MONO_SUFFIX_CACHE: dict[str, bool] = {}

# fill/stroke/stop-color 的 hex 值（属性式 fill="#..." 与内联式 fill:#...）。
_SVG_HEX_COLOR = re.compile(
    r"(?:fill|stroke|stop-color)\s*[:=]\s*\"?(#[0-9a-fA-F]{3,8})\b"
)

# 无彩阈值：max-min ≤ 12% 视为灰（tint 安全——图标本意是「跟随文字色的
# 中性字形」；TEXT_SECONDARY 浅色值本身即落在该阈值内）。带明显语义
# 彩色的 SVG 一律跳过染色。


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
    ratio = _device_pixel_ratio()
    key = (name, tint, ratio)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    path = _ICONS_DIR / name
    icon = _render_tinted(path, tint, ratio) if path.exists() else QIcon()
    _ICON_CACHE[key] = icon
    return icon


def tinted_map_icon(name: str, color: str = "") -> QIcon:
    """Map-workspace icon from ``assets/icons/map``，主题感知（E2）。

    查找顺序 ``map/`` 优先、assets 根目录兜底（沿用 map_action_controller
    的双目录回退语义）；资产缺失返回空 QIcon（调用点的 no-asset 回退不变）。

    染色策略（CompositionMode_SourceIn，DPR 感知，缓存 + 主题切换失效，
    与 :func:`workstation_icon` 同一机制）：SVG 内所有 bake 色都是**无彩
    灰系**（中性字形）时用当前主题 TEXT_SECONDARY 重染；含任何语义彩色
    （Tango/GIS 多色符号：绿=植被、红=危险、蓝=水体…）则原样返回——
    拉平重染会破坏图义。currentColor/无色 SVG 视为可染。
    """
    stem = str(name)
    if stem.endswith(".svg"):
        stem = stem[:-4]
    tint = str(color) or _default_icon_color()
    ratio = _device_pixel_ratio()
    key = (f"map/{stem}", tint, ratio)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    path = _resolve_icon(stem)
    if path is None:
        icon = QIcon()
    elif _is_achromatic_svg(path):
        icon = _render_tinted(path, tint, ratio)
    else:
        icon = QIcon(str(path))
    _ICON_CACHE[key] = icon
    return icon


def _device_pixel_ratio() -> float:
    ratio = 1.0
    try:
        app = QGuiApplication.instance()
        if app is not None:
            ratio = max(1.0, float(app.devicePixelRatio()))
    except (RuntimeError, TypeError):
        ratio = 1.0
    return ratio


def _resolve_icon(stem: str) -> Path | None:
    for directory in (_MAP_ICONS_DIR, _ICONS_DIR):
        path = directory / f"{stem}.svg"
        if path.exists():
            return path
    return None


def _is_achromatic_svg(path: Path) -> bool:
    """True 当 SVG 只含无彩（灰）bake 色——可安全整体重染。

    结果按文件名缓存（资产在运行期不可变）。
    """
    cached = _MONO_SUFFIX_CACHE.get(path.name)
    if cached is None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        cached = all(_is_achromatic(m.group(1)) for m in _SVG_HEX_COLOR.finditer(text))
        _MONO_SUFFIX_CACHE[path.name] = cached
    return cached


def _is_achromatic(hex_color: str) -> bool:
    value = hex_color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) not in (6, 8):
        return True  # 非法定长不参与判定（不因解析问题拒绝染色）
    rgb = value[-6:] if len(value) == 8 else value
    r, g, b = (int(rgb[i : i + 2], 16) for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    return (mx - mn) <= 0.12 * 255


def _render_tinted(path: Path, tint: str, ratio: float) -> QIcon:
    source = QIcon(str(path))
    base = QSize(48, 48)
    pixmap = source.pixmap(base)
    pixmap.setDevicePixelRatio(ratio)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(tint))
    painter.end()
    return QIcon(pixmap)
