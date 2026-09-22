#!/usr/bin/env bash
# check-python-retirement.sh — Python-retirement regression gate
# (docs/development/python-retirement/).
#
# Fails when any retirement invariant is violated:
#   1. archive isolation — legacy/python_reference must not be referenced by
#      effective (non-comment) CMake/install/launcher/product-C++ code;
#   2. tree shape — the retired package must not reappear at the repo root,
#      and pyproject must not re-register it as an installable product;
#   3. sanctioned bridge — every ACTIVE tracked .py that imports
#      paleo_workbench must reach the archive through the sanctioned shim
#      (tools/oracle/_legacy_reference.py or an explicit archive-path
#      insert adjacent to the import, in effective code);
#   4. runtime python-independence — delegates to
#      audit-python-runtime-deps.sh (source scan of the product link set +
#      optional ldd closure);
#   5. install-tree purity — an install/deploy root passed via
#      PALEO_RETIRE_INSTALL_DIR must contain zero .py/.pyc files and zero
#      legacy/ paths (final-closure-gate.sh exports it for the package leg).
#
# Exit 0 = clean; exit 1 = violation (with file:line evidence).
# Development tooling only — never part of the product.
set -u

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
Status=0
InstallDir="${PALEO_RETIRE_INSTALL_DIR:-}"

fail() { echo "VIOLATION: $*"; Status=1; }

# Normalized archive marker: matches literal legacy/python_reference AND
# segment-joined constructions like Path("legacy") / "python_reference".
ARCHIVE_RE='legacy.{0,12}python_reference'

# Strip comment-only lines (# for shell/py, // and * for cmake/cpp) so the
# scans below judge EFFECTIVE code only.
strip_comments() { grep -vE '^[[:space:]]*(#|//|\*|/\*)' "$1" 2>/dev/null || true; }

# ---------------------------------------------------------------- 1. archive
# isolation.
echo "== retirement gate: archive isolation"
for scope in CMakeLists.txt cmake apps libs native tests CMakePresets.json; do
    path="$RepoRoot/$scope"
    [ -e "$path" ] || continue
    if [ -d "$path" ]; then
        hits=$(grep -rnE "$ARCHIVE_RE" --include='*.cmake' --include='CMakeLists.txt' \
               --include='*.cpp' --include='*.hpp' "$path" 2>/dev/null \
               | grep -vE '^[^:]+:[0-9]+:[[:space:]]*(//|\*|/\*|#)' || true)
    else
        hits=$(strip_comments "$path" | grep -nE "$ARCHIVE_RE" \
               | sed "s|^|$path:|" || true)
    fi
    if [ -n "$hits" ]; then
        fail "legacy/python_reference referenced by effective product/build code ($scope):"
        echo "$hits"
    fi
done
echo "  clean: no effective archive references in CMake/product sources"

# launchers/deploy scripts must not launch or copy the archive
launcher_hits=$(grep -rnE "$ARCHIVE_RE" "$RepoRoot/scripts" 2>/dev/null \
                | grep -vE ':[0-9]+:[[:space:]]*#' \
                | grep -v 'check-python-retirement.sh' || true)
if [ -n "$launcher_hits" ]; then
    fail "archive referenced by product launcher/deploy scripts:"
    echo "$launcher_hits"
else
    echo "  clean: launchers/deploy scripts do not touch the archive"
fi

# ---------------------------------------------------------------- 2. shape
echo "== retirement gate: repository tree shape"
if [ -d "$RepoRoot/paleo_workbench" ]; then
    fail "paleo_workbench/ exists again at the repo root — the retired package must stay under legacy/python_reference/product"
fi
if [ -e "$RepoRoot/run_app.py" ]; then
    fail "run_app.py exists again at the repo root (retired Python launcher)"
fi
if grep -qE '^\s*paleo-workbench\s*=' "$RepoRoot/pyproject.toml" 2>/dev/null; then
    fail "pyproject.toml re-registers a paleo-workbench console script"
fi
if grep -qE 'include\s*=\s*\[.*paleo_workbench' "$RepoRoot/pyproject.toml" 2>/dev/null; then
    fail "pyproject.toml re-packages paleo_workbench"
fi
echo "  clean: retired tree absent; pyproject carries no product entry"

# ---------------------------------------------------------------- 3. shim
echo "== retirement gate: sanctioned archive bridge"
unshimmed=$(git -C "$RepoRoot" ls-files '*.py' | while IFS= read -r f; do
    case "$f" in
        legacy/*) continue ;;
    esac
    if grep -qE '(^|[^A-Za-z_])(from|import)[[:space:]]+paleo_workbench' "$RepoRoot/$f" 2>/dev/null; then
        # effective-code shim markers: the sanctioned module or an explicit
        # archive-path insert (comments stripped before the test)
        if ! strip_comments "$RepoRoot/$f" | grep -qE \
            'import[[:space:]]+_legacy_reference|ensure_legacy_reference\(\)|'"$ARCHIVE_RE"; then
            printf '%s\n' "$f"
        fi
    fi
done)
if [ -n "$unshimmed" ]; then
    fail "active Python imports the retired package without the sanctioned shim (tools/oracle/_legacy_reference.py):"
    echo "$unshimmed"
else
    echo "  clean: every active importer goes through the shim"
fi

# ---------------------------------------------------------------- 4. runtime
echo "== retirement gate: native runtime python-independence"
"$RepoRoot/scripts/cpp-migration/audit-python-runtime-deps.sh" || Status=1

# ---------------------------------------------------------------- 5. install
if [ -n "$InstallDir" ] && [ -d "$InstallDir" ]; then
    echo "== retirement gate: install-tree purity ($InstallDir)"
    py_files=$(find "$InstallDir" -type f \( -name '*.py' -o -name '*.pyc' \) -print -quit)
    if [ -n "$py_files" ]; then
        fail "install tree contains Python files: $py_files"
    fi
    legacy_paths=$(find "$InstallDir" -path '*legacy*' -print -quit)
    if [ -n "$legacy_paths" ]; then
        fail "install tree contains archived paths: $legacy_paths"
    fi
    echo "  clean: install tree python-free and archive-free"
fi

if [ "$Status" -eq 0 ]; then
    echo "PYTHON_RETIREMENT_GATE_PASS"
fi
exit "$Status"
