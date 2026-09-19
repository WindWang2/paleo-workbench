#!/usr/bin/env python3
"""Freeze the conv-31 catalog domain oracles from the REAL Python modules.

Every expectation below is derived from real module output — governance /
intermediate_policy / port_roles / model_gates / checksum / lineage_graph /
impact / explain / sources / queries / tags / migration / audit / the V11
policy core — over a deterministic scenario document built through the real
DataCatalogService on a temp project. Ids and timestamps are frozen
as-generated; the C++ replay consumes them verbatim.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from paleo_workbench.catalog import (
    audit as py_audit,
    governance as py_governance,
    impact as py_impact,
    intermediate_policy as py_policy,
    lineage_graph as py_lineage,
    model_gates as py_model_gates,
    port_roles as py_port_roles,
    queries as py_queries,
    sources as py_sources,
    tags as py_tags,
)
from paleo_workbench.catalog import service as py_service_mod
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataStage,
    DataVersion,
    Tag,
)
from paleo_workbench.catalog.checksum import sha256_file, sha256_text
from paleo_workbench.catalog.migration import migrate_resources
from paleo_workbench.project.models import ResourceItem

OUT = REPO / "tests" / "cpp" / "data" / "fixtures" / "catalog_domain" / "oracle.json"


def build_service(tmp: Path):
    project = tmp / "demo.paleo.json"
    project.write_text("{}", encoding="utf-8")
    service = py_service_mod.DataCatalogService.open(project, sweep_temp=False)
    doc = CatalogDocument()
    # Scenario: asset A raw v1→v2 (evolution), derived D(v3) on v1;
    # asset B raw v5 external missing; dangling parent v9; run r1 typed.
    doc.assets.extend([
        DataAsset(id="asset_a", name="Seismic A", type="seismic",
                  current_version_id="ver_a2"),
        DataAsset(id="asset_b", name="Log B", type="well_log",
                  current_version_id="ver_b5"),
        DataAsset(id="asset_d", name="Derived D", type="seismic_attribute",
                  current_version_id="ver_d3"),
    ])
    doc.versions.extend([
        DataVersion(id="ver_a1", asset_id="asset_a", version_number=1,
                    stage=DataStage.RAW, managed=True,
                    path="demo.artifacts/raw/asset_a/ver_a1/a.sgy",
                    sha256="00" * 32, created_at="2024-01-01T00:00:00+00:00"),
        DataVersion(id="ver_a2", asset_id="asset_a", version_number=2,
                    stage=DataStage.RAW, managed=True,
                    path="demo.artifacts/raw/asset_a/ver_a2/a.sgy",
                    sha256="11" * 32, created_at="2024-01-02T00:00:00+00:00"),
        DataVersion(id="ver_b5", asset_id="asset_b", version_number=5,
                    stage=DataStage.RAW, managed=False,
                    path=str(tmp / "gone.las"),
                    sha256="22" * 32, created_at="2024-01-03T00:00:00+00:00"),
        DataVersion(id="ver_d3", asset_id="asset_d", version_number=1,
                    stage=DataStage.DERIVED, managed=True,
                    path="demo.artifacts/derived/asset_d/ver_d3/d.npy",
                    sha256="33" * 32, run_id="run_r1",
                    parent_version_ids=["ver_a1", "ver_missing"],
                    created_at="2024-01-04T00:00:00+00:00"),
        DataVersion(id="ver_e4", asset_id="asset_d", version_number=2,
                    stage=DataStage.OUTPUT, managed=True,
                    path="demo.artifacts/outputs/asset_d/ver_e4/e.png",
                    run_id="run_r1", parent_version_ids=["ver_d3"],
                    created_at="2024-01-05T00:00:00+00:00",
                    metadata={"pin": {"reason": "保图", "pinned_at": "2024-01-06T00:00:00+00:00"}}),
    ])
    doc.runs.append(DataRun(
        id="run_r1", operation="factor_map",
        input_version_ids=["ver_a1"], output_version_ids=["ver_d3", "ver_e4"],
        input_ports=[{"direction": "input", "role": "seismic_volume",
                      "version_id": "ver_a1", "ordinal": 0, "required": True,
                      "entity_type": "", "entity_id": "", "note": ""}],
        parameters={"factor": "paleo"}, generator="pwb 0.2",
        status="completed", created_at="2024-01-04T00:00:00+00:00"))
    doc.tags.append(Tag(id="tag_t1", name="qc", display_name="QC"))
    doc.asset_tags["asset_a"] = ["tag_t1"]
    doc.version_tags["ver_d3"] = ["tag_t1"]
    service.document = doc
    service._invalidate_maps()
    return service, tmp


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="catalog-domain-oracle-"))
    service, tmp = build_service(tmp)

    oracle: dict = {}

    # ---- governance ----
    gov_cases = [
        ("discipline", "welllog"), ("discipline", "  地层对比 "),
        ("confidence", "H"), ("review_status", "已通过"),
        ("source", " 野外  2023  队 "), ("confidence", "super"),
        ("bogus", "x"),
    ]
    gov_out = []
    for key, value in gov_cases:
        try:
            gov_out.append({"key": key, "value": value,
                            "ok": py_governance.normalize_governance_value(key, value)})
        except ValueError as exc:
            gov_out.append({"key": key, "value": value, "ok": None, "err": str(exc)})
    oracle["governance_normalize"] = gov_out
    try:
        py_governance.normalize_governance_patch({"format": "x"})
        oracle["governance_patch_reserved"] = None
    except ValueError as exc:
        oracle["governance_patch_reserved"] = str(exc)
    oracle["governance_display_rows"] = [
        list(row) for row in py_governance.governance_display_rows(
            {"source": "野外", "discipline": "seismic", "confidence": "high",
             "creator": "", "format": "sgy"})]
    oracle["governance_keys"] = list(py_governance.GOVERNANCE_KEYS)

    # ---- artifact policy ----
    oracle["artifact_policy_table"] = {
        kind: {"artifact_class": p.artifact_class, "must_register": p.must_register,
               "data_stage": p.data_stage.value if p.data_stage else None,
               "retention_class": p.retention_class, "rationale": p.rationale}
        for kind, p in py_policy.KNOWN_ARTIFACT_POLICIES.items()}
    fallback = py_policy.policy_for("brand_new_kind")
    oracle["artifact_policy_fallback"] = {
        "artifact_class": fallback.artifact_class,
        "must_register": fallback.must_register,
        "data_stage": fallback.data_stage.value if fallback.data_stage else None,
        "retention_class": fallback.retention_class,
        "rationale": fallback.rationale}
    oracle["artifact_policy_registered"] = [
        py_policy.is_registered_kind(k) for k in ("map_product", "brand_new_kind", " map_product ")]

    # ---- port roles ----
    oracle["port_roles_display"] = {
        role: py_port_roles.display_for(role)
        for role in ("well_logs", "sonic", "faults", "manual_edit", "foreign_role", "")}

    # ---- model gates ----
    class FakeVersion:
        def __init__(self, **kw):
            self.demo_only = kw.get("demo_only", False)
            self.metadata = kw.get("metadata", {})
            self.input_schema = kw.get("input_schema", {})

    class FakeModel:
        def __init__(self, **kw):
            self.provider = kw.get("provider", "")
            self.model_type = kw.get("model_type", "")
            self.metadata = kw.get("metadata", {})

    class FakeService:
        def __init__(self, model, version, error=None):
            self._m, self._v, self._e = model, version, error
        def get_model(self, _mid):
            if self._e: raise KeyError(self._e)
            return self._m
        def get_model_version(self, _mid, _mv):
            if self._e: raise KeyError(self._e)
            return self._v

    gate_cases = [
        ("ok", FakeModel(provider="pwb", model_type="xgboost"),
         FakeVersion(input_schema={"curves": []})),
        ("demo", FakeModel(provider="Demo", model_type="xgboost"), FakeVersion()),
        ("local", FakeModel(provider="local-asset", model_type="xgboost"), FakeVersion()),
        ("heuristic", FakeModel(provider="pwb", model_type="HEURISTIC"), FakeVersion()),
        ("demo_only", FakeModel(), FakeVersion(demo_only=True)),
        ("sci_false", FakeModel(metadata={"scientific": False}), FakeVersion()),
        ("ver_sci_false", FakeModel(), FakeVersion(metadata={"scientific": False})),
        ("no_schema", FakeModel(), FakeVersion()),
        ("no_schema_read", FakeModel(), FakeVersion()),
        ("lookup_error", FakeModel(), FakeVersion()),
    ]
    oracle["model_gates"] = []
    for name, model, version in gate_cases:
        error = "get_model failed: no row" if name == "lookup_error" else None
        ok, reason = py_model_gates.can_promote_to_production(
            FakeService(model, version, error), "m", "v1",
            require_input_schema=(name != "no_schema_read"))
        oracle["model_gates"].append({"case": name, "ok": ok, "reason": reason})

    # ---- checksum ----
    payload = tmp / "hash.bin"
    payload.write_bytes(b"paleo\x00workbench" * 10000)
    oracle["checksum_file"] = hashlib.sha256(payload.read_bytes()).hexdigest()
    oracle["checksum_file_streamed"] = sha256_file(payload, chunk_size=64)
    oracle["checksum_text"] = [sha256_text("a\r\nb\rc\nd"), sha256_text("国际\r\n化")]

    # ---- lineage ----
    summaries = py_lineage.compute_summaries(service)
    oracle["lineage_summaries"] = summaries
    chain = py_lineage.build_lineage_chain(service, "ver_e4", direction="ancestors")

    def node_json(node):
        return {"version_id": node.version_id, "asset_name": node.asset_name,
                "depth": node.depth, "tags": node.tags,
                "run_operation": node.run_operation,
                "children": [node_json(c) for c in node.children]}
    oracle["lineage_chain_ver_e4"] = {
        "node_count": chain.node_count, "truncated": chain.truncated,
        "root": node_json(chain.root)}
    try:
        py_lineage.build_lineage_chain(service, "ver_e4", direction="sideways")
        oracle["lineage_bad_direction"] = None
    except ValueError as exc:
        oracle["lineage_bad_direction"] = str(exc)

    # ---- impact ----
    impact = py_impact.ImpactService(service)
    def stale_json(items):
        return [{"version_id": i.version_id, "direct": i.direct,
                 "nearest": list(i.nearest_changed_ancestor or ()),
                 "reason": i.reason, "pinned": i.pinned,
                 "classification": i.classification,
                 "reproducible": i.reproducible, "stage": i.stage} for i in items]
    oracle["impact_downstream"] = stale_json(impact.downstream_stale())
    oracle["impact_downstream_trashed"] = stale_json(
        impact.downstream_stale(include_trashed=True))
    oracle["impact_is_stale"] = list(impact.is_stale("ver_d3"))
    up = impact.upstream_impact("ver_e4")
    oracle["impact_upstream"] = {
        "ancestor_version_ids": up.ancestor_version_ids,
        "ancestor_asset_ids": up.ancestor_asset_ids,
        "runs_involved": up.runs_involved,
        "missing_ancestors": up.missing_ancestors,
        "trashed_ancestors": up.trashed_ancestors}
    dele = impact.delete_impact(version_id="ver_a1")
    oracle["impact_delete"] = {
        "target_version_ids": dele.target_version_ids,
        "target_asset_ids": dele.target_asset_ids,
        "broken_lineage_edges": dele.broken_lineage_edges,
        "runs_consuming": dele.runs_consuming, "runs_producing": dele.runs_producing,
        "live_descendants": stale_json(dele.live_descendants),
        "cascade_advice": dele.cascade_advice}

    # ---- v11 policy ----
    oracle["v11_ports_for_run"] = {
        "input": [p.model_dump() for p in
                  py_service_mod.DataCatalogService.ports_for_run(service, "run_r1")["input"]],
        "output": [p.model_dump() for p in
                   py_service_mod.DataCatalogService.ports_for_run(service, "run_r1")["output"]]}
    oracle["v11_eligibility_ver_d3"] = service.cleanup_eligibility("ver_d3")
    oracle["v11_eligibility_ver_e4"] = service.cleanup_eligibility("ver_e4")
    oracle["v11_lifecycle_ver_e4"] = service.version_lifecycle_status("ver_e4")
    oracle["v11_retention"] = [service.retention_class(v) for v in
                               ("ver_a1", "ver_d3", "ver_e4")]
    oracle["v11_migrate_ports"] = service.migrate_run_ports()
    oracle["v11_ports_after_backfill"] = [
        p.model_dump() for p in service.document.runs[0].output_ports]

    # ---- queries ----
    # Force the canonical document-scan path: the hand-built document was
    # never synced into the sqlite index (batch_depth trips the staleness
    # guard exactly like an in-flight batch_save, #1139).
    service._batch_depth = 1
    try:
        oracle["queries_find_assets_by_tag"] = py_tags.find_assets_by_tag(service, "QC")
    finally:
        service._batch_depth = 0
    integrity = py_queries.verify_integrity(service, version_id="ver_b5")
    oracle["queries_integrity_ver_b5"] = integrity.statuses

    # ---- sources ----
    report = py_sources.find_missing_sources(service, include_managed=True)
    oracle["sources_missing"] = [
        {"version_id": e.version_id, "relinkable": e.relinkable,
         "recorded_path": e.recorded_path, "scanned": report.scanned}
        for e in report.entries]

    # ---- tags (mutations through the real service + sqlite) ----
    tag = py_tags.add_tag(service, "  实验  Zone ", asset_id="asset_b")
    oracle["tags_add"] = {"id": tag.id, "name": tag.name, "display": tag.display_name}
    py_tags.bulk_add_tag(service, "batch", version_ids=["ver_a1", "ver_b5"])
    renamed = py_tags.rename_tag(service, "qc", "quality control")
    oracle["tags_rename"] = {"name": renamed.name, "display": renamed.display_name}
    oracle["tags_usage_names"] = {
        t["name"]: [t["assets"], t["versions"]] for t in py_tags.tag_usage(service).values()}
    py_tags.remove_tag(service, "batch", version_id="ver_a1")
    pruned = py_tags.prune_unused_tags(service)
    oracle["tags_pruned"] = [t.name for t in pruned]
    oracle["tags_search"] = [t.name for t in py_tags.search_tags(service, "qua")]

    # ---- migration ----
    legacy = [
        ResourceItem(id="res_1", name="Old seismic", type="seismic",
                     path="data/old.sgy", format="sgy", checksum=None,
                     tags=["legacy"], parsed_summary={"path": str(tmp / "old.sgy")},
                     status="active"),
        ResourceItem(id="asset_a", name="dup", type="x", path="x", format="",
                     checksum=None, tags=[], parsed_summary={}),
        ResourceItem(id="../evil", name="evil", type="x", path="y", format="",
                     checksum=None, tags=[], parsed_summary={}),
    ]
    (tmp / "data").mkdir(exist_ok=True)
    (tmp / "data" / "old.sgy").write_bytes(b"legacy")
    doc2 = CatalogDocument()
    doc2.assets.append(DataAsset(id="asset_a", name="Seismic A", type="seismic"))
    stamp = iter(["2024-02-01T00:00:00+00:00"] * 10)
    report2 = migrate_resources(legacy, tmp / "demo.paleo.json", doc2,
                                now=lambda: next(stamp))
    ev = [v for v in doc2.versions if v.asset_id != "asset_a"]
    oracle["migration"] = {
        "migrated": report2.migrated_count, "skipped": report2.skipped_count,
        "warnings": report2.warnings,
        "versions": [{"id": v.id, "asset": v.asset_id, "managed": v.managed,
                      "path": v.path, "stage": v.stage.value,
                      "has_stat": "external_stat" in v.metadata}
                     for v in ev],
        "assets": [{"id": a.id, "legacy": a.legacy_resource_id}
                   for a in doc2.assets if a.id != "asset_a"]}

    # ---- audit ----
    audit_report = py_audit.audit_catalog(service, deep=False)
    oracle["audit"] = {
        "checked": audit_report.checked,
        "issues": [{"kind": i.kind, "severity": i.severity, "ref_id": i.ref_id,
                    "detail": i.detail} for i in audit_report.issues],
        "ok": audit_report.ok}

    # ---- explain ----
    from paleo_workbench.catalog.explain import ExplainService
    explanation = ExplainService(service).explain_version("ver_e4")
    oracle["explain_ver_e4"] = explanation.__dict__

    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(oracle, ensure_ascii=False, indent=1, sort_keys=True)
    # Absolute scenario paths become {ROOT} placeholders so the C++ replay
    # can substitute its own temp root.
    text = text.replace(str(tmp), "{ROOT}")
    OUT.write_text(text, encoding="utf-8")
    print(f"oracle -> {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
