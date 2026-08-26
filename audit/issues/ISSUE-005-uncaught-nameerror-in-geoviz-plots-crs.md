# ISSUE-005: Uncaught `NameError` in `geoviz_plots.crs.coerce_to_project_crs`

- **Severity**: High
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_plots`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_plots/geoviz_plots/crs/__init__.py#L94`

---

## Defect Description & Root Cause Analysis

In `geoviz_plots/crs/__init__.py`, coordinate reference system (CRS) management provides context-variable-backed project CRS lookup.
At line 20, the module defines `_project_crs_var: ContextVar[str]`, and at line 30, it defines the accessor `get_project_crs() -> str`.

However, inside `coerce_to_project_crs(source_crs, geom)` at line 94:
```python
def coerce_to_project_crs(source_crs: str, geom: Any) -> Any:
    # ...
    target = _project_crs
    if not target or source_crs == target:
        return geom
    # ...
```

The variable `_project_crs` does not exist in the module's global or local scope. Any call to `coerce_to_project_crs` immediately aborts with `NameError: name '_project_crs' is not defined`.

---

## Impact Analysis

- **Functional Failure**: All automatic spatial reprojection workflows in `geoviz_plots` fail when loading geometries with explicit source CRSs.
- **Test Failures**: Multiple automated unit tests in `tests/test_geoviz_plots.py` fail unconditionally on invocation.

---

## Reproduction Scenario & Execution Proof

### Pytest Execution
```bash
pytest geo-viz-engine/tests/test_geoviz_plots.py -k "test_crs_coerce"
```

### Output:
```
FAILED test_geoviz_plots.py::test_crs_coerce_identity_when_source_equals_project - NameError: name '_project_crs' is not defined
FAILED test_geoviz_plots.py::test_crs_coerce_reprojects_wgs84_to_web_mercator - NameError: name '_project_crs' is not defined
```

---

## Concrete Suggested Fix

Replace `target = _project_crs` with `target = get_project_crs()` in `coerce_to_project_crs()`.

### Patch (`geo-viz-engine/packages/geoviz_plots/geoviz_plots/crs/__init__.py`)
```python
# In coerce_to_project_crs():
# BEFORE:
# target = _project_crs

# AFTER:
target = get_project_crs()
```
