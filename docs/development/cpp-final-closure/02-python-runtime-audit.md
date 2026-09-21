# Python Runtime Audit

The native source audit passes:

```text
no Python C API
no embedded interpreter
no PySide/shiboken dependency
no Python child process
pybind11 confined to mapping compatibility facades
```

The repository-wide dependency report still records Python outside the formal
native product:

- 13 effective CMake references, in optional binding tests or
  oracle/development gates;
- 83 packaging/document references, including the Python package's own
  `requires-python` declaration and vendored third-party metadata;
- one Python compatibility fallback seam:
  `paleo_workbench/mapping/geological_pipeline/native_bind.py`;
- six oracle-only Python modules.

These findings do not prove a native binary dependency. The final binary check
remains mandatory:

```bash
scripts/cpp-migration/audit-python-runtime-deps.sh --exe <pwb-platform>
```

The final closure gate also rejects `.py` and `.pyc` files in native install
and deployment trees. Binary and package checks are currently unexecuted
because Qt/QGIS prerequisites are unavailable in this environment.
