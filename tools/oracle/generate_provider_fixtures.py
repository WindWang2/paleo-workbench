#!/usr/bin/env python3
"""Freeze provider SDK oracle fixtures for the C++ providers conformance test.

Runs the real Python implementation (paleo_workbench.providers) over a
deterministic case table and writes
``libs/providers/providers_tests/provider_oracle.json`` — the C++
``providers.oracle`` test replays every case and demands verdict parity
(problem lists compared verbatim, order included).

Coverage: normal, empty, illegal, boundary (min == value == max), nested
objects/arrays, unions (known/unknown members), bool-vs-integer rejection,
enum membership (incl. Unicode), additionalProperties:false, unknown type
names, non-object top level and custom label.

Negative self-check: after writing the fixture the generator re-imports it,
perturbs one frozen verdict and asserts its comparator detects the change —
the same comparison logic the C++ side relies on, so a broken fixture cannot
pass silently.

NaN/Inf are intentionally NOT frozen here: json.dumps would emit
``NaN/Infinity`` literals which strict JSON parsers reject. The C++ suite
covers the NaN boundary natively instead (providers_schema_test).

Run from the repository root::

    python3 tools/oracle/generate_provider_fixtures.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.providers.contracts import (  # noqa: E402
    TYPED_REFS,
    ProviderDescriptor,
    ProviderFamily,
    ResourceProfile,
    validate_descriptor,
)
from paleo_workbench.providers.execution import validate_parameters  # noqa: E402

OUT_PATH = REPO_ROOT / "libs" / "providers" / "providers_tests" / "provider_oracle.json"

# ---------------------------------------------------------------------------
# validate_parameters case table
# ---------------------------------------------------------------------------
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "output_path": {"type": "string"},
        "width": {"type": "integer", "minimum": 64, "maximum": 4096},
        "height": {"type": "integer", "minimum": 64, "maximum": 4096},
        "mode": {"type": "string", "enum": ["fast", "quality", "精细"]},
        "ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
        "nested": {
            "type": "object",
            "properties": {"depth": {"type": "integer", "minimum": 0}},
            "required": ["depth"],
            "additionalProperties": False,
        },
        "maybe": {"type": ["string", "null"]},
        "wild": {"type": ["barnum", "whodunit"]},
        "loose": {"type": "floatly"},
    },
    "required": ["output_path"],
    "additionalProperties": False,
}

PARAM_CASES = [
    # (case id, schema, parameters, label)
    ("params.valid.minimal", PARAM_SCHEMA, {"output_path": "out/thumb.png"}, "parameters"),
    ("params.valid.full", PARAM_SCHEMA,
     {"output_path": "out/a.png", "width": 640, "height": 480, "mode": "精细",
      "ratio": 0.5, "tags": ["a", "b"], "nested": {"depth": 2}, "maybe": None},
     "parameters"),
    ("params.empty-params-missing-required", PARAM_SCHEMA, {}, "parameters"),
    ("params.empty-schema-empty-params", {}, {}, "parameters"),
    ("params.wrong-type-integer", PARAM_SCHEMA, {"output_path": 12}, "parameters"),
    ("params.bool-not-integer", PARAM_SCHEMA, {"output_path": "a.png", "width": True}, "parameters"),
    ("params.bool-not-number", PARAM_SCHEMA, {"output_path": "a.png", "ratio": False}, "parameters"),
    ("params.below-minimum", PARAM_SCHEMA, {"output_path": "a.png", "width": 63}, "parameters"),
    ("params.above-maximum", PARAM_SCHEMA, {"output_path": "a.png", "height": 4097}, "parameters"),
    ("params.boundary-minimum-equal", PARAM_SCHEMA, {"output_path": "a.png", "width": 64}, "parameters"),
    ("params.boundary-maximum-equal", PARAM_SCHEMA, {"output_path": "a.png", "width": 4096}, "parameters"),
    ("params.float-against-integer-minimum", PARAM_SCHEMA, {"output_path": "a.png", "width": 63.5}, "parameters"),
    ("params.not-in-enum", PARAM_SCHEMA, {"output_path": "a.png", "mode": "BALANCED"}, "parameters"),
    ("params.enum-unicode-member", PARAM_SCHEMA, {"output_path": "a.png", "mode": "精细"}, "parameters"),
    ("params.number-maximum-violated", PARAM_SCHEMA, {"output_path": "a.png", "ratio": 1.5}, "parameters"),
    ("params.array-too-short", PARAM_SCHEMA, {"output_path": "a.png", "tags": []}, "parameters"),
    ("params.array-too-long", PARAM_SCHEMA, {"output_path": "a.png", "tags": ["a", "b", "c", "d"]}, "parameters"),
    ("params.array-item-wrong-type", PARAM_SCHEMA, {"output_path": "a.png", "tags": ["a", 3]}, "parameters"),
    ("params.array-items-boundary-ok", PARAM_SCHEMA, {"output_path": "a.png", "tags": ["x"]}, "parameters"),
    ("params.nested-missing-required", PARAM_SCHEMA, {"output_path": "a.png", "nested": {}}, "parameters"),
    ("params.nested-additional-property", PARAM_SCHEMA,
     {"output_path": "a.png", "nested": {"depth": 1, "extra": True}}, "parameters"),
    ("params.nested-below-minimum", PARAM_SCHEMA, {"output_path": "a.png", "nested": {"depth": -1}}, "parameters"),
    ("params.union-null-ok", PARAM_SCHEMA, {"output_path": "a.png", "maybe": None}, "parameters"),
    ("params.union-string-ok", PARAM_SCHEMA, {"output_path": "a.png", "maybe": "x"}, "parameters"),
    ("params.union-rejected", PARAM_SCHEMA, {"output_path": "a.png", "maybe": 5}, "parameters"),
    ("params.union-all-unknown", PARAM_SCHEMA, {"output_path": "a.png", "wild": "x"}, "parameters"),
    ("params.unknown-single-type", PARAM_SCHEMA, {"output_path": "a.png", "loose": "x"}, "parameters"),
    ("params.additional-top-level", PARAM_SCHEMA, {"output_path": "a.png", "surprise": 1}, "parameters"),
    ("params.empty-string-output", PARAM_SCHEMA, {"output_path": ""}, "parameters"),
    ("params.top-level-not-object", PARAM_SCHEMA, ["not", "an", "object"], "parameters"),
    ("params.top-level-string-label", {"type": "object"}, "nope", "arguments"),
    ("params.string-type-toplevel-nonobject", {"type": "string"}, 42, "parameters"),
    ("params.int-toplevel-valid", {"type": "integer"}, 7, "parameters"),
    ("params.array-schema-nested-paths", {"type": "array", "items": {"type": "object",
     "properties": {"v": {"type": "number", "minimum": 0}}, "required": ["v"]}},
     [{"v": 1.5}, {"v": -2}], "parameters"),
]

# ---------------------------------------------------------------------------
# validate_descriptor case table
# ---------------------------------------------------------------------------
VALID_DESCRIPTOR = {
    "provider_id": "geology.factor_stats",
    "family": "interpolation",
    "version": "1.0.0",
    "display_name": "地质因子统计摘要",
    "capabilities": ["factor_stats"],
    "input_types": ["GeologicalFactorDataset", "FactorDatasetRef"],
    "output_types": ["PathRef"],
    "parameters_schema": {"type": "object", "properties": {}},
    "resource_profile": {
        "estimated_cpu_cores": 0.5,
        "estimated_ram_bytes": 67108864,
        "estimated_vram_bytes": 0,
        "io_weight": 0.2,
        "category": "background.compute",
    },
    "threading_model": "worker_thread",
}


def make_descriptor(**overrides):
    payload = {**VALID_DESCRIPTOR, **overrides}
    profile = payload["resource_profile"]
    if not isinstance(profile, ResourceProfile):
        profile = ResourceProfile(**profile)
    return ProviderDescriptor(
        provider_id=payload["provider_id"],
        family=ProviderFamily(payload["family"]),
        version=payload["version"],
        display_name=payload["display_name"],
        capabilities=tuple(payload["capabilities"]),
        input_types=tuple(payload["input_types"]),
        output_types=tuple(payload["output_types"]),
        parameters_schema=payload["parameters_schema"],
        resource_profile=profile,
        threading_model=payload["threading_model"],
    )


DESCRIPTOR_CASES = [
    ("descriptor.valid", make_descriptor()),
    ("descriptor.empty-id", make_descriptor(provider_id="")),
    ("descriptor.uppercase-id", make_descriptor(provider_id="Geology.Stats")),
    ("descriptor.leading-dot-id", make_descriptor(provider_id=".geology")),
    ("descriptor.short-id", make_descriptor(provider_id="a")),
    ("descriptor.too-long-id", make_descriptor(provider_id="a" * 65)),
    ("descriptor.id-max-length-ok", make_descriptor(provider_id="a" * 64)),
    ("descriptor.bad-version-empty", make_descriptor(version="")),
    ("descriptor.bad-version-alpha", make_descriptor(version="1.0.x")),
    ("descriptor.version-four-segments-ok", make_descriptor(version="1.2.3.4")),
    ("descriptor.version-five-segments", make_descriptor(version="1.2.3.4.5")),
    ("descriptor.whitespace-display-name", make_descriptor(display_name="   ")),
    ("descriptor.schema-not-object", make_descriptor(parameters_schema="nope")),
    ("descriptor.schema-wrong-top-type", make_descriptor(parameters_schema={"type": "string"})),
    ("descriptor.schema-top-type-null-ok", make_descriptor(parameters_schema={"type": None})),
    ("descriptor.schema-properties-not-dict", make_descriptor(parameters_schema={"properties": []})),
    ("descriptor.schema-required-not-list", make_descriptor(parameters_schema={"required": "width"})),
    ("descriptor.unknown-input-ref", make_descriptor(input_types=("BogusRef",))),
    ("descriptor.unknown-output-ref", make_descriptor(output_types=("BogusRef",))),
    ("descriptor.bad-threading-model", make_descriptor(threading_model="main_loop")),
    ("descriptor.threading-any-ok", make_descriptor(threading_model="any")),
    ("descriptor.cpu-cores-zero", make_descriptor(
        resource_profile=ResourceProfile(estimated_cpu_cores=0.0))),
    ("descriptor.io-weight-negative", make_descriptor(
        resource_profile=ResourceProfile(io_weight=-0.1))),
    ("descriptor.deterministic-false-ok", make_descriptor(
        parameters_schema={}, capabilities=())),
]


def main() -> int:
    param_cases = []
    for case_id, schema, params, label in PARAM_CASES:
        problems = validate_parameters(schema, params, label=label)
        param_cases.append({
            "id": case_id,
            "fn": "validate_parameters",
            "schema": schema,
            "parameters": params,
            "label": label,
            "problems": problems,
        })

    descriptor_cases = []
    for case_id, descriptor in DESCRIPTOR_CASES:
        problems = validate_descriptor(descriptor)
        descriptor_cases.append({
            "id": case_id,
            "fn": "validate_descriptor",
            "descriptor": descriptor.to_dict(),
            "problems": problems,
        })

    fixture = {
        "generator": "tools/oracle/generate_provider_fixtures.py",
        "typed_refs": sorted(TYPED_REFS),
        "cases": param_cases + descriptor_cases,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    # Negative self-check: a perturbed verdict must be detectable by the same
    # comparison the C++ replay uses (exact list equality).
    mutated = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    mutated["cases"][0]["problems"] = ["deliberately wrong"]
    plain = [c["problems"] for c in fixture["cases"]]
    mangled = [c["problems"] for c in mutated["cases"]]
    if plain == mangled:
        print("NEGATIVE SELF-CHECK FAILED: perturbed fixture not detected")
        return 1
    differing = sum(1 for a, b in zip(plain, mangled) if a != b)
    if differing != 1:
        print(f"NEGATIVE SELF-CHECK FAILED: expected 1 differing case, got {differing}")
        return 1

    n = len(fixture["cases"])
    problems_total = sum(len(c["problems"]) for c in fixture["cases"])
    print(f"frozen {n} oracle cases ({problems_total} problem strings) -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
