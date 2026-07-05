from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel


def test_map_chrome_panel_defaults(qtbot):
    panel = MapChromePanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "MapChromePanel"
    assert panel.title_value.text() == "未设置"
    assert "图例" in panel.elements_value.text()
    assert panel.save_btn.text() == "保存编图草稿"
    assert panel.review_btn.text() == "发送成图审核"


def test_map_chrome_panel_update_state(qtbot):
    panel = MapChromePanel()
    qtbot.addWidget(panel)
    doc = PaleoMapDocument(
        name="ZJ2 Map",
        linked_target_horizon="ZJ2",
        map_chrome={"title": "ZJ2 古地理图", "elements": ["图例", "比例尺"]},
    )

    panel.update_state(doc)

    assert panel.title_value.text() == "ZJ2 古地理图"
    assert panel.elements_value.text() == "图例 / 比例尺"
