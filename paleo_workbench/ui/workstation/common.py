from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QIcon, QPainter

_ICONS_DIR = Path(__file__).parents[1] / "assets" / "icons"


def workstation_icon(name: str, color: str = "#53616c") -> QIcon:
    """Return a repository-owned icon tinted for the light workstation."""
    path = _ICONS_DIR / name
    if not path.exists():
        return QIcon()
    source = QIcon(str(path))
    pixmap = source.pixmap(QSize(48, 48))
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)
