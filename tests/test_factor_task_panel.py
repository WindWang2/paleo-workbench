from paleo_workbench.project.models import FactorMapTask
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.tokens import INTERPOLATION_METHODS


def _make_tasks():
    return [
        FactorMapTask(
            name="地层厚度图",
            target_horizon="ZJ-2",
            factor_type="地层厚度",
            method="mock",
            status="complete",
        ),
        FactorMapTask(
            name="砂岩含量图",
            target_horizon="ZJ-2",
            factor_type="砂岩含量",
            method="mock",
            status="complete",
        ),
        FactorMapTask(
            name="水深图",
            target_horizon="ZJ-2",
            factor_type="水深",
            method="mock",
            status="pending",
        ),
    ]


def test_panel_object_name(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "FactorTaskPanel"


def test_panel_has_horizon_label(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    assert panel.horizon_label is not None
    assert panel.horizon_label.text() == "层位: —"


def test_panel_method_combo(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    assert panel.method_combo.count() == len(INTERPOLATION_METHODS)
    items = [
        panel.method_combo.itemText(i) for i in range(panel.method_combo.count())
    ]
    assert items == INTERPOLATION_METHODS


def test_panel_update_populates_rows(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    panel.update_state(_make_tasks())
    rows = panel.task_container.findChildren(FactorTaskPanel.Row)
    assert len(rows) == 3
    assert rows[0].name_label.text() == "地层厚度图"
    assert rows[2].name_label.text() == "水深图"
    # status badge text comes from TASK_STATUS_LABELS
    assert rows[0].status_badge.text() == "已生成"
    assert rows[2].status_badge.text() == "待生成"


def test_panel_summary_count(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    panel.update_state(_make_tasks())
    assert panel.summary_label.text() == "已制备 2 / 3 个单因素图"


def test_panel_empty_state(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    panel.update_state([])
    assert panel.summary_label.text() == "已制备 0 / 0 个单因素图"
    assert panel.horizon_label.text() == "层位: —"
    rows = panel.task_container.findChildren(FactorTaskPanel.Row)
    assert rows == []
