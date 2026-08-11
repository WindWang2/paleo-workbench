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
is intentionally not part of this minimal runtime closure. No imported C++
source is modified.
