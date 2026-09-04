# Paleo Workbench

Paleogeographic map compilation desktop workbench (PySide6) with visualization
and well-log engine **submodules**:

| Submodule | Role | Public repo |
|-----------|------|-------------|
| `geo-viz-engine` | Map / geologic visualization packages | [WindWang2/geo-viz-engine](https://github.com/WindWang2/geo-viz-engine) |
| `well-log-engine` | C++20 well-log SDK + **WellPlot Desktop** host app | [WindWang2/well-log-engine](https://github.com/WindWang2/well-log-engine) |

**WellPlot Desktop** (log-first desktop; example and/or product as it matures) is no longer packaged in this repo’s Python tree. It lives at:

`well-log-engine/apps/wellplot-desktop/` — run with `pip install -e well-log-engine/apps/wellplot-desktop && wellplot-desktop`

## Setup

### Linux / macOS

```bash
# From the repository root
git submodule update --init --recursive
python -m pip install -e .
python -m pip install -r requirements-geoviz.txt   # editable geoviz_* packages
python -m pip install -e ".[dev]"                  # pytest / pytest-qt
```

### Windows (MSVC 2022)

Requirements: Visual Studio 2022 with "Desktop development with C++" workload (MSVC `cl.exe`), CMake ≥ 3.24, Ninja, and Python 3.10+.

```powershell
# From the repository root in PowerShell
git submodule update --init --recursive

# Automated one-click build (native C++ extensions, WellLogEngine SDK, tests):
powershell -ExecutionPolicy Bypass -File .\scripts\build_and_test_windows.ps1

# Or manual step-by-step setup:
python -m pip install -e .
python -m pip install -r requirements-geoviz.txt
python -m pip install -e ".[dev]"
```

Editable installs are the **preferred** way to make `import geoviz` work for any
Python process (ISS-ENV-01). Pytest also configures package roots via
`pyproject.toml` `[tool.pytest.ini_options].pythonpath`.

**Windows source checkout:** supported. The packaging #441 blocker
(Windows-invalid filenames in the `geo-viz-engine` submodule) was resolved
upstream by the rename; the pinned submodule trees scan clean, and the CI
guard step ("Guard against Windows-invalid submodule filenames" in `ci.yml`,
with a local twin in `tests/test_workflow_integrity.py`) fails on any *new*
Windows-invalid submodule path so a broken gitlink cannot be re-pinned
silently. A full recursive checkout
(`git submodule update --init --recursive`) works on Windows.

### Native C++ Extensions (`[native]`)

High-performance computational kernels (rasterization, 3D seismic slicing/coherence, LAS parsing, and map topological editing) provide optional C++ accelerated backends:

- `grid_render_core`: fast scalar raster rendering hot path
- `layer_model_core`: layer hierarchy and visibility evaluation
- `seismic_3d_core`: 3D volume slicing with OpenMP multithreading
- `well_log_core`: fast min-max downsampling and streaming LAS parser
- `map_edit_core` (in `geo-viz-engine`): topological hit test, vertex snapping, and intersection validation

To build all native extensions:

```bash
# Linux / macOS (GCC / Clang):
python -m pip install -e native/grid_render_core
python -m pip install -e native/layer_model_core
python -m pip install -e native/seismic_3d_core
python -m pip install -e native/well_log_core
python -m pip install -e geo-viz-engine/native/map_edit_core

# Windows (PowerShell with MSVC 2022):
.\scripts\build_and_test_windows.ps1
```

When native extensions are not built, the workbench transparently falls back to pure Python / NumPy / SciPy implementations.

### QGIS 原生地图栈（硬依赖，自 v0.3 起）

地图区由 vendored QGIS 4.2（`third_party/qgis`）的 `QgsMapCanvas` 承载，
M2 起综合编修区的图层管理（真 `QgsLayerTreeView`：图例/勾选/拖拽/重命名/
右键菜单）与图层属性对话框（真 `QgsVectorLayerProperties`，符号系统页与
QGIS 桌面同款）也由 QGIS 原生控件承载。M4 起首页 / 工区图 / 编图预览在桥
可用时也嵌入只读 `QgsMapCanvas`（自有 `QgsProject`，与综合编修隔离）。无桥
或主 CI 仍走 `UnifiedMapCanvas` + fallback。综合编修继续硬依赖桥。fallback
拆除与工程文件 QgsProject XML 不在本切片。
首次构建/安装：

    python -m pip install "pybind11>=2.12" ninja
    PALEO_WITH_QGIS_RENDERER=1 python -m pip install -e native/qgis_render_bridge   # 首次构建 vendored QGIS 需数小时

桥未安装时地图区构造会明确报错（无 fallback）。

### Running the Application

```bash
# Entry points (after `pip install .` / `pip install -e .`, or from a source
# checkout with the geoviz bootstrap)
paleo-workbench            # console script
python -m paleo_workbench  # module entry
python -m paleo_workbench.main
```

If geoviz cannot be imported the app exits with code 2 and prints the install
commands (geoviz is intentionally not a hard dependency; see
`requirements-geoviz.txt`). `python paleo_workbench/main.py` script mode is
also supported (it re-adds the repo root to `sys.path`).

### Qt display platform (Linux)

| Context | `QT_QPA_PLATFORM` |
|---------|-------------------|
| **Desktop app** (normal use) | **Unset** — on Wayland sessions Qt uses **wayland** (default today). |
| **CI / headless pytest** | `offscreen` (not X11). |
| **XWayland debug only** | `xcb` plus `PALEO_FORCE_XCB=1` if the session is Wayland. |

Do **not** set `QT_QPA_PLATFORM=xcb` as a general default. `DISPLAY=:N` under a Wayland session usually means XWayland compatibility, not “the app should run as X11”. The app entry point clears accidental `xcb` on Wayland unless `PALEO_FORCE_XCB=1`.

## Tests

```bash
# CI / headless (recommended default for automated runs)
QT_QPA_PLATFORM=offscreen python -m pytest -q

# Local GUI-session tests: leave QT_QPA_PLATFORM unset (Wayland on Wayland sessions)
python -m pytest -q
```

## Resource governance, Provider SDK & Agent Harness (P2)

- **Global resource governance** (ADR 0064): one governor over the existing
  TaskScheduler/ResourceBudget — admission control (CPU/RAM/VRAM/IO), memory
  pressure states with cache relief, a dedicated interactive scheduler lane
  (background I/O stays at concurrency 1), bounded priority aging, and runtime
  telemetry (`paleo_workbench.runtime`).
- **Capability Provider SDK** (ADR 0065, `paleo_workbench.providers`):
  descriptor-driven providers over typed refs with schema validation,
  registry isolation and DataRun provenance; built-ins wrap the production
  interpolation engines, seismic attribute kernels, tiled ONNX inference, map
  export and render backends. Extension example:
  `docs/extension/provider-and-action-examples.md`.
- **Geological Agent Harness** (ADR 0066, `paleo_workbench.harness`): 20
  stable professional actions (workspace/well/seismic/map/geology/workflow)
  behind a guarded executor (validate → permissions → context → admission →
  execute → scientific/map verification), with vendor-agnostic
  ToolSource/ChatModel protocols for any agent runtime. Agents never drive
  UI, never touch SQLite, and every data output enters the catalog.

## QGIS renderer (primary authoring core, optional build)

> M1 起综合编修区由 QGIS 画布承载（`QgisCanvasShim` + `QgsMapCanvas`，硬依赖）；M2 起图层管理面板（`QgsLayerTreeView`）与图层属性对话框（`QgsVectorLayerProperties`）同为 QGIS 原生控件。M4 起首页 / 工区图 / 编图预览在桥可用时也嵌入只读 `QgsMapCanvas`（自有 `QgsProject`，与综合编修隔离）。无桥或主 CI 仍走 `UnifiedMapCanvas` + fallback。综合编修继续硬依赖桥。fallback 拆除与工程文件 QgsProject XML 不在本切片。

Per ADR 0059 the QGIS renderer is the **primary professional 2-D cartographic
authoring core**: `create_map_render_backend()` defaults to
`prefer_qgis=True`, so a built bridge is used automatically (screen, export
PNG/SVG/PDF). The legacy QPainter fallback remains the always-available path
for tests/headless/minimal runtimes and gains no new professional features.

The bridge itself requires the optional `qgis_render_bridge` extension (a
vendored-QGIS build under `native/qgis_render_bridge`; QGIS sources are fixed
in `third_party/qgis`). It is **not** part of the default install, so a
bridge-less environment transparently runs the fallback (with a logged,
actionable reason when a broken bridge fails the one-shot runtime probe).
The main CI gate does **not** build the bridge — every QGIS test self-skips
there (they carry the `qgis` pytest marker; skip reasons show the exact
enablement commands).

Build it explicitly (needs Qt6 dev headers, cmake and ninja on the system):

```bash
python -m pip install -e ".[qgis-renderer]"
PALEO_WITH_QGIS_RENDERER=1 python -m pip install -e native/qgis_render_bridge
python -m pytest -q -m qgis tests/   # run the QGIS renderer tests
```

Tests and headless paths that need the painter construct
`FallbackMapRenderBackend` directly, or call
`create_map_render_backend(prefer_qgis=False)`. There is no environment-variable
opt-out that demotes a built bridge.

A dedicated CI leg (`.github/workflows/qgis-renderer.yml`) builds the bridge
and executes the qgis-marked tests (fail-closed, count-gated). It runs on
manual dispatch and on changes touching `native/qgis_render_bridge/**`,
`third_party/qgis/**`, `paleo_workbench/mapping/**`, or the QGIS test family.
See `docs/ci-merge-policy.md` for the coverage statement.

## 3D Geological Modeling (`viz/geomodel`)

Page 11 adds a full 3D geological modeling workbench with:

- **Borehole / Tunnel / Fault** 3D rendering (OpenGL cylinders, swept tubes, fault surfaces)
- **GPU 3-way interactive clipping** (X / Y / Z axis real-time cut)
- **Well-seismic tie calibration** — Ricker synthetic seismograms, cross-correlation auto-tie, 3D GR log curve overlay
- **Seismic amplitude slice** overlay in the 3D viewport
- **Rule-based consistency advisor** — borehole layer overlap detection, coplanar fault warning
- **Numerical simulation export** — FLAC3D (`.f3grid`) and Abaqus (`.inp`) structured hex grids

See [`docs/geomodel-architecture.md`](docs/geomodel-architecture.md) for the full module architecture.

## Interpolation note (ISS-KRIG-01 resolved)

The preparation combobox option **克里金** runs REAL variogram ordinary
kriging: empirical-variogram fitting plus an ordinary-kriging solve, with the
kriging variance grid exposed alongside the prediction (geo-viz-engine
`geoviz_plots.factor.kriging`). The earlier MVP linear placeholder is gone.
**IDW** (with optional fault barriers) and **方向趋势** remain available.

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
