"""V13 map→data：检查器数据来源行 + 图层绑定（W-M/W-I UI 面）。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.models import ProjectDocument


@pytest.fixture(autouse=True)
def _clean_catalog_runtime():
    reset_catalog()
    yield
    reset_catalog()


@pytest.fixture()
def env(tmp_path: Path, qtbot, monkeypatch):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    project = ProjectDocument.new("demo")
    project.meta.project_root = str(project_path.parent)

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    yield service, project, doc, tmp_path
    reset_catalog()
    service.close()


class TestLayerDataSourceRows:
    def test_bound_layer_shows_source_asset_run_and_checksum(self, env):
        service, project, doc, tmp_path = env
        src = tmp_path / "src.las"
        src.write_text("~W\n", encoding="utf-8")
        raw = service.import_raw(src, name="src.las", type="well_log")
        mid = tmp_path / "mid.out"
        mid.write_text("mid", encoding="utf-8")
        run = service.register_run("prediction", input_version_ids=[raw.id])
        derived = service.register_result_asset(
            name="pred", type="prediction", format="txt",
            asset_metadata=None, source_path=mid, stage="derived",
            run_id=run.id,
        )
        layer_id = doc.edit_controller.create_layer(
            name="预测相", kind="polygon")
        doc.stage_controller.group_controller.register_layer(
            layer_id, LayerRole.WELL_FACIES_PREDICTION,
            source_version_id=derived.id)

        rows = doc.layer_domain_status(layer_id)
        assert "数据来源" in rows
        assert "pred" in rows["数据来源"]
        assert rows["生成方式"] == "run prediction"
        assert rows["上游输入"] == "1 个输入版本"
        assert rows["校验和"] and rows["校验和"] != "—"

    def test_unbound_layer_shows_no_source_rows(self, env):
        service, project, doc, tmp_path = env
        layer_id = doc.edit_controller.create_layer(
            name="随手注记", kind="polygon")
        doc.stage_controller.group_controller.register_layer(
            layer_id, LayerRole.INTERPRETATION_ANNOTATION)
        rows = doc.layer_domain_status(layer_id)
        assert "数据来源" not in rows
        assert "生成方式" not in rows

    def test_manual_edit_binding_labels_run_as_manual(self, env):
        service, project, doc, tmp_path = env
        from paleo_workbench.catalog.lifecycle import (
            complete_manual_edit_run,
            register_manual_edit_run,
        )

        src = tmp_path / "m.las"
        src.write_text("x", encoding="utf-8")
        raw = service.import_raw(src, name="m.las", type="well_log")
        working = service.create_working_copy(raw.id)
        Path(working).write_text("edited", encoding="utf-8")
        run = register_manual_edit_run(
            service, source_version_ids=[raw.id], actor="tester")
        version = service.commit_working_copy(
            working, run_id=run.id)
        complete_manual_edit_run(service, run.id,
                                 committed_version_ids=[version.id])

        layer_id = doc.edit_controller.create_layer(
            name="人工修订", kind="polygon")
        doc.stage_controller.group_controller.register_layer(
            layer_id, LayerRole.INITIAL_FACIES_DRAFT,
            source_version_id=version.id)
        rows = doc.layer_domain_status(layer_id)
        assert "人工修改" in rows["生成方式"]
