from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.seismic_task_panel import SeismicTaskPanel
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel


def test_seismic_prediction_page_assembles_three_widgets(qtbot):
    page = SeismicPredictionPage()
    qtbot.addWidget(page)

    assert page.objectName() == "SeismicPredictionPage"
    assert isinstance(page.task_panel, SeismicTaskPanel)
    assert isinstance(page.view_panel, SeismicViewPanel)
    assert isinstance(page.control_panel, SeismicControlPanel)


def test_seismic_prediction_page_update_delegates(qtbot):
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    calls = {"task": [], "view": [], "control": []}

    page.task_panel.update_state = lambda tasks, selected_index=None: calls["task"].append(
        (tasks, selected_index)
    )
    page.view_panel.update_state = lambda task, project=None: calls["view"].append(
        (task, project)
    )
    page.control_panel.update_state = lambda task, volume_shape=None: calls["control"].append(
        (task, volume_shape)
    )
    page.view_panel.volume_shape = (8, 10, 12)

    tasks = [{"name": "old"}, {"name": "active"}]
    project = object()
    page.update_state(tasks, project=project)

    assert calls["task"] == [(tasks, None)]
    assert calls["view"] == [(tasks[-1], project)]
    assert calls["control"] == [(tasks[-1], (8, 10, 12))]
