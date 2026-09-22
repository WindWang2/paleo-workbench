"""V13 ingest plan UI（W-G）：dialog 构建/编辑/执行走同一 service。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import WellEntity, links_for_entity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.ingest_plan_dialog import IngestPlanDialog


@pytest.fixture()
def env(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("demo")
    doc.meta.project_root = str(tmp_path)
    doc.wells.append(WellEntity(name="Well-A"))
    yield service, doc, tmp_path
    service.close()


def _make_import_root(tmp_path: Path) -> Path:
    root = tmp_path / "import_root"
    well_a = root / "Well-A"
    well_a.mkdir(parents=True)
    (well_a / "A.las").write_text(
        "~W\nWELL: Well-A\n~C\nDT 1 1\n", encoding="utf-8")
    (well_a / "A2.las").write_text(
        "~W\nWELL: Well-A\n~C\nRHOB 1 1\n", encoding="utf-8")
    (well_a / "tops.csv").write_text("fm,md\nF1,100\n", encoding="utf-8")
    (root / "mystery.xyz").write_text("unknown\n", encoding="utf-8")
    return root


def _open_dialog(qtbot, env) -> IngestPlanDialog:
    service, doc, tmp_path = env
    root = _make_import_root(tmp_path)
    dialog = IngestPlanDialog(
        None, service=service, project=doc, root=root)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(
        lambda: dialog._plan is not None or "失败" in dialog.summary_label.text(),
        timeout=15000,
    )
    assert dialog._plan is not None, dialog.summary_label.text()
    return dialog


class TestIngestPlanDialog:
    def test_build_populates_model_and_summary(self, qtbot, env):
        dialog = _open_dialog(qtbot, env)
        plan = dialog._plan
        assert dialog._model.rowCount() == len(plan.items)
        # 2 LAS + 1 tops.csv（.xyz 非首选扩展名，正确地不进计划）
        assert len(plan.items) == 3
        summary = dialog.summary_label.text()
        assert "共 3" in summary and "重复 0" in summary
        dialog._teardown_worker()

    def test_accept_all_and_execute_registers_and_binds(self, qtbot, env):
        service, doc, tmp_path = env
        dialog = _open_dialog(qtbot, env)
        dialog._accept_all()
        assert all(item.decision == "accept"
                   for item in dialog._plan.items
                   if not item.duplicate_of_version)
        # 待确认项（.xyz 无法分类/匹配）默认跳过，不静默入库
        dialog._skip_unresolved()

        with qtbot.waitSignal(dialog.ingest_finished, timeout=30000):
            dialog._execute()

        report = dialog._report
        assert report is not None
        assert len(report.imported_version_ids) >= 3
        assert report.bound_links >= 1
        # 实体绑定落位：Well-A 有 well_log/tops 链接
        well = doc.wells[0]
        roles = {link.role for link in links_for_entity(doc, "well", well.id)}
        assert {"well_log", "tops"} <= roles
        # 登记版本真实存在且为 RAW
        version = service.get_version(report.imported_version_ids[0])
        assert version.stage.value == "raw"
        dialog._teardown_worker()

    def test_detail_panel_edits_decision_and_role(self, qtbot, env):
        dialog = _open_dialog(qtbot, env)
        item = next(i for i in dialog._plan.items
                    if i.path.suffix == ".csv")
        dialog.detail.set_item(item, project=dialog._project)
        combo_index = dialog.detail.decision_combo.findData("skip")
        dialog.detail.decision_combo.setCurrentIndex(combo_index)
        assert item.decision == "skip"
        role_index = dialog.detail.role_combo.findData("other")
        if role_index >= 0:
            dialog.detail.role_combo.setCurrentIndex(role_index)
            assert item.role == "other"
        dialog._teardown_worker()

    def test_execute_idempotent_rerun_skips_registered(self, qtbot, env):
        dialog = _open_dialog(qtbot, env)
        dialog._accept_all()
        dialog._skip_unresolved()
        with qtbot.waitSignal(dialog.ingest_finished, timeout=30000):
            dialog._execute()
        first = len(dialog._report.imported_version_ids)
        assert first >= 1
        # 幂等重跑：同 (path, sha) 跳过
        dialog.execute_btn.setEnabled(True)
        with qtbot.waitSignal(dialog.ingest_finished, timeout=30000):
            dialog._execute()
        assert len(dialog._report.imported_version_ids) == 0
        assert len(dialog._report.skipped) >= first
        dialog._teardown_worker()
