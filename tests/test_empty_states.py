"""Empty-state labels must use the EmptyStateLabel objectName so the shared
QSS rule (muted TEXT_SECONDARY color) applies. Companion to the focus-ring
audit in test_focus_states.py.

Scope: key empty / no-selection placeholders surfaced to the user.
"""
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.inspector_panel import InspectorPanel


def test_reader_empty_label_uses_empty_state_label(qtbot):
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_reader_message_label_uses_empty_state_label(qtbot):
    # The message slot doubles as a placeholder/loading surface, so it shares
    # the EmptyStateLabel styling.
    panel = DataReaderPanel()
    qtbot.addWidget(panel)
    assert panel.message_label.objectName() == "EmptyStateLabel"


def test_inspector_empty_state_clears_on_none(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert panel.metadata_table.rowCount() == 0


def test_inspector_empty_label_uses_empty_state_label(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    assert panel.empty_label.objectName() == "EmptyStateLabel"


def test_inspector_empty_label_shown_when_no_selection(qtbot):
    panel = InspectorPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    # isHidden() is controlled explicitly in update_asset, unlike isVisible()
    # which depends on the headless display state.
    assert panel.empty_label.isHidden() is False


def test_inspector_empty_label_hidden_when_asset_selected(qtbot):
    from paleo_workbench.project.models import ResourceItem

    panel = InspectorPanel()
    qtbot.addWidget(panel)
    res = ResourceItem(
        name="well1.las", path="/data/well1.las", type="well_log", format="LAS",
        status="parsed",
    )
    panel.update_asset(res)
    assert panel.empty_label.isHidden() is True
