#!/usr/bin/env bash
# Five-line integrated gate (conversion plan M5): configure + build + the
# full acceptance battery in ONE command. Exit 0 only when everything
# passes — suitable for CI and for pre-merge local runs.
#
#   scripts/cpp-migration/run-integrated-gate.sh [build-dir] [jobs]
#
# Battery (v3-verification §4a):
#   1. configure the integrated tree (A+B+C+D+E+seismic_io, integration
#      tests, tools; fail-closed root switches)
#   2. build
#   3. full ctest TWICE (green x2 rule)
#   4. MALLOC_CHECK_=3 over platform+integration (heap-sensitivity audit)
#
# SDK paths default to this checkout's layout and can be overridden via
# environment (PwbQgisSdk.cmake contract).
set -euo pipefail

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BuildDir="${1:-$RepoRoot/build/cpp-integrated}"
Jobs="${2:-8}"

: "${PALEO_QGIS_SOURCE_DIR:=$RepoRoot/third_party/qgis}"
: "${PALEO_QGIS_SDK_DIR:=$RepoRoot/native/qgis_render_bridge/build/qgis-vendor/output}"
: "${PALEO_QGIS_BUILD_DIR:=$RepoRoot/native/qgis_render_bridge/build/qgis-vendor}"

echo "== integrated gate: source=$RepoRoot build=$BuildDir jobs=$Jobs"
cmake -S "$RepoRoot" -B "$BuildDir" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DPWB_BUILD_PLATFORM=ON \
    -DPWB_BUILD_DATA=ON \
    -DPWB_BUILD_SCIENCE=ON \
    -DPWB_BUILD_INTEGRATION_TESTS=ON \
    -DPWB_BUILD_TOOLS=ON \
    -DPWB_BUILD_SEISMIC_VIEWER=ON \
    -DPWB_BUILD_SEISMIC_ATTRIBUTES=ON \
    -DPWB_BUILD_SEISMIC_IO=ON -DPWB_BUILD_MAPPING_KERNEL=ON \
    -DPALEO_QGIS_SOURCE_DIR="$PALEO_QGIS_SOURCE_DIR" \
    -DPALEO_QGIS_SDK_DIR="$PALEO_QGIS_SDK_DIR" \
    -DPALEO_QGIS_BUILD_DIR="$PALEO_QGIS_BUILD_DIR"

cmake --build "$BuildDir" -j "$Jobs"

echo "== ctest pass 1 (full)"
ctest --test-dir "$BuildDir" -j 4 --output-on-failure
echo "== ctest pass 2 (green x2 rule)"
ctest --test-dir "$BuildDir" -j 4

echo "== MALLOC_CHECK_=3 audit (platform + integration)"
MALLOC_CHECK_=3 ctest --test-dir "$BuildDir" -R "platform.|integration."

echo "== integrated gate PASS"
