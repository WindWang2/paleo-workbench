#!/usr/bin/env bash
#
# Import the QGIS Python closure into third_party/qgis (Prompt 7).
#
# The vendored QGIS snapshot (tag final-4_2_0) deliberately excludes the
# Python-binding targets, so third_party/qgis carries neither src/python
# (qgispython / QgsPythonUtils) nor python/ (PyQGIS bindings, console,
# built-in plugins). This script imports both from the immutable upstream tag
# and refuses to run unless the archive hash matches the value recorded in
# third_party/qgis/UPSTREAM.md.
#
# Usage:
#   scripts/import_qgis_python_closure.sh [path-to-final-4_2_0.tar.gz]
#
# The archive is never committed; only the imported files are.

set -euo pipefail

ARCHIVE="${1:-$HOME/.build-tmp/qgis-src/final-4_2_0.tar.gz}"
EXPECTED_SHA256="98f6913e9e836976f2c0d72d992a172a616621b96c78d9d3a820fdeefd737174"
UPSTREAM_TAG="final-4_2_0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DEST="${REPO_ROOT}/third_party/qgis"

if [[ ! -f "${ARCHIVE}" ]]; then
    echo "archive not found: ${ARCHIVE}" >&2
    echo "download it with:" >&2
    echo "  curl -sL -o ${ARCHIVE} https://github.com/qgis/QGIS/archive/refs/tags/${UPSTREAM_TAG}.tar.gz" >&2
    exit 1
fi

echo "verifying archive: ${ARCHIVE}"
ACTUAL_SHA256="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
if [[ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]]; then
    echo "SHA-256 mismatch:" >&2
    echo "  expected ${EXPECTED_SHA256}" >&2
    echo "  actual   ${ACTUAL_SHA256}" >&2
    exit 1
fi
echo "  ok ${ACTUAL_SHA256}"

# The extraction workspace must not land on a small tmpfs: /tmp is 10 MB on
# some verification hosts and tar dies mid-archive with "no space left".
WORK_ROOT="${TMPDIR:-/home/kevin/.build-tmp}"
mkdir -p "${WORK_ROOT}"
WORK="$(mktemp -d "${WORK_ROOT}/qgis-python-import.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

# Class-D built-in plugins (see 07-plugin-runtime-design.md §5) and the QGIS
# server bindings are excluded at extraction time — the script never deletes
# anything, so it cannot be blocked by a bulk-delete guard and stays safe to
# re-run over an existing import.
echo "extracting python subtree…"
tar xzf "${ARCHIVE}" -C "${WORK}" \
    --exclude="QGIS-${UPSTREAM_TAG}/python/plugins/grassprovider" \
    --exclude="QGIS-${UPSTREAM_TAG}/python/plugins/db_manager" \
    --exclude="QGIS-${UPSTREAM_TAG}/python/plugins/MetaSearch" \
    --exclude="QGIS-${UPSTREAM_TAG}/python/PyQt6/server" \
    "QGIS-${UPSTREAM_TAG}/src/python" \
    "QGIS-${UPSTREAM_TAG}/python"
SRC="${WORK}/QGIS-${UPSTREAM_TAG}"

if [[ ! -f "${SRC}/src/python/qgspythonutils.h" ]]; then
    echo "archive layout unexpected: src/python/qgspythonutils.h missing" >&2
    exit 1
fi

echo "importing src/python (qgispython support library)…"
mkdir -p "${DEST}/src/python"
cp -a "${SRC}/src/python/." "${DEST}/src/python/"

echo "importing python/ (bindings, console, built-in plugins)…"
mkdir -p "${DEST}/python"
cp -a "${SRC}/python/." "${DEST}/python/"

echo
echo "imported:"
echo "  src/python : $(find "${DEST}/src/python" -type f | wc -l) files"
echo "  python     : $(find "${DEST}/python" -type f | wc -l) files"
echo
echo "next: record the extension in third_party/qgis/UPSTREAM.md and configure"
echo "with -DPALEO_WITH_QGIS_PYTHON=ON (bindings additionally need a sip >= 6"
echo "matching the installed PyQt6)."
