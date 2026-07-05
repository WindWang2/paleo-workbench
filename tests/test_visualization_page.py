from paleo_workbench.ui.pages.composite_visualization_panel import CompositeVisualizationPanel
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.visualization_summary_panel import VisualizationSummaryPanel
from paleo_workbench.ui.pages.visualization_trace_panel import VisualizationTracePanel


def test_visualization_page_assembles_three_widgets(qtbot):
    page = VisualizationPage()
    qtbot.addWidget(page)

    assert page.objectName() == "VisualizationPage"
    assert isinstance(page.summary_panel, VisualizationSummaryPanel)
    assert isinstance(page.composite_panel, CompositeVisualizationPanel)
    assert isinstance(page.trace_panel, VisualizationTracePanel)


def test_visualization_page_update_delegates(qtbot):
    page = VisualizationPage()
    qtbot.addWidget(page)
    calls = {"summary": [], "composite": [], "trace": []}

    page.summary_panel.update_state = lambda *args: calls["summary"].append(args)
    page.composite_panel.update_state = lambda tasks: calls["composite"].append(tasks)
    page.trace_panel.update_state = lambda tasks, maps: calls["trace"].append((tasks, maps))

    resources = [{"name": "res"}]
    tasks = [{"name": "task"}]
    maps = [{"name": "map"}]
    page.update_state(resources, tasks, maps)

    assert calls["summary"] == [(resources, tasks, maps)]
    assert calls["composite"] == [tasks]
    assert calls["trace"] == [(tasks, maps)]
