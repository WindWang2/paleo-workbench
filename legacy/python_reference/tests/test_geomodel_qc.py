"""QC framework tests (G13): severity ladder, per-object audits, export gate."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.geomodel.builders import (
    build_fault_curtain_from_trace,
    build_horizon_from_grid,
    build_simplified_vertical_well,
    build_volume_shell,
    build_well_trajectory,
)
from paleo_workbench.viz.geomodel.domain import (
    FaultSurface,
    MeasurementRecord,
    ModelAssembly,
    StratigraphicVolume,
)
from paleo_workbench.viz.geomodel.qc import (
    QCBlockerError,
    QCReport,
    assert_exportable,
    qc_assembly,
    qc_fault_surface,
    qc_horizon_surface,
    qc_object,
    qc_stratigraphic_volume,
    qc_well_trajectory,
)


from paleo_workbench.viz.geomodel.domain import Provenance

CRS = "EPSG:32650"
PROV = Provenance(source_kind="catalog", source_version_ids=("hv-top", "hv-base"))


def flat_volume(object_id="volume:v", crossed=False, name="V"):
    """5x5 lattice / 0..40 boundary -> 16 kept cells, georeferenced."""
    tg = np.full((5, 5), 100.0)
    bg = np.full((5, 5), 150.0)
    if crossed:
        bg[1:3, 1:3] = 90.0  # 4 crossed nodes -> 9 invalid cells, 7 kept
    top = build_horizon_from_grid(
        "Top", tg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS, provenance=PROV
    )
    base = build_horizon_from_grid(
        "Base", bg, origin=(0, 0), spacing=(10.0, 10.0), crs=CRS, provenance=PROV
    )
    return build_volume_shell(
        top,
        base,
        [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)],
        object_id=object_id,
        name=name,
    )


class TestWellQC:
    def test_good_well_passes(self):
        st = np.array([[0, 0, 0, 0], [100, 5, 5, 100], [200, 12, 9, 200]], dtype=float)
        well = build_well_trajectory("W", st, crs="EPSG:32650")
        report = qc_well_trajectory(well)
        assert report.worst() == "ok"
        assert report.severities()["blocker"] == 0

    def test_non_monotonic_md_is_blocker(self):
        st = np.array([[0, 0, 0, 0], [100, 0, 0, 100], [90, 0, 0, 90]], dtype=float)
        with pytest.raises(Exception):
            build_well_trajectory("W", st)  # builder refuses (first line of defense)
        # QC still flags the pattern if a constructor bypass happened
        # (frozen dataclass: mutate via object.__setattr__ to simulate a
        # deserializer that skipped validation).
        well = build_well_trajectory("W", st[:2], crs=CRS)
        object.__setattr__(well, "stations", st)
        report = qc_well_trajectory(well)
        assert report.worst() == "blocker"
        assert any(i.code == "NON_MONOTONIC_MD" for i in report.issues)

    def test_missing_crs_blocks_export(self):
        well = build_simplified_vertical_well("W", (0, 0, 0), 100.0)  # no crs
        report = qc_well_trajectory(well)
        assert report.worst() == "blocker"
        assert any(i.code == "MISSING_CRS" for i in report.issues)
        assert any(i.code == "SIMPLIFIED_VERTICAL" for i in report.issues)
        with pytest.raises(QCBlockerError):
            assert_exportable([well])

    def test_empty_stations_blocker(self):
        well = build_well_trajectory.__wrapped__ if hasattr(build_well_trajectory, "__wrapped__") else None
        from paleo_workbench.viz.geomodel.domain import WellTrajectory

        empty = WellTrajectory(object_id="well:empty", name="empty")
        report = qc_well_trajectory(empty)
        assert report.worst() == "blocker"

    def test_mixed_units_warns(self):
        st = np.array([[0, 0, 0, 0], [100, 0, 0, 100]], dtype=float)
        well = build_well_trajectory("W", st, crs=CRS)
        well = __import__("dataclasses").replace(well, z_unit="ft")
        report = qc_well_trajectory(well)
        assert any(i.code == "MIXED_UNITS" for i in report.issues)


class TestHorizonQC:
    def test_nan_holes_info_not_error(self):
        g = np.full((5, 5), 100.0)
        g[2, 2] = np.nan
        hor = build_horizon_from_grid("H", g, crs=CRS, provenance=PROV)
        report = qc_horizon_surface(hor)
        codes = {i.code: i.severity for i in report.issues}
        assert codes.get("NAN_HOLES") == "info"
        assert report.worst() == "info"  # informational only

    def test_largely_missing_warns(self):
        g = np.full((5, 5), 100.0)
        g[1:, 1:] = np.nan
        hor = build_horizon_from_grid("H", g, crs=CRS, provenance=PROV)
        report = qc_horizon_surface(hor)
        assert any(i.code == "LARGELY_MISSING" for i in report.issues)

    def test_unknown_crs_blocks(self):
        g = np.full((5, 5), 100.0)
        hor = build_horizon_from_grid("H", g)
        report = qc_horizon_surface(hor)
        assert any(i.code == "MISSING_CRS" and i.severity == "blocker" for i in report.issues)

    def test_empty_grid_blocker(self):
        from paleo_workbench.viz.geomodel.domain import HorizonSurface

        hor = HorizonSurface(object_id="horizon:empty", name="empty", crs=CRS)
        report = qc_horizon_surface(hor)
        assert report.worst() == "blocker"


class TestVolumeQC:
    def test_healthy_volume_is_watertight_ok(self):
        vol, _ = flat_volume()
        report = qc_stratigraphic_volume(vol)
        codes = {i.code for i in report.issues}
        assert "WATERTIGHT" in codes
        assert report.worst() == "info"  # watertight is an informational note

    def test_crossed_columns_flagged(self):
        vol, qc = flat_volume(crossed=True)
        report = qc_stratigraphic_volume(vol)
        assert any(i.code == "CROSSED_COLUMNS" for i in report.issues)

    def test_open_shell_is_blocker(self):
        vol, _ = flat_volume()
        # cut one face off the shell -> boundary edge -> not closed
        faces = np.asarray(vol.faces)[:-1]
        broken = __import__("dataclasses").replace(vol, faces=faces)
        report = qc_stratigraphic_volume(broken)
        assert any(
            i.code == "SHEET_NOT_CLOSED" and i.severity == "blocker"
            for i in report.issues
        )


class TestFaultQC:
    def test_curtain_labelled(self):
        fault = build_fault_curtain_from_trace(
            "F", [(0, 0), (10, 10)], 100.0, 200.0, crs="EPSG:32650"
        )
        report = qc_fault_surface(fault)
        assert any(i.code == "CURTAIN_REPRESENTATION" for i in report.issues)


class TestExportGate:
    def test_blocker_refuses_export(self):
        from paleo_workbench.viz.geomodel.domain import WellTrajectory

        empty = WellTrajectory(object_id="well:empty", name="empty")
        with pytest.raises(QCBlockerError) as exc:
            assert_exportable([empty])
        assert "well:empty" in str(exc.value)

    def test_error_severity_does_not_block(self):
        # warning-level findings report loudly but still export (ADR-06 gate
        # is blocker-only); e.g. a sparse-but-georeferenced trajectory.
        st = np.array([[0, 0, 0, 0], [100, 0, 0, 100]], dtype=float)
        well = build_well_trajectory("W", st, crs="EPSG:32650")
        report = assert_exportable([well])
        assert report.worst() == "warning"  # SPARSE_TRAJECTORY

    def test_report_meta_roundtrip(self):
        vol, _ = flat_volume()
        report = qc_object(vol)
        meta = report.to_meta()
        again = QCReport.from_meta(meta)
        assert again.worst() == report.worst()
        assert len(again.issues) == len(report.issues)


class TestAssemblyQC:
    def test_stale_source_detection(self):
        vol, _ = flat_volume()
        asm = ModelAssembly()
        asm.add(vol)
        report = qc_assembly(asm, known_source_ids=["other-version"])
        assert any(i.code == "STALE_SOURCE" for i in report.issues)
        report2 = qc_assembly(asm, known_source_ids=["hv-top", "hv-base"])
        assert not any(i.code == "STALE_SOURCE" for i in report2.issues)

    def test_assembly_worst_aggregates(self):
        from paleo_workbench.viz.geomodel.domain import WellTrajectory

        vol, _ = flat_volume()
        asm = ModelAssembly()
        asm.add(vol)
        asm.add(WellTrajectory(object_id="well:empty", name="empty"))
        report = qc_assembly(asm)
        assert report.worst() == "blocker"
        assert report.worst("volume:v") == "info"
