# Visualization geo-viz Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shared `VizAdapter` turns project LAS / SEGY / paleomap assets into geo-viz payloads; data page jumps to visualization; visualization page loads real assets (with prediction mock fallback).

**Architecture:** Pure package `paleo_workbench/viz/` (no Qt widgets) exposes `VizRef` / `VizPayload` / `VizAdapter`. UI pages own canvases. Data page emits `open_in_visualization(VizRef)`; window switches to page index 5 and calls `VisualizationPage.open_ref`.

**Tech Stack:** Python 3.12, PySide6, pydantic models, lasio, optional segyio/numpy, geo-viz-engine (`WellLogCanvas`, `SeismicView`, `PaleoMapCanvas`), pytest-qt, `QT_QPA_PLATFORM=offscreen`.

## Global Constraints

- `paleo_workbench/viz/` must **not** import AppShell pages or create Qt widgets.
- SEGY loads are **bounded** (default max shape product ≤ 64×64×64 samples after downsample).
- LAS curves/samples are **bounded** (default max 12 curves, max 2000 samples per curve via stride).
- Missing/corrupt files → `VizPayload(kind="message", ...)` — never raise into the event loop from UI handlers.
- Keep prediction mock path: when no resource ref is set, visualization may still use `from_prediction`.
- Tests: `QT_QPA_PLATFORM=offscreen python -m pytest …`.
- Spec: `docs/superpowers/specs/2026-07-10-visualization-geoviz-adapter-design.md`.

## File map

| Path | Responsibility |
|------|----------------|
| Create `paleo_workbench/viz/__init__.py` | Public exports |
| Create `paleo_workbench/viz/models.py` | `VizKind`, `VizRef`, `VizPayload` |
| Create `paleo_workbench/viz/well_log_load.py` | LAS path → `WellLogData` |
| Create `paleo_workbench/viz/seismic_load.py` | SEGY path → bounded `ndarray` |
| Create `paleo_workbench/viz/map_load.py` | `PaleoMapDocument` → map canvas fields |
| Create `paleo_workbench/viz/adapter.py` | `VizAdapter.supports` / `resolve` / ref helpers / prediction bridge |
| Create `tests/test_viz_adapter.py` | Adapter + loaders unit tests |
| Modify `paleo_workbench/ui/pages/composite_visualization_panel.py` | 古地理 tab + `load_payload` |
| Modify `paleo_workbench/ui/pages/visualization_summary_panel.py` | Selectable asset list + signal |
| Modify `paleo_workbench/ui/pages/visualization_trace_panel.py` | Show VizRef; wire refresh |
| Modify `paleo_workbench/ui/pages/visualization_page.py` | `open_ref`, project state, signals |
| Create `tests/test_visualization_open_ref.py` | Page open_ref / tab selection |
| Modify `paleo_workbench/ui/pages/action_panel.py` | 「在可视化中打开」 button |
| Modify `paleo_workbench/ui/pages/data_page.py` | Enable button + emit `VizRef` |
| Modify `paleo_workbench/app.py` | Connect jump → switch page + `open_ref` |
| Modify `paleo_workbench/ui/app_shell.py` | Optional helper to expose visualization page |
| Create `tests/test_visualization_jump.py` | Data page → visualization integration |
| Modify `task_plan.md` / `progress.md` / `findings.md` | Phase note |

---

### Task 1: viz package models + loaders + adapter

**Files:**
- Create: `paleo_workbench/viz/__init__.py`
- Create: `paleo_workbench/viz/models.py`
- Create: `paleo_workbench/viz/well_log_load.py`
- Create: `paleo_workbench/viz/seismic_load.py`
- Create: `paleo_workbench/viz/map_load.py`
- Create: `paleo_workbench/viz/adapter.py`
- Test: `tests/test_viz_adapter.py`

**Interfaces:**
- Produces:
  - `VizRef(kind: str, id: str, path: str = "", label: str = "", source: str = "")`
  - `VizPayload(kind, label, message="", warning="", well_log=None, seismic_volume=None, map_features=None, map_wells=None, period_name="")`
  - `VizAdapter.supports_resource(resource) -> bool`
  - `VizAdapter.ref_from_resource(resource) -> VizRef | None`
  - `VizAdapter.ref_from_map_document(doc) -> VizRef`
  - `VizAdapter.resolve(ref, project: ProjectDocument) -> VizPayload`
  - `VizAdapter.from_prediction(task) -> VizPayload`

- [ ] **Step 1: Write failing unit tests**

```python
# tests/test_viz_adapter.py
from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizPayload, VizRef
from paleo_workbench.viz.well_log_load import load_well_log_from_path


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. TEST:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def test_supports_resource_kinds():
    adapter = VizAdapter()
    las = ResourceItem(name="a.las", path="/x/a.las", type="well_log", format="las")
    sgy = ResourceItem(name="b.sgy", path="/x/b.sgy", type="seismic", format="sgy")
    txt = ResourceItem(name="c.txt", path="/x/c.txt", type="document", format="txt")
    assert adapter.supports_resource(las) is True
    assert adapter.supports_resource(sgy) is True
    assert adapter.supports_resource(txt) is False


def test_load_well_log_from_minimal_las(tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    data = load_well_log_from_path(str(path))
    assert data is not None
    assert data.well_name
    assert data.curves
    assert len(data.curves[0].depth) >= 2


def test_resolve_missing_las_returns_message():
    project = ProjectDocument.new("P")
    res = ResourceItem(
        name="missing.las",
        path="/no/such/missing.las",
        type="well_log",
        format="las",
        status="missing",
    )
    project.resources.append(res)
    adapter = VizAdapter()
    ref = adapter.ref_from_resource(res)
    assert ref is not None
    payload = adapter.resolve(ref, project)
    assert payload.kind == "message"
    assert payload.message


def test_resolve_map_document():
    project = ProjectDocument.new("P")
    doc = PaleoMapDocument(
        name="M1",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
        }],
        well_overlays=[{"name": "W1", "x": 0.5, "y": 0.5}],
    )
    project.paleomap_documents.append(doc)
    adapter = VizAdapter()
    ref = adapter.ref_from_map_document(doc)
    payload = adapter.resolve(ref, project)
    assert payload.kind == "map"
    assert payload.map_features
    assert payload.period_name == "H1"
    assert payload.map_wells


def test_from_prediction_still_works():
    from paleo_workbench.project.models import PredictionTask

    task = PredictionTask(name="T1", seed=1, result_summary={
        "predicted_regions": [{"facies": "砂", "probability": 0.8}],
    })
    payload = VizAdapter().from_prediction(task)
    assert payload.kind in {"well_log", "prediction"}
    assert payload.well_log is not None
```

- [ ] **Step 2: Run tests — expect fail (import / missing module)**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_viz_adapter.py -q --tb=short
```

Expected: FAIL with `ModuleNotFoundError: paleo_workbench.viz` or similar.

- [ ] **Step 3: Implement models**

```python
# paleo_workbench/viz/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

VizKind = Literal["well_log", "seismic", "map", "prediction", "message"]


@dataclass(frozen=True)
class VizRef:
    kind: VizKind
    id: str
    path: str = ""
    label: str = ""
    source: str = ""


@dataclass
class VizPayload:
    kind: VizKind
    label: str
    message: str = ""
    warning: str = ""
    well_log: Any = None  # WellLogData | None
    seismic_volume: np.ndarray | None = None
    map_features: list[dict[str, Any]] | None = None
    map_wells: list[dict[str, Any]] | None = None
    period_name: str = ""
```

- [ ] **Step 4: Implement well_log_load / seismic_load / map_load**

```python
# paleo_workbench/viz/well_log_load.py — sketch
MAX_CURVES = 12
MAX_SAMPLES = 2000

def load_well_log_from_path(path: str):
    """Return WellLogData or None on failure. Uses lasio; stride samples if long."""
    ...

# paleo_workbench/viz/seismic_load.py
MAX_DIM = 64

def load_seismic_volume_from_path(path: str) -> tuple[np.ndarray | None, str]:
    """Return (volume, warning). volume None on failure. Bound to MAX_DIM^3 budget."""
    ...

# paleo_workbench/viz/map_load.py
def load_map_payload_from_document(doc) -> tuple[list, list, str]:
    """Reuse mapping_helpers.preview_payload_from_document."""
    from paleo_workbench.ui.pages.mapping_helpers import preview_payload_from_document
    return preview_payload_from_document(doc)
```

Note: `map_load` may import `mapping_helpers` (pure helpers already; no page widgets). Prefer moving pure helpers later if needed — for V1 reusing `preview_payload_from_document` is OK.

- [ ] **Step 5: Implement VizAdapter**

```python
# paleo_workbench/viz/adapter.py
class VizAdapter:
    WELL_TYPES = {"well_log"}
    WELL_FORMATS = {"las"}
    SEISMIC_TYPES = {"seismic"}
    SEISMIC_FORMATS = {"sgy", "segy"}

    def supports_resource(self, resource) -> bool: ...
    def ref_from_resource(self, resource) -> VizRef | None: ...
    def ref_from_map_document(self, doc) -> VizRef: ...
    def resolve(self, ref: VizRef, project) -> VizPayload: ...
    def from_prediction(self, task) -> VizPayload:
        # bridge prediction_helpers.well_log_data_from_prediction
        # and optionally attach seismic_volume_from_prediction on same payload
        # kind can be "prediction" with well_log set, or dual-load in UI
        ...
```

`resolve` for `well_log`/`seismic`: find resource by `ref.id` in `project.resources`, then load path.  
`resolve` for `map`: find `paleomap_documents` by id.  
On failure: `VizPayload(kind="message", label=ref.label, message="…")`.

- [ ] **Step 6: Export package**

```python
# paleo_workbench/viz/__init__.py
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.viz.models import VizPayload, VizRef

__all__ = ["VizAdapter", "VizPayload", "VizRef"]
```

- [ ] **Step 7: Run tests — expect pass**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_viz_adapter.py -q --tb=short
```

Expected: PASS (SEGY tests may skip if no fixture/segyio; do not require real SEGY file for green — message path is enough).

Optional extra test with monkeypatched `load_seismic_volume_from_path` returning a small array.

- [ ] **Step 8: Commit**

```bash
git add paleo_workbench/viz tests/test_viz_adapter.py
git commit -m "feat: add VizAdapter for LAS, SEGY, and map payloads"
```

---

### Task 2: Visualization page open_ref + 古地理 tab

**Files:**
- Modify: `paleo_workbench/ui/pages/composite_visualization_panel.py`
- Modify: `paleo_workbench/ui/pages/visualization_summary_panel.py`
- Modify: `paleo_workbench/ui/pages/visualization_trace_panel.py`
- Modify: `paleo_workbench/ui/pages/visualization_page.py`
- Test: `tests/test_visualization_open_ref.py`
- Update: `tests/test_visualization_page.py` / `tests/test_visualization_summary_panel.py` if assertions break

**Interfaces:**
- Consumes: `VizAdapter`, `VizRef`, `VizPayload`
- Produces:
  - `CompositeVisualizationPanel.load_payload(payload: VizPayload) -> None`
  - `VisualizationPage.open_ref(ref: VizRef) -> None`
  - `VisualizationPage.update_state(resources, prediction_tasks, map_documents)` stores lists for resolve
  - `VisualizationSummaryPanel.asset_selected = Signal(object)`  # VizRef
  - `VisualizationTracePanel.refresh_requested = Signal()`
  - `VisualizationTracePanel.update_ref(ref, payload)`

- [ ] **Step 1: Write failing page tests**

```python
# tests/test_visualization_open_ref.py
from pathlib import Path

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.viz.adapter import VizAdapter


def _minimal_las(path: Path) -> None:
    # same content as Task 1 fixture
    ...


def test_open_ref_well_log_selects_well_tab(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    project = ProjectDocument.new("P")
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    project.resources.append(res)

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(project.resources, [], [])

    ref = VizAdapter().ref_from_resource(res)
    page.open_ref(ref)

    assert page.composite_panel.tabs.currentIndex() == 0  # 测井
    # tracks non-empty or canvas has data
    assert page.composite_panel.well_canvas is not None


def test_open_ref_map_selects_map_tab(qtbot):
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1", "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([], [], [doc])
    ref = VizAdapter().ref_from_map_document(doc)
    page.open_ref(ref)
    # 古地理 tab index — document which index after adding tab
    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "古地理"
```

- [ ] **Step 2: Run — expect fail**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_visualization_open_ref.py -q --tb=short
```

- [ ] **Step 3: Extend CompositeVisualizationPanel**

- Add `self.map_canvas = PaleoMapCanvas()` and tab `"古地理"`.
- Add method:

```python
def load_payload(self, payload: VizPayload) -> None:
    if payload.kind == "message":
        # clear or leave; empty labels optional
        return
    if payload.kind in {"well_log", "prediction"} and payload.well_log is not None:
        from geoviz_well_log import build_qpainter_tracks
        self.well_canvas.set_tracks(build_qpainter_tracks(payload.well_log))
        self.tabs.setCurrentIndex(self._tab_index("测井"))
    if payload.seismic_volume is not None:
        self.seismic_view.load_demo(payload.seismic_volume)
        if payload.kind == "seismic":
            self.tabs.setCurrentIndex(self._tab_index("地震"))
    if payload.kind == "map":
        feats = payload.map_features or []
        wells = payload.map_wells or []
        self.map_canvas.load_features(feats, period_name=payload.period_name, wells=wells)
        self.tabs.setCurrentIndex(self._tab_index("古地理"))
```

Keep existing `update_state(prediction_tasks)` as fallback when no current ref.

- [ ] **Step 4: Summary panel list**

- Store resources + map docs.
- `QListWidget` or clickable labels listing well_log/seismic resources and map documents.
- Emit `asset_selected(VizRef)` on activate.
- Keep count labels.

- [ ] **Step 5: Trace panel**

- Fields: source, label, kind, path/message.
- `refresh_btn` emits `refresh_requested`.
- `update_ref(ref: VizRef | None, payload: VizPayload | None)`.

- [ ] **Step 6: VisualizationPage**

```python
class VisualizationPage(QWidget):
    def __init__(...):
        self._resources = []
        self._prediction_tasks = []
        self._map_documents = []
        self._current_ref: VizRef | None = None
        self._adapter = VizAdapter()
        # wire summary.asset_selected -> open_ref
        # wire trace.refresh_requested -> _reload_current

    def update_state(self, resources, prediction_tasks, map_documents):
        self._resources = list(resources or [])
        ...
        self.summary_panel.update_state(...)
        if self._current_ref is None:
            self.composite_panel.update_state(prediction_tasks)  # legacy mock
        else:
            self.open_ref(self._current_ref)
        self.trace_panel.update_state(prediction_tasks, map_documents)

    def open_ref(self, ref: VizRef | None) -> None:
        if ref is None:
            return
        self._current_ref = ref
        project = self._project_stub()  # build minimal ProjectDocument or pass project in
        payload = self._adapter.resolve(ref, project)
        self.composite_panel.load_payload(payload)
        self.trace_panel.update_ref(ref, payload)
```

**Project access:** Prefer extending `update_state` to accept optional `project: ProjectDocument | None`, or assemble a temporary `ProjectDocument` with the three lists for resolve. Cleanest V1:

```python
def update_state(self, resources, prediction_tasks, map_documents, project=None):
    self._project = project
    ...
```

And change `AppShell.update_visualization_page` / window `_apply_project_to_shell` to pass `self.project` if easy; else construct:

```python
doc = ProjectDocument.new("_viz")
doc.resources = list(resources)
doc.prediction_tasks = list(prediction_tasks)
doc.paleomap_documents = list(map_documents)
```

- [ ] **Step 7: Run tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_visualization_open_ref.py tests/test_visualization_page.py tests/test_visualization_summary_panel.py tests/test_visualization_trace_panel.py tests/test_visualization_integration.py -q --tb=short
```

Expected: PASS (update legacy tests for new widgets/tabs as needed).

- [ ] **Step 8: Commit**

```bash
git add paleo_workbench/ui/pages/composite_visualization_panel.py \
  paleo_workbench/ui/pages/visualization_*.py tests/test_visualization_*.py
git commit -m "feat: visualization open_ref and paleomap tab"
```

---

### Task 3: Data page button + AppShell jump

**Files:**
- Modify: `paleo_workbench/ui/pages/action_panel.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/app.py`
- Modify: `paleo_workbench/ui/app_shell.py` (if needed for page access)
- Test: `tests/test_visualization_jump.py`

**Interfaces:**
- Produces:
  - `DataPage.open_in_visualization = Signal(object)`  # VizRef
  - `ActionPanel.open_visualization_btn`
  - `PaleoWorkbenchWindow._on_open_in_visualization(ref)`

- [ ] **Step 1: Failing integration test**

```python
# tests/test_visualization_jump.py
from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION


def _minimal_las(path: Path) -> None:
    ...


def test_data_page_jump_switches_to_visualization(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    window.project.resources.append(res)
    window._apply_project_to_shell()

    data_page = window.app_shell.data_page_widget()
    data_page._set_selected_asset(res)  # or public select API
    assert data_page.action_panel.open_visualization_btn.isEnabled() is True

    data_page.action_panel.open_visualization_btn.click()
    assert window.app_shell.page_stack.currentIndex() == PAGE_INDEX_VISUALIZATION
```

- [ ] **Step 2: Action panel button**

```python
self.open_visualization_btn = QPushButton("在可视化中打开")
self.open_visualization_btn.setObjectName("SecondaryButton")
self.open_visualization_btn.setEnabled(False)
layout.addWidget(self.open_visualization_btn)
```

Update `set_selection_enabled` / existing enable helpers so the button is only enabled when data page says so.

- [ ] **Step 3: Data page**

```python
from PySide6.QtCore import Signal
from paleo_workbench.viz.adapter import VizAdapter

class DataPage(QWidget):
    open_in_visualization = Signal(object)

    def __init__(...):
        self._viz_adapter = VizAdapter()
        self.open_visualization_btn = self.action_panel.open_visualization_btn
        self.open_visualization_btn.clicked.connect(self._emit_open_visualization)

    def _sync_visualization_button(self):
        asset = self._selected_asset
        ok = isinstance(asset, ResourceItem) and self._viz_adapter.supports_resource(asset)
        self.open_visualization_btn.setEnabled(ok)

    def _emit_open_visualization(self):
        asset = self._selected_asset
        ref = self._viz_adapter.ref_from_resource(asset) if asset else None
        if ref is not None:
            ref = VizRef(..., source="data_page")  # or replace source field
            self.open_in_visualization.emit(ref)
```

Call `_sync_visualization_button` whenever selection changes.

- [ ] **Step 4: Wire window**

In `PaleoWorkbenchWindow._wire_toolbar` or after shell create / `_refresh_shell`:

```python
def _wire_data_visualization_jump(self):
    page = self.app_shell.data_page_widget()
    if hasattr(page, "open_in_visualization"):
        page.open_in_visualization.connect(self._on_open_in_visualization)

def _on_open_in_visualization(self, ref) -> None:
    from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION
    self.app_shell.page_stack.setCurrentIndex(PAGE_INDEX_VISUALIZATION)
    # also update icon rail if it tracks index
    viz = self.app_shell.page_stack.widget(PAGE_INDEX_VISUALIZATION)
    if hasattr(viz, "open_ref"):
        viz.open_ref(ref)
```

If `IconRail` must stay in sync, call the same path as clicking the visualization nav item (prefer existing `_switch_page` if public).

- [ ] **Step 5: Run tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_visualization_jump.py tests/test_data_page.py tests/test_app_shell.py -q --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/pages/action_panel.py paleo_workbench/ui/pages/data_page.py \
  paleo_workbench/app.py paleo_workbench/ui/app_shell.py tests/test_visualization_jump.py
git commit -m "feat: open visualization from data page assets"
```

---

### Task 4: Refresh polish, prediction fallback, planning docs, full suite

**Files:**
- Modify: visualization page refresh path (if not complete)
- Modify: `task_plan.md`, `progress.md`, `findings.md`
- Test: extend `tests/test_viz_adapter.py` for prediction dual payload if needed

- [ ] **Step 1: Ensure refresh re-resolves current ref**

```python
def _reload_current(self):
    if self._current_ref is not None:
        self.open_ref(self._current_ref)
    else:
        self.composite_panel.update_state(self._prediction_tasks)
```

- [ ] **Step 2: Prediction fallback when no ref**

When `open_ref` not used and prediction tasks exist, `from_prediction` still feeds well tab (and seismic volume if desired). Cross-well tab may keep existing dual-canvas behavior from prediction data.

- [ ] **Step 3: Full suite**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q --tb=line
```

Expected: all previous tests + new ones green (skips for optional C++ unchanged).

- [ ] **Step 4: Update planning files**

- `task_plan.md`: Phase 17 visualization geo-viz adapter complete (or in progress).
- `progress.md`: session note with modules and test count.
- `findings.md`: adapter boundary, bounds constants, jump wiring.

- [ ] **Step 5: Commit**

```bash
git add task_plan.md progress.md findings.md paleo_workbench/ui/pages/visualization_page.py
git commit -m "docs: record visualization geo-viz adapter delivery"
```

- [ ] **Step 6: Push** (only if user wants / default main workflow)

```bash
git push origin main
```

---

## Spec coverage checklist

| Spec requirement | Task |
|------------------|------|
| `paleo_workbench/viz/` pure package | 1 |
| VizRef / VizPayload / adapter API | 1 |
| LAS / SEGY / map resolve | 1 |
| Prediction mock bridge | 1, 4 |
| Visualization open_ref + tabs + 古地理 | 2 |
| Summary list selection | 2 |
| Trace + refresh | 2, 4 |
| Data page button + signal | 3 |
| Window switch to index 5 | 3 |
| Missing file message | 1, 2 |
| Bounded SEGY/LAS | 1 |
| Tests adapter / open_ref / jump | 1–3 |
| Full suite + planning docs | 4 |

## Placeholder / consistency review

- No TBD steps; SEGY file fixture optional — message path required, happy path can use monkeypatch.
- Tab index for 古地理 must be read from `tabText` in tests (not hard-coded if order shifts).
- `VizRef.source` set to `"data_page"` on jump.
- `map_load` reuses `preview_payload_from_document` — same GeoJSON/wells contract as mapping preview.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-visualization-geoviz-adapter.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session, executing-plans with checkpoints  

Which approach?
