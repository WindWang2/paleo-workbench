#!/usr/bin/env bash
# cpp-close-02 — direct-compile full closure + test run (CONV-32/33
# precedent: cmake unavailable on this host; g++ -std=c++20 direct
# compilation of the whole dependency closure, then the four test
# binaries). Run under the resource gate.
# Usage: bash scripts/cpp-migration/closure02-build-and-test.sh [run-only]
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/closure02"
mkdir -p "$BUILD"
cd "$ROOT"

FLAGS=(-std=c++20 -c -O0 -g0 -Wall -Wextra
  -Ilibs/closure_workflow/include -Ilibs/workflow_runtime/include
  -Ilibs/workflow_engine/include -Ilibs/workflow_spec/include
  -Ilibs/workflow_graph/include -Ilibs/workflow_interpretation/include
  -Ilibs/workflow_contracts/include -Ilibs/factor_fusion/include
  -Ilibs/factor_host/include -Ilibs/mapping_kernel/include
  -Ilibs/job_runtime/include -Ilibs/domain/include -Ilibs/project/include
  -Ilibs/data_suite/third_party)

CORE_TUS=(
  libs/domain/src/ids.cpp libs/domain/src/sha256.cpp libs/domain/src/support.cpp
  libs/workflow_spec/src/model.cpp libs/workflow_spec/src/validation.cpp libs/workflow_spec/src/python_repr.cpp
  libs/workflow_graph/src/graph.cpp libs/workflow_graph/src/evidence.cpp
  libs/factor_host/src/canonical_json.cpp libs/factor_host/src/fingerprint.cpp libs/factor_host/src/evaluation.cpp libs/factor_host/src/plan.cpp libs/factor_host/src/interop.cpp libs/factor_host/src/semantics.cpp
  libs/factor_fusion/src/factor_units.cpp libs/factor_fusion/src/fusion.cpp
  libs/mapping_kernel/src/contouring.cpp libs/mapping_kernel/src/interpolator.cpp libs/mapping_kernel/src/polygonization.cpp libs/mapping_kernel/src/extract.cpp libs/mapping_kernel/src/crs_policy.cpp libs/mapping_kernel/src/class_grid.cpp libs/mapping_kernel/src/sample_normalization.cpp libs/mapping_kernel/src/layer_products.cpp libs/mapping_kernel/src/ring_ops.cpp libs/mapping_kernel/src/constrained_idw.cpp libs/mapping_kernel/src/representative_facies.cpp libs/mapping_kernel/src/geometry_units.cpp libs/mapping_kernel/src/crs_contract.cpp libs/mapping_kernel/src/factor_grid_io.cpp
  # job_bridge.cpp is the Qt6 target (Qt6::Core absent on this host);
  # the Qt-free scheduler core is job_scheduler + job_categories.
  libs/job_runtime/src/job_scheduler.cpp libs/job_runtime/src/job_categories.cpp
  libs/project/src/document.cpp libs/project/src/manager.cpp libs/project/src/paths.cpp libs/project/src/schema.cpp libs/project/src/relocation.cpp libs/project/src/version_models.cpp
  libs/workflow_engine/src/engine.cpp libs/workflow_engine/src/ops.cpp libs/workflow_engine/src/store.cpp libs/workflow_engine/src/reproduction.cpp libs/workflow_engine/src/receipt.cpp libs/workflow_engine/src/plan_view.cpp libs/workflow_engine/src/run_engine.cpp libs/workflow_engine/src/recipe.cpp
  libs/workflow_runtime/src/catalog_seam.cpp libs/workflow_runtime/src/constraint_versions.cpp libs/workflow_runtime/src/current_context.cpp libs/workflow_runtime/src/freshness.cpp libs/workflow_runtime/src/node_adapters.cpp libs/workflow_runtime/src/provenance_graph.cpp libs/workflow_runtime/src/recompute_plan.cpp libs/workflow_runtime/src/runtime_service.cpp libs/workflow_runtime/src/staleness.cpp libs/workflow_runtime/src/orchestrator.cpp libs/workflow_runtime/src/service.cpp libs/workflow_runtime/src/qc.cpp libs/workflow_runtime/src/map_qa_rules.cpp libs/workflow_runtime/src/versioning.cpp libs/workflow_runtime/src/resolve_context.cpp
  libs/workflow_interpretation/src/algorithm_registry.cpp libs/workflow_interpretation/src/compilation.cpp libs/workflow_interpretation/src/constraint_capabilities.cpp libs/workflow_interpretation/src/constraint_product.cpp libs/workflow_interpretation/src/factor_product.cpp libs/workflow_interpretation/src/integrated_interpretation.cpp libs/workflow_interpretation/src/revision.cpp libs/workflow_interpretation/src/summaries.cpp
  libs/closure_workflow/src/python_json.cpp libs/closure_workflow/src/persistent_catalog.cpp libs/closure_workflow/src/map_product.cpp libs/closure_workflow/src/integrated_compilation.cpp libs/closure_workflow/src/workflow_scheduler.cpp libs/closure_workflow/src/cache_run_rail.cpp libs/closure_workflow/src/host_bindings.cpp
)

objects=()
if [ "${1:-build}" != "run-only" ]; then
  echo "== compiling core closure (${#CORE_TUS[@]} TUs, serial -O0)"
  for tu in "${CORE_TUS[@]}"; do
    out="$BUILD/$(echo "$tu" | tr '/' '_').o"
    objects+=("$out")
    if [ "$out" -nt "$tu" ]; then
      continue
    fi
    if ! g++ "${FLAGS[@]}" "$tu" -o "$out"; then
      echo "COMPILE FAILED: $tu"
      exit 1
    fi
  done
else
  for tu in "${CORE_TUS[@]}"; do
    objects+=("$BUILD/$(echo "$tu" | tr '/' '_').o")
  done
fi
# Tests also compile as objects for linking.
TEST_TUS=(
  libs/closure_workflow/closure_workflow_tests/resolve_test.cpp
  libs/closure_workflow/closure_workflow_tests/map_product_test.cpp
  libs/closure_workflow/closure_workflow_tests/fusion_test.cpp
  libs/closure_workflow/closure_workflow_tests/closure_e2e_test.cpp
)
test_objects=()
for tu in "${TEST_TUS[@]}"; do
  out="$BUILD/$(echo "$tu" | tr '/' '_').o"
  test_objects+=("$out")
  if [ "${1:-build}" != "run-only" ]; then
    if [ "$out" -nt "$tu" ]; then continue; fi
    if ! g++ "${FLAGS[@]}" "$tu" -o "$out"; then
      echo "COMPILE FAILED: $tu"
      exit 1
    fi
  fi
done

link_and_run() {
  local name="$1" obj="$2"; shift 2
  echo "== linking $name"
  if ! g++ -std=c++20 -O0 "$obj" "${objects[@]}" -o "$BUILD/$name" -pthread; then
    echo "LINK FAILED: $name"
    return 1
  fi
  echo "== running $name $*"
  "$BUILD/$name" "$@"
}

fail=0
link_and_run closure_workflow_resolve_test "${test_objects[0]}" \
  libs/closure_workflow/closure_workflow_tests/fixtures/closure_resolve_oracle.json || fail=1
link_and_run closure_workflow_map_product_test "${test_objects[1]}" \
  libs/closure_workflow/closure_workflow_tests/fixtures/closure_map_product_oracle.json || fail=1
link_and_run closure_workflow_fusion_test "${test_objects[2]}" \
  libs/closure_workflow/closure_workflow_tests/fixtures/closure_fusion_oracle.json || fail=1
link_and_run closure_workflow_e2e_test "${test_objects[3]}" || fail=1

echo "== RESULT fail=$fail"
exit $fail
