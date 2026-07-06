from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar


def test_summary_has_three_type_labels(qtbot):
    bar = ResourceSummaryBar()
    qtbot.addWidget(bar)
    assert len(bar.name_labels) == 3
    assert len(bar.count_labels) == 3
    assert bar.name_labels["well_log"].text() == tokens.RESOURCE_LABELS["well_log"]
    assert bar.count_labels["well_log"].text() == "0井"


def test_summary_update_ready(qtbot):
    bar = ResourceSummaryBar()
    qtbot.addWidget(bar)
    state = {
        "resource_readiness": {
            "available_counts": {"well_log": 57, "seismic": 8, "horizon": 3},
            "missing_types": [],
            "ready": True,
        }
    }
    bar.update_state(state)
    assert bar.name_labels["well_log"].text() == tokens.RESOURCE_LABELS["well_log"]
    assert bar.count_labels["well_log"].text() == "57井"
    assert bar.count_labels["seismic"].text() == "8条测线"
    assert bar.count_labels["horizon"].text() == "3层位"
    assert "数据完整" in bar.status_label.text()


def test_summary_update_missing(qtbot):
    bar = ResourceSummaryBar()
    qtbot.addWidget(bar)
    state = {
        "resource_readiness": {
            "available_counts": {"well_log": 0, "seismic": 8, "horizon": 3},
            "missing_types": ["well_log"],
            "ready": False,
        }
    }
    bar.update_state(state)
    assert "缺少" in bar.status_label.text()


def test_summary_object_name(qtbot):
    bar = ResourceSummaryBar()
    qtbot.addWidget(bar)
    assert bar.objectName() == "ResourceSummaryBar"
