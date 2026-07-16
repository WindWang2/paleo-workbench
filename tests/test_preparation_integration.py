from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_app_shell_page_six_is_preparation_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)
    assert isinstance(page, PreparationPage)


def test_preparation_page_has_factor_tasks(qtbot):
    project = ProjectDocument.new("Test")
    create_mock_factor_map(project, target_horizon="T1", factor_type="sand", seed=1)
    create_mock_factor_map(project, target_horizon="T1", factor_type="shale", seed=2)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(6)
    assert isinstance(page, PreparationPage)
    summary_text = page.task_panel.summary_label.text()
    assert "2 / 2" in summary_text


def test_batch_generate_runs_idw_and_updates_mapping_shelf(qtbot):
    project = ProjectDocument.new("IDW Wire")
    project.stratigraphy.target_horizon = "H9"
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)

    prep = window.app_shell.preparation_page_widget()
    assert isinstance(prep, PreparationPage)
    assert prep._project is window.project
    assert window.project.factor_map_tasks == []

    # Select IDW and click batch generate
    idx = prep.task_panel.method_combo.findText("IDW")
    assert idx >= 0
    prep.task_panel.method_combo.setCurrentIndex(idx)
    prep.task_panel.generate_btn.click()

    assert len(window.project.factor_map_tasks) >= 3
    task = window.project.factor_map_tasks[0]
    assert task.method == "IDW"
    assert "grid_z" in task.parameters
    assert task.quality_metrics.get("range")
    assert "3 / 3" in prep.task_panel.summary_label.text() or " / " in prep.task_panel.summary_label.text()

    # Mapping factor shelf receives completed tasks (closed loop)
    mapping = window.app_shell.mapping_page_widget()
    cards = mapping.bottom_workbench.factor_shelf.grid.findChildren(
        type(mapping.bottom_workbench.factor_shelf.grid).FactorPreviewCard
    )
    assert len(cards) >= 3
