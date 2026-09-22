#!/usr/bin/env python3
"""Generate the frozen workflow QC oracle for CONV-33 (route A1).

Drives the REAL Python implementation (paleo_workbench.workflow.qc +
paleo_workbench.workflow.map_qa_rules, backed by the real geoviz
validate_ring and mapping.geometry_operations.centroid facades) with
representative ProjectDocument cases and freezes every observable output:
issue lists (with the three-level centroid locate chain), stable-id report
upserts, mutated project state, active-run binding, honest rule coverage,
extended QA issues, and composite-page furniture checks.

Every case's ``input`` carries the FULL scenario as plain JSON so the C++
replay reconstructs it independently — the fixture is the only shared
artifact. Determinism: pydantic ids/timestamps are set explicitly, and the
two runtime stamping seams (models._now_iso via a frozen datetime subclass,
models._id via a sequential factory) are patched; the frozen clock state is
recorded per case in ``input["clock"]`` so the C++ side injects identical
values through project::ModelClock.

Raise cases freeze class + message verbatim. Re-runs are byte-identical.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.project.models as pm  # noqa: E402
from paleo_workbench.workflow.qc import (  # noqa: E402
    active_quality_reports,
    issue_layer_geojson,
    make_issue,
    run_basic_qc,
    run_map_qc,
    spatial_issues,
)
from paleo_workbench.workflow.map_qa_rules import (  # noqa: E402
    collect_extended_qc_issues,
    composition_qa_issues,
    extended_rule_coverage,
)

FIXTURE = (
    ROOT
    / "libs/workflow_runtime/workflow_runtime_tests/fixtures/"
    "workflow_qc_oracle.json"
)

FROZEN_NOW = "2026-01-01T00:00:00+00:00"


class _FrozenDatetime(datetime):
    """models._now_iso() reads the module-global ``datetime`` at call time."""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 — parity with datetime.now(tz)
        return datetime(2026, 1, 1, tzinfo=timezone.utc)


pm.datetime = _FrozenDatetime

_clock_ids: list[str] = []


def _frozen_id(prefix: str) -> str:
    value = f"{prefix}_frozen{len(_clock_ids) + 1:02d}"
    _clock_ids.append(value)
    return value


pm._id = _frozen_id  # default_factory lambdas resolve this at call time


def reset_clock() -> None:
    _clock_ids.clear()


def clock_state() -> dict:
    return {"now_iso": FROZEN_NOW, "ids": list(_clock_ids)}


cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def capture(fn, *args, **kwargs):
    try:
        return {"result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 — freeze class + message verbatim
        return {"raise": {"python_class": type(exc).__name__, "message": str(exc)}}


# ------------------------------------------------------------- doc builders

def make_doc(
    doc_id: str = "map_doc1",
    name: str = "H1 古地理图",
    horizon: str = "H1",
    **over,
) -> pm.PaleoMapDocument:
    fields: dict = {
        "id": doc_id,
        "name": name,
        "linked_target_horizon": horizon,
    }
    fields.update(over)
    return pm.PaleoMapDocument(**fields)


def make_project(
    docs: list | None = None,
    tables: list | None = None,
    runs: list | None = None,
    reports: list | None = None,
    layers: list | None = None,
    tasks: list | None = None,
    products: list | None = None,
    interpretations: dict | None = None,
) -> pm.ProjectDocument:
    project = pm.ProjectDocument(
        meta=pm.ProjectMeta(
            name="qc-oracle",
            created_at=FROZEN_NOW,
            updated_at=FROZEN_NOW,
        )
    )
    project.paleomap_documents = docs or []
    project.well_tables = tables or []
    project.compilation_runs = runs or []
    project.quality_reports = reports or []
    project.user_vector_layers = layers or []
    project.factor_map_tasks = tasks or []
    project.map_products = products or []
    interpretations = interpretations or {}
    project.horizon_interpretations = interpretations.get("horizon", [])
    project.correlation_interpretations = interpretations.get("correlation", [])
    project.fault_interpretations = interpretations.get("fault", [])
    return project


def make_run(
    run_id: str,
    name: str,
    horizon: str = "H1",
    active_report: str | None = None,
    active_map: str | None = None,
    updated_at: str = "2025-06-01T00:00:00+00:00",
) -> pm.CompilationRun:
    return pm.CompilationRun(
        id=run_id,
        name=name,
        target_horizon=horizon,
        workflow_steps=[
            pm.WorkflowStep(id="step_a", step_type="data_check", status="complete"),
        ],
        active_quality_report_id=active_report,
        active_paleomap_document_id=active_map,
        created_at="2025-05-01T00:00:00+00:00",
        updated_at=updated_at,
    )


def make_report(
    report_id: str,
    map_id: str,
    status: str = "warning",
    issues: list | None = None,
) -> pm.QualityReport:
    return pm.QualityReport(
        id=report_id,
        linked_map_document_id=map_id,
        rules=["target_horizon_present"],
        issues=issues or [],
        status=status,
        generated_at="2025-06-02T00:00:00+00:00",
    )


SQUARE_RING = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]]
BOWTIE_RING = [[0.0, 0.0], [4.0, 0.0], [0.0, 4.0], [4.0, 4.0], [0.0, 0.0]]

# ---------------------------------------------------------- make_issue face

MAKE_ISSUE_CASES: list[tuple[str, dict]] = [
    (
        "plain",
        {"rule": "well_table_qc_clean", "severity": "warning",
         "message": "井点 W-1 质控=outlier"},
    ),
    (
        "point",
        {"rule": "well_table_qc_clean", "severity": "warning",
         "message": "井点 W-2 质控=missing",
         "fields": {"geometry": {"type": "Point", "coordinates": [3.5, -1.25]}}},
    ),
    (
        "polygon_area_centroid",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f1 自相交",
         "fields": {"geometry": {
             "type": "Polygon",
             "coordinates": [[list(r) for r in SQUARE_RING]],
         }}},
    ),
    (
        "polygon_with_hole",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f2 自相交",
         "fields": {"geometry": {
             "type": "Polygon",
             "coordinates": [
                 [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]],
                 [[1.0, 1.0], [3.0, 1.0], [3.0, 3.0], [1.0, 3.0], [1.0, 1.0]],
             ],
         }}},
    ),
    (
        "bowtie_vertex_mean_fallback",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f3 自相交",
         "fields": {"geometry": {
             "type": "Polygon",
             "coordinates": [[list(r) for r in BOWTIE_RING]],
         }}},
    ),
    (
        "degenerate_zero_area",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f4 自相交",
         "fields": {"geometry": {
             "type": "Polygon",
             "coordinates": [[[0.0, 0.0], [2.0, 2.0], [4.0, 4.0], [0.0, 0.0]]],
         }}},
    ),
    (
        "malformed_no_coordinates",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f5 自相交",
         "fields": {"geometry": {"type": "Polygon"}}},
    ),
    (
        "linestring",
        {"rule": "out_of_bound_feature", "severity": "warning",
         "message": "要素坐标 (12.00, -3.00) 超出图面范围",
         "fields": {"geometry": {
             "type": "LineString",
             "coordinates": [[0.0, 0.0], [4.0, 2.0], [8.0, 0.0]],
         }}},
    ),
    (
        "unknown_type_fallback",
        {"rule": "out_of_bound_feature", "severity": "warning",
         "message": "要素坐标 (12.00, -3.00) 超出图面范围",
         "fields": {"geometry": {
             "type": "GeometryCollection",
             "coordinates": [[1.0, 2.0], [5.0, 6.0]],
         }}},
    ),
    (
        "multipolygon_two_parts",
        {"rule": "out_of_bound_feature", "severity": "warning",
         "message": "要素坐标 (20.00, 0.00) 超出图面范围",
         "fields": {"geometry": {
             "type": "MultiPolygon",
             "coordinates": [
                 [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]],
                 [[[10.0, 0.0], [12.0, 0.0], [12.0, 2.0], [10.0, 2.0], [10.0, 0.0]]],
             ],
         }}},
    ),
    (
        "empty_line_no_centroid",
        {"rule": "out_of_bound_feature", "severity": "warning",
         "message": "要素坐标 (20.00, 0.00) 超出图面范围",
         "fields": {"geometry": {"type": "LineString", "coordinates": []}}},
    ),
    (
        "extra_and_spatial_fields",
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f6 自相交",
         "fields": {
             "feature_id": "f6",
             "feature_kind": "facies",
             "geometry": {"type": "Point", "coordinates": [7.0, 8.0]},
             "ref": "map:map_doc1/facies/f6",
             "extra": {"code": "self_intersection"},
         }},
    ),
    (
        "empty_extra_ignored",
        {"rule": "target_horizon_present", "severity": "error",
         "message": "古地理图未关联目标位",
         "fields": {"extra": {}}},
    ),
]

for cid, spec in MAKE_ISSUE_CASES:
    fields = spec.get("fields", {})
    kwargs = {
        "feature_id": fields.get("feature_id"),
        "feature_kind": fields.get("feature_kind"),
        "geometry": fields.get("geometry"),
        "ref": fields.get("ref"),
        "extra": fields.get("extra"),
    }
    add(
        f"make_issue.{cid}",
        "qc.make_issue",
        spec,
        capture(
            make_issue,
            rule=spec["rule"],
            severity=spec["severity"],
            message=spec["message"],
            **kwargs,
        ),
    )

# ------------------------------------------------------- spatial_issues face

SPATIAL_MIX = [
    {"rule": "a", "severity": "error", "message": "m1"},
    {"rule": "b", "severity": "warning", "message": "m2",
     "geometry": {"type": "Point", "coordinates": [1.0, 2.0]},
     "centroid": [1.0, 2.0]},
    {"rule": "c", "severity": "warning", "message": "m3", "centroid": [3.0, 4.0]},
    {"rule": "d", "severity": "warning", "message": "m4", "geometry": {}},
    {"rule": "e", "severity": "warning", "message": "m5", "centroid": []},
    {"rule": "f", "severity": "warning", "message": "m6",
     "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}, "centroid": []},
    "not-a-dict",
    {"rule": "g", "severity": "warning", "message": "m7", "geometry": None},
]
add("spatial.mixed", "qc.spatial_issues", {"issues": SPATIAL_MIX},
    capture(spatial_issues, SPATIAL_MIX))
add("spatial.none", "qc.spatial_issues", {"issues": None},
    capture(spatial_issues, None))

# -------------------------------------------------- issue_layer_geojson face

add("geojson.none_report", "qc.issue_layer_geojson",
    {"report": None, "map_document_id": None},
    capture(issue_layer_geojson, None, map_document_id=None))

GEOJSON_REPORT = pm.QualityReport(
    id="qc_layer1",
    linked_map_document_id="map_doc1",
    rules=["well_table_qc_clean", "facies_geometry_valid"],
    issues=[
        {"rule": "well_table_qc_clean", "severity": "warning",
         "message": "井点 W-1 质控=outlier",
         "feature_id": "well_1", "feature_kind": "well",
         "geometry": {"type": "Point", "coordinates": [1.5, 2.5]},
         "centroid": [1.5, 2.5], "ref": "well_table:wt1/well_1"},
        {"rule": "facies_geometry_valid", "severity": "error",
         "message": "相带 f3 自相交", "feature_id": "f3",
         "feature_kind": "facies", "centroid": [2.0, 2.0],
         "ref": "map:map_doc1/facies/f3"},  # centroid-only: no geometry → skipped
        {"rule": "target_horizon_present", "severity": "error",
         "message": "古地理图未关联目标层位"},  # no spatial fields
        {"rule": "well_table_qc_clean", "severity": "warning",
         "message": "井点 W-9 质控=missing",
         "geometry": {},  # empty geometry dict is not locatable
         "feature_id": None, "ref": None},
    ],
    status="error",
    generated_at=FROZEN_NOW,
)
add("geojson.report_default_map", "qc.issue_layer_geojson",
    {"report": GEOJSON_REPORT.model_dump(mode="json"), "map_document_id": None},
    capture(issue_layer_geojson, GEOJSON_REPORT, map_document_id=None))
add("geojson.report_explicit_map", "qc.issue_layer_geojson",
    {"report": GEOJSON_REPORT.model_dump(mode="json"),
     "map_document_id": "map_override"},
    capture(issue_layer_geojson, GEOJSON_REPORT,
            map_document_id="map_override"))

# ------------------------------------------------------- run_basic_qc face

def add_run_basic(cid: str, project: pm.ProjectDocument, doc_id: str,
                  bind: bool = True) -> None:
    reset_clock()
    frozen_project = project.model_dump(mode="json")
    expect = capture(run_basic_qc, project, doc_id, bind_active_run=bind)
    if "result" in expect:
        expect = {
            "result": {
                "report": expect["result"].model_dump(mode="json"),
                "project": project.model_dump(mode="json"),
            }
        }
    add(
        cid,
        "qc.run_basic_qc",
        {
            "project": frozen_project,
            "map_document_id": doc_id,
            "bind_active_run": bind,
            "clock": clock_state(),
        },
        expect,
    )


# 1) empty document: every BASIC presence rule fires, status error.
add_run_basic(
    "basic.empty_doc",
    make_project(docs=[make_doc(horizon="", name="空图")]),
    "map_doc1",
)

# 2) clean document: facies square + well overlay + contour lines + ok rows.
CLEAN_DOC = make_doc(
    facies_polygons=[{"id": "f1", "coordinates": [list(r) for r in SQUARE_RING]}],
    well_overlays=[{"well_id": "well_1"}],
    line_features=[
        {"id": "l1", "role": "contour", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
        {"id": "l2", "properties": {"role": "contour"},
         "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
        {"id": "l3", "role": "fault"},
    ],
)
CLEAN_TABLE = pm.WellTable(
    id="wt_main",
    name="主表",
    target_horizon="H1",
    rows=[
        pm.WellTableRow(well_id="well_1", name="W-1", x=1.5, y=2.5),
        pm.WellTableRow(well_id="well_2", name="W-2", x=3.5, y=4.5,
                        qc_flag="ok", qc_z_star=2.0),
    ],
)
add_run_basic(
    "basic.clean_pass",
    make_project(docs=[CLEAN_DOC], tables=[CLEAN_TABLE]),
    "map_doc1",
)

# 3) malformed facies records of every shape.
BAD_FACIES_DOC = make_doc(
    well_overlays=[{"well_id": "well_1"}],
    line_features=[
        {"id": "l1", "role": "contour", "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    ],
    facies_polygons=[
        {"id": "f_ring", "coordinates": [[0.0, 0.0], [1.0, 0.0]]},  # < 3 顶点
        {"id": "f_flat", "coordinates": [1.0, 2.0, 3.0]},  # 扁平数字列表
        {"id": "f_multi", "coordinates": [  # polygon 坐标（外环自交）
            [list(r) for r in BOWTIE_RING],
            [[0.5, 0.5], [1.0, 0.5], [1.0, 1.0], [0.5, 1.0], [0.5, 0.5]],
        ]},
        {"name": "只有名字的相带", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1]]},
        {  # geometry 键形式（外环合法，无 issue）
            "id": "f_geom",
            "geometry": {"type": "Polygon",
                         "coordinates": [[list(r) for r in SQUARE_RING]]},
        },
        {"id": "f_open", "coordinates": [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0]]},
    ],
)
BAD_FACIES_DOC.facies_polygons.append("junk-entry")  # 非字典记录（绕过校验）
add_run_basic(
    "basic.bad_facies",
    make_project(docs=[BAD_FACIES_DOC]),
    "map_doc1",
)

# 4) well-table qc flags with horizon filtering.
FLAG_TABLES = [
    pm.WellTable(
        id="wt_main",
        name="主表",
        target_horizon="H1",
        rows=[
            pm.WellTableRow(well_id="well_1", name="W-1", x=1.5, y=2.5,
                            qc_flag="outlier", qc_z_star=3.25),
            pm.WellTableRow(well_id="well_2", name="", x=3.5, y=4.5,
                            qc_flag="invalid_ratio"),
            pm.WellTableRow(name="仅名字", x=0.5, y=0.5,
                            qc_flag="missing"),
            pm.WellTableRow(well_id="well_4", name="W-4", x=9.0, y=9.0,
                            qc_flag="ok", qc_z_star=1.5),
        ],
    ),
    pm.WellTable(  # 层位不匹配 → 跳过
        id="wt_other",
        name="别的层位",
        target_horizon="H2",
        rows=[
            pm.WellTableRow(well_id="well_5", name="W-5", x=1.0, y=1.0,
                            qc_flag="outlier"),
        ],
    ),
    pm.WellTable(  # 空层位 → 始终检查
        id="wt_open",
        name="未标层位",
        target_horizon="",
        rows=[
            pm.WellTableRow(well_id="well_6", x=2.0, y=7.0,
                            qc_flag="outlier", qc_z_star=-1.5),
        ],
    ),
]
add_run_basic(
    "basic.well_table_flags",
    make_project(docs=[make_doc()], tables=FLAG_TABLES),
    "map_doc1",
)

# 5) stable-id upsert + active-run binding with two runs.
UPSERT_PROJECT = make_project(
    docs=[make_doc(), make_doc(doc_id="map_other", name="另一张图")],
    runs=[
        make_run("run_1", "第一次编译"),
        make_run("run_2", "第二次编译", updated_at="2025-07-01T00:00:00+00:00"),
    ],
    reports=[
        make_report("qc_prev", "map_doc1", issues=[
            {"rule": "facies_polygons_present", "severity": "warning",
             "message": "旧报告"},
        ]),
        make_report("qc_other", "map_other"),
    ],
)
add_run_basic("basic.upsert_reuse_id", UPSERT_PROJECT, "map_doc1")

# 6) bind_active_run=False leaves the last run untouched.
NOBIND_PROJECT = make_project(
    docs=[make_doc()],
    runs=[make_run("run_9", "运行九")],
)
add_run_basic("basic.no_bind", NOBIND_PROJECT, "map_doc1", bind=False)

# 7) no compilation runs at all.
add_run_basic("basic.no_runs", make_project(docs=[make_doc()]), "map_doc1")

# 8) unknown document id raises.
add_run_basic("basic.unknown_doc", make_project(docs=[make_doc()]), "map_ghost")

# ------------------------------------------------- active_quality_reports

def add_active(cid: str, project: pm.ProjectDocument) -> None:
    frozen = project.model_dump(mode="json")
    expect = capture(active_quality_reports, project)
    if "result" in expect:
        expect = {"result": [r.model_dump(mode="json") for r in expect["result"]]}
    add(cid, "qc.active_quality_reports", {"project": frozen}, expect)


add_active(
    "active.by_map_latest",
    make_project(
        reports=[
            make_report("qc_a1", "map_doc1"),
            make_report("qc_b1", "map_other"),
            make_report("qc_a2", "map_doc1", status="pass"),  # 同图第二份 → 最新
            make_report("qc_a0", "map_doc1"),  # 再一份（按 list 顺序它是最新）
        ],
    ),
)
add_active(
    "active.run_bound",
    make_project(
        runs=[make_run("run_1", "R1", active_report="qc_b1",
                       active_map="map_other")],
        reports=[
            make_report("qc_a1", "map_doc1"),
            make_report("qc_b1", "map_other"),
        ],
    ),
)
add_active(
    "active.dangling_active_id",
    make_project(
        runs=[make_run("run_1", "R1", active_report="qc_ghost")],
        reports=[
            make_report("qc_a1", "map_doc1"),
            make_report("qc_b1", "map_other"),
            make_report("qc_b2", "map_other", status="error"),
        ],
    ),
)
add_active(
    "active.empty_reports",
    make_project(runs=[make_run("run_1", "R1", active_report="qc_ghost")]),
)
add_active(
    "active.falsy_active_id",
    make_project(
        runs=[make_run("run_1", "R1", active_report="")],
        reports=[make_report("qc_a1", "map_doc1")],
    ),
)

# ---------------------------------------------------------- run_map_qc face

QA_LAYER_STYLED = pm.UserVectorLayer(
    id="uvl_1",
    name="岩性点",
    geometry_kind="point",
    crs="",  # 未声明
    style={
        "renderer": "categorized",
        "field": "litho",
        "categories": [["砂岩", "#d9c08a"], ["泥岩", "#8a8ad9"]],
    },
    features=[
        pm.UserVectorFeature(id="f1", geometry={"type": "Point",
                                                "coordinates": [1.0, 1.0]},
                             properties={"litho": "砂岩"}),
        pm.UserVectorFeature(id="f2", geometry={"type": "Point",
                                                "coordinates": [2.0, 2.0]},
                             properties={"litho": "石灰岩"}),
        pm.UserVectorFeature(id="f3", geometry={"type": "Point",
                                                "coordinates": [3.0, 3.0]},
                             properties={"litho": "砾岩"}),
    ],
)
QA_LAYER_MATCHED = pm.UserVectorLayer(
    id="uvl_2",
    name="匹配层",
    geometry_kind="polygon",
    crs="EPSG:32650",
    style={"renderer": "categorized", "field": "zone",
           "categories": {"z1": "#fff", "z2": "#0f0"}},
    features=[
        pm.UserVectorFeature(id="f4",
                             geometry={"type": "Point", "coordinates": [4.0, 4.0]},
                             properties={"zone": "z1"}),
    ],
)
QA_TASKS = [
    pm.FactorMapTask(
        id="factor_1", name="厚度因子", target_horizon="H1",
        factor_type="thickness", method="idw", status="complete",
        well_table_id="wt_empty",
        grid_artifact_version_id=None,  # complete 无栅格 → stale_inputs
    ),
    pm.FactorMapTask(
        id="factor_2", name="泥比因子", target_horizon="H1",
        factor_type="shale_ratio", method="idw", status="complete",
        well_table_id="wt_missing_ref",  # 不存在的表 id → 无 empty 提示
        grid_artifact_version_id="ver_grid_2",
    ),
    pm.FactorMapTask(
        id="factor_3", name="待算因子", target_horizon="H1",
        factor_type="sand_ratio", method="kriging", status="pending",
        well_table_id="wt_empty",
    ),
]
QA_PRODUCTS = [
    pm.MapProductRecord(
        id="mapprod_1",
        product_name="T1 成图",
        interpretation_refs=["interp_h1", "corr_1", "ghost-fault"],
        created_at=FROZEN_NOW,
    ),
]
QA_INTERPRETATIONS = {
    "horizon": [pm.HorizonInterpretationRef(id="interp_h1", name="H1 解释",
                                            horizon_key="H1")],
    "correlation": [pm.CorrelationInterpretationRef(id="corr_1")],
    "fault": [],
}
QA_EMPTY_TABLE = pm.WellTable(id="wt_empty", name="空表", target_horizon="H1")
QA_DOC_NO_CRS = make_doc(
    facies_polygons=[
        {"id": "f1", "properties": {"facies_name": "三角洲"},
         "coordinates": [list(r) for r in SQUARE_RING]},
        {"facies_name": "河流",  # 无 properties → 兜底 facies_name
         "coordinates": [[20.0, 20.0], [24.0, 20.0], [24.0, 24.0],
                         [20.0, 24.0], [20.0, 20.0]]},
    ],
    facies_style={
        "renderer": "categorized",
        "categories": [["三角洲", "#ccc"]],  # 缺 河流 类
    },
    map_crs=None,
)


def qa_project() -> pm.ProjectDocument:
    return make_project(
        docs=[QA_DOC_NO_CRS],
        tables=[QA_EMPTY_TABLE],
        layers=[QA_LAYER_STYLED, QA_LAYER_MATCHED],
        tasks=QA_TASKS,
        products=QA_PRODUCTS,
        interpretations=QA_INTERPRETATIONS,
    )


def add_map_qc(cid: str, project: pm.ProjectDocument, doc_id: str,
               inputs: dict, bind: bool = True) -> None:
    reset_clock()
    frozen_project = project.model_dump(mode="json")
    expect = capture(
        run_map_qc,
        project,
        doc_id,
        map_extent=inputs.get("map_extent"),
        fusion_confidence=inputs.get("fusion_confidence"),
        confidence_threshold=inputs.get("confidence_threshold", 0.5),
        export_report=inputs.get("export_report"),
        bind_active_run=bind,
    )
    if "result" in expect:
        expect = {
            "result": {
                "report": expect["result"].model_dump(mode="json"),
                "project": project.model_dump(mode="json"),
            }
        }
    add(
        cid,
        "qc.run_map_qc",
        {
            "project": frozen_project,
            "map_document_id": doc_id,
            "bind_active_run": bind,
            "inputs": inputs,
            "clock": clock_state(),
        },
        expect,
    )


# 1) all extended inputs absent: CRS/renderer/data-health issues + 3 skips.
add_map_qc("mapqc.all_skip_inputs", qa_project(), "map_doc1", {})

# 2) explicit extent: out-of-bound layer / facies / line features.
# The facies/line extent check only sees features carrying a "geometry" key
# (map_qa_rules._extent_issues reads feature["geometry"]["coordinates"]).
OOB_DOC = make_doc(
    map_crs="EPSG:32650",
    facies_polygons=[
        {"id": "f_in",
         "geometry": {"type": "Polygon", "coordinates": [
             [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0], [1.0, 1.0]]]}},
        {"id": "f_out",
         "geometry": {"type": "Polygon", "coordinates": [
             [[8.0, 8.0], [12.0, 8.0], [12.0, 12.0], [8.0, 12.0], [8.0, 8.0]]]}},
    ],
    line_features=[
        {"id": "l_in", "role": "contour",
         "geometry": {"type": "LineString",
                      "coordinates": [[1.0, 1.0], [2.0, 2.0]]}},
        {"id": "l_out", "role": "contour", "feature_id": "l_out_id",
         "geometry": {"type": "LineString",
                      "coordinates": [[1.0, 1.0], [11.0, 11.0]]}},
    ],
)
OOB_LAYERS = [
    pm.UserVectorLayer(
        id="uvl_oob",
        name="越界层",
        crs="EPSG:32650",
        features=[
            pm.UserVectorFeature(id="f_ok",
                                 geometry={"type": "Point",
                                           "coordinates": [2.0, 2.0]}),
            pm.UserVectorFeature(id="f_bad",
                                 geometry={"type": "LineString",
                                           "coordinates": [[0.0, 0.0],
                                                           [-4.5, 20.25]]}),
        ],
    ),
]
add_map_qc(
    "mapqc.explicit_extent",
    make_project(docs=[OOB_DOC], layers=OOB_LAYERS),
    "map_doc1",
    {"map_extent": [0.0, 0.0, 10.0, 10.0]},
)

# 3) view_state.extent fallback (no explicit map_extent).
VIEW_DOC = make_doc(
    map_crs="EPSG:32650",
    view_state={"extent": [0.0, 0.0, 5.0, 5.0], "zoom": 4},
    line_features=[
        {"id": "l_out", "role": "contour",
         "geometry": {"type": "LineString",
                      "coordinates": [[0.0, 0.0], [6.5, 0.0]]}},
    ],
)
add_map_qc(
    "mapqc.view_state_extent",
    make_project(docs=[VIEW_DOC]),
    "map_doc1",
    {},
)

# 4) fusion confidence + custom threshold + degraded export, all present.
add_map_qc(
    "mapqc.confidence_and_export",
    make_project(docs=[make_doc(map_crs="EPSG:32650")]),
    "map_doc1",
    {
        "map_extent": [0.0, 0.0, 10.0, 10.0],
        "fusion_confidence": {"min": 0.42, "mean": 0.61},
        "confidence_threshold": 0.5,
        "export_report": {
            "engine": "qgis",
            "degraded": True,
            "degraded_reason": "QGIS 布局引擎不可用",
        },
    },
)
add_map_qc(
    "mapqc.confidence_above_threshold",
    make_project(docs=[make_doc(map_crs="EPSG:32650")]),
    "map_doc1",
    {"fusion_confidence": {"min": 0.83, "mean": 0.91},
     "export_report": {"engine": "qgis", "degraded": False}},
)
add_map_qc(
    "mapqc.composer_fallback_no_reason",
    make_project(docs=[make_doc(map_crs="EPSG:32650")]),
    "map_doc1",
    {"export_report": {"engine": "composer_fallback"}},
)
add_map_qc(
    "mapqc.confidence_mean_null",
    make_project(docs=[make_doc(map_crs="EPSG:32650")]),
    "map_doc1",
    {"fusion_confidence": {"min": 0.1, "mean": None},
     "confidence_threshold": 0.75},
)
add_map_qc(
    "mapqc.empty_confidence_object",
    make_project(docs=[make_doc(map_crs="EPSG:32650")]),
    "map_doc1",
    {"fusion_confidence": {}, "export_report": {}},
)

# 5) upsert over an existing basic report (id stability + run binding).
MAP_UPSERT_PROJECT = make_project(
    docs=[QA_DOC_NO_CRS],
    tables=[QA_EMPTY_TABLE],
    layers=[QA_LAYER_STYLED, QA_LAYER_MATCHED],
    tasks=QA_TASKS,
    products=QA_PRODUCTS,
    interpretations=QA_INTERPRETATIONS,
    runs=[make_run("run_1", "编译")],
    reports=[make_report("qc_map_prev", "map_doc1")],
)
add_map_qc("mapqc.upsert_reuse_id", MAP_UPSERT_PROJECT, "map_doc1", {})

# 6) unknown document id raises.
add_map_qc("mapqc.unknown_doc", make_project(docs=[make_doc()]), "map_ghost", {})

# ------------------------------------------ collect_extended_qc_issues face

def add_collect(cid: str, project: pm.ProjectDocument, document, inputs: dict,
                doc_id: str = "map_doc1") -> None:
    frozen_project = project.model_dump(mode="json")
    expect = capture(
        collect_extended_qc_issues,
        project,
        project.paleomap_documents[0] if document is None else document,
        map_extent=inputs.get("map_extent"),
        fusion_confidence=inputs.get("fusion_confidence"),
        confidence_threshold=inputs.get("confidence_threshold", 0.5),
        export_report=inputs.get("export_report"),
    )
    frozen_doc = (
        project.paleomap_documents[0] if document is None else document
    ).model_dump(mode="json")
    add(
        cid,
        "mapqa.collect_extended_qc_issues",
        {"project": frozen_project, "document": frozen_doc, "inputs": inputs,
         "map_document_id": doc_id},
        expect,
    )


add_collect("collect.all_groups", qa_project(), None, {})
add_collect(
    "collect.extent_and_confidence",
    make_project(docs=[OOB_DOC], layers=OOB_LAYERS),
    None,
    {"map_extent": [0.0, 0.0, 10.0, 10.0],
     "fusion_confidence": {"min": 0.25, "mean": 0.55},
     "export_report": {"engine": "fallback", "degraded_reason": "测试"}},
)

# ------------------------------------------- extended_rule_coverage face

for cid, inputs in [
    ("all_absent", {}),
    ("all_present", {"map_extent": [0.0, 0.0, 1.0, 1.0],
                     "fusion_confidence": {"min": 0.9, "mean": 0.95},
                     "export_report": {"engine": "qgis"}}),
    ("extent_only", {"map_extent": [0.0, 0.0, 1.0, 1.0]}),
    ("empty_confidence_counts_present", {"fusion_confidence": {}}),
]:
    add(
        f"coverage.{cid}",
        "mapqa.extended_rule_coverage",
        {"inputs": inputs},
        capture(
            extended_rule_coverage,
            map_extent=inputs.get("map_extent"),
            fusion_confidence=inputs.get("fusion_confidence"),
            export_report=inputs.get("export_report"),
        ),
    )

# -------------------------------------------- composition_qa_issues face

from paleo_workbench.mapping.composer.models import (  # noqa: E402
    ComposerElement,
    ElementType,
    MapCompositionDocument,
)


def add_composition(cid: str, composition: MapCompositionDocument) -> None:
    expect = capture(composition_qa_issues, composition)
    add(
        f"composition.{cid}",
        "mapqa.composition_qa_issues",
        {"composition": composition.to_dict()},
        expect,
    )


EMPTY_COMP = MapCompositionDocument(id="comp_empty", title="空合成页")
add_composition("empty", EMPTY_COMP)

TITLE_COMP = MapCompositionDocument(id="comp_title", title="只有标题")
TITLE_COMP.add_element(ComposerElement("el_title", ElementType.TITLE, 0, 0, 10, 5))
add_composition("title_only", TITLE_COMP)

FULL_COMP = MapCompositionDocument(id="comp_full", title="齐备")
FULL_COMP.add_element(ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180, 150))
FULL_COMP.add_element(ComposerElement("el_legend", ElementType.LEGEND, 192, 12, 60, 60))
FULL_COMP.add_element(ComposerElement("el_scale", ElementType.SCALE_BAR, 192, 150, 60, 10))
add_composition("full_furniture", FULL_COMP)

HIDDEN_COMP = MapCompositionDocument(id="comp_hidden", title="隐藏主图")
HIDDEN_COMP.add_element(ComposerElement("el_map", ElementType.MAIN_MAP, 8, 12, 180, 150, visible=False))
HIDDEN_COMP.add_element(ComposerElement("el_legend", ElementType.LEGEND, 192, 12, 60, 60))
HIDDEN_COMP.add_element(ComposerElement("el_scale", ElementType.SCALE_BAR, 192, 150, 60, 10))
add_composition("hidden_main_map", HIDDEN_COMP)

# ------------------------------------------------------------------- write

FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {len(cases)} cases to {FIXTURE}")
