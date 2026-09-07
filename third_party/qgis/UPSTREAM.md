# QGIS Source Provenance

This directory contains the QGIS 4.2.0 source closure used by paleo-workbench's
owned vector editing and rendering runtime.

- Upstream repository: <https://github.com/qgis/QGIS>
- Immutable upstream tag: `final-4_2_0`
- Upstream commit: `ca5812c8b8e39b59695a3b0206fc5f3206eda0a9`
- Archive: `https://github.com/qgis/QGIS/archive/refs/tags/final-4_2_0.tar.gz`
- Archive SHA-256: `98f6913e9e836976f2c0d72d992a172a616621b96c78d9d3a820fdeefd737174`
- Upstream license: GPL-2.0-or-later; see [COPYING](COPYING).

Imported components:

- `src/core`, including QGIS's in-core memory and GDAL providers;
- `src/analysis` for vector analysis;
- `src/ui`, `src/gui`, and `src/native` for map canvas, rendering and editing;
- `src/app` and `src/plugins`, preserving the QGIS Desktop vector-editing and
  editing-plugin implementations that build on the reusable GUI layer;
- `src/auth`, required by QGIS Core network/auth manager source;
- `src/providers`, `src/crssync`, and `src/test`, which the upstream CMake
  source closure declares;
- QGIS resource/image data, upstream CMake modules/templates and internal
  dependencies required by that build closure.
- Upstream `scripts/`, used by QGIS Core to generate expression source during
  its build.

QGIS Desktop and desktop plugin *targets* are not built by paleo-workbench; their
source is retained for the complete vector-editing implementation. QGIS server,
standalone 3D, Quick UI, Python-binding, documentation, translation and packaging
*targets* are disabled. Core/GUI support files that upstream places below their source
directories remain when they are required by the Core/GUI build closure.

Only `CMakeLists.txt` differs from upstream: four non-runtime subdirectories
(`doc`, `i18n`, `postinstall`, and `linux`) are not added because their source
is intentionally not part of this minimal runtime closure. One imported C++
header carries a documented compatibility patch:

- `src/core/qgsconnectionpool.h` — `QSemaphore::tryAcquire(int,
  QDeadlineTimer)` does not exist before Qt 6.6; on older Qt runtimes (the
  CI leg builds against Ubuntu noble's Qt 6.4) the call falls back to the
  identical milliseconds overload, guarded by `QT_VERSION`. Semantics are
  unchanged (both forms time out after `timeout` ms).

Windows (MSVC) build support patches — qgis-geolayer-cartography-v7:

- `platform/windows/rc/version.rc.in` — restored verbatim from the pinned
  upstream commit. The win32_version_info() CMake function
  (cmake/CreateQgsVersion.cmake) requires it on WIN32, but `platform/` had
  been dropped from the closure because Linux builds never reference it.
- `src/core/CMakeLists.txt` — `include(CheckFunctionExists)` added inside
  `if(WITH_INTERNAL_SPATIALINDEX)`. Upstream only includes that module
  under `if(NOT WIN32 ...)` (the openpty probe in the top-level
  CMakeLists.txt), so pure-MSVC configure fails with "Unknown CMake
  command" at the spatialindex `check_function_exists()` calls. No
  behavioural change on Linux (the module is idempotent to include).
- `src/gui/symbology/qgstemplatedcategorizedrendererwidget_p.h` — added
  the `typename` keyword to the dependent type
  `RendererType::Category` in the virtual `symbolIcon` declaration
  (C2061 on MSVC; GCC accepts both). This is an upstream
  MSVC-incompatibility in the Nov-2025 categorized-renderer-widget
  rework; the file is otherwise verbatim.

