# Python Retirement — Final Report

Branch `chore/archive-legacy-python-product`, stacked on `0936779e`
(PR #1473 head). All numbers generated from the actual tree/diff at PR
time (scripts inline in this ledger's history; no estimates).

## Repository semantics achieved

```text
ACTIVE PRODUCT      C++ (apps/ + libs/** → pwb-platform), resources/ assets
DEVELOPMENT TOOLING Python allowed where justified (tools/oracle,
                    tools/migration, tools/verify, tests support, native
                    extension hosts)
LEGACY REFERENCE    legacy/python_reference/** (product/tests/scratch,
                    metadata manifest; non-runtime by declaration and gate)
```

## Inventory (baseline 1897 tracked .py → final 1900)

| Class | Baseline | Final state |
|---|---|---|
| legacy product implementation (+tests/launchers/benchmarks/examples) | 1529 (+1 conftest copy) | archived |
| oracle/reference generators (P2) | 104 | **kept active** (94 tools/oracle + 6 tests/cpp + 5 libs/oracle oracle pieces… incl. the new shim module) |
| active development tooling (P3) | 18 | kept |
| compatibility bindings / pybind hosts (P4) | 6 | kept (native/**; C++ sources product-linked) |
| active test infrastructure (P5) | 77 | kept (73 tests/ + 6 tests/cpp generators, post-amendment) |
| scratch / one-off (P6) | 56 | archived |
| third-party (P7) | 107 | 98 third_party untouched; 9 package-vendored archived with the package |

## Moves and final shape

- `git mv` renames vs base: **1760** · tracked-file deletions: **0** ·
  additions: 165 (150 archive reference-copy assets + manifest + ledgers +
  shim + gates + trimmed conftest + archive qgis_support copy) ·
  modifications: 123.
- `legacy/python_reference/`: 1765 files (1600 .py:
  678 product package + 831 product tests + 56 scratch + 35 product
  extras; plus assets/metadata).
- Product-owned runtime assets staged to `resources/` (150 files: 2 facies
  JSONs + 148 SVG icons; git-mv history; installed to
  `share/paleo-workbench/resources`).
- Retirement manifest: `legacy/python_reference/metadata/retirement_manifest.json`
  (schema 2; per-file record with verbatim matrix attributions — 208
  NATIVE_PRODUCT / 79 PARTIAL_NATIVE / 390 LEGACY_REFERENCE / 1 NOT_WIRED;
  3 review amendments recorded; nothing fabricated).

## Runtime independence (measured)

| Audit | Result |
|---|---|
| Product source scan (Python C API / PySide / python subprocess) | clean |
| pybind11 outside the two compat seams | clean |
| `ldd` closure of built `pwb-platform` | **python-free** |
| Product self-check `python_free_process` | **verified** (13/13 checks) |
| Native install tree `.py`/`.pyc` count | **0** |
| Native install/deploy tree `legacy/` paths | **0** |
| Active-tree importers of the retired package outside the sanctioned shim | **0** (gate-enforced) |

## Gates

- `scripts/cpp-migration/check-python-retirement.sh` (new): archive
  isolation (effective-code, normalized path pattern), tree shape,
  sanctioned-bridge, install purity — **PASS**, wired into
  `final-closure-gate.sh` (static + package stages).
- final-closure gate stages executed locally: **static PASS · configure
  PASS · build PASS (pwb-platform + full 870-step tree) · test PASS
  (focused 68/68 ×2; full 244/246 — 2 ONNX-runtime-environment fails) ·
  package PASS (deployed-tree self-check 13/13) · runtime PASS**.

## Documentation

README rewritten (C++ canonical entry `pwb-platform`); historical docs
(PROJECT/CONTEXT/TEST_INFRA) carry retirement banners; ci-merge-policy and
workflow narrations updated; this ledger 00-09 complete.

## CI statement

Local verification completed. Online CI was not required or awaited for
this goal; the workflows were adjusted for the retirement and their first
online runs should be watched after merge (K6).
