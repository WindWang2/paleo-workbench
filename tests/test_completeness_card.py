from paleo_workbench.ui.pages.completeness_card import DataCompletenessCard
from paleo_workbench.ui import tokens


def test_completeness_card_title(qtbot):
    card = DataCompletenessCard()
    qtbot.addWidget(card)
    assert card.title_label.text() == "数据完整度"


def test_completeness_card_has_three_rows(qtbot):
    card = DataCompletenessCard()
    qtbot.addWidget(card)
    assert len(card.rows) == 3
    labels = [row["name"].text() for row in card.rows]
    assert labels == ["测井数据", "地震数据", "层位数据"]


def test_completeness_card_update_ready(qtbot):
    card = DataCompletenessCard()
    qtbot.addWidget(card)
    state = {
        "resource_readiness": {
            "required_types": ["well_log", "seismic", "horizon"],
            "available_counts": {"well_log": 57, "seismic": 8, "horizon": 3},
            "missing_types": [],
            "ready": True,
        }
    }
    card.update_state(state)
    assert "数据完整" in card.summary_label.text()


def test_completeness_card_update_missing(qtbot):
    card = DataCompletenessCard()
    qtbot.addWidget(card)
    state = {
        "resource_readiness": {
            "required_types": ["well_log", "seismic", "horizon"],
            "available_counts": {"well_log": 0, "seismic": 8, "horizon": 3},
            "missing_types": ["well_log"],
            "ready": False,
        }
    }
    card.update_state(state)
    assert "缺少" in card.summary_label.text()


def test_completeness_card_object_name(qtbot):
    card = DataCompletenessCard()
    qtbot.addWidget(card)
    assert card.objectName() == "PanelCard"
