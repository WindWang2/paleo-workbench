### Task 12: Optional Engine Adapter Hardening

Run this task only if Tasks 6-11 prove that a workbench adapter needs package-side changes in `geo-viz-engine`.

**Files:**
- Modify: `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/__init__.py`
- Create or modify: `geo-viz-engine/tests/test_paleo_workbench_adapter_import.py`

**Interfaces:**
- Consumes: existing `PaleoMapCanvas`
- Produces: stable import surface for workbench adapter code

- [ ] **Step 1: Write failing engine import test**

Create `geo-viz-engine/tests/test_paleo_workbench_adapter_import.py`:

```python
def test_paleo_map_canvas_is_public():
    from geoviz_paleo_map import PaleoMapCanvas

    assert PaleoMapCanvas is not None
```

- [ ] **Step 2: Run engine import test**

Run:

```bash
cd geo-viz-engine && python -m pytest tests/test_paleo_workbench_adapter_import.py -v
```

Expected: PASS if public import already exists. If it fails, continue.

- [ ] **Step 3: Export missing public symbol**

Modify `geo-viz-engine/packages/geoviz_paleo_map/geoviz_paleo_map/__init__.py` so it contains:

```python
from geoviz_paleo_map.canvas import PaleoMapCanvas

__all__ = ["PaleoMapCanvas"]
```

- [ ] **Step 4: Rerun engine import test**

Run:

```bash
cd geo-viz-engine && python -m pytest tests/test_paleo_workbench_adapter_import.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit engine change**

Because `geo-viz-engine` is a valid git repository, run:

```bash
cd geo-viz-engine
git add packages/geoviz_paleo_map/geoviz_paleo_map/__init__.py tests/test_paleo_workbench_adapter_import.py
git commit -m "feat: expose paleo map canvas for workbench adapter"
```

---

## Self-Review

### Spec Coverage

- UI prototype dependency: Task 8 creates screen inventory and prevents runtime bundle dependency.
- Root packaging: Task 1 creates `pyproject.toml`, package, and entry point.
- `.paleo.json` schema and artifact layout: Task 2 implements project models, path relativization, and artifact directories.
- Resource catalog and unsupported format policy: Task 3 implements scanner and `indexed_reference`.
- Compilation run and workflow dashboard state: Task 4 implements run and dashboard state.
- Deterministic mock factor maps and predictions: Task 5 implements seed/version/hash.
- Typed adapter boundary: Task 6 implements schemas and protocol.
- Minimal visualization adapter: Task 7 implements a testable `PaleoMapAdapter`.
- Workflow dashboard UI: Task 9 implements first screen.
- QC and export records: Task 10 implements records.
- MVP success criteria: Task 11 proves end-to-end recovery.
- `geo-viz-engine` independent boundary: Task 12 is optional and only touches the engine if a package public API is missing.

### Placeholder Scan

The plan avoids incomplete markers and vague steps. Mock output is intentional and deterministic, with explicit metadata for later replacement.

### Type Consistency

The plan consistently uses:

- `ProjectDocument.new(name: str, region: str = "") -> ProjectDocument`
- `ProjectManager.save(project: ProjectDocument) -> None`
- `ProjectManager.load() -> ProjectDocument`
- `ResourceItem`
- `create_compilation_run(project, name, target_horizon, sequence_scheme) -> CompilationRun`
- `dashboard_state(project) -> dict[str, object]`
- `create_mock_factor_map(project, target_horizon, factor_type, seed) -> FactorMapTask`
- `MockPredictionAdapter.run(project, factor_map_ids, seed) -> PredictionTask`
- `ViewerPayload`, `ViewState`, `ExportRequest`, `ExportResult`, `AdapterError`
- `PaleoMapAdapter`
