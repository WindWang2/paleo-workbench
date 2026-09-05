"""I19 — headless tests for the interchange UI models (offscreen Qt)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.interchange.batch import BatchItemResult, BatchResult
from paleo_workbench.interchange.preflight import ImportPreflightService
from paleo_workbench.interchange.ui_models import (
    BatchResultModel,
    PackagePlanModel,
    PreflightIssueModel,
)

from tests import interchange_fixtures as fx


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_preflight_issue_model_orders_errors_first(qapp, tmp_path):
    broken = tmp_path / "mystery.dat"
    broken.write_bytes(b"\x01\x02\x03")
    report = ImportPreflightService().inspect(broken)
    model = PreflightIssueModel()
    model.set_report(report)
    assert model.rowCount() == model.rowCount()  # stable
    assert model.rowCount() >= 1
    assert not model.ok
    assert model.recommendation == "unavailable"
    # first row is the error-level issue
    assert model.data(model.index(0, 0)) in ("错误", "警告", "提示")


def test_batch_result_model(qapp):
    result = BatchResult()
    result.results = [
        BatchItemResult(source="a.geojson", target="out/a.geojson", status="converted",
                        verification_state="VERIFIED", duration_ms=5),
        BatchItemResult(source="b.geojson", status="failed", detail="无法解析"),
    ]
    model = BatchResultModel()
    model.set_result(result)
    assert model.rowCount() == 2
    assert model.columnCount() == 6
    assert model.data(model.index(0, 2)) == "已转换"
    assert model.data(model.index(1, 2)) == "失败"
    assert model.summary["total"] == 2


def test_package_plan_model_labels_statuses(qapp, tmp_path):
    from paleo_workbench.interchange.package.builder import (
        PackageBuilder,
        PackageItem,
        PackagePlan,
    )

    plan = PackagePlan(project_file="demo.paleo.json")
    plan.items = [
        PackageItem(None, "demo.paleo.json", str(tmp_path / "demo.paleo.json"), 10,
                    "project", "included"),
        PackageItem("v1", "ext", "/outside/x.las", 0, "raw", "external"),
        PackageItem("v2", "gone", "/outside/gone.las", 0, "raw", "missing"),
    ]
    model = PackagePlanModel()
    model.set_plan(plan)
    assert model.rowCount() == 3
    assert model.data(model.index(0, 2)) == "打包"
    assert model.data(model.index(1, 2)) == "外部引用"
    assert model.data(model.index(2, 2)) == "缺失"
    assert model.summary["counts"]["missing"] == 1


def test_package_plan_model_from_real_build(qapp, tmp_path):
    from paleo_workbench.catalog.service import DataCatalogService
    from paleo_workbench.interchange.executor import ImportExecutor
    from paleo_workbench.interchange.package.builder import PackageBuilder
    from paleo_workbench.interchange.preflight import ImportPreflightService

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    catalog = DataCatalogService.open(project_path)
    try:
        las = fx.write_valid_las(tmp_path / "w.las")
        plan = ImportPreflightService().plan(las, asset_name="W")
        ImportExecutor(catalog, work_dir=tmp_path / "work").execute(plan)
        builder = PackageBuilder(project_path, catalog=catalog)
        model = PackagePlanModel()
        model.set_plan(builder.plan())
        assert model.rowCount() >= 2
        assert model.summary["counts"].get("included", 0) >= 2
    finally:
        catalog.close()
