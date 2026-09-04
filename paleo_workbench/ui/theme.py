"""Dynamic Theme Manager for Paleo Workbench.

The theme system has a single source (#1047): the semantic token sheet in
:mod:`paleo_workbench.tokens`. Every theme — light, dark, high contrast — is
a curated *palette of the same token vocabulary* rendered through
``tokens.build_qss(theme=...)``; this manager owns only the runtime switching
state. It no longer carries its own stylesheet, so the two systems that used
to drift apart (a 700-line production sheet vs. a 30-line stub) cannot
diverge again.

B1（Workstation V4）：manager 同时持有 **密度**（compact / comfortable），
两者一起进入持久化（QSettings org=PaleoWorkbench app=Workstation，统一
历史三种应用名）。``theme_changed`` 携带 ``(theme, density)``；inline 样式
widget 经 :mod:`paleo_workbench.ui.style` 的动态注册表随主题重渲染。
"""

from __future__ import annotations

from enum import Enum

from PySide6.QtCore import QObject, QSettings, Signal

from paleo_workbench import tokens

SETTINGS_ORG = "PaleoWorkbench"
SETTINGS_APP = "Workstation"
_THEME_KEY = "ui/theme"
_DENSITY_KEY = "ui/density"


class ThemeMode(str, Enum):
    DARK = "dark"
    LIGHT = "light"
    HIGH_CONTRAST = "high_contrast"


class DensityMode(str, Enum):
    COMPACT = "compact"
    COMFORTABLE = "comfortable"


def _coerce_density(value: str | DensityMode | None) -> DensityMode:
    if isinstance(value, DensityMode):
        return value
    try:
        return DensityMode(str(value))
    except ValueError:
        return DensityMode.COMFORTABLE


def _coerce_theme(value: str | ThemeMode | None) -> ThemeMode:
    if isinstance(value, ThemeMode):
        return value
    try:
        return ThemeMode(str(value))
    except ValueError:
        return ThemeMode.LIGHT


class ThemeManager(QObject):
    """Central manager for application-wide theme + density switching."""

    theme_changed = Signal(str, str)  # Emits (theme, density) after a change

    def __init__(self, default: ThemeMode = ThemeMode.LIGHT) -> None:
        super().__init__()
        self._current_theme: ThemeMode = default
        self._density: DensityMode = DensityMode.COMFORTABLE

    # -- theme ---------------------------------------------------------------

    @property
    def current_theme(self) -> ThemeMode:
        return self._current_theme

    def set_theme(self, mode: ThemeMode | str) -> None:
        mode = _coerce_theme(mode)
        if mode != self._current_theme:
            self._current_theme = mode
            self._emit_and_persist()

    # -- density (B1) ---------------------------------------------------------

    @property
    def density(self) -> DensityMode:
        return self._density

    def set_density(self, mode: DensityMode | str) -> None:
        mode = _coerce_density(mode)
        if mode != self._density:
            self._density = mode
            self._emit_and_persist()

    def toggle_density(self) -> None:
        """Compact ⇄ Comfortable（专业工作站默认 Compact 由入口层决定）。"""
        self.set_density(
            DensityMode.COMFORTABLE
            if self._density is DensityMode.COMPACT
            else DensityMode.COMPACT
        )

    # -- stylesheet -----------------------------------------------------------

    def get_qss(self, density: str | None = None) -> str:
        """Render the token stylesheet for the current theme (+density)."""
        return tokens.build_qss(
            density=density or self._density.value,
            theme=self._current_theme.value,
        )

    def apply(self, app) -> None:
        """(Re)apply the current sheet to the application instance."""
        app.setStyleSheet(self.get_qss())

    # -- persistence ----------------------------------------------------------

    def _emit_and_persist(self) -> None:
        self.theme_changed.emit(self._current_theme.value, self._density.value)
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        settings.setValue(_THEME_KEY, self._current_theme.value)
        settings.setValue(_DENSITY_KEY, self._density.value)

    def load_persisted(self) -> None:
        """Restore persisted theme/density（无配置时保持当前值）。"""
        settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        theme = settings.value(_THEME_KEY, "")
        density = settings.value(_DENSITY_KEY, "")
        if theme:
            self._current_theme = _coerce_theme(theme)
        if density:
            self._density = _coerce_density(density)


theme_manager = ThemeManager()
