from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_document_panel import MapDocumentPanel
from paleo_workbench.ui.pages.mapping_helpers import active_map_document


def test_active_map_document_selects_latest():
    first = PaleoMapDocument(name="T1 Map", linked_target_horizon="T1")
    second = PaleoMapDocument(name="T2 Map", linked_target_horizon="T2")

    assert active_map_document([first, second]) is second


def test_map_document_panel_empty_state(qtbot):
    panel = MapDocumentPanel()
    qtbot.addWidget(panel)

    panel.update_state([])

    assert panel.objectName() == "MapDocumentPanel"
    assert panel.name_value.text() == "未选择古地理图"
    assert panel.horizon_value.text() == "未设置"
    assert panel.polygon_count_value.text() == "0 个相带"
    assert panel.well_count_value.text() == "0 口井"


def test_map_document_panel_update_state(qtbot):
    panel = MapDocumentPanel()
    qtbot.addWidget(panel)
    doc = PaleoMapDocument(
        name="ZJ2 Map",
        linked_target_horizon="ZJ2",
        facies_polygons=[{"type": "Feature"}, {"type": "Feature"}],
        well_overlays=[{"name": "HZ26-7"}],
    )

    panel.update_state([doc])

    assert panel.name_value.text() == "ZJ2 Map"
    assert panel.horizon_value.text() == "ZJ2"
    assert panel.polygon_count_value.text() == "2 个相带"
    assert panel.well_count_value.text() == "1 口井"
    assert panel.document_list.count() == 1
