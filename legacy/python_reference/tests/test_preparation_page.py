from paleo_workbench.ui.pages.boundary_panel import BoundaryPanel
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.pages.preparation_page import PreparationPage


def test_preparation_page_assembles_three_panels(qtbot):
    page = PreparationPage()
    qtbot.addWidget(page)
    assert page.objectName() == "PreparationPage"
    assert isinstance(page.task_panel, FactorTaskPanel)
    assert isinstance(page.preview_grid, FactorPreviewGrid)
    assert isinstance(page.boundary_panel, BoundaryPanel)


def test_preparation_page_update_delegates(qtbot):
    page = PreparationPage()
    qtbot.addWidget(page)

    calls = []

    def make_spy():
        return lambda tasks: calls.append(tasks)

    page.task_panel.update_state = make_spy()
    page.preview_grid.update_state = make_spy()

    tasks = [{"id": 1}, {"id": 2}]
    page.update_state(tasks)

    assert calls == [tasks, tasks]
