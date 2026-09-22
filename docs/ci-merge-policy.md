# CI merge policy

Last updated 2026-09-15: PR-gate real-format smoke (#1230) added as a
required product gate; 3.13 remains observe-only.

## Product merge gates (required)

A PR is merge-ready when these are green on the head SHA:

| Gate | Workflow / job |
|------|----------------|
| **WellLogEngine C++ (Ubuntu)** | `WellLogEngine C++` — shared ON/OFF, ASan, Qt Mesa, wheels, vcpkg, benchmark as configured |
| **Full monorepo Tests (CPython 3.12)** | `CI` → `Tests` matrix on `ubuntu-latest` + `windows-latest` (both **required**; native extensions built on both legs) |
| **Well Log Workstation (host)** | `CI` → `Well Log Workstation (host)` (CPython 3.12) |
| **Real-format smoke (PR)** | `CI` → `Real-format smoke (PR)` — LAS/DAT/SEGY prepare() against tiny committed fixtures (`tests/fixtures/realdata/`, marker `realdata_smoke`); fail-closed, no skip-pass (#1230) |
| **Merge gate** | `CI` → `Merge gate (full monorepo + workstation)` — `needs:` the full Tests matrix, workstation host, and real-format smoke (the 3D OpenGL leg retired with the Python product suite — `docs/development/python-retirement/`) |

Cross-workflow: GitHub does not `needs:` across workflows; reviewers confirm **WellLogEngine C++** on the same commit as the CI host gate. The `WellLogEngine C++` workflow (`well-log-engine.yml`) is triggered on well-log-engine submodule **gitlink bumps** (paths cover the bare `well-log-engine` entry and `well-log-engine/**`), so any engine-pointer change re-runs it.

The full monorepo suite runs with `-m "not slow and not welllog_binding"` and
must be green **without
quarantine**: there is no `continue-on-error`, no advisory xfail registry
(`tests/advisory_xfail.py` is empty by design — do not grow it back), and no
"exit 124 is advisory" ceiling. A test that fails is a bug to fix, not a
reason to loosen the gate.

## WellLog binding contract (audit #917)

The workbench↔engine native contract (`tests/test_welllog_engine_native_integration.py`,
marker `welllog_binding`) needs a **built** welllog pybind module, which no CI
leg installs today — running it in the fast gate made the required gate
permanently red (#917). The gate therefore deselects the family but asserts
its collection (baseline 2: the contract + the #896 anti-vanishing guard), so
the contract cannot silently disappear. Execution happens where the binding is
built (developer environments; a future binding CI leg should select
`-m welllog_binding` and install `well-log-engine`).

## Slow tests (nightly leg, packaging #442)

The fast gate deliberately deselects the `slow` family (real-data vendor-format
smoke against the large `data/` tree + interpolation perf). They run only in the
dedicated `Slow tests (nightly)` workflow (`.github/workflows/slow-tests.yml`,
schedule + manual dispatch), which is fail-closed: it asserts the slow family
stays ≥ its baseline collected, and fails with an explicit error when the
representative `data/` tree is absent so the real-data tests can never
silently skip to green. The main `Tests` job runs the same collect guard. The
geoviz dependency install in `ci.yml` is fail-closed too — no `|| true`;
`requirements-geoviz.txt` is the single source of truth (the old eight-line
fallback list had drifted, missing `geoviz_well_seismic_3d`), followed by an
`import geoviz, geoviz_well_seismic_3d` smoke.

## Real-format smoke on PRs (#1230)

Nightly `slow` coverage of the large vendor `data/` tree is necessary but not
sufficient for merge safety: a PR that breaks LAS/DAT/SEGY prepare could still
green the fast gate and only fail overnight. Since 2026-09-15 the dedicated
`test-realdata-smoke` job runs `tests/test_geoviz_pr_realdata_smoke.py`
(`-m realdata_smoke`) against tiny committed fixtures under
`tests/fixtures/realdata/` (real format bytes, <<1 MB total). The job is
fail-closed, has no `continue-on-error` / `|| true`, and is in `merge-gate`
`needs`. Missing fixtures fail (no skip-pass). The nightly slow family remains
the home for large-tree / perf coverage. Product `requires-python` is
`>=3.12,<3.13`; 3.13 legs stay observe-only diagnostics — do not fail-close them.

## QGIS renderer coverage (opt-in, packaging #437)

The production-preferred QGIS renderer (`prefer_qgis=True` in
`paleo_workbench.mapping.map_render_backend`) requires the optional
`qgis_render_bridge` extension (vendored-QGIS build, `native/qgis_render_bridge`).
The main `CI` `Tests` matrix **does not cover it**: it installs neither QGIS
nor the bridge, so the fallback renderer is the effectively-gated path and
all QGIS tests (marker `qgis`, 9 sites) self-skip there.

Coverage statement: QGIS bridge changes are gated by the dedicated
`QGIS renderer` workflow (`.github/workflows/qgis-renderer.yml`) — fail-closed
build + import smoke + vendor-integrity checks plus the ``qgis``-marked test
execution (≥9 tests collected and executed) when the bridge is built,
triggered on manual dispatch or on paths
`native/qgis_render_bridge/**` / `third_party/qgis/**`. The main `CI` `Tests`
matrix still has no QGIS runtime leg, so all ``qgis`` tests self-skip there
— that split is intentional (see #437, #935). Any QGIS-path change must keep
the `qgis` marker selection intact — both the doc baseline and the workflow's
``≥ 9`` collect+pass gate enforce it.

## Windows WellLogEngine

**Windows source checkout of the monorepo is clean (packaging #441 resolved
upstream):** the geo-viz-engine rename landed and the pinned gitlink contains
no Windows-invalid filenames, so `git submodule update --init --recursive`
succeeds on windows-latest. Workflow jobs that only need the engine still
init just the `well-log-engine` submodule — a deliberate scope choice (the
sibling geo-viz-engine checkout is unnecessary build time for those jobs),
no longer a filesystem workaround. The main CI `Tests` job runs a guard step
(with a local twin in `tests/test_workflow_integrity.py`) that fails on any
Windows-invalid submodule path, so a broken gitlink can never be re-pinned
silently. The application CI (ci.yml) runs the remaining Python dev-tooling suite on **both `ubuntu-latest` and `windows-latest`** (CPython 3.12; 3.13 diagnostic legs remain `ubuntu-latest`-only, #951). **Python-retirement note (2026-09-22):** the retired product's pytest suite (incl. the `opengl`/`welllog_binding` families and the crash-prone teardown pair) moved to `legacy/python_reference/tests/` and left the default run; the `test-3d-opengl` leg was removed with them (docs/development/python-retirement/). Linux-only steps (vendored GDAL, native C++ selftests, Mesa/Xvfb + `LIBGL_ALWAYS_SOFTWARE`/`GALLIUM_DRIVER`) are gated with `if: runner.os == 'Linux'`; the Windows leg runs the same `pytest -m "not slow and not welllog_binding"` suite with `QT_QPA_PLATFORM=offscreen` / `QT_OPENGL=software` (#1045, packaging #441 no longer blocks Windows checkouts). Since 2026-08-29 (#1111) the `windows-latest` row is a **required** gate again: the five native extensions build under MSVC on the leg, and the platform divergences found during convergence are fixed (POSIX-only absoluteness heuristics in audit/readiness, read-only blob deletion, Windows thread-termination probing via `WaitForSingleObject`, corrupt-flow forensic rename vs deferred-handle close, `tests/perf` moved to the nightly on both legs — fsync-heavy budgets cannot hold the fast gate's 45s per-test ceiling under runner load; `test_catalog_scale.py` joined the `slow` family so the nightly's 300s ceiling owns it).

**Status (as of #236):** matrix row **re-enabled** (`os: [ubuntu-latest, windows-latest]`) for `shared=OFF` and `shared=ON` in `.github/workflows/well-log-engine.yml`. Windows path runs with `WELLLOG_BUILD_TEXT=OFF` and `WELLLOG_BUILD_ARROW=OFF` (HarfBuzz/FreeType/ICU and Arrow not on stock Windows runners), `WELLLOG_WARNINGS_AS_ERRORS=OFF`, and a locally built zlib prefix.

Code staged in #234 that makes the Windows build clean:

- Text-linked tests gated with `if(WELLLOG_BUILD_TEXT)` (multi-scale, PDF scene, export-parity), so `popen`/`pclose`/`M_PI` usage in those files never compiles on Windows.
- `pdf_spike_test.cpp` (always built) uses `_popen`/`_pclose` under `#if defined(_WIN32)`.
- MSVC portability: `std::numbers::pi_v` (no `M_PI`), C4251/C4275 suppress, shadow renames (C4456), `WELLLOG_SCENE_API` on multi-well friends.
- Workflow helpers: zlib prefix, empty `VCPKG_ROOT` ignored, Ninja path pinned after `msvc-dev-cmd` (Git Bash hangs under msvc-dev-cmd env, so Windows steps use `cmd`).

**Python wheels remain Ubuntu-only** (Shiboken6/Qt aqt on Windows still open).

## Hang prevention

- Prefer stubbing **all** `QMessageBox` / modal dialogs in headless tests.
- Per-test: `--timeout-method=thread` on monorepo and workstation jobs.
- Job-level timeouts (`Tests`: 60m; workstation: 20m) act as the backstop for
  native hangs; a green suite fits well inside them.

## Related

- Issue #236 — re-enable Windows WellLogEngine CI matrix
- Issue #234 — Windows CI + advisory suite cleanup
- PR #233 — Well Log Workstation phase-1 + engine bridge
- Map #207 — wayfinder product map (closed)

## Review follow-up (2026-09-13)

QGIS renderer path filters now also include paleo_workbench/ui/workstation/** and paleo_workbench/qgis_runtime/** so 编图 host / runtime loader changes re-run the bridge gate.

## Review follow-up (2026-09-15)

PR merge gate now includes real-format smoke (`test-realdata-smoke`, #1230):
tiny in-tree LAS/DAT/SEGY fixtures exercise GeoVizEngine.prepare on every PR.
The slow vendor-data family stays nightly; 3.13 remains observe-only.
