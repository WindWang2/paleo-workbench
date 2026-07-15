from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    PreviewProvider,
    PreviewResult,
)


def test_preview_provider_empty_state():
    result = PreviewProvider().preview(None)

    assert result.mode == "empty"
    assert result.title == "请选择数据项"


def test_preview_provider_reads_bounded_text(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_text("a" * (MAX_TEXT_PREVIEW_BYTES + 100), encoding="utf-8")
    resource = ResourceItem(name="large.txt", path=str(path), type="document", format="txt")

    class BoundedBinaryFile:
        def __init__(self, file_obj):
            self._file_obj = file_obj
            self.read_sizes: list[int] = []

        def read(self, size: int = -1):
            self.read_sizes.append(size)
            assert size == MAX_TEXT_PREVIEW_BYTES
            return self._file_obj.read(size)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._file_obj.__exit__(exc_type, exc, tb)

    real_open = Path.open

    def bounded_open(self: Path, mode: str = "r", *args, **kwargs):
        if mode == "rb":
            return BoundedBinaryFile(real_open(self, mode, *args, **kwargs))
        return real_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", bounded_open):
        result = PreviewProvider().preview(resource)

    assert result.mode == "text"
    assert len(result.text) <= MAX_TEXT_PREVIEW_BYTES + 32
    assert result.truncated is True
    assert "仅显示" in result.warning


def test_preview_provider_reads_bounded_csv_table(tmp_path: Path):
    path = tmp_path / "table.csv"
    header = ",".join(f"c{i}" for i in range(MAX_TABLE_COLUMNS + 3))
    rows = [
        ",".join(str(column) for column in range(MAX_TABLE_COLUMNS + 3))
        for _ in range(MAX_TABLE_ROWS + 5)
    ]
    path.write_text("\n".join([header, *rows]), encoding="utf-8")
    resource = ResourceItem(name="table.csv", path=str(path), type="tabular", format="csv")

    class BoundedBinaryFile:
        def __init__(self, file_obj):
            self._file_obj = file_obj
            self.read_sizes: list[int] = []

        def read(self, size: int = -1):
            self.read_sizes.append(size)
            assert size == MAX_TEXT_PREVIEW_BYTES
            return self._file_obj.read(size)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._file_obj.__exit__(exc_type, exc, tb)

    real_open = Path.open

    def bounded_open(self: Path, mode: str = "r", *args, **kwargs):
        if mode == "rb":
            return BoundedBinaryFile(real_open(self, mode, *args, **kwargs))
        return real_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", bounded_open):
        result = PreviewProvider().preview(resource)

    assert result.mode == "table"
    assert result.table_headers is not None
    assert len(result.table_rows) == MAX_TABLE_ROWS
    assert all(len(row) == MAX_TABLE_COLUMNS for row in result.table_rows)
    assert result.truncated is True
    assert isinstance(result.table_headers, tuple)
    assert isinstance(result.table_rows, tuple)
    assert all(isinstance(row, tuple) for row in result.table_rows)


def test_preview_provider_preserves_quoted_csv_newlines(tmp_path: Path):
    path = tmp_path / "quoted-newlines.csv"
    path.write_text('name,note\nalpha,"line one\nline two"\nbeta,plain', encoding="utf-8")
    resource = ResourceItem(name="quoted-newlines.csv", path=str(path), type="tabular", format="csv")

    result = PreviewProvider().preview(resource)

    assert result.mode == "table"
    assert result.table_headers == ("name", "note")
    assert result.table_rows[0] == ("alpha", "line one\nline two")
    assert result.table_rows[1] == ("beta", "plain")


def test_preview_provider_missing_file_message(tmp_path: Path):
    resource = ResourceItem(
        name="missing.txt",
        path=str(tmp_path / "missing.txt"),
        type="document",
        format="txt",
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "message"
    assert result.status == "missing"
    assert "文件不存在" in result.message


@pytest.mark.parametrize(
    ("name", "fmt", "resource_type", "expected_mode"),
    [
        ("deck.pptx", "pptx", "document", "message"),
        ("phase.dfb", "dfb", "reference_map", "message"),
        ("bundle.zip", "zip", "archive", "message"),
        ("well.wlp", "wlp", "well_reference", "message"),
    ],
)
def test_preview_provider_dispatches_bounded_fallbacks(
    tmp_path: Path,
    name: str,
    fmt: str,
    resource_type: str,
    expected_mode: str,
):
    path = tmp_path / name
    path.write_bytes(b"vendor bytes")
    resource = ResourceItem(name=name, path=str(path), type=resource_type, format=fmt)

    result = PreviewProvider().preview(resource)

    assert result.mode == expected_mode
    if fmt == "wlp":
        assert "暂不支持 WLP" in result.message


def test_preview_provider_keeps_ordinary_xml_as_text(tmp_path: Path):
    path = tmp_path / "ordinary.xml"
    path.write_text("<root><value>plain</value></root>", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="spreadsheet", format="xml")

    result = PreviewProvider().preview(resource)

    assert result.mode == "text"
    assert "plain" in result.text


def test_preview_provider_is_pure_no_internal_cache(tmp_path: Path):
    # Provider.preview is pure; LRU lives on PreviewRequestController (UI thread).
    path = tmp_path / "sample.txt"
    path.write_text("first", encoding="utf-8")
    resource = ResourceItem(name="sample.txt", path=str(path), type="document", format="txt")
    provider = PreviewProvider()

    first = provider.preview(resource)
    second = provider.preview(resource)

    assert first == second
    assert first.mode == "text"
    assert first.text == "first"
    provider.clear()  # no-op cleanup still callable


def test_preview_provider_export_artifact_message(tmp_path: Path):
    artifact = ExportArtifact(linked_id="map_1", format="png", output_path=str(tmp_path / "map.png"))

    result = PreviewProvider().preview(artifact)

    assert result.mode == "message"
    assert result.title == "map.png"
    assert "成果文件" in result.message


def test_preview_provider_image_revision_changes_when_resource_checksum_changes(tmp_path: Path):
    path = tmp_path / "map.png"
    path.write_bytes(b"first-image")
    resource = ResourceItem(
        name="map.png",
        path=str(path),
        type="image_reference",
        format="png",
        checksum="checksum-1",
    )
    provider = PreviewProvider()

    provider._safe_stat = lambda _path: (12, 100)  # type: ignore[method-assign]
    first = provider.preview(resource)
    resource.checksum = "checksum-2"
    path.write_bytes(b"second-image-with-new-bytes")
    second = provider.preview(resource)

    assert first.mode == "image"
    assert second.mode == "image"
    assert first.revision != second.revision


def test_preview_provider_reads_excel_first_sheet_as_table(tmp_path: Path):
    path = tmp_path / "wells.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            {
                "well": ["A1", "A2"],
                "depth": [100.0, 120.5],
            }
        ).to_excel(writer, sheet_name="Wells", index=False)
        pd.DataFrame({"key": ["datum"], "value": ["CGCS2000"]}).to_excel(
            writer,
            sheet_name="Meta",
            index=False,
        )
    resource = ResourceItem(
        name="wells.xlsx",
        path=str(path),
        type="spreadsheet",
        format="xlsx",
    )

    result = PreviewProvider().preview(resource)

    assert result.mode == "table"
    assert result.sheets == ("Wells", "Meta")
    assert result.table_headers == ("well", "depth")
    assert result.table_rows[0] == ("A1", "100.0")


def test_preview_provider_reads_las_curve_summary(tmp_path: Path):
    path = tmp_path / "well.las"
    path.write_text(
        """~Version Information
 VERS. 2.0 : CWLS log ASCII Standard - VERSION 2.0
 WRAP. NO : One line per depth step
~Well Information
 STRT.M 100.0 : START DEPTH
 STOP.M 101.0 : STOP DEPTH
 STEP.M 0.5 : STEP
 NULL. -999.25 : NULL VALUE
 WELL. A1 : WELL
~Curve Information
 DEPT.M : Depth
 GR.API : Gamma Ray
 RHOB.G/C3 : Bulk Density
~ASCII
100.0 80.0 2.45
100.5 82.0 2.46
101.0 84.0 2.47
""",
        encoding="utf-8",
    )
    resource = ResourceItem(name="well.las", path=str(path), type="well_log", format="las")

    result = PreviewProvider().preview(resource)

    assert result.mode == "well_log"
    assert ("井名", "A1") in result.summary_rows
    assert ("曲线数", "3") in result.summary_rows
    assert result.table_headers == ("曲线", "单位", "描述")
    assert ("GR", "API", "Gamma Ray") in result.table_rows


def test_preview_provider_degrades_incomplete_las_without_crashing(tmp_path: Path):
    path = tmp_path / "incomplete.las"
    path.write_text("~Version\n", encoding="utf-8")
    resource = ResourceItem(name="incomplete.las", path=str(path), type="well_log", format="las")

    result = PreviewProvider().preview(resource)

    assert result.mode == "well_log"
    assert ("采样点", "0") in result.summary_rows
    assert result.table_rows == ()


def test_preview_provider_reads_segy_metadata_with_optional_library(
    monkeypatch,
    tmp_path: Path,
):
    path = tmp_path / "cube.sgy"
    path.write_bytes(b"not-a-real-segy")

    class FakeSegyFile:
        tracecount = 12
        samples = [0, 1, 2, 3]
        bin = {"interval": 2000}
        header = {0: {"inline": 1180, "crossline": 220}}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSegyio:
        BinField = type("BinField", (), {"Interval": "interval"})
        TraceField = type(
            "TraceField",
            (),
            {"INLINE_3D": "inline", "CROSSLINE_3D": "crossline"},
        )

        @staticmethod
        def open(path_arg, mode="r", ignore_geometry=True):
            assert path_arg == str(path)
            assert mode == "r"
            assert ignore_geometry is True
            return FakeSegyFile()

    monkeypatch.setattr("paleo_workbench.ui.pages.preview_provider.segyio", FakeSegyio)
    resource = ResourceItem(name="cube.sgy", path=str(path), type="seismic", format="sgy")

    result = PreviewProvider().preview(resource)

    assert result.mode == "seismic"
    assert ("道数", "12") in result.summary_rows
    assert ("采样点", "4") in result.summary_rows
    assert ("采样间隔", "2000 us") in result.summary_rows
    assert result.table_rows == (("Inline", "1180"), ("Crossline", "220"))


def test_preview_result_has_rich_html_field():
    r = PreviewResult(mode="rich_text", title="t", rich_html="<p>x</p>")
    assert r.rich_html == "<p>x</p>"


def test_preview_result_defaults_new_fields_empty():
    r = PreviewResult(mode="text", title="t", text="hi")
    assert r.rich_html == ""
    assert r.json_payload is None
    assert r.json_truncated is False
    assert r.geo_metadata == ()
    assert r.media_path == ""


def _resource(tmp_path, name, fmt, content=""):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return ResourceItem(name=name, path=str(p), type="document", format=fmt, status="parsed")


@pytest.mark.parametrize(("name", "fmt"), [("notes.md", "md"), ("notes.markdown", "markdown")])
def test_markdown_preview_returns_rich_text(tmp_path, name, fmt):
    res = _resource(tmp_path, name, fmt, "# Title\n\nSome **bold** text.")
    result = PreviewProvider().preview(res)
    assert result.mode == "rich_text"
    assert "<h1>Title</h1>" in result.rich_html


@pytest.mark.parametrize(("name", "fmt"), [("r.html", "html"), ("r.htm", "htm")])
def test_html_preview_returns_rich_text(tmp_path, name, fmt):
    res = _resource(tmp_path, name, fmt, "<h1>Hi</h1>")
    result = PreviewProvider().preview(res)
    assert result.mode == "rich_text"
    assert result.path == res.path
    assert "<h1>Hi</h1>" in result.rich_html


@pytest.mark.parametrize("fmt", ["html", "htm"])
def test_html_preview_reads_file_content(tmp_path, fmt):
    path = tmp_path / f"doc.{fmt}"
    path.write_text("<h1>Hello</h1><p>World</p>", encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format=fmt)

    result = PreviewProvider().preview(resource)

    assert result.mode == "rich_text"
    assert "<h1>Hello</h1>" in result.rich_html


def test_markdown_rich_preview_is_bounded_and_escaped(tmp_path):
    path = tmp_path / "large.md"
    path.write_text("# Title\n\n- one\n\n<script>x</script>\n" * 50_000, encoding="utf-8")
    resource = ResourceItem(name=path.name, path=str(path), type="document", format="md")

    result = PreviewProvider().preview(resource)

    assert result.mode == "rich_text"
    assert "<h1>Title</h1>" in result.rich_html
    assert "&lt;script&gt;x&lt;/script&gt;" in result.rich_html
    assert result.truncated is True
    assert result.warning == "仅显示前 256 KiB"


def test_markdown_missing_file_falls_back(tmp_path):
    res = ResourceItem(name="x.md", path=str(tmp_path / "missing.md"), type="document", format="md", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "message"
    assert "不存在" in result.message


def test_json_preview_parses_object(tmp_path):
    res = _resource(tmp_path, "c.json", "json", '{"a": 1, "b": [1,2,3]}')
    result = PreviewProvider().preview(res)
    assert result.mode == "json_tree"
    assert result.json_payload == {"a": 1, "b": [1, 2, 3]}
    assert result.json_truncated is False


def test_geojson_preview_recognized(tmp_path):
    payload = '{"type":"FeatureCollection","features":[]}'
    res = _resource(tmp_path, "f.geojson", "geojson", payload)
    result = PreviewProvider().preview(res)
    assert result.mode == "json_tree"
    assert isinstance(result.json_payload, dict)


def test_json_corrupt_falls_back(tmp_path):
    res = _resource(tmp_path, "bad.json", "json", "{ not json")
    result = PreviewProvider().preview(res)
    assert result.mode == "message"
    assert "JSON" in result.message or "解析" in result.message


def test_geotiff_preview_metadata(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np

    path = tmp_path / "band.tif"
    arr = np.zeros((32, 32), dtype="uint8")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=32,
        width=32,
        count=1,
        dtype="uint8",
        crs="EPSG:32649",
        transform=rasterio.transform.from_bounds(0, 0, 1, 1, 1, 1),
    ) as dst:
        dst.write(arr, 1)
    res = ResourceItem(
        name="band.tif",
        path=str(path),
        type="image_reference",
        format="tif",
        status="parsed",
    )
    result = PreviewProvider().preview(res)
    assert result.mode == "geotiff"
    assert any("EPSG" in k or "CRS" in k for k, _ in result.geo_metadata)
    assert len(result.image_bytes) > 0  # thumbnail PNG


def test_geotiff_fallback_to_image(tmp_path):
    # A non-raster tiff (plain bytes) → rasterio fails → image fallback.
    path = tmp_path / "fake.tif"
    path.write_bytes(b"\x00" * 64)
    res = ResourceItem(
        name="fake.tif",
        path=str(path),
        type="image_reference",
        format="tif",
        status="parsed",
    )
    result = PreviewProvider().preview(res)
    assert result.mode == "image"
    assert "失败" in result.warning


def test_audio_preview_returns_media_path(tmp_path):
    path = tmp_path / "clip.wav"
    path.write_bytes(b"\x00" * 64)  # placeholder bytes; no real decode in provider
    res = ResourceItem(name="clip.wav", path=str(path), type="unknown", format="wav", status="parsed")
    result = PreviewProvider().preview(res)
    assert result.mode == "media"
    assert result.media_path == str(path)
