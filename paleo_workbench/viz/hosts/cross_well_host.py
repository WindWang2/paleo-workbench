from __future__ import annotations

from geoviz import CrossWellCanvas, WellLogCanvas, build_qpainter_tracks

from paleo_workbench.viz.models import VizPayload


class CrossWellHost:
    """Host for ``geoviz_cross_well.CrossWellCanvas`` (aligns with CrossWellPage).

    Loads one or more well-log canvases into the package multi-well shell.
    DTW / picks remain engine-side and activate once multi-well data is present.
    """

    tab_title = "连井"

    def __init__(self) -> None:
        self.widget = CrossWellCanvas()
        self.inner = self.widget.widget  # CrossWellWidget

    def clear(self) -> None:
        self.inner.clear_all()

    def apply(self, payload: VizPayload) -> bool:
        logs = list(payload.well_logs or [])
        names = list(payload.well_names or [])
        if not logs and payload.well_log is not None:
            logs = [payload.well_log]
            names = [
                str(getattr(payload.well_log, "well_name", "") or payload.label or "Well")
            ]
        if not logs:
            return False

        # Prediction mock historically showed two synthetic wells for section layout.
        if payload.kind == "prediction" and len(logs) == 1:
            logs = [logs[0], logs[0]]
            base = names[0] if names else "Well"
            names = [f"{base}-1", f"{base}-2"]

        self.inner.clear_all()
        for index, data in enumerate(logs):
            name = (
                names[index]
                if index < len(names)
                else str(getattr(data, "well_name", "") or f"Well-{index + 1}")
            )
            canvas = WellLogCanvas()
            canvas.set_tracks(build_qpainter_tracks(data))
            self.inner.add_canvas(canvas, name)
        return True
