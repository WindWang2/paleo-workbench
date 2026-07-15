from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch
import zipfile

import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.fallback_preview import (
    MAX_ARCHIVE_NAMES,
    MAX_EMBEDDED_IMAGE_BYTES,
    dfb_preview,
    pptx_preview,
    spreadsheetml_preview,
    wlp_preview,
    zip_preview,
)
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
)


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUB"
    "AScY42YAAAAASUVORK5CYII="
)


def _resource(path: Path, fmt: str, resource_type: str = "unknown") -> ResourceItem:
    return ResourceItem(name=path.name, path=str(path), type=resource_type, format=fmt)


def _spreadsheetml(rows: int, columns: int, *, second_sheet: bool = False) -> bytes:
    cells = "".join(
        f"<Cell><Data>{column % 10}</Data></Cell>"
        for column in range(columns)
    )
    worksheet = "".join(f"<Row>{cells}</Row>" for _ in range(rows))
    extra = (
        '<Worksheet ss:Name="Ignored"><Table><Row><Cell><Data ss:Type="String">'
        "do-not-read</Data></Cell></Row></Table></Worksheet>"
        if second_sheet
        else ""
    )
    return (
        '<?xml version="1.0"?><Workbook '
        'xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        f'<Worksheet ss:Name="First"><Table>{worksheet}</Table></Worksheet>{extra}'
        "</Workbook>"
    ).encode()


def test_spreadsheetml_preview_is_bounded_to_first_sheet_and_global_table_limits(
    tmp_path: Path,
):
    path = tmp_path / "large.xml"
    path.write_bytes(_spreadsheetml(MAX_TABLE_ROWS + 50, MAX_TABLE_COLUMNS + 5, second_sheet=True))

    result = spreadsheetml_preview(_resource(path, "xml", "spreadsheet"))

    assert result is not None
    assert result.mode == "table"
    assert result.sheets == ("First",)
    assert len(result.table_rows) == MAX_TABLE_ROWS
    assert len(result.table_headers) == MAX_TABLE_COLUMNS
    assert all(len(row) == MAX_TABLE_COLUMNS for row in result.table_rows)
    assert result.truncated is True
    assert "截断" in result.warning
    assert all("do-not-read" not in cell for row in result.table_rows for cell in row)


def test_spreadsheetml_honours_sparse_cell_indexes_without_unbounded_padding(tmp_path: Path):
    path = tmp_path / "sparse.xml"
    path.write_text(
        '<?xml version="1.0"?><Workbook '
        'xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
        '<Worksheet ss:Name="Sparse"><Table><Row>'
        '<Cell ss:Index="40"><Data ss:Type="String">last</Data></Cell>'
        '<Cell ss:Index="1000000"><Data ss:Type="String">outside</Data></Cell>'
        "</Row></Table></Worksheet></Workbook>",
        encoding="utf-8",
    )

    result = spreadsheetml_preview(_resource(path, "xml", "spreadsheet"))

    assert result is not None
    assert len(result.table_headers) == MAX_TABLE_COLUMNS
    assert result.table_headers[-1] == "last"
    assert "outside" not in result.table_headers
    assert result.truncated is True


def test_spreadsheetml_reports_real_malformed_xml_but_keeps_boundary_rows(tmp_path: Path):
    malformed = tmp_path / "malformed.xml"
    malformed.write_bytes(
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet><Table>'
        b"<Row><Cell><Data>broken</Cell></Row>"
    )
    bounded = tmp_path / "bounded.xml"
    prefix = _spreadsheetml(5, 2).replace(
        b"</Table></Worksheet></Workbook>",
        b"<Row><Cell><Data>boundary",
    )
    bounded.write_bytes(prefix + b" " * (256 * 1024))

    malformed_result = spreadsheetml_preview(_resource(malformed, "xml", "spreadsheet"))
    bounded_result = spreadsheetml_preview(_resource(bounded, "xml", "spreadsheet"))

    assert malformed_result is not None
    assert malformed_result.mode == "message"
    assert "XML" in malformed_result.warning
    assert bounded_result is not None
    assert bounded_result.mode == "table"
    assert bounded_result.truncated is True
    assert len(bounded_result.table_rows) == 4


def test_empty_or_non_spreadsheet_xml_is_not_claimed(tmp_path: Path):
    empty = tmp_path / "empty.xml"
    empty.write_bytes(b"")
    ordinary = tmp_path / "ordinary.xml"
    ordinary.write_text("<root><value>text</value></root>", encoding="utf-8")

    empty_result = spreadsheetml_preview(_resource(empty, "xml", "spreadsheet"))
    ordinary_result = spreadsheetml_preview(_resource(ordinary, "xml", "spreadsheet"))

    assert empty_result is not None
    assert empty_result.mode == "message"
    assert "XML" in empty_result.warning
    assert ordinary_result is None


def test_pptx_reads_only_bounded_thumbnail_and_counts_unique_slides(tmp_path: Path):
    path = tmp_path / "slides.pptx"
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("docProps/thumbnail.jpeg", PNG_1X1)
        for number in range(1, 4):
            package.writestr(f"ppt/slides/slide{number}.xml", "<slide />")
        package.writestr("ppt/slides/_rels/slide1.xml.rels", "not a slide")

    with patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("no extract")), patch.object(
        zipfile.ZipFile, "extractall", side_effect=AssertionError("no extractall")
    ):
        result = pptx_preview(_resource(path, "pptx", "document"))

    assert result.mode == "image"
    assert result.image_bytes == PNG_1X1
    assert ("幻灯片数", "3") in result.summary_rows


def test_pptx_rejects_bad_zip_duplicate_directory_and_oversized_thumbnails(tmp_path: Path):
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"not zip")
    duplicate = tmp_path / "duplicate.pptx"
    with zipfile.ZipFile(duplicate, "w") as package:
        package.writestr("docProps/thumbnail.jpeg", PNG_1X1)
        with pytest.warns(UserWarning, match="Duplicate name"):
            package.writestr("docProps/thumbnail.jpeg", PNG_1X1)
    directory = tmp_path / "directory.pptx"
    with zipfile.ZipFile(directory, "w") as package:
        package.writestr("docProps/thumbnail.jpeg/", b"")
    oversized = tmp_path / "oversized.pptx"
    with zipfile.ZipFile(oversized, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("docProps/thumbnail.png", b"x" * (MAX_EMBEDDED_IMAGE_BYTES + 1))

    bad_result = pptx_preview(_resource(bad, "pptx", "document"))
    duplicate_result = pptx_preview(_resource(duplicate, "pptx", "document"))
    directory_result = pptx_preview(_resource(directory, "pptx", "document"))
    oversized_result = pptx_preview(_resource(oversized, "pptx", "document"))

    assert bad_result.mode == "message" and "PPTX" in bad_result.warning
    assert duplicate_result.mode == "message" and "重复" in duplicate_result.warning
    assert directory_result.mode == "message" and directory_result.image_bytes == b""
    assert oversized_result.mode == "message" and "过大" in oversized_result.warning
    assert oversized_result.image_bytes == b""


def test_dfb_prefers_same_stem_sibling_then_validated_embedded_image(tmp_path: Path):
    sibling_dfb = tmp_path / "phase.dfb"
    sibling_dfb.write_bytes(b"ignored" + PNG_1X1)
    sibling = tmp_path / "phase.png"
    sibling.write_bytes(PNG_1X1)
    embedded_dfb = tmp_path / "embedded.dfb"
    embedded_dfb.write_bytes(b"vendor-prefix" + PNG_1X1 + b"vendor-suffix")

    sibling_result = dfb_preview(_resource(sibling_dfb, "dfb", "reference_map"))
    embedded_result = dfb_preview(_resource(embedded_dfb, "dfb", "reference_map"))

    assert sibling_result.mode == "image"
    assert sibling_result.path == str(sibling)
    assert sibling_result.image_bytes == b""
    assert embedded_result.mode == "image"
    assert embedded_result.image_bytes == PNG_1X1


def test_dfb_rejects_unterminated_or_corrupt_embedded_images_as_metadata(tmp_path: Path):
    no_iend = tmp_path / "no-iend.dfb"
    no_iend.write_bytes(b"prefix" + PNG_1X1[:-12])
    bad_chunk = tmp_path / "bad-chunk.dfb"
    corrupted = bytearray(PNG_1X1)
    corrupted[20] ^= 0x01
    bad_chunk.write_bytes(b"prefix" + corrupted)
    no_eoi = tmp_path / "no-eoi.dfb"
    no_eoi.write_bytes(b"prefix\xff\xd8\xff\xe0\x00\x02")

    results = [
        dfb_preview(_resource(path, "dfb", "reference_map"))
        for path in (no_iend, bad_chunk, no_eoi)
    ]

    assert all(result.mode == "message" for result in results)
    assert all(result.image_bytes == b"" for result in results)
    assert all(result.summary_rows for result in results)
    assert all("地质" not in result.message for result in results)


def test_zip_lists_only_first_500_sorted_central_names_without_extracting(tmp_path: Path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for number in reversed(range(600)):
            archive.writestr(f"item-{number:03}.txt", "payload")

    with patch.object(zipfile.ZipFile, "extract", side_effect=AssertionError("no extract")), patch.object(
        zipfile.ZipFile, "extractall", side_effect=AssertionError("no extractall")
    ):
        result = zip_preview(_resource(path, "zip", "archive"))

    assert result.mode == "table"
    assert len(result.table_rows) == MAX_ARCHIVE_NAMES == 500
    assert result.table_rows[0] == ("item-000.txt",)
    assert result.table_rows[-1] == ("item-499.txt",)
    assert result.truncated is True
    assert "截断" in result.warning


def test_zip_bad_package_and_wlp_return_explicit_messages(tmp_path: Path):
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"not zip")
    wlp = tmp_path / "well.wlp"
    wlp.write_bytes(b"vendor bytes")

    zip_result = zip_preview(_resource(bad_zip, "zip", "archive"))
    wlp_result = wlp_preview(_resource(wlp, "wlp", "well_reference"))

    assert zip_result.mode == "message"
    assert "ZIP" in zip_result.warning
    assert wlp_result.mode == "message"
    assert "暂不支持 WLP" in wlp_result.message
