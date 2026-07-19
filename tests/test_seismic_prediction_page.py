from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel
from paleo_workbench.ui.pages.seismic_attribute_panel import SeismicAttributePanel
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.project.models import ProjectDocument


def test_seismic_prediction_page_assembles_analysis_workbench(qtbot):
    page = SeismicPredictionPage()
    qtbot.addWidget(page)

    assert page.objectName() == "SeismicPredictionPage"
    assert isinstance(page.context_toolbar, SeismicContextToolbar)
    assert isinstance(page.attribute_panel, SeismicAttributePanel)
    assert isinstance(page.view_panel, SeismicViewPanel)
    assert isinstance(page.control_panel, SeismicControlPanel)
    assert not hasattr(page, "task_panel")


def test_seismic_prediction_page_update_delegates(qtbot):
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    calls = {"view": [], "control": [], "context": []}

    page.context_toolbar.set_context = lambda task, horizon, attribute, mode: calls[
        "context"
    ].append(
        (task, horizon, attribute, mode)
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

    assert calls["view"] == [(tasks[-1], project)]
    assert calls["control"] == [(tasks[-1], (8, 10, 12))]
    assert calls["context"] == [(tasks[-1], "—", "振幅", "vd")]


def test_seismic_page_routes_attribute_and_toolbar_actions(qtbot):
    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    with qtbot.waitSignal(page.prediction_updated, timeout=1000):
        page.context_toolbar.run_btn.click()

    page.attribute_panel.set_selected_attribute("包络")
    item = page.attribute_panel.attribute_tree.topLevelItem(0).child(1)
    page.attribute_panel.attribute_tree.itemClicked.emit(item, 0)

    assert page.view_panel.attribute_label() == "包络"
