from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import hashlib
import json
from typing import Literal, Mapping

from PySide6.QtCore import QSettings


from paleo_workbench.resources.preview_settings import (
    PreviewSettings,
    _BOOLEAN_FIELDS,
    _INTEGER_RANGES,
)


class PreviewSettingsStore:
    """Persist preview-only preferences without touching ProjectDocument."""

    ORGANIZATION = "PaleoWorkbench"
    APPLICATION = "paleo-workbench"
    GROUP = "preview/settings"

    def __init__(self, qsettings: QSettings | None = None) -> None:
        self._settings = qsettings or QSettings(self.ORGANIZATION, self.APPLICATION)

    def load(self) -> PreviewSettings:
        defaults = PreviewSettings.defaults()
        values: dict[str, object] = {}
        self._settings.beginGroup(self.GROUP)
        try:
            for field in fields(PreviewSettings):
                default = getattr(defaults, field.name)
                values[field.name] = self._settings.value(
                    field.name,
                    defaultValue=default,
                    type=type(default),
                )
        finally:
            self._settings.endGroup()
        try:
            return PreviewSettings.from_mapping(values)
        except (TypeError, ValueError):
            return defaults

    def save(self, settings: PreviewSettings) -> None:
        self._settings.beginGroup(self.GROUP)
        try:
            for name, value in settings.to_mapping().items():
                self._settings.setValue(name, value)
        finally:
            self._settings.endGroup()
        self._settings.sync()

    def reset(self) -> PreviewSettings:
        self._settings.remove(self.GROUP)
        self._settings.sync()
        return PreviewSettings.defaults()
