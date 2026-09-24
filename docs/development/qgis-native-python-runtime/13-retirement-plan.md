# QGIS Native Python Runtime — Retirement / Non-Regression Plan

Date: 2026-09-23 · Base: `192422c60`

## 1. What is already retired (do not re-animate)

The legacy Python **product** stack was archived by
`chore/archive-legacy-python-product` (PR #1477, closed) with the ledger in
`docs/development/python-retirement/`:

| Class | Meaning | State |
|---|---|---|
| P1 | retired Python product implementation (1 529 files) | archived to `legacy/python_reference/product/` |
| P2 | oracle / frozen-fixture generators | kept, dev-only |
| P3 | active development tooling | kept |
| P4 | **pybind compatibility hosts under `native/**`** (6 files) | **kept** — see §2 |
| P5 | test infrastructure | kept |
| P6/P7 | scratch / third-party | archived / untouched |

Gate #7 of the goal spec ("did you restore the legacy Python product
implementation?") is answered by this ledger plus this document: **nothing in
this branch imports `legacy/**`, and no Python product implementation is
restored.**

## 2. The one thing that could become a second runtime

The retirement ledger itself flags the open end:

> P4 COMPATIBILITY_BINDING — pybind compat hosts under `native/**` … kept;
> seams' Python consumers are archived (**known limitation**).

Those hosts are the only remaining place where paleo binds Python by itself.
Rules this branch imposes on them:

| Rule | Statement |
|---|---|
| R1 | a pybind host may keep serving *packaging/compat* purposes; it must never become the product's Python runtime |
| R2 | it must not initialise an interpreter when `PALEO_WITH_QGIS_PYTHON` is `ON` — one process, one Python runtime |
| R3 | it must not expose a second plugin/script/algorithm registry |
| R4 | if a pybind host and the QGIS runtime would both bind the same domain object, the QGIS/PyQGIS side wins and the pybind seam is deprecated in this ledger |

Nothing is deleted in this branch: deleting the hosts is a separate, separable
change. The rule is that they cannot be the runtime, and that is enforced by
the single-initialisation test (`test_qgis_python_bootstrap`, "init once only").

## 3. Non-regression guarantees of this branch

| # | Guarantee | How it is held |
|---|---|---|
| N1 | no second CPython initialisation | gate #1; no `Py_Initialize` anywhere in paleo code (checked in `14`) |
| N2 | no paleo venv/conda runtime | gate #2; `10-packaging-platform-matrix.md` §4 |
| N3 | one `QgsProject` | Python resolves `QgsProject.instance()`, never a copy |
| N4 | one processing registry | `08` §1 |
| N5 | one plugin lifecycle | `07` §1 |
| N6 | no second console/editor/REPL | `06` §6 |
| N7 | legacy Python product stays archived | §1 |
| N8 | no silent execution of project Python | `09` §4 |
| N9 | ABI agreement (QGIS / PyQGIS / Python / PyQt6 / SIP) | `10` §3, reported by the diagnostics panel |
| N10 | missing runtime degrades, never crashes | `04` §5, `test_qgis_python_missing_library` |

## 4. What "retiring" does **not** mean here

- it does not mean removing Python from paleo — Python becomes an extension
  runtime, which is the point of the whole work;
- it does not mean removing the pybind hosts' packaging role;
- it does not mean reclassifying archived oracles as supported API.
