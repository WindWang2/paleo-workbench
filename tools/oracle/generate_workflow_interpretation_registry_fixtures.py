#!/usr/bin/env python3
"""Oracle fixture generator for the workflow_interpretation registry (CONV-32).

Imports the REAL implementations (paleo_workbench.workflow.constraint_capabilities
and paleo_workbench.workflow.interpretation.algorithm_registry) and freezes
their outputs to JSON so the C++ port in libs/workflow_interpretation can be
verified against the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_interpretation_registry_fixtures.py

24 cases (recon list): label/alias resolution, the KeyError/ValueError/
ConstraintViolationError message text (byte-exact, incl. the str(KeyError)
double-quoted form), default capability cells, strict-mode violation attrs,
dedupe order, to_dict freezes (kriging/linear/factor_fusion), constraint
support projection defaults, alias canonicalization, get_algorithm strip-only
semantics, UI lists, register/replace semantics, the full capability matrix
plus its insertion-order key list, and honest()/diagnostics_labels closure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.workflow.constraint_capabilities import (  # noqa: E402
    ConstraintKind,
    ConstraintViolationError,
    capabilities_for_method,
    capability_matrix,
    evaluate_request,
)
from paleo_workbench.workflow.interpretation.algorithm_registry import (  # noqa: E402
    ALGORITHMS,
    AlgorithmSpec,
    canonical_algorithm_id,
    display_label,
    get_algorithm,
    interpolation_algorithm_labels,
    register_algorithm,
    ui_interpolation_methods,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_interpretation"
    / "workflow_interpretation_tests"
    / "fixtures"
)


def raise_expect(exc: BaseException) -> dict:
    """Raise parity: python class name, raw message (args[0] for KeyError,
    whose str() adds repr quoting), and the str() form Python would print."""
    message = str(exc.args[0]) if isinstance(exc, KeyError) else str(exc)
    return {
        "python_class": type(exc).__name__,
        "message": message,
        "str": str(exc),
    }


def caps_detail(method: str) -> dict:
    caps = capabilities_for_method(method)
    return {
        "method": caps.method,
        "label": caps.label,
        "prerequisites": list(caps.prerequisites),
        "for_kind": {
            kind.value: [
                caps.for_kind(kind)[0].value,
                caps.for_kind(kind)[1],
            ]
            for kind in ConstraintKind
        },
    }


def eval_expect(method: str, requested, strict: bool = False) -> dict:
    app = evaluate_request(method, requested, strict=strict)
    return {
        "result": app.as_dict(),
        "honest": app.honest,
        "diagnostics_labels": sorted(app.diagnostics_labels()),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # (1) label/alias resolution — strip+lower direct lookup first, then
    # _LABEL_ALIASES (lowercase mvp alias vs the uppercase ALGORITHMS alias).
    def resolve(method: str) -> dict:
        caps = capabilities_for_method(method)
        return {"method": caps.method, "label": caps.label}

    case01 = {
        "id": "case01_label_alias_resolution",
        "fn": "capabilities_resolve",
        "input": {"methods": [" IDW ", "反距离加权", "克里金(mvp·线性)"]},
        "expect": {
            "results": [
                resolve(" IDW "),
                resolve("反距离加权"),
                resolve("克里金(mvp·线性)"),
            ]
        },
    }

    # (2) KeyError message full — repr of the ORIGINAL argument + the sorted
    # known list as a Python list-repr; str(KeyError(...)) double-quotes it.
    try:
        capabilities_for_method("nope")
        raise AssertionError("capabilities_for_method('nope') must raise")
    except KeyError as exc:
        case02 = {
            "id": "case02_keyerror_message",
            "fn": "capabilities_for",
            "input": {"method": "nope"},
            "expect": {"raise": raise_expect(exc)},
        }

    # (3) default cell (absent -> UNSUPPORTED + "not consumed by this
    # method") + rbf's projected prerequisite.
    case03 = {
        "id": "case03_default_cell_and_rbf_prereq",
        "fn": "capabilities_for",
        "input": {"method": "rbf"},
        "expect": {"result": caps_detail("rbf")},
    }

    # (4) kriging barrier+trend unsupported diagnostics verbatim (label
    # 普通克里金; em-dash with spaces, uppercase NOT).
    case04 = {
        "id": "case04_kriging_unsupported_diagnostics",
        "fn": "evaluate_request",
        "input": {"method": "kriging",
                  "requested": ["barrier", "trend"], "strict": False},
        "expect": eval_expect("kriging", ["barrier", "trend"]),
    }

    # (5) strict violation — byte-exact ":;" join artifact + attrs.
    try:
        evaluate_request("kriging", ["barrier", "trend"], strict=True)
        raise AssertionError("strict kriging barrier+trend must raise")
    except ConstraintViolationError as exc:
        case05 = {
            "id": "case05_strict_violation",
            "fn": "evaluate_request",
            "input": {"method": "kriging",
                      "requested": ["barrier", "trend"], "strict": True},
            "expect": {
                "raise": {
                    **raise_expect(exc),
                    "method": exc.method,
                    "unsupported": list(exc.unsupported),
                    "ignored": list(exc.ignored),
                }
            },
        }

    # (6) constrained_idw all kinds (partial anisotropy diagnostic).
    all_kinds = [kind.value for kind in ConstraintKind]
    case06 = {
        "id": "case06_constrained_idw_all_kinds",
        "fn": "evaluate_request",
        "input": {"method": "constrained_idw",
                  "requested": all_kinds, "strict": False},
        "expect": eval_expect("constrained_idw", all_kinds),
    }

    # (7) spline partial diag + unsupported diag in one request.
    case07 = {
        "id": "case07_spline_partial",
        "fn": "evaluate_request",
        "input": {"method": "spline",
                  "requested": ["boundary_mask", "barrier"], "strict": False},
        "expect": eval_expect("spline", ["boundary_mask", "barrier"]),
    }

    # (8) dedupe requested (first-seen order kept).
    case08 = {
        "id": "case08_dedupe_requested",
        "fn": "evaluate_request",
        "input": {"method": "idw",
                  "requested": ["barrier", "barrier", "trend", "barrier"],
                  "strict": False},
        "expect": eval_expect(
            "idw", ["barrier", "barrier", "trend", "barrier"]),
    }

    # (9) None/empty requested + strict no-raise (Python None == [] here;
    # the C++ port has no None, so [] is the frozen form).
    case09 = {
        "id": "case09_empty_requested_strict",
        "fn": "evaluate_request",
        "input": {"method": "kriging", "requested": [], "strict": True},
        "expect": eval_expect("kriging", None, strict=True),
    }

    # (10) 样条 alias method + string kinds + invalid kind ValueError.
    try:
        evaluate_request("idw", ["bogus"])
        raise AssertionError("invalid ConstraintKind must raise")
    except ValueError as exc:
        case10 = {
            "id": "case10_alias_method_and_invalid_kind",
            "fn": "evaluate_request_two",
            "input": {
                "ok": {"method": "样条",
                       "requested": ["boundary_mask"], "strict": False},
                "invalid": {"method": "idw",
                            "requested": ["bogus"], "strict": False},
            },
            "expect": {
                "ok": eval_expect("样条", ["boundary_mask"]),
                "invalid": {"raise": raise_expect(exc)},
            },
        }

    # (11) unknown method KeyError propagates out of evaluate_request
    # (repr of the ORIGINAL argument).
    try:
        evaluate_request("nope", [])
        raise AssertionError("evaluate_request('nope') must raise")
    except KeyError as exc:
        case11 = {
            "id": "case11_unknown_method_propagates",
            "fn": "evaluate_request",
            "input": {"method": "nope", "requested": [], "strict": False},
            "expect": {"raise": raise_expect(exc)},
        }

    # (12-14) to_dict freeze.
    def to_dict_case(cid: str, algorithm_id: str) -> dict:
        return {
            "id": cid,
            "fn": "algorithm_to_dict",
            "input": {"algorithm_id": algorithm_id},
            "expect": {"result": get_algorithm(algorithm_id).to_dict()},
        }

    # (15) constraint_support default + barrier hit (idw).
    cs_kinds = ["barrier", "trend", "boundary_mask"]
    idw_spec = get_algorithm("idw")
    case15 = {
        "id": "case15_constraint_support_projection",
        "fn": "algorithm_constraint_support",
        "input": {"algorithm_id": "idw", "kinds": cs_kinds},
        "expect": {
            "result": {
                kind: [
                    idw_spec.constraint_support(ConstraintKind(kind))[0].value,
                    idw_spec.constraint_support(ConstraintKind(kind))[1],
                ]
                for kind in cs_kinds
            }
        },
    }

    # (16) alias canonicalization incl. case-folding and CJK aliases.
    canon_refs = ["OK", "Constrained IDW", "样条插值",
                  "克里金(MVP·线性)", "factor_fusion", " RBF "]

    def canon_outcome(ref: str):
        try:
            return {"ok": canonical_algorithm_id(ref)}
        except ValueError as exc:
            return {"raise": raise_expect(exc)}

    case16 = {
        "id": "case16_alias_canonicalization",
        "fn": "canonical_algorithm_id",
        "input": {"refs": canon_refs},
        "expect": {"outcomes": [canon_outcome(r) for r in canon_refs]},
    }

    # (17) empty ref ValueError.
    case17 = {
        "id": "case17_empty_ref",
        "fn": "canonical_algorithm_id",
        "input": {"refs": [""]},
        "expect": {"outcomes": [canon_outcome("")]},
    }

    # (18) " nope " -> unknown algorithm, repr of the ORIGINAL unstripped ref.
    case18 = {
        "id": "case18_unknown_ref_repr",
        "fn": "canonical_algorithm_id",
        "input": {"refs": [" nope "]},
        "expect": {"outcomes": [canon_outcome(" nope ")]},
    }

    # (19) get_algorithm: strip only, no alias/case resolution, empty -> None.
    ga_refs = [" kriging ", "克里金", "", "factor_fusion"]

    def ga(ref: str):
        spec = get_algorithm(ref)
        if spec is None:
            return None
        return {"algorithm_id": spec.algorithm_id, "family": spec.family}

    case19 = {
        "id": "case19_get_algorithm_strip_only",
        "fn": "get_algorithm",
        "input": {"refs": ga_refs},
        "expect": {"results": [ga(r) for r in ga_refs]},
    }

    # (20) UI lists + registry membership (ids compared order-insensitively:
    # C++ algorithms() is a std::map — key-sorted, not Python insert order).
    case20 = {
        "id": "case20_ui_lists",
        "fn": "ui_lists",
        "input": {},
        "expect": {
            "methods": ui_interpolation_methods(),
            "labels": interpolation_algorithm_labels(),
            "algorithm_ids": list(ALGORITHMS.keys()),
        },
    }

    # (21) display_label via canonical resolution (fallback raw str).
    dl_refs = ["ok", "RBF 多二次"]
    case21 = {
        "id": "case21_display_label",
        "fn": "display_label",
        "input": {"refs": dl_refs},
        "expect": {"results": [display_label(r) for r in dl_refs]},
    }

    # (22) register + replace semantics (global mutation, scripted outcome
    # strings; the C++ test reproduces the same script).
    steps: list[str] = []
    steps.append(f"size_before={len(ALGORITHMS)}")
    register_algorithm(AlgorithmSpec(
        algorithm_id="test.custom",
        family="interpolation",
        display_label="测试替换",
        aliases=("custom thing", "替换前"),
    ))
    steps.append("canonical[Custom Thing]="
                 + canonical_algorithm_id("Custom Thing"))
    steps.append("canonical[替换前]=" + canonical_algorithm_id("替换前"))
    steps.append(f"size_after_register={len(ALGORITHMS)}")
    register_algorithm(AlgorithmSpec(
        algorithm_id="test.custom",
        family="interpolation",
        display_label="测试替换2",
        aliases=("替换后",),
    ))
    try:
        canonical_algorithm_id("custom thing")
        raise AssertionError("stale alias must raise after replace")
    except ValueError as exc:
        steps.append(f"canonical[custom thing]={type(exc).__name__}:{exc}")
    steps.append("canonical[替换后]=" + canonical_algorithm_id("替换后"))
    steps.append(f"size_after_replace={len(ALGORITHMS)}")
    case22 = {
        "id": "case22_register_replace_semantics",
        "fn": "register_semantics",
        "input": {},
        "expect": {"steps": steps},
    }

    # (23) capability_matrix: full matrix + _METHODS insertion key order
    # (idw, constrained_idw, kriging, spline, linear, nearest, rbf,
    # directional) — the C++ side must emit that exact order — plus the
    # enum-ordered constraint keys of the idw row.
    matrix = capability_matrix()
    case23 = {
        "id": "case23_capability_matrix",
        "fn": "capability_matrix",
        "input": {},
        "expect": {
            "matrix": matrix,
            "key_order": list(matrix.keys()),
            "idw_constraints_order":
                list(matrix["idw"]["constraints"].keys()),
        },
    }

    # (24) honest()/diagnostics_labels semantics (directional: supported
    # trend has no diagnostic; ignored stays empty -> honest True).
    case24 = {
        "id": "case24_honest_and_diagnostics_labels",
        "fn": "evaluate_request",
        "input": {"method": "directional",
                  "requested": ["direction", "anisotropy", "trend", "barrier"],
                  "strict": False},
        "expect": eval_expect(
            "directional", ["direction", "anisotropy", "trend", "barrier"]),
    }

    doc = {
        "cases": [
            case01, case02, case03, case04, case05, case06, case07, case08,
            case09, case10, case11, to_dict_case("case12_to_dict_kriging",
                                                 "kriging"),
            to_dict_case("case13_to_dict_linear", "linear"),
            to_dict_case("case14_to_dict_factor_fusion", "factor_fusion"),
            case15, case16, case17, case18, case19, case20, case21, case22,
            case23, case24,
        ]
    }
    assert len(doc["cases"]) == 24, "recon case count must stay at 24"
    target = OUT / "workflow_interpretation_registry_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(doc['cases'])} cases)")


if __name__ == "__main__":
    main()
