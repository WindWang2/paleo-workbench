# Python Retirement — Phase 2 Dependency Audit

How the active product/build/test/doc surfaces depend on the Python tree at
base `0936779e`, and what each dependency implies for the retirement.

## 1. C++ runtime → Python tree (must be severed)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| R1 | The product resource locator probes `<source>/paleo_workbench` as a dev-tree resources root (canonical icon set) | `libs/platform_services/src/resource_locator.cpp:36-44` (`source_candidates << PWB_SOURCE_DIR + "/paleo_workbench" << PWB_SOURCE_DIR + "/resources"`) | Stage a native-owned `<source>/resources/` tree (facies JSONs + `ui/assets/icons/**`) and drop the `paleo_workbench` probe |
| R2 | `resource_file("ui/assets/icons/<name>")` resolves icons that live inside the Python package | `libs/ui_widgets/src/icon_factory.cpp:40-43`; 148 SVGs under `paleo_workbench/ui/assets/icons/` | Move the icon tree into `<source>/resources/ui/assets/icons/` (git mv, history preserved); duplicate reference copies stay in the archive so the archived implementation remains importable for oracles |
| R3 | Builtin facies vocabulary reads `<resources>/facies_taxonomy.json` (+ `facies_adjacency.json`) from the Python package dir | `libs/ui_widgets/include/pwb/ui_widgets/core/facies_taxonomy.hpp:8,48`; assets at `paleo_workbench/resources/*.json` | Same staging: `git mv` both JSONs to `<source>/resources/`; reference copies remain in archive |
| R4 | Platform-services test encodes the `paleo_workbench` dev-tree probe as a contract | `tests/cpp/platform/test_platform_services.cpp:565-570` | Update the assertion to the new `<source>/resources` staging |
| R5 | C++ product link closure is already Python-free (source + ldd audits exist) | `scripts/cpp-migration/audit-python-runtime-deps.sh` (source scan of apps/libs product paths + `ldd` closure over pwb-platform) | Keep as a retirement gate; extend with an archive-isolation half |

No `Python.h` / `Py_Initialize` / pybind usage exists in the product link
set; pybind is confined to the two compat seams (`libs/mapping_bind`,
`libs/cartography/cartography_bind`) that are consumed *by* Python and never
linked into `pwb-platform` (verified by the same audit script).

## 2. CMake install / packaging (must not pick up the archive)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| B1 | `pwb_install_resources()` installs `paleo_workbench/{resources,templates,icons}` (+ `*schema*` glob) into `share/paleo-workbench` (py files excluded; absent dirs skipped) | `cmake/PwbInstall.cmake:118-158` | Re-point at the new `<source>/resources` tree; delete the `paleo_workbench` entries and schema glob |
| B2 | Install/deploy trees are already gated Python-free (fail on any `.py`/`.pyc`) | `scripts/cpp-migration/final-closure-gate.sh` `run_package` | Keep; extend the gate with an explicit archive-isolation check |
| B3 | `native/qgis_render_bridge/src/*.cpp` is product-linked (`libs/qgis` compiles `layout_spec_exec.cpp` under `PWB_BUILD_CONV_29`; headers consumed by ui_canvas/ui_composite/ui_wellseis) | `libs/qgis/CMakeLists.txt:39-45` | `native/**` stays active (P4). Its `setup.py`s host the optional pybind build; the C++ sources are product code |

## 3. Python tooling → retired package (keep working, dev-time only)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| T1 | 78/93 `tools/oracle/generate_*.py` import `paleo_workbench` as the reference implementation | `rg -l 'from paleo_workbench' tools/` → 78 files | Keep tools (P2); add an explicit archive-path shim (`tools/oracle/_legacy_reference.py`) so dev-time generation keeps importing the archived reference; CTest stays Python-independent via frozen fixtures |
| T2 | 6 oracle generators under `tests/cpp/**` + `libs/**/oracle/` also import the package (e.g. `tests/cpp/platform/make_golden.py`, `tests/cpp/science/oracle/generate_seismic_fixture.py`) | inventory `imports_product` flags | Same shim treatment (they are C++-test fixture generators, run by developers not by CTest) |
| T3 | Migration truth tooling scans `paleo_workbench/` on disk: `pwb_final_closure_matrix.py::python_modules()`, `pwb_migration_inventory.py` (pkg join at :722), `pwb_python_dependency_audit.py` (path prefixes at :203/:248) | tool sources | Add archive-root fallback resolution (active dir, else `legacy/python_reference/product/paleo_workbench`), reporting original relative paths so the matrix/inventory stay meaningful |
| T4 | `tests/conftest.py` imports `paleo_workbench.qt_platform` in `pytest_configure` (suite-wide) and `paleo_workbench.qgis_runtime.loader` in a Windows-only lazy hook | `tests/conftest.py:63-67,124-130` | Original conftest moves with the archived suite; the remaining suite gets a trimmed conftest (inline Qt-platform policy, no product imports) |
| T5 | `tests/qgis_support.py`'s product import is lazy inside `try/except` (Windows DLL dirs helper) | `tests/qgis_support.py:29-36` | Keep as-is: degrades to a no-op when the package is archived |

## 4. Product entry points / packaging metadata (must flip to C++-only)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| E1 | `pyproject.toml` registers console script `paleo-workbench = paleo_workbench.main:main`, packages `paleo_workbench*`, and ships package-data from the package | `pyproject.toml` `[project.scripts]`, `[tool.setuptools.*]` | Drop script + package find/data; keep the dev extras + pytest config (now serving dev tooling and the remaining suite) |
| E2 | Root launchers `run.bat`, `run-venv.bat`, `run_app.py` launch the Python app; `run_main_batched.bat` / `run_main_suite_detached.bat` are machine-specific one-offs | root files | Archived with the product (`run.bat`-class) or to scratch (batched/detached one-offs) |
| E3 | README "Running the Application" documents `paleo-workbench` / `python -m paleo_workbench` as the entry | `README.md` | Rewrite: `pwb-platform` (C++) is the product; Python is reference/tooling only |

## 5. Tests / CI (split, then re-anchor)

| # | Finding | Evidence | Disposition |
|---|---|---|---|
| C1 | 822/908 `tests/*.py` import `paleo_workbench` directly; +3 transitively via `tests.*` helpers (825 closure) + `tests/test_perf_helpers.py` via `tests.perf.fixtures` | inventory closure | Move the product suite to `legacy/python_reference/tests/` (paths preserved); default `pytest` no longer treats archived code as product |
| C2 | Post-split marker coverage on kept tests: `slow` 3, `qgis` 34, `realdata_smoke` 1 — but `opengl` 0, `welllog_binding` 0 | marker scan | Adjust ci.yml's fail-closed presence checks for `opengl`/`welllog_binding` (families retired with the product); note in known limitations |
| C3 | `perf-gate.yml` runs `pytest -m slow tests/perf/` (thresholds in `test_interpolation_perf.py`, which imports the product) and two benchmark scripts (`bench_interpolation.py`, `render_engine_benchmark.py` — both import the retired implementation) | `.github/workflows/perf-gate.yml` | Retire both benchmark legs; the gate keeps the geoviz slow perf suite (`tests/perf`) |
| C4 | `tests/test_workflow_integrity.py` / `tests/e2e/test_integrity_guard.py` (CI guard twins) do not reference moved paths | rg audit | Keep unchanged |
| C5 | `tests/cpp/**` fixtures (631 non-py files) are C++ CTest inputs | `git ls-files tests/cpp` | Keep unchanged |

## 6. Docs / compatibility seams (record, don't over-reach)

- `libs/mapping_bind` + `libs/cartography/cartography_bind` are C++ pybind
  compat seams consumed by the *archived* Python side
  (`paleo_workbench/mapping/cartography_native.py`,
  `paleo_workbench/mapping/geological_pipeline/native_bind.py`). The C++
  seams stay (out of scope for Python retirement; off by default,
  whitelisted in the runtime audit). Recorded as a known limitation: their
  only consumers are now archived.
- Migration-history docs (`docs/development/cpp-*/…`) keep their historical
  statements; the retirement adds status notes where a reader could mistake
  the Python tree for a live product.
- Submodules `geo-viz-engine`, `well-log-engine` and vendored
  `third_party/qgis`, `third_party/{gdal,proj}` are untouched (P7).
