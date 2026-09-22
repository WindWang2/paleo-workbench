#!/usr/bin/env python3
"""Build the per-module C++ final-closure migration truth matrix."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


CLASSIFICATIONS = (
    "NATIVE_PRODUCT",
    "NATIVE_LIBRARY_NOT_WIRED",
    "PARTIAL_NATIVE",
    "ORACLE_DEV_ONLY",
    "LEGACY_REFERENCE",
    "UNSUPPORTED_BY_DESIGN",
    "DEAD_REMOVAL_CANDIDATE",
)

STATUS_CLASSIFICATION = {
    "native_complete_wired": "NATIVE_PRODUCT",
    "native_core_not_wired": "NATIVE_LIBRARY_NOT_WIRED",
    "partial_native": "PARTIAL_NATIVE",
    "legacy_deprecated_candidate": "LEGACY_REFERENCE",
}

CLASSIFICATION_PRIORITY = {
    "PARTIAL_NATIVE": 0,
    "NATIVE_LIBRARY_NOT_WIRED": 1,
    "NATIVE_PRODUCT": 2,
    "ORACLE_DEV_ONLY": 3,
    "UNSUPPORTED_BY_DESIGN": 4,
    "LEGACY_REFERENCE": 5,
    "DEAD_REMOVAL_CANDIDATE": 6,
}


def load_inventory_module(repo_root: Path) -> Any:
    path = repo_root / "tools/migration/pwb_migration_inventory.py"
    spec = importlib.util.spec_from_file_location("pwb_migration_inventory", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration inventory generator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def line_evidence(repo_root: Path, relative_path: str, needle: str) -> str:
    path = repo_root / relative_path
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if needle in line:
                return f"{relative_path}:{number}"
    except OSError:
        pass
    return relative_path


def python_product_dir(repo_root: Path) -> Path:
    """The retired package dir: active tree first, else the archive
    (legacy/python_reference/product/paleo_workbench — retired with the
    Python retirement; paths are reported in their pre-retirement form)."""
    active = repo_root / "paleo_workbench"
    if active.is_dir():
        return active
    return repo_root / "legacy" / "python_reference" / "product" / "paleo_workbench"


def python_modules(repo_root: Path) -> list[str]:
    root = python_product_dir(repo_root)
    prefix = "paleo_workbench/"
    return sorted(
        prefix + path.relative_to(root).as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def target_names(unit: dict[str, Any]) -> list[str]:
    """All native target identities of a unit: every Pwb:: alias plus every
    bare add_library name (#1448: a single unit may expose several aliases and
    wiring may go through any of them)."""
    names: list[str] = []
    for key in ("aliases", "targets", "alias", "target"):
        value = unit.get(key)
        if isinstance(value, str):
            value = [value]
        for name in value or []:
            if name and name not in names:
                names.append(name)
    return names


def classify(units: list[dict[str, Any]]) -> str:
    if not units:
        return "LEGACY_REFERENCE"
    candidates = {
        STATUS_CLASSIFICATION.get(unit["status"], "PARTIAL_NATIVE")
        for unit in units
    }
    return min(candidates, key=CLASSIFICATION_PRIORITY.__getitem__)


def build_matrix(repo_root: Path) -> dict[str, Any]:
    inventory_module = load_inventory_module(repo_root)
    inventory = inventory_module.build_inventory(str(repo_root))
    units_by_origin: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for unit in inventory["units"]:
        for source in unit["python_origins_present"]:
            units_by_origin[source].append(unit)

    app_cmake = "apps/paleo_workbench_platform/CMakeLists.txt"
    source_audit = "scripts/cpp-migration/audit-python-runtime-deps.sh"
    install_cmake = "cmake/PwbInstall.cmake"
    rows: list[dict[str, Any]] = []
    for source in python_modules(repo_root):
        units = sorted(units_by_origin.get(source, []), key=lambda unit: unit["unit"])
        classification = classify(units)
        targets = sorted({name for unit in units for name in target_names(unit)})
        wired_units = [unit for unit in units if unit["wired"]]
        # TU-level product consumer evidence (#1448 A-2): linked alone is not
        # product wiring; a product TU must actually include the unit's public
        # headers for runtime_reachable to hold.
        tu_reachable_units = [unit for unit in units if unit.get("tu_reachable")]
        tests = sorted({test for unit in units for test in unit["tests"]})
        fixtures = sorted({fixture for unit in units for fixture in unit["fixtures"]})
        wiring_evidence = sorted(
            {evidence for unit in wired_units for evidence in unit["wiring_evidence"]}
        )

        target_exists = bool(targets)
        product_wired = classification == "NATIVE_PRODUCT" and bool(
            tu_reachable_units
        )
        target_built = False
        runtime_reachable = product_wired
        oracle_covered = bool(fixtures)
        product_tested = False

        evidence = []
        if units:
            evidence.extend(
                f"{unit['root_dir']}/CMakeLists.txt ({unit['status']})"
                for unit in units
            )
            evidence.extend(wiring_evidence[:4])
            evidence.extend(fixtures[:2])
            if tu_reachable_units:
                sample_consumers = sorted(
                    {c for unit in tu_reachable_units for c in unit.get("tu_consumers", [])}
                )[:4]
                evidence.append(
                    "TU consumers: " + (", ".join(sample_consumers) or "—")
                )
        else:
            evidence.append(
                "No native origin attribution in the generated libs/* inventory"
            )
        evidence.append(line_evidence(repo_root, source_audit, "Python C API"))
        evidence.append(line_evidence(repo_root, install_cmake, "FILES_MATCHING"))

        if classification == "NATIVE_PRODUCT":
            remaining_action = (
                "Retired: the module now lives under "
                "legacy/python_reference/product (reference only; oracle "
                "generators reach it through the sanctioned shim)."
            )
        elif classification == "NATIVE_LIBRARY_NOT_WIRED":
            remaining_action = (
                "Add a product entry point, composition-root service binding, "
                "runtime audit, and product-level test before claiming support."
            )
        elif classification == "PARTIAL_NATIVE":
            remaining_action = (
                "Complete the missing native behavior and oracle parity before "
                "wiring it into the product."
            )
        else:
            remaining_action = (
                "Keep isolated from the native package; remove only after a "
                "separate import/reference audit proves it is dead."
            )

        rows.append(
            {
                "python_source": source,
                "native_target": targets,
                "native_target_exists": target_exists,
                "native_target_built": target_built,
                "product_wired": product_wired,
                "runtime_reachable": runtime_reachable,
                "oracle_covered": oracle_covered,
                "product_tested": product_tested,
                "packaged": False,
                "python_runtime_required": False,
                "final_classification": classification,
                "evidence": evidence,
                "remaining_action": remaining_action,
            }
        )

    counts = Counter(row["final_classification"] for row in rows)
    return {
        "schema_version": 2,
        "scope": "all tracked paleo_workbench/**/*.py modules",
        "policy": {
            "classification_vocabulary": list(CLASSIFICATIONS),
            "native_product_rule": (
                "Every attributed native unit for the Python module must be "
                "classified native_complete_wired, which since schema 2 "
                "requires TU-level consumer evidence: the unit must be linked "
                "into the pwb-platform closure through an unconditional path "
                "AND at least one product translation unit must include its "
                "public headers. A partial or unwired attribution wins over a "
                "wired attribution."
            ),
            "build_evidence_rule": (
                "The committed matrix does not infer a successful build or "
                "test run from CMake declarations. native_target_built and "
                "product_tested remain false until a provisioned acceptance "
                "run supplies revision-specific evidence."
            ),
            "runtime_reachability_rule": (
                "runtime_reachable records static reachability from the "
                "native composition root (target link or host definition), "
                "not successful execution on the current revision. Runtime "
                "execution evidence is represented by product_tested."
            ),
            "unattributed_rule": (
                "An existing Python production module with no native origin "
                "attribution remains LEGACY_REFERENCE; it is not called dead "
                "without a separate import/reference proof."
            ),
            "packaging_rule": (
                "Python modules are excluded from the native install tree; "
                "packaged therefore describes the Python source, not its "
                "native replacement."
            ),
        },
        "summary": {
            "python_modules": len(rows),
            "unique_python_modules": len({row["python_source"] for row in rows}),
            "classification_counts": {
                classification: counts.get(classification, 0)
                for classification in CLASSIFICATIONS
            },
            "native_targets": len(
                {
                    target
                    for row in rows
                    for target in row["native_target"]
                }
            ),
            "python_runtime_required": sum(
                bool(row["python_runtime_required"]) for row in rows
            ),
            "python_modules_packaged": sum(bool(row["packaged"]) for row in rows),
        },
        "rows": rows,
        "evidence_roots": {
            "migration_inventory": "tools/migration/pwb_migration_inventory.py",
            "product_composition_root": app_cmake,
            "python_runtime_audit": source_audit,
            "native_install_rules": install_cmake,
        },
    }


def render_markdown(matrix: dict[str, Any]) -> str:
    summary = matrix["summary"]
    out = [
        "# C++ Final Closure Migration Matrix (generated)",
        "",
        "Generated by `tools/migration/pwb_final_closure_matrix.py`. "
        "Do not hand-edit.",
        "",
        f"Scope: **{summary['python_modules']}** unique Python modules. "
        f"Native product runtime requirements: "
        f"**{summary['python_runtime_required']}**. Python modules installed "
        f"by the native package: **{summary['python_modules_packaged']}**.",
        "",
        "## Classification roll-up",
        "",
        "| Classification | Count |",
        "| --- | ---: |",
    ]
    for classification in CLASSIFICATIONS:
        out.append(
            f"| `{classification}` | "
            f"{summary['classification_counts'][classification]} |"
        )
    out.extend(
        [
            "",
            "## Per-module truth",
            "",
            "| Python source | Native target | Built | Wired | Reachable | "
            "Oracle | Product test | Packaged | Python runtime | Classification |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in matrix["rows"]:
        targets = "<br>".join(f"`{target}`" for target in row["native_target"]) or "—"
        yes = lambda value: "yes" if value else "no"
        out.append(
            f"| `{row['python_source']}` | {targets} | "
            f"{yes(row['native_target_built'])} | {yes(row['product_wired'])} | "
            f"{yes(row['runtime_reachable'])} | {yes(row['oracle_covered'])} | "
            f"{yes(row['product_tested'])} | {yes(row['packaged'])} | "
            f"{yes(row['python_runtime_required'])} | "
            f"`{row['final_classification']}` |"
        )
    out.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `NATIVE_PRODUCT` means the native target is linked by the formal "
            "composition root; it does not mean the legacy Python file may be "
            "deleted immediately.",
            "- `NATIVE_LIBRARY_NOT_WIRED` is deliberately not reported as product "
            "support. A target and unit tests alone are insufficient.",
            "- `LEGACY_REFERENCE` is conservative. No module is marked dead without "
            "a separate import/reference proof.",
            "- `packaged=no` and `python_runtime_required=no` apply to every Python "
            "row because the native install rules exclude Python sources and the "
            "native binary audit rejects Python runtime seams.",
        ]
    )
    return "\n".join(out)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument(
        "--json-out",
        default="docs/development/cpp-final-closure/migration-matrix.json",
    )
    parser.add_argument(
        "--markdown-out",
        default="docs/development/cpp-final-closure/migration-matrix.md",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    matrix = build_matrix(repo_root)
    json_path = Path(args.json_out)
    markdown_path = Path(args.markdown_out)
    if not json_path.is_absolute():
        json_path = repo_root / json_path
    if not markdown_path.is_absolute():
        markdown_path = repo_root / markdown_path
    write_text(json_path, json.dumps(matrix, ensure_ascii=False, indent=2) + os.linesep)
    write_text(markdown_path, render_markdown(matrix) + os.linesep)
    print(
        f"matrix: {matrix['summary']['python_modules']} modules, "
        f"{matrix['summary']['classification_counts']['NATIVE_PRODUCT']} native product"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
