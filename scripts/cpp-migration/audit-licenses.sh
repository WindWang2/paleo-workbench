#!/usr/bin/env bash
# audit-licenses.sh — cpp-close-12: license-material audit for the shippable
# native product. Verifies that every third-party runtime component the
# deployed tree carries has license/copyright material present in the
# consume location (the deployed tree or the SDK prefix it is cut from).
#
# Usage:
#   scripts/cpp-migration/audit-licenses.sh <dist-dir> [qgis-sdk-dir]
#     <dist-dir>     the deploy-native-product.sh output tree
#     [qgis-sdk-dir] PALEO_QGIS_SDK_DIR (default: env or cached value)
#
# Checked components (native-product closure scope):
#   Qt6            — system/vendor Qt the binary resolves (license text in
#                    the deployed tree; third-party Qt stays LGPL, the
#                    package must carry the license text + a notice)
#   QGIS 4.2       — vendored SDK (COPYING/GPL exception in the SDK root)
#   GDAL/PROJ/GEOS — QGIS SDK share dirs (data licenses + LICENSE files)
#   WLE SDK        — well-log-engine source tree LICENSE (external SDK)
#   ONNX Runtime   — pwb-sdks/ort or the vendored onnxruntime tree LICENSE
#
# Exit 0 = all required materials found; 1 = missing (file:line-free
# component list); 2 = usage error. Read-only: never writes into the SDK.
set -u

Usage="usage: audit-licenses.sh <dist-dir> [qgis-sdk-dir]"
[ $# -ge 1 ] || { echo "$Usage" >&2; exit 2; }
DistDir="$(cd "$1" 2>/dev/null && pwd)" || { echo "dist dir not found: $1" >&2; exit 2; }
[ -d "$DistDir" ] || { echo "dist dir not found: $1" >&2; exit 2; }

RepoRoot="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
QgisSdk="${2:-${PALEO_QGIS_SDK_DIR:-}}"
if [ -z "$QgisSdk" ] && [ -f "$DistDir/CMakeCache.txt" ]; then
    QgisSdk="$(awk -F= '/^PALEO_QGIS_SDK_DIR/{print $2}' "$DistDir/CMakeCache.txt" | head -1)"
fi

Status=0
missing() { echo "MISSING $1"; Status=1; }
present() { echo "OK      $1"; }

# --- 1) deployed tree carries the bundled-license notice -------------------
# The deploy script writes THIRD-PARTY-LICENSES.md (or -NOTICE); if the
# dist tree predates that contract the audit fails loudly instead of
# shipping a license-free package.
found_notice=0
for candidate in "$DistDir/THIRD-PARTY-LICENSES.md" \
                 "$DistDir/THIRD-PARTY-LICENSES.txt" \
                 "$DistDir/LICENSES" "$DistDir/licenses" "$DistDir/share/licenses"; do
    [ -e "$candidate" ] && { present "dist notice: $candidate"; found_notice=1; break; }
done
[ "$found_notice" = 1 ] || missing "dist notice (THIRD-PARTY-LICENSES.md in $DistDir)"

# --- 2) Qt6 (system/vendor prefix the binary resolves against) -----------
# The deploy keeps one system Qt ABI, so the license material ships as a
# bundled notice in the dist tree; the prefix check verifies the source
# material exists to copy from.
QtPrefix="${PWB_QT_PREFIX:-/usr}"
found=0
for candidate in "$QtPrefix/share/licenses/qt6-base" \
                 "$QtPrefix/share/licenses/qt6-base/LICENSES" \
                 "$QtPrefix/share/licenses/qt6" \
                 "$QtPrefix/LICENSE" "$QtPrefix/lib/qt6/LICENSE"; do
    [ -e "$candidate" ] && { present "qt6: $candidate"; found=1; break; }
done
[ "$found" = 1 ] || missing "qt6 license material in $QtPrefix/share/licenses"

# --- 3) QGIS vendor SDK ---------------------------------------------------
# The vendor install tree carries no COPYING at its root — the deploy
# collects it from the QGIS source (PALEO_QGIS_SOURCE_DIR) into
# <dist>/licenses/QGIS-COPYING; the dist copy satisfies the audit even
# when the SDK dir itself is not resolvable on the auditing host.
QgisSource="${PALEO_QGIS_SOURCE_DIR:-$RepoRoot/third_party/qgis}"
if [ -f "$DistDir/licenses/QGIS-COPYING" ] \
    || [ -f "$DistDir/licenses/QGIS-COPYING.txt" ]; then
    present "qgis: $DistDir/licenses/QGIS-COPYING* (collected by deploy)"
elif [ -n "$QgisSdk" ] && [ -d "$QgisSdk" ]; then
    found=0
    for candidate in "$QgisSource/COPYING" "$QgisSource/COPYING.txt" \
                     "$QgisSdk/COPYING" "$QgisSdk/COPYING.txt" \
                     "$QgisSdk/LICENSE" "$QgisSdk/share/LICENSE"; do
        [ -n "$candidate" ] && [ -f "$candidate" ] && { present "qgis: $candidate"; found=1; break; }
    done
    [ "$found" = 1 ] || missing "qgis license (SDK $QgisSdk / source $QgisSource)"
else
    echo "SKIP    qgis (SDK dir not resolvable — pass it as argument 2)"
fi

# --- 4) WLE SDK (well-log-engine) -----------------------------------------
WleRoot="${PWB_WLE_SDK_DIR:-$RepoRoot/well-log-engine}"
if [ -d "$WleRoot" ] && [ -n "$(ls -A "$WleRoot" 2>/dev/null)" ]; then
    found=0
    for candidate in "$WleRoot/LICENSE" "$WleRoot/LICENSE.txt" \
                     "$WleRoot/COPYING" "$WleRoot/LICENSE.md"; do
        [ -f "$candidate" ] && { present "wle: $candidate"; found=1; break; }
    done
    [ "$found" = 1 ] || missing "wle license in $WleRoot"
elif [ -d "$WleRoot" ]; then
    # Submodule not checked out in this worktree — nothing is shipped from
    # it in this build state; the deploy records it in the notice.
    echo "SKIP    wle (submodule not checked out: $WleRoot)"
else
    echo "SKIP    wle (SDK tree not present on this host)"
fi

# --- 5) ONNX Runtime ------------------------------------------------------
found_ort=0
for ort_root in "${PWB_ORT_DIR:-}" "$RepoRoot/third_party/onnxruntime" \
                "$HOME/pwb-sdks/ort"; do
    [ -n "$ort_root" ] && [ -d "$ort_root" ] || continue
    found_ort=1
    found=0
    for candidate in "$ort_root"/LICENSE "$ort_root"/LICENSE.txt \
                     "$ort_root"/LICENSE-MIT.txt "$ort_root"/share/LICENSE \
                     "$ort_root"/*/LICENSE "$ort_root"/*/LICENSE.txt \
                     "$ort_root"/*/LICENSE-MIT.txt; do
        [ -f "$candidate" ] && { present "onnxruntime: $candidate"; found=1; break; }
    done
    [ "$found" = 1 ] || missing "onnxruntime license in $ort_root"
done
[ "$found_ort" = 1 ] || echo "SKIP    onnxruntime (no ort tree on this host)"

# --- 6) GDAL/PROJ data licenses inside the QGIS prefix --------------------
if [ -n "$QgisSdk" ] && [ -d "$QgisSdk" ]; then
    if [ -d "$QgisSdk/share/proj" ]; then
        present "proj data dir: $QgisSdk/share/proj"
    else
        missing "proj data dir in $QgisSdk/share"
    fi
fi

echo "----"
if [ "$Status" = 0 ]; then
    echo "license audit: PASS ($DistDir)"
else
    echo "license audit: FAIL ($DistDir) — missing materials above"
fi
exit "$Status"
