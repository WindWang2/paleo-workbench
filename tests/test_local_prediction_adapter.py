"""ISS-PRED-01: LocalAssetPredictionAdapter driven by real LAS when present."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.prediction.adapters import (
    LocalAssetPredictionAdapter,
    MockPredictionAdapter,
)
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.seismic_prediction import run_seismic_facies_prediction
from paleo_workbench.workflow.well_log_prediction import (
    regions_to_depth_intervals,
    run_well_log_facies_prediction,
)


def _write_gr_las(path: Path) -> None:
    # Depth 1000-1100, GR rises then falls → mixed sand/mud zones
    lines = [
        "~VERSION INFORMATION",
        " VERS. 2.0:",
        " WRAP. NO:",
        "~WELL INFORMATION",
        " STRT.M 1000.0:",
        " STOP.M 1100.0:",
        " STEP.M 10.0:",
        " NULL. -999.25:",
        " WELL. A1:",
        "~CURVE INFORMATION",
        " DEPT.M :",
        " GR.GAPI :",
        "~ASCII",
    ]
    # Low GR (sand) then high GR (mud)
    for i, d in enumerate(range(1000, 1101, 10)):
        gr = 30.0 + (i * 8.0 if i < 6 else 20.0)
        lines.append(f"{d:.1f} {gr:.1f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_local_adapter_falls_back_to_mock_without_assets():
    project = ProjectDocument.new("Empty")
    task = LocalAssetPredictionAdapter().run(project, [], seed=1)
    assert task.adapter_kind == "mock"
    assert task.result_summary.get("is_mock") is True


def test_local_adapter_uses_las_gr_when_readable(tmp_path: Path):
    las = tmp_path / "A1.las"
    _write_gr_las(las)
    project = ProjectDocument.new("LAS")
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(
            name="A1.las",
            path=str(las),
            type="well_log",
            format="las",
        )
    )
    task = LocalAssetPredictionAdapter().run(project, [], seed=2)
    assert task.adapter_kind == "local"
    assert task.generator_version.startswith("local-asset")
    summary = task.result_summary
    assert summary.get("is_mock") is False
    assert summary.get("source_kind") in {"las_curve", "las_and_seismic"}
    regions = summary.get("predicted_regions") or []
    assert len(regions) >= 2
    # Depth-annotated zones from LAS
    assert any("top" in r and "bottom" in r for r in regions)
    well_meta = summary.get("well_meta") or {}
    assert well_meta.get("curve")
    assert well_meta.get("source_well") == "A1.las"


def test_run_well_log_workflow_marks_local_adapter(tmp_path: Path):
    las = tmp_path / "B1.las"
    _write_gr_las(las)
    project = ProjectDocument.new("W")
    project.stratigraphy.target_horizon = "ZJ2"
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(name="B1.las", path=str(las), type="well_log", format="las")
    )
    task = run_well_log_facies_prediction(project, seed=1)
    assert task.model_metadata.get("adapter") == "local"
    assert task.input_refs.get("well_log_resource_ids") == [project.resources[0].id]
    assert task.result_summary.get("is_mock") is False


def test_run_seismic_records_seismic_meta(tmp_path: Path):
    segy = tmp_path / "vol.sgy"
    segy.write_bytes(b"\x00" * 64)  # unreadable volume but path exists
    project = ProjectDocument.new("S")
    project.stratigraphy.target_horizon = "H1"
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(name="vol.sgy", path=str(segy), type="seismic", format="segy")
    )
    task = run_seismic_facies_prediction(project, seed=0)
    assert task.input_refs.get("seismic_resource_ids") == [project.resources[0].id]
    # local adapter with seismic path
    assert task.adapter_kind in {"local", "mock"}
    if task.adapter_kind == "local":
        meta = task.result_summary.get("seismic_meta") or {}
        assert meta.get("source_seismic") == "vol.sgy"
        assert meta.get("path_readable") is True


def test_seismic_only_random_fallback_is_honestly_mocked(tmp_path: Path):
    """P2 honesty: the seismic-only random template must NEVER display as 真实.

    No readable LAS → the seeded random template is used; it must carry
    is_mock=True + final_scientific_prediction=False (+ model_type=heuristic
    + probabilities_uncalibrated) so the UI shows Mock, not 真实.
    """
    segy = tmp_path / "vol.sgy"
    segy.write_bytes(b"\x00" * 64)  # exists but unreadable as a volume
    project = ProjectDocument.new("S")
    project.stratigraphy.target_horizon = "H1"
    project.meta.project_root = str(tmp_path)
    project.resources.append(
        ResourceItem(name="vol.sgy", path=str(segy), type="seismic", format="segy")
    )
    task = LocalAssetPredictionAdapter().run(project, [], seed=0)
    assert task.adapter_kind == "local"
    summary = task.result_summary
    assert summary.get("source_kind") == "seismic_path"
    # The critical honesty contract:
    assert summary.get("is_mock") is True
    assert summary.get("final_scientific_prediction") is False
    assert summary.get("model_type") == "heuristic"
    assert summary.get("probabilities_uncalibrated") is True
    assert summary.get("demo") is True  # template output is demo-grade


def test_regions_to_depth_intervals_prefers_explicit_tops():
    regions = [
        {"facies": "砂", "probability": 0.9, "top": 1000, "bottom": 1030},
        {"facies": "泥", "probability": 0.7, "top": 1030, "bottom": 1100},
    ]
    intervals = regions_to_depth_intervals(regions, top=1000, bottom=1100)
    assert intervals[0]["top"] == 1000.0
    assert intervals[0]["bottom"] == 1030.0
    assert intervals[1]["facies"] == "泥"


def test_mock_adapter_still_available():
    project = ProjectDocument.new("M")
    task = MockPredictionAdapter().run(project, [], seed=0)
    assert task.adapter_kind == "mock"
    assert len(task.result_summary["predicted_regions"]) == 4
