"""I3 — LAS adapter diagnostics, plan/execute/verify lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.interchange.adapters.las_adapter import LasAdapter
from paleo_workbench.interchange.contracts import VerificationState

from tests import interchange_fixtures as fx


@pytest.fixture()
def adapter():
    return LasAdapter()


def test_inspect_valid_las_reports_units_and_curves(tmp_path, adapter):
    las = fx.write_valid_las(tmp_path / "w1.las", curves=(("DEPT", "M"), ("GR", "GAPI")))
    inspection = adapter.inspect(las)
    assert inspection.ok
    assert inspection.units.get("GR") == "GAPI"
    assert inspection.metadata["well_name"] == "W-001"
    assert inspection.metadata["row_count"] == 20
    assert inspection.metadata["depth_direction"] == "increasing"
    assert inspection.warnings == []


def test_inspect_flags_duplicate_mnemonics(tmp_path, adapter):
    las = fx.write_duplicate_mnemonic_las(tmp_path / "dup.las")
    inspection = adapter.inspect(las)
    assert inspection.ok
    assert any("重复曲线助记名" in w for w in inspection.warnings)


def test_inspect_flags_nonmonotonic_depth(tmp_path, adapter):
    las = fx.write_nonmonotonic_las(tmp_path / "bad_order.las")
    inspection = adapter.inspect(las)
    assert any("深度顺序异常" in w for w in inspection.warnings)


def test_inspect_flags_malformed_rows(tmp_path, adapter):
    las = fx.write_malformed_rows_las(tmp_path / "malformed.las")
    inspection = adapter.inspect(las)
    assert any("行数据格式异常" in w for w in inspection.warnings)


def test_inspect_flags_non_utf8(tmp_path, adapter):
    las = fx.write_gbk_encoded_las(tmp_path / "gbk.las")
    inspection = adapter.inspect(las)
    assert any("UTF-8" in w for w in inspection.warnings)


def test_inspect_truncated_file_still_reports(tmp_path, adapter):
    las = fx.write_truncated_las(tmp_path / "cut.las")
    inspection = adapter.inspect(las)
    # header survives but the counted row count reflects the truncation;
    # the report must stay honest either way (warnings, no crash)
    assert inspection.format_id == "las"


def test_missing_file_fails_inspection(tmp_path, adapter):
    inspection = adapter.inspect(tmp_path / "missing.las")
    assert not inspection.ok
    assert inspection.errors


def test_plan_and_export_csv_roundtrip(tmp_path, adapter):
    las = fx.write_valid_las(tmp_path / "w.las")
    target = tmp_path / "out" / "w.csv"
    target.parent.mkdir(exist_ok=True)
    plan = adapter.plan_export(las, target, options={})
    path, verification = _export(adapter, las, plan)
    assert path == target
    assert verification.state in (VerificationState.VERIFIED, VerificationState.VERIFIED_WITH_WARNINGS)
    content = target.read_text(encoding="utf-8-sig")
    assert "GR" in content

    # JSON summary variant
    target_json = tmp_path / "out" / "w.json"
    plan_json = adapter.plan_export(las, target_json)
    _, v_json = _export(adapter, las, plan_json)
    assert v_json.ok


def test_plan_export_rejects_las_writer(tmp_path, adapter):
    las = fx.write_valid_las(tmp_path / "w.las")
    with pytest.raises(Exception):
        adapter.plan_export(las, tmp_path / "copy.las")


def _export(adapter, source, plan):
    from paleo_workbench.interchange.executor import ExportExecutor

    executor = ExportExecutor()
    return executor.execute(plan)
