# GeoViz Local Data Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `geo-viz-engine` into the single public visualization package and use it to render bounded, interactive geological previews in the data page's existing right-side reader.

**Architecture:** The nested `geo-viz-engine` repository exposes a stable `geoviz` facade, thread-safe preparation contracts, a backend registry, and preview widgets backed by its existing specialist packages. `paleo_workbench` converts `ResourceItem` objects into facade requests, prepares bounded payloads through the existing latest-only worker, caches them by byte weight, and renders them on the UI thread through a reusable preview host; unsupported formats fall back to the existing reader.

**Tech Stack:** Python 3.12, PySide6, Pydantic/dataclasses, NumPy, lasio-compatible LAS semantics, segyio, geoviz-well-log, geoviz-seismic, geoviz-cross-well, geoviz-plots, pytest, pytest-qt.

## Global Constraints

- `geo-viz-engine` must never import or depend on `paleo_workbench`.
- Workbench production modules must import professional visualization APIs from `geoviz`, not directly from `geoviz_*` packages.
- `GeoVizEngine.prepare()` is worker-thread safe and returns no Qt objects; widget creation, rendering, and release are UI-thread-only.
- Local LAS previews display at most 12 non-depth curves and 2,000 depth rows.
- Local SGY previews read only selected two-dimensional slices and cap each displayed axis at 512 samples; they must not initialize the three-dimensional renderer.
- Point plots cap at 50,000 representative points; surface grids cap at 256 by 256.
- SpreadsheetML initial parsing caps at 256 KiB, 200 rows, 40 columns, and one active sheet.
- ZIP preview lists at most 500 entries and never extracts archive content.
- Prepared GeoViz payloads use a 128 MiB byte-weighted LRU; an individual payload over budget is rendered once and not cached.
- Preview failures are non-modal, clear stale professional graphics, and fall back to the existing reader when possible.
- DFB and WLP are not heuristically interpreted as geological data without a reliable parser.
- `geo-viz-engine` is a nested Git repository. Commit engine changes inside it first; only stage the parent `geo-viz-engine` gitlink when the referenced engine commit is independently usable.

---

## File Structure

### GeoViz engine repository

- Create `geo-viz-engine/geoviz/contracts.py`: stable request, options, capabilities, kinds, and prepared-payload contracts.
- Create `geo-viz-engine/geoviz/errors.py`: structured public error codes and `GeoVizError`.
- Create `geo-viz-engine/geoviz/registry.py`: backend protocol and deterministic backend selection.
- Create `geo-viz-engine/geoviz/engine.py`: public orchestration API and default backend registration.
- Create `geo-viz-engine/geoviz/__init__.py`: public facade plus compatibility exports for established canvases/models.
- Create `geo-viz-engine/geoviz/previews/well_log.py`: LAS backend.
- Create `geo-viz-engine/geoviz/previews/seismic.py`: two-dimensional SGY backend.
- Create `geo-viz-engine/geoviz/previews/dat.py`: semantic DAT parsing and plot/surface backends.
- Create `geo-viz-engine/geoviz/previews/__init__.py`: backend exports.
- Create `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/las_preview.py`: bounded two-pass LAS-to-`WellLogData` loader.
- Create `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/preview_widget.py`: non-OpenGL slice switcher built on `ProfileWidget`.
- Create `geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/formation_preview.py`: lightweight well-versus-depth formation-top canvas.
- Modify specialist package `__init__.py` files only to export those reusable APIs.
- Create focused engine tests under `geo-viz-engine/tests/test_geoviz_*.py`.

### Workbench repository

- Create `paleo_workbench/ui/pages/geoviz_preview_provider.py`: `ResourceItem` conversion and professional-preview/fallback composition.
- Create `paleo_workbench/ui/pages/geoviz_preview_host.py`: lazy widget creation, render switching, clearing, and release.
- Modify `preview_provider.py`, `data_reader_panel.py`, `preview_cache.py`, `preview_worker.py`, and `data_page.py` to carry, cache, render, and release prepared engine payloads.
- Modify existing visualization modules to import the public `geoviz` facade.
- Add focused tests under `tests/test_geoviz_*.py` and extend existing preview/cache/integration tests.

---

### Task 1: Public GeoViz contracts and installable facade

**Files:**
- Create: `geo-viz-engine/geoviz/contracts.py`
- Create: `geo-viz-engine/geoviz/errors.py`
- Create: `geo-viz-engine/geoviz/__init__.py`
- Modify: `geo-viz-engine/pyproject.toml`
- Test: `geo-viz-engine/tests/test_geoviz_contracts.py`

**Interfaces:**
- Consumes: no workbench types.
- Produces: `PreviewKind`, `PreviewRequest`, `PreviewOptions`, `PreviewCapabilities`, `PreparedPreview`, `ErrorCode`, and `GeoVizError`.

- [ ] **Step 1: Write the failing public-contract tests**

```python
from pathlib import Path

import pytest

from geoviz import (
    ErrorCode,
    GeoVizError,
    PreparedPreview,
    PreviewKind,
    PreviewOptions,
    PreviewRequest,
)


def test_local_options_are_exact_and_immutable():
    options = PreviewOptions.local()
    assert options.max_curves == 12
    assert options.max_depth_samples == 2_000
    assert options.max_slice_axis == 512
    assert options.max_points == 50_000
    assert options.surface_grid_size == 256
    with pytest.raises(AttributeError):
        options.max_curves = 99


def test_request_normalizes_format_without_workbench_model(tmp_path: Path):
    request = PreviewRequest(
        resource_id="r1",
        path=str(tmp_path / "A1.Las"),
        semantic_type="well_log",
        format=".LAS",
        label="A1",
    )
    assert request.normalized_format == "las"


def test_prepared_preview_reports_memory_weight():
    preview = PreparedPreview(
        kind=PreviewKind.WELL_LOG,
        title="A1",
        payload={"rows": 2_000},
        estimated_bytes=32_000,
    )
    assert preview.estimated_bytes == 32_000


def test_structured_error_preserves_public_code():
    error = GeoVizError(ErrorCode.INVALID_DATA, "LAS 曲线为空", detail="no curves")
    assert error.code is ErrorCode.INVALID_DATA
    assert str(error) == "LAS 曲线为空"
    assert error.detail == "no curves"
```

- [ ] **Step 2: Run the contract tests and verify the facade is absent**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_contracts.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'geoviz'`.

- [ ] **Step 3: Implement the frozen contracts and structured errors**

```python
# geo-viz-engine/geoviz/contracts.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class PreviewKind(StrEnum):
    WELL_LOG = "well_log"
    SEISMIC_2D = "seismic_2d"
    XY_SCATTER = "xy_scatter"
    FORMATION_TOPS = "formation_tops"
    SURFACE = "surface"
    TIME_DEPTH = "time_depth"


@dataclass(frozen=True)
class PreviewRequest:
    resource_id: str
    path: str
    semantic_type: str
    format: str
    label: str = ""

    @property
    def normalized_format(self) -> str:
        return self.format.strip().lower().lstrip(".") or Path(self.path).suffix.lower().lstrip(".")


@dataclass(frozen=True)
class PreviewOptions:
    profile: str = "local"
    max_curves: int = 12
    max_depth_samples: int = 2_000
    max_slice_axis: int = 512
    max_points: int = 50_000
    surface_grid_size: int = 256

    @classmethod
    def local(cls) -> "PreviewOptions":
        return cls()


@dataclass(frozen=True)
class PreviewCapabilities:
    kind: PreviewKind
    interactions: tuple[str, ...] = ()
    optional_dependency: str = ""


@dataclass(frozen=True)
class PreparedPreview:
    kind: PreviewKind
    title: str
    payload: object
    summary_rows: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    warning: str = ""
    estimated_bytes: int = 0
```

```python
# geo-viz-engine/geoviz/errors.py
from enum import StrEnum


class ErrorCode(StrEnum):
    UNSUPPORTED = "unsupported"
    INVALID_DATA = "invalid_data"
    DEPENDENCY_MISSING = "dependency_missing"
    IO_ERROR = "io_error"
    RESOURCE_LIMIT = "resource_limit"
    RENDER_ERROR = "render_error"


class GeoVizError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail
```

Export the contracts and errors from `geoviz/__init__.py`. Add `[tool.setuptools.packages.find]` with `include = ["geoviz*"]` to `geo-viz-engine/pyproject.toml` so the umbrella distribution contains the facade.

- [ ] **Step 4: Install the umbrella package and run the focused tests**

Run: `cd geo-viz-engine && .venv/bin/python -m pip install -e . --no-deps && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_contracts.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz pyproject.toml tests/test_geoviz_contracts.py
git -C geo-viz-engine commit -m "feat: add public geoviz preview contracts"
```

---

### Task 2: Backend registry, engine orchestration, and compatibility exports

**Files:**
- Create: `geo-viz-engine/geoviz/registry.py`
- Create: `geo-viz-engine/geoviz/engine.py`
- Modify: `geo-viz-engine/geoviz/__init__.py`
- Test: `geo-viz-engine/tests/test_geoviz_engine.py`
- Test: `geo-viz-engine/tests/test_geoviz_independence.py`

**Interfaces:**
- Consumes: contracts from Task 1.
- Produces: `PreviewBackend` protocol, `PreviewRegistry`, and `GeoVizEngine` with `supports`, `capabilities`, `prepare`, `create_widget`, `render`, and `release`.

- [ ] **Step 1: Write failing orchestration and independence tests**

```python
from pathlib import Path

from PySide6.QtWidgets import QLabel

from geoviz import GeoVizEngine, PreparedPreview, PreviewCapabilities, PreviewKind, PreviewOptions, PreviewRequest


class FakeBackend:
    kind = PreviewKind.XY_SCATTER

    def supports(self, request):
        return request.normalized_format == "dat"

    def capabilities(self, request):
        return PreviewCapabilities(self.kind, ("zoom", "pan"))

    def prepare(self, request, options):
        return PreparedPreview(self.kind, request.label, {"path": request.path}, estimated_bytes=64)

    def create_widget(self, parent=None):
        return QLabel(parent)

    def render(self, widget, preview):
        widget.setText(preview.title)

    def release(self, widget):
        widget.clear()


def test_engine_routes_prepare_and_ui_calls(qtbot, tmp_path: Path):
    engine = GeoVizEngine([FakeBackend()])
    request = PreviewRequest("r1", str(tmp_path / "wells.dat"), "well_head", "dat", "Wells")
    assert engine.supports(request)
    assert engine.capabilities(request).interactions == ("zoom", "pan")
    preview = engine.prepare(request, PreviewOptions.local())
    widget = engine.create_widget(preview.kind)
    qtbot.addWidget(widget)
    engine.render(widget, preview)
    assert widget.text() == "Wells"
    engine.release(widget)
    assert widget.text() == ""
```

The independence test must AST-scan `geo-viz-engine/geoviz/**/*.py` and assert no import root equals `paleo_workbench`.

- [ ] **Step 2: Run tests and verify `GeoVizEngine` is missing**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_engine.py tests/test_geoviz_independence.py -q`

Expected: FAIL during collection because `GeoVizEngine` is not exported.

- [ ] **Step 3: Implement deterministic backend routing**

```python
# geo-viz-engine/geoviz/registry.py
from __future__ import annotations

from typing import Protocol

from PySide6.QtWidgets import QWidget

from .contracts import PreparedPreview, PreviewCapabilities, PreviewKind, PreviewOptions, PreviewRequest
from .errors import ErrorCode, GeoVizError


class PreviewBackend(Protocol):
    kind: PreviewKind
    def supports(self, request: PreviewRequest) -> bool:
        raise NotImplementedError
    def capabilities(self, request: PreviewRequest) -> PreviewCapabilities:
        raise NotImplementedError
    def prepare(self, request: PreviewRequest, options: PreviewOptions) -> PreparedPreview:
        raise NotImplementedError
    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        raise NotImplementedError
    def render(self, widget: QWidget, preview: PreparedPreview) -> None:
        raise NotImplementedError
    def release(self, widget: QWidget) -> None:
        raise NotImplementedError


class PreviewRegistry:
    def __init__(self, backends: list[PreviewBackend] | tuple[PreviewBackend, ...] = ()) -> None:
        self._backends = list(backends)

    def backend_for_request(self, request: PreviewRequest) -> PreviewBackend:
        for backend in self._backends:
            if backend.supports(request):
                return backend
        raise GeoVizError(ErrorCode.UNSUPPORTED, f"不支持的可视化格式: {request.normalized_format}")

    def backend_for_kind(self, kind: PreviewKind) -> PreviewBackend:
        for backend in self._backends:
            if backend.kind is kind:
                return backend
        raise GeoVizError(ErrorCode.UNSUPPORTED, f"未注册的预览类型: {kind}")
```

Implement `GeoVizEngine` as a thin delegate around `PreviewRegistry`. `create_widget(kind)` records the widget-to-kind association in a `WeakKeyDictionary`; `release(widget)` uses that association to call the correct backend and then removes it. `GeoVizEngine.default()` must import and instantiate default backends locally inside the classmethod, so importing contracts does not construct Qt widgets or open optional libraries.

- [ ] **Step 4: Add lazy compatibility exports to the public facade**

Use module-level `__getattr__` with an explicit map for `WellLogCanvas`, `WellLogData`, `CurveData`, `build_qpainter_tracks`, `SeismicView`, `ProfileWidget`, `PaleoMapCanvas`, `CrossWellCanvas`, `PlotWidget`, and `SurfaceWidget`. Each lookup calls `importlib.import_module()` only when requested. Add `GeoVizEngine` and `PreviewRegistry` to ordinary facade exports.

- [ ] **Step 5: Run focused and existing package-independence tests**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_contracts.py tests/test_geoviz_engine.py tests/test_geoviz_independence.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz tests/test_geoviz_engine.py tests/test_geoviz_independence.py
git -C geo-viz-engine commit -m "feat: add geoviz backend registry"
```

---

### Task 3: Migrate existing workbench visualization imports to the facade

**Files:**
- Modify: `requirements-geoviz.txt`
- Modify: `paleo_workbench/ui/pages/composite_visualization_panel.py`
- Modify: `paleo_workbench/ui/pages/map_canvas_panel.py`
- Modify: `paleo_workbench/ui/pages/prediction_helpers.py`
- Modify: `paleo_workbench/ui/pages/seismic_view_panel.py`
- Modify: `paleo_workbench/ui/pages/well_log_canvas_panel.py`
- Modify: `paleo_workbench/viz/well_log_load.py`
- Modify: corresponding visualization tests that import `geoviz_*`
- Test: `tests/test_geoviz_package_independence.py`

**Interfaces:**
- Consumes: lazy compatibility exports from Task 2.
- Produces: a workbench whose production visualization imports use only `geoviz`.

- [ ] **Step 1: Add a failing AST boundary test**

```python
def test_workbench_production_imports_only_geoviz_facade():
    root = Path(__file__).resolve().parents[1] / "paleo_workbench"
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            names = [item.name for item in node.names] if isinstance(node, ast.Import) else []
            roots = [module.split(".")[0]] if module else [name.split(".")[0] for name in names]
            if any(name.startswith("geoviz_") for name in roots):
                violations.append(str(path.relative_to(root.parent)))
    assert not violations, violations
```

- [ ] **Step 2: Run the boundary test and capture current direct imports**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_package_independence.py::test_workbench_production_imports_only_geoviz_facade -q`

Expected: FAIL listing the current visualization modules.

- [ ] **Step 3: Replace production and test imports with facade imports**

For example, `composite_visualization_panel.py` must use:

```python
from geoviz import (
    CrossWellCanvas,
    PaleoMapCanvas,
    SeismicView,
    WellLogCanvas,
    build_qpainter_tracks,
)
```

`paleo_workbench/viz/well_log_load.py` must import `CurveData` and `WellLogData` from `geoviz`. Append `-e geo-viz-engine` after the internal editable packages in `requirements-geoviz.txt` so local installation exposes the facade.

- [ ] **Step 4: Run the visualization regression subset**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_package_independence.py tests/test_viz_adapter.py tests/test_composite_visualization_panel.py tests/test_visualization_canvas_alignment.py tests/test_well_log_canvas_panel.py tests/test_seismic_view_panel.py -q`

Expected: all tests pass with no direct production `geoviz_*` imports.

- [ ] **Step 5: Commit the usable facade boundary in the parent repository**

```bash
git add geo-viz-engine requirements-geoviz.txt paleo_workbench/ui/pages/composite_visualization_panel.py paleo_workbench/ui/pages/map_canvas_panel.py paleo_workbench/ui/pages/prediction_helpers.py paleo_workbench/ui/pages/seismic_view_panel.py paleo_workbench/ui/pages/well_log_canvas_panel.py paleo_workbench/viz/well_log_load.py tests/test_geoviz_package_independence.py tests/test_composite_visualization_panel.py tests/test_prediction_helpers.py tests/test_visualization_canvas_alignment.py tests/test_well_log_canvas_panel.py
git commit -m "refactor: consume geoviz through public facade"
```

Before committing, inspect `git diff --cached --name-only` and unstage any unrelated user files; the intended engine entry is the submodule gitlink plus the listed workbench/test files.

---

### Task 4: Bounded LAS loader and well-log preview backend

**Files:**
- Create: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/las_preview.py`
- Modify: `geo-viz-engine/packages/geoviz_well_log/geoviz_well_log/__init__.py`
- Create: `geo-viz-engine/geoviz/previews/well_log.py`
- Create: `geo-viz-engine/geoviz/previews/__init__.py`
- Modify: `geo-viz-engine/geoviz/engine.py`
- Test: `geo-viz-engine/tests/test_geoviz_well_log_preview.py`

**Interfaces:**
- Consumes: `PreviewOptions.max_curves`, `PreviewOptions.max_depth_samples`, `WellLogData`, `CurveData`, `WellLogCanvas`, and `build_qpainter_tracks`.
- Produces: `load_las_preview(path, max_curves, max_samples) -> WellLogData` and a default backend for `well_log`/`las`.

- [ ] **Step 1: Write failing bounded-loader and backend tests**

Create a LAS fixture with 5,001 ASCII rows and 15 non-depth curves. Assert the loader returns exactly 12 curves, no more than 2,000 depth rows, preserves first/last depth, maps `-99999` to `NaN`, and derives the display range from finite values. Assert the backend produces `PreviewKind.WELL_LOG`, a positive `estimated_bytes`, and a `WellLogCanvas` whose tracks are cleared by `release()`.

- [ ] **Step 2: Run the focused test and verify the loader is absent**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_well_log_preview.py -q`

Expected: FAIL importing `load_las_preview`.

- [ ] **Step 3: Implement a two-pass, bounded-memory LAS loader**

The first pass records WELL/NULL/curve headers and counts valid ASCII rows. Define `LASCurveHeader(index: int, mnemonic: str, unit: str, description: str)` and `LASPreviewHeader(well_name: str, null_value: float, depth_index: int, curves: tuple[LASCurveHeader, ...], row_count: int)`. Implement `inspect_las_file(path: str) -> LASPreviewHeader`, `read_sampled_ascii(path: str, header: LASPreviewHeader, selected: tuple[LASCurveHeader, ...], stride: int, max_samples: int) -> tuple[np.ndarray, dict[int, np.ndarray]]`, and `curve_data_from_arrays(header: LASCurveHeader, depth: np.ndarray, values: np.ndarray) -> CurveData`. The second pass keeps rows at `max(1, ceil(row_count / max_samples))` stride, includes the final valid row, and reads only the depth plus the first `max_curves` non-depth columns.

```python
def load_las_preview(path: str, *, max_curves: int = 12, max_samples: int = 2_000) -> WellLogData:
    header = inspect_las_file(path)
    selected = header.non_depth_curves[:max_curves]
    stride = max(1, math.ceil(header.row_count / max_samples))
    depth, values = read_sampled_ascii(path, header, selected, stride)
    if depth.size < 2:
        raise ValueError("LAS contains fewer than two depth rows")
    curves = [curve_data_from_arrays(item, depth, values[item.index]) for item in selected]
    return WellLogData(
        well_name=header.well_name or Path(path).stem,
        top_depth=float(np.nanmin(depth)),
        bottom_depth=float(np.nanmax(depth)),
        curves=curves,
    )
```

- [ ] **Step 4: Implement the well-log backend and register it by default**

`WellLogPreviewBackend.supports()` returns true only for normalized format `las` with semantic type `well_log` or an empty/unknown semantic type. `prepare()` maps loader `ValueError` to `GeoVizError(INVALID_DATA, "无法解析 LAS 测井数据")` and `OSError` to `IO_ERROR`. `create_widget()` returns `WellLogCanvas`; `render()` calls `set_tracks(build_qpainter_tracks(payload))`; `release()` calls `set_tracks([])`.

- [ ] **Step 5: Run focused tests and the established LAS/canvas suite**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_well_log_preview.py tests/test_las_parser.py tests/test_qpainter_builder.py tests/test_qpainter_widget.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz packages/geoviz_well_log/geoviz_well_log tests/test_geoviz_well_log_preview.py
git -C geo-viz-engine commit -m "feat: add bounded LAS preview backend"
```

---

### Task 5: Slice-only seismic preview backend and non-OpenGL widget

**Files:**
- Create: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/preview_widget.py`
- Modify: `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/__init__.py`
- Create: `geo-viz-engine/geoviz/previews/seismic.py`
- Modify: `geo-viz-engine/geoviz/previews/__init__.py`
- Modify: `geo-viz-engine/geoviz/engine.py`
- Test: `geo-viz-engine/tests/test_geoviz_seismic_preview.py`

**Interfaces:**
- Consumes: `SeismicLoader.inspect/read_inline/read_crossline/read_timeslice`, `ProfileWidget`, and `PreviewOptions.max_slice_axis`.
- Produces: `SeismicPreviewPayload`, `SeismicPreviewWidget`, and the default `seismic_2d` backend.

- [ ] **Step 1: Write failing slice-only tests using `small_segy_path`**

Patch `SeismicLoader.get_volume_downsampled` to raise if called. Assert preparation still succeeds, returns inline/crossline/time arrays with both axes at or below 512, closes the loader, and reports estimated bytes equal to the sum of array `nbytes`. Construct the widget and assert switching its combo changes the active slice without any `Renderer3D` instance.

- [ ] **Step 2: Run focused tests and verify the preview widget is absent**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_seismic_preview.py -q`

Expected: FAIL importing `SeismicPreviewWidget`.

- [ ] **Step 3: Implement bounded slice preparation**

```python
@dataclass(frozen=True)
class SeismicSlice:
    data: np.ndarray
    info: SliceInfo


@dataclass(frozen=True)
class SeismicPreviewPayload:
    slices: dict[str, SeismicSlice]
    initial_mode: str = "inline"


def downsample_2d(data: np.ndarray, limit: int) -> np.ndarray:
    row_step = max(1, math.ceil(data.shape[0] / limit))
    col_step = max(1, math.ceil(data.shape[1] / limit))
    return np.ascontiguousarray(data[::row_step, ::col_step], dtype=np.float32)
```

Preparation opens `SeismicLoader` in `try/finally`, inspects metadata, reads the middle inline, middle crossline, and middle sample only, downsamples each, constructs three `SliceInfo` objects with correct axis labels, then closes the loader.

- [ ] **Step 4: Implement `SeismicPreviewWidget` without importing `Renderer3D`**

The widget contains a `QComboBox` with stable item data `inline`, `crossline`, `time` and one `ProfileWidget`. `set_slices(payload)` stores the three slices and calls `ProfileWidget.update_profile()` for the selected mode. `clear()` resets stored slices and displays `ProfileWidget.set_overlay_text("暂无地震切片")`.

- [ ] **Step 5: Register the backend and run seismic regressions**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_seismic_preview.py tests/test_seismic_loader.py tests/test_profile_widget.py tests/test_profile_vd.py -q`

Expected: all selected tests pass and no OpenGL test is collected.

- [ ] **Step 6: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz packages/geoviz_seismic/geoviz_seismic tests/test_geoviz_seismic_preview.py
git -C geo-viz-engine commit -m "feat: add slice-only seismic preview"
```

---

### Task 6: Semantic DAT parsing, scatter, time-depth, and horizon previews

**Files:**
- Create: `geo-viz-engine/geoviz/previews/dat.py`
- Modify: `geo-viz-engine/packages/geoviz_plots/geoviz_plots/surface/surface_widget.py`
- Modify: `geo-viz-engine/geoviz/previews/__init__.py`
- Modify: `geo-viz-engine/geoviz/engine.py`
- Test: `geo-viz-engine/tests/test_geoviz_dat_preview.py`

**Interfaces:**
- Consumes: semantic types `well_head`, `horizon`, and `time_depth`; `PlotWidget`, `ScatterSeries`, `LineSeries`, `SurfaceWidget`, and `interpolate_idw`.
- Produces: `XYPreviewPayload`, `TimeDepthPreviewPayload`, `SurfacePreviewPayload`, conservative DAT header recognition, and three default backends.

- [ ] **Step 1: Write failing parser/backend tests with exact sample headers**

Use fixtures beginning with `#WellHead File From SMI`, `# XYZInlineCrossline Format Horizon File From SMI`, and a time-depth header containing `Depth` and `Time(ms)`. Assert well-head output preserves names and XY extent, horizon output creates grids no larger than 256 by 256, time-depth output is ordered by depth, and an arbitrary three-column DAT with semantic type `unknown` is unsupported.

- [ ] **Step 2: Run the focused test and verify the DAT backend is absent**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_dat_preview.py -q`

Expected: FAIL importing DAT preview payloads.

- [ ] **Step 3: Implement conservative parsing and representative sampling**

```python
@dataclass(frozen=True)
class XYPreviewPayload:
    names: tuple[str, ...]
    x: np.ndarray
    y: np.ndarray


@dataclass(frozen=True)
class TimeDepthPreviewPayload:
    depth: np.ndarray
    time_ms: np.ndarray


@dataclass(frozen=True)
class SurfacePreviewPayload:
    grid_x: np.ndarray
    grid_y: np.ndarray
    grid_z: np.ndarray
    levels: tuple[float, ...]


def representative_indices(length: int, limit: int) -> np.ndarray:
    if length <= limit:
        return np.arange(length, dtype=np.int64)
    return np.linspace(0, length - 1, num=limit, dtype=np.int64)


def supports_well_head(request: PreviewRequest, header: tuple[str, ...]) -> bool:
    return request.semantic_type == "well_head" and any("WellHead File From SMI" in line for line in header)


def supports_horizon(request: PreviewRequest, header: tuple[str, ...]) -> bool:
    return request.semantic_type == "horizon" and any("XYZInlineCrossline" in line for line in header)
```

Read comment headers and whitespace-delimited data rows with `utf-8-sig`. Reject schema mismatches with `GeoVizError(INVALID_DATA, "DAT 数据结构与资源类型不匹配")`. Well-head uses columns name/X/Y; horizon uses X/Y/Z; time-depth selects registered depth/time columns rather than guessing arbitrary numeric columns.

- [ ] **Step 4: Implement plot and surface rendering**

`XYScatterBackend` renders one `ScatterSeries` and calls `autofit()`. `TimeDepthBackend` renders one `LineSeries` with time on X and depth on Y, then calls `autofit()`. `HorizonSurfaceBackend` builds bounded `grid_x`, `grid_y`, `grid_z` in `prepare()`, chooses finite contour levels with `np.linspace()`, calls `SurfaceWidget.set_grid_data()`, and then `autofit()`.

Add this explicit reusable reset API to `SurfaceWidget` and test it through the horizon backend:

```python
def clear(self) -> None:
    self.grid_x = None
    self.grid_y = None
    self.grid_z = None
    self.levels = []
    self.control_points = []
    self.fault_polylines = []
    self.selected_contour_level = None
    self.view_xmin, self.view_xmax = 0.0, 1.0
    self.view_ymin, self.view_ymax = 0.0, 1.0
    self.update()
```

Each backend `release()` calls the public `clear()` method on its widget.

- [ ] **Step 5: Run DAT and plot regressions**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_dat_preview.py tests/test_geoviz_plots.py tests/test_plots_interpolation.py tests/test_surface_widget_interaction.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz packages/geoviz_plots/geoviz_plots/surface/surface_widget.py tests/test_geoviz_dat_preview.py
git -C geo-viz-engine commit -m "feat: add semantic DAT preview backends"
```

---

### Task 7: Formation-top comparison preview in the cross-well engine

**Files:**
- Create: `geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/formation_preview.py`
- Modify: `geo-viz-engine/packages/geoviz_cross_well/geoviz_cross_well/__init__.py`
- Modify: `geo-viz-engine/geoviz/previews/dat.py`
- Modify: `geo-viz-engine/geoviz/engine.py`
- Test: `geo-viz-engine/tests/test_geoviz_formation_preview.py`

**Interfaces:**
- Consumes: `FormationTop`, the sample `#WellTops File From SMI` schema, and `PreviewKind.FORMATION_TOPS`.
- Produces: `FormationTopsPreviewWidget.set_tops(tops)`, `clear()`, and a well-stratification backend.

- [ ] **Step 1: Write failing model, rendering-state, and backend tests**

Parse rows `(well_name, formation_name, MD)` from a fixture with two wells and three shared formations. Assert deterministic well order, depth extent, formation color reuse, backend interactions `("zoom", "pan", "hover")`, and `clear()` empties the widget. A row with nonnumeric MD must be ignored; a file with no valid rows must raise `INVALID_DATA`.

- [ ] **Step 2: Run focused tests and verify the widget is absent**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_formation_preview.py -q`

Expected: FAIL importing `FormationTopsPreviewWidget`.

- [ ] **Step 3: Implement the lightweight QPainter canvas**

The canvas stores a tuple of `FormationTop`, derives sorted wells and global depth bounds, paints one vertical well axis per well, paints a colored point and label for each top, and connects equal formation names across adjacent wells with antialiased lines. Mouse wheel scales the visible depth range around the cursor; drag pans depth; hover exposes `hovered_top_changed(str, str, float)`.

```python
def set_tops(self, tops: list[FormationTop] | tuple[FormationTop, ...]) -> None:
    self._tops = tuple(tops)
    self._well_names = tuple(sorted({top.well_name for top in self._tops}))
    depths = [top.depth_m for top in self._tops]
    self._full_depth_range = (min(depths), max(depths)) if depths else (0.0, 1.0)
    self._view_depth_range = self._full_depth_range
    self.update()


def clear(self) -> None:
    self._tops = ()
    self._well_names = ()
    self._full_depth_range = (0.0, 1.0)
    self._view_depth_range = (0.0, 1.0)
    self.update()
```

- [ ] **Step 4: Add `WellStratificationBackend` and register it**

The backend supports only `format=dat`, `semantic_type=well_stratification`, and the exact WellTops header. Preparation maps parsed rows to immutable `FormationTop` values, caps the total at 50,000 representative rows, and estimates payload memory from string bytes plus numeric fields.

- [ ] **Step 5: Run cross-well and focused regressions**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_formation_preview.py tests/test_cross_well_widget.py tests/test_cross_well_fidelity.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit inside the engine repository**

```bash
git -C geo-viz-engine add geoviz packages/geoviz_cross_well/geoviz_cross_well tests/test_geoviz_formation_preview.py
git -C geo-viz-engine commit -m "feat: add formation tops preview canvas"
```

---

### Task 8: Workbench GeoViz provider, preview host, and reader integration

**Files:**
- Create: `paleo_workbench/ui/pages/geoviz_preview_provider.py`
- Create: `paleo_workbench/ui/pages/geoviz_preview_host.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Test: `tests/test_geoviz_preview_provider.py`
- Test: `tests/test_geoviz_preview_host.py`
- Modify: `tests/test_data_reader_panel.py`

**Interfaces:**
- Consumes: `GeoVizEngine.default()`, `PreviewRequest`, `PreviewOptions.local()`, `PreparedPreview`, and existing `PreviewProvider` fallback behavior.
- Produces: `LocalVisualizationProvider`, `GeoVizPreviewHost`, and `PreviewResult(mode="geoviz", engine_preview=prepared, estimated_bytes=prepared.estimated_bytes)`.

- [ ] **Step 1: Write failing provider, fallback, host-reuse, and stale-clear tests**

Use a fake engine that records calls. Assert a LAS `ResourceItem` becomes a facade `PreviewRequest` with no workbench model in it; successful preparation returns `mode="geoviz"`; `GeoVizError(INVALID_DATA)` invokes the ordinary LAS summary fallback and adds a warning; an unsupported request directly uses the existing reader. In host tests, render two `WELL_LOG` payloads and assert one widget is reused, then render `SURFACE` and assert the old widget is released and hidden.

- [ ] **Step 2: Run focused tests and verify the new classes are absent**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py -q`

Expected: FAIL importing the new workbench modules.

- [ ] **Step 3: Extend the structured reader result**

Add `"geoviz"` to `PreviewMode` and these frozen dataclass fields:

```python
engine_preview: object | None = None
estimated_bytes: int = 0
```

Do not place engine widgets or file handles in `PreviewResult`.

- [ ] **Step 4: Implement professional-first provider composition**

```python
def request_from_resource(resource: ResourceItem) -> PreviewRequest:
    return PreviewRequest(
        resource_id=resource.id,
        path=resource.path,
        semantic_type=resource.type,
        format=resource.format,
        label=resource.name,
    )


class LocalVisualizationProvider(PreviewProvider):
    def __init__(self, engine: GeoVizEngine | None = None) -> None:
        super().__init__()
        self.engine = engine or GeoVizEngine.default()

    def _build_preview(self, asset):
        if isinstance(asset, ResourceItem):
            request = request_from_resource(asset)
            if self.engine.supports(request):
                try:
                    prepared = self.engine.prepare(request, PreviewOptions.local())
                    return self._engine_result(asset, prepared)
                except GeoVizError as error:
                    fallback = super()._build_preview(asset)
                    return replace(fallback, warning=self._merge_warning(fallback.warning, str(error)))
        return super()._build_preview(asset)

    @staticmethod
    def _engine_result(asset: ResourceItem, prepared: PreparedPreview) -> PreviewResult:
        return PreviewResult(
            mode="geoviz",
            title=asset.name,
            path=asset.path,
            format=asset.format,
            status=asset.status,
            type_label=asset.type,
            warning=prepared.warning,
            summary_rows=prepared.summary_rows,
            engine_preview=prepared,
            estimated_bytes=prepared.estimated_bytes,
        )

    @staticmethod
    def _merge_warning(existing: str, engine_message: str) -> str:
        return " · ".join(part for part in (existing, engine_message) if part)
```

- [ ] **Step 5: Implement the UI-thread preview host and reader dispatch**

`GeoVizPreviewHost` owns a `QStackedWidget`, one widget per `PreviewKind`, and the shared engine. `render(preview)` lazily creates the kind, releases the previously active kind when switching, and calls `engine.render`. `clear()` releases the active widget. `release_all()` releases and deletes every cached widget.

`DataReaderPanel` defaults to `LocalVisualizationProvider`, adds the host to its stack, and dispatches `mode="geoviz"` only when `engine_preview` is a `PreparedPreview`. Loading, failure, empty, and ordinary fallback states must call `geoviz_host.clear()` before displaying another widget.

- [ ] **Step 6: Wire shutdown and full-visualization action behavior**

`DataPage.closeEvent` and deferred deletion call both `self._preview_controller.shutdown()` and `self.reader_panel.release_engine_widgets()`. Keep the existing **Open in Visualization** / `open_in_visualization` action, `VizRef` navigation, resource identity, and button wiring; only change its imports to `geoviz` facade types where necessary.

- [ ] **Step 7: Run reader and data-page integration tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_visualization_jump.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit the engine gitlink and workbench integration together**

```bash
git add geo-viz-engine paleo_workbench/ui/pages/geoviz_preview_provider.py paleo_workbench/ui/pages/geoviz_preview_host.py paleo_workbench/ui/pages/preview_provider.py paleo_workbench/ui/pages/data_reader_panel.py paleo_workbench/ui/pages/data_page.py tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py tests/test_data_reader_panel.py
git commit -m "feat: add geoviz previews to data reader"
```

This parent commit must point at the engine commit containing Tasks 4-7, so a clean checkout has every backend required by the workbench.

---

### Task 9: Byte-weighted payload cache and async lifecycle hardening

**Files:**
- Modify: `paleo_workbench/ui/pages/preview_cache.py`
- Modify: `paleo_workbench/ui/pages/preview_worker.py`
- Modify: `tests/test_preview_cache.py`
- Modify: `tests/test_preview_async.py`
- Test: `tests/test_geoviz_preview_lifecycle.py`

**Interfaces:**
- Consumes: `PreviewResult.estimated_bytes` and existing revision cache keys/generation tokens.
- Produces: `PreviewCache(max_size=32, max_bytes=134_217_728)`, `current_bytes`, and deterministic oversize behavior.

- [ ] **Step 1: Write failing byte-budget tests**

```python
def test_byte_budget_evicts_oldest_even_below_count_limit():
    cache = PreviewCache(max_size=32, max_bytes=100)
    cache.put(("a",), PreviewResult(mode="geoviz", title="a", estimated_bytes=60))
    cache.put(("b",), PreviewResult(mode="geoviz", title="b", estimated_bytes=60))
    assert cache.get(("a",)) is None
    assert cache.get(("b",)) is not None
    assert cache.current_bytes == 60


def test_single_oversize_payload_is_not_cached():
    cache = PreviewCache(max_bytes=100)
    cache.put(("big",), PreviewResult(mode="geoviz", title="big", estimated_bytes=101))
    assert cache.get(("big",)) is None
    assert cache.current_bytes == 0
```

Add an async test where a slow GeoViz request A is replaced by B; assert only B reaches the reader and only B enters the cache. Add a teardown test that no controller job remains and every fake engine widget receives one release call.

- [ ] **Step 2: Run cache/lifecycle tests and verify byte accounting is absent**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_preview_cache.py tests/test_geoviz_preview_lifecycle.py -q`

Expected: FAIL because `max_bytes` and `current_bytes` do not exist.

- [ ] **Step 3: Implement exact cache weight accounting**

```python
DEFAULT_PREVIEW_CACHE_BYTES = 128 * 1024 * 1024


def preview_result_weight(value: PreviewResult) -> int:
    if value.estimated_bytes > 0:
        return value.estimated_bytes
    return len(value.text.encode("utf-8")) + len(value.image_bytes) + len(value.pdf_bytes)
```

Store `(value, weight)` in the ordered dictionary. Replacing a key subtracts its old weight first. Reject entries whose weight exceeds `max_bytes`. Evict oldest entries while either `len(_data) > max_size` or `current_bytes > max_bytes`. `clear()` resets bytes to zero.

- [ ] **Step 4: Preserve latest-only semantics for GeoViz payloads**

Keep the controller's serial worker and generation checks. Generalize cache writes to accept any `PreviewResult`, including `mode="geoviz"`; only the current generation may call `cache.put`. Do not preload or strip media for engine payloads.

- [ ] **Step 5: Run cache, async, and shutdown regressions**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_preview_cache.py tests/test_preview_async.py tests/test_geoviz_preview_lifecycle.py tests/test_project_lifecycle.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit the cache/lifecycle slice**

```bash
git add paleo_workbench/ui/pages/preview_cache.py paleo_workbench/ui/pages/preview_worker.py tests/test_preview_cache.py tests/test_preview_async.py tests/test_geoviz_preview_lifecycle.py
git commit -m "perf: bound geoviz preview cache by bytes"
```

---

### Task 10: Best-effort SpreadsheetML, PPTX, DFB, ZIP, and proprietary fallbacks

**Files:**
- Create: `paleo_workbench/ui/pages/fallback_preview.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Modify: `paleo_workbench/resources/classifier.py`
- Test: `tests/test_fallback_preview.py`
- Modify: `tests/test_preview_provider.py`
- Modify: `tests/test_resources_classifier.py`

**Interfaces:**
- Consumes: existing `table`, `image`, `text`, and `message` reader modes.
- Produces: bounded SpreadsheetML table extraction, PPTX package thumbnail/slide count, DFB sibling-or-embedded thumbnail discovery, ZIP listing, and explicit WLP fallback.

- [ ] **Step 1: Write failing bounded fallback tests**

Create fixtures for: SpreadsheetML with 250 rows and 45 columns; PPTX ZIP containing `docProps/thumbnail.jpeg` and three `ppt/slides/slide*.xml` entries; DFB bytes containing an embedded PNG signature; DFB with a same-stem PNG sibling; ZIP with 600 entries; and arbitrary WLP bytes. Assert the exact global limits, no archive extraction, image mode for discovered thumbnails, and a message containing `暂不支持 WLP`.

- [ ] **Step 2: Run focused tests and verify helpers are absent**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_fallback_preview.py tests/test_resources_classifier.py -q`

Expected: FAIL importing `fallback_preview` helpers.

- [ ] **Step 3: Implement bounded fallback helpers**

Wrap the SpreadsheetML file in this reader, then pass it to `xml.etree.ElementTree.iterparse()`:

```python
from typing import BinaryIO


class BoundedReader:
    def __init__(self, raw: BinaryIO, limit: int = 256 * 1024) -> None:
        self._raw = raw
        self._remaining = limit

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        wanted = self._remaining if size < 0 else min(size, self._remaining)
        chunk = self._raw.read(wanted)
        self._remaining -= len(chunk)
        return chunk
```

Retain completed rows from the first worksheet and treat the expected `ParseError` at the byte boundary as truncation; stop at 200 by 40 cells. Use `zipfile.ZipFile` to read only PPTX central-directory names and `docProps/thumbnail.jpeg`/`.png`; do not render arbitrary slides. ZIP listing returns the first 500 sorted names and a truncation warning.

For DFB, check a same-stem `.png`, `.jpg`, or `.jpeg` sibling first. If absent, memory-map the file and extract only a validated PNG range or JPEG SOI/EOI range capped at 16 MiB. If validation fails, return metadata instead of image bytes. WLP always returns a clear unsupported message in this phase.

- [ ] **Step 4: Dispatch formats without overriding professional GeoViz matches**

In the ordinary `PreviewProvider`, check SpreadsheetML XML before generic text, PPTX before generic document fallback, DFB before generic reference-map image handling, and ZIP before unknown format. Keep `LocalVisualizationProvider` professional-first so registered LAS/SGY/DAT resources never reach these helpers unless engine preparation fails.

- [ ] **Step 5: Run preview and classifier regressions**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_fallback_preview.py tests/test_preview_provider.py tests/test_preview_widgets.py tests/test_resources_classifier.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit fallback support**

```bash
git add paleo_workbench/ui/pages/fallback_preview.py paleo_workbench/ui/pages/preview_provider.py paleo_workbench/resources/classifier.py tests/test_fallback_preview.py tests/test_preview_provider.py tests/test_resources_classifier.py
git commit -m "feat: expand bounded data fallbacks"
```

---

### Task 11: Real-data smoke tests, public package documentation, and final verification

**Files:**
- Modify: `geo-viz-engine/README.md`
- Create: `geo-viz-engine/tests/test_geoviz_public_api.py`
- Create: `tests/test_geoviz_real_data_smoke.py`
- Modify: `tests/test_geoviz_package_independence.py`
- Modify: `progress.md`

**Interfaces:**
- Consumes: complete facade, default backend registry, data-page integration, and default repository `data/` resolution.
- Produces: documented public API, opt-in slow smoke coverage, final package-boundary enforcement, and verification evidence.

- [ ] **Step 1: Write public API and opt-in real-data smoke tests**

The engine public API test imports only `geoviz`, creates `GeoVizEngine.default()`, and asserts capabilities for LAS, SGY, well-head DAT, well-stratification DAT, horizon DAT, and time-depth DAT. It AST-scans the entire `geoviz` tree for workbench imports.

The root smoke test resolves `data/`, marks every test `@pytest.mark.slow`, and skips only when the representative file is absent. For LAS and DAT, assert a nonempty prepared payload within limits. For SGY, monkeypatch `SeismicLoader.get_volume_downsampled` to fail, prepare the real file, and assert three bounded slices. For DFB and WLP, assert a non-crashing image or message fallback.

- [ ] **Step 2: Run focused public API tests before documentation**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_public_api.py -q`

Expected: tests pass against the implemented facade.

- [ ] **Step 3: Document one-package installation and usage**

Add a `GeoViz public package` section to `geo-viz-engine/README.md` with installation, the named public imports, thread rules, local preview limits, error codes, and a minimal example:

```python
from geoviz import GeoVizEngine, PreviewOptions, PreviewRequest

engine = GeoVizEngine.default()
request = PreviewRequest("well-1", "/data/A1.Las", "well_log", "las", "A1")
if engine.supports(request):
    prepared = engine.prepare(request, PreviewOptions.local())
```

Document that widget creation and rendering must occur on the Qt UI thread.

- [ ] **Step 4: Run engine fast tests**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_contracts.py tests/test_geoviz_engine.py tests/test_geoviz_independence.py tests/test_geoviz_well_log_preview.py tests/test_geoviz_seismic_preview.py tests/test_geoviz_dat_preview.py tests/test_geoviz_formation_preview.py tests/test_geoviz_public_api.py -q`

Expected: all selected engine tests pass.

- [ ] **Step 5: Run workbench fast integration tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_package_independence.py tests/test_geoviz_preview_provider.py tests/test_geoviz_preview_host.py tests/test_geoviz_preview_lifecycle.py tests/test_preview_cache.py tests/test_preview_async.py tests/test_data_reader_panel.py tests/test_data_page.py tests/test_visualization_jump.py tests/test_viz_adapter.py tests/test_fallback_preview.py -q`

Expected: all selected workbench tests pass.

- [ ] **Step 6: Run opt-in real-data smoke tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_geoviz_real_data_smoke.py -m slow -q`

Expected: representative LAS, SGY, DAT, DFB, and WLP cases pass; no test loads a full seismic volume.

- [ ] **Step 7: Run the complete fast suites in both repositories**

Run: `cd geo-viz-engine && QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not slow' -q`

Expected: the complete engine fast suite passes.

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -m 'not slow' -q`

Expected: the complete workbench fast suite passes.

- [ ] **Step 8: Record verification and commit final documentation/gitlink**

Add a concise `GeoViz local data preview` entry to `progress.md` listing the implemented formats and exact test commands/results. Then commit engine documentation/tests inside the nested repository, followed by the parent gitlink and root smoke/docs changes:

```bash
git -C geo-viz-engine add README.md tests/test_geoviz_public_api.py
git -C geo-viz-engine commit -m "docs: publish geoviz preview API"
git add geo-viz-engine tests/test_geoviz_real_data_smoke.py tests/test_geoviz_package_independence.py progress.md
git commit -m "test: verify geoviz local data previews"
```

Before each commit, run `git diff --cached --check` and inspect `git diff --cached --name-only` so unrelated existing worktree changes remain untouched.
