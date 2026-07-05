from __future__ import annotations

import numpy as np

from paleo_workbench.ui.pages.prediction_helpers import field_value


def seismic_volume_from_prediction(task, shape: tuple[int, int, int] = (8, 10, 12)) -> np.ndarray:
    seed = field_value(task, "seed", None)
    rng = np.random.default_rng(0 if seed is None else int(seed))
    volume = rng.normal(0.0, 0.18, size=shape).astype(np.float32)

    regions = (field_value(task, "result_summary", {}) or {}).get("predicted_regions", [])
    if regions:
        for index, region in enumerate(regions):
            probability = float(region.get("probability", 0.0))
            volume[index % shape[0], :, :] += np.float32(probability)

    return volume.astype(np.float32)
