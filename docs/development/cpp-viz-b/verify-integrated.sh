#!/usr/bin/env bash
# VIZ-B line acceptance wrapper (resource-gated): configure the full
# integrated tree with the viz-B slice ON, build this line's closure with
# jobs=2, run the viz_b ctest battery TWICE, then the MALLOC_CHECK_=3
# audit. Mirrors scripts/cpp-migration/run-integrated-gate.sh with the
# line-B job ceiling and this line's own build tree.
set -euo pipefail

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BuildDir="$RepoRoot/build/viz-b-integrated"
Jobs=2

: "${PALEO_QGIS_SOURCE_DIR:=/home/kevin/projects/paleo_project/main/third_party/qgis}"
: "${PALEO_QGIS_SDK_DIR:=/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor/output}"
: "${PALEO_QGIS_BUILD_DIR:=/home/kevin/projects/paleo_project/main/native/qgis_render_bridge/build/qgis-vendor}"
: "${PWB_QGIS_DEPS_PREFIX:=/home/kevin/projects/paleo_project/main/native/gdal-vendored/install}"
export PWB_QGIS_DEPS_PREFIX

export CMAKE_BUILD_PARALLEL_LEVEL=2
export CTEST_PARALLEL_LEVEL=2
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

Gate="$RepoRoot/scripts/cpp-migration/invoke-resource-gate.sh"

cd "$RepoRoot"
bash "$Gate" Configure -s "$RepoRoot" -b "$BuildDir" \
    -a "-DPWB_BUILD_PLATFORM=ON;-DPWB_BUILD_DATA=ON;-DPWB_BUILD_SCIENCE=ON;-DPWB_BUILD_INTEGRATION_TESTS=ON;-DPWB_BUILD_TOOLS=ON;-DPWB_BUILD_SEISMIC_VIEWER=ON;-DPWB_BUILD_SEISMIC_ATTRIBUTES=ON;-DPWB_BUILD_SEISMIC_SERVICE=ON;-DPWB_BUILD_SEISMIC_IO=ON;-DPWB_BUILD_MAPPING_KERNEL=ON;-DPWB_BUILD_VIZ_B=ON;-DPALEO_QGIS_SOURCE_DIR=$PALEO_QGIS_SOURCE_DIR;-DPALEO_QGIS_SDK_DIR=$PALEO_QGIS_SDK_DIR;-DPALEO_QGIS_BUILD_DIR=$PALEO_QGIS_BUILD_DIR;-DCMAKE_BUILD_TYPE=Release"

# pwb-platform itself is currently blocked by the PRE-EXISTING upstream
# TU error (#1399: importSegyDialog version_id under CONV_30+VIEWER) —
# unrelated to this line. Build this line's full closure instead; the
# dock is compiled + exercised by viz_b.dock_smoke with the real
# JobCenter.
bash "$Gate" Build -s "$RepoRoot" -b "$BuildDir" -j "$Jobs" \
    -t "pwb_visualization_cross_well;pwb_visualization_cross_well_qt;pwb_visualization_well_tie;pwb_visualization_well_tie_qt;viz_b.well_tie.oracle;viz_b.cross_well.oracle;viz_b.cross_well.qt_smoke;viz_b.integration;viz_b.engines_example;viz_b.dock_smoke"

echo "== ctest pass 1 (viz_b battery)"
ctest --test-dir "$BuildDir" -j 2 -R "viz_b\."

echo "== ctest pass 2 (green x2 rule)"
ctest --test-dir "$BuildDir" -j 2 -R "viz_b\."

echo "== MALLOC_CHECK_=3 audit (viz_b battery)"
MALLOC_CHECK_=3 ctest --test-dir "$BuildDir" -R "viz_b\."

echo "== VIZ-B integrated verification PASS"
