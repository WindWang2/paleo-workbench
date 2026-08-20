"""Regression tests for #893: BOM handling and csv field-size limits.

Excel's "CSV UTF-8" export writes a leading BOM, and the csv module's default
131072-char field limit sits below the preview byte budget. Preview parsers
must survive both without leaking ``\ufeff`` into headers or raising
uncaught ``_csv.Error``.
"""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.document_parsers import (
    json_preview,
    markdown_rich_preview,
)
from paleo_workbench.resources.preview_parsers.table_parsers import table_preview
from paleo_workbench.ui.pages.preview_settings import PreviewSettings


def _resource(path: Path, fmt: str, type_: str = "tabular") -> ResourceItem:
    return ResourceItem(
        name=path.name, path=str(path), type=type_, format=fmt, status="parsed"
    )


def test_csv_bom_header_is_stripped(tmp_path: Path):
    path = tmp_path / "bom.csv"
    path.write_bytes("\ufeffName,X\nalpha,1\nbeta,2\n".encode("utf-8"))
    result = table_preview(_resource(path, "csv"), ",", PreviewSettings.defaults())
    assert result.mode == "table"
    assert result.table_headers == ("Name", "X")
    assert result.table_rows == (("alpha", "1"), ("beta", "2"))


def test_tsv_bom_header_is_stripped(tmp_path: Path):
    path = tmp_path / "bom.tsv"
    path.write_bytes("\ufeffName\tX\nalpha\t1\nbeta\t2\n".encode("utf-8"))
    result = table_preview(_resource(path, "tsv"), "\t", PreviewSettings.defaults())
    assert result.mode == "table"
    assert result.table_headers == ("Name", "X")
    assert result.table_rows == (("alpha", "1"), ("beta", "2"))


def test_json_bom_parses(tmp_path: Path):
    path = tmp_path / "bom.json"
    path.write_bytes('\ufeff{"a": 1, "b": [1, 2]}'.encode("utf-8"))
    result = json_preview(
        _resource(path, "json", "document"), PreviewSettings.defaults()
    )
    assert result.mode == "json_tree"
    assert result.json_payload == {"a": 1, "b": [1, 2]}
    assert result.json_truncated is False


def test_markdown_bom_first_heading_detected(tmp_path: Path):
    path = tmp_path / "bom.md"
    path.write_bytes("\ufeff# Title\n\nbody text".encode("utf-8"))
    result = markdown_rich_preview(
        _resource(path, "md", "document"), PreviewSettings.defaults()
    )
    assert result.mode == "rich_text"
    assert "<h1>Title</h1>" in result.rich_html


def test_csv_oversized_single_field_parses_within_budget(tmp_path: Path):
    """A quoted field larger than csv's 131072-char default must not escape
    table_preview as _csv.Error while still inside the 256 KiB budget."""
    path = tmp_path / "bigcell.csv"
    path.write_bytes(b"h1,h2\nalpha,\"" + b"x" * 200_000 + b"\"\n")
    result = table_preview(_resource(path, "csv"), ",", PreviewSettings.defaults())
    assert result.mode == "table"
    assert result.table_headers == ("h1", "h2")
    assert result.table_rows[0][0] == "alpha"
