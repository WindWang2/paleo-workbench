from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.tokens import SMOOTHING_LEVELS


def test_boundary_object_name(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "BoundaryPanel"


def test_boundary_threshold_default(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    assert panel.threshold_spin.minimum() == 0.0
    assert panel.threshold_spin.maximum() == 1.0
    assert panel.threshold_spin.singleStep() == 0.05
    assert panel.threshold_spin.decimals() == 2
    assert panel.threshold_spin.value() == 0.55


def test_boundary_smoothing_options(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    items = [
        panel.smoothing_combo.itemText(i)
        for i in range(panel.smoothing_combo.count())
    ]
    assert items == SMOOTHING_LEVELS
    assert panel.smoothing_combo.currentText() == "中"


def test_boundary_area_default(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    assert panel.area_spin.minimum() == 0.0
    assert panel.area_spin.maximum() == 10.0
    assert panel.area_spin.singleStep() == 0.1
    assert panel.area_spin.decimals() == 1
    assert panel.area_spin.value() == 0.5
    assert panel.area_spin.suffix() == " km²"


def test_boundary_generate_button_present(qtbot):
    panel = BoundaryPanel()
    qtbot.addWidget(panel)
    btn = panel.generate_btn
    assert btn is not None
    assert btn.objectName() == "PrimaryButton"
    assert "生成初始边界" in btn.text()
