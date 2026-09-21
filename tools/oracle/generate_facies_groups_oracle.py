#!/usr/bin/env python3
"""CONV-35 — freeze geojson_layers (facies product grouping) behavior from
the REAL paleo_workbench/resources/geojson_layers.py.

Fixture: libs/ui_data_core/ui_data_core_tests/fixtures/
facies_groups_oracle.json — replayed by ui_data_core.facies_groups.

ResourceItem is serialized as a plain dict (name/path/type/format/tags/
parsed_summary/artifact_role); the C++ side reconstructs the POD.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.project.models import ResourceItem  # noqa: E402
from paleo_workbench.resources import geojson_layers as gl  # noqa: E402


def res(name, path=None, rtype="geojson", fmt="geojson", tags=None,
        summary=None, artifact_role=None, rid=None):
    return ResourceItem(
        id=rid or f"res_{name}", name=name, path=path if path is not None else name,
        type=rtype, format=fmt, tags=tags or [],
        parsed_summary=summary or {}, artifact_role=artifact_role)


def dump_res(r: ResourceItem) -> dict:
    return {
        "name": r.name, "path": r.path, "type": r.type, "format": r.format,
        "tags": r.tags, "parsed_summary": r.parsed_summary,
        "artifact_role": r.artifact_role,
    }


def res_from(d: dict) -> ResourceItem:
    return res(d["name"], d.get("path"), d.get("type", "geojson"),
               d.get("format", "geojson"), d.get("tags"),
               d.get("parsed_summary"), d.get("artifact_role"),
               d.get("id"))


def freeze_normalize() -> list[dict]:
    cases = []
    for value in ("facies", "Facies", " 微相 ", "MICRO-FACIES", "sub_facies",
                  "亚相", "相图", " 相", "", None, 0, "unknown", "sub",
                  "MICROFACIES", "Facies ", "micro facies", "subfacies_",
                  5, True, ["facies"], {"x": 1}):
        out = gl.normalize_facies_layer_role(value)
        cases.append({"value": value, "role": out})
    return cases


def freeze_from_name() -> list[dict]:
    cases = []
    for name in ("facies.geojson", "subfacies.geojson", "microfacies.geojson",
                 "盆地相图.json", "洼陷亚相.geojson", "洼陷微相.geojson",
                 "Sub_Facies.geojson", "MICRO-facies.geojson",
                 "product_facies_result.geojson", "plain.geojson",
                 "Facies_Subfacies.geojson", "微相亚相.geojson",
                 "dir/洼陷微相.geojson", "nofacieslayer.geojson",
                 "facies.GEOJSON", "微相.geojson", "相图_backup.geojson"):
        cases.append({
            "filename": name,
            "role": gl.facies_layer_role_from_name(name),
            "summary": gl.facies_layer_summary_from_name(name),
        })
    return cases


def freeze_doc_summary() -> list[dict]:
    cases = []

    def emit(name, payload, filename):
        cases.append({"name": name, "payload": payload, "filename": filename,
                      "summary": gl.geojson_document_summary(payload, filename)})

    emit("not_object", [1, 2], "x.geojson")
    emit("not_fc", {"type": "Feature"}, "x.geojson")
    emit("fc_no_features", {"type": "FeatureCollection"}, "x.geojson")
    emit("fc_features_not_list",
         {"type": "FeatureCollection", "features": {}}, "x.geojson")
    emit("basic", {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon"}, "properties": {}},
            {"type": "Feature", "geometry": {"type": "Point"}, "properties": {}},
            {"type": "Feature", "geometry": None, "properties": {}},
            "not-a-dict",
        ]}, "plain.geojson")
    emit("geometry_types_sorted", {
        "type": "FeatureCollection",
        "features": [
            {"geometry": {"type": "Polygon"}},
            {"geometry": {"type": "LineString"}},
            {"geometry": {"type": "Polygon"}},
            {"geometry": {}},
        ]}, "x.geojson")
    emit("role_from_metadata", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"layer_role": "subfacies"}}, "plain.geojson")
    emit("role_from_payload_key", {
        "type": "FeatureCollection", "features": [],
        "facies_level": "microfacies"}, "plain.geojson")
    emit("role_metadata_beats_filename", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"level": "microfacies"}}, "facies.geojson")
    emit("role_from_filename", {
        "type": "FeatureCollection", "features": []}, "洼陷亚相.geojson")
    emit("role_key_order", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"facies_level": "subfacies"},
        "level": "microfacies"}, "plain.geojson")
    emit("role_bad_then_good_key", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"layer_role": "garbage", "facies_level": "亚相"}},
        "plain.geojson")
    emit("product_id", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"product_id": "  prod-42  "}}, "facies.geojson")
    emit("product_id_payload", {
        "type": "FeatureCollection", "features": [],
        "result_id": "res-9"}, "plain.geojson")
    emit("product_id_empty_skipped", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"product_id": "   "}}, "plain.geojson")
    emit("metadata_not_dict", {
        "type": "FeatureCollection", "features": [],
        "metadata": "oops"}, "facies.geojson")
    emit("metadata_null_value_falls_to_payload", {
        "type": "FeatureCollection", "features": [],
        "metadata": {"layer_role": None}, "level": "facies"}, "plain.geojson")
    return cases


def freeze_grouping() -> list[dict]:
    cases = []

    def emit(name, added, existing=None):
        added_res = [res_from(d) for d in added]
        existing_res = [res_from(d) for d in (existing or [])]
        warnings = gl.annotate_facies_product_groups(added_res, existing_res)
        cases.append({
            "name": name,
            "added": added,
            "existing": existing or [],
            "warnings": warnings,
            "after": {
                "added": [dump_res(r) for r in added_res],
                "existing": [dump_res(r) for r in existing_res],
            },
        })

    emit("standalone_no_role", [
        dict(name="plain.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("complete_group_by_filename", [
        dict(name="facies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="microfacies.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("missing_microfacies", [
        dict(name="facies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("duplicate_role", [
        dict(name="facies_a.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="facies_b.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="microfacies.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("missing_and_duplicate", [
        dict(name="facies_a.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="facies_b.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("same_product_id_explicit", [
        dict(name="a.geojson",
             parsed_summary={"geojson_valid": True,
                             "geojson_layer_role": "facies",
                             "facies_product_source_id": "P1"}),
        dict(name="b.geojson",
             parsed_summary={"geojson_valid": True,
                             "geojson_layer_role": "subfacies",
                             "facies_product_source_id": "P1"}),
        dict(name="c.geojson",
             parsed_summary={"geojson_valid": True,
                             "geojson_layer_role": "microfacies",
                             "facies_product_source_id": "P1"}),
    ])
    emit("parse_failure_never_promoted", [
        dict(name="facies.geojson",
             parsed_summary={"geojson_valid": False}),
        dict(name="subfacies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="microfacies.geojson", parsed_summary={"geojson_valid": True}),
    ])
    emit("existing_completes_added", [
        dict(name="microfacies.geojson",
             parsed_summary={"geojson_valid": True}),
    ], existing=[
        dict(name="facies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson",
             parsed_summary={"geojson_valid": True}),
    ])
    emit("incomplete_existing_no_warning", [], existing=[
        dict(name="facies.geojson", parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson",
             parsed_summary={"geojson_valid": True}),
    ])
    emit("non_geojson_ignored", [
        dict(name="facies.geojson", type="vector",
             parsed_summary={"geojson_valid": True}),
        dict(name="facies2.geojson", format="txt",
             parsed_summary={"geojson_valid": True}),
    ])
    emit("subdir_scopes_group", [
        dict(name="facies.geojson", path="a/facies.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="facies.geojson", path="b/facies.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson", path="a/subfacies.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="microfacies.geojson", path="a/microfacies.geojson",
             parsed_summary={"geojson_valid": True}),
    ])
    emit("stem_words_stripped", [
        dict(name="盆地facies图层.geojson", path="p/盆地facies图层.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="盆地亚相图.geojson", path="p/盆地亚相图.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="盆地微相.geojson", path="p/盆地微相.geojson",
             parsed_summary={"geojson_valid": True}),
    ])
    emit("preannotated_group_id", [
        dict(name="x.geojson",
             parsed_summary={"geojson_valid": True,
                             "geojson_layer_role": "facies",
                             "facies_product_group_id": "facies_product_FIXED"}),
    ])
    emit("tags_rewritten", [
        dict(name="facies.geojson", tags=["input", "custom", "reference"],
             parsed_summary={"geojson_valid": True}),
        dict(name="subfacies.geojson", tags=["custom"],
             parsed_summary={"geojson_valid": True}),
        dict(name="microfacies.geojson", tags=["output", "other"],
             parsed_summary={"geojson_valid": True}),
    ])
    return cases


def freeze_members() -> list[dict]:
    cases = []

    def emit(name, clicked, pool):
        pool_res = [res_from(d) for d in pool]
        clicked_res = res_from(clicked)
        members = gl.facies_group_members(clicked_res, pool_res)
        cases.append({
            "name": name, "clicked": clicked, "pool": pool,
            "member_names": [r.name for r in members],
        })

    trio_a = [
        dict(name="microfacies.geojson", path="a/microfacies.geojson",
             parsed_summary={"geojson_valid": True,
                             "facies_product_group_id": "facies_product_G"}),
        dict(name="facies.geojson", path="a/facies.geojson",
             parsed_summary={"geojson_valid": True,
                             "facies_product_group_id": "facies_product_G"}),
        dict(name="subfacies.geojson", path="a/subfacies.geojson",
             parsed_summary={"geojson_valid": True,
                             "facies_product_group_id": "facies_product_G"}),
        dict(name="unrelated.geojson", path="a/unrelated.geojson",
             parsed_summary={"geojson_valid": True}),
        dict(name="facies.geojson", path="b/facies.geojson",
             parsed_summary={"geojson_valid": True}),
    ]
    emit("click_microfacies_orders_facies_first",
         dict(name="microfacies.geojson", path="a/microfacies.geojson",
              parsed_summary={"geojson_valid": True,
                              "facies_product_group_id": "facies_product_G"}),
         trio_a)
    emit("click_unrelated_returns_alone",
         dict(name="unrelated.geojson", path="a/unrelated.geojson",
              parsed_summary={"geojson_valid": True}),
         trio_a)
    emit("no_role_clicked_returns_alone",
         dict(name="x.geojson", parsed_summary={}),
         trio_a)
    emit("digest_group_by_path",
         dict(name="facies.geojson", path="z/facies.geojson",
              parsed_summary={"geojson_valid": True}),
         [dict(name="facies.geojson", path="z/facies.geojson",
               parsed_summary={"geojson_valid": True})] + trio_a[:4])
    return cases


def main() -> int:
    oracle = {
        "schema": "pwb.facies_groups_oracle/1",
        "source": "paleo_workbench/resources/geojson_layers.py",
        "normalize": freeze_normalize(),
        "from_name": freeze_from_name(),
        "doc_summary": freeze_doc_summary(),
        "grouping": freeze_grouping(),
        "members": freeze_members(),
    }
    out_dir = (REPO_ROOT / "libs" / "ui_data_core" / "ui_data_core_tests" /
               "fixtures")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "facies_groups_oracle.json"
    out_path.write_text(json.dumps(oracle, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    total = sum(len(oracle[k]) for k in
                ("normalize", "from_name", "doc_summary", "grouping",
                 "members"))
    print(f"frozen {out_path} ({total} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
