"""QSettings-backed persistence for panel float/dock layouts."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, QRect


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

    ORGANIZATION = "PaleoWorkbench"
    APPLICATION = "paleo-workbench"
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
