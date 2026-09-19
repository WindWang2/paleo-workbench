#!/usr/bin/env python3
"""Oracle fixture generator for the workflow_interpretation constraint
product + interpretation revisions (CONV-32, I6).

Imports the REAL implementations (paleo_workbench.workflow.interpretation.
constraint_product / revision, layer_roles + constraint_capabilities
vocabularies, workflow.constraint_versions commit chain) and freezes their
outputs to JSON so the C++ port in libs/workflow_interpretation can be
verified against the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_interpretation_constraint_fixtures.py

15 case groups (see main()): geo->engine kind mapping (string form, invalid,
strip/lower), all-10-kinds convergence, CRS mismatch byte-exact message, CRS
honest notes (4 variants + context prefix + whitespace), group projection
without catalog (kinds/engine order, strength/confidence rows, n_points),
empty catalog (never-committed draft), invalid strength/confidence, real
catalog commit -> committed+current, post-commit edit -> uncommitted-edits
validity, malformed coordinates -> hash failure tolerance, revision chain
(first / unchanged-None / second parent link + deltas + order + latest),
fingerprint stability (same content diff layer ids, 9dp rounding, int coords,
attributes + feature_id seam), from_dict roundtrip + coercions, revision
summary (empty + populated), integrated domain link (revision_ids growth,
phase1_draft touches nothing).

Determinism: revision ids are injected by patching sys.modules["uuid"]
around record_interpretation_revision (the module does `import uuid` inside
the function, so each call re-resolves the fake module). Catalog version ids
are uuid-based and therefore frozen as null sentinels (the C++ test checks
non-empty and compares everything else byte-exact).
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.mapping_workspace.layer_roles import ConstraintKind  # noqa: E402
from paleo_workbench.project.models import (  # noqa: E402
    ConstraintLayers,
    ConstraintLine,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
)
from paleo_workbench.workflow.constraint_versions import (  # noqa: E402
    commit_constraint_group,
    constraint_group_content_hash,
)
from paleo_workbench.workflow.interpretation.constraint_product import (  # noqa: E402
    assert_constraints_crs_compatible,
    constraint_product_for_group,
    constraint_products_for_document,
    to_engine_kind,
)
from paleo_workbench.workflow.interpretation.integrated_interpretation import (  # noqa: E402
    create_integrated_interpretation,
)
from paleo_workbench.workflow.interpretation.revision import (  # noqa: E402
    InterpretationRevision,
    layer_content_fingerprint,
    latest_revision_for_layer,
    record_interpretation_revision,
    revision_summary,
    revisions_for_layer,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_interpretation"
    / "workflow_interpretation_tests"
    / "fixtures"
    / "workflow_interpretation_constraint_oracle.json"
)


# ---------------------------------------------------------------- seam views
# The Json views handed to the C++ port — exactly the attributes the Python
# side reads off the model objects (see constraint_versions._canonical_line
# and constraint_product._line_summary).


def line_view(line: object) -> dict:
    view = {
        "id": str(getattr(line, "id", "") or ""),
        "name": str(getattr(line, "name", "") or ""),
        "role": str(getattr(line, "role", "") or ""),
        "active": bool(getattr(line, "active", True)),
        "target_horizon": str(getattr(line, "target_horizon", "") or ""),
        "coordinates": [list(p) for p in (getattr(line, "coordinates", None) or [])],
        "properties": dict(getattr(line, "properties", None) or {}),
    }
    for key in ("azimuth_deg", "semi_major", "semi_minor"):
        value = getattr(line, key, None)
        if value is not None:
            view[key] = float(value)
    return view


def group_view(group: object) -> dict:
    return {
        "id": str(getattr(group, "id", "") or ""),
        "name": str(getattr(group, "name", "") or ""),
        "target_horizon": str(getattr(group, "target_horizon", "") or ""),
        "crs": getattr(group, "crs", None),
        "lines": [line_view(l) for l in (getattr(group, "lines", None) or [])],
    }


def document_view(doc: object) -> dict:
    return {
        "constraint_layers": [
            group_view(g)
            for g in (getattr(doc, "constraint_layers", None) or [])
        ],
    }


def feature_view(feature: object) -> dict:
    if isinstance(feature, UserVectorFeature):
        return {
            "id": str(feature.id),
            "geometry": copy.deepcopy(feature.geometry),
            "properties": copy.deepcopy(feature.properties),
        }
    # SimpleNamespace fakes exercising the feature_id / attributes seam.
    view: dict = {}
    if getattr(feature, "feature_id", None) is not None:
        view["feature_id"] = str(feature.feature_id)
    if getattr(feature, "id", None) is not None:
        view["id"] = str(feature.id)
    view["geometry"] = copy.deepcopy(getattr(feature, "geometry", None) or {})
    if getattr(feature, "attributes", None) is not None:
        view["attributes"] = copy.deepcopy(feature.attributes)
    return view


def layer_view(layer: object) -> dict:
    raw = getattr(layer, "features", None)
    if callable(raw):
        raw = raw()
    return {"features": [feature_view(f) for f in (raw or [])]}


# ------------------------------------------------------------- constructions


def make_group_document() -> tuple[ProjectDocument, ConstraintLayers]:
    doc = ProjectDocument.new("t")
    group = ConstraintLayers(
        id="cg_1", name="T1 约束", target_horizon="T1", crs="EPSG:32650")
    group.lines = [
        ConstraintLine(
            id="l1", name="断层F1", role="break",
            coordinates=[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
            properties={"constraint_kind": "fault",
                        "strength": 0.8, "confidence": "high"}),
        ConstraintLine(
            id="l2", name="古岸线", role="boundary",
            coordinates=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0],
                         [0.0, 0.0]],
            properties={"constraint_kind": "paleo_shoreline"}),
    ]
    doc.constraint_layers.append(group)
    return doc, group


def make_layer(layer_id: str = "L1", polys: int = 1,
               feature_prefix: str = "f") -> UserVectorLayer:
    layer = UserVectorLayer(id=layer_id, name="综合沉积相", geometry_kind="polygon")
    for i in range(polys):
        layer.features.append(UserVectorFeature(
            id=f"{feature_prefix}{i}",
            geometry={"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
            properties={"class": "三角洲"},
        ))
    return layer


class EmptyCatalog:
    """catalog seam with no commits (list_assets is all the projection asks)."""

    def list_assets(self):
        return []


class _FixedUuid4:
    def __init__(self, hexstr: str):
        self.hex = hexstr


def with_fixed_uuids(ids: list[str], fn):
    """Patch sys.modules['uuid'] around fn — revision.py does `import uuid`
    inside record_interpretation_revision, so each call re-resolves this."""
    iterator = iter(ids)
    fake = SimpleNamespace(uuid4=lambda: _FixedUuid4(next(iterator)))
    original = sys.modules.get("uuid")
    sys.modules["uuid"] = fake
    try:
        return fn()
    finally:
        if original is None:
            sys.modules.pop("uuid", None)
        else:
            sys.modules["uuid"] = original


# ------------------------------------------------------------------- cases


def kind_cases() -> list[dict]:
    cases = []
    # 1 — representative mappings incl. string form, invalid, strip/lower.
    for text in ("fault", "source_direction", "paleo_shoreline", "mask",
                 "trend_line", "not-a-kind", "", "FAULT", " fault ", "faults"):
        from paleo_workbench.mapping_workspace.layer_roles import (
            constraint_kind_from_value,
        )

        resolved = constraint_kind_from_value(text)
        engine = to_engine_kind(text)
        cases.append({
            "id": f"kind_{len(cases)}_{text or 'empty'}",
            "input": text,
            "resolved_kind": None if resolved is None else str(resolved.value),
            "engine_kind": None if engine is None else str(engine.value),
        })
    # 2 — every geo kind maps (never None, never ValueError).
    all_kinds = []
    for kind in ConstraintKind:
        engine = to_engine_kind(kind)
        assert engine is not None, kind
        all_kinds.append({
            "id": f"all_{kind.value}",
            "input": str(kind.value),
            "resolved_kind": str(kind.value),
            "engine_kind": str(engine.value),
        })
    cases.append({"id": "every_geo_kind_maps", "inputs": all_kinds})
    return cases


def crs_cases() -> list[dict]:
    cases = []

    def run(case_id, factor, constraint, context=""):
        try:
            note = assert_constraints_crs_compatible(
                factor, constraint, context=context)
            error = None
        except ValueError as exc:
            note, error = "", str(exc)
        cases.append({
            "id": case_id,
            "factor_crs": factor,
            "constraint_crs": constraint,
            "context": context,
            "note": note,
            "error": error,
        })

    run("mismatch", "EPSG:32650", "EPSG:4326")
    run("mismatch_with_context", "EPSG:32650", "EPSG:4326", "T1 制图")
    run("factor_only", "EPSG:32650", "")
    run("factor_none_constraint_only", None, "EPSG:4326")
    run("both_undeclared", "", "")
    run("both_none", None, None)
    run("equal", "EPSG:32650", "EPSG:32650")
    run("equal_after_strip", " EPSG:32650\t", "EPSG:32650")
    run("factor_only_with_context", "EPSG:32650", None, "T1 制图")
    assert cases[0]["error"] == (
        "constraint CRS 'EPSG:4326' differs from factor CRS 'EPSG:32650' — "
        "reproject the constraint group before interpolation "
        "(mixed coordinates are never silently mixed)")
    assert cases[7]["note"] == ""
    return cases


def product_cases() -> list[dict]:
    cases = []

    def freeze(case_id, doc, group, catalog, *, catalog_spec,
               extra=None, commit_view=None, actor="", notes=""):
        product = constraint_product_for_group(doc, group, catalog=catalog)
        expect = product.to_dict()
        sentinel = bool(catalog_spec) and catalog_spec.get("kind") == "commit"
        if sentinel:
            expect["committed_version_id"] = None  # uuid — C++ checks non-empty
        case = {
            "id": case_id,
            "document": document_view(doc),
            "group": group_view(group),
            "catalog": catalog_spec,
            "expect": expect,
            "has_uncommitted": product.has_uncommitted_edits,
            "document_products_len": len(constraint_products_for_document(
                doc, catalog=catalog)),
        }
        if commit_view is not None:
            case["group_committed"] = commit_view
            case["commit_actor"] = actor
            case["commit_notes"] = notes
        if extra:
            case.update(extra)
        cases.append(case)
        return product

    # 5 — projection without catalog (kinds, engine order, rows, n_points).
    doc, group = make_group_document()
    product = freeze("projection_no_catalog", doc, group, None,
                     catalog_spec=None)
    assert set(product.kinds) == {"fault", "paleo_shoreline"}
    assert list(product.engine_kinds) == ["barrier", "boundary_mask"]
    assert product.lines[1].n_points == 5
    assert not product.has_uncommitted_edits

    # 6 — catalog present but never committed (still an uncommitted draft).
    doc, group = make_group_document()
    freeze("empty_catalog_draft", doc, group, EmptyCatalog(),
           catalog_spec={"kind": "empty"})

    # 7 — invalid strength/confidence values are rejected, not guessed.
    doc = ProjectDocument.new("t")
    group = ConstraintLayers(id="cg_2", name="x")
    group.lines = [ConstraintLine(
        id="l", name="bad", role="break",
        coordinates=[[0.0, 0.0], [1.0, 1.0]],
        properties={"strength": "not-a-number", "confidence": "superb"})]
    doc.constraint_layers.append(group)
    freeze("invalid_strength_confidence", doc, group, None, catalog_spec=None)

    # 8 + 9 — real catalog commit chain (SQLite-backed, like the tests).
    from paleo_workbench.catalog.service import DataCatalogService

    with tempfile.TemporaryDirectory(prefix="pwb-oracle-") as tmp:
        catalog = DataCatalogService.open(Path(tmp) / "proj" / "demo.paleo.json")
        try:
            doc, group = make_group_document()
            committed_view = group_view(group)
            report = commit_constraint_group(
                doc, catalog, group, actor="geologist-a", notes="初版")
            assert report.committed and report.reason == "changed"
            product = freeze(
                "committed_current", doc, group, catalog,
                catalog_spec={"kind": "commit"}, commit_view=committed_view,
                actor="geologist-a", notes="初版")
            assert product.maturity == "committed"
            assert product.staleness == "current"
            assert not product.has_uncommitted_edits
        finally:
            catalog.close()

    with tempfile.TemporaryDirectory(prefix="pwb-oracle-") as tmp:
        catalog = DataCatalogService.open(Path(tmp) / "proj" / "demo.paleo.json")
        try:
            doc, group = make_group_document()
            committed_view = group_view(group)
            commit_constraint_group(
                doc, catalog, group, actor="geologist-a", notes="初版")
            # Post-commit edit on the live editing surface (QGIS geometry).
            group.lines[0].coordinates.append([3.0, 3.0])
            product = freeze(
                "committed_then_edit", doc, group, catalog,
                catalog_spec={"kind": "commit"}, commit_view=committed_view,
                actor="geologist-a", notes="初版")
            assert product.has_uncommitted_edits
            assert product.validity == "存在未提交编辑（live 内容 ≠ 最新提交）"
            assert product.staleness == "current"
        finally:
            catalog.close()

    # 10 — malformed coordinates: content hash fails honestly ("" + no
    # staleness), the projection itself never breaks.
    bad_line = SimpleNamespace(
        id="l9", name="坏坐标", role="break", active=True, target_horizon="",
        coordinates=[["oops", 1.0]], properties={})
    bad_group = SimpleNamespace(
        id="cg_bad", name="坏", target_horizon="T1", crs=None, lines=[bad_line])
    doc_bad = SimpleNamespace(constraint_layers=[bad_group])
    try:
        constraint_group_content_hash(bad_group)
        raise SystemExit("expected the malformed group hash to raise")
    except ValueError:
        pass
    freeze("hash_failure_tolerance", doc_bad, bad_group, None,
           catalog_spec=None)
    return cases


def revision_chain_case() -> dict:
    doc = ProjectDocument.new("t")
    layer = make_layer("L1")
    call_one = dict(
        target_kind="integrated_facies", target_layer_id="L1",
        actor="geologist-a", now="t1", base_kind="fusion",
        base_version_id="ver_fusion_1",
        evidence_refs=["factor:t1:ver_1", "constraints:current"])
    call_unchanged = dict(
        target_kind="integrated_facies", target_layer_id="L1", now="t2")
    call_two = dict(
        target_kind="integrated_facies", target_layer_id="L1",
        actor="geologist-b", now="t3")
    layer_before = layer_view(layer)
    ids = ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]

    def replay():
        first = record_interpretation_revision(doc, layer=layer, **call_one)
        unchanged = record_interpretation_revision(doc, layer=layer,
                                                   **call_unchanged)
        layer.features.append(UserVectorFeature(
            id="f1",
            geometry={"type": "Polygon", "coordinates": [
                [[2.0, 2.0], [3.0, 2.0], [3.0, 3.0], [2.0, 2.0]]]},
            properties={"class": "湖泊"}))
        second = record_interpretation_revision(doc, layer=layer, **call_two)
        return first, unchanged, second

    first, unchanged, second = with_fixed_uuids(ids, replay)
    assert unchanged is None
    assert second.parent_revision_id == first.revision_id
    assert second.delta == {"features": 1, "vertices": 4}
    expected_ids = ["irev_" + ids[0], "irev_" + ids[1]]
    chain = revisions_for_layer(doc, "L1")
    assert [r.revision_id for r in chain] == expected_ids
    assert latest_revision_for_layer(doc, "L1").revision_id == expected_ids[1]

    def call_spec(spec, layer_key):
        out = dict(spec)
        out["layer"] = layer_key
        return out

    return {
        "id": "revision_chain",
        "document_in": {"interpretation_revisions": []},
        "layer_before": layer_before,
        "layer_after": layer_view(layer),
        "calls": [call_spec(call_one, "before"),
                  call_spec(call_unchanged, "before"),
                  call_spec(call_two, "after")],
        "ids": ["irev_" + ids[0], "irev_" + ids[1]],
        "expect_results": [first.to_dict(), None, second.to_dict()],
        "expect_document": {"interpretation_revisions": copy.deepcopy(
            doc.interpretation_revisions)},
        "chain_ids": expected_ids,
        "latest_id": expected_ids[1],
    }


def fingerprint_cases() -> list[dict]:
    cases = []

    def freeze(case_id, layer, equal_to=None):
        digest, counts = layer_content_fingerprint(layer)
        cases.append({
            "id": case_id,
            "layer": layer_view(layer),
            "expect": {"digest": digest,
                       "features": counts["features"],
                       "vertices": counts["vertices"]},
            "equal_to": equal_to,
        })
        return digest

    # 12 — same content, different layer ids -> identical fingerprints.
    digest_a = freeze("stability_layer_a", make_layer("a"))
    digest_b = freeze("stability_layer_b", make_layer("b"),
                      equal_to="stability_layer_a")
    assert digest_a == digest_b
    assert layer_content_fingerprint(make_layer("L1"))[1] == {
        "features": 1, "vertices": 4}

    # 9dp rounding equality inside LIST-valued attributes. (Python's _stab
    # recurses lists only — it has no dict branch — so a dict-rooted GeoJSON
    # geometry passes through VERBATIM and is never rounded; the port
    # mirrors that faithfully.)
    base = SimpleNamespace(features=[SimpleNamespace(
        id="f0", geometry={}, attributes={"m": [1.0, 2.0]})])
    long_tail = SimpleNamespace(features=[SimpleNamespace(
        id="f0", geometry={}, attributes={"m": [1.000000000001, 2.0]})])
    digest_list = freeze("nine_dp_list_attribute", base)
    digest_list_2 = freeze("nine_dp_list_attribute_rounded", long_tail,
                           equal_to="nine_dp_list_attribute")
    assert digest_list == digest_list_2

    # Consequence of the same rule, frozen as-is: 1.0 vs 1.000000000001 in
    # dict geometry coordinates produce DIFFERENT fingerprints.
    def geom_layer(x):
        layer = UserVectorLayer(id="g", name="g", geometry_kind="polygon")
        layer.features.append(UserVectorFeature(
            id="f0",
            geometry={"type": "Polygon", "coordinates": [
                [[0.0, 0.0], [x, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
            properties={"class": "三角洲"}))
        return layer

    digest_geom_base = freeze("geometry_verbatim_base", geom_layer(1.0))
    digest_geom_long = freeze("geometry_verbatim_long",
                              geom_layer(1.000000000001))
    assert digest_geom_base != digest_geom_long

    # Integer coordinates keep their type in dict geometry ("2" stays an
    # int in the digest — no float coercion without the list recursion).
    ints = SimpleNamespace(features=[SimpleNamespace(
        id="i0",
        geometry={"type": "LineString", "coordinates": [[2, 3], [4, 5]]})])
    freeze("integer_coordinates", ints)

    # feature_id precedence + attributes seam (edit_controller shape).
    fancy = SimpleNamespace(features=[SimpleNamespace(
        feature_id="fa1", id="ignored",
        geometry={"type": "Point", "coordinates": [1.5, 2.5]},
        attributes={"b": 2, "a": 1, "m": [0, 1]})])
    freeze("attributes_and_feature_id", fancy)

    # Empty layer: sha256 of "[]" — an honest empty fingerprint.
    empty = UserVectorLayer(id="e", name="空")
    freeze("empty_layer", empty)
    return cases


def from_dict_cases() -> list[dict]:
    full = {
        "revision_id": "irev_0123456789ab",
        "target_kind": "integrated_facies",
        "target_layer_id": "L1",
        "interpretation_id": "iint_abc123def456",
        "parent_revision_id": "irev_ffffffffffff",
        "base_kind": "fusion",
        "base_version_id": "ver_fusion_1",
        "evidence_refs": ["factor:t1:ver_1", "constraints:current"],
        "actor": "geologist-a",
        "created_at": "2026-09-19T10:00:00",
        "content_fingerprint": "ab" * 32,
        "delta": {"features": 1, "vertices": 4},
        "note": "初稿",
    }
    roundtrip = InterpretationRevision.from_dict(
        copy.deepcopy(full)).to_dict()
    assert roundtrip == full
    coercions = {
        "revision_id": 7,
        "target_kind": None,
        "target_layer_id": "L7",
        "parent_revision_id": 0,
        "base_kind": "",
        "evidence_refs": [1, "a", True, 2.5],
        "actor": 0,
        "content_fingerprint": 0,
        "delta": None,
        "note": False,
    }
    return [
        {"id": "roundtrip", "input": full,
         "expect": InterpretationRevision.from_dict(full).to_dict()},
        {"id": "empty", "input": {},
         "expect": InterpretationRevision.from_dict({}).to_dict()},
        {"id": "coercions", "input": coercions,
         "expect": InterpretationRevision.from_dict(coercions).to_dict()},
        # FROZEN-HEADER contract (Python dict(5) would raise TypeError; the
        # C++ from_dict is specified to coerce non-object deltas to {}).
        {"id": "delta_non_object", "source": "cpp_contract",
         "input": {"revision_id": "irev_x", "delta": 5},
         "expect": InterpretationRevision.from_dict(
             {"revision_id": "irev_x", "delta": None}).to_dict()},
    ]


def summary_cases(chain_revisions: list[dict]) -> list[dict]:
    empty_doc = ProjectDocument.new("t")
    populated = SimpleNamespace(interpretation_revisions=chain_revisions)
    return [
        {"id": "empty", "document": {"interpretation_revisions": []},
         "layer_id": "L0",
         "expect": revision_summary(empty_doc, "L0")},
        {"id": "populated",
         "document": {"interpretation_revisions": chain_revisions},
         "layer_id": "L1",
         "expect": revision_summary(populated, "L1")},
    ]


def integrated_link_case() -> dict:
    doc = ProjectDocument.new("t")
    layer = make_layer("L9", polys=2)
    phase1_layer = make_layer("L8")
    interpretation = create_integrated_interpretation(
        doc, name="综合解释", layer_id="L9", input_set_id="ciset_1",
        fusion_version_id="ver_seed")
    # create uses a uuid slice; pin it so the fixture is byte-deterministic
    # (the id must merely stay consistent between input and expectation).
    interpretation.interpretation_id = "iint_0123456789ab"
    doc.integrated_interpretations[0]["interpretation_id"] = \
        interpretation.interpretation_id
    document_in = {
        "integrated_interpretations": copy.deepcopy(
            doc.integrated_interpretations),
        "interpretation_revisions": [],
    }
    call_one = dict(
        target_kind="integrated_facies", target_layer_id="L9",
        actor="expert", now="t1",
        interpretation_id=interpretation.interpretation_id)
    call_two = dict(
        target_kind="phase1_draft", target_layer_id="L8",
        actor="expert", now="t2")
    ids = ["cccccccccccc", "dddddddddddd"]

    def replay():
        linked = record_interpretation_revision(
            doc, layer=layer, **call_one)
        assert doc.integrated_interpretations[0]["revision_ids"] == \
            [linked.revision_id]
        untouched = record_interpretation_revision(
            doc, layer=phase1_layer, **call_two)
        # phase1_draft with no interpretation id touches no interpretation.
        assert doc.integrated_interpretations[0]["revision_ids"] == \
            [linked.revision_id]
        return linked, untouched

    linked, untouched = with_fixed_uuids(ids, replay)
    return {
        "id": "integrated_link",
        "document_in": document_in,
        "layers": {"L9": layer_view(layer), "L8": layer_view(phase1_layer)},
        "calls": [
            dict(call_one, layer="L9"),
            dict(call_two, layer="L8"),
        ],
        "ids": ["irev_" + ids[0], "irev_" + ids[1]],
        "expect_results": [linked.to_dict(), untouched.to_dict()],
        "expect_document": {
            "integrated_interpretations": copy.deepcopy(
                doc.integrated_interpretations),
            "interpretation_revisions": copy.deepcopy(
                doc.interpretation_revisions),
        },
    }


def main() -> None:
    kinds = kind_cases()
    chain = revision_chain_case()
    doc = {
        "kind_cases": kinds,
        "crs_cases": crs_cases(),
        "product_cases": product_cases(),
        "revision_chain": chain,
        "fingerprint_cases": fingerprint_cases(),
        "from_dict_cases": from_dict_cases(),
        "summary_cases": summary_cases(
            copy.deepcopy(chain["expect_document"]["interpretation_revisions"])),
        "integrated_link": integrated_link_case(),
    }
    target = OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                      encoding="utf-8")
    print(
        f"wrote {target} ({target.stat().st_size} bytes, "
        f"{len(kinds)} kind cases, "
        f"{sum(1 for c in doc['crs_cases'])} CRS cases, "
        f"{len(doc['product_cases'])} product cases, "
        f"{len(doc['fingerprint_cases'])} fingerprint cases, "
        f"{len(doc['from_dict_cases'])} from_dict cases, "
        f"{len(doc['summary_cases'])} summary cases)")


if __name__ == "__main__":
    main()
