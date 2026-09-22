# Paleo Workbench

Paleogeographic map compilation desktop workbench.

**The production application is the native C++ product: `pwb-platform`**
(built from `apps/paleo_workbench_platform` + `libs/**`, Qt6 + vendored QGIS).
The original Python implementation is **retired to
[`legacy/python_reference/`](legacy/python_reference/)** — reference and
oracle use only, never shipped, never a runtime fallback. Python in this
repository now means **development tooling** (oracle/fixture generators,
migration/verification gates) plus the visualization and well-log engine
**submodules**:

| Submodule | Role | Public repo |
|-----------|------|-------------|
| `geo-viz-engine` | Map / geologic visualization packages | [WindWang2/geo-viz-engine](https://github.com/WindWang2/geo-viz-engine) |
| `well-log-engine` | C++20 well-log SDK + **WellPlot Desktop** host app | [WindWang2/well-log-engine](https://github.com/WindWang2/well-log-engine) |

See [`docs/development/python-retirement/`](docs/development/python-retirement/)
for the retirement ledger (inventory, classification, manifest).

## Building and running the product (C++)

Requirements: CMake ≥ 3.24, Ninja, Qt6 (6.8 line), a C++20 compiler
(GCC/Clang or MSVC 2022), and the vendored QGIS SDK (built once from
`third_party/qgis`; see below).

```bash
git submodule update --init geo-viz-engine well-log-engine

# Configure + build the native product (Linux example; see CMakePresets.json
# for windows-msvc / linux-ninja / native-product presets)
cmake --preset linux-native-product -DPALEO_QGIS_SDK_DIR=/path/to/qgis-sdk
cmake --build --preset linux-native-product -j 2

# Product smoke / diagnostics
QT_QPA_PLATFORM=offscreen build/native-product/bin/pwb-platform --self-check
build/native-product/bin/pwb-platform --capabilities
build/native-product/bin/pwb-platform --diagnostics
```

The reproducible gate that CI and release acceptance use is
`scripts/cpp-migration/final-closure-gate.sh [static|configure|build|test|package|runtime|all]`
(configure/build/test through the shared resource gate; install/deploy trees
are verified Python-free and archive-free).

### QGIS map stack (vendored)

The product's map area is carried by vendored QGIS 4.2 sources
(`third_party/qgis`), compiled into the native SDK that `libs/qgis` links
(`PwbQgis::Sdk`). Build the SDK once (hours on first build) via
`native/qgis_render_bridge` (CMake, `PALEO_WITH_QGIS_RENDERER=1`) or reuse an
existing `PALEO_QGIS_SDK_DIR`. The optional **pybind bridge** under
`native/qgis_render_bridge` (Python host) remains available as
development/compatibility tooling for the archived reference — it is never
part of the product binary.

## Development tooling environment (Python)

The Python environment provisions dev tooling only — oracle/fixture
generators (`tools/oracle/**`), migration/verification gates
(`tools/migration/**`, `tools/verify/**`), the remaining pytest suite, and
the geoviz submodule packages:

```bash
# From the repository root
git submodule update --init --recursive
python -m pip install -e ".[dev]"                  # pytest / pytest-qt + tooling deps
python -m pip install -r requirements-geoviz.txt   # editable geoviz_* packages
```

The distribution no longer packages any application code (no console
scripts, no `paleo_workbench` package — see `pyproject.toml`). Oracle
generators that need the retired implementation import it from
`legacy/python_reference/product` through the sanctioned shim
(`tools/oracle/_legacy_reference.py`); CTest always consumes frozen fixtures
and never launches Python.

### Optional native C++ kernels (`[native]`)

`native/grid_render_core`, `layer_model_core`, `seismic_3d_core`,
`well_log_core` (and `map_edit_core` in `geo-viz-engine`) are C++ kernels
whose Python hosts belonged to the retired implementation. They remain
buildable as development/compatibility packages (`python -m pip install -e
native/<name>`) and are covered by the remaining pytest contracts;
`native/qgis_render_bridge/src` additionally carries C++ sources that the
**product** links (`libs/qgis`).

## Tests

```bash
# Native product (CTest, via the resource gate)
scripts/cpp-migration/final-closure-gate.sh test

# Remaining Python dev-tooling suite (CI / headless)
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

The retired implementation's pytest suite lives with it under
`legacy/python_reference/tests/` and is not part of the default run.

## Qt display platform (Linux)

| Context | `QT_QPA_PLATFORM` |
|---------|-------------------|
| **Desktop app** (normal use) | **Unset** — on Wayland sessions Qt uses **wayland** (default today). |
| **CI / headless pytest / `--self-check`** | `offscreen` (not X11). |
| **XWayland debug only** | `xcb` plus `PALEO_FORCE_XCB=1` if the session is Wayland. |

Do **not** set `QT_QPA_PLATFORM=xcb` as a general default.

## Resource governance, Providers & Agent harness

These product capabilities are part of the native C++ product: resource
governance and platform services (`libs/platform_services`), the capability
provider SDK and plugin loading (`libs/providers`), and the geological agent
harness (`libs/closure_agent`, `libs/agent` line). The historical Python
implementations are retired (see the migration matrix at
`docs/development/cpp-final-closure/migration-matrix.md` for the per-module
native attribution).

## Well Log Workstation

Standalone log-first app (not the paleogeography workbench), living in the
`well-log-engine` submodule. See
[`well-log-engine/apps/wellplot-desktop/well_log_workstation/README.md`](well-log-engine/apps/wellplot-desktop/well_log_workstation/README.md).

```bash
# From the repository root: install the app, then run it
pip install -e well-log-engine/apps/wellplot-desktop
unset QT_QPA_PLATFORM   # Wayland session default
wellplot-desktop        # or: python -m well_log_workstation (from the app dir)
```
