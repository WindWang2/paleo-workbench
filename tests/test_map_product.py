"""P1-D — MapProduct: multi-factor paleogeographic product assembly.

A MapProduct composes validated factor maps + interpretations + manual
adjustments + a cartographic composition into ONE OUTPUT version with the
complete lineage. Fail-closed: synthetic/mock inputs are refused rather
than laundered into a product (compile_map_production discipline).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.map_product import (
    MapProductAssembly,
    assemble_map_product,
)


def _task(task_id: str, *, source: str = "real", has_grid: bool = True) -> FactorMapTask:
    return FactorMapTask(
        id=task_id,
        name=f"task {task_id}",
        target_horizon="H1",
        factor_type="sand_ratio",
        method="kriging",
        parameters={},
        status="complete",
        source_kind=source,
        grid_artifact_version_id=f"ver_{task_id}" if has_grid else None,
    )


@pytest.fixture()
def project() -> ProjectDocument:
    project = ProjectDocument(id="p1", name="产品工程", meta=ProjectMeta(name="产品工程"))
    project.factor_map_tasks = [_task("t1"), _task("t2")]
    return project


@pytest.fixture()
def catalog(tmp_path: Path) -> DataCatalogService:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


class TestAssemblyValidation:
    def test_rejects_mock_factor_tasks(self, project):
        project.factor_map_tasks[1] = _task("t2", source="mock")
        with pytest.raises(ValueError, match="mock"):
            assemble_map_product(
                project,
                assembly=MapProductAssembly(
                    product_name="古地理图",
                    factor_task_ids=["t1", "t2"],
                ),
            )

    def test_rejects_tasks_without_grid_versions(self, project):
        project.factor_map_tasks[1] = _task("t2", has_grid=False)
        with pytest.raises(ValueError, match="grid"):
            assemble_map_product(
                project,
                assembly=MapProductAssembly(product_name="x", factor_task_ids=["t1", "t2"]),
            )

    def test_rejects_unknown_task_ids(self, project):
        with pytest.raises(ValueError, match="unknown"):
            assemble_map_product(
                project,
                assembly=MapProductAssembly(product_name="x", factor_task_ids=["t1", "nope"]),
            )

    def test_requires_at_least_one_factor(self, project):
        with pytest.raises(ValueError, match="at least one"):
            assemble_map_product(
                project,
                assembly=MapProductAssembly(product_name="x", factor_task_ids=[]),
            )


class TestProductAssembly:
    def test_assembles_output_version_with_full_lineage(self, project, catalog, tmp_path):
        payload = tmp_path / "product.json"
        payload.write_text("{}", encoding="utf-8")
        result = assemble_map_product(
            project,
            assembly=MapProductAssembly(
                product_name="沙河街组三期古地理图",
                factor_task_ids=["t1", "t2"],
                interpretation_refs=["interp_a", "interp_b"],
                composition_ref="comp_1",
                notes="物源来自北东向",
            ),
            catalog=catalog,
            payload_path=payload,
        )
        assert result.product_name == "沙河街组三期古地理图"
        assert result.output_version_id
        version = catalog.get_version(result.output_version_id)
        assert version.stage.value == "output"
        run = next(r for r in catalog.document.runs if r.id == result.run_id)
        assert run.operation == "map_product_assembly"
        # Input lineage: both factor grids' versions are run inputs.
        assert set(run.input_version_ids) >= {"ver_t1", "ver_t2"}
        assert run.parameters["factor_task_ids"] == ["t1", "t2"]
        assert run.parameters["interpretation_refs"] == ["interp_a", "interp_b"]
        assert run.parameters["composition_ref"] == "comp_1"
        assert run.generator == "map-product-v1"
        # The project record references the output version.
        record = next(
            r for r in project.map_products if r.product_name == result.product_name
        )
        assert record.output_version_id == result.output_version_id
        assert record.factor_task_ids == ["t1", "t2"]

    def test_reproducible_fingerprint(self, project):
        a = MapProductAssembly(product_name="x", factor_task_ids=["t1", "t2"])
        b = MapProductAssembly(product_name="x", factor_task_ids=["t1", "t2"])
        c = MapProductAssembly(product_name="x", factor_task_ids=["t2", "t1"])
        assert a.scientific_fingerprint(project) == b.scientific_fingerprint(project)
        assert a.scientific_fingerprint(project) != c.scientific_fingerprint(project)
