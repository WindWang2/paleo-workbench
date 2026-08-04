"""CrossWellFenceGenerator: 2D/3D seismic slice extractor.

Phase-2 promote-down (#256 / PR-A): ``generate_fence_mesh`` was promoted to
``geoviz_plots.fence`` (headless numpy) and is exposed via the ``geoviz``
facade as ``generate_fence_mesh`` / ``CrossWellFenceGenerator``. This local
module keeps only ``extract_seismic_slice`` (per #257: "仅移
generate_fence_mesh；其余几何若仍需保留则留在原处").
"""

from __future__ import annotations

import numpy as np


class CrossWellFenceGenerator:
    """Extracts inter-well 2D seismic slices.

    The 3D curtain mesh half of this class now lives in the geoviz facade
    (``geoviz.generate_fence_mesh``); this class retains the seismic-slice
    geometry that was not promoted.
    """

    @staticmethod
    def extract_seismic_slice(
        seismic_data: np.ndarray,
        wells: list[dict],
        n_samples_per_segment: int = 50,
    ) -> np.ndarray:
        """Extract 2D seismic amplitude section along piecewise multi-well trajectory path."""
        if len(wells) < 2 or seismic_data.ndim != 3:
            return np.zeros((0, 0), dtype=np.float32)

        ni, nx, nz = seismic_data.shape
        path_x = []
        path_y = []

        for i in range(len(wells) - 1):
            w1 = wells[i]
            w2 = wells[i + 1]
            x1, y1 = float(w1.get("x", 0)), float(w1.get("y", 0))
            x2, y2 = float(w2.get("x", 0)), float(w2.get("y", 0))

            xs = np.linspace(x1, x2, n_samples_per_segment)
            ys = np.linspace(y1, y2, n_samples_per_segment)

            if i > 0:
                xs = xs[1:]
                ys = ys[1:]

            path_x.extend(xs)
            path_y.extend(ys)

        n_pts = len(path_x)
        slice_2d = np.zeros((nz, n_pts), dtype=np.float32)

        for p in range(n_pts):
            ix = int(np.clip(path_x[p], 0, ni - 1))
            iy = int(np.clip(path_y[p], 0, nx - 1))
            slice_2d[:, p] = seismic_data[ix, iy, :]

        return slice_2d
