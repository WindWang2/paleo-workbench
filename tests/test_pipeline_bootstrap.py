from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.pipeline.bootstrap import (
    BootstrapResult,
    bootstrap_sample_project,
)


def _make_sample_tree(root: Path) -> None:
    (root / "井曲线").mkdir(parents=True)
    (root / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (root / "井曲线" / "A2.Las").write_text("~Version\n", encoding="utf-8")
    (root / "层位").mkdir()
    (root / "层位" / "C6.dat").write_text("h", encoding="utf-8")
    (root / "层位" / "D71.dat").write_text("h", encoding="utf-8")
    (root / "地震体").mkdir()
    (root / "地震体" / "200P_seismic.sgy").write_bytes(b"x" * 100)


def test_bootstrap_indexes_and_stratigraphy(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    _make_sample_tree(data)

    result = bootstrap_sample_project(
        data,
        project_name="Demo",
        region="惠西南",
        skip_checksum_over_bytes=50,
    )
    assert isinstance(result, BootstrapResult)
    doc = result.document
    assert doc.meta.name == "Demo"
    assert doc.meta.region == "惠西南"
    assert len(doc.resources) >= 5
    types = {r.type for r in doc.resources}
    assert "well_log" in types
    assert "seismic" in types
    assert "horizon" in types
    assert doc.stratigraphy.target_horizon == "C6"
    assert doc.stratigraphy.sequence_boundaries == ["C6", "D71"]
    assert doc.stratigraphy.applicable_wells == ["A1", "A2"]
    assert any("200P" in n for n in doc.stratigraphy.applicable_seismic_ranges)
    assert len(doc.compilation_runs) == 1
    assert doc.compilation_runs[0].status == "draft"
    assert doc.compilation_runs[0].target_horizon == "C6"
    assert doc.factor_map_tasks == []
    assert doc.prediction_tasks == []
    assert doc.paleomap_documents == []
    big = next(r for r in doc.resources if r.name.endswith(".sgy"))
    assert big.checksum is None
    assert result.stats["files"] == len(doc.resources)
    assert result.stats["by_type"]["well_log"] == 2


def test_bootstrap_default_keeps_full_scan_checksums(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "well.las"
    source.write_text("~Version\n", encoding="utf-8")

    result = bootstrap_sample_project(data_root)

    assert result.document.resources[0].checksum is not None


def test_bootstrap_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        bootstrap_sample_project(tmp_path / "nope")


def test_bootstrap_empty_tree_raises(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no files"):
        bootstrap_sample_project(empty)
