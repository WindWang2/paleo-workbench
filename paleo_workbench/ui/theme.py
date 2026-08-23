"""Dynamic Theme Manager for Paleo Workbench.

Supports Dark, Light, and High-Contrast Scientific Publication themes with instant switching.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable
from PySide6.QtCore import QObject, Signal


class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    HIGH_CONTRAST = "high_contrast"


class ThemeManager(QObject):
    """Central manager for application-wide theme switching."""

    theme_changed = Signal(str)  # Emits new theme name

    def __init__(self) -> None:
        super().__init__()
        self._current_theme: ThemeMode = ThemeMode.DARK

    @property
    def current_theme(self) -> ThemeMode:
        return self._current_theme

    def set_theme(self, mode: ThemeMode | str) -> None:
        if isinstance(mode, str):
            mode = ThemeMode(mode)
        if mode != self._current_theme:
            self._current_theme = mode
            self.theme_changed.emit(mode.value)

    def get_qss(self) -> str:
        """Generate corresponding QSS for the current theme."""
        if self._current_theme == ThemeMode.LIGHT:
            return self._light_qss()
        elif self._current_theme == ThemeMode.HIGH_CONTRAST:
            return self._high_contrast_qss()
        return self._dark_qss()

    def _dark_qss(self) -> str:
        return """
        QWidget {
            background-color: #181c22;
            color: #f1f5f9;
            font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 13px;
        }
        QMenuBar, QMenu {
            background-color: #22272e;
            color: #f1f5f9;
            border: 1px solid #334155;
        }
        QToolBar {
            background-color: #1e293b;
            border-bottom: 1px solid #334155;
        }
        QPushButton {
            background-color: #334155;
            color: #ffffff;
            border-radius: 4px;
            padding: 4px 12px;
        }
        QPushButton:hover {
            background-color: #0ea5e9;
        }
        QTableWidget, QTableView {
            background-color: #1e293b;
            color: #f1f5f9;
            gridline-color: #334155;
        }
        """

    def _light_qss(self) -> str:
        return """
        QWidget {
            background-color: #f8fafc;
            color: #0f172a;
            font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            font-size: 13px;
        }
        QMenuBar, QMenu {
            background-color: #ffffff;
            color: #0f172a;
            border: 1px solid #e2e8f0;
        }
        QToolBar {
            background-color: #ffffff;
            border-bottom: 1px solid #e2e8f0;
        }
        QPushButton {
            background-color: #0ea5e9;
            color: #ffffff;
            border-radius: 4px;
            padding: 4px 12px;
        }
        QPushButton:hover {
            background-color: #0284c7;
        }
        QTableWidget, QTableView {
            background-color: #ffffff;
            color: #0f172a;
            gridline-color: #e2e8f0;
        }
        """

    def _high_contrast_qss(self) -> str:
        return """
        QWidget {
            background-color: #ffffff;
            color: #000000;
            font-family: Arial, "SimSun", sans-serif;
            font-size: 13px;
            font-weight: 500;
        }
        QMenuBar, QMenu {
            background-color: #ffffff;
            color: #000000;
            border: 2px solid #000000;
        }
        QPushButton {
            background-color: #ffffff;
            color: #000000;
            border: 2px solid #000000;
            border-radius: 0px;
            padding: 4px 12px;
            font-weight: bold;
        }
        """


theme_manager = ThemeManager()
