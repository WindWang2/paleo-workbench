"""L3 — curve-processing toolbox dialog (offscreen widget contract)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
lasio = pytest.importorskip("lasio")

pytestmark = pytest.mark.qt_no_exception_capture

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.ui.pages.curve_operation_dialog import (
    CurveOperationDialog,
    run_curve_operation_dialog,
)
from paleo_workbench.workflow.curve_interpretation import CURVE_OPERATIONS


@pytest.fixture()
def catalog_las(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    source = tmp_path / "raw.las"
    depths = np.arange(1000.0, 1010.0, 0.5)
    lines = [
        "~VERSION INFORMATION", "VERS. 2.0", "WRAP. NO",
        "~WELL", "STRT.M 1000.0 : Start depth", "STOP.M 1009.5 : Stop depth",
        "STEP.M 0.5 : Step", "NULL. -999.25 : Null value",
        "~CURVE INFORMATION", "DEPT.M : Depth", "GR.gAPI : Gamma Ray",
        "~PARAMETER INFORMATION", "~OTHER", "~ASCII LOG DATA",
    ]
    for d in depths:
        lines.append(f"{d:10.3f} {60.0:10.4f}")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    version = service.import_raw(source, name="W-DLG", type="well_log")
    return service, version


def _select_op(dialog: CurveOperationDialog, op: str) -> None:
    index = next(
        i for i in range(dialog.operation_combo.count())
        if dialog.operation_combo.itemData(i) == op
    )
    dialog.operation_combo.setCurrentIndex(index)


def test_dialog_lists_every_registered_operation(qtbot, catalog_las):
    service, version = catalog_las
    dialog = CurveOperationDialog(service, version.id)
    qtbot.addWidget(dialog)
    listed = {
        dialog.operation_combo.itemData(i)
        for i in range(dialog.operation_combo.count())
    }
    assert listed == set(CURVE_OPERATIONS)


def test_parameter_rows_follow_operation_scope(qtbot, catalog_las):
    service, version = catalog_las
    dialog = CurveOperationDialog(service, version.id)
    qtbot.addWidget(dialog)

    _select_op(dialog, "despike")
    names = set(dialog._rows)
    assert {"threshold_sigma", "window"} <= names

    _select_op(dialog, "resample")
    assert "step" in dialog._rows
    assert not dialog.curve_edit.isEnabled()  # file-scope: curve input irrelevant

    _select_op(dialog, "derive_curve")
    assert {"expression", "result_mnemonic", "result_unit"} <= set(dialog._rows)
    assert dialog.curve_edit.isEnabled()  # derive still validates the file


def test_collect_parameters_reads_editors(qtbot, catalog_las):
    service, version = catalog_las
    dialog = CurveOperationDialog(service, version.id)
    qtbot.addWidget(dialog)
    _select_op(dialog, "smooth")
    dialog._rows["window"].setValue(9)
    assert dialog._collect_parameters() == {"window": 9}
    _select_op(dialog, "normalize")
    combo = dialog._rows["method"]
    assert isinstance(combo, QComboBox)
    combo.setCurrentIndex(1)
    assert dialog._collect_parameters() == {"method": "minmax"}


def test_run_dialog_creates_derived_version(qtbot, catalog_las, monkeypatch):
    service, version = catalog_las
    captured: dict[str, object] = {}

    class _Dialog(CurveOperationDialog):
        def exec(self):  # pretend the user pressed OK
            return 1

    def _fake_show(parent, title, text):  # swallow the success box
        captured["message"] = text

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", staticmethod(_fake_show))

    import paleo_workbench.ui.pages.curve_operation_dialog as dlg_mod

    monkeypatch.setattr(dlg_mod, "CurveOperationDialog", _Dialog)
    output_id = run_curve_operation_dialog(None, service, version.id)
    assert output_id is not None
    derived = service.get_version(str(output_id))
    assert derived.id != version.id
    assert derived.parent_version_ids == [version.id]
    # The run carries the operation contract.
    run = next(r for r in service.document.runs if output_id in (r.output_version_ids or ()))
    assert run.operation == "curve_interpretation:despike"  # first combo entry
    assert run.generator == "curve-interpretation-v2"


def test_diagnostics_button_reports_gaps(qtbot, catalog_las, monkeypatch):
    service, version = catalog_las
    dialog = CurveOperationDialog(service, version.id)
    qtbot.addWidget(dialog)

    shown: dict[str, str] = {}

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda parent, title, text: shown.update(message=text)),
    )
    dialog._run_diagnostics()
    assert "GR" in shown.get("message", "")
    assert "缺失样点" in shown["message"]
