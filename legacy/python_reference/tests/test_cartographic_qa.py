"""V7 §14 — cartographic QA rules: localization + honest degradation.

Every rule fires on a purpose-built fake project/snapshot/capability; every
issue carries rule/severity/message plus a localization field
(layer_id/feature_id/ref/geometry); missing inputs SKIP with a note in the
rule summary instead of being guessed. All fixtures are plain objects — no
bridge, no Qt.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest

from paleo_workbench.mapping.cartographic_qa import (
    CARTOGRAPHIC_QA_RULES,
    collect_cartographic_qa,
    collect_cartographic_qa_issues,
)
from paleo_workbench.mapping_workspace.dependencies import (
    ArtifactFreshness,
    FreshnessStatus,
    StaleSummary,
)
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.layer_tree import GroupNode, LayerRef
from paleo_workbench.mapping_workspace.stage_state import (
    LayerMembershipRecord,
    MappingWorkspaceState,
)
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import (
    MapProductRecord,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ProjectMeta,
    UserVectorFeature,
    UserVectorLayer,
)

pyproj = pytest.importorskip("pyproj", reason="crs rules need pyproj to resolve")


def _project(**extra) -> ProjectDocument:
    return ProjectDocument(
        id="p1", name="p1", meta=ProjectMeta(name="p1"), **extra
    )


def _layer(layer_id: str, *, crs: str = "EPSG:32650", features=(), style=None,
           role=None) -> UserVectorLayer:
    return UserVectorLayer(
        id=layer_id,
        name=layer_id,
        crs=crs,
        style=dict(style or {}),
        features=list(features),
    )


def _feature(fid: str, geometry: dict, properties: dict | None = None):
    return UserVectorFeature(id=fid, geometry=geometry, properties=properties or {})


def _snap(*layers):
    return NS(project_crs="EPSG:32650", layers=tuple(layers))


def _snap_layer(layer_id: str, layer_type: str, *, crs: str = "EPSG:32650",
                style=None, extent=(0.0, 0.0, 1.0, 1.0), metadata=None,
                source_version_id: str = "", renderer_payload=None):
    return NS(
        id=layer_id, name=layer_id, layer_type=layer_type, crs=crs,
        style=dict(style or {}), extent=extent, metadata=dict(metadata or {}),
        source_version_id=source_version_id,
        renderer_payload=renderer_payload, features=(),
    )


def _by_rule(issues, rule: str) -> list[dict]:
    return [i for i in issues if i["rule"] == rule]


# ---------------------------------------------------------------------------
# Registry + honesty
# ---------------------------------------------------------------------------


def test_rule_registry_covers_the_section14_list():
    assert set(CARTOGRAPHIC_QA_RULES) == {
        "crs_invalid", "unit_unknown", "geometry_invalid",
        "layer_outside_extent", "stale_input", "missing_source",
        "renderer_domain_mismatch", "legend_empty", "core_furniture_missing",
        "low_confidence", "fallback_renderer", "unpublished_data_in_export",
        "style_binding_unknown", "raster_range_invalid",
        "broken_factor_group",
    }


def test_empty_project_skips_every_rule_with_notes():
    issues, summary = collect_cartographic_qa(_project())
    assert issues == []
    assert set(summary) == set(CARTOGRAPHIC_QA_RULES)
    for rule, entry in summary.items():
        assert entry["evaluated"] == 0
        assert entry["skipped"] >= 1, f"{rule} skipped without a note"
        assert entry["notes"], f"{rule} carries no skip note"


# ---------------------------------------------------------------------------
# CRS / unit
# ---------------------------------------------------------------------------


def test_crs_invalid_fires_for_unresolvable_crs():
    project = _project(
        user_vector_layers=[_layer("l1", crs="NOT::A-CRS::at-all")]
    )
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "crs_invalid")
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"
    assert hits[0]["ref"] == "l1" and hits[0]["layer_id"] == "l1"


def test_unit_unknown_when_axes_cannot_be_verified(monkeypatch):
    from paleo_workbench.mapping import cartographic_qa

    monkeypatch.setattr(cartographic_qa, "_pyproj_available", lambda: False)
    project = _project(
        user_vector_layers=[_layer("l1", crs="EPSG:777777777")]
    )
    issues, summary = collect_cartographic_qa(project)
    hits = _by_rule(issues, "unit_unknown")
    assert len(hits) == 1
    assert hits[0]["ref"] == "l1"
    assert summary["unit_unknown"]["evaluated"] >= 1


# ---------------------------------------------------------------------------
# Geometry / extent
# ---------------------------------------------------------------------------


def test_geometry_invalid_locates_feature_and_geometry():
    shapely = pytest.importorskip("shapely", reason="validation engine")
    bowtie = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]],
    }
    project = _project(user_vector_layers=[
        _layer("l1", features=[_feature("f1", bowtie),
                               _feature("f2", {"type": "Point",
                                               "coordinates": [1, 1]})]),
    ])
    issues, summary = collect_cartographic_qa(project)
    hits = _by_rule(issues, "geometry_invalid")
    assert len(hits) == 1  # the valid feature stays silent
    issue = hits[0]
    assert issue["feature_id"] == "f1"
    assert issue["ref"] == "l1" and issue["layer_id"] == "l1"
    assert issue["geometry"] == bowtie
    assert summary["geometry_invalid"]["evaluated"] == 2


def test_layer_outside_workarea_extent_reported_with_bboxes():
    from paleo_workbench.project.domain import WorkArea

    project = _project(
        workarea=WorkArea(
            boundary=[[0, 0], [10, 0], [10, 10], [0, 10]],
            boundary_crs="EPSG:32650",
            project_crs="EPSG:32650",
        ),
        user_vector_layers=[
            _layer("inside", features=[
                _feature("f1", {"type": "Point", "coordinates": [5, 5]})]),
            _layer("outside", features=[
                _feature("f2", {"type": "Point", "coordinates": [50, 50]})]),
        ],
    )
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "layer_outside_extent")
    assert [h["layer_id"] for h in hits] == ["outside"]
    assert hits[0]["layer_bbox"] == [50.0, 50.0, 50.0, 50.0]
    assert hits[0]["workarea_bbox"] == [0.0, 0.0, 10.0, 10.0]


# ---------------------------------------------------------------------------
# Staleness / sources
# ---------------------------------------------------------------------------


def test_stale_input_reuses_dependency_summary_and_localizes():
    summary_in = StaleSummary((
        ArtifactFreshness(
            "factor:task1", "factor", MappingStage.CONSTRAINT_FACTOR,
            FreshnessStatus.STALE, "上游输入已有新版本",
            upstream_culprits=("ver_1",),
        ),
        ArtifactFreshness(
            "integrated:lyr1", "integrated", MappingStage.INTEGRATED_COMPILATION,
            FreshnessStatus.MISSING_INPUT, "输入版本缺失或已清理",
        ),
    ))
    issues = collect_cartographic_qa_issues(_project(), stale_summary=summary_in)
    hits = _by_rule(issues, "stale_input")
    assert {h["ref"] for h in hits} == {"factor:task1", "integrated:lyr1"}
    missing = next(h for h in hits if h["ref"] == "integrated:lyr1")
    assert missing["severity"] == "error"
    stale = next(h for h in hits if h["ref"] == "factor:task1")
    assert stale["severity"] == "warning"
    assert stale["upstream_culprits"] == ["ver_1"]


def test_missing_source_fires_for_absent_catalog_version_and_file(tmp_path):
    class _Catalog:
        def resolve_version(self, version_id):
            if version_id == "ver_ok":
                return NS(id=version_id, asset_id="a1", run_id="")
            return None

    snapshot = _snap(
        _snap_layer("g1", "scalar_grid", source_version_id="ver_gone"),
        _snap_layer("r1", "raster_source",
                    renderer_payload=str(tmp_path / "missing.tif")),
    )
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="lyr_draft", role=LayerRole.INITIAL_FACIES_DRAFT,
        source_version_id="ver_gone"))
    project = _project(mapping_workspace=state.to_dict())
    issues = collect_cartographic_qa_issues(
        project, snapshot=snapshot, catalog=_Catalog()
    )
    hits = _by_rule(issues, "missing_source")
    assert {h["layer_id"] for h in hits} == {"g1", "r1", "lyr_draft"}
    assert all(h["severity"] == "error" for h in hits)


# ---------------------------------------------------------------------------
# Renderer domain / legends / furniture
# ---------------------------------------------------------------------------


def test_renderer_domain_mismatch_uses_spec_choices_and_locates_layer():
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="lyr_int", role=LayerRole.INTEGRATED_FACIES))
    project = _project(
        mapping_workspace=state.to_dict(),
        user_vector_layers=[
            _layer(
                "lyr_int",
                style={"renderer": "categorized", "field": "facies_name",
                       "categories": [["alluvial_fan", "#111"]]},
                features=[
                    _feature("f1", {"type": "Point", "coordinates": [1, 1]},
                             {"facies_name": "alluvial_fan"}),
                    _feature("f2", {"type": "Point", "coordinates": [2, 2]},
                             {"facies_name": "volcanic_wasteland"}),
                ],
            ),
        ],
    )
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "renderer_domain_mismatch")
    assert len(hits) == 1
    assert hits[0]["layer_id"] == "lyr_int"
    assert hits[0]["out_of_domain"] == ["volcanic_wasteland"]


def test_renderer_domain_rule_skips_honestly_for_unknown_role():
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="lyr_x", role=LayerRole.LEGACY_UNCLASSIFIED))
    project = _project(
        mapping_workspace=state.to_dict(),
        user_vector_layers=[
            _layer("lyr_x", style={"renderer": "categorized",
                                   "field": "whatever"}),
        ],
    )
    issues, summary = collect_cartographic_qa(project)
    assert _by_rule(issues, "renderer_domain_mismatch") == []
    assert summary["renderer_domain_mismatch"]["skipped"] >= 1


def _legend_composition(elements, template_id=None):
    from paleo_workbench.mapping.composer.models import MapCompositionDocument

    doc = MapCompositionDocument(id="comp_qa", title="t")
    for element in elements:
        doc.add_element(element)
    if template_id:
        doc.metadata["template_id"] = template_id
    return doc


def test_empty_legend_reported_at_element_level():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement, ElementType,
    )

    empty = ComposerElement("el_leg", ElementType.LEGEND, 200, 30, 80, 60,
                            properties={})
    filled = ComposerElement(
        "el_leg2", ElementType.FACIES_LEGEND, 200, 95, 78, 60,
        properties={"items": ({"label": "河流", "color": "#123456"},)},
    )
    project = _project(compositions=[
        _legend_composition([empty, filled]),
    ])
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "legend_empty")
    assert len(hits) == 1
    assert hits[0]["feature_id"] == "el_leg"
    assert hits[0]["ref"] == "comp_qa"


def test_missing_core_furniture_for_template_composition():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement, ElementType,
    )

    composition = _legend_composition(
        [
            ComposerElement("m", ElementType.MAIN_MAP, 15, 30, 180, 140),
            ComposerElement("s", ElementType.SCALE_BAR, 20, 180, 50, 8),
        ],
        template_id="single_factor",
    )
    plain = _legend_composition([])  # no template expectation → skipped
    project = _project(compositions=[composition, plain])
    issues, summary = collect_cartographic_qa(project)
    hits = _by_rule(issues, "core_furniture_missing")
    assert {h["missing"] for h in hits} == {"north_arrow", "title"}
    assert all(h["ref"] == "comp_qa" for h in hits)
    assert summary["core_furniture_missing"]["skipped"] >= 1  # plain comp


# ---------------------------------------------------------------------------
# Confidence / capability / maturity / style binding / ranges / groups
# ---------------------------------------------------------------------------


def test_low_confidence_prediction_overlay_reported():
    project = _project(prediction_tasks=[
        PredictionTask(id="pred1", name="测井预测",
                       probability_summary={"mean": 0.3, "min": 0.1,
                                            "low_confidence_regions": 4}),
        PredictionTask(id="pred2", name="高置信",
                       probability_summary={"mean": 0.9, "min": 0.8}),
    ])
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "low_confidence")
    assert [h["ref"] for h in hits] == ["pred1"]
    assert hits[0]["low_confidence_regions"] == 4


def test_fallback_renderer_disclosed_when_qgis_unavailable_with_scalars():
    snapshot = _snap(_snap_layer("g1", "scalar_grid"))
    issues = collect_cartographic_qa_issues(
        _project(), snapshot=snapshot,
        capability={"qgis_available": False, "reason": "bridge 未构建"},
    )
    hits = _by_rule(issues, "fallback_renderer")
    assert len(hits) == 1
    assert hits[0]["layer_id"] == "g1"
    assert hits[0]["severity"] == "warning"
    assert "bridge 未构建" in hits[0]["message"]
    # capability saying qgis IS available evaluates silently
    issues_ok = collect_cartographic_qa_issues(
        _project(), snapshot=snapshot, capability={"qgis_available": True}
    )
    assert _by_rule(issues_ok, "fallback_renderer") == []


def test_unpublished_maturity_in_export_bound_project():
    state = MappingWorkspaceState()
    state.set_maturity("integrated:lyr1", "draft")
    state.set_maturity("integrated:lyr2", "published")
    project = _project(
        mapping_workspace=state.to_dict(),
        map_products=[MapProductRecord(product_name="T1 古地理图")],
    )
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "unpublished_data_in_export")
    assert [h["ref"] for h in hits] == ["integrated:lyr1"]
    assert hits[0]["layer_id"] == "lyr1"
    # no MapProduct → the rule is out of scope, honestly skipped
    _issues2, summary2 = collect_cartographic_qa(
        _project(mapping_workspace=state.to_dict())
    )
    assert summary2["unpublished_data_in_export"]["skipped"] == 1


def test_style_binding_against_symbols_library():
    good = _layer("l1", style={"style_binding": {"symbol_id": "facies_v2"}})
    bad = _layer("l2", style={"style_binding": {"symbol_id": "nope_v99"}})
    aliased = _layer("l3", style={"style_binding": "shoreline_v1"})
    project = _project(user_vector_layers=[good, bad, aliased])
    issues, summary = collect_cartographic_qa(project)
    hits = _by_rule(issues, "style_binding_unknown")
    if summary["style_binding_unknown"]["skipped"] and not hits:
        pytest.skip("geological_symbols library not importable — honest skip")
    assert [h["layer_id"] for h in hits] == ["l2"]
    assert hits[0]["symbol_id"] == "nope_v99"


def test_raster_range_invalid_for_bad_manual_range_and_nan_stats():
    bad_manual = _snap_layer(
        "g1", "scalar_grid",
        style={"scalar_style": {"manual_range": [5.0, 2.0]}},
    )
    nan_stats = _snap_layer(
        "g2", "scalar_grid",
        style={"color_range": [0.0, 1.0], "value_range": [float("nan")] * 2},
    )
    legacy_bad = _snap_layer("g3", "scalar_grid",
                             style={"color_range": [9.0, 1.0]})
    ok = _snap_layer("g4", "scalar_grid",
                     style={"color_range": [0.0, 1.0]})
    issues = collect_cartographic_qa_issues(
        _project(), snapshot=_snap(bad_manual, nan_stats, legacy_bad, ok)
    )
    hits = _by_rule(issues, "raster_range_invalid")
    assert {h["layer_id"] for h in hits} == {"g1", "g2", "g3"}
    assert all(h["severity"] == "error" for h in hits)
    assert any("hi<=lo" in h["problem"] for h in hits)


def _workspace_with_factor_group(complete: bool) -> dict:
    state = MappingWorkspaceState()
    roles = [LayerRole.FACTOR_INPUT, LayerRole.FACTOR_GRID,
             LayerRole.FACTOR_CONTOUR, LayerRole.FACTOR_CLASSIFICATION,
             LayerRole.FACTOR_UNCERTAINTY, LayerRole.FACTOR_QC]
    roles = roles if complete else roles[:2]
    children = [LayerRef(layer_id=f"lyr_{role.value}").to_dict() for role in roles]
    for role in roles:
        state.set_membership(LayerMembershipRecord(
            layer_id=f"lyr_{role.value}", role=role, factor_task_id="task1"))
    tree = GroupNode(group_id="root", name="root", children=(
        GroupNode(group_id="factor.task1", name="task1",
                  children=tuple(LayerRef(layer_id=f"lyr_{role.value}")
                                 for role in roles)),
    )).to_dict()
    state.tree = tree
    return state.to_dict()


def test_broken_factor_group_missing_children():
    project = _project(mapping_workspace=_workspace_with_factor_group(False))
    issues = collect_cartographic_qa_issues(project)
    hits = _by_rule(issues, "broken_factor_group")
    assert len(hits) == 1
    assert hits[0]["ref"] == "factor.task1"
    assert set(hits[0]["missing_roles"]) == {
        "factor_contour", "factor_classification",
        "factor_uncertainty", "factor_qc",
    }
    complete = _project(mapping_workspace=_workspace_with_factor_group(True))
    assert _by_rule(
        collect_cartographic_qa_issues(complete), "broken_factor_group"
    ) == []


# ---------------------------------------------------------------------------
# Localization contract + stage-QA composition
# ---------------------------------------------------------------------------


def test_every_issue_is_localized_and_well_formed():
    state = MappingWorkspaceState()
    state.set_membership(LayerMembershipRecord(
        layer_id="lyr_int", role=LayerRole.INTEGRATED_FACIES))
    state.set_maturity("integrated:lyr_int", "draft")
    project = _project(
        mapping_workspace=state.to_dict(),
        user_vector_layers=[
            _layer("l1", crs="NOT::A-CRS"),
            _layer("lyr_int",
                   style={"renderer": "categorized", "field": "facies_name"},
                   features=[_feature(
                       "f1", {"type": "Point", "coordinates": [1, 1]},
                       {"facies_name": "mystery"})]),
        ],
        prediction_tasks=[PredictionTask(
            id="pred1", name="p",
            probability_summary={"mean": 0.2})],
        map_products=[MapProductRecord(product_name="x")],
    )
    snapshot = _snap(_snap_layer("g1", "scalar_grid",
                                 style={"color_range": [3.0, 1.0]}))
    issues = collect_cartographic_qa_issues(
        project, snapshot=snapshot,
        capability={"qgis_available": False},
    )
    assert issues, "fixture must fire several rules"
    for issue in issues:
        assert issue["rule"] in CARTOGRAPHIC_QA_RULES
        assert issue["severity"] in ("error", "warning", "info")
        assert issue["message"]
        assert ("ref" in issue or "feature_id" in issue
                or "layer_id" in issue), f"unlocalized: {issue}"


def test_stage_qa_can_compose_both_collectors():
    """The wiring proof: extended + cartographic collectors compose.

    ``ui/workstation/stage_actions.py`` ``run_qa`` is main-agent owned (not
    edited here); this test pins the contract its one-line wiring needs —
    both collectors run on the same project and their rule ids stay
    disjoint.
    """
    from paleo_workbench.workflow.map_qa_rules import (
        cartographic_issues,
        collect_extended_qc_issues,
    )

    document = PaleoMapDocument(name="T1 图", linked_target_horizon="T1",
                                map_crs="EPSG:32650")
    project = _project(
        user_vector_layers=[_layer("l1", crs="EPSG:4326")],  # crs_mismatch
        prediction_tasks=[PredictionTask(
            id="pred1", name="p", probability_summary={"mean": 0.1})],
    )
    snapshot = _snap(_snap_layer("g1", "scalar_grid"))
    extended = collect_extended_qc_issues(project, document)
    carto = cartographic_issues(
        project, snapshot=snapshot,
        capability={"qgis_available": False},
    )
    assert any(i["rule"] == "crs_mismatch" for i in extended)
    assert any(i["rule"] == "low_confidence" for i in carto)
    assert any(i["rule"] == "fallback_renderer" for i in carto)
    assert not {i["rule"] for i in extended} & {i["rule"] for i in carto}
