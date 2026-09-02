from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter

_ICONS_DIR = Path(__file__).parents[1] / "assets" / "icons"

_ICON_CACHE: dict[tuple[str, str], QIcon] = {}


def workstation_icon(name: str, color: str = "#53616c") -> QIcon:
    """Return a repository-owned icon tinted for the light workstation."""
    key = (name, color)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    path = _ICONS_DIR / name
    icon = QIcon()
    if path.exists():
        source = QIcon(str(path))
        pixmap = source.pixmap(QSize(48, 48))
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), QColor(color))
        painter.end()
        icon = QIcon(pixmap)
    _ICON_CACHE[key] = icon
    return icon
