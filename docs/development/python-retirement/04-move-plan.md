# Python Retirement — Move Plan

Archive layout (paths under the original repo root are preserved verbatim
after the `product/` prefix — no flattening):

```text
legacy/python_reference/
├── README.md                     # non-runtime declaration (EN + 中文)
├── MANIFEST.md                   # human summary of the classes below
├── product/                      # retired product implementation
│   ├── paleo_workbench/…         # 678 modules (minus staged assets)
│   ├── run_app.py
│   ├── run.bat / run-venv.bat
│   ├── build_catalog.py
│   ├── src/…
│   ├── benchmarks/… scripts/…    # benchmark/dev scripts of retired code
│   └── examples/provider_plugins/…
├── tests/                        # 826 product pytest files + original conftest
├── scratch/                      # scratch/**, .scratch-*.py, one-off .bat
└── metadata/retirement_manifest.json
```

## Ordered execution

1. **Stage product assets (git mv, pre-archive)**
   - `paleo_workbench/resources/facies_taxonomy.json` → `resources/facies_taxonomy.json`
   - `paleo_workbench/resources/facies_adjacency.json` → `resources/facies_adjacency.json`
   - `paleo_workbench/ui/assets/icons/**` → `resources/ui/assets/icons/**`
   - Restore reference copies of the three asset groups inside the archive
     after step 2 (plain `git add`, marked `asset_staging: reference-copy`).
2. **Package + entries (git mv)** — `paleo_workbench/`, `run_app.py`,
   `run.bat`, `run-venv.bat`, `build_catalog.py`, `src/`, retired
   `benchmarks/*`, retired `scripts/bench_*.py`, `examples/provider_plugins/*.py`.
3. **Product tests (git mv)** — the 828-file closure (825 transitive +
   `test_perf_helpers.py` + `test_wheel_assets.py` + `test_build_catalog.py`)
   plus a bootstrap-prepended copy of the original `tests/conftest.py` →
   `legacy/python_reference/tests/…`; the active `tests/conftest.py` is
   rewritten trimmed (no product imports).
4. **Scratch (git mv)** — `scratch/`, `.scratch-*.py`,
   `run_main_batched.bat`, `run_main_suite_detached.bat`.
5. **Archive metadata** — `README.md`, `MANIFEST.md`,
   `metadata/retirement_manifest.json` (generated from the inventory JSON +
   migration matrix; per-file class + native attribution, no fabricated
   replacements).
6. **Build/packaging cleanup** — `cmake/PwbInstall.cmake` resource entries →
   `resources/`; `resource_locator.cpp` drop the `paleo_workbench` probe;
   `test_platform_services.cpp` assertion; `pyproject.toml` drop script +
   package find/data.
7. **Tooling detach** — archive-path shim for oracle generators;
   archive-root fallback in the three migration tools; `perf-gate.yml` /
   `ci.yml` leg adjustments.
8. **Gates** — `scripts/cpp-migration/check-python-retirement.sh`:
   (a) no `legacy/python_reference` path in CMake product sources/install
   manifests/launchers; (b) product link set free of Python C API /
   libpython / python subprocess; (c) native install/deploy trees `.py = 0`;
   wired into `final-closure-gate.sh` static stage.
9. **Docs** — README canonical entry, retirement notes, ledger 05–09.

## Non-goals (unchanged)

No C++ feature work, no UI/QGIS refactor, no algorithm changes, no
submodule/vendor edits, no deletions of tracked Python sources.
