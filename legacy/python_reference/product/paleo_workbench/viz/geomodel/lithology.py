"""Lithology property lookup tables shared across the 3D modeling analysis.

The tables map representative log values (GR, sonic, density, acoustic
impedance) per lithology name. They were previously duplicated inline in
several ``GeologicalModeling3DPage`` methods; this is the single home.
"""
from __future__ import annotations

import numpy as np

# Representative GR (API units) per lithology; unknown lithologies fall back
# to ``DEFAULT_GR``.
LITHO_GR = {"砂岩": 40.0, "泥岩": 120.0, "石灰岩": 25.0, "花岗岩": 80.0}
# Representative sonic travel time (us/ft) per lithology.
LITHO_SONIC = {"砂岩": 180.0, "泥岩": 250.0, "石灰岩": 150.0, "花岗岩": 120.0}
# Representative density (g/cm3) per lithology.
LITHO_DENSITY = {"砂岩": 2.2, "泥岩": 2.4, "石灰岩": 2.65, "花岗岩": 2.7}
# Representative acoustic impedance (m/s * g/cm3) per lithology.
LITHO_AI = {"砂岩": 8200.0, "泥岩": 4800.0, "石灰岩": 14500.0, "花岗岩": 18000.0}

DEFAULT_GR = 60.0
DEFAULT_SONIC = 180.0
DEFAULT_DENSITY = 2.4
DEFAULT_AI = 6000.0


def sample_log_values(layers: list[dict], depths: np.ndarray, table: dict, default: float) -> np.ndarray:
    """Assign per-lithology property values to a depth array (float32).

    Each layer contributes its table value over ``[top, bottom)``; depths not
    covered by any layer stay ``0.0``, and *default* applies only to covered
    depths whose lithology is missing from the table. Mirrors the inline
    mask-assignment loop previously duplicated in the page methods.
    """
    values = np.zeros(len(depths), dtype=np.float32)
    for layer in layers:
        mask = (depths >= layer["top"]) & (depths < layer["bottom"])
        values[mask] = table.get(layer["lithology"], default)
    return values
