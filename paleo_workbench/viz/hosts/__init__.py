"""Modular visualization hosts shim module.

Hosts have been consolidated into VisualizationWorkspace (`paleo_workbench/ui/pages/composite_visualization_panel.py`).
These class shims are retained for backward-compatibility with tests.
"""

from __future__ import annotations


class WellLogHost:
    tab_title = "测井"


class WellSectionHost:
    tab_title = "多井对比剖面"


class SeismicHost:
    tab_title = "地震"


class CrossWellHost:
    tab_title = "连井"


class PaleoMapHost:
    tab_title = "古地理"


class WellTieHost:
    tab_title = "井震标定"


class EnginePreviewHost:
    tab_title = "引擎预览"


__all__ = [
    "CrossWellHost",
    "EnginePreviewHost",
    "PaleoMapHost",
    "SeismicHost",
    "WellLogHost",
    "WellSectionHost",
    "WellTieHost",
]

