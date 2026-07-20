from __future__ import annotations

from geoviz import GeoVizEngine, PreparedPreview

from paleo_workbench.viz.hosts.geoviz_preview_host import GeoVizPreviewHost
from paleo_workbench.viz.models import VizPayload


class EnginePreviewHost:
    """Host for ``GeoVizEngine`` prepare/render backends (plots, tops, TD, SEGY-2D).

    Aligns Visualization with the same contract as DataPage previews so DAT
    horizons, well heads, formation tops, and slice-scrub SEGY share one path.
    """

    tab_title = "引擎预览"

    def __init__(self, engine: GeoVizEngine | None = None) -> None:
        self.engine = engine or GeoVizEngine.default()
        self.widget = GeoVizPreviewHost(engine=self.engine)

    def clear(self) -> None:
        try:
            self.widget.clear()
        except Exception:
            pass

    def apply(self, payload: VizPayload) -> bool:
        prepared = payload.prepared
        if not isinstance(prepared, PreparedPreview):
            return False
        try:
            self.widget.render(prepared)
            return True
        except Exception:
            return False
