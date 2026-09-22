#!/usr/bin/env bash
# Final native-product closure gate. Heavy configure/build/test/package work
# always runs through the shared resource gate.
set -euo pipefail

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BuildDir="${PWB_FINAL_BUILD_DIR:-$RepoRoot/build/final-closure}"
InstallDir="${PWB_FINAL_INSTALL_DIR:-$RepoRoot/build/final-closure-install}"
DeployDir="${PWB_FINAL_DEPLOY_DIR:-$RepoRoot/build/final-closure-deploy}"
Jobs="${PWB_FINAL_JOBS:-2}"
Stage="${1:-all}"
Gate="$RepoRoot/scripts/cpp-migration/invoke-resource-gate.sh"

cd "$RepoRoot"

if ! command -v cmake >/dev/null 2>&1 \
        && [ -x "$RepoRoot/.venv/bin/cmake" ]; then
    export PATH="$RepoRoot/.venv/bin:$PATH"
fi

export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
export CTEST_PARALLEL_LEVEL="${CTEST_PARALLEL_LEVEL:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"

case "$Stage" in
    static|configure|build|test|package|runtime|all) ;;
    *) echo "usage: $0 [static|configure|build|test|package|runtime|all]"; exit 2 ;;
esac

run_static() {
    echo "== final closure: repository truth"
    python3 "$RepoRoot/tools/migration/pwb_migration_inventory.py" \
        --repo-root "$RepoRoot" \
        --json-out "$RepoRoot/build/migration-inventory/current.json" \
        --markdown-out "$RepoRoot/docs/development/cpp-migration-inventory.md" \
        --quiet
    python3 "$RepoRoot/tools/migration/pwb_final_closure_matrix.py" \
        --repo-root "$RepoRoot"
    python3 -m unittest tools.migration.tests.test_final_closure_matrix -v
    python3 "$RepoRoot/tools/verify/pwb_artifact_hygiene.py" \
        --repo-root "$RepoRoot" \
        --json-out "$RepoRoot/build/final-closure-artifact-hygiene.json" \
        --markdown-out "$RepoRoot/build/final-closure-artifact-hygiene.md" \
        --quiet
    python3 "$RepoRoot/tools/migration/pwb_python_dependency_audit.py" \
        --repo-root "$RepoRoot" \
        --json-out "$RepoRoot/build/final-closure-python-audit.json" \
        --markdown-out "$RepoRoot/build/final-closure-python-audit.md" \
        --quiet
    "$RepoRoot/scripts/cpp-migration/audit-python-runtime-deps.sh"
    "$RepoRoot/scripts/cpp-migration/check-python-retirement.sh"

    if git -C "$RepoRoot" ls-files | grep -Eq \
        '(^|/)(__pycache__/|[^/]+\.py[co]$|\.pytest_cache/)'; then
        echo "tracked Python cache/build artifacts are forbidden" >&2
        exit 1
    fi
}

run_configure() {
    echo "== final closure: configure native product"
    "$Gate" Configure -s "$RepoRoot" -b "$BuildDir" -j "$Jobs" \
        -a "-DBUILD_TESTING=ON;-DPWB_BUILD_NATIVE_PRODUCT=ON;-DPWB_BUILD_INTEGRATION_TESTS=ON;-DPWB_BUILD_TOOLS=OFF;-DPWB_ENABLE_PACKAGING=ON"
}

run_build() {
    echo "== final closure: build native product"
    "$Gate" Build -b "$BuildDir" -j "$Jobs" -t "pwb-platform"
}

run_tests() {
    echo "== final closure: focused native tests"
    "$Gate" Test -b "$BuildDir" -j "$Jobs" \
        -r "^(platform\\.|integration\\.|data\\.|science\\.|seismic\\.|mapping\\.)"
    echo "== final closure: integrated tests pass 2"
    "$Gate" Test -b "$BuildDir" -j "$Jobs" \
        -r "^(platform\\.|integration\\.|data\\.|science\\.|seismic\\.|mapping\\.)"
}

product_exe() {
    for candidate in \
        "$BuildDir/bin/pwb-platform" \
        "$BuildDir/apps/paleo_workbench_platform/pwb-platform" \
        "$BuildDir/pwb-platform"; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

run_package() {
    echo "== final closure: install/package/deploy"
    "$Gate" Exec -j "$Jobs" -- cmake --install "$BuildDir" \
        --prefix "$InstallDir"
    if find "$InstallDir" -type f \
        \( -name '*.py' -o -name '*.pyc' \) -print -quit | grep -q .; then
        echo "native install tree contains Python product modules" >&2
        exit 1
    fi
    if find "$InstallDir" -path '*legacy*' -print -quit | grep -q .; then
        echo "native install tree contains archived (legacy/) paths" >&2
        exit 1
    fi
    if find "$DeployDir" -path '*legacy*' -print -quit | grep -q .; then
        echo "deployed native tree contains archived (legacy/) paths" >&2
        exit 1
    fi
    PALEO_RETIRE_INSTALL_DIR="$InstallDir" \
        "$RepoRoot/scripts/cpp-migration/check-python-retirement.sh"
    "$Gate" Exec -j "$Jobs" -- \
        "$RepoRoot/scripts/cpp-migration/deploy-native-product.sh" \
        "$BuildDir" "$DeployDir"
    if find "$DeployDir" -type f \
        \( -name '*.py' -o -name '*.pyc' \) -print -quit | grep -q .; then
        echo "deployed native tree contains Python product modules" >&2
        exit 1
    fi
}

run_runtime() {
    local exe
    exe="$(product_exe)" || {
        echo "pwb-platform not found under $BuildDir" >&2
        exit 1
    }
    echo "== final closure: runtime diagnostics"
    "$Gate" Exec -j "$Jobs" -- env QT_QPA_PLATFORM=offscreen \
        "$exe" --self-check
    "$Gate" Exec -j "$Jobs" -- "$exe" --capabilities
    "$Gate" Exec -j "$Jobs" -- "$exe" --diagnostics
    "$RepoRoot/scripts/cpp-migration/audit-python-runtime-deps.sh" --exe "$exe"
}

case "$Stage" in
    static) run_static ;;
    configure) run_configure ;;
    build) run_build ;;
    test) run_tests ;;
    package) run_package ;;
    runtime) run_runtime ;;
    all)
        run_static
        run_configure
        run_build
        run_tests
        run_package
        run_runtime
        ;;
esac

echo "FINAL_CLOSURE_GATE_PASS stage=$Stage"
