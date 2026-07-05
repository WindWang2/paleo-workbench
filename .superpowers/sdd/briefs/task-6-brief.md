### Task 6: Typed Visualization Adapter Schemas

**Files:**
- Create: `paleo_workbench/adapters/__init__.py`
- Create: `paleo_workbench/adapters/schemas.py`
- Create: `paleo_workbench/adapters/base.py`
- Create: `tests/test_adapter_schemas.py`

**Interfaces:**
- Produces: `ViewerPayload`, `ViewState`, `ExportRequest`, `ExportResult`, `AdapterError`
- Produces: abstract protocol `WorkbenchViewerAdapter`

- [ ] **Step 1: Write failing adapter schema tests**

Create `tests/test_adapter_schemas.py`:

```python
import pytest
from pydantic import ValidationError

from paleo_workbench.adapters.schemas import ExportRequest, ViewerPayload, ViewState


def test_viewer_payload_requires_schema_version():
    payload = ViewerPayload(
        viewer_type="paleo_map",
        schema_version="1.0",
        resources=[],
        layers=[],
        crs="EPSG:4326",
    )

    assert payload.viewer_type == "paleo_map"


def test_invalid_export_format_fails_validation():
    with pytest.raises(ValidationError):
        ExportRequest(path="out.xyz", format="xyz")


def test_view_state_round_trip():
    state = ViewState(schema_version="1.0", viewport={"zoom": 3}, selected_ids=["res_1"])

    assert state.model_dump()["viewport"]["zoom"] == 3
```

- [ ] **Step 2: Run adapter schema tests to verify they fail**

Run:

```bash
python -m pytest tests/test_adapter_schemas.py -v
```

Expected: FAIL with missing adapter modules.

- [ ] **Step 3: Implement schemas**

Create `paleo_workbench/adapters/__init__.py`:

```python
from paleo_workbench.adapters.schemas import AdapterError, ExportRequest, ExportResult, ViewerPayload, ViewState

__all__ = ["AdapterError", "ExportRequest", "ExportResult", "ViewerPayload", "ViewState"]
```

Create `paleo_workbench/adapters/schemas.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ViewerPayload(BaseModel):
    viewer_type: Literal["well_log", "seismic", "cross_well", "factor_map", "paleo_map"]
    schema_version: str = "1.0"
    resources: list[dict[str, Any]] = Field(default_factory=list)
    layers: list[dict[str, Any]] = Field(default_factory=list)
    style_hints: dict[str, Any] = Field(default_factory=dict)
    crs: str = "EPSG:4326"


class ViewState(BaseModel):
    schema_version: str = "1.0"
    viewport: dict[str, Any] = Field(default_factory=dict)
    selected_ids: list[str] = Field(default_factory=list)
    visible_layers: list[str] = Field(default_factory=list)
    style_overrides: dict[str, Any] = Field(default_factory=dict)


class ExportRequest(BaseModel):
    path: str
    format: Literal["pdf", "svg", "png", "geojson"]
    dpi: int | None = None
    vector_mode: bool = True
    selected_layers: list[str] = Field(default_factory=list)
    layout_options: dict[str, Any] = Field(default_factory=dict)


class ExportResult(BaseModel):
    output_path: str
    format: Literal["pdf", "svg", "png", "geojson"]
    byte_size: int | None = None
    warnings: list[str] = Field(default_factory=list)
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)


class AdapterError(BaseModel):
    adapter_name: str
    operation: str
    severity: Literal["warning", "error", "critical"]
    message: str
    recoverable: bool = True
    traceback_summary: str | None = None
```

- [ ] **Step 4: Implement adapter protocol**

Create `paleo_workbench/adapters/base.py`:

```python
from __future__ import annotations

from typing import Protocol

from paleo_workbench.adapters.schemas import ExportRequest, ExportResult, ViewerPayload, ViewState


class WorkbenchViewerAdapter(Protocol):
    def set_data(self, payload: ViewerPayload | dict) -> None:
        ...

    def set_view_state(self, state: ViewState | dict) -> None:
        ...

    def get_view_state(self) -> ViewState:
        ...

    def export(self, request: ExportRequest | dict) -> ExportResult:
        ...

    def clear(self) -> None:
        ...
```

- [ ] **Step 5: Run adapter schema tests**

Run:

```bash
python -m pytest tests/test_adapter_schemas.py -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/adapters tests/test_adapter_schemas.py
git commit -m "feat: add typed visualization adapter schemas"
```

If root git is still invalid, record checkpoint: `Task 6 complete; root commit pending repository repair`.

---

