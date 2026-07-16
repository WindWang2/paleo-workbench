from paleo_workbench.ui.pages.activity_card import RecentActivityCard


def test_activity_card_title(qtbot):
    card = RecentActivityCard()
    qtbot.addWidget(card)
    assert card.title_label.text() == "最近活动"


def test_activity_card_empty_state(qtbot):
    card = RecentActivityCard()
    qtbot.addWidget(card)
    assert "暂无活动" in card.empty_label.text()


def test_activity_card_update_with_steps(qtbot):
    card = RecentActivityCard()
    qtbot.addWidget(card)
    steps = [
        type("S", (), {"step_type": "data_check", "status": "complete"}),
        type("S", (), {"step_type": "factor_map", "status": "running"}),
        type("S", (), {"step_type": "prediction", "status": "pending"}),
        type("S", (), {"step_type": "map_compile", "status": "pending"}),
        type("S", (), {"step_type": "qc", "status": "pending"}),
        type("S", (), {"step_type": "export", "status": "pending"}),
    ]
    card.update_state({}, steps)
    assert card.entry_count() == 2  # only non-pending steps


def test_activity_card_evidence_fallback_when_all_pending(qtbot):
    card = RecentActivityCard()
    qtbot.addWidget(card)
    steps = [
        type("S", (), {"step_type": "data_check", "status": "pending"}),
        type("S", (), {"step_type": "factor_map", "status": "pending"}),
    ]
    state = {
        "resource_counts": {"well_log": 3, "seismic": 1},
        "factor_map_count": 2,
        "prediction_count": 0,
        "map_document_count": 1,
        "qc_issue_count": 0,
        "export_count": 0,
    }
    card.update_state(state, steps)
    assert card.entry_count() == 3  # resources + factors + map
    assert card.empty_label.isHidden()


def test_activity_card_object_name(qtbot):
    card = RecentActivityCard()
    qtbot.addWidget(card)
    assert card.objectName() == "PanelCard"
