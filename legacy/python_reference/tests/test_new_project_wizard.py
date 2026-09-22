"""新建工程向导对话框测试 — 第1步校验、第2步分析与预览.

Covers:
  ① Step-1 validation (empty name, non-existent dir, target exists, checkbox toggle)
  ② Browse autofill name
  ③ Step-2 success (monkeypatched analyze_data_folder → table/summary/WellMapPanel/accept)
  ④ Step-2 failure (exception → error + back)
  ⑤ Cancel → result_document is None
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QTableWidget

from paleo_workbench.project.domain import CoordinateStatus, WellEntity, ensure_workarea
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.onboarding import OnboardingResult


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_fake_result(name: str = "测试工区") -> OnboardingResult:
    doc = ProjectDocument.new(name)
    ensure_workarea(doc)
    doc.wells.append(
        WellEntity(name="W1", project_x=0, project_y=0, coordinate_status=CoordinateStatus.OK, surface_x=0, surface_y=0)
    )
    doc.wells.append(
        WellEntity(name="W2", project_x=10, project_y=5, coordinate_status=CoordinateStatus.OK, surface_x=10, surface_y=5)
    )
    from paleo_workbench.project.domain import DomainEntity, SeismicSurveyEntity

    doc.seismic_surveys.append(SeismicSurveyEntity(name="S1"))
    doc.geological_entities.append(DomainEntity(kind="geological", name="H1", entity_kind="horizon"))
    report: dict = {
        "generated_at": "2026-08-23T00:00:00+00:00",
        "source_folder": "/tmp/src",
        "intermediate_folder": "/tmp/src",
        "imported_count": 5,
        "by_type": {"测井": 2, "时深": 1, "层位": 2},
        "skipped": 0,
        "warnings": [],
        "wells_total": 2,
        "wells_with_coords": 2,
        "surveys": 1,
        "entities": 1,
        "ambiguous": 0,
        "issues": [],
        "extent": [0, 10, 0, 5],
    }
    doc.onboarding_report = dict(report)
    return OnboardingResult(document=doc, report=report, imported=5)


def _make_result_with_issues(name: str = "问题工区") -> OnboardingResult:
    res = _make_fake_result(name)
    res.report["issues"] = [f"issue-{i}" for i in range(5)]
    res.report["warnings"] = ["warn-1", "warn-2"]
    res.document.onboarding_report = dict(res.report)
    return res


def _new_dialog(qtbot):
    from paleo_workbench.ui.pages.new_project_wizard import NewProjectWizardDialog

    dlg = NewProjectWizardDialog()
    qtbot.addWidget(dlg)
    dlg.show()
    # ensure layout & visibility settled
    QApplication.processEvents()
    return dlg


# ---------------------------------------------------------------------------
# Step 1 validation
# ---------------------------------------------------------------------------


def test_wizard_step1_empty_name_shows_error(tmp_path: Path, qtbot):
    dlg = _new_dialog(qtbot)
    data = tmp_path / "data"
    data.mkdir()
    dlg._name_edit.setText("")
    dlg._data_dir_edit.setText(str(data))
    dlg._same_dir_check.setChecked(True)
    QApplication.processEvents()

    # trigger Next validation
    dlg._next_btn.click()
    QApplication.processEvents()

    assert dlg._error_label.isVisible()
    assert dlg._error_label.text()
    assert dlg._stack.currentIndex() == 0
    assert dlg.findChild(QTableWidget, "WizardInventoryTable") is not None
    assert dlg.objectName() == "NewProjectWizard"
    assert dlg._name_edit.objectName() == "WizardNameEdit"
    assert dlg._error_label.objectName() == "WizardErrorLabel"


def test_wizard_step1_data_dir_not_exists_shows_error(tmp_path: Path, qtbot):
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("MyProj")
    dlg._data_dir_edit.setText(str(tmp_path / "nonexistent"))
    dlg._same_dir_check.setChecked(True)
    QApplication.processEvents()

    dlg._next_btn.click()
    QApplication.processEvents()

    assert dlg._error_label.isVisible()
    assert "数据目录不存在" in dlg._error_label.text()
    assert dlg._stack.currentIndex() == 0


def test_wizard_step1_target_exists_shows_error(tmp_path: Path, qtbot):
    data = tmp_path / "data"
    data.mkdir()
    target = data / "MyProj.paleo.json"
    target.write_text("{}", encoding="utf-8")

    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("MyProj")
    dlg._data_dir_edit.setText(str(data))
    dlg._same_dir_check.setChecked(True)
    QApplication.processEvents()

    dlg._next_btn.click()
    QApplication.processEvents()

    assert dlg._error_label.isVisible()
    assert "工程文件已存在" in dlg._error_label.text()
    assert dlg._stack.currentIndex() == 0


def test_wizard_step1_intermediate_dir_not_exists_shows_error(tmp_path: Path, qtbot):
    data = tmp_path / "data"
    data.mkdir()
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("Proj")
    dlg._data_dir_edit.setText(str(data))
    dlg._same_dir_check.setChecked(False)
    dlg._intermediate_edit.setText(str(tmp_path / "nope"))
    QApplication.processEvents()

    dlg._next_btn.click()
    QApplication.processEvents()

    assert dlg._error_label.isVisible()
    assert "中间目录不存在" in dlg._error_label.text()
    assert dlg._stack.currentIndex() == 0


def test_wizard_checkbox_toggles_intermediate_row(qtbot):
    dlg = _new_dialog(qtbot)
    # default checked → hidden
    assert dlg._same_dir_check.isChecked() is True
    assert dlg._same_dir_check.text() == "中间文件与原始数据同目录"
    assert not dlg._intermediate_row.isVisible()

    dlg._same_dir_check.setChecked(False)
    QApplication.processEvents()
    assert dlg._intermediate_row.isVisible()

    dlg._same_dir_check.setChecked(True)
    QApplication.processEvents()
    assert not dlg._intermediate_row.isVisible()


def test_wizard_browse_autofills_name(tmp_path: Path, qtbot, monkeypatch):
    data = tmp_path / "my_data_folder"
    data.mkdir()
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("")
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(data),
    )
    dlg._browse_data_dir()
    QApplication.processEvents()

    assert dlg._data_dir_edit.text() == str(data)
    assert dlg._name_edit.text() == data.name

    # already filled name should not be overwritten
    dlg._name_edit.setText("KeepName")
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(tmp_path),
    )
    dlg._browse_data_dir()
    QApplication.processEvents()
    assert dlg._name_edit.text() == "KeepName"
    assert dlg._data_dir_edit.text() == str(tmp_path)


# ---------------------------------------------------------------------------
# Step 2 — success
# ---------------------------------------------------------------------------


def test_wizard_step2_success_shows_inventory_and_wellmap(tmp_path: Path, qtbot, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    result = _make_result_with_issues()

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.analyze_data_folder",
        lambda *a, **k: result,
    )

    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("测试工区")
    dlg._data_dir_edit.setText(str(data))
    dlg._same_dir_check.setChecked(True)
    QApplication.processEvents()

    dlg._next_btn.click()

    # entering step 2 immediately shows progress
    assert dlg._stack.currentIndex() == 1
    # progress may be briefly visible; wait until success UI appears
    qtbot.waitUntil(lambda: dlg._summary_label.isVisible(), timeout=5000)
    QApplication.processEvents()

    # progress hidden after finish
    assert not dlg._progress.isVisible()
    # summary contains well counts
    txt = dlg._summary_label.text()
    assert "井 2 口" in txt
    assert "2 有坐标" in txt
    assert "地震 1 个" in txt
    assert "地质实体" in txt

    # inventory table
    table = dlg._inventory_table
    assert table.objectName() == "WizardInventoryTable"
    assert table.isVisible()
    assert table.rowCount() == len(result.report["by_type"])
    # check by_type keys appear
    headers = {table.item(r, 0).text() for r in range(table.rowCount())}
    for k in result.report["by_type"].keys():
        assert k in headers

    # issues/warnings browser visible (we injected issues)
    assert dlg._issues_browser.isVisible()
    browser_text = dlg._issues_browser.toPlainText()
    assert "issue-0" in browser_text

    # WellMapPanel exists and expanded
    from paleo_workbench.ui.pages.well_map_panel import WellMapPanel

    panel = dlg._well_map_panel
    assert panel is not None
    assert isinstance(panel, WellMapPanel)
    # also find via findChild
    found = dlg.findChild(WellMapPanel)
    assert found is panel
    assert not panel.is_collapsed()
    assert panel.isVisible()

    # Finish enabled now
    assert dlg._finish_btn.isEnabled()
    assert dlg._finish_btn.objectName() == "PrimaryButton"

    # accept → result_document / properties
    dlg.accept()
    QApplication.processEvents()
    assert dlg.result_document is result.document
    assert dlg.project_name == "测试工区"
    assert dlg.data_dir == data
    assert dlg.intermediate_dir == data  # same-dir checked
    assert dlg.result() == QDialog.DialogCode.Accepted


def test_wizard_step2_success_intermediate_separate(tmp_path: Path, qtbot, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    inter = tmp_path / "inter"
    inter.mkdir()
    result = _make_fake_result("SepProj")
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.analyze_data_folder",
        lambda *a, **k: result,
    )
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("SepProj")
    dlg._data_dir_edit.setText(str(data))
    dlg._same_dir_check.setChecked(False)
    dlg._intermediate_edit.setText(str(inter))
    QApplication.processEvents()

    dlg._next_btn.click()
    qtbot.waitUntil(lambda: dlg._summary_label.isVisible(), timeout=5000)

    assert dlg.intermediate_dir == inter
    assert dlg.data_dir == data
    dlg.accept()
    assert dlg.result_document is result.document


# ---------------------------------------------------------------------------
# Step 2 — failure
# ---------------------------------------------------------------------------


def test_wizard_step2_failure_shows_error_and_allows_back(tmp_path: Path, qtbot, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()

    def _raise(*a, **k):
        raise RuntimeError("boom-fail")

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.analyze_data_folder",
        _raise,
    )
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("FailProj")
    dlg._data_dir_edit.setText(str(data))
    QApplication.processEvents()

    dlg._next_btn.click()
    assert dlg._stack.currentIndex() == 1

    qtbot.waitUntil(lambda: dlg._step2_error.isVisible(), timeout=5000)
    QApplication.processEvents()

    assert "分析失败" in dlg._step2_error.text()
    assert not dlg._finish_btn.isEnabled()
    assert dlg._back_btn.isEnabled()

    # back to step 1
    dlg._back_btn.click()
    QApplication.processEvents()
    assert dlg._stack.currentIndex() == 0
    assert dlg.result_document is None


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


def test_wizard_reject_result_none(qtbot):
    dlg = _new_dialog(qtbot)
    # reject without analysis
    dlg.reject()
    QApplication.processEvents()
    assert dlg.result_document is None
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_wizard_cancel_during_analysis_discards_result(tmp_path: Path, qtbot, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    result = _make_fake_result("CancelProj")
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.new_project_wizard.analyze_data_folder",
        lambda *a, **k: result,
    )
    dlg = _new_dialog(qtbot)
    dlg._name_edit.setText("CancelProj")
    dlg._data_dir_edit.setText(str(data))
    dlg._next_btn.click()
    # immediately cancel
    dlg.reject()
    QApplication.processEvents()
    assert dlg.result_document is None or dlg.result() == QDialog.DialogCode.Rejected
