from __future__ import annotations

import base64
import io
from pathlib import Path
import struct
from unittest.mock import patch
import zipfile

import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.preview_parsers.office_parsers import (
    dfb_preview,
    pptx_preview,
    spreadsheetml_preview,
    wlp_preview,
    zip_preview,
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


def _patch_eocd(path: Path, offset: int, format_code: str, value: int) -> None:
    payload = bytearray(path.read_bytes())
    eocd = payload.rfind(b"PK\x05\x06")
    assert eocd >= 0
    struct.pack_into(format_code, payload, eocd + offset, value)
    path.write_bytes(payload)


def test_spreadsheetml_preview_is_bounded_to_first_sheet_and_global_table_limits(
    tmp_path: Path,
):
    path = tmp_path / "large.xml"
    path.write_bytes(_spreadsheetml(250, 45, second_sheet=True))

    result = spreadsheetml_preview(_resource(path, "xml", "spreadsheet"))

    assert result is not None
    assert result.mode == "table"
    assert result.sheets == ("First",)
    assert len(result.table_rows) == 200
    assert len(result.table_headers) == 40
    assert all(len(row) == 40 for row in result.table_rows)
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
    assert len(result.table_headers) == 40
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


def test_spreadsheetml_malformed_inside_last_budget_chunk_is_not_truncation(tmp_path: Path):
    path = tmp_path / "malformed-near-boundary.xml"
    prefix = (
        b'<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet">'
        b"<Worksheet><Table><Row><Cell><Data>"
    )
    bad_close_offset = 250 * 1024
    payload = prefix + b"x" * (bad_close_offset - len(prefix)) + b"</Cell>"
    path.write_bytes(payload + b"x" * (256 * 1024 - len(payload) + 4096))

    result = spreadsheetml_preview(_resource(path, "xml", "spreadsheet"))

    assert result is not None
    assert result.mode == "message"
    assert result.truncated is False
    assert "XML 格式错误" in result.warning


def test_spreadsheetml_ignores_foreign_namespace_elements(tmp_path: Path):
    path = tmp_path / "mixed-namespace.xml"
    path.write_text(
        '<?xml version="1.0"?>'
        '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet" '
        'xmlns:ext="urn:vendor-extension">'
        '<ext:Worksheet><ext:Table><ext:Row><ext:Cell><ext:Data>evil</ext:Data>'
        '</ext:Cell></ext:Row></ext:Table></ext:Worksheet>'
        '<Worksheet ss:Name="Real"><Table><Row>'
        '<ext:Cell><ext:Data>ignored</ext:Data></ext:Cell>'
        '<Cell><Data>good</Data></Cell>'
        "</Row></Table></Worksheet></Workbook>",
        encoding="utf-8",
    )

    result = spreadsheetml_preview(_resource(path, "xml", "spreadsheet"))

    assert result is not None
    assert result.mode == "table"
    assert result.sheets == ("Real",)
    assert result.table_headers == ("good",)


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

    with patch.object(
        zipfile.ZipFile,
        "extract",
        side_effect=AssertionError("no extract"),
    ), patch.object(
        zipfile.ZipFile,
        "extractall",
        side_effect=AssertionError("no extractall"),
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
        package.writestr("docProps/thumbnail.png", b"x" * (16 * 1024 * 1024 + 1))

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
    assert sibling_result.image_bytes == PNG_1X1
    assert embedded_result.mode == "image"
    assert embedded_result.image_bytes == PNG_1X1


def test_dfb_sibling_suffix_matching_is_case_insensitive_and_png_first(tmp_path: Path):
    path = tmp_path / "mixed.dfb"
    path.write_bytes(b"vendor")
    png = tmp_path / "mixed.PnG"
    jpg = tmp_path / "mixed.JpG"
    jpeg = tmp_path / "mixed.jPeG"
    png.write_bytes(b"png-preview")
    jpg.write_bytes(b"jpg-preview")
    jpeg.write_bytes(b"jpeg-preview")

    result = dfb_preview(_resource(path, "dfb", "reference_map"))

    assert result.mode == "image"
    assert result.path == str(png)
    assert result.image_bytes == b"png-preview"


def test_dfb_rejects_sibling_larger_than_16_mib_without_reading_unbounded(
    tmp_path: Path,
):
    path = tmp_path / "oversized.dfb"
    path.write_bytes(b"vendor")
    sibling = tmp_path / "oversized.png"
    sibling.write_bytes(b"x" * (16 * 1024 * 1024 + 1))

    result = dfb_preview(_resource(path, "dfb", "reference_map"))

    assert result.mode == "message"
    assert result.image_bytes == b""
    assert "16 MiB" in result.warning


def test_dfb_rejects_unterminated_or_corrupt_embedded_images_as_metadata(tmp_path: Path):
    no_iend = tmp_path / "no-iend.dfb"
    no_iend.write_bytes(b"prefix" + PNG_1X1[:-12])
    bad_chunk = tmp_path / "bad-chunk.dfb"
    corrupted = bytearray(PNG_1X1)
    corrupted[20] ^= 0x01
    bad_chunk.write_bytes(b"prefix" + corrupted)
    no_eoi = tmp_path / "no-eoi.dfb"
    no_eoi.write_bytes(b"prefix\xff\xd8\xff\xe0\x00\x02")
    fake_markers = tmp_path / "fake-markers.dfb"
    fake_markers.write_bytes(
        b"prefix\xff\xd8"  # SOI
        b"\xff\xc0\x00\x02"  # empty SOF0
        b"\xff\xda\x00\x02"  # empty SOS
        b"\xff\xd9"  # EOI
    )

    results = [
        dfb_preview(_resource(path, "dfb", "reference_map"))
        for path in (no_iend, bad_chunk, no_eoi, fake_markers)
    ]

    assert all(result.mode == "message" for result in results)
    assert all(result.image_bytes == b"" for result in results)
    assert all(result.summary_rows for result in results)
    assert all("地质" not in result.message for result in results)


def test_dfb_accepts_structurally_consistent_jpeg_with_scan_and_eoi(tmp_path: Path):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (2, 3), color=(10, 20, 30)).save(buffer, format="JPEG")
    jpeg_bytes = buffer.getvalue()
    path = tmp_path / "embedded-jpeg.dfb"
    path.write_bytes(b"prefix" + jpeg_bytes + b"suffix")

    result = dfb_preview(_resource(path, "dfb", "reference_map"))

    assert result.mode == "image"
    assert result.image_bytes == jpeg_bytes


def test_dfb_rejects_27_byte_header_only_jpeg_without_entropy_data(tmp_path: Path):
    header_only_jpeg = (
        b"\xff\xd8"  # SOI
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"  # SOF0
        b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"  # SOS
        b"\xff\xd9"  # EOI with no entropy-coded data
    )
    assert len(header_only_jpeg) == 27
    path = tmp_path / "header-only.dfb"
    path.write_bytes(b"prefix" + header_only_jpeg + b"suffix")

    result = dfb_preview(_resource(path, "dfb", "reference_map"))

    assert result.mode == "message"
    assert result.image_bytes == b""


def test_zip_lists_only_first_500_sorted_central_names_without_extracting(tmp_path: Path):
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for number in reversed(range(600)):
            archive.writestr(f"item-{number:03}.txt", "payload")

    with patch.object(
        zipfile.ZipFile,
        "extract",
        side_effect=AssertionError("no extract"),
    ), patch.object(
        zipfile.ZipFile,
        "extractall",
        side_effect=AssertionError("no extractall"),
    ):
        result = zip_preview(_resource(path, "zip", "archive"))

    assert result.mode == "table"
    assert len(result.table_rows) == 500
    assert result.table_rows[0] == ("item-000.txt",)
    assert result.table_rows[-1] == ("item-499.txt",)
    assert result.truncated is True
    assert "截断" in result.warning


@pytest.mark.parametrize(
    ("name", "fmt", "resource_type", "preview"),
    [
        ("bad-eocd.zip", "zip", "archive", zip_preview),
        ("bad-eocd.pptx", "pptx", "document", pptx_preview),
    ],
)
def test_zip_and_pptx_reject_truncated_eocd(
    tmp_path: Path,
    name: str,
    fmt: str,
    resource_type: str,
    preview,
):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("docProps/thumbnail.png", PNG_1X1)
    path.write_bytes(path.read_bytes()[:-1])

    result = preview(_resource(path, fmt, resource_type))

    assert result.mode == "message"
    assert "目录" in result.warning or fmt.upper() in result.warning


@pytest.mark.parametrize(
    ("field_offset", "format_code", "value"),
    [
        (8, "<H", 10_001),
        (12, "<L", 4 * 1024 * 1024 + 1),
        (10, "<H", 0xFFFF),
        (16, "<L", 0xFFFFFFFF),
    ],
)
def test_zip_rejects_eocd_budgets_and_zip64_before_zipfile(
    tmp_path: Path,
    field_offset: int,
    format_code: str,
    value: int,
):
    path = tmp_path / f"central-{field_offset}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("one.txt", "payload")
    _patch_eocd(path, field_offset, format_code, value)

    with patch.object(zipfile, "ZipFile", wraps=zipfile.ZipFile) as constructor:
        result = zip_preview(_resource(path, "zip", "archive"))

    assert result.mode == "message"
    assert constructor.call_count == 0


def test_zip_rejects_total_utf8_central_name_budget(tmp_path: Path):
    path = tmp_path / "name-budget.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for number in range(1800):
            archive.writestr(f"{number:04}-" + "n" * 595, b"")

    result = zip_preview(_resource(path, "zip", "archive"))

    assert result.mode == "message"
    assert "名称" in result.warning


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
