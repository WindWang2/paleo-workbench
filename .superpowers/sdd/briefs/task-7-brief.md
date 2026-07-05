### Task 7: Minimal Paleo Map Adapter

**Files:**
- Create: `paleo_workbench/adapters/paleo_map.py`
- Modify: `tests/test_adapter_schemas.py`

**Interfaces:**
- Consumes: `ViewerPayload`, `ViewState`, `ExportRequest`, `ExportResult`
- Produces: `PaleoMapAdapter`

- [ ] **Step 1: Write failing adapter behavior test**

Append to `tests/test_adapter_schemas.py`:

```python
from pathlib import Path

from paleo_workbench.adapters.paleo_map import PaleoMapAdapter


def test_paleo_map_adapter_validates_payload_and_exports_metadata(tmp_path: Path):
    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "resources": [], "layers": []})
    adapter.set_view_state({"schema_version": "1.0", "viewport": {"zoom": 2}})

    result = adapter.export({"path": str(tmp_path / "map.geojson"), "format": "geojson"})

    assert adapter.get_view_state().viewport["zoom"] == 2
    assert result.output_path.endswith("map.geojson")
    assert Path(result.output_path).exists()
```

- [ ] **Step 2: Run adapter behavior test to verify it fails**

Run:

```bash
python -m pytest tests/test_adapter_schemas.py::test_paleo_map_adapter_validates_payload_and_exports_metadata -v
```

Expected: FAIL with missing `paleo_workbench.adapters.paleo_map`.

- [ ] **Step 3: Implement minimal adapter**

Create `paleo_workbench/adapters/paleo_map.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from paleo_workbench.adapters.schemas import ExportRequest, ExportResult, ViewerPayload, ViewState


class PaleoMapAdapter:
    adapter_name = "paleo_map"

    def __init__(self):
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()

    def set_data(self, payload: ViewerPayload | dict) -> None:
        parsed = payload if isinstance(payload, ViewerPayload) else ViewerPayload.model_validate(payload)
        if parsed.viewer_type != "paleo_map":
            raise ValueError(f"PaleoMapAdapter cannot render {parsed.viewer_type}")
        self._payload = parsed

    def set_view_state(self, state: ViewState | dict) -> None:
        self._state = state if isinstance(state, ViewState) else ViewState.model_validate(state)

    def get_view_state(self) -> ViewState:
        return self._state

    def export(self, request: ExportRequest | dict) -> ExportResult:
        parsed = request if isinstance(request, ExportRequest) else ExportRequest.model_validate(request)
        output = Path(parsed.path)
        output.parent.mkdir(parents=True, exist_ok=True)
        if parsed.format == "geojson":
            output.write_text(
                json.dumps({"type": "FeatureCollection", "features": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            output.write_text(f"minimal {parsed.format} export\n", encoding="utf-8")
        return ExportResult(
            output_path=output.as_posix(),
            format=parsed.format,
            byte_size=output.stat().st_size,
            artifact_metadata={"adapter": self.adapter_name},
        )

    def clear(self) -> None:
        self._payload = ViewerPayload(viewer_type="paleo_map")
        self._state = ViewState()
```

- [ ] **Step 4: Run adapter behavior tests**

Run:

```bash
python -m pytest tests/test_adapter_schemas.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/adapters/paleo_map.py tests/test_adapter_schemas.py
git commit -m "feat: add minimal paleo map adapter"
```

If root git is still invalid, record checkpoint: `Task 7 complete; root commit pending repository repair`.

---

