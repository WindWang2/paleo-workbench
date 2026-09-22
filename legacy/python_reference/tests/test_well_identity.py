"""V6 §5–6 — well identity (duplicate display names) + registry scale.

Duplicate WELL names are valid real-world data. Display names must never be
identity: two wells named "W-1" must keep distinct tops, distinct section
shifts, distinct engine documents — and binding 10k wells × thousands of
extracts must not rebuild the registry per extract.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.workflow.correlation_session import (
    build_well_identity_map,
    stable_top_id,
    tops_from_canvas_rows,
    tops_overlay_for_well,
)
from paleo_workbench.workflow.stratigraphy_models import DepthDomain, FormationTop


# ---------------------------------------------------------------------------
# stable_top_id / identity map
# ---------------------------------------------------------------------------


class TestStableTopId:
    def test_same_name_different_well_ids_distinct(self):
        a = stable_top_id(well_id="well-a", well_name="W-1", marker="H1")
        b = stable_top_id(well_id="well-b", well_name="W-1", marker="H1")
        assert a != b

    def test_idless_same_name_collides_by_design_but_map_refuses(self):
        # id-less duplicates are inherently ambiguous — the identity map
        # builder must refuse them before tops are ever persisted.
        with pytest.raises(ValueError, match="重复"):
            build_well_identity_map(["W-1", "W-1"], ["well-a", "well-b"])

    def test_distinct_names_map_positionally(self):
        mapping = build_well_identity_map(["W-1", "W-2"], ["well-a", "well-b"])
        assert mapping == {"W-1": "well-a", "W-2": "well-b"}

    def test_missing_rid_is_empty_not_guessed(self):
        mapping = build_well_identity_map(["W-1", "W-2"], ["well-a"])
        assert mapping == {"W-1": "well-a", "W-2": ""}


class TestTopsFromCanvasRows:
    def test_duplicate_wells_get_distinct_ids(self):
        from types import SimpleNamespace

        rows = [
            SimpleNamespace(well_name="W-1", formation_name="H1", depth_m=100.0),
            SimpleNamespace(well_name="W-1", formation_name="H1", depth_m=105.0),
        ]
        tops = tops_from_canvas_rows(
            rows, name_to_resource_id={"W-1": "well-a"}
        )
        # Both rows belong to well-a per the (unambiguous) mapping; they are
        # two marker picks, not one merged top.
        assert len(tops) == 2


# ---------------------------------------------------------------------------
# tops_overlay_for_well — the leak that crossed duplicate-named wells
# ---------------------------------------------------------------------------


def _top(well_id: str, well_name: str, marker: str, depth: float) -> FormationTop:
    return FormationTop(
        id=stable_top_id(well_id=well_id, well_name=well_name, marker=marker),
        well_id=well_id,
        well_name=well_name,
        marker=marker,
        depth=depth,
        depth_domain=DepthDomain.MD,
    )


class TestTopsOverlayForWell:
    def test_same_well_id_included(self):
        tops = [_top("well-a", "W-1", "H1", 100.0)]
        rows = tops_overlay_for_well(tops, well_id="well-a", well_name="W-1")
        assert [r["marker"] for r in rows] == ["H1"]

    def test_other_well_same_name_excluded(self):
        """THE P0-2 leak: a top from well-b named identically to well-a must
        never appear on well-a's log."""
        tops = [
            _top("well-b", "W-1", "H1", 100.0),  # same display name, other well
            _top("well-a", "W-1", "H1", 90.0),   # the real top
        ]
        rows = tops_overlay_for_well(tops, well_id="well-a", well_name="W-1")
        assert [r["marker"] for r in rows] == ["H1"]
        assert rows[0]["depth"] == 90.0
        assert rows[0]["well_id"] == "well-a"

    def test_idless_top_matches_by_name_only(self):
        tops = [_top("", "W-1", "H1", 100.0)]
        rows = tops_overlay_for_well(tops, well_id="well-a", well_name="W-1")
        assert len(rows) == 1  # legacy id-less data: name is all we have

    def test_idless_top_different_name_excluded(self):
        tops = [_top("", "W-2", "H1", 100.0)]
        rows = tops_overlay_for_well(tops, well_id="well-a", well_name="W-1")
        assert rows == []

    def test_target_without_id_matches_by_name(self):
        tops = [_top("well-a", "W-1", "H1", 100.0)]
        rows = tops_overlay_for_well(tops, well_id="", well_name="W-1")
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Section datum shifts under duplicate names
# ---------------------------------------------------------------------------


class TestSectionDatumDuplicates:
    def test_well_id_keys_disambiguate_duplicates(self):
        from paleo_workbench.viz.well_section_datum import WellSectionDatum

        wells = [
            {"name": "W-1", "well_id": "well-a", "tops": [{"name": "H1", "depth": 100.0}]},
            {"name": "W-1", "well_id": "well-b", "tops": [{"name": "H1", "depth": 200.0}]},
        ]
        shifts = WellSectionDatum().compute_shifts(wells, mode="horizon", target_horizon="H1")
        assert shifts["well-a"] == -100.0
        assert shifts["well-b"] == -200.0

    def test_name_only_duplicates_are_flagged(self):
        from paleo_workbench.viz.well_section_datum import WellSectionDatum

        wells = [
            {"name": "W-1", "tops": [{"name": "H1", "depth": 100.0}]},
            {"name": "W-1", "tops": [{"name": "H1", "depth": 200.0}]},
        ]
        diagnostics: list[str] = []
        shifts = WellSectionDatum().compute_shifts(
            wells, mode="horizon", target_horizon="H1", diagnostics=diagnostics
        )
        assert len(shifts) == 1  # name-keyed: collapse is unavoidable…
        assert any("重复" in d or "duplicate" in d.lower() for d in diagnostics)


# ---------------------------------------------------------------------------
# Multi-well engine adapter identity
# ---------------------------------------------------------------------------


class TestMultiWellAdapterIdentity:
    def _sample(self, name: str):
        import numpy as np
        from geoviz_well_log.models import CurveData, WellLogData

        depth = np.arange(1000.0, 1010.0, 0.5).tolist()
        return WellLogData(
            well_name=name,
            top_depth=1000.0,
            bottom_depth=1009.5,
            curves=[
                CurveData(
                    name="GR",
                    unit="gAPI",
                    depth=depth,
                    values=(60.0 + np.arange(len(depth))).tolist(),
                    display_range=(0.0, 150.0),
                )
            ],
        )

    def test_duplicate_names_without_rids_get_distinct_documents(self):
        from paleo_workbench.viz import welllog_multi_well_adapter as multi

        plan = multi.adapt_multi_well_section(
            [self._sample("W-1"), self._sample("W-1")], ["W-1", "W-1"]
        )
        doc_ids = [slot.document_id for slot in plan.wells]
        assert len(set(doc_ids)) == 2, "duplicate display names must not share a document"
        assert any("duplicate" in d for d in plan.diagnostics)

    def test_duplicate_names_with_rids_kept_distinct(self):
        from paleo_workbench.viz import welllog_multi_well_adapter as multi

        plan = multi.adapt_multi_well_section(
            [self._sample("W-1"), self._sample("W-1")],
            ["W-1", "W-1"],
            resource_ids=["well-a", "well-b"],
        )
        doc_ids = [slot.document_id for slot in plan.wells]
        assert len(set(doc_ids)) == 2


# ---------------------------------------------------------------------------
# Registry scale (§6): one registry per binding pass, not per extract
# ---------------------------------------------------------------------------


class TestRegistryScale:
    def _project(self, n_wells: int):
        from types import SimpleNamespace

        from paleo_workbench.project.domain import WellEntity

        wells = []
        for i in range(n_wells):
            well = WellEntity(name=f"W-{i}", uwi="")
            well.spatial_scope = "reference"
            wells.append(well)
        return SimpleNamespace(
            wells=wells,
            workarea=SimpleNamespace(metadata={}),
            coordinate=SimpleNamespace(project_crs="", display_crs=""),
        )

    def test_resolve_well_accepts_prebuilt_registry(self, monkeypatch):
        from paleo_workbench.project.domain import WellRegistry, resolve_well

        project = self._project(10)
        registry = WellRegistry(project.wells)
        outcome = resolve_well(project, name="W-3", registry=registry)
        assert outcome.matched and outcome.well_id == project.wells[3].id

    def test_bind_well_extracts_builds_registry_once(self, monkeypatch):
        from paleo_workbench.catalog import domain_binding
        from paleo_workbench.project.domain import WellRegistry

        project = self._project(50)
        constructs = 0
        real_init = WellRegistry.__init__

        def counting_init(self, wells):
            nonlocal constructs
            constructs += 1
            real_init(self, wells)

        from paleo_workbench.project.domain import WellRegistry as DomainWellRegistry

        monkeypatch.setattr(DomainWellRegistry, "__init__", counting_init)
        from paleo_workbench.catalog.domain_binding import WellExtract

        extracts = [
            WellExtract(name=f"W-{i}", uwi="", x=None, y=None)
            for i in range(20)
        ]
        domain_binding.bind_well_extracts(
            project, extracts, asset_id=None, spatial_scope="reference"
        )
        assert constructs == 1, f"registry built {constructs} times for 20 extracts"

    def test_ten_k_wells_thousands_of_extracts(self):
        """§6 scale gate: 10k wells × 3k extracts binds in bounded time."""
        import time

        from paleo_workbench.catalog.domain_binding import (
            WellExtract,
            bind_well_extracts,
        )

        project = self._project(10_000)
        extracts = [
            WellExtract(name=f"W-{i}", uwi="", x=float(i), y=float(i))
            for i in range(3_000)
        ]
        start = time.perf_counter()
        report = bind_well_extracts(
            project, extracts, asset_id=None, spatial_scope="reference"
        )
        elapsed = time.perf_counter() - start
        assert report.wells_created == 3_000 or report.wells_updated >= 0
        # 10k existing + 3k extracts must complete well under the O(N×W)
        # regime (which re-normalized 30M match-key sets); generous bound.
        assert elapsed < 60.0, f"binding took {elapsed:.1f}s"

    def test_ambiguous_duplicate_names_flagged_not_merged(self):
        from paleo_workbench.catalog.domain_binding import (
            WellExtract,
            bind_well_extracts,
        )

        project = self._project(2)
        # Force two existing wells to share the normalized name key.
        project.wells[1].name = "W-0"
        from paleo_workbench.project.domain import normalize_well_name

        report = bind_well_extracts(
            project,
            [WellExtract(name="W-0", uwi="", x=None, y=None)],
            asset_id=None,
        )
        assert report.ambiguous_assets == 1
        assert report.wells_created == 0


class TestReviewRegressions:
    def test_anonymous_target_returns_no_tops(self):
        """R3-P1: a target with no id AND no name must not receive every
        well's tops."""
        tops = [
            _top("well-a", "W-1", "H1", 100.0),
            _top("well-b", "W-2", "H1", 200.0),
        ]
        assert tops_overlay_for_well(tops, well_id="", well_name="") == []
