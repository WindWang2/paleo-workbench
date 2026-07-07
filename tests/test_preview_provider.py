from pathlib import Path
from unittest.mock import patch

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import (
    MAX_TABLE_COLUMNS,
    MAX_TABLE_ROWS,
    MAX_TEXT_PREVIEW_BYTES,
    PreviewProvider,
)


def test_preview_provider_empty_state():
    result = PreviewProvider().preview(None)

    assert result.mode == "empty"
    assert result.title == "请选择数据项"


def test_preview_provider_reads_bounded_text(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_text("a" * (MAX_TEXT_PREVIEW_BYTES + 100), encoding="utf-8")
    resource = ResourceItem(name="large.txt", path=str(path), type="document", format="txt")

    with patch.object(Path, "read_bytes", side_effect=AssertionError("full text file read")):
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

    class BoundedTextFile:
        def __init__(self, text: str):
            self._lines = text.splitlines(True)
            self._index = 0
            self.read_calls = 0

        def readline(self, size: int = -1) -> str:
            self.read_calls += 1
            if self.read_calls > 2:
                raise AssertionError("table preview read beyond bounded preview chunk")
            if self._index >= len(self._lines):
                return ""
            line = self._lines[self._index]
            self._index += 1
            return line

        def __iter__(self):
            return self

        def __next__(self) -> str:
            line = self.readline()
            if line == "":
                raise StopIteration
            return line

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    real_open = Path.open

    def bounded_open(self: Path, mode: str = "r", *args, **kwargs):
        if mode == "rb":
            return real_open(self, mode, *args, **kwargs)
        if mode == "r":
            with real_open(self, "r", encoding="utf-8", newline="") as handle:
                return BoundedTextFile(handle.read())
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


def test_preview_provider_reuses_cached_result_for_unchanged_file(tmp_path: Path):
    path = tmp_path / "sample.txt"
    path.write_text("first", encoding="utf-8")
    resource = ResourceItem(name="sample.txt", path=str(path), type="document", format="txt")
    provider = PreviewProvider()

    first = provider.preview(resource)
    second = provider.preview(resource)

    assert first is second


def test_preview_provider_export_artifact_message(tmp_path: Path):
    artifact = ExportArtifact(linked_id="map_1", format="png", output_path=str(tmp_path / "map.png"))

    result = PreviewProvider().preview(artifact)

    assert result.mode == "message"
    assert result.title == "map.png"
    assert "成果文件" in result.message
