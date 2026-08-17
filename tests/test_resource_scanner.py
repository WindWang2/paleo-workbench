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


def test_scan_resources_skips_checksum_over_threshold(tmp_path: Path):
    big = tmp_path / "vol.sgy"
    big.write_bytes(b"x" * 100)
    small = tmp_path / "A1.Las"
    small.write_text("~Version\n", encoding="utf-8")

    resources = scan_resources(tmp_path, skip_checksum_over_bytes=50)
    by_name = {r.name: r for r in resources}

    assert by_name["vol.sgy"].checksum is None
    assert by_name["vol.sgy"].parsed_summary.get("checksum_skipped") is True
    assert by_name["vol.sgy"].parsed_summary["size_bytes"] == 100
    assert by_name["A1.Las"].checksum is not None
    assert by_name["A1.Las"].parsed_summary.get("checksum_skipped") is not True


def test_scan_resources_default_still_checksums(tmp_path: Path):
    f = tmp_path / "A1.Las"
    content = "~Version\n"
    f.write_text(content, encoding="utf-8")
    resources = scan_resources(tmp_path)
    assert resources[0].checksum == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_scan_concurrent_preserves_order(tmp_path: Path):
    (tmp_path / "c.las").write_bytes(b"x")
    (tmp_path / "a.las").write_bytes(b"x")
    (tmp_path / "b.las").write_bytes(b"x")
    results = scan_resources(tmp_path)
    names = [r.name for r in results]
    assert names == ["a.las", "b.las", "c.las"]


def test_scan_concurrent_matches_serial(tmp_path: Path):
    for i in range(20):
        (tmp_path / f"f{i:02d}.las").write_bytes(f"content{i}".encode())
    serial = scan_resources(tmp_path, max_workers=1)
    concurrent = scan_resources(tmp_path, max_workers=4)
    assert len(serial) == len(concurrent) == 20
    for s, c in zip(serial, concurrent):
        assert s.name == c.name
        assert s.path == c.path
        assert s.type == c.type
        assert s.format == c.format
        assert s.checksum == c.checksum


def test_scan_concurrent_empty_dir(tmp_path: Path):
    assert scan_resources(tmp_path) == []


def test_scan_concurrent_checksum_correct(tmp_path: Path):
    import hashlib
    (tmp_path / "data.dat").write_bytes(b"hello world")
    results = scan_resources(tmp_path)
    assert len(results) == 1
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert results[0].checksum == expected


def test_scan_concurrent_max_workers_param(tmp_path: Path):
    (tmp_path / "a.las").write_bytes(b"x")
    # Both should work without error; max_workers=1 forces serial
    r1 = scan_resources(tmp_path, max_workers=1)
    r8 = scan_resources(tmp_path, max_workers=8)
    assert len(r1) == len(r8) == 1


def test_scan_concurrent_vanished_file_skipped(tmp_path: Path, monkeypatch):
    (tmp_path / "a.las").write_bytes(b"x")
    (tmp_path / "b.las").write_bytes(b"x")
    # Make _process_file return None for one file (simulating vanished file)
    from paleo_workbench.resources import scanner
    original = scanner._process_file
    call_count = [0]

    def patched(path, project_path, skip, classify=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # simulate vanished
        if classify is None:
            return original(path, project_path, skip)
        return original(path, project_path, skip, classify)

    monkeypatch.setattr(scanner, "_process_file", patched)
    results = scan_resources(tmp_path)
    assert len(results) == 1  # one skipped, one kept
