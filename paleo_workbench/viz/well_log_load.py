from __future__ import annotations

from pathlib import Path
from typing import Any

# Align bounds with geo-viz-engine WellLogPreviewBackend / load_las_preview defaults.
MAX_CURVES = 12
MAX_SAMPLES = 2000


def load_well_log_from_path(path: str) -> Any | None:
    """Return engine ``WellLogData`` via the public ``geoviz`` facade.

    Single source of truth: ``geoviz.load_las_preview`` (geoviz_well_log).
    """
    file_path = Path(path)
    if not file_path.is_file():
        return None
    try:
        from geoviz import load_las_preview
    except Exception:
        return None
    try:
        return load_las_preview(
            str(file_path),
            max_curves=MAX_CURVES,
            max_samples=MAX_SAMPLES,
        )
    except Exception:
        return None
