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
        self._overlay_conn = None
        self._overlay_expected_path: str | None = None

    def _disconnect_overlay(self) -> None:
        """Drop any pending overlay connection so a stale payload's closure
        can never fire on a newer file's ``segy_loaded``."""
        if self._overlay_conn is not None:
            try:
                self.widget.segy_loaded.disconnect(self._overlay_conn)
            except Exception:
                pass
            self._overlay_conn = None
        self._overlay_expected_path = None

    def clear(self) -> None:
        self._disconnect_overlay()
        # Best-effort visual reset when API allows.
        try:
            import numpy as np

            # Renderer normal-map gradients require at least 3 samples/axis.
            empty = np.zeros((3, 3, 3), dtype=np.float32)
            self.widget.load_demo(empty)
        except Exception:
            pass

    def apply(self, payload: VizPayload) -> bool:
        # A new apply invalidates any overlay connection registered for a
        # previous apply: that closure carries the old payload's dense volume
        # and must not be triggered by this file's load.
        self._disconnect_overlay()
        path = (payload.seismic_path or "").strip()
        has_segy = False
        if path and Path(path).is_file():
            try:
                self.widget.load_segy_async(path)
                has_segy = True
            except Exception:
                pass

        if payload.seismic_volume is not None:
            if has_segy:
                self._overlay_expected_path = path

                def on_ready(result=None, *args, **kwargs):
                    try:
                        # Only overlay when the finished load is the file this
                        # apply requested; a stale/older closure must no-op.
                        actual = getattr(result, "path", None)
                        if actual is not None and actual != self._overlay_expected_path:
                            return
                        self.widget.load_overlay_volume(payload.seismic_volume)
                    except Exception:
                        pass
                    try:
                        self.widget.segy_loaded.disconnect(on_ready)
                    except Exception:
                        pass
                    self._overlay_conn = None

                self._overlay_conn = self.widget.segy_loaded.connect(on_ready)
            else:
                self.widget.load_demo(payload.seismic_volume)
            return True

        return has_segy

