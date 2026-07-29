from typing import Any

from PySide6.QtWidgets import QWidget

from .errors import (
    WellLogCapabilityError,
    WellLogError,
    WellLogExportError,
    WellLogThreadError,
    WellLogValidationError,
    WellLogVersionConflict,
)


class WellLogView(QWidget):
    def __init__(self, parent: QWidget | None = ...) -> None: ...
    def submit_curve(
        self,
        depth: Any,
        values: Any,
        document_id: str,
        axis_id: str,
        curve_id: str,
        mnemonic: str,
        depth_unit: str,
        value_unit: str,
    ) -> dict[str, dict[str, int | str]]: ...
    def sample_value(self, curve_id: str, sample_index: int) -> float | None: ...
    def reset_viewport(self) -> None: ...
