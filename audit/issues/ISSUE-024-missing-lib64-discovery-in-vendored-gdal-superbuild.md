# ISSUE-024: Missing `lib64` Discovery in Vendored GDAL Superbuild

- **Severity**: Medium
- **Subproject**: `scripts` (`scripts/build_vendored_gdal.sh`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/scripts/build_vendored_gdal.sh#L102-L114`

---

## Defect Description & Root Cause Analysis

In `scripts/build_vendored_gdal.sh`, the environment export generator locates Python `osgeo` bindings and configures the dynamic library path:

```bash
export LD_LIBRARY_PATH="${PREFIX}/lib:\${LD_LIBRARY_PATH:-}"
# ...
OSGEO_SITE="$(find "${PREFIX}/lib" -maxdepth 4 -type d -name site-packages -path "*python*" 2>/dev/null | head -1)"
if [ -n "${OSGEO_SITE}" ] && [ -d "${OSGEO_SITE}/osgeo" ]; then
  echo "export PYTHONPATH=\"${OSGEO_SITE}:\${PYTHONPATH:-}\"" >> "${PREFIX}/env.sh"
  echo "osgeo exposed via PYTHONPATH=${OSGEO_SITE}"
else
  echo "WARNING: osgeo bindings not found under ${PREFIX}/lib" >&2
  exit 1
fi
```

The script only searches under `${PREFIX}/lib`. On 64-bit Linux distributions (such as RHEL, CentOS, Fedora, openSUSE, and Gentoo), CMake's `GNUInstallDirs` defaults `CMAKE_INSTALL_LIBDIR` to `lib64`. Consequently, CMake installs `libgdal.so` and Python site-packages into `${PREFIX}/lib64`.

Because `find "${PREFIX}/lib"` returns empty, the script outputs `"WARNING: osgeo bindings not found under ${PREFIX}/lib"` and terminates with exit code 1. In addition, `LD_LIBRARY_PATH` only contains `${PREFIX}/lib`, preventing the runtime dynamic linker from finding `libgdal.so` located in `${PREFIX}/lib64`.

---

## Impact Analysis

- **Build Pipeline Failure**: Vendored GDAL superbuild fails unconditionally on 64-bit RPM-based or `lib64` Linux distributions.
- **Runtime Linker Failures**: Python bindings cannot locate `libgdal.so` when installed into `lib64`.

---

## Reproduction Scenario & Execution Proof

### Reproduction Trace
1. Run `scripts/build_vendored_gdal.sh` on Fedora / RHEL 9 / CentOS Stream.
2. CMake completes the build and installs artifacts to `${PREFIX}/lib64`.
3. Script executes `find "${PREFIX}/lib"` -> returns empty string.
4. Script outputs `WARNING: osgeo bindings not found under .../lib` and exits with error code 1.

---

## Concrete Suggested Fix

Include both `${PREFIX}/lib` and `${PREFIX}/lib64` in `LD_LIBRARY_PATH` and search paths:

### Patch (`scripts/build_vendored_gdal.sh`)
```bash
# In scripts/build_vendored_gdal.sh:
cat > "${PREFIX}/env.sh" <<EOF
export GDAL_VENDORED_PREFIX="${PREFIX}"
export GDAL_DATA="${PREFIX}/share/gdal"
export LD_LIBRARY_PATH="${PREFIX}/lib:${PREFIX}/lib64:\${LD_LIBRARY_PATH:-}"
EOF

OSGEO_SITE="$(find "${PREFIX}"/lib* -maxdepth 4 -type d -name site-packages -path "*python*" 2>/dev/null | head -1)"
if [ -n "${OSGEO_SITE}" ] && [ -d "${OSGEO_SITE}/osgeo" ]; then
  echo "export PYTHONPATH=\"${OSGEO_SITE}:\${PYTHONPATH:-}\"" >> "${PREFIX}/env.sh"
  echo "osgeo exposed via PYTHONPATH=${OSGEO_SITE}"
else
  echo "WARNING: osgeo bindings not found under ${PREFIX}/lib or ${PREFIX}/lib64" >&2
  exit 1
fi
```
