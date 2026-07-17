from __future__ import annotations

from pathlib import Path

from geoviz import SeismicView

from paleo_workbench.viz.models import VizPayload


class SeismicHost:
    """Host for ``geoviz_seismic.SeismicView`` (aligns with SeismicPage).

    Uses engine-prepared asynchronous SEGY loading for file payloads.  The
    workbench never invokes the synchronous full-file API on the GUI thread.
    """

    tab_title = "地震"

    def __init__(self) -> None:
        self.widget = SeismicView(auto_load=False)

    def clear(self) -> None:
        # Best-effort visual reset when API allows.
        try:
            import numpy as np

            # Renderer normal-map gradients require at least 3 samples/axis.
            empty = np.zeros((3, 3, 3), dtype=np.float32)
            self.widget.load_demo(empty)
        except Exception:
            pass

    def apply(self, payload: VizPayload) -> bool:
        # Prefer bounded volume from adapter (MAX_DIM budget).
        if payload.seismic_volume is not None:
            self.widget.load_demo(payload.seismic_volume)
            return True
        path = (payload.seismic_path or "").strip()
        if path and Path(path).is_file():
            try:
                self.widget.load_segy_async(path)
                return True
            except Exception:
                return False
        return False
