from __future__ import annotations

"""Re-export facade for preview widgets.

Each PreviewWidget implementation has been refactored into a dedicated module
under ``paleo_workbench.ui.pages``. This facade maintains 100% backward
compatibility for existing imports and monkeypatches in tests.
"""

from paleo_workbench.ui.pages.geotiff_preview_widget import GeoTiffPreviewWidget
from paleo_workbench.ui.pages.image_preview_widget import ImagePreviewWidget
from paleo_workbench.ui.pages.json_tree_preview_widget import JsonTreePreviewWidget
from paleo_workbench.ui.pages.media_preview_widget import MediaPreviewWidget, QAudioOutput, QMediaPlayer
from paleo_workbench.ui.pages.message_preview_widget import MessagePreviewWidget
from paleo_workbench.ui.pages.pdf_preview_widget import QPdfDocument, QPdfView, PdfPreviewWidget
from paleo_workbench.ui.pages.rich_text_preview_widget import RichTextPreviewWidget
from paleo_workbench.ui.pages.seismic_slice_preview_widget import SeismicSlicePreviewWidget
from paleo_workbench.ui.pages.summary_table_preview_widget import SummaryTablePreviewWidget
from paleo_workbench.ui.pages.table_preview_widget import TablePreviewWidget
from paleo_workbench.ui.pages.text_preview_widget import TextPreviewWidget
from paleo_workbench.ui.pages.web_document_preview_widget import (
    WebDocumentPreviewWidget,
    _LocalOnlyPage,
    _LocalOnlyRequestInterceptor,
)

__all__ = [
    "GeoTiffPreviewWidget",
    "ImagePreviewWidget",
    "JsonTreePreviewWidget",
    "MediaPreviewWidget",
    "MessagePreviewWidget",
    "PdfPreviewWidget",
    "QAudioOutput",
    "QMediaPlayer",
    "QPdfDocument",
    "QPdfView",
    "RichTextPreviewWidget",
    "SeismicSlicePreviewWidget",
    "SummaryTablePreviewWidget",
    "TablePreviewWidget",
    "TextPreviewWidget",
    "WebDocumentPreviewWidget",
    "_LocalOnlyPage",
    "_LocalOnlyRequestInterceptor",
]
