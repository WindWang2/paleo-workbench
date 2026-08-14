import pytest
from PySide6.QtWidgets import QMessageBox

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService, reset_catalog, set_catalog
from paleo_workbench.prediction.providers import ensure_default_models
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


def test_seismic_completion_from_replaced_project_is_ignored(qtbot, monkeypatch):
    page = SeismicPredictionPage()
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


@pytest.fixture
def catalog_service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    yield service
    reset_catalog()
    service.close()


def test_run_without_catalog_shows_unavailable_state(qtbot, monkeypatch):
    """No active catalog → explicit unavailable state, NO auto-run of mock."""
    # The catalog is process-global runtime state; do not inherit a service
    # from an earlier catalog-backed test when asserting the unavailable path.
    reset_catalog()
    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a) or 0)
    )

    page.context_toolbar.run_btn.click()
    assert warnings, "expected an unavailable-state warning"
    assert "未连接数据目录" in warnings[-1][2]
    # No task was auto-created.
    assert project.prediction_tasks == []


def test_run_without_production_model_shows_unavailable(qtbot, monkeypatch, catalog_service):
    """Registry has only demo models → no production model → no run."""
    ensure_default_models(catalog_service)
    assert catalog_service.find_production_model("facies_prediction") is None

    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a) or 0)
    )
    page.context_toolbar.run_btn.click()
    assert "未配置生产模型" in warnings[-1][2]
    assert project.prediction_tasks == []


def test_demo_run_creates_honestly_marked_task(qtbot, catalog_service):
    """Explicit demo mode runs DemoModelProvider → task marked demo/mock."""
    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    with qtbot.waitSignal(page.prediction_updated, timeout=5000):
        page.context_toolbar.demo_btn.click()

    assert len(project.prediction_tasks) == 1
    task = project.prediction_tasks[0]
    assert task.result_summary.get("is_mock") is True
    assert task.result_summary.get("final_scientific_prediction") is False
    assert task.result_summary.get("demo") is True
    assert task.model_metadata.get("demo_only") is True
    # The inference run is tracked in the catalog with a DERIVED output.
    # Stage-13 renamed the run operation "inference" → "prediction"
    # (freshness.py still accepts the legacy value for migrated projects).
    runs = [r for r in catalog_service.document.runs if r.operation == "prediction"]
    assert runs, "expected an inference DataRun"
    assert runs[-1].status == "complete"
    assert len(runs[-1].output_version_ids) == 1
    version = catalog_service.get_version(runs[-1].output_version_ids[0])
    assert version.metadata.get("source") == "synthetic/demo"
    assert version.metadata.get("demo") is True


def test_seismic_page_routes_attribute_and_toolbar_actions(qtbot):
    project = ProjectDocument.new("Run")
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    page.attribute_panel.set_selected_attribute("包络")
    item = page.attribute_panel.attribute_tree.topLevelItem(0).child(1)
    page.attribute_panel.attribute_tree.itemClicked.emit(item, 0)

    assert page.view_panel.attribute_label() == "包络"
