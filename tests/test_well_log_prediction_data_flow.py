from __future__ import annotations

from pathlib import Path

from geoviz import CurveData, WellLogData

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.prediction.inference_service import (
    materialize_prediction_task,
    resolve_inputs_for_model,
)
from paleo_workbench.prediction.providers import (
    MODEL_ID_DEMO,
    ensure_default_models,
    ensure_geoviz_online_model,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage


def _well_resource(tmp_path: Path, ident: str, name: str) -> ResourceItem:
    path = tmp_path / name
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                "~WELL INFORMATION",
                f" WELL. {ident}:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "1000.0 40.0",
                "1010.0 50.0",
            ]
        ),
        encoding="utf-8",
    )
    return ResourceItem(
        id=ident,
        name=name,
        path=str(path),
        type="well_log",
        format="las",
    )


def _xml_well_resource(tmp_path: Path, ident: str, name: str) -> ResourceItem:
    path = tmp_path / name
    path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<WITSMLComposite xmlns="http://www.witsml.org/schemas/1series">
  <log>
    <nameWell>XML-1</nameWell>
    <logCurveInfo><mnemonic>DEPT</mnemonic><unit>m</unit></logCurveInfo>
    <logCurveInfo><mnemonic>GR</mnemonic><unit>gAPI</unit></logCurveInfo>
    <logData><data>1000.0, 40.0</data><data>1000.125, 45.0</data></logData>
  </log>
</WITSMLComposite>
""",
        encoding="utf-8",
    )
    return ResourceItem(
        id=ident,
        name=name,
        path=str(path),
        type="well_log",
        format="xml",
    )


def test_selected_data_manager_well_loads_into_prediction_canvas(qtbot, tmp_path, monkeypatch):
    """A well-log resource can be previewed before any prediction task exists."""
    project = ProjectDocument.new("P")
    resource = _well_resource(tmp_path, "well-1", "A-1.las")
    project.resources.append(resource)
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    calls = []
    monkeypatch.setattr(
        page.canvas_panel,
        "show_resource",
        lambda selected, project_arg, prediction_task=None: calls.append(
            (selected, project_arg, prediction_task)
        ),
    )

    page.update_state([], project=project)

    assert page.well_source_combo.count() == 1
    assert page.select_well_resource(resource.id) is True
    assert page.selected_well_resource_id() == resource.id
    assert calls == [(resource, project, None)]
    assert page.evidence_panel.source_value.text() == "数据管理井数据"


def test_catalogued_xml_well_is_selectable_on_prediction_page(qtbot, tmp_path, monkeypatch):
    project = ProjectDocument.new("P")
    resource = _xml_well_resource(tmp_path, "well-xml", "17.xml")
    project.resources.append(resource)
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    calls = []
    monkeypatch.setattr(
        page.canvas_panel,
        "show_resource",
        lambda selected, project_arg, prediction_task=None: calls.append(
            (selected, project_arg, prediction_task)
        ),
    )

    page.update_state([], project=project)

    assert page.well_source_combo.count() == 1
    assert page.well_source_combo.itemText(0) == "17.xml · XML"
    assert page.select_well_resource(resource.id)
    assert calls == [(resource, project, None)]


def test_prediction_page_emits_las_xml_import_request(qtbot, tmp_path, monkeypatch):
    import paleo_workbench.ui.pages.well_log_prediction_page as wlp_page

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page.set_project(ProjectDocument.new("P"))
    source = tmp_path / "incoming.xml"
    source.write_text("<log />", encoding="utf-8")
    # Patch on the imported module object — the dotted-string target resolves
    # through the package __getattr__, which fails when test ordering has not
    # yet imported the submodule.
    monkeypatch.setattr(
        wlp_page.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(source)], "测井数据 (*.las *.LAS *.xml *.XML)"),
    )

    with qtbot.waitSignal(page.well_log_import_requested) as emitted:
        page._on_import_well_logs()

    assert emitted.args == [[str(source)]]


def test_prediction_well_log_import_accepts_generic_named_xml(qtbot, tmp_path):
    """The explicit prediction importer must not rely on XML filename hints."""
    project = ProjectDocument.new("P")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    source = _xml_well_resource(tmp_path, "ignored", "17.xml")

    with qtbot.waitSignal(page.import_finished, timeout=5_000):
        assert page.begin_import_well_log_paths([Path(source.path)])

    assert len(project.resources) == 1
    assert project.resources[0].type == "well_log"
    assert project.resources[0].format == "xml"


def test_prediction_import_routes_through_data_manager_and_selects_result(
    qtbot, tmp_path, monkeypatch
):
    """The page import action keeps catalog provenance and loads its result."""
    from paleo_workbench.app import PaleoWorkbenchWindow

    project = ProjectDocument.new("P")
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    prediction_page = window.app_shell.well_log_prediction_page_widget()
    imported = _xml_well_resource(tmp_path, "ignored", "17.xml")
    calls = []
    monkeypatch.setattr(
        prediction_page.canvas_panel,
        "show_resource",
        lambda selected, project_arg, prediction_task=None: calls.append(selected),
    )

    with qtbot.waitSignal(window.app_shell.data_page.import_finished, timeout=5_000):
        prediction_page.well_log_import_requested.emit([imported.path])

    qtbot.waitUntil(
        lambda: prediction_page.selected_well_resource_id() is not None,
        timeout=5_000,
    )
    selected = next(
        resource
        for resource in project.resources
        if resource.id == prediction_page.selected_well_resource_id()
    )
    assert selected.type == "well_log"
    assert selected.format == "xml"
    assert calls and calls[-1].id == selected.id


def test_selected_data_manager_well_renders_real_las(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    project = ProjectDocument.new("P")
    resource = _well_resource(tmp_path, "well-1", "A-1.las")
    project.resources.append(resource)
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page.update_state([], project=project)

    assert page.select_well_resource(resource.id) is True
    qtbot.waitUntil(page.canvas_panel.has_bound_las, timeout=10_000)

    assert page.canvas_panel.well_log_data.well_name == "well-1"
    assert page.canvas_panel.is_canvas_ready()
    page.shutdown_workers(2_000)


def test_legacy_prediction_canvas_fills_its_available_viewport(qtbot, monkeypatch):
    """The well-log content grows and shrinks with the centre panel."""
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page.resize(1_400, 900)
    page.show()
    page.canvas_panel._show_well_log(
        WellLogData(
            well_name="A-1",
            top_depth=1_000.0,
            bottom_depth=1_100.0,
            curves=[
                CurveData(
                    name="GR",
                    unit="API",
                    depth=[1_000.0, 1_050.0, 1_100.0],
                    values=[30.0, 80.0, 45.0],
                )
            ],
        )
    )
    qtbot.waitUntil(lambda: page.canvas_panel.canvas_scroll.viewport().width() > 0)

    viewport = page.canvas_panel.canvas_scroll.viewport()
    canvas = page.canvas_panel.canvas
    assert canvas.width() == viewport.width()
    assert canvas.height() == viewport.height()

    page.resize(1_000, 650)
    qtbot.waitUntil(
        lambda: canvas.size() == page.canvas_panel.canvas_scroll.viewport().size()
    )


def test_data_page_emits_selected_well_for_prediction(qtbot, tmp_path):
    project = ProjectDocument.new("P")
    resource = _well_resource(tmp_path, "well-1", "A-1.las")
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(resource)

    with qtbot.waitSignal(page.open_in_well_prediction) as emitted:
        page._emit_open_in_well_prediction()

    assert emitted.args == [resource]


def test_data_manager_well_opens_the_prediction_page(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.app import PaleoWorkbenchWindow

    project = ProjectDocument.new("P")
    resource = _well_resource(tmp_path, "well-1", "A-1.las")
    project.resources.append(resource)
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    prediction_page = window.app_shell.well_log_prediction_page_widget()
    calls = []
    monkeypatch.setattr(
        prediction_page.canvas_panel,
        "show_resource",
        lambda selected, project_arg, prediction_task=None: calls.append(
            (selected, project_arg, prediction_task)
        ),
    )

    window.app_shell.data_page.open_in_well_prediction.emit(resource)

    assert window.app_shell.page_stack.currentWidget() is window.app_shell.hub_well
    assert window.app_shell.hub_well.current_page() is prediction_page
    assert prediction_page.selected_well_resource_id() == resource.id
    assert calls == [(resource, project, None)]


def test_selected_well_is_the_only_inference_input_and_is_saved(tmp_path):
    project_file = tmp_path / "P.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    try:
        project = ProjectDocument.new("P")
        first = _well_resource(tmp_path, "well-1", "A-1.las")
        second = _well_resource(tmp_path, "well-2", "A-2.las")
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
        assert service.get_version(input_ids[0]).asset_id in {
            first.id,
            next(
                asset.id
                for asset in service.document.assets
                if asset.legacy_resource_id == first.id
            ),
        }
        task = materialize_prediction_task(
            project,
            {"result_summary": {}, "model": {}},
            name_prefix="测井相预测",
            workflow="well_log_facies",
            well_log_resource_ids=[first.id],
        )
        assert task.input_refs["well_log_resource_ids"] == [first.id]
    finally:
        service.close()


def test_reference_xml_with_gr_satisfies_online_prediction_contract(tmp_path):
    """A rendered WITSML GR well must count as one online-model input well."""
    project_file = tmp_path / "P.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    try:
        project = ProjectDocument.new("P")
        resource = _xml_well_resource(tmp_path, "well-xml", "HZ28.xml")
        project.resources.append(resource)
        service.migrate_legacy_resources(project.resources)
        model = ensure_geoviz_online_model(service)

        input_ids = resolve_inputs_for_model(
            project,
            service,
            model.id,
            strict=True,
            resource_ids=[resource.id],
        )

        assert len(input_ids) == 1
        assert service.get_asset(service.get_version(input_ids[0]).asset_id).type == "well_log"
    finally:
        service.close()


def test_reimported_reference_xml_with_gr_satisfies_online_prediction_contract(
    tmp_path,
):
    """Catalog reuse must not make the fresh project resource resolve as 0 wells."""
    project_file = tmp_path / "P.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    try:
        previous = _xml_well_resource(tmp_path, "previous-import", "HZ28.xml")
        service.migrate_legacy_resources([previous])
        current = previous.model_copy(update={"id": "current-project-resource"})
        project = ProjectDocument.new("P")
        project.resources.append(current)
        model = ensure_geoviz_online_model(service)

        input_ids = resolve_inputs_for_model(
            project,
            service,
            model.id,
            strict=True,
            resource_ids=[current.id],
        )

        assert len(input_ids) == 1
        assert service.get_asset(service.get_version(input_ids[0]).asset_id).type == "well_log"
    finally:
        service.close()
