"""Install C++-accelerated render hooks into the geoviz engine.

Called once at application startup. The engine side
(``geoviz_well_log.renderer.downsample``) defines the hook point; this module
is the only place that knows about the workbench's C++ backend, keeping the
engine free of reverse dependencies.
"""
from __future__ import annotations

import numpy as np

from paleo_workbench.viz.well_log_api import minmax_downsample

_installed_provider = None


def _cpp_minmax_provider(
    depths: np.ndarray, values: np.ndarray, pixel_height: int
) -> tuple[np.ndarray, np.ndarray]:
    if len(depths) <= pixel_height * 2:
        return depths, values
    d = np.asarray(depths, dtype=np.float32)
    v = np.asarray(values, dtype=np.float32)
    out_d, out_v = minmax_downsample(d, v, int(pixel_height))
    return np.asarray(out_d, dtype=np.float64), np.asarray(out_v, dtype=np.float64)


def install_geoviz_acceleration() -> None:
    """Inject the C++ min-max downsample provider into geoviz (idempotent)."""
    global _installed_provider
    if _installed_provider is not None:
        return
    from geoviz import set_downsample_provider

    set_downsample_provider(_cpp_minmax_provider)
    _installed_provider = _cpp_minmax_provider
