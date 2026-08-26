# ISSUE-028: Missing Dynamic Library RPATH for Arrow Adapter CTest Target

- **Severity**: Low
- **Subproject**: `well-log-engine` (`well-log-engine/CMakeLists.txt`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/well-log-engine/CMakeLists.txt#L1000-L1050`

---

## Defect Description & Root Cause Analysis

In `well-log-engine/CMakeLists.txt`, the test target `welllog_arrow_adapter_tests` links dynamically against Apache Arrow shared libraries (`libarrow.so.2400`).

However, the CMake target configuration does not embed `BUILD_RPATH` or `INSTALL_RPATH` pointing to the directory containing `libarrow.so`.

When native CTest suites are executed directly via `ctest` without pre-configuring the `LD_LIBRARY_PATH` environment variable, the Linux dynamic linker fails to locate `libarrow.so.2400`, failing the test target with:
`error while loading shared libraries: libarrow.so.2400: cannot open shared object file: No such file or directory`

---

## Impact Analysis

- **CI Test Failures**: CTest runner fails test 44 (`welllog.arrow-adapter`) in standard developer builds and automated build pipelines unless `LD_LIBRARY_PATH` is manually exported.

---

## Reproduction Scenario & Execution Proof

### Command Execution Trace
```bash
ctest --test-dir build/dev-python -R arrow-adapter --output-on-failure
# Output:
# 44/78 Test #44: welllog.arrow-adapter ....................***Failed    0.01 sec
# /path/to/welllog_arrow_adapter_tests: error while loading shared libraries: libarrow.so.2400: cannot open shared object file: No such file or directory
```

---

## Concrete Suggested Fix

Set the `BUILD_RPATH` and `INSTALL_RPATH` target properties on `welllog_arrow_adapter_tests` in `CMakeLists.txt`:

### Patch (`well-log-engine/CMakeLists.txt`)
```cmake
set_target_properties(welllog_arrow_adapter_tests PROPERTIES
    BUILD_RPATH "${ARROW_LIB_DIR}"
    INSTALL_RPATH "${ARROW_LIB_DIR}"
)
```
