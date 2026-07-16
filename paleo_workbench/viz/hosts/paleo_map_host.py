from __future__ import annotations

from geoviz import PaleoMapCanvas

from paleo_workbench.viz.models import VizPayload


class PaleoMapHost:
    """Host for ``geoviz_paleo_map.PaleoMapCanvas`` (read-only product view).

    Full topology editing stays on MappingPage (workbench map_edit_*); this host
    mirrors engine preview chrome used by geo-viz map pages.
    """

    tab_title = "古地理"

    def __init__(self) -> None:
        self.widget = PaleoMapCanvas()

    def clear(self) -> None:
        self.widget.load_features([], period_name="", wells=[])

    def apply(self, payload: VizPayload) -> bool:
        if payload.kind not in {"map", "prediction"} and not (
            payload.map_features or payload.map_wells
        ):
            if payload.kind != "map":
                return False
        feats = payload.map_features or []
        wells = payload.map_wells or []
        self.widget.load_features(
            feats, period_name=payload.period_name or "", wells=wells
        )
        return True
