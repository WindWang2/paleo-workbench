from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_document_panel import MapDocumentPanel
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_mapping_page_assembles_three_widgets(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.objectName() == "MappingPage"
    assert isinstance(page.document_panel, MapDocumentPanel)
    assert isinstance(page.canvas_panel, MapCanvasPanel)
    assert isinstance(page.chrome_panel, MapChromePanel)


def test_mapping_page_update_delegates(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    calls = {"document": [], "canvas": [], "chrome": []}

    page.document_panel.update_state = lambda docs: calls["document"].append(docs)
    page.canvas_panel.update_state = lambda doc: calls["canvas"].append(doc)
    page.chrome_panel.update_state = lambda doc: calls["chrome"].append(doc)

    docs = [{"name": "old"}, {"name": "active"}]
    page.update_state(docs)

    assert calls["document"] == [docs]
    assert calls["canvas"] == [docs[-1]]
    assert calls["chrome"] == [docs[-1]]
