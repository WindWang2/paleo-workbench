"""P1-A — well curve interpretation → derived version loop.

Explicit, user-attributable operations on a cataloged curve dataset produce
DERIVED versions carrying the full provenance set (input version ids,
operation, parameters, generator, time, output version ids). The RAW
version is never modified — neither its payload bytes nor its catalog
record.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
lasio = pytest.importorskip("lasio")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.workflow.curve_interpretation import (
    CURVE_OPERATIONS,
    apply_curve_operation,
    depth_shift,
    despike,
    baseline_shift,
)


def _write_las(path: Path) -> None:
    depths = np.arange(1000.0, 1020.0, 0.5)
    gr = 60.0 + 10.0 * np.sin(depths * 0.7)
    gr[5] = 999.25  # a spike sentinel the despike op must remove
    lines = [
        "~VERSION INFORMATION",
        "VERS. 2.0",
        "WRAP. NO",
        "~WELL",
        "STRT.M 1000.0 : Start depth",
        "STOP.M 1019.5 : Stop depth",
        "STEP.M 0.5 : Step",
        "NULL. -999.25 : Null value",
        "~CURVE INFORMATION",
    ]
    lines.append("DEPT.M : Depth")
    lines.append("GR.gAPI : Gamma Ray")
    lines.append("~PARAMETER INFORMATION")
    lines.append("~OTHER")
    lines.append("~ASCII LOG DATA")
    for d, g in zip(depths, gr):
        lines.append(f"{d:10.3f} {g:10.4f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture()
def catalog_with_las(tmp_path: Path):
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True)
    project.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project)
    source = tmp_path / "raw.las"
    _write_las(source)
    version = service.import_raw(source, name="W-1 GR", type="well_log")
    return service, version, source


class TestOperations:
    def test_depth_shift_moves_the_depth_axis(self):
        depths = np.array([1000.0, 1000.5, 1001.0])
        shifted = depth_shift(depths, delta_m=-1.5)
        np.testing.assert_allclose(shifted, [998.5, 999.0, 999.5])

    def test_despike_removes_sentinel_spikes_only(self):
        values = np.array([60.0, 61.0, 999.25, 60.5, 59.5, 60.0])
        cleaned = despike(values, threshold_sigma=3.0, window=3)
        assert cleaned[2] < 200.0  # spike replaced, not merely clipped
        np.testing.assert_allclose(cleaned[[0, 1, 3, 4, 5]], values[[0, 1, 3, 4, 5]])

    def test_baseline_shift_adds_offset(self):
        values = np.array([60.0, 61.0])
        np.testing.assert_allclose(baseline_shift(values, delta=5.0), [65.0, 66.0])

    def test_registry_names_the_operations(self):
        assert set(CURVE_OPERATIONS) >= {"depth_shift", "despike", "baseline_shift"}


class TestDerivedLoop:
    def test_operation_creates_derived_version_with_provenance(self, catalog_with_las, tmp_path):
        service, raw_version, source = catalog_with_las
        raw_bytes_before = source.read_bytes()
        raw_run_count = len(service.document.runs)

        result = apply_curve_operation(
            service,
            raw_version.id,
            operation="despike",
            curve="GR",
            parameters={"threshold_sigma": 3.0, "window": 3},
        )

        # Provenance contract: derived version + run with input/output ids.
        assert result.operation == "despike"
        assert result.input_version_ids == [raw_version.id]
        assert result.output_version_id not in (None, raw_version.id)
        run = next(
            r for r in service.document.runs if r.id == result.run_id
        )
        assert run.operation == "curve_interpretation:despike"
        assert run.input_version_ids == [raw_version.id]
        assert run.parameters["curve"] == "GR"
        assert run.parameters["threshold_sigma"] == 3.0

        # RAW untouched: same bytes, same version count, still immutable.
        assert source.read_bytes() == raw_bytes_before
        derived_path = Path(run_outputs_path(service, result.output_version_id))
        assert derived_path.is_file()
        derived = lasio.read(str(derived_path))
        gr = np.asarray(derived.curves["GR"].data, dtype=float)
        assert gr.max() < 200.0  # the spike is gone in the derived curve

    def test_unknown_operation_refused(self, catalog_with_las):
        service, raw_version, _source = catalog_with_las
        with pytest.raises(ValueError, match="unknown curve operation"):
            apply_curve_operation(
                service, raw_version.id, operation="smooth_magic", curve="GR", parameters={}
            )

    def test_unknown_curve_refused(self, catalog_with_las):
        service, raw_version, _source = catalog_with_las
        with pytest.raises(ValueError, match="curve .* not found"):
            apply_curve_operation(
                service, raw_version.id, operation="despike", curve="NOPE", parameters={}
            )


def run_outputs_path(service: DataCatalogService, version_id: str) -> str:
    return str(service.resolve_path(service.get_version(version_id)))
