from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar


def test_context_toolbar_displays_active_context_and_emits_run(qtbot):
    task = MockPredictionAdapter().run(ProjectDocument.new("Test"), [], seed=3)
    toolbar = SeismicContextToolbar()
    qtbot.addWidget(toolbar)
    runs: list[bool] = []
    toolbar.run_requested.connect(lambda: runs.append(True))

    toolbar.set_context(task, "C6", "包络", "wiggle")
    toolbar.run_btn.click()

    assert toolbar.objectName() == "SeismicContextToolbar"
    assert toolbar.task_value.text() == task.name
    assert toolbar.horizon_value.text() == "C6"
    assert toolbar.attribute_value.text() == "包络"
    assert toolbar.attribute_combo.currentText() == "包络"
    assert toolbar.mode_value.text() == "wiggle"
    assert runs == [True]


def test_context_toolbar_attribute_combo_and_popup_menu(qtbot):
    toolbar = SeismicContextToolbar()
    qtbot.addWidget(toolbar)
    attr_events: list[str] = []
    mode_events: list[str] = []
    toolbar.attribute_changed.connect(attr_events.append)
    toolbar.display_mode_changed.connect(mode_events.append)

    # 1. Attribute combo changes emit attribute_changed
    toolbar.attribute_combo.setCurrentText("瞬时频率")
    assert attr_events == ["瞬时频率"]
    assert toolbar.attribute_value.text() == "瞬时频率"

    # 2. Settings button and popup menu are configured
    assert toolbar.settings_btn.text() == "设置与详情 ▾"
    assert toolbar.settings_menu is not None
    assert toolbar.seismic_source_combo is not None

    # 3. Switching display mode from menu action
    toolbar._on_mode_action_triggered("wiggle")
    assert mode_events == ["wiggle"]
    assert toolbar.mode_value.text() == "wiggle"

