"""Dynamic Theme Manager for Paleo Workbench.

The theme system has a single source (#1047): the semantic token sheet in
:mod:`paleo_workbench.tokens`. Every theme — light, dark, high contrast — is
a curated *palette of the same token vocabulary* rendered through
``tokens.build_qss(theme=...)``; this manager owns only the runtime switching
state. It no longer carries its own stylesheet, so the two systems that used
to drift apart (a 700-line production sheet vs. a 30-line stub) cannot
diverge again.
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, Signal

from paleo_workbench import tokens


class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    HIGH_CONTRAST = "high_contrast"


class ThemeManager(QObject):
    """Central manager for application-wide theme switching."""

    theme_changed = Signal(str)  # Emits new theme name

    def __init__(self, default: ThemeMode = ThemeMode.LIGHT) -> None:
        super().__init__()
        self._current_theme: ThemeMode = default

    @property
    def current_theme(self) -> ThemeMode:
        return self._current_theme

    def set_theme(self, mode: ThemeMode | str) -> None:
        if isinstance(mode, str):
            mode = ThemeMode(mode)
        if mode != self._current_theme:
            self._current_theme = mode
            self.theme_changed.emit(mode.value)

    def get_qss(self, density: str = "comfortable") -> str:
        """Render the token stylesheet for the current theme."""
        return tokens.build_qss(density=density, theme=self._current_theme.value)


theme_manager = ThemeManager()
