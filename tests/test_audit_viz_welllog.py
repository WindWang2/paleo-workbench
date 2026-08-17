"""Deep-audit regressions (2026-08-14): prediction input contract, geomodel
auto-tie, DTW depth mapping, formation volume precision, datum diagnostics,
well-tie seeding, section datum sync, and shared-memory handle leaks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from paleo_workbench.prediction.input_contract import (
    InputContractError,
    resolve_model_inputs,
)


# --- F7: required_curves enforcement ---------------------------------------------


class _Asset:
    def __init__(self, asset_id: str, rtype: str, version_id: str, legacy_id: str):
        self.id = asset_id
        self.type = rtype
        self.legacy_resource_id = legacy_id
        self.current_version_id = version_id


class _Version:
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.metadata: dict = {}


class _Service:
    def __init__(self, assets, versions):
        self.document = SimpleNamespace(assets=assets, runs=[])
        self._versions = versions

    def get_version(self, version_id):
        return self._versions[version_id]


def _project_with_well(tmp_path: Path, *, parsed_curves=None):
    from paleo_workbench.project.models import ProjectDocument, ResourceItem

    project = ProjectDocument.new("audit")
    las = tmp_path / "does-not-exist.las"
    resource = ResourceItem(
        id="res:las",
        name="W1.las",
        path=str(las),
        type="well_log",
        format="las",
    )
    if parsed_curves is not None:
        resource.parsed_summary = {"curves": list(parsed_curves)}
    project.resources.append(resource)
    return project


def _service_for(project):
    assets, versions = [], {}
    for resource in project.resources:
        asset = _Asset(f"asset:{resource.id}", "well_log", f"ver:{resource.id}", resource.id)
        assets.append(asset)
        versions[asset.current_version_id] = _Version(asset.id)
    return _Service(assets, versions)


def test_required_curves_satisfied_by_recorded_curve_metadata(tmp_path):
    project = _project_with_well(tmp_path, parsed_curves=["DEPT", "GR", "RHOB"])
    service = _service_for(project)
    model_version = SimpleNamespace(
        input_schema={"required_asset_types": ["well_log"], "required_curves": ["GR"]}
    )

    ids = resolve_model_inputs(project, service, model_version, strict=True)

    assert ids, "well-log version must resolve"


def test_required_curves_missing_raises_contract_error(tmp_path):
    project = _project_with_well(tmp_path, parsed_curves=["DEPT", "GR"])
    service = _service_for(project)
    model_version = SimpleNamespace(
        input_schema={"required_asset_types": ["well_log"], "required_curves": ["DT", "GR"]}
    )

    with pytest.raises(InputContractError, match="缺少必需曲线") as excinfo:
        resolve_model_inputs(project, service, model_version, strict=True)
    assert "DT" in str(excinfo.value)


def test_required_curves_without_well_inputs_raises_contract_error(tmp_path):
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("audit-empty")
    service = _service_for(project)
    # Schema declares only curves → legacy gather path must still enforce them.
    model_version = SimpleNamespace(input_schema={"required_curves": ["GR"]})

    with pytest.raises(InputContractError, match="测井输入"):
        resolve_model_inputs(project, service, model_version, strict=True)


def test_required_curves_enforced_on_legacy_gather_path(tmp_path):
    project = _project_with_well(tmp_path, parsed_curves=["GR"])
    service = _service_for(project)
    model_version = SimpleNamespace(input_schema={"required_curves": ["GR"]})

    ids = resolve_model_inputs(project, service, model_version, strict=True)

    assert ids


def test_required_curves_skip_las_reread_when_summary_covers(tmp_path, monkeypatch):
    """#636: parsed_summary already covering required curves must not touch disk."""
    las = tmp_path / "w1.las"
    las.write_text("~Version\n VERS. 2.0 :\n~Well\n~Curve\n DEPT.m\n GR.gAPI\n~Ascii\n0 1\n")
    project = _project_with_well(tmp_path, parsed_curves=["DEPT", "GR", "RHOB"])
    project.resources[0].path = str(las)
    service = _service_for(project)
    calls: list[str] = []

    def fake_load_las_preview(path, fast=False):
        calls.append(str(path))
        raise AssertionError("LAS header must not be re-read when summary covers required curves")

    monkeypatch.setattr("geoviz.load_las_preview", fake_load_las_preview)
    model_version = SimpleNamespace(
        input_schema={"required_asset_types": ["well_log"], "required_curves": ["GR"]}
    )

    ids = resolve_model_inputs(project, service, model_version, strict=True)

    assert ids
    assert calls == []


def test_required_curves_not_enforced_when_not_strict(tmp_path):
    project = _project_with_well(tmp_path, parsed_curves=["GR"])
    service = _service_for(project)
    model_version = SimpleNamespace(
        input_schema={"required_asset_types": ["well_log"], "required_curves": ["DT"]}
    )

    ids = resolve_model_inputs(project, service, model_version, strict=False)

    assert ids


# --- F8: run_auto_tie skips boreholes with empty layer stacks ---------------------


def _layers():
    return [
        {"top": 0.0, "bottom": 30.0, "lithology": "砂岩"},
        {"top": 30.0, "bottom": 75.0, "lithology": "泥岩"},
    ]


def test_run_auto_tie_skips_empty_layer_boreholes():
    from paleo_workbench.viz.geomodel import analysis

    bh_raw_data = [
        {"name": "empty", "x": 0.0, "y": 0.0, "total_depth": 0.0, "layers": []},
        {"name": "real", "x": 10.0, "y": 0.0, "total_depth": 75.0, "layers": _layers()},
    ]
    result = analysis.run_auto_tie(bh_raw_data, freq=30.0)
    assert result is not None
    assert isinstance(result["shift_samples"], int)
    assert 0.0 <= result["cc"] <= 1.0


def test_run_auto_tie_all_boreholes_empty_returns_none():
    from paleo_workbench.viz.geomodel import analysis

    bh_raw_data = [
        {"name": "empty", "x": 0.0, "y": 0.0, "total_depth": 0.0, "layers": []},
    ]
    # Previously crashed with ValueError (max() over empty layer stack).
    assert analysis.run_auto_tie(bh_raw_data, freq=30.0) is None


# --- F9: DTW depth transfer uses the curve's own depth axis ----------------------


def test_recommend_top_depth_maps_through_real_depth_axis():
    from paleo_workbench.viz.formation_top_correlator import FormationTopCorrelator

    depths = np.arange(1000.0, 1100.0, 0.5)  # 200 samples, start 1000 m, step 0.5 m
    ref = np.sin(np.linspace(0.0, 4.0 * np.pi, depths.size)).astype(np.float32)
    target = np.roll(ref, 5)

    rec = FormationTopCorrelator().recommend_top_depth(
        ref_curve=ref,
        target_curve=target,
        ref_top_depth=1010.0,
        ref_depths=depths,
        target_depths=depths,
    )

    # Recommendation must stay on the 1000–1100 m measured-depth domain instead
    # of the legacy magic 0.0/0.5 grid (which mapped 1010 m to ~index 20*0.5).
    assert 1000.0 <= rec.suggested_depth <= 1100.0
    assert rec.confidence > 0.0


def test_recommend_top_depth_explicit_scalars_still_override():
    from paleo_workbench.viz.formation_top_correlator import FormationTopCorrelator

    ref = np.sin(np.linspace(0.0, 4.0 * np.pi, 100)).astype(np.float32)
    target = np.roll(ref, 5)

    rec = FormationTopCorrelator().recommend_top_depth(
        ref_curve=ref,
        target_curve=target,
        ref_top_depth=20.0,
        start_depth=0.0,
        depth_step=1.0,
    )

    assert rec.suggested_depth >= 20.0


# --- F10: closed-volume integration survives UTM-scale coordinates ---------------


def test_formation_volume_survives_utm_offsets():
    from paleo_workbench.viz.formation_volume import FormationVolumeIntegrator

    rows = cols = 20
    xs = np.tile(np.arange(cols) * 10.0, rows)
    ys = np.repeat(np.arange(rows) * 10.0, cols)

    def grid(x0: float, y0: float, z: float) -> np.ndarray:
        return np.column_stack([xs + x0, ys + y0, np.full(xs.size, z)]).astype(np.float32)

    integrator = FormationVolumeIntegrator()
    local = integrator.compute_closed_volume(grid(0.0, 0.0, 1000.0), grid(0.0, 0.0, 990.0), (rows, cols))
    utm = integrator.compute_closed_volume(
        grid(500000.0, 4000000.0, 1000.0), grid(500000.0, 4000000.0, 990.0), (rows, cols)
    )

    expected = 190.0 * 190.0 * 10.0  # 20 vertices span 190 m per axis, 10 m thick
    assert local == pytest.approx(expected, rel=1e-6)
    # float32 accumulation at UTM offsets previously lost ~2000% of the volume.
    assert utm == pytest.approx(expected, rel=1e-4)


# --- F11: un-correctable wells are reported, correct wells unchanged -------------


def test_compute_shifts_reports_uncorrectable_wells():
    from paleo_workbench.viz.well_section_datum import WellSectionDatum

    wells = [
        {"name": "A", "tops": [{"name": "H1", "depth": 100.0}]},
        {"name": "B", "tops": [{"name": "H2", "depth": 150.0}]},
    ]
    diagnostics: list[str] = []
    shifts = WellSectionDatum().compute_shifts(
        wells, mode="horizon", target_horizon="H1", diagnostics=diagnostics
    )

    assert shifts == {"A": -100.0, "B": 0.0}
    assert len(diagnostics) == 1
    assert "B" in diagnostics[0] and "H1" in diagnostics[0]

    # Values identical when no diagnostics channel is passed.
    silent = WellSectionDatum().compute_shifts(wells, mode="horizon", target_horizon="H1")
    assert silent == shifts


def test_compute_shifts_reports_missing_kb_for_tvdss():
    from paleo_workbench.viz.well_section_datum import WellSectionDatum

    wells = [{"name": "A"}, {"name": "B"}]
    diagnostics: list[str] = []
    shifts = WellSectionDatum().compute_shifts(
        wells, mode="tvdss", kb_elevations={"A": 30.0}, diagnostics=diagnostics
    )

    assert shifts["A"] == -30.0
    assert shifts["B"] == 0.0
    assert len(diagnostics) == 1
    assert "B" in diagnostics[0]


# --- F15: well-tie synthetic seed is stable across hash-salt changes -------------


def test_well_tie_seed_ignores_process_hash_salt(qtbot, monkeypatch):
    from geoviz import CurveData, WellLogData

    from paleo_workbench.viz.hosts.well_tie_host import WellTieHost
    from paleo_workbench.viz.models import VizPayload

    depths = [1000.0 + i * 10.0 for i in range(20)]
    well = WellLogData(
        well_name="TIE-1",
        top_depth=1000.0,
        bottom_depth=1190.0,
        curves=[
            CurveData(
                name="GR",
                unit="gapi",
                depth=depths,
                values=[40.0 + i for i in range(20)],
                display_range=(0.0, 150.0),
            )
        ],
    )
    host = WellTieHost()
    qtbot.addWidget(host.widget)
    payload = VizPayload(kind="well_log", label="TIE-1", well_log=well)

    import builtins

    first: list[float] = []
    monkeypatch.setattr(builtins, "hash", lambda obj=-1: 111, raising=False)
    assert host.apply(payload)
    first.append(0.0)
    trace_a = np.array(host.widget._seismic, copy=True)

    # A different process (hash salt) must not change the synthetic trace.
    monkeypatch.setattr(builtins, "hash", lambda obj=-1: 999, raising=False)
    assert host.apply(payload)
    trace_b = np.array(host.widget._seismic, copy=True)

    assert first
    assert np.array_equal(trace_a, trace_b)


# --- F16: apply() re-applies the datum mode the combo actually shows -------------


def test_well_section_apply_reapplies_datum_mode_to_canvas(qtbot):
    from geoviz import CurveData, WellLogData

    from paleo_workbench.viz.hosts.well_section_host import WellSectionHost
    from paleo_workbench.viz.models import VizPayload

    depths = [1000.0 + i * 10.0 for i in range(10)]
    well = WellLogData(
        well_name="W1",
        top_depth=1000.0,
        bottom_depth=1090.0,
        curves=[
            CurveData(
                name="GR",
                unit="gapi",
                depth=depths,
                values=[50.0 + i for i in range(10)],
                display_range=(0.0, 150.0),
            )
        ],
    )
    host = WellSectionHost()
    qtbot.addWidget(host.widget)

    # Previous well set left the canvas flattening onto a now-removed horizon.
    host.canvas.set_datum_mode("datum_shift", datum_name="H1")

    payload = VizPayload(kind="well_log", label="W1", well_log=well)
    assert host.apply(payload)

    assert host.datum_combo.currentData() == "absolute"
    assert host.canvas.transformer.mode == "absolute"


# --- F17: SharedMemoryArrayHandle releases every mapping -------------------------


def _maps_for(name: str) -> int:
    maps = Path("/proc/self/maps")
    if not maps.is_file():
        pytest.skip("needs /proc/self/maps")
    return sum(1 for line in maps.read_text().splitlines() if name in line)


def test_shared_memory_handle_releases_mappings_and_array():
    from paleo_workbench.viz.ipc.shared_memory_handle import SharedMemoryArrayHandle

    handle, meta = SharedMemoryArrayHandle.create(shape=(64, 64), dtype="float32")
    assert handle.array is not None
    handle.array[0, 0] = 7.5
    # create() must release its create-time attach: exactly one mapping stays.
    assert _maps_for(f"/{meta.shm_name}") == 1

    handle.close()

    # close() clears the dangling ndarray and really releases the mapping.
    assert handle.array is None
    assert _maps_for(f"/{meta.shm_name}") == 0
