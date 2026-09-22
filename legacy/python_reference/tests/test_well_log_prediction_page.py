from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QSplitter

from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.pages.prediction_evidence_panel import PredictionEvidencePanel
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.project.models import PredictionTask, ProjectDocument


def _tracked_page(qtbot, tmp_path):
    """A page whose float persistence is bound to a throwaway ini store."""
    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    page = WellLogPredictionPage(persistence=LayoutPersistence(settings))
    qtbot.addWidget(page)
    return page


def test_well_log_prediction_page_assembles_three_widgets(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)

    assert page.objectName() == "WellLogPredictionPage"
    assert isinstance(page.task_panel, PredictionTaskPanel)
    assert isinstance(page.canvas_panel, WellLogCanvasPanel)
    assert isinstance(page.evidence_panel, PredictionEvidencePanel)


def test_well_log_prediction_page_uses_resizable_splitter(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)

    splitter = page.content_splitter
    assert isinstance(splitter, QSplitter)
    assert splitter.objectName() == "WellLogPredictionSplitter"
    assert splitter.count() == 3
    assert splitter.widget(0) is page.task_panel
    assert splitter.widget(1) is page.canvas_panel
    assert splitter.widget(2) is page.evidence_panel
    # Side panels keep their design width as a draggable minimum.
    assert page.task_panel.minimumWidth() < page.task_panel.maximumWidth()
    assert page.evidence_panel.minimumWidth() < page.evidence_panel.maximumWidth()


def test_well_log_prediction_page_splitter_sizes_favor_canvas(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    splitter = page.content_splitter

    page.resize(1280, 800)
    page.show()
    before = splitter.sizes()
    page.resize(1680, 800)
    QApplication.processEvents()
    after = splitter.sizes()

    # 任务 | 画布 | 证据: the canvas is dominant and absorbs the extra width.
    assert before[1] > before[0]
    assert before[1] > before[2]
    assert after[1] - before[1] > after[0] - before[0]
    assert after[1] - before[1] > after[2] - before[2]


def test_well_log_prediction_page_side_panel_float_round_trip(qtbot, tmp_path):
    page = _tracked_page(qtbot, tmp_path)
    page.resize(1280, 800)
    page.show()

    key = "well_log:evidence"
    assert page.float_controller.toggle(key) is True
    assert page.float_controller.is_floating(key)
    floating = page.float_controller.floating_panel(key)
    qtbot.addWidget(floating)
    assert page.evidence_panel.parentWidget() is floating.content_host
    # The canvas never floats — no entry point exists for it.
    assert "well_log:canvas" not in page._floatable
    assert page.canvas_panel.parentWidget() is page.content_splitter

    assert page.float_controller.toggle(key) is True
    assert not page.float_controller.is_floating(key)
    assert page.content_splitter.widget(2) is page.evidence_panel


def test_well_log_prediction_page_float_layout_persists(qtbot, tmp_path):
    ini_path = tmp_path / "layout.ini"

    def build():
        settings = QSettings(str(ini_path), QSettings.Format.IniFormat)
        page = WellLogPredictionPage(persistence=LayoutPersistence(settings))
        qtbot.addWidget(page)
        return page

    page = build()
    page.resize(1280, 800)
    page.show()
    page.float_controller.toggle("well_log:task")
    page.content_splitter.moveSplitter(600, 1)
    page._persist_docked_sizes()

    restored = build()
    assert restored.float_controller.is_floating("well_log:task")
    floating = restored.float_controller.floating_panel("well_log:task")
    qtbot.addWidget(floating)
    assert restored.task_panel.parentWidget() is floating.content_host
    # The undocked evidence panel stays docked, at its persisted share.
    assert not restored.float_controller.is_floating("well_log:evidence")
    assert restored._float_persistence.load("well_log:evidence").docked_sizes


def test_online_prediction_evidence_shows_remote_class_distribution(qtbot):
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)
    task = PredictionTask(
        name="online",
        result_summary={
            "model_type": "inference_api_online",
            "predicted_regions": [{"facies": "分流间湾", "probability": 0.62}],
            "remote_summary": {
                "classCounts": {"分流间湾": 14785, "分流河道": 113}
            },
        },
    )

    panel.update_state(task, bound_las=True)

    assert "分流间湾 99.2%" in panel.class_distribution_value.text()
    assert "分流河道: 113" in panel.class_distribution_value.toolTip()


def test_online_prediction_evidence_shows_and_hides_wait_animation(qtbot):
    """Online inference must have a non-modal, visible running state."""
    panel = PredictionEvidencePanel()
    qtbot.addWidget(panel)

    assert panel.waiting_indicator.minimum() == 0
    assert panel.waiting_indicator.maximum() == 0
    assert panel.waiting_indicator.isHidden()

    panel.set_inferring(True)

    assert not panel.waiting_indicator.isHidden()
    assert not panel.waiting_label.isHidden()
    assert not panel.run_btn.isEnabled()

    panel.set_inferring(False)

    assert panel.waiting_indicator.isHidden()
    assert panel.waiting_label.isHidden()
    assert panel.run_btn.isEnabled()


def test_well_log_prediction_page_update_delegates(qtbot):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    calls = {"task": [], "canvas": [], "evidence": []}

    page.task_panel.update_state = lambda tasks, selected_index=None: calls["task"].append(
        (tasks, selected_index)
    )
    page.canvas_panel.update_state = lambda task, project=None: calls["canvas"].append(
        (task, project)
    )
    page.evidence_panel.update_state = lambda task, bound_las=False: calls["evidence"].append(
        (task, bound_las)
    )
    page.canvas_panel.has_bound_las = lambda: False

    tasks = [{"name": "old"}, {"name": "active"}]
    project = object()
    page.update_state(tasks, project=project)

    assert calls["task"] == [(tasks, None)]
    assert calls["canvas"] == [(tasks[-1], project)]
    assert calls["evidence"] == [(tasks[-1], False)]


def test_well_log_completion_from_replaced_project_is_ignored(qtbot, monkeypatch):
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    old_project = ProjectDocument.new("old")
    new_project = ProjectDocument.new("new")
    service = object()
    page.set_project(old_project)
    page._inference_service = service
    page._active_inference_context = (page._session_token, old_project, service)
    received = []
    monkeypatch.setattr(page, "_on_inference_completed", received.append)

    page.set_project(new_project)
    page._on_inference_completed_if_current({"stale": True})

    assert received == []


def test_complete_run_without_result_is_visible(qtbot, monkeypatch):
    """#635: complete + result=None must not be a silent no-op."""
    from types import SimpleNamespace

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page._project = ProjectDocument.new("p")
    seen: list[str] = []
    monkeypatch.setattr(
        page.evidence_panel,
        "set_status",
        lambda text: seen.append(text),
    )
    page._on_inference_completed(
        {
            "run": SimpleNamespace(
                status="complete",
                parameters={"error": "CatalogStore save failed"},
                output_version_ids=["ver:1"],
            ),
            "result": None,
        }
    )
    assert seen
    assert "CatalogStore save failed" in str(seen[0])


def test_failed_online_run_shows_redacted_copyable_diagnostic_log(qtbot):
    """The page exposes the catalogued online failure, not just a short status."""
    from types import SimpleNamespace

    from paleo_workbench.project.models import ResourceItem

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("P")
    project.resources.append(
        ResourceItem(
            id="well-1",
            name="A14.las",
            path="/tmp/A14.las",
            type="well_log",
            format="las",
        )
    )
    page._project = project
    page._selected_well_resource_id = "well-1"

    page._on_inference_completed(
        {
            "run": SimpleNamespace(
                id="run_404",
                status="failed",
                parameters={
                    "model_version": "20260507-fold15-HZ27-5-3",
                    "online_endpoint": "https://user:secret@example.test/inference?token=abc",
                    "error": "GeoVizOnlinePredictionError: HTTP 404 Authorization: Bearer abc",
                },
                output_version_ids=[],
            ),
            "result": None,
        }
    )

    log = page.evidence_panel.diagnostic_log.toPlainText()
    assert "运行 ID: run_404" in log
    assert "井数据: A14.las" in log
    assert "模型版本: 20260507-fold15-HZ27-5-3" in log
    assert "https://example.test/inference" in log
    assert "HTTP 404" in log
    assert "secret" not in log
    assert "token=abc" not in log
    assert "Bearer abc" not in log


def test_selected_well_restores_its_latest_failed_online_run_log(qtbot, monkeypatch):
    """A past failed online run remains inspectable after a page restart."""
    from types import SimpleNamespace

    from paleo_workbench.project.models import ResourceItem
    import paleo_workbench.ui.pages.well_log_prediction_page as page_module

    resource = ResourceItem(
        id="well-1",
        name="A14.las",
        path="/tmp/A14.las",
        type="well_log",
        format="las",
    )
    latest_failed = SimpleNamespace(
        id="run_latest",
        status="failed",
        created_at="2026-08-23T11:54:58+00:00",
        parameters={
            "workflow": "geoviz_online_well_log_facies",
            "well_log_resource_ids": [resource.id],
            "model_version": "20260507-fold15-HZ27-5-3",
            "online_endpoint": "https://api.example.test/inference",
            "error": "GeoVizOnlinePredictionError: HTTP 404",
        },
    )
    monkeypatch.setattr(
        page_module,
        "get_catalog_service",
        lambda: SimpleNamespace(list_runs=lambda: [latest_failed]),
    )
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("P")
    project.resources.append(resource)
    page.update_state([], project=project)
    monkeypatch.setattr(page.canvas_panel, "show_resource", lambda *args: None)

    assert page.select_well_resource(resource.id)

    assert "run_latest" in page.evidence_panel.diagnostic_log.toPlainText()
    assert "上次推断失败" in page.evidence_panel.status_value.text()
