# Python Retirement — Classification

Taxonomy, rules, and the notable decisions behind the 1897-file
classification in `01-python-inventory.md`.

## Classes

| Class | Meaning | Action |
|---|---|---|
| P1 LEGACY_PRODUCT_IMPLEMENTATION | retired Python product implementation, plus its tests, launchers, benchmarks-of-retired-code, and examples of its plugin API | `git mv` → `legacy/python_reference/product/…` (paths preserved) |
| P2 PYTHON_REFERENCE_ORACLE | oracle / frozen-fixture generators that use the Python implementation as semantic reference | keep in `tools/oracle`, `tests/cpp/**`, `libs/**/oracle`; import the archived reference via an explicit path shim |
| P3 ACTIVE_DEVELOPMENT_TOOL | migration matrix/inventory/audit/verify tooling, repo scripts, prototypes, doc-attached measurement scripts | keep, clearly dev-only |
| P4 COMPATIBILITY_BINDING | pybind compat hosts under `native/**` (C++ sources product-linked, setup.py hosts the optional Python build) | keep; seams' Python consumers are archived (known limitation) |
| P5 TEST_INFRASTRUCTURE | remaining pytest suite: C++ product support tests, native-extension contract tests, QGIS bridge tests, integrity guards | keep under `tests/` (never installed with the product) |
| P6 SCRATCH | `scratch/**`, `.scratch-*.py`, machine-specific one-off `.bat` runners | `git mv` → `legacy/python_reference/scratch/…` |
| P7 THIRD_PARTY | `third_party/**` (vendored QGIS scripts), `paleo_workbench/_vendored/**` | untouched in place / archived verbatim with the package |

## Key decisions

### D1 — The whole `paleo_workbench/` package retires as one unit (678 modules)

The per-module truth matrix attributes complete, wired, runtime-reachable
native replacements to 205 modules; 77 are PARTIAL_NATIVE and 395 are
LEGACY_REFERENCE at *module* granularity (1:1 unit attribution). At
*product* granularity the base branch (#1473) closes the final six product
gaps and the matrix records `python_runtime_required = 0` and
`python_modules_packaged = 0` — the native product neither runs nor ships
any of it. The old UI pages / app shell / domain modules classified
LEGACY_REFERENCE are exactly the "老 Python UI / application shell /
domain implementation" the retirement goal names as P1: their replacement
is the C++ `pwb-platform` application itself, not a per-file unit.

Therefore the package is archived **as a unit**, and the retirement
manifest records each module's honest per-module matrix classification
(NATIVE_PRODUCT / PARTIAL_NATIVE / LEGACY_REFERENCE / NOT_WIRED) plus its
attributed native targets — nothing is upgraded to "complete" without
matrix evidence. `paleo_workbench/_vendored/**` (vendored constrained-IDW
reference) goes with the package and is labeled P7-in-archive.

### D2 — Product-owned runtime assets are staged out first

`paleo_workbench/resources/{facies_taxonomy,facies_adjacency}.json` and
`paleo_workbench/ui/assets/icons/**` (148 SVGs) are **runtime assets of the
C++ product** (R1–R3 in the audit). They are `git mv`-ed to a new
native-owned `resources/` tree before the package moves. Reference copies
of the two JSONs and the icon set remain inside the archive so the archived
implementation stays importable/runnable as an oracle source. The manifest
marks these entries `asset_staging: product-owned`.

### D3 — The product's pytest suite archives with the product

826 test files (825 transitive closure + `test_perf_helpers.py`) test the
retired implementation; the wheel/catalog packaging tests
(`test_wheel_assets.py`, `test_build_catalog.py`) test packaging of the
retired package. They move to `legacy/python_reference/tests/` with paths
preserved, together with the original `tests/conftest.py`. The default
`pytest` run (testpaths `tests` + geoviz submodule suites) then covers only
active surfaces. Kept tests never import the archived package (verified by
the upward-closure scan; the `tests.qgis_support` product import is a
lazy `try/except` Windows helper that degrades to a no-op).

### D4 — Oracle tooling keeps working against the archive (P2)

78 `tools/oracle` generators, 6 `tests/cpp`/`libs/**/oracle` generators,
and 1 doc benchmark import the package. A single shim module
(`tools/oracle/_legacy_reference.py`, also used by the C++-side generators)
inserts `legacy/python_reference/product` on `sys.path` on demand. This is
dev-time only; CTest keeps consuming frozen fixtures and never launches
Python.

### D5 — Benchmarks/scripts that measure the retired implementation archive with it

`benchmarks/*` and `scripts/bench_*.py` that import the product measure
retired code; they archive under `legacy/python_reference/product/`
(paths preserved). Geoviz/native benchmarks (e.g.
`render_engine_benchmark.py`) stay. The perf-gate workflow drops the legs
whose subjects retired.

### D6 — `native/**` stays (P4)

`native/qgis_render_bridge/src` C++ is compiled into the product
(`libs/qgis`); the five `setup.py`s host optional pybind builds whose
consumers are the archived package — kept as compat/dev packaging, flagged
in known limitations. No C++ library is moved by this retirement.

### D7 — Launchers and scratch (E2, P6)

`run_app.py`, `run.bat`, `run-venv.bat`, `src/**` (retired "mainline"
entry scaffold) → archive/product. `.scratch-*.py` (8), `scratch/**` (48),
`run_main_batched.bat`, `run_main_suite_detached.bat` (machine-specific
one-offs) → archive/scratch. `build_catalog.py` + `tests/test_build_catalog.py`
(catalog builder for the retired UI icon library) → archive/product.
`svg_output/` (652 non-py design SVGs) stays in place this round — noted as
a follow-up candidate in known limitations (non-Python asset, out of scope).

### D8 — Nothing is deleted

Every archived file is a `git mv` (rename history preserved). Zero tracked
`.py` files are deleted by this retirement.
