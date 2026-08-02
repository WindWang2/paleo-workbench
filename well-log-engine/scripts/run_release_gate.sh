#!/usr/bin/env bash
# #174 — run the publish-gate CTest subset (structural; not absolute frame SLOs).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${WELLLOG_BUILD_DIR:-$ROOT/build/dev-shared}"

if [[ ! -d "$BUILD" ]]; then
  echo "Build dir not found: $BUILD" >&2
  echo "Set WELLLOG_BUILD_DIR or configure build/dev-shared first." >&2
  exit 2
fi

echo "== WellLogEngine release-gate (label) =="
ctest --test-dir "$BUILD" -L release-gate --output-on-failure "$@"

echo
echo "Full ADR 0014 1e8 scale (optional, fixed workstation):"
echo "  WELLLOG_GATE_SCALE=full ctest --test-dir \$BUILD -R welllog.release-gate-scenario-full -V"
echo "GL frame P95/P99 (optional, WELLLOG_BUILD_BENCHMARKS=ON + Qt):"
echo "  ./welllog_dense_curve_benchmark  # single-curve 500k @ 4K"
echo "Workbench default engine:"
echo "  pytest tests/test_welllog_engine_adapter.py tests/test_well_log_canvas_panel.py -q"
