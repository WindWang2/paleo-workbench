from __future__ import annotations

from typing import Protocol

from paleo_workbench.adapters.schemas import ExportRequest, ExportResult, ViewerPayload, ViewState


class WorkbenchViewerAdapter(Protocol):
    def set_data(self, payload: ViewerPayload | dict) -> None:
        ...

    def set_view_state(self, state: ViewState | dict) -> None:
        ...

    def get_view_state(self) -> ViewState:
        ...

    def export(self, request: ExportRequest | dict) -> ExportResult:
        ...

    def clear(self) -> None:
        ...