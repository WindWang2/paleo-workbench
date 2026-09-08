"""V8 M10 — product lifecycle provenance graph (pure data for Inspector)."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task
from paleo_workbench.workflow.map_product import MapProductRecord
from paleo_workbench.workflow.provenance_graph import build_product_lifecycle_graph


@pytest.fixture()
def project() -> ProjectDocument:
    doc = ProjectDocument(meta=ProjectMeta(name="m10"))
    doc.coordinate.project_crs = "EPSG:32650"
    doc.constraint_layers.append(
        ConstraintLayers(
            name="约束层",
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    name="F1", role="break", coordinates=[[0.0, 0.0], [10.0, 0.0]]
                )
            ],
        )
    )
    doc.factor_map_tasks.append(
        FactorMapTask(
            name="砂地比",
            target_horizon="H1",
            method="IDW",
            factor_type="砂地比",
            parameters={
                "sample_points": [
                    {"x": float(i * 10), "y": float(i % 5), "value": float(i)}
                    for i in range(10)
                ]
            },
        )
    )
    return doc


def _record(project: ProjectDocument) -> MapProductRecord:
    record = MapProductRecord(
        product_name="P1",
        factor_task_ids=[project.factor_map_tasks[0].id],
    )
    project.map_products.append(record)
    return record


class TestLifecycleGraph:
    def test_unknown_product_reports_gap(self, project):
        result = build_product_lifecycle_graph(project, product_id="ghost")
        assert result["nodes"] == []
        assert result["gaps"][0]["scope"] == "product:ghost"

    def test_graph_links_product_task_version_constraints(self, project):
        task = project.factor_map_tasks[0]
        apply_interpolation_to_task(task, project=project)
        task.grid_artifact_version_id = "ver_demo_1"
        record = _record(project)

        result = build_product_lifecycle_graph(project, product_id=record.id)
        kinds = {n["kind"] for n in result["nodes"]}
        assert "map_product" in kinds
        assert "factor_task" in kinds
        assert "factor_output" in kinds
        assert "constraints" in kinds

        ids = {n["id"] for n in result["nodes"]}
        assert f"product:{record.id}" in ids
        assert f"factor_task:{task.id}" in ids
        assert "version:ver_demo_1" in ids

        relations = {(e["source"], e["target"], e["relation"]) for e in result["edges"]}
        assert (
            f"product:{record.id}",
            f"factor_task:{task.id}",
            "assembles_factor",
        ) in relations
        assert any(r == "consumed_constraints" for _s, _t, r in relations)
        # constraint node carries the content hash pin (V8 M2)
        constraint_node = next(n for n in result["nodes"] if n["kind"] == "constraints")
        assert constraint_node["content_hash"]

    def test_missing_grid_version_is_a_gap_not_an_exception(self, project):
        record = _record(project)  # task never interpolated
        result = build_product_lifecycle_graph(project, product_id=record.id)
        assert any(
            g["scope"] == f"factor_task:{project.factor_map_tasks[0].id}"
            and "no persisted grid version" in g["reason"]
            for g in result["gaps"]
        )

    def test_fusion_versions_appear_with_catalog(self, project, tmp_path):
        from paleo_workbench.catalog.service import DataCatalogService
        from paleo_workbench.workflow.factor_fusion import (
            FactorEvidence,
            FusionModel,
            Normalization,
            fuse,
            register_output,
        )
        from paleo_workbench.workflow.factor_grid_result import FactorGridResult

        project_path = tmp_path / "proj" / "d.paleo.json"
        project_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        service = DataCatalogService.open(project_path)
        try:
            (tmp_path / "a.npz").write_bytes(b"a")
            parent = service.import_raw(
                tmp_path / "a.npz", name="a.npz", type="factor_map"
            )
            grid = FactorGridResult(
                grid_z=np.array([[30.0, 70.0]], dtype=np.float32),
                grid_x=np.linspace(0, 2, 2),
                grid_y=np.linspace(0, 1, 1),
                factor_name="A",
                algorithm_id="idw",
                crs="EPSG:32650",
                unit="1",
                source_refs=[parent.id],
            )
            model = FusionModel(
                name="F",
                kind="weighted_evidence",
                evidences=[
                    FactorEvidence("A", grid, 1.0, Normalization("minmax", 0, 100))
                ],
                class_thresholds=[0.5],
                class_names=["低", "高"],
            )
            result_fuse = fuse(model)
            register_output(service, result_fuse)

            record = _record(project)
            graph = build_product_lifecycle_graph(project, service)
            kinds = [n["kind"] for n in graph["nodes"]]
            assert "fusion_output" in kinds
        finally:
            service.close()
