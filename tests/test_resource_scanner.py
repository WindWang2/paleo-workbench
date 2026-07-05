import hashlib
from pathlib import Path

from paleo_workbench.resources.classifier import classify_path
from paleo_workbench.resources.scanner import scan_resources


def test_classify_known_and_reference_formats():
    assert classify_path(Path("A1.Las")) == ("well_log", "las", "indexed")
    assert classify_path(Path("200P_seismic.sgy")) == ("seismic", "sgy", "indexed")
    assert classify_path(Path("C6.dat")) == ("tabular", "dat", "indexed")
    assert classify_path(Path("相图.dfb")) == ("reference_map", "dfb", "indexed_reference")
    assert classify_path(Path("综合柱状图.WLP")) == (
        "well_reference",
        "wlp",
        "indexed_reference",
    )


def test_scan_resources_indexes_nested_data(tmp_path: Path):
    (tmp_path / "井曲线").mkdir()
    (tmp_path / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (tmp_path / "外委资料").mkdir()
    (tmp_path / "外委资料" / "相图.dfb").write_text("binary-like", encoding="utf-8")

    resources = scan_resources(tmp_path)

    assert [resource.name for resource in resources] == ["A1.Las", "相图.dfb"]
    assert resources[0].type == "well_log"
    assert resources[0].format == "las"
    assert resources[0].parsed_summary["size_bytes"] == len("~Version\n".encode("utf-8"))
    assert resources[1].status == "indexed_reference"
    assert resources[1].format == "dfb"
    assert resources[1].parsed_summary["size_bytes"] == len("binary-like".encode("utf-8"))


def test_scan_resources_without_project_path_preserves_canonical_source_path(tmp_path: Path):
    source_file = tmp_path / "external" / "logs" / "A1.Las"
    source_file.parent.mkdir(parents=True)
    content = "~Version\n"
    source_file.write_text(content, encoding="utf-8")

    resources = scan_resources(tmp_path / "external")

    assert len(resources) == 1
    assert resources[0].path == source_file.resolve().as_posix()
    assert resources[0].external is False
    assert resources[0].checksum == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_scan_resources_relativizes_paths_and_skips_macos_sidecars(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_dir = tmp_path / "data" / "外委资料"
    data_dir.mkdir(parents=True)
    (data_dir / "03-惠西南区域构造图.pptx").write_text("ppt", encoding="utf-8")
    (data_dir / "._03-惠西南区域构造图.pptx").write_text("sidecar", encoding="utf-8")

    resources = scan_resources(tmp_path / "data", project_path=project_path)

    assert len(resources) == 1
    assert resources[0].path == "data/外委资料/03-惠西南区域构造图.pptx"
    assert resources[0].external is False
    assert resources[0].status == "indexed_reference"
    assert resources[0].format == "pptx"
    assert resources[0].source == "scan"
    assert resources[0].parsed_summary["size_bytes"] == len("ppt".encode("utf-8"))


def test_scan_resources_computes_checksum_for_reference_image(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    image_file = tmp_path / "data" / "图件" / "剖面图.png"
    image_file.parent.mkdir(parents=True)
    payload = b"fake-png-bytes"
    image_file.write_bytes(payload)

    resources = scan_resources(tmp_path / "data", project_path=project_path)

    assert len(resources) == 1
    assert resources[0].status == "indexed_reference"
    assert resources[0].format == "png"
    assert resources[0].checksum == hashlib.sha256(payload).hexdigest()
