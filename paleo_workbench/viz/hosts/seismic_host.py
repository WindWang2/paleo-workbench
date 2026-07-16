from __future__ import annotations

from pathlib import Path

from geoviz import SeismicView

from paleo_workbench.viz.models import VizPayload


class SeismicHost:
    """Host for ``geoviz_seismic.SeismicView`` (aligns with SeismicPage).

    Prefers the adapter's **budgeted** ``seismic_volume`` via ``load_demo`` so
    visualization stays within the same memory bounds as the load path.
    Falls back to ``load_segy`` only when no volume is available.
    """

    tab_title = "地震"

    def __init__(self) -> None:
        self.widget = SeismicView(auto_load=False)

    def clear(self) -> None:
        loader = getattr(self.widget, "_loader", None)
        if loader is not None:
            try:
                loader.close()
            except Exception:
                pass
            try:
                self.widget._loader = None
            except Exception:
                pass
        # Best-effort visual reset when API allows.
        try:
            import numpy as np

            empty = np.zeros((2, 2, 2), dtype=np.float32)
            self.widget.load_demo(empty)
        except Exception:
            pass

    def apply(self, payload: VizPayload) -> bool:
        # Prefer bounded volume from adapter (MAX_DIM budget).
        if payload.seismic_volume is not None:
            self._close_loader()
            self.widget.load_demo(payload.seismic_volume)
            return True
        path = (payload.seismic_path or "").strip()
        if path and Path(path).is_file():
            try:
                self.widget.load_segy(path)
                return True
            except Exception:
                return False
        return False

    def _close_loader(self) -> None:
        loader = getattr(self.widget, "_loader", None)
        if loader is not None:
            try:
                loader.close()
            except Exception:
                pass
            try:
                self.widget._loader = None
            except Exception:
                pass
