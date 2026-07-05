from paleo_workbench.ui.pages.resource_summary import ResourceSummaryBar


def test_summary_has_three_type_labels(qtbot):
    bar = ResourceSummaryBar()
    qtbot.addWidget(bar)
    assert len(bar.type_labels) == 3
    texts = [lbl.text() for lbl in bar.type_labels.values()]
    assert any("测井数据" in t for t in texts)
    assert any("地震数据" in t for t in texts)
    assert any("层位数据" in t for t in texts)


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
    assert "57" in bar.type_labels["well_log"].text()
    assert "8" in bar.type_labels["seismic"].text()
    assert "3" in bar.type_labels["horizon"].text()
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
