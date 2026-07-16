"""Modular visualization hosts — thin wrappers over geo-viz-engine widgets.

Each host owns one product surface from the engine. The composite panel only
coordinates tabs and routes ``VizPayload`` to the matching host.
"""

from __future__ import annotations

from paleo_workbench.viz.hosts.cross_well_host import CrossWellHost
from paleo_workbench.viz.hosts.engine_preview_host import EnginePreviewHost
from paleo_workbench.viz.hosts.paleo_map_host import PaleoMapHost
from paleo_workbench.viz.hosts.seismic_host import SeismicHost
from paleo_workbench.viz.hosts.well_log_host import WellLogHost

__all__ = [
    "CrossWellHost",
    "EnginePreviewHost",
    "PaleoMapHost",
    "SeismicHost",
    "WellLogHost",
]
