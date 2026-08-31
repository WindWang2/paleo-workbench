from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QSplitter

from paleo_workbench.ui.layout_persistence import LayoutPersistence
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


def test_visualization_page_uses_resizable_splitter(qtbot):
    page = VisualizationPage()
    qtbot.addWidget(page)

    splitter = page.content_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.objectName() == "VisualizationSplitter"
    assert splitter.count() == 2
    assert splitter.widget(0) is page.composite_panel
    assert splitter.widget(1) is page.trace_panel
    # The trace panel keeps its design width as a resizable minimum.
    assert page.trace_panel.minimumWidth() < page.trace_panel.maximumWidth()

    page.resize(1280, 800)
    page.show()
    before = splitter.sizes()
    page.resize(1680, 800)
    QApplication.processEvents()
    after = splitter.sizes()

    # 综合可视化 stays the stretchy center and absorbs the extra width.
    assert before[0] > before[1]
    assert after[0] - before[0] > after[1] - before[1]


def test_visualization_page_trace_panel_float_round_trip(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    page = VisualizationPage(persistence=LayoutPersistence(settings))
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()

    key = "visualization:trace"
    assert page.float_controller.toggle(key) is True
    floating = page.float_controller.floating_panel(key)
    qtbot.addWidget(floating)
    assert page.trace_panel.parentWidget() is floating.content_host
    # The composite center never floats — no entry point exists for it.
    assert "visualization:composite" not in page._floatable
    assert page.composite_panel.parentWidget() is page.content_splitter

    assert page.float_controller.toggle(key) is True
    assert page.content_splitter.widget(1) is page.trace_panel


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
