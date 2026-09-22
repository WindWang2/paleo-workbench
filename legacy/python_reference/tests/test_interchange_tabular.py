"""I4 — tabular (CSV/TSV/Excel) adapters: sniffing, presets, normalization."""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.interchange.adapters.tabular_adapter import (
    CsvAdapter,
    TabularMappingPreset,
    TsvAdapter,
    sniff_delimiter,
)
from paleo_workbench.interchange.contracts import VerificationState

from tests import interchange_fixtures as fx


@pytest.fixture(params=[CsvAdapter, TsvAdapter])
def adapter(request):
    return request.param()


def test_sniff_delimiter_picks_consistent_column_count():
    assert sniff_delimiter("a,b,c\n1,2,3\n4,5,6\n") == ","
    assert sniff_delimiter("a\tb\tc\n1\t2\t3\n") == "\t"
    assert sniff_delimiter("a;b;c\n1;2;3\n") == ";"


def test_inspect_csv_reports_columns_and_mapping(tmp_path, adapter):
    csv_file = fx.write_csv(tmp_path / "samples.csv")
    inspection = adapter.inspect(csv_file)
    assert inspection.ok
    assert inspection.metadata["delimiter"] == ","
    assert inspection.metadata["row_count"] == 10
    header_map = inspection.metadata["header_map"]
    assert header_map.get("well_name") == "Well"
    assert header_map.get("depth") == "Depth"
    assert header_map.get("x") == "X" and header_map.get("y") == "Y"


def test_inspect_tsv_detects_tab_delimiter(tmp_path):
    adapter = TsvAdapter()
    tsv = fx.write_csv(tmp_path / "samples.tsv", delimiter="\t")
    inspection = adapter.inspect(tsv)
    assert inspection.metadata["delimiter"] == "\t"


def test_inspect_flags_duplicate_headers(tmp_path, adapter):
    csv_file = fx.write_duplicate_header_csv(tmp_path / "dup.csv")
    inspection = adapter.inspect(csv_file)
    assert any("重复表头列名" in w for w in inspection.warnings)


def test_inspect_flags_missing_well_column(tmp_path, adapter):
    csv_file = tmp_path / "nowell.csv"
    csv_file.write_text("Depth,Value\n1,2\n3,4\n", encoding="utf-8")
    inspection = adapter.inspect(csv_file)
    assert any("井名列" in w for w in inspection.warnings)


def test_inspect_flags_non_utf8(tmp_path, adapter):
    csv_file = fx.write_shift_jis_ish_csv(tmp_path / "gbk.csv")
    inspection = adapter.inspect(csv_file)
    assert any("编码" in w for w in inspection.warnings)
    assert inspection.metadata["columns"][0] == "井名" or inspection.metadata["columns"]


def test_preset_serializable_and_path_free(tmp_path, adapter):
    csv_file = fx.write_csv(tmp_path / "s.csv")
    plan = adapter.plan_import(csv_file, adapter.inspect(csv_file))
    preset = plan.options["mapping_preset"]
    assert preset["delimiter"] == ","
    serialized = repr(preset)
    assert str(tmp_path) not in serialized
    assert str(csv_file) not in serialized
    revived = TabularMappingPreset.from_dict(preset)
    assert revived.delimiter == ","


def _make_catalog(tmp_path):
    from paleo_workbench.catalog.service import DataCatalogService

    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return DataCatalogService.open(project_path)


def test_normalize_transform_import_registers_utf8_csv(tmp_path, adapter):
    """A GBK semicolon file normalizes to UTF-8 comma CSV before registering."""
    from paleo_workbench.interchange.executor import ImportExecutor

    csv_file = tmp_path / "semicolon.csv"
    lines = ["Well;Depth;Value", "W-1;1.5;2.5", "W-2;2.5;3.5"]
    csv_file.write_bytes("\n".join(lines).encode("gb18030"))

    catalog = _make_catalog(tmp_path)
    executor = ImportExecutor(catalog, work_dir=tmp_path / "work")
    plan = adapter.plan_import(csv_file, adapter.inspect(csv_file))
    plan.options["normalize"] = True
    result = executor.execute(plan)
    version = catalog.get_version(result.version_id)
    assert version.format == "csv"
    registered = Path(catalog.resolve_path(version))
    raw = registered.read_bytes()
    assert raw.startswith(b"Well,Depth,Value")
    assert result.verification is not None and result.verification.ok
    # the staged normalization temp must be cleaned up after registration
    assert result.staged_path is None or not Path(result.staged_path).exists()
    catalog.close()


def test_export_tsv_and_verify(tmp_path):
    adapter = CsvAdapter()
    source = fx.write_csv(tmp_path / "in.csv", rows=5)
    target = tmp_path / "out.tsv"
    plan = adapter.plan_export(source, target)
    from paleo_workbench.interchange.executor import ExportExecutor

    _, verification = ExportExecutor().execute(plan)
    assert verification.state is VerificationState.VERIFIED
    assert "\t" in target.read_text(encoding="utf-8")


def test_excel_inspect_lists_sheets(tmp_path):
    from openpyxl import Workbook

    from paleo_workbench.interchange.adapters.tabular_adapter import ExcelAdapter

    adapter = ExcelAdapter()
    workbook_path = tmp_path / "book.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["井名", "深度", "值"])
    sheet.append(["W-1", 1.5, 2.5])
    workbook.create_sheet("第二表")
    workbook.save(workbook_path)

    inspection = adapter.inspect(workbook_path)
    assert inspection.ok
    names = [s["name"] for s in inspection.metadata["sheets"]]
    assert "数据" in names and "第二表" in names
    assert any("多工作表" in w for w in inspection.warnings)
