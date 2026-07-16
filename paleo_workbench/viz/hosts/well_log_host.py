from __future__ import annotations

from geoviz import WellLogCanvas, build_qpainter_tracks

from paleo_workbench.viz.models import VizPayload


class WellLogHost:
    """Host for ``geoviz_well_log.WellLogCanvas`` (aligns with WellLogPage)."""

    tab_title = "测井"

    def __init__(self) -> None:
        self.widget = WellLogCanvas()

    def clear(self) -> None:
        self.widget.set_tracks([])

    def apply(self, payload: VizPayload) -> bool:
        data = payload.well_log
        if data is None and payload.well_logs:
            data = payload.well_logs[0]
        if data is None:
            return False
        tracks = build_qpainter_tracks(data)
        self.widget.set_tracks(tracks)
        return True
