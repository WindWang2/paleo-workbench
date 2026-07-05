from paleo_workbench.project.models import StratigraphicFramework
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel


def test_sequence_target_panel_defaults(qtbot):
    panel = SequenceTargetPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "SequenceTargetPanel"
    assert panel.target_value.text() == "未设置"
    assert panel.scheme_combo.currentText() == "LST/TST/HST"
    assert panel.version_value.text() == "v1"


def test_sequence_target_panel_update_state(qtbot):
    panel = SequenceTargetPanel()
    qtbot.addWidget(panel)
    stratigraphy = StratigraphicFramework(
        target_horizon="ZJ2",
        systems_tract_scheme="三级层序格架",
        interpretation_version="v3",
        applicable_wells=["HZ26-7", "HZ26-11"],
        applicable_seismic_ranges=["Inline 1180"],
    )

    panel.update_state(stratigraphy)

    assert panel.target_value.text() == "ZJ2"
    assert panel.scheme_combo.currentText() == "三级层序格架"
    assert panel.version_value.text() == "v3"
    assert panel.scope_value.text() == "2 口井 / 1 条测线"
