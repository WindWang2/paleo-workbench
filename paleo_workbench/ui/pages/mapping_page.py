from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_document_panel import MapDocumentPanel
from paleo_workbench.ui.pages.mapping_helpers import active_map_document


class MappingPage(QWidget):
    """Display-first 编图 page backed by PaleoMapDocument and PaleoMapCanvas."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MappingPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(16)

        content = QHBoxLayout()
        content.setSpacing(16)

        self.document_panel = MapDocumentPanel()
        content.addWidget(self.document_panel, 0)

        self.canvas_panel = MapCanvasPanel()
        content.addWidget(self.canvas_panel, 1)

        self.chrome_panel = MapChromePanel()
        content.addWidget(self.chrome_panel, 0)

        outer.addLayout(content, 1)

    def update_state(self, map_documents: list | tuple | None) -> None:
        document = active_map_document(map_documents)
        self.document_panel.update_state(map_documents)
        self.canvas_panel.update_state(document)
        self.chrome_panel.update_state(document)
