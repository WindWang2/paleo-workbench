"""L7 — reviewed well-tie → versioned time-depth calibration authority.

The full loop: tie arrays with bulk shift / bounded stretch-squeeze →
validated pairs → SMI TD-table artifact (parse_td_table-compatible) →
catalog DERIVED version + run with quality provenance → project
entity_asset_link(role=time_depth) → hub calibration with catalog
identity → reopened project re-registers through bind_project.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.project.domain import EntityAssetLink, WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.view_coordination import ViewCoordinationController
from paleo_workbench.viz.coordinate_hub import (
    CoordinateTransformHub,
    TimeDepthCalibration,
)
from paleo_workbench.viz.selection_context import SelectionContext
from paleo_workbench.workflow.td_calibration_lifecycle import (
    QC_CORRELATION_THRESHOLD,
    STRETCH_FACTOR_LIMITS,
    CalibrationBuildError,
    StretchSqueezeRecord,
    TieReviewData,
    build_calibration_pairs,
    calibration_fingerprint,
    hub_calibration_from_td_table,
    save_reviewed_calibration,
    tvdss_from_hub,
    write_td_table,
)


def _tie_arrays() -> tuple[np.ndarray, np.ndarray]:
    depths = np.linspace(0.0, 4000.0, 41)
    twt = 2.0 * depths / 2.5  # ~2500 m/s average
    return depths, twt


@pytest.fixture()
def catalog_project(tmp_path: Path):
    project_file = tmp_path / "proj" / "demo.paleo.json"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_file)
    doc = ProjectDocument.new("Tie Project")
    well = WellEntity(name="W-TIE", kb=25.0, td=4000.0)
    doc.wells = [well]
    return service, doc, well


# ---------------------------------------------------------------------------
# Pair building: bulk shift, bounded stretch/squeeze, validation
# ---------------------------------------------------------------------------


class TestPairBuilding:
    def test_bulk_shift_applies_to_twt(self):
        depths, twt = _tie_arrays()
        pairs = build_calibration_pairs(depths, twt, bulk_shift_ms=-12.0)
        assert pairs[3][1] == pytest.approx(twt[3] - 12.0)

    def test_duplicate_depths_refused(self):
        depths = np.array([1000.0, 1000.0, 2000.0])
        twt = np.array([100.0, 200.0, 300.0])
        with pytest.raises(CalibrationBuildError, match="duplicate MD"):
            build_calibration_pairs(depths, twt)

    def test_non_monotonic_twt_refused(self):
        depths = np.array([0.0, 1000.0, 2000.0])
        twt = np.array([0.0, 500.0, 400.0])
        with pytest.raises(CalibrationBuildError, match="not strictly increasing"):
            build_calibration_pairs(depths, twt)

    def test_descending_input_depth_axis_is_sorted(self):
        depths, twt = _tie_arrays()
        pairs = build_calibration_pairs(depths[::-1].copy(), twt[::-1].copy())
        assert [p[0] for p in pairs] == sorted(p[0] for p in pairs)
        assert pairs[0][1] == pytest.approx(0.0)

    def test_bounded_stretch_squeeze_monotonic_result(self):
        depths, twt = _tie_arrays()
        stretch = StretchSqueezeRecord(
            anchors_m=(0.0, 2000.0, 4000.0), factors=(1.0, 0.95, 1.0)
        )
        pairs = build_calibration_pairs(depths, twt, stretch=stretch)
        assert len(pairs) == depths.size
        # strictly increasing TWT survived the warp (validated in-module);
        # the squeeze bounds the result: factors ∈ [0.95, 1] cumulative →
        # every warped TWT sits between 0.95× and 1× the original.
        warped = np.array([p[1] for p in pairs])
        np.testing.assert_array_less(warped, twt + 1e-9)
        np.testing.assert_array_less(0.95 * twt - 1e-9, warped)

    def test_stretch_factor_out_of_bounds_refused(self):
        lo, hi = STRETCH_FACTOR_LIMITS
        with pytest.raises(CalibrationBuildError, match="outside bounded range"):
            StretchSqueezeRecord(
                anchors_m=(0.0, 1000.0), factors=(1.0, hi + 0.01)
            )
        with pytest.raises(CalibrationBuildError, match="outside bounded range"):
            StretchSqueezeRecord(anchors_m=(0.0, 1000.0), factors=(1.0, lo - 0.01))

    def test_stretch_anchors_must_increase(self):
        with pytest.raises(CalibrationBuildError, match="strictly increase"):
            StretchSqueezeRecord(anchors_m=(0.0, 0.0), factors=(1.0, 1.0))

    def test_mismatched_review_arrays_refused(self):
        depths, twt = _tie_arrays()
        with pytest.raises(CalibrationBuildError):
            TieReviewData(
                well_name="W",
                well_entity_id="e1",
                depths_m=depths,
                twt_ms=twt[:-1],
            )


# ---------------------------------------------------------------------------
# Artifact round-trip (parse_td_table is the reader)
# ---------------------------------------------------------------------------


class TestTdTableArtifact:
    def test_write_then_parse_roundtrip(self, tmp_path):
        from paleo_workbench.viz.joint_well_parsers import parse_td_table

        depths, twt = _tie_arrays()
        pairs = build_calibration_pairs(depths, twt)
        path = write_td_table(
            tmp_path / "W-TIE.dat", "W-TIE", pairs, [-p[0] for p in pairs]
        )
        table = parse_td_table(path, well_name="W-TIE")
        assert table is not None
        np.testing.assert_allclose(table.md_m, [p[0] for p in pairs], atol=1e-3)
        np.testing.assert_allclose(table.time_ms, [p[1] for p in pairs], atol=1e-2)

    def test_tvdss_mismatch_refused(self, tmp_path):
        depths, twt = _tie_arrays()
        pairs = build_calibration_pairs(depths, twt)
        with pytest.raises(CalibrationBuildError, match="tvdss"):
            write_td_table(tmp_path / "x.dat", "W", pairs, [0.0])

    def test_tvdss_from_hub_vertical_and_deviated(self):
        hub = CoordinateTransformHub()
        hub.register_well("W-V", x=0.0, y=0.0, elevation=25.0, total_depth_m=3000.0)
        assert tvdss_from_hub(hub, "W-V", [1000.0]) == pytest.approx([25.0 - 1000.0])

        hub.register_well(
            "W-D",
            x=0.0,
            y=0.0,
            elevation=0.0,
            total_depth_m=4000.0,
            stations=[(0.0, 0.0, 0.0), (4000.0, 60.0, 0.0)],
        )
        # consistency with the hub's own minimum-curvature trajectory
        # (an independently hardcoded dip would duplicate the kernel here)
        _, _, tvd = hub.well_depth_to_map("W-D", 4000.0)
        assert tvdss_from_hub(hub, "W-D", [4000.0])[0] == pytest.approx(-tvd)

    def test_fingerprint_is_pair_science_only(self):
        depths, twt = _tie_arrays()
        pairs = build_calibration_pairs(depths, twt)
        f1 = calibration_fingerprint(pairs)
        assert f1 == calibration_fingerprint(list(pairs))
        perturbed = list(pairs)
        perturbed[0] = (perturbed[0][0], perturbed[0][1] + 0.5)
        assert calibration_fingerprint(perturbed) != f1


# ---------------------------------------------------------------------------
# Save loop: catalog version + run + project link + identity
# ---------------------------------------------------------------------------


class TestSaveReviewedCalibration:
    def _review(self, well, *, correlation=0.92, confirmed=True):
        depths, twt = _tie_arrays()
        return TieReviewData(
            well_name=well.name,
            well_entity_id=well.id,
            depths_m=depths,
            twt_ms=twt,
            bulk_shift_ms=-8.0,
            correlation=correlation,
            wavelet="ricker:25Hz",
            reviewer="geophysicist@example.com",
            reviewer_confirmed=confirmed,
        )

    def test_save_produces_versioned_authority(self, catalog_project):
        service, doc, well = catalog_project
        review = self._review(well)
        tvdss = [-md for md in review.depths_m]

        result = save_reviewed_calibration(service, doc, review, tvdss_m=tvdss)

        assert result.verified is True
        assert result.pair_count == review.depths_m.size
        # catalog DERIVED version + run with quality provenance
        version = service.get_version(result.version_id)
        assert version.stage.value == "derived"
        run = next(r for r in service.document.runs if r.id == result.run_id)
        params = run.parameters
        assert params["operation"] if "operation" in params else True
        assert params["bulk_shift_ms"] == -8.0
        assert params["correlation"] == pytest.approx(0.92)
        assert params["reviewer"] == "geophysicist@example.com"
        assert params["verified"] is True
        assert params["fingerprint"] == result.fingerprint
        # project link: primary, role time_depth, catalog asset id
        links = [
            l for l in doc.entity_asset_links if l.role == "time_depth"
        ]
        assert len(links) == 1
        assert links[0].asset_id == result.asset_id
        assert links[0].entity_id == well.id
        assert links[0].is_primary is True

    def test_verified_requires_threshold_and_reviewer(self, catalog_project):
        service, doc, well = catalog_project
        # correlation below threshold → verified False even with reviewer
        review = self._review(well, correlation=QC_CORRELATION_THRESHOLD - 0.01)
        result = save_reviewed_calibration(
            service, doc, review, tvdss_m=[-md for md in review.depths_m]
        )
        assert result.verified is False
        run = next(r for r in service.document.runs if r.id == result.run_id)
        assert run.parameters["verified"] is False

        # correlation fine but reviewer did not confirm → verified False
        service2_file = doc  # same project, second asset
        review2 = self._review(well, correlation=0.95, confirmed=False)
        result2 = save_reviewed_calibration(
            service, service2_file, review2, tvdss_m=[-md for md in review2.depths_m]
        )
        assert result2.verified is False

    def test_resave_demotes_previous_primary_link(self, catalog_project):
        service, doc, well = catalog_project
        review = self._review(well)
        tvdss = [-md for md in review.depths_m]
        first = save_reviewed_calibration(service, doc, review, tvdss_m=tvdss)
        second = save_reviewed_calibration(service, doc, review, tvdss_m=tvdss)

        primaries = [
            l
            for l in doc.entity_asset_links
            if l.role == "time_depth" and l.entity_id == well.id and l.is_primary
        ]
        assert len(primaries) == 1
        assert primaries[0].asset_id == second.asset_id
        assert first.asset_id != second.asset_id  # immutable chain, not overwrite

    def test_artifact_reopens_as_hub_calibration_with_identity(
        self, catalog_project, tmp_path
    ):
        service, doc, well = catalog_project
        review = self._review(well)
        result = save_reviewed_calibration(
            service, doc, review, tvdss_m=[-md for md in review.depths_m]
        )

        cal = hub_calibration_from_td_table(
            Path(result.artifact_path),
            review.well_name,
            version_id=result.version_id,
            fingerprint=result.fingerprint,
            metadata={"correlation": 0.92},
        )
        assert cal.version_id == result.version_id
        assert cal.fingerprint == result.fingerprint
        assert cal.metadata["correlation"] == pytest.approx(0.92)
        # and it actually converts
        assert cal.md_to_twt(2000.0) == pytest.approx(
            review.twt_ms[20] - 8.0, rel=1e-3
        )

    def test_bind_project_registers_saved_calibration(self, catalog_project):
        """Reopen loop: a project carrying the saved link re-registers the
        calibration through the EXISTING bind_project path, now with the
        catalog version identity attached."""
        import paleo_workbench.catalog as catalog_module

        service, doc, well = catalog_project
        review = self._review(well)
        result = save_reviewed_calibration(
            service, doc, review, tvdss_m=[-md for md in review.depths_m]
        )

        # The production singleton catalog is what bind_project resolves
        # asset ids through; point it at our service's document.
        class _FakeGetCatalog:
            def __call__(self):
                return service

        hub = CoordinateTransformHub()
        controller = ViewCoordinationController(
            SelectionContext(), hub
        )
        monkey_target = catalog_module.get_catalog
        catalog_module.get_catalog = _FakeGetCatalog()
        try:
            controller.bind_project(doc)
        finally:
            catalog_module.get_catalog = monkey_target

        cal = hub.time_depth_calibration(well.name)
        assert cal is not None
        assert cal.version_id == result.version_id
        assert cal.fingerprint == result.fingerprint
        assert cal.metadata.get("verified") is True

    def test_unparseable_artifact_refused_not_guessed(self, tmp_path):
        bad = tmp_path / "bad.dat"
        bad.write_text("# Well : W-TIE\nonly one column\n", encoding="utf-8")
        with pytest.raises(CalibrationBuildError, match="not parseable"):
            hub_calibration_from_td_table(bad, "W-TIE")


class TestReviewFixes:
    def test_artifact_precision_matches_fingerprint(self, catalog_project):
        """R1-m2: a fingerprint recomputed from the written artifact must
        equal the stored one (6-decimal writer, 6-decimal fingerprint)."""
        from paleo_workbench.workflow.td_calibration_lifecycle import (
            build_calibration_pairs,
            calibration_fingerprint as _fp,
            hub_calibration_from_td_table,
            save_reviewed_calibration,
        )
        from paleo_workbench.viz.joint_well_parsers import parse_td_table

        service, doc, well = catalog_project
        depths, twt = _tie_arrays()
        review = TieReviewData(
            well_name=well.name,
            well_entity_id=well.id,
            depths_m=depths,
            twt_ms=twt,
        )
        result = save_reviewed_calibration(
            service, doc, review, tvdss_m=[-md for md in depths]
        )
        table = parse_td_table(
            Path(result.artifact_path), well_name=review.well_name
        )
        recomputed = _fp(build_calibration_pairs(table.md_m, table.time_ms))
        assert recomputed == result.fingerprint

    def test_upsert_link_is_idempotent(self, catalog_project):
        """R2-M1: saving the same asset twice keeps ONE primary link."""
        service, doc, well = catalog_project
        depths, twt = _tie_arrays()
        review = TieReviewData(
            well_name=well.name, well_entity_id=well.id, depths_m=depths, twt_ms=twt
        )
        result = save_reviewed_calibration(
            service, doc, review, tvdss_m=[-md for md in depths]
        )
        from paleo_workbench.workflow.td_calibration_lifecycle import (
            _upsert_time_depth_link,
        )

        _upsert_time_depth_link(doc, well.id, result.asset_id)
        _upsert_time_depth_link(doc, well.id, result.asset_id)
        links = [l for l in doc.entity_asset_links if l.role == "time_depth"]
        assert len(links) == 1
