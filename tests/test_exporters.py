import json
from pathlib import Path
import pytest
from paleo_workbench.resources.exporters import (
    ExportError, las_to_csv, table_to_json, image_to_png, text_to_txt,
    get_available_formats,
)
from paleo_workbench.project.models import ResourceItem, ExportArtifact


def test_las_to_csv(tmp_path):
    las_content = "~V\nSTRT.M 0:\nSTOP.M 100:\nSTEP.M 1:\n~C\nDEPT.M  :\nGR.US/API  :\n~A\n0 50\n1 55\n"
    src = tmp_path / "well.las"
    src.write_text(las_content)
    out = tmp_path / "well.csv"
    las_to_csv(src, out)
    assert out.exists()
    text = out.read_text()
    assert "," in text  # CSV format


def test_table_to_json_csv(tmp_path):
    src = tmp_path / "data.csv"
    src.write_text("name,value\nalpha,1\nbeta,2\n")
    out = tmp_path / "data.json"
    table_to_json(src, out)
    data = json.loads(out.read_text())
    assert len(data) == 2
    assert data[0]["name"] == "alpha"


def test_image_to_png(tmp_path):
    from PIL import Image
    import numpy as np
    src = tmp_path / "img.bmp"
    Image.fromarray(np.zeros((4, 4, 3), dtype="uint8")).save(src)
    out = tmp_path / "img.png"
    image_to_png(src, out)
    assert out.exists()
    # Verify it's a valid PNG
    Image.open(out).verify()


def test_text_to_txt(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text("# Title\n\nSome text.")
    out = tmp_path / "notes.txt"
    text_to_txt(src, out)
    assert out.read_text() == "# Title\n\nSome text."


def test_get_available_formats_las():
    res = ResourceItem(name="w.las", path="/w.las", type="well_log", format="las", status="parsed")
    fmts = get_available_formats(res)
    assert any(label == "CSV" for label, _ in fmts)


def test_get_available_formats_unknown():
    res = ResourceItem(name="x.xyz", path="/x.xyz", type="unknown", format="xyz", status="parsed")
    assert get_available_formats(res) == []


def test_get_available_formats_artifact():
    art = ExportArtifact(linked_id="m1", format="PDF", output_path="/m.pdf")
    assert get_available_formats(art) == []


def test_export_error_on_missing_file(tmp_path):
    with pytest.raises(ExportError):
        text_to_txt(tmp_path / "nonexistent.md", tmp_path / "out.txt")
