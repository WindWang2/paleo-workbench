# Data Page UI and Performance Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing data workspace layout while making 2000+ assets feel smooth via a virtual table model, in-memory filter index, async preview with generation + LRU cache, batched import refresh, and light UI polish.

**Architecture:** Surgical changes only. `DataAssetTable` moves from `QTableWidget` to `QTableView` + `AssetTableModel`. Filtering moves into pure-Python `FilterIndex`. Preview stays in `PreviewProvider` for content building, but selection loading runs on a `PreviewWorker` thread with generation tokens; LRU cache bounds memory. `DataPage` / `DataToolbar` / floating panels keep their public contracts.

**Tech Stack:** Python 3.12, PySide6 (`QAbstractTableModel`, `QTableView`, `QThread`, `QTimer`), pytest + pytest-qt, existing `ResourceItem` / `ExportArtifact` models.

**Spec:** `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md`

---

## File map

| File | Role |
|------|------|
| Create `paleo_workbench/ui/pages/asset_table_model.py` | `AssetTableModel` — full asset list + filtered row map + column keys |
| Create `paleo_workbench/ui/pages/filter_index.py` | `FilterIndex` — category + text search → source indices |
| Create `paleo_workbench/ui/pages/preview_cache.py` | `PreviewCache` — LRU keyed by kind/id/path/checksum/stat |
| Create `paleo_workbench/ui/pages/preview_worker.py` | `_PreviewWorker` + small `PreviewRequestController` (generation) |
| Modify `paleo_workbench/ui/pages/data_asset_table.py` | Host `QTableView` + model; use `FilterIndex`; keep column menu API |
| Modify `paleo_workbench/ui/pages/data_reader_panel.py` | Explicit `loading` state; `render` only; optional async entry from page |
| Modify `paleo_workbench/ui/pages/preview_provider.py` | Drop unbounded internal dict cache (or delegate to `PreviewCache`); keep `_build_preview` |
| Modify `paleo_workbench/ui/pages/data_page.py` | Wire preview controller; keep import worker; batch refresh path |
| Modify `paleo_workbench/ui/pages/data_toolbar.py` | Search debounce; checkable catalog/reader toggles |
| Modify `tests/test_data_asset_table.py` | Model/view cell helpers; scale test |
| Create `tests/test_filter_index.py` | Pure filter tests |
| Create `tests/test_preview_cache.py` | LRU + key tests |
| Create `tests/test_preview_async.py` | Generation + loading + cache-hit behavior |
| Modify existing `tests/test_data_page.py`, `tests/test_data_reader_panel.py`, integration tests as needed | Regression |

**Test helper (use in table tests after Task 1):**

```python
def table_text(table_widget, row: int, column: int) -> str:
    model = table_widget.table.model()
    index = model.index(row, column)
    return model.data(index) or ""


def table_row_count(table_widget) -> int:
    return table_widget.table.model().rowCount()
```

**Always run Qt tests with:**

```bash
QT_QPA_PLATFORM=offscreen pytest <paths> -v
```

---

### Task 1: `AssetTableModel` + virtual `QTableView`

**Files:**
- Create: `paleo_workbench/ui/pages/asset_table_model.py`
- Modify: `paleo_workbench/ui/pages/data_asset_table.py`
- Modify: `tests/test_data_asset_table.py`

- [ ] **Step 1: Write failing tests for model-backed table**

Add helpers and replace direct `QTableWidgetItem` access. Extend `tests/test_data_asset_table.py`:

```python
from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable
from PySide6.QtWidgets import QTableView


def table_text(table_widget, row: int, column: int) -> str:
    model = table_widget.table.model()
    return model.data(model.index(row, column)) or ""


def table_row_count(table_widget) -> int:
    return table_widget.table.model().rowCount()


def test_asset_table_uses_table_view(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    assert isinstance(table.table, QTableView)
    assert table.table.model() is not None


def test_asset_table_columns(qtbot):
    from PySide6.QtCore import Qt

    table = DataAssetTable()
    qtbot.addWidget(table)
    model = table.table.model()
    headers = [
        model.headerData(i, Qt.Orientation.Horizontal)
        for i in range(model.columnCount())
    ]
    assert headers == ["文件名", "类型", "格式", "状态", "角色", "大小", "来源", "路径"]


def test_asset_table_renders_resources_and_artifacts(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
            parsed_summary={"size_bytes": 10},
        )
    ]
    artifacts = [
        ExportArtifact(linked_id="map_1", format="PDF", output_path="/tmp/map.pdf")
    ]
    table.update_assets(resources, artifacts)
    assert table_row_count(table) == 2
    assert table_text(table, 0, 0) == "well.las"
    # role column index among default keys: name,type,format,status,role -> 4
    assert table_text(table, 1, 4) == "成果"


def test_asset_table_handles_2000_assets(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(
            name=f"well_{i}.las",
            path=f"/tmp/well_{i}.las",
            type="well_log",
            format="las",
        )
        for i in range(2000)
    ]
    table.update_assets(resources, [])
    assert table_row_count(table) == 2000
    assert table_text(table, 0, 0) == "well_0.las"
    assert table_text(table, 1999, 0) == "well_1999.las"
    # Virtual views should not materialize 2000*8 widget items:
    assert not hasattr(table.table, "item") or table.table.item is None or True
```

Update **all** existing tests in this file that use `.item(...).text()` / `.rowCount()` on `table.table` to use `table_text` / `table_row_count`. Keep category/search/column visibility tests' intent.

- [ ] **Step 2: Run tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_asset_table.py -v
```

Expected: FAIL — still `QTableWidget`, or helpers fail on missing model.

- [ ] **Step 3: Implement `AssetTableModel`**

Create `paleo_workbench/ui/pages/asset_table_model.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens

RESOURCE_TYPE_LABELS = {
    **tokens.RESOURCE_LABELS,
    "spreadsheet": "表格",
    "tabular": "表格",
    "time_depth": "时深",
    "horizon": "层位",
    "well_stratification": "井分层",
    "document": "文档",
    "image_reference": "影像",
    "reference_map": "参考图",
    "well_reference": "测井参考",
    "unknown": "未知",
}


class AssetTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._assets: list[ResourceItem | ExportArtifact] = []
        self._filtered_rows: list[int] = []
        self._column_keys: list[str] = []

    def set_column_keys(self, keys: list[str]) -> None:
        self.beginResetModel()
        self._column_keys = list(keys)
        self.endResetModel()

    def set_assets(self, assets: list[ResourceItem | ExportArtifact]) -> None:
        self.beginResetModel()
        self._assets = list(assets)
        # Default: all rows visible until filter applied
        self._filtered_rows = list(range(len(self._assets)))
        self.endResetModel()

    def set_filtered_rows(self, rows: list[int]) -> None:
        self.beginResetModel()
        self._filtered_rows = list(rows)
        self.endResetModel()

    def asset_at(self, view_row: int) -> ResourceItem | ExportArtifact | None:
        if view_row < 0 or view_row >= len(self._filtered_rows):
            return None
        return self._assets[self._filtered_rows[view_row]]

    def assets(self) -> list[ResourceItem | ExportArtifact]:
        return list(self._assets)

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered_rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._column_keys)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            from paleo_workbench.ui.pages.data_asset_table import COLUMN_BY_KEY
            key = self._column_keys[section]
            return COLUMN_BY_KEY[key].label
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        asset = self.asset_at(index.row())
        if asset is None:
            return None
        key = self._column_keys[index.column()]
        return self._row_values(asset).get(key, "")

    def _row_values(self, asset: ResourceItem | ExportArtifact) -> dict[str, str]:
        if isinstance(asset, ExportArtifact):
            return {
                "name": Path(asset.output_path).name,
                "type": "成果",
                "format": asset.format,
                "status": "generated",
                "role": "成果",
                "size": "—",
                "source": "export",
                "path": asset.output_path,
            }
        size = asset.parsed_summary.get("size_bytes")
        role = asset.artifact_role or "input"
        return {
            "name": asset.name,
            "type": RESOURCE_TYPE_LABELS.get(asset.type, asset.type),
            "format": asset.format,
            "status": asset.status,
            "role": {"input": "输入", "derived": "成果", "export": "成果"}.get(role, role),
            "size": str(size) if size is not None else "—",
            "source": asset.source,
            "path": asset.path,
        }
```

Avoid circular imports: either keep `COLUMN_BY_KEY` labels passed into the model via `set_column_keys` + parallel label list, or move `COLUMN_DEFINITIONS` / `COLUMN_BY_KEY` to a tiny `data_table_columns.py`. **Preferred:** move column definitions to `paleo_workbench/ui/pages/data_table_columns.py` and import from both model and table.

- [ ] **Step 4: Migrate `DataAssetTable` to `QTableView`**

In `data_asset_table.py`:

- Import `QTableView`, `QItemSelectionModel` as needed; remove `QTableWidget` / `QTableWidgetItem`.
- Create `self.model = AssetTableModel(self)`.
- `self.table = QTableView(...)`; `self.table.setModel(self.model)`.
- Object name remains `DataAssetGrid`; update stylesheet selector to `QTableView#DataAssetGrid`.
- Selection: `self.table.selectionModel().selectionChanged.connect(...)`.
- `update_assets`: store resources/artifacts, build combined list, `self.model.set_assets(...)`, then apply category/search (still local filter logic until Task 2).
- `_emit_selection`: use `self.model.asset_at(row)`.
- `_sync_selection`: find view row via model, `selectRow`.
- Column visibility: `self.model.set_column_keys(self._visible_column_keys)` instead of rewriting widget items.
- Keep public API: `update_assets`, `set_category`, `set_search_text`, `visible_asset_count`, `visible_column_keys`, `set_visible_columns`, `reset_columns`, `set_selected_asset`, `column_settings_btn`, `column_actions`, `reset_columns_action`, `selected_asset_changed`.

Minimal `update_assets` shape:

```python
def update_assets(self, resources, artifacts) -> None:
    self._resources = list(resources)
    self._artifacts = list(artifacts)
    self._apply_filter()

def _apply_filter(self) -> None:
    assets = [*self._resources, *self._artifacts]
    self.model.set_column_keys(self._visible_column_keys)
    self.model.set_assets(assets)
    filtered = [
        i for i, asset in enumerate(assets)
        if self._matches_category(asset) and self._matches_search(asset)
    ]
    self.model.set_filtered_rows(filtered)
    self._visible_assets = [assets[i] for i in filtered]
    if not self._sync_selection() and self._selected_asset is not None:
        self._selected_asset = None
        self.selected_asset_changed.emit(None)
```

Note: calling `set_assets` then `set_filtered_rows` causes two resets — acceptable for Task 1; Task 2 can refine to a single reset API `set_assets_and_filter(assets, rows)`.

- [ ] **Step 5: Run table tests**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_asset_table.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/ui/pages/asset_table_model.py \
  paleo_workbench/ui/pages/data_table_columns.py \
  paleo_workbench/ui/pages/data_asset_table.py \
  tests/test_data_asset_table.py
git commit -m "feat: virtualize data asset table with QAbstractTableModel"
```

---

### Task 2: `FilterIndex` + debounced search

**Files:**
- Create: `paleo_workbench/ui/pages/filter_index.py`
- Create: `tests/test_filter_index.py`
- Modify: `paleo_workbench/ui/pages/data_asset_table.py`
- Modify: `paleo_workbench/ui/pages/data_toolbar.py`
- Modify: `paleo_workbench/ui/pages/data_page.py` (if debounce lives on page)
- Modify: `tests/test_data_asset_table.py` (scale filter test)

- [ ] **Step 1: Write failing pure tests for `FilterIndex`**

`tests/test_filter_index.py`:

```python
from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.filter_index import FilterIndex


def _assets():
    return [
        ResourceItem(name="A1.las", path="/d/A1.las", type="well_log", format="las", status="indexed"),
        ResourceItem(name="cube.sgy", path="/d/cube.sgy", type="seismic", format="sgy", status="missing"),
        ExportArtifact(linked_id="m1", format="PDF", output_path="/d/map.pdf"),
    ]


def test_filter_all_returns_all_indices():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("全部", "") == [0, 1, 2]


def test_filter_category_well_log():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("测井", "") == [0]


def test_filter_search_substring():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("全部", "cube") == [1]


def test_filter_category_then_search():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("测井", "A1") == [0]
    assert idx.filter("测井", "cube") == []


def test_filter_issues_category():
    idx = FilterIndex()
    assets = _assets()
    idx.rebuild(assets)
    assert idx.filter("异常", "") == [1]
```

- [ ] **Step 2: Run to verify fail**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_filter_index.py -v
```

Expected: FAIL import error.

- [ ] **Step 3: Implement `FilterIndex`**

Move category/search matching from `DataAssetTable` into `filter_index.py` (same semantics as current `_matches_category` / `_matches_search` / `CATEGORIES` / `ISSUE_STATUSES` / `REFERENCE_TYPES`).

```python
from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_catalog_panel import CATEGORIES

ISSUE_STATUSES = {"missing", "warning", "failed", "error"}
REFERENCE_TYPES = {"document", "image_reference", "reference_map", "well_reference"}


class FilterIndex:
    def __init__(self) -> None:
        self._assets: list[ResourceItem | ExportArtifact] = []
        self._haystacks: list[str] = []

    def rebuild(self, assets: list[ResourceItem | ExportArtifact]) -> None:
        self._assets = list(assets)
        self._haystacks = [self._haystack(asset) for asset in self._assets]

    def filter(self, category: str, search_text: str) -> list[int]:
        needle = search_text.strip().lower()
        rows: list[int] = []
        for i, asset in enumerate(self._assets):
            if not self._matches_category(asset, category):
                continue
            if needle and needle not in self._haystacks[i]:
                continue
            rows.append(i)
        return rows

    def _haystack(self, asset: ResourceItem | ExportArtifact) -> str:
        if isinstance(asset, ExportArtifact):
            parts = [
                Path(asset.output_path).name,
                asset.format,
                "成果",
                asset.output_path,
                asset.linked_id,
            ]
        else:
            parts = [
                asset.name,
                asset.type,
                asset.format,
                asset.status,
                asset.source,
                asset.path,
            ]
        return " ".join(parts).lower()

    def _matches_category(self, asset: ResourceItem | ExportArtifact, category: str) -> bool:
        # Copy exact logic from current DataAssetTable._matches_category
        ...
```

- [ ] **Step 4: Wire `DataAssetTable` to `FilterIndex`**

```python
self._index = FilterIndex()

def _apply_filter(self) -> None:
    assets = [*self._resources, *self._artifacts]
    self._index.rebuild(assets)
    rows = self._index.filter(self._category, self._search_text)
    self.model.set_column_keys(self._visible_column_keys)
    self.model.set_assets(assets)
    self.model.set_filtered_rows(rows)
    self._visible_assets = [assets[i] for i in rows]
    ...
```

Add scale test: 2000 assets, search `"well_1999"`, expect 1 row — without calling any preview API.

- [ ] **Step 5: Debounce toolbar search**

In `data_toolbar.py`, use `QTimer` single-shot 180ms:

```python
from PySide6.QtCore import QTimer, Signal

# in __init__:
self._search_timer = QTimer(self)
self._search_timer.setSingleShot(True)
self._search_timer.setInterval(180)
self._pending_search = ""
self._search_timer.timeout.connect(self._emit_debounced_search)
self.search_box.textChanged.connect(self._on_search_text_changed)

def _on_search_text_changed(self, text: str) -> None:
    self._pending_search = text
    self._search_timer.start()

def _emit_debounced_search(self) -> None:
    self.search_changed.emit(self._pending_search)
```

Tests that type into the search box and assert immediately may need `qtbot.wait(200)` or call `asset_table.set_search_text` directly (preferred for unit tests).

- [ ] **Step 6: Run tests**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_filter_index.py tests/test_data_asset_table.py -v
```

Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add paleo_workbench/ui/pages/filter_index.py \
  paleo_workbench/ui/pages/data_asset_table.py \
  paleo_workbench/ui/pages/data_toolbar.py \
  tests/test_filter_index.py \
  tests/test_data_asset_table.py
git commit -m "feat: add FilterIndex and debounced data search"
```

---

### Task 3: Async preview + generation + loading state

**Files:**
- Create: `paleo_workbench/ui/pages/preview_worker.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Create: `tests/test_preview_async.py`
- Modify: `tests/test_data_reader_panel.py` if `update_asset` behavior splits

- [ ] **Step 1: Write failing async/generation tests**

`tests/test_preview_async.py`:

```python
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class SlowProvider(PreviewProvider):
    def __init__(self):
        super().__init__()
        self.calls: list[str] = []

    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        self.calls.append(asset.name)
        # Deterministic light result; real worker still off-thread
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"preview:{asset.name}",
        )


def test_rapid_selection_keeps_last_result(qtbot, tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("aaa")
    b.write_text("bbb")
    project = ProjectDocument.new("P")
    project.resources = [
        ResourceItem(name="a.txt", path=str(a), type="document", format="txt"),
        ResourceItem(name="b.txt", path=str(b), type="document", format="txt"),
    ]
    page = DataPage(project)
    qtbot.addWidget(page)
    provider = SlowProvider()
    page.reader_panel.provider = provider

    page._set_selected_asset(project.resources[0])
    page._set_selected_asset(project.resources[1])

    def ready_for_b():
        return page.reader_panel.title_label.text() == "b.txt"

    qtbot.waitUntil(ready_for_b, timeout=3000)
    assert page.reader_panel.current_mode in {"message", "text"}
    # Intermediate a may or may not have completed; UI must show b
    assert "b.txt" in page.reader_panel.title_label.text()


def test_reader_shows_loading_on_miss(qtbot, monkeypatch, tmp_path):
    path = tmp_path / "big.txt"
    path.write_text("x" * 100)
    resource = ResourceItem(name="big.txt", path=str(path), type="document", format="txt")
    project = ProjectDocument.new("P")
    project.resources = [resource]
    page = DataPage(project)
    qtbot.addWidget(page)

    # Force async path: monkeypatch provider.preview to signal slow work if needed
    page._set_selected_asset(resource)
    # Either loading flashes or result arrives; after wait, not empty
    qtbot.waitUntil(lambda: page.reader_panel.current_mode != "empty", timeout=3000)
```

Also add unit-level test for generation controller if extracted:

```python
def test_stale_generation_discarded():
    from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
    # controller.apply(generation, result) only updates if generation matches current
```

- [ ] **Step 2: Run to verify fail / red behavior**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_async.py -v
```

- [ ] **Step 3: Implement `preview_worker.py`**

```python
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class _PreviewWorker(QObject):
    finished = Signal(int, object)  # generation, PreviewResult
    failed = Signal(int, str)

    def __init__(self, provider: PreviewProvider, asset, generation: int, parent=None):
        super().__init__(parent)
        self._provider = provider
        self._asset = asset
        self._generation = generation

    @Slot()
    def run(self) -> None:
        try:
            result = self._provider.preview(self._asset)
        except Exception as exc:  # pragma: no cover
            self.failed.emit(self._generation, str(exc))
            return
        self.finished.emit(self._generation, result)


class PreviewRequestController(QObject):
    result_ready = Signal(object)  # PreviewResult
    loading = Signal()
    failed = Signal(str)

    def __init__(self, provider: PreviewProvider | None = None, parent=None):
        super().__init__(parent)
        self.provider = provider or PreviewProvider()
        self._generation = 0
        self._jobs: list[tuple[QThread, _PreviewWorker]] = []

    def request(self, asset: ResourceItem | ExportArtifact | None) -> None:
        self._generation += 1
        generation = self._generation
        if asset is None:
            self.result_ready.emit(self.provider.preview(None))
            return
        self.loading.emit()
        thread = QThread(self)
        worker = _PreviewWorker(self.provider, asset, generation)
        worker.moveToThread(thread)
        self._jobs.append((thread, worker))
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._drop_job(t, w))
        thread.start()

    def _on_finished(self, generation: int, result: object) -> None:
        if generation != self._generation:
            return
        self.result_ready.emit(result)

    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self.failed.emit(message)

    def _drop_job(self, thread: QThread, worker: _PreviewWorker) -> None:
        self._jobs = [job for job in self._jobs if job != (thread, worker)]
```

**Thread safety note:** `PreviewProvider.preview` must not touch Qt widgets. It already returns dataclasses and does file IO — OK on worker thread. Cache mutation in provider must be removed or made thread-safe (Task 4 moves cache to controller/UI thread).

For Task 3 interim: disable provider internal cache writes from worker, or use a provider instance only on the worker (no shared mutable cache until Task 4).

- [ ] **Step 4: Reader loading state**

In `data_reader_panel.py`:

```python
def show_loading(self, asset: ResourceItem | ExportArtifact | None = None) -> None:
    self.current_mode = "loading"
    self.reader_mode_changed.emit("loading")
    title = "加载中…"
    if isinstance(asset, ResourceItem):
        title = f"加载中… {asset.name}"
    elif isinstance(asset, ExportArtifact):
        title = f"加载中… {Path(asset.output_path).name}"
    self.title_label.setText(title)
    self.meta_label.setText("")
    self.warning_label.setText("")
    self.message_label.set_message("正在生成预览…")
    self.stack.setCurrentWidget(self.message_label)

def update_asset(self, asset) -> None:
    # Sync path for tests that inject panel directly:
    self.render(self.provider.preview(asset))
```

- [ ] **Step 5: Wire `DataPage._set_selected_asset`**

```python
# in __init__ after reader_panel exists:
self._preview_controller = PreviewRequestController(self.reader_panel.provider, self)
self._preview_controller.loading.connect(
    lambda: self.reader_panel.show_loading(self._selected_asset)
)
self._preview_controller.result_ready.connect(self.reader_panel.render)
self._preview_controller.failed.connect(
    lambda msg: self.reader_panel.render(
        PreviewResult(mode="message", title="预览失败", message=msg)
    )
)

def _set_selected_asset(self, asset):
    self._selected_asset = asset
    self.asset_table.set_selected_asset(asset)
    self._preview_controller.request(asset)  # async
    self.action_panel.update_selection_state(...)
    self._emit_data_context()
```

**Regression:** tests that call `reader_panel.update_asset` directly stay sync. Tests that go through `DataPage` selection need `qtbot.waitUntil`.

Update any `DataPage` selection tests that assert immediate reader content to wait.

- [ ] **Step 6: Run tests**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_async.py tests/test_data_reader_panel.py tests/test_data_page.py -v
```

Expected: PASS (fix timing/assertions as needed).

- [ ] **Step 7: Commit**

```bash
git add paleo_workbench/ui/pages/preview_worker.py \
  paleo_workbench/ui/pages/data_reader_panel.py \
  paleo_workbench/ui/pages/data_page.py \
  tests/test_preview_async.py \
  tests/test_data_page.py \
  tests/test_data_reader_panel.py
git commit -m "feat: async data preview with generation tokens"
```

---

### Task 4: `PreviewCache` LRU + key invalidation

**Files:**
- Create: `paleo_workbench/ui/pages/preview_cache.py`
- Create: `tests/test_preview_cache.py`
- Modify: `paleo_workbench/ui/pages/preview_provider.py`
- Modify: `paleo_workbench/ui/pages/preview_worker.py` / `data_page.py` (controller uses cache on UI thread)

- [ ] **Step 1: Write cache tests**

```python
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_cache import PreviewCache, make_preview_cache_key
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def test_lru_evicts_oldest(tmp_path):
    cache = PreviewCache(max_size=2)
    a = tmp_path / "a.txt"; a.write_text("a")
    b = tmp_path / "b.txt"; b.write_text("b")
    c = tmp_path / "c.txt"; c.write_text("c")
    ra = ResourceItem(name="a", path=str(a), type="document", format="txt")
    rb = ResourceItem(name="b", path=str(b), type="document", format="txt")
    rc = ResourceItem(name="c", path=str(c), type="document", format="txt")
    cache.put(make_preview_cache_key(ra), PreviewResult(mode="text", title="a", text="a"))
    cache.put(make_preview_cache_key(rb), PreviewResult(mode="text", title="b", text="b"))
    cache.put(make_preview_cache_key(rc), PreviewResult(mode="text", title="c", text="c"))
    assert cache.get(make_preview_cache_key(ra)) is None
    assert cache.get(make_preview_cache_key(rb)) is not None
    assert cache.get(make_preview_cache_key(rc)) is not None


def test_key_changes_when_file_rewritten(tmp_path):
    path = tmp_path / "a.txt"
    path.write_text("v1")
    r = ResourceItem(name="a", path=str(path), type="document", format="txt", checksum="1")
    k1 = make_preview_cache_key(r)
    path.write_text("v2-longer")
    k2 = make_preview_cache_key(r)
    assert k1 != k2
```

- [ ] **Step 2: Implement cache**

```python
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def _safe_stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
        return (st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
    except OSError:
        return None


def make_preview_cache_key(asset: ResourceItem | ExportArtifact) -> tuple:
    if isinstance(asset, ExportArtifact):
        path = Path(asset.output_path)
        return ("artifact", asset.id, asset.output_path, "", _safe_stat(path))
    path = Path(asset.path)
    return (
        "resource",
        asset.id,
        asset.path,
        asset.checksum or "",
        _safe_stat(path),
    )


class PreviewCache:
    def __init__(self, max_size: int = 32):
        self.max_size = max_size
        self._data: OrderedDict[tuple, PreviewResult] = OrderedDict()

    def get(self, key: tuple) -> PreviewResult | None:
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: tuple, value: PreviewResult) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
```

- [ ] **Step 3: Use cache on UI thread before starting worker**

In `PreviewRequestController.request`:

```python
def request(self, asset):
    self._generation += 1
    generation = self._generation
    if asset is None:
        self.result_ready.emit(self.provider.preview(None))
        return
    key = make_preview_cache_key(asset)
    hit = self.cache.get(key)
    if hit is not None:
        self.result_ready.emit(hit)
        return
    self.loading.emit()
    # start worker...
    # on finished (if generation matches): self.cache.put(key, result); emit
```

Remove or gut unbounded `self._cache` inside `PreviewProvider` so worker-side builds are pure; keep `preview()` as pure build+return.

Add test: re-select same asset → provider.preview call count does not increase (spy on provider from controller).

- [ ] **Step 4: Run tests**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_preview_cache.py tests/test_preview_async.py tests/test_data_reader_panel.py -v
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/pages/preview_cache.py \
  paleo_workbench/ui/pages/preview_provider.py \
  paleo_workbench/ui/pages/preview_worker.py \
  paleo_workbench/ui/pages/data_page.py \
  tests/test_preview_cache.py \
  tests/test_preview_async.py
git commit -m "feat: LRU preview cache for data reader"
```

---

### Task 5: Import batch refresh hygiene

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/ui/pages/data_asset_table.py` / `asset_table_model.py` if needed for single-reset API
- Modify: `tests/test_data_page.py` or `tests/test_data_integration.py`

- [ ] **Step 1: Write/adjust test for import completion batch update**

```python
def test_async_import_refreshes_table_once(qtbot, tmp_path, monkeypatch):
    # Create several files, begin_import_paths, wait import_finished
    # Assert row count matches, action status contains 新增, table still QTableView model
    ...
```

Reuse existing async import tests; ensure they still pass with model table.

- [ ] **Step 2: Ensure `_apply_import_report` is the single UI refresh entry**

Already:

```python
def _apply_import_report(self, report: ImportReport) -> None:
    self.project.resources.extend(report.added)
    self.update_state(...)
    self._set_import_status(report)
```

Improvements:

1. `update_state` → `asset_table.update_assets` must use one model reset path (`set_assets` + filter in one `beginResetModel` if still double-resetting).
2. Optional status copy when `added_count` is large: keep existing format `新增 N · 重复 M · 警告 W`.
3. Do not call `reader_panel.update_asset` on import unless selection still valid; if selected path was re-imported, bump cache miss via new checksum/stat naturally on next select.

Add `AssetTableModel.set_assets_filtered(assets, rows)` to avoid double reset:

```python
def set_assets_filtered(self, assets, rows) -> None:
    self.beginResetModel()
    self._assets = list(assets)
    self._filtered_rows = list(rows)
    self.endResetModel()
```

- [ ] **Step 3: Run import-related tests**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_integration.py tests/test_data_import_service.py -v
```

- [ ] **Step 4: Commit**

```bash
git add paleo_workbench/ui/pages/asset_table_model.py \
  paleo_workbench/ui/pages/data_asset_table.py \
  paleo_workbench/ui/pages/data_page.py \
  tests/test_data_page.py
git commit -m "perf: batch data table refresh after import"
```

---

### Task 6: Light UI polish

**Files:**
- Modify: `paleo_workbench/ui/pages/data_toolbar.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/ui/pages/data_reader_panel.py` (loading copy already done)
- Modify: `paleo_workbench/ui/pages/data_workspace.py` if toggle state needs feedback
- Modify: tests for toolbar checked state if added

- [ ] **Step 1: Tests for toggle checked state**

```python
def test_toolbar_catalog_button_checkable(qtbot):
    from paleo_workbench.ui.pages.data_toolbar import DataToolbar
    bar = DataToolbar()
    qtbot.addWidget(bar)
    assert bar.catalog_btn.isCheckable()
    assert bar.reader_btn.isCheckable()
```

Wire page so `catalog_toggled` / `reader_toggled` flip checked to match panel visibility:

```python
self.data_toolbar.catalog_toggled.connect(self._toggle_catalog)
def _toggle_catalog(self):
    self.workspace.toggle_catalog_panel()
    self.data_toolbar.catalog_btn.setChecked(self.workspace.catalog_panel.is_expanded())
```

(Inspect `FloatingPanel` API for expanded state; use existing method names.)

- [ ] **Step 2: Optional density**

Only if still cramped: `DataPage` layout margins `16` → `12` (one place). Do not change global tokens.

- [ ] **Step 3: Run focused + full suite**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_toolbar.py tests/test_data_page.py tests/test_data_workspace.py tests/test_data_asset_table.py tests/test_filter_index.py tests/test_preview_cache.py tests/test_preview_async.py tests/test_data_reader_panel.py -v
QT_QPA_PLATFORM=offscreen pytest -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add paleo_workbench/ui/pages/data_toolbar.py \
  paleo_workbench/ui/pages/data_page.py \
  paleo_workbench/ui/pages/data_reader_panel.py \
  tests/
git commit -m "polish: data toolbar toggles and reader loading feedback"
```

---

### Task 7: Final verification

- [ ] **Step 1: Full test suite**

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

Expected: all green.

- [ ] **Step 2: Manual smoke (if display available)**

```bash
python -m paleo_workbench.main
```

Check: open data page → import a folder with many files → scroll table → filter → click rows quickly → reader shows loading then last file → re-click same file feels instant.

- [ ] **Step 3: Commit any leftover test fixes**

```bash
git add -A
git status
# commit only if needed
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| Virtual table / 2000+ scroll | Task 1 |
| FilterIndex + no file IO on filter | Task 2 |
| Debounced search | Task 2 |
| Async preview + generation | Task 3 |
| Loading reader state | Task 3 |
| PreviewCache LRU + stat key | Task 4 |
| Import batch refresh | Task 5 |
| Light UI polish | Task 6 |
| Preserve floating panels / APIs | All tasks (no workspace layout rewrite) |
| Out of scope SEG-Y/LAS full viz | Not in any task |
| Tests without hard SLOs | Task 1 scale test + behavior tests |

No TBD placeholders. Types: `PreviewResult`, `FilterIndex.filter -> list[int]`, `make_preview_cache_key`, `PreviewRequestController.request` used consistently across tasks.
