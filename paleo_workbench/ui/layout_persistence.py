"""QSettings-backed persistence for panel float/dock layouts."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QSettings, QRect

_log = logging.getLogger(__name__)

#: 统一的 QSettings 身份（B2）：历史上 shell 用 ``WorkstationV3``、面板浮
#: 动用 ``paleo-workbench``、主题用 ``Workstation`` 三处分裂；统一到主题
#: 已在用的 (PaleoWorkbench, Workstation)，旧数据一次性迁移。
SETTINGS_ORG = "PaleoWorkbench"
SETTINGS_APP = "Workstation"

#: 布局状态版本：不认识（更新或缺失）的版本一律丢弃走默认布局。
LAYOUT_STATE_VERSION = 4

_WINDOW_STATE_KEY = "layout/window_state"
_STATE_VERSION_KEY = "layout/state_version"
_INSPECTOR_FLAG_KEY = "layout/inspector_user_hidden"

#: 旧 shell 身份（WorkstationV3）下的窗口状态键。
_LEGACY_SHELL_APP = "WorkstationV3"
_LEGACY_WINDOW_STATE_KEY = "layout/windowState.v4"
#: 旧面板浮动持久化身份。
_LEGACY_PANELS_APP = "paleo-workbench"


def migrate_legacy_layout_settings() -> bool:
    """把历史 QSettings 身份里的布局数据迁到 (PaleoWorkbench, Workstation)。

    纯函数（只依赖默认 QSettings 存储），幂等：新键已有值时不覆盖，
    迁移成功后删除旧键。返回是否有任何数据被迁移——供测试与诊断断言。

    迁移内容：

    - ``(PaleoWorkbench, WorkstationV3)`` 的 ``layout/windowState.v4`` 与
      ``layout/inspector_user_hidden`` → 新应用名下 ``layout/window_state``
      /同名键，并补写 ``layout/state_version = 4``；
    - ``(PaleoWorkbench, paleo-workbench)`` 的 ``panel_layout`` 组 → 新应用
      名下同名组（键前缀不变）。
    """
    migrated = False
    target = QSettings(SETTINGS_ORG, SETTINGS_APP)

    legacy_shell = QSettings(SETTINGS_ORG, _LEGACY_SHELL_APP)
    legacy_shell.sync()
    state = legacy_shell.value(_LEGACY_WINDOW_STATE_KEY)
    if state is not None:
        if target.value(_WINDOW_STATE_KEY) is None:
            target.setValue(_WINDOW_STATE_KEY, state)
        inspector_hidden = legacy_shell.value(_INSPECTOR_FLAG_KEY, None)
        if inspector_hidden is not None:
            target.setValue(_INSPECTOR_FLAG_KEY, inspector_hidden)
        target.setValue(_STATE_VERSION_KEY, LAYOUT_STATE_VERSION)
        legacy_shell.remove(_LEGACY_WINDOW_STATE_KEY)
        legacy_shell.remove(_INSPECTOR_FLAG_KEY)
        migrated = True

    legacy_panels = QSettings(SETTINGS_ORG, _LEGACY_PANELS_APP)
    legacy_panels.sync()
    legacy_panels.beginGroup("panel_layout")
    try:
        keys = list(legacy_panels.allKeys())
        for key in keys:
            # 组内读、组外写：新存储键前缀保持 panel_layout/… 不变。
            target.setValue(f"panel_layout/{key}", legacy_panels.value(key))
    finally:
        legacy_panels.endGroup()
    if keys:
        legacy_panels.remove("panel_layout")
        migrated = True

    if migrated:
        target.sync()
        _log.info("migrated legacy layout settings into (%s, %s)", SETTINGS_ORG, SETTINGS_APP)
    return migrated


@dataclass(frozen=True)
class PanelLayoutRecord:
    """Everything persisted about one panel, keyed ``page:panel``."""

    floating: bool = False
    geometry: QRect | None = None
    docked_sizes: tuple[int, ...] | None = None
    visible: bool = True

    @property
    def is_empty(self) -> bool:
        """True when the store holds nothing worth restoring."""
        return not self.floating and not self.docked_sizes and self.visible


class LayoutPersistence:
    """Persist per-panel layout state (float geometry, docked sizes, visibility).

    Keys follow the ``page:panel`` convention (``"mapping:layer_tree"``) so
    persisted entries stay namespaced per page. Entries are only written when
    a float/dock actually happens, so a session that never floated a panel
    leaves nothing behind and restoring is a safe no-op — under offscreen CI
    nothing reads or writes unless a caller asks for it.

    Pass an explicit :class:`QSettings` to bind a custom backend (tests use a
    temporary ini file); the default binds the workbench org/application store
    lazily on first use.
    """

    ORGANIZATION = SETTINGS_ORG
    APPLICATION = SETTINGS_APP
    GROUP = "panel_layout"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings

    # --- write ----------------------------------------------------------

    def save_float(self, key: str, geometry: QRect) -> None:
        """Record ``key`` as floating at ``geometry`` (and visible)."""
        settings = self._bind()
        settings.beginGroup(self._group(key))
        try:
            settings.setValue("floating", True)
            settings.setValue("visible", True)
            settings.setValue(
                "geometry",
                "{},{},{},{}".format(
                    geometry.x(), geometry.y(), geometry.width(), geometry.height()
                ),
            )
        finally:
            settings.endGroup()
        settings.sync()

    def save_dock(self, key: str, sizes) -> None:
        """Record ``key`` as docked again with the splitter ``sizes``."""
        settings = self._bind()
        settings.beginGroup(self._group(key))
        try:
            settings.setValue("floating", False)
            settings.setValue("visible", True)
            settings.setValue(
                "docked_sizes", self._encode_sizes(sizes)
            )
        finally:
            settings.endGroup()
        settings.sync()

    def save_docked_sizes(self, key: str, sizes) -> None:
        """Record only the splitter ``sizes`` (float keeps ``floating`` True).

        Written at float time so a crash mid-float still leaves the pre-float
        dock slot recoverable.
        """
        settings = self._bind()
        settings.setValue(
            f"{self._group(key)}/docked_sizes", self._encode_sizes(sizes)
        )
        settings.sync()

    def save_visibility(self, key: str, visible: bool) -> None:
        """Record only the visibility flag (a floating panel was closed)."""
        settings = self._bind()
        settings.setValue(f"{self._group(key)}/visible", bool(visible))
        settings.sync()

    def clear(self, key: str) -> None:
        settings = self._bind()
        settings.remove(self._group(key))
        settings.sync()

    # --- read -----------------------------------------------------------

    def load(self, key: str) -> PanelLayoutRecord:
        settings = self._bind()
        settings.beginGroup(self._group(key))
        try:
            floating = settings.value("floating", False, type=bool)
            visible = settings.value("visible", True, type=bool)
            geometry = self._parse_geometry(
                settings.value("geometry", "", type=str)
            )
            sizes = self._parse_sizes(
                settings.value("docked_sizes", "", type=str)
            )
        finally:
            settings.endGroup()
        return PanelLayoutRecord(
            floating=floating, geometry=geometry, docked_sizes=sizes, visible=visible
        )

    # --- internals ------------------------------------------------------

    def _bind(self) -> QSettings:
        if self._settings is None:
            # 默认后端绑定前先做一次旧身份迁移（幂等）：孤立使用
            # LayoutPersistence（无工作站壳）也能读到旧面板布局。
            migrate_legacy_layout_settings()
            self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)
        return self._settings

    @classmethod
    def _group(cls, key: str) -> str:
        return f"{cls.GROUP}/{key}"

    @staticmethod
    def _encode_sizes(sizes) -> str:
        return ",".join(str(int(size)) for size in sizes)

    @staticmethod
    def _parse_geometry(raw: str) -> QRect | None:
        parts = [part for part in (raw or "").split(",") if part]
        if len(parts) != 4:
            return None
        try:
            x, y, width, height = (int(part) for part in parts)
        except ValueError:
            return None
        return QRect(x, y, width, height)

    @staticmethod
    def _parse_sizes(raw: str) -> tuple[int, ...] | None:
        parts = [part for part in (raw or "").split(",") if part]
        if not parts:
            return None
        try:
            return tuple(int(part) for part in parts)
        except ValueError:
            return None
