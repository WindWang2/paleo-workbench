from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.inference_service import (
    materialize_prediction_task,
    resolve_inputs_for_model,
)
from paleo_workbench.prediction.providers import MODEL_ID_DEMO, ensure_default_models
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.viz.models import VizPayload


def _seismic_resource(
    tmp_path: Path,
    ident: str,
    name: str,
    *,
    fmt: str = "sgy",
    rtype: str = "seismic",
) -> ResourceItem:
    path = tmp_path / name
    path.write_bytes(b"segy-stub")
    return ResourceItem(
        id=ident,
        name=name,
        path=str(path),
        type=rtype,
        format=fmt,
    )


def test_seismic_source_selector_lists_only_workarea_segy(qtbot, tmp_path):
    project = ProjectDocument.new("P")
    first = _seismic_resource(tmp_path, "seis-1", "cube-1.sgy")
    second = _seismic_resource(tmp_path, "seis-2", "cube-2.segy", fmt="segy")
    project.resources.extend(
        (
            first,
            second,
            _seismic_resource(tmp_path, "seis-npz", "volume.npz", fmt="npz"),
            _seismic_resource(
                tmp_path, "not-seismic", "well.sgy", rtype="well_log"
            ),
        )
    )
    page = SeismicPredictionPage()
    qtbot.addWidget(page)

    page.update_state([], project=project)

    assert page.seismic_source_combo.count() == 2
    assert [page.seismic_source_combo.itemData(i) for i in range(2)] == [
        first.id,
        second.id,
    ]
    assert page.seismic_source_combo.itemText(0) == "cube-1.sgy · SGY"
    assert page.selected_seismic_resource_id() is None


def test_selected_workarea_segy_loads_before_prediction(qtbot, tmp_path, monkeypatch):
    project = ProjectDocument.new("P")
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")
    project.resources.append(resource)
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    calls = []
    monkeypatch.setattr(
        page.view_panel,
        "show_resource",
        lambda selected, project_arg: calls.append((selected, project_arg)),
    )

    page.update_state([], project=project)

    assert page.select_seismic_resource(resource.id)
    assert page.selected_seismic_resource_id() == resource.id
    assert calls == [(resource, project)]


def test_seismic_view_panel_can_preview_resource_directly(qtbot, tmp_path, monkeypatch):
    project = ProjectDocument.new("P")
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")
    project.resources.append(resource)
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    scheduled = []

    from paleo_workbench.viz.adapter import VizAdapter

    monkeypatch.setattr(
        VizAdapter,
        "resolve",
        lambda self, ref, project_arg: VizPayload(
            kind="seismic", label=resource.name, seismic_path=resource.path
        ),
    )
    monkeypatch.setattr(panel.view, "load_segy_async", scheduled.append)

    assert panel.show_resource(resource, project)
    assert scheduled == [resource.path]
    assert panel.stack.currentWidget() is panel.view


def test_demo_uses_selected_seismic_resource(qtbot, tmp_path, monkeypatch):
    project = ProjectDocument.new("P")
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")
    project.resources.append(resource)
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.update_state([], project=project)
    monkeypatch.setattr(page.view_panel, "show_resource", lambda *args: True)
    assert page.select_seismic_resource(resource.id)

    service = SimpleNamespace(
        get_model_version=lambda model_id, version: SimpleNamespace(id="model-version")
    )
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.seismic_prediction_page.get_catalog_service",
        lambda: service,
    )
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.seismic_prediction_page.ensure_default_models",
        lambda current: None,
    )
    calls = []
    monkeypatch.setattr(
        page,
        "_start_inference",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    page._on_demo()

    assert calls[0][1]["seismic_resource_id"] == resource.id


def test_data_page_emits_selected_segy_for_seismic_prediction(qtbot, tmp_path):
    project = ProjectDocument.new("P")
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(resource)

    with qtbot.waitSignal(page.open_in_seismic_prediction) as emitted:
        page._emit_open_in_seismic_prediction()

    assert emitted.args == [resource]


def test_data_manager_segy_opens_seismic_prediction_page(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow

    project = ProjectDocument.new("P")
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")
    project.resources.append(resource)
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    prediction_page = window.app_shell.seismic_prediction_page_widget()
    calls = []
    monkeypatch.setattr(
        prediction_page.view_panel,
        "show_resource",
        lambda selected, project_arg: calls.append((selected, project_arg)),
    )

    window.app_shell.data_page.open_in_seismic_prediction.emit(resource)

    assert window.app_shell.page_stack.currentWidget() is prediction_page
    assert prediction_page.selected_seismic_resource_id() == resource.id
    assert calls == [(resource, project)]


def test_seismic_context_menu_offers_prediction_handoff(qtbot, tmp_path):
    menu = AssetContextMenu()
    resource = _seismic_resource(tmp_path, "seis-1", "cube.sgy")

    menu.build(resource, viz_supported=True, seismic_prediction_supported=True)

    action = menu.find_action("ctx_seismic_prediction")
    assert action is not None
    assert action.text() == "在地震预测中打开"


def test_selected_seismic_is_the_only_inference_input_and_is_saved(tmp_path):
    project_file = tmp_path / "P.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    try:
        project = ProjectDocument.new("P")
        first = _seismic_resource(tmp_path, "seis-1", "cube-1.sgy")
        second = _seismic_resource(tmp_path, "seis-2", "cube-2.sgy")
        project.resources.extend((first, second))
        service.migrate_legacy_resources(project.resources)
        ensure_default_models(service)
        model = service.get_model_version(MODEL_ID_DEMO, "1")

        input_ids = resolve_inputs_for_model(
            project,
            service,
            model.id,
            strict=True,
            resource_ids=[first.id],
        )

        assert len(input_ids) == 1
        task = materialize_prediction_task(
            project,
            {"result_summary": {}, "model": {}},
            name_prefix="地震相预测",
            workflow="seismic_facies",
            seismic_resource_ids=[first.id],
        )
        assert task.input_refs["seismic_resource_ids"] == [first.id]
    finally:
        service.close()
