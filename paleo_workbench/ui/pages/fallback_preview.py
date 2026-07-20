"""Re-export facade for fallback_preview functions.

The parsing implementations have down-layered to
``paleo_workbench.resources.preview_parsers.office_parsers``.
"""

from paleo_workbench.resources.preview_parsers.office_parsers import (
    BoundedReader,
    dfb_preview,
    pptx_preview,
    spreadsheetml_preview,
    wlp_preview,
    zip_preview,
)

__all__ = [
    "BoundedReader",
    "dfb_preview",
    "pptx_preview",
    "spreadsheetml_preview",
    "wlp_preview",
    "zip_preview",
]
