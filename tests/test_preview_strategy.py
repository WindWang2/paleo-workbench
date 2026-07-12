from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_strategy import (
    preview_for_artifact,
    preview_for_resource,
)


def test_preview_strategy_identifies_image(tmp_path: Path):
    image = tmp_path / "map.png"
    image.write_bytes(b"not-real-png")
    resource = ResourceItem(
        name="map.png",
        path=image.as_posix(),
        type="image_reference",
        format="png",
    )

    state = preview_for_resource(resource)

    assert state.mode == "image"
    assert state.image_path == image.as_posix()


def test_preview_strategy_keeps_excel_summary_only(tmp_path: Path):
    workbook = tmp_path / "table.xlsx"
    workbook.write_bytes(b"not-a-real-workbook")
    resource = ResourceItem(
        name="table.xlsx",
        path=workbook.as_posix(),
        type="spreadsheet",
        format="xlsx",
        parsed_summary={"size_bytes": 2048},
    )

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "table.xlsx" in state.title
    assert any("2048" in line for line in state.lines)
    assert "安全摘要预览" in state.warning


def test_preview_strategy_reads_bounded_text_lines(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("\n".join(f"line {index}" for index in range(25)), encoding="utf-8")
    resource = ResourceItem(
        name="notes.txt",
        path=text.as_posix(),
        type="document",
        format="txt",
    )

    state = preview_for_resource(resource)

    assert state.mode == "text"
    assert "line 0" in state.lines
    assert "line 19" in state.lines
    assert "line 20" not in state.lines
    assert "仅显示前 20 行" in state.warning


def test_preview_strategy_csv_uses_table_mode(tmp_path: Path):
    csv = tmp_path / "table.csv"
    csv.write_text("well,depth\nA1,100\n", encoding="utf-8")
    resource = ResourceItem(
        name="table.csv",
        path=csv.as_posix(),
        type="spreadsheet",
        format="csv",
    )

    state = preview_for_resource(resource)

    assert state.mode == "table"
    assert any("well,depth" in line for line in state.lines)
    assert any("A1,100" in line for line in state.lines)


def test_preview_strategy_missing_file_warns(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    resource = ResourceItem(
        name="missing.txt",
        path=missing.as_posix(),
        type="document",
        format="txt",
    )

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "文件不存在" in state.warning


def test_preview_strategy_professional_formats_stay_summary_only(tmp_path: Path):
    pdf = tmp_path / "report.xlsx"
    pdf.write_bytes(b"workbook")
    resource = ResourceItem(
        name="report.xlsx",
        path=pdf.as_posix(),
        type="spreadsheet",
        format="xlsx",
    )

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "安全摘要预览" in state.warning


def test_preview_strategy_pdf_uses_pdf_mode(tmp_path: Path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    resource = ResourceItem(
        name="report.pdf",
        path=pdf.as_posix(),
        type="document",
        format="pdf",
    )

    state = preview_for_resource(resource)

    assert state.mode == "pdf"
    assert state.document_path == pdf.as_posix()
    assert state.warning == ""


def test_preview_strategy_metadata_for_unknown():
    resource = ResourceItem(
        name="raw.bin",
        path="/tmp/raw.bin",
        type="unknown",
        format="bin",
    )

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "暂不支持预览" in state.warning


def test_preview_strategy_export_artifact():
    artifact = ExportArtifact(
        linked_id="map_1",
        format="GeoTIFF",
        output_path="/tmp/map.tif",
    )

    state = preview_for_artifact(artifact)

    assert state.mode == "artifact"
    assert "GeoTIFF" in state.title


def test_preview_strategy_audio_uses_media_mode(tmp_path: Path):
    clip = tmp_path / "note.wav"
    clip.write_bytes(b"\x00" * 64)
    resource = ResourceItem(
        name="note.wav",
        path=clip.as_posix(),
        type="unknown",
        format="wav",
    )

    state = preview_for_resource(resource)

    assert state.mode == "media"
    assert any("note.wav" in line for line in state.lines)
