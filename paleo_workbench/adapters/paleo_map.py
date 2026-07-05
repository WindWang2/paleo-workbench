from __future__ import annotations

import json
from pathlib import Path

from paleo_workbench.adapters.schemas import ExportRequest, ExportResult, ViewerPayload, ViewState


class PaleoMapAdapter:
    adapter_name = "paleo_map"

    def __init__(self):
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()

    def set_data(self, payload: ViewerPayload | dict) -> None:
        parsed = payload if isinstance(payload, ViewerPayload) else ViewerPayload.model_validate(payload)
        if parsed.viewer_type != "paleo_map":
            raise ValueError(f"PaleoMapAdapter cannot render {parsed.viewer_type}")
        self._payload = parsed

    def set_view_state(self, state: ViewState | dict) -> None:
        self._state = state if isinstance(state, ViewState) else ViewState.model_validate(state)

    def get_view_state(self) -> ViewState:
        return self._state

    def export(self, request: ExportRequest | dict) -> ExportResult:
        parsed = request if isinstance(request, ExportRequest) else ExportRequest.model_validate(request)
        output = Path(parsed.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if parsed.format == "geojson":
            output.write_text(
                json.dumps({"type": "FeatureCollection", "features": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            output.write_text(f"minimal {parsed.format} export\n", encoding="utf-8")
        return ExportResult(
            output_path=output.as_posix(),
            format=parsed.format,
            byte_size=output.stat().st_size,
            artifact_metadata={"adapter": self.adapter_name},
        )

    def clear(self) -> None:
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()