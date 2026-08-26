# ISSUE-029: Submodule Worktree In-Place Mutation in `build_vendored_gdal.sh`

- **Severity**: Low
- **Subproject**: `scripts` (`scripts/build_vendored_gdal.sh`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/scripts/build_vendored_gdal.sh#L39-L43`

---

## Defect Description & Root Cause Analysis

In `scripts/build_vendored_gdal.sh`, legacy Python 2 SWIG macro compatibility fixes are applied using in-place stream editing (`sed -i`):

```bash
TYPEMAPS="${ROOT}/third_party/gdal/swig/include/python/typemaps_python.i"
if grep -q "PyInt_" "${TYPEMAPS}"; then
  sed -i 's/ || PyInt_Check($input)//g; s/PyInt_FromLong/PyLong_FromLong/g; s/PyInt_AsLong/PyLong_AsLong/g' "${TYPEMAPS}"
  echo "Patched Python-2 PyInt_* remnants in $(basename "${TYPEMAPS}")"
fi
```

The script mutates the file directly inside the tracked `third_party/gdal` Git submodule worktree.

---

## Impact Analysis

- **Dirty Git Submodule State**: Running `build_vendored_gdal.sh` permanently dirties the git submodule worktree. `git status` in `third_party/gdal` reports modified files, which causes subsequent submodule checkouts, CI git guardrails, or pull commands to fail or report uncommitted changes.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
# Run build script:
bash scripts/build_vendored_gdal.sh

# Check submodule git status:
git -C third_party/gdal status --short
# Output: M swig/include/python/typemaps_python.i
```

---

## Concrete Suggested Fix

Copy the SWIG interface files to the temporary CMake build staging directory before applying the `sed` substitution, or use CMake's patch step during configuration:

### Patch (`scripts/build_vendored_gdal.sh`)
```bash
# In scripts/build_vendored_gdal.sh:
cp -r "${ROOT}/third_party/gdal/swig" "${BUILD}/gdal_swig"
sed -i 's/ || PyInt_Check($input)//g; s/PyInt_FromLong/PyLong_FromLong/g; s/PyInt_AsLong/PyLong_AsLong/g' "${BUILD}/gdal_swig/include/python/typemaps_python.i"
```
