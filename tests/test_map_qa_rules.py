"""M12 — extended map QA rules.

Every rule fires on a purpose-built fixture, every issue locates the problem
(layer/feature/ref), and clean documents produce no noise.
"""

from __future__ import annotations

import pytest

from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
    ProjectMeta,
    UserVectorFeature,
    UserVectorLayer,
)
from paleo_workbench.workflow.map_qa_rules import (
    EXTENDED_QC_RULES,
    collect_extended_qc_issues,
    composition_qa_issues,
)


def _document(**kwargs) -> PaleoMapDocument:
    return PaleoMapDocument(name="T1 图", linked_target_horizon="T1", **kwargs)


def _project() -> ProjectDocument:
    return ProjectDocument(id="p", name="p", meta=ProjectMeta(name="p"))


def test_extended_rules_registry_complete():
    assert "crs_undeclared" in EXTENDED_QC_RULES
    assert "class_renderer_mismatch" in EXTENDED_QC_RULES
    assert "export_fallback" in EXTENDED_QC_RULES


def test_clean_project_has_no_issues():
    project = _project()
    document = _document(map_crs="EPSG:32650", extent=(0.0, 0.0, 100.0, 100.0))
    issues = collect_extended_qc_issues(project, document)
    assert issues == []


def test_undeclared_crs_reported_at_document_and_layer():
    project = _project()
    project.user_vector_layers = [
        UserVectorLayer(id="l1", name="断层线", crs=""),
    ]
    document = _document()
    issues = collect_extended_qc_issues(project, document)
    rules = {i["rule"] for i in issues}
    assert rules == {"crs_undeclared"}
    refs = {i["ref"] for i in issues}
    assert document.id in refs and "l1" in refs


def test_layer_crs_mismatch_is_error_and_locates_layer():
    project = _project()
    project.user_vector_layers = [
        UserVectorLayer(id="l1", name="井位", crs="EPSG:4326"),
    ]
    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(project, document)
    mismatch = [i for i in issues if i["rule"] == "crs_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["severity"] == "error"
    assert mismatch[0]["ref"] == "l1"


def test_categorized_style_missing_class_reported():
    project = _project()
    project.user_vector_layers = [
        UserVectorLayer(
            id="l1",
            name="相带",
            crs="EPSG:32650",
            style={
                "renderer": "categorized",
                "field": "facies_name",
                "categories": [["浅湖", "#cccccc", "浅湖"]],
            },
            features=[
                UserVectorFeature(
                    id="f1",
                    geometry={"type": "Point", "coordinates": [1.0, 2.0]},
                    properties={"facies_name": "深湖"},
                ),
            ],
        ),
    ]
    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(project, document)
    mismatch = [i for i in issues if i["rule"] == "class_renderer_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["missing_classes"] == ["深湖"]


def test_facies_style_missing_class_reported():
    project = _project()
    document = _document(
        map_crs="EPSG:32650",
        facies_style={
            "renderer": "categorized",
            "field": "facies_name",
            "categories": [["浅湖", "#cccccc", "浅湖"]],
        },
        facies_polygons=[
            {
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                "properties": {"facies_name": "河口坝"},
            },
        ],
    )
    issues = collect_extended_qc_issues(project, document)
    mismatch = [i for i in issues if i["rule"] == "class_renderer_mismatch"]
    assert len(mismatch) == 1
    assert mismatch[0]["missing_classes"] == ["河口坝"]


def test_out_of_bound_feature_locates_geometry():
    project = _project()
    project.user_vector_layers = [
        UserVectorLayer(
            id="l1",
            name="物源",
            crs="EPSG:32650",
            features=[
                UserVectorFeature(
                    id="f_out",
                    geometry={"type": "Point", "coordinates": [500.0, 500.0]},
                    properties={},
                ),
                UserVectorFeature(
                    id="f_in",
                    geometry={"type": "Point", "coordinates": [5.0, 5.0]},
                    properties={},
                ),
            ],
        ),
    ]
    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(
        project, document, map_extent=(0.0, 0.0, 100.0, 100.0)
    )
    out = [i for i in issues if i["rule"] == "out_of_bound_feature"]
    assert len(out) == 1
    assert out[0]["feature_id"] == "f_out"
    assert out[0]["geometry"]["type"] == "Point"


def test_stale_factor_task_and_empty_well_table():
    project = _project()
    task = FactorMapTask(
        id="t1",
        name="T1 砂地比",
        target_horizon="T1",
        factor_type="砂地比",
        method="IDW",
        well_table_id="wt1",
        status="complete",
        grid_artifact_version_id=None,
    )
    project.factor_map_tasks = [task]

    from paleo_workbench.project.models import WellTable

    table = WellTable(id="wt1", name="井表", target_horizon="T1", rows=[])
    project.well_tables = [table]

    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(project, document)
    rules = {i["rule"] for i in issues}
    assert "stale_inputs" in rules
    assert "well_table_empty" in rules
    stale = next(i for i in issues if i["rule"] == "stale_inputs")
    assert stale["ref"] == "t1"


def test_low_confidence_rule_fires_below_threshold():
    project = _project()
    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(
        project,
        document,
        fusion_confidence={"min": 0.21, "mean": 0.6},
        confidence_threshold=0.5,
    )
    low = [i for i in issues if i["rule"] == "low_confidence"]
    assert len(low) == 1
    assert low[0]["confidence_min"] == pytest.approx(0.21)
    # healthy confidence is silent
    assert collect_extended_qc_issues(
        project,
        document,
        fusion_confidence={"min": 0.8, "mean": 0.9},
        confidence_threshold=0.5,
    ) == []


def test_export_fallback_surfaces_as_qa_warning():
    project = _project()
    document = _document(map_crs="EPSG:32650")
    issues = collect_extended_qc_issues(
        project,
        document,
        export_report={"engine": "fallback", "degraded_reason": "no stack"},
    )
    warn = [i for i in issues if i["rule"] == "export_fallback"]
    assert len(warn) == 1
    assert "回退" in warn[0]["message"]


def test_broken_interpretation_reference():
    from paleo_workbench.project.models import MapProductRecord

    project = _project()
    document = _document(map_crs="EPSG:32650")
    record = MapProductRecord(
        product_name="T1 成果", interpretation_refs=["ghost-ref"]
    )
    project.map_products = [record]
    issues = collect_extended_qc_issues(project, document)
    broken = [i for i in issues if i["rule"] == "broken_external_reference"]
    assert len(broken) == 1
    assert broken[0]["ref"] == "ghost-ref"
    assert broken[0]["severity"] == "error"


def test_composition_qa_missing_core_furniture():
    from paleo_workbench.mapping.composer.models import (
        ComposerElement,
        ElementType,
        MapCompositionDocument,
    )

    composition = MapCompositionDocument(id="c1", title="t")
    composition.add_element(
        ComposerElement("el_title", ElementType.TITLE, 0, 0, 10, 5)
    )
    issues = composition_qa_issues(composition)
    rules = {i["rule"] for i in issues}
    assert rules == {"composition_incomplete"}
    messages = " ".join(i["message"] for i in issues)
    for label in ("主图", "图例", "比例尺"):
        assert label in messages

    composition.add_element(
        ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180, 150)
    )
    composition.add_element(
        ComposerElement("el_legend", ElementType.LEGEND, 192, 12, 60, 60)
    )
    composition.add_element(
        ComposerElement("el_scale", ElementType.SCALE_BAR, 192, 150, 60, 10)
    )
    assert composition_qa_issues(composition) == []
