# Data Management Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade DataPage into a project-wide data, result, and file management center with import, catalog filters, dedupe, details, and lightweight previews.

**Architecture:** Keep filesystem/import logic out of widgets. Add a pure `DataImportService` and preview helper layer, then rebuild DataPage from focused panels: `DataCatalogPanel`, `DataAssetTable`, `DataDetailPanel`, and the existing `ActionPanel`. `DataPage` owns the current project slices, delegates import/dedupe to services, and refreshes child widgets.

**Tech Stack:** Python 3.12, PySide6 6.6+, Pydantic v2, pytest, pytest-qt, existing `geo-viz-engine` widgets where safe.

## Global Constraints

- Existing model first: use `ProjectDocument.resources`, `ProjectDocument.export_artifacts`, `ResourceItem.artifact_role`, and `ResourceItem.parsed_summary`; do not introduce `ProjectFileItem`.
- Do not copy or delete source files in the first implementation.
- Do not deep-load LAS, SEGY, PDF, PPT, or Excel by default.
- Preview must be lazy, non-crashing, and safe for unsupported or missing files.
- Import dedupe must be deterministic by normalized path first, checksum second.
- UI must stay dense and operational, consistent with existing AppShell tokens.
- TDD required: write failing tests, verify red, implement minimal green, then run focused and full tests.
- Use `QT_QPA_PLATFORM=offscreen pytest ...` for PySide tests in this environment.

---

## File Structure

Create or modify:

```text
paleo_workbench/resources/classifier.py          # extend direct classifier coverage only if tests expose gaps
paleo_workbench/resources/scanner.py             # keep existing scan behavior; add tests
paleo_workbench/resources/import_service.py      # pure import/dedupe service
paleo_workbench/ui/pages/data_catalog_panel.py   # left category/count panel
paleo_workbench/ui/pages/data_asset_table.py     # extended table with filters/selection
paleo_workbench/ui/pages/data_detail_panel.py    # metadata + preview host
paleo_workbench/ui/pages/preview_strategy.py     # preview mode/data helpers
paleo_workbench/ui/pages/data_page.py            # orchestrates panels and import hooks
paleo_workbench/ui/pages/action_panel.py         # add file/folder/rescan/remove action buttons
paleo_workbench/ui/app_shell.py                  # pass export artifacts to data page
paleo_workbench/app.py                           # pass project + exports to data page
paleo_workbench/ui/pages/__init__.py             # export new panels if needed
tests/test_resources_classifier.py               # new classifier tests
tests/test_resources_scanner.py                  # new scanner tests
tests/test_data_import_service.py                # new import/dedupe tests
tests/test_preview_strategy.py                   # new preview-mode tests
tests/test_data_catalog_panel.py                 # new widget tests
tests/test_data_asset_table.py                   # new widget tests
tests/test_data_detail_panel.py                  # new widget tests
tests/test_data_page.py                          # update assembly/import-refresh tests
tests/test_data_integration.py                   # update shell integration tests
```

---

## Shared Interfaces

Use these names and signatures across tasks:

```python
# paleo_workbench/resources/import_service.py
from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.project.models import ResourceItem

@dataclass
class ImportReport:
    added: list[ResourceItem] = field(default_factory=list)
    skipped_path: list[Path] = field(default_factory=list)
    skipped_checksum: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def added_count(self) -> int: ...

    @property
    def skipped_count(self) -> int: ...

def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport: ...

def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport: ...
```

```python
# paleo_workbench/ui/pages/preview_strategy.py
from dataclasses import dataclass
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem

@dataclass(frozen=True)
class PreviewState:
    mode: str
    title: str
    lines: list[str]
    image_path: str | None = None
    warning: str = ""

def preview_for_resource(resource: ResourceItem, base_path: Path | None = None) -> PreviewState: ...
def preview_for_artifact(artifact: ExportArtifact, base_path: Path | None = None) -> PreviewState: ...
```

```python
# UI panel APIs
DataCatalogPanel.update_counts(resources: list[ResourceItem], artifacts: list[ExportArtifact]) -> None
DataCatalogPanel.category_changed: Signal(str)

DataAssetTable.update_assets(resources: list[ResourceItem], artifacts: list[ExportArtifact]) -> None
DataAssetTable.set_category(category: str) -> None
DataAssetTable.set_search_text(text: str) -> None
DataAssetTable.selected_asset_changed: Signal(object)

DataDetailPanel.update_asset(asset: object | None) -> None
```

---

### Task 1: Resource Classifier And Scanner Coverage

**Files:**
- Test: `tests/test_resources_classifier.py`
- Test: `tests/test_resources_scanner.py`
- Modify only if needed: `paleo_workbench/resources/classifier.py`
- Modify only if needed: `paleo_workbench/resources/scanner.py`

**Interfaces:**
- Consumes: `classify_path(path: Path) -> tuple[str, str, str]`, `scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]`.
- Produces: tested confidence in existing classifier/scanner behavior.

- [ ] **Step 1: Write failing or characterization classifier tests**

Create `tests/test_resources_classifier.py`:

```python
from pathlib import Path

from paleo_workbench.resources.classifier import classify_path


def test_classifies_core_data_formats():
    assert classify_path(Path("well_a.las")) == ("well_log", "las", "indexed")
    assert classify_path(Path("line_01.sgy")) == ("seismic", "sgy", "indexed")
    assert classify_path(Path("horizon.segy")) == ("seismic", "segy", "indexed")


def test_classifies_dat_variants_from_folder_names():
    assert classify_path(Path("td/table.dat")) == ("time_depth", "dat", "indexed")
    assert classify_path(Path("层位/top.dat")) == ("horizon", "dat", "indexed")
    assert classify_path(Path("井分层/well.dat")) == ("well_stratification", "dat", "indexed")


def test_classifies_reference_and_unknown_formats():
    assert classify_path(Path("report.pdf")) == ("document", "pdf", "indexed_reference")
    assert classify_path(Path("image.tif")) == ("image_reference", "tif", "indexed_reference")
    assert classify_path(Path("相图_reference.dfb")) == ("reference_map", "dfb", "indexed_reference")
    assert classify_path(Path("notes.xyz")) == ("unknown", "xyz", "indexed_reference")
```

- [ ] **Step 2: Write scanner tests**

Create `tests/test_resources_scanner.py`:

```python
from pathlib import Path

from paleo_workbench.resources.scanner import scan_resources


def test_scan_resources_recurses_and_records_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    well = data_dir / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    seismic = data_dir / "cube.sgy"
    seismic.write_bytes(b"segy")

    resources = scan_resources(data_dir)

    names = {resource.name for resource in resources}
    assert names == {"well.las", "cube.sgy"}
    well_resource = next(resource for resource in resources if resource.name == "well.las")
    assert well_resource.type == "well_log"
    assert well_resource.parsed_summary["size_bytes"] == len("~Version\n")
    assert well_resource.checksum is not None


def test_scan_resources_relativizes_project_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    well = data_dir / "well.las"
    well.write_text("~Version\n", encoding="utf-8")

    resources = scan_resources(data_dir, project_path=project_path)

    assert resources[0].path == "data/well.las"
    assert resources[0].external is False
```

- [ ] **Step 3: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_resources_classifier.py tests/test_resources_scanner.py -q`

Expected:
- PASS if existing implementation is sufficient.
- If a test fails due to a genuine classifier/scanner gap, fix only that gap and rerun.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/test_resources_classifier.py tests/test_resources_scanner.py paleo_workbench/resources/classifier.py paleo_workbench/resources/scanner.py
git commit -m "test: cover resource classification and scanning"
```

---

### Task 2: DataImportService

**Files:**
- Create: `paleo_workbench/resources/import_service.py`
- Test: `tests/test_data_import_service.py`

**Interfaces:**
- Consumes: `scan_resources()`, `classify_path()`, `ResourceItem`.
- Produces: `ImportReport`, `import_files()`, `import_folder()`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_import_service.py`:

```python
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.import_service import import_files, import_folder


def test_import_files_adds_new_resources(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")

    report = import_files([well], existing=[])

    assert report.added_count == 1
    assert report.skipped_count == 0
    assert report.added[0].name == "well.las"
    assert report.added[0].type == "well_log"


def test_import_files_skips_duplicate_path(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    existing = [
        ResourceItem(
            name="well.las",
            path=well.resolve().as_posix(),
            type="well_log",
            format="las",
            checksum="existing",
        )
    ]

    report = import_files([well], existing=existing)

    assert report.added == []
    assert report.skipped_path == [well]
    assert report.skipped_count == 1


def test_import_files_skips_duplicate_checksum(tmp_path: Path):
    first = tmp_path / "first.las"
    second = tmp_path / "second.las"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")
    first_report = import_files([first], existing=[])

    second_report = import_files([second], existing=first_report.added)

    assert second_report.added == []
    assert second_report.skipped_checksum == [second]


def test_import_folder_uses_recursive_scanner(tmp_path: Path):
    root = tmp_path / "folder"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "cube.sgy").write_bytes(b"cube")

    report = import_folder(root, existing=[])

    assert report.added_count == 1
    assert report.added[0].type == "seismic"
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'paleo_workbench.resources.import_service'`.

- [ ] **Step 3: Implement service**

Create `paleo_workbench/resources/import_service.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.scanner import scan_resources


@dataclass
class ImportReport:
    added: list[ResourceItem] = field(default_factory=list)
    skipped_path: list[Path] = field(default_factory=list)
    skipped_checksum: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def added_count(self) -> int:
        return len(self.added)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped_path) + len(self.skipped_checksum)


def _resolved_path(path: str | Path) -> str:
    return Path(path).expanduser().resolve().as_posix()


def _existing_path_keys(existing: list[ResourceItem]) -> set[str]:
    return {_resolved_path(resource.path) for resource in existing if resource.path}


def _existing_checksums(existing: list[ResourceItem]) -> set[str]:
    return {resource.checksum for resource in existing if resource.checksum}


def _filter_new(candidates: list[ResourceItem], existing: list[ResourceItem]) -> ImportReport:
    report = ImportReport()
    path_keys = _existing_path_keys(existing)
    checksums = _existing_checksums(existing)

    for resource in candidates:
        candidate_path = Path(resource.path)
        resolved = _resolved_path(candidate_path)
        if resolved in path_keys:
            report.skipped_path.append(candidate_path)
            continue
        if resource.checksum and resource.checksum in checksums:
            report.skipped_checksum.append(candidate_path)
            continue
        report.added.append(resource)
        path_keys.add(resolved)
        if resource.checksum:
            checksums.add(resource.checksum)
    return report


def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    candidates: list[ResourceItem] = []
    warnings: list[str] = []
    for path in paths:
        try:
            candidates.extend(scan_resources(path.parent, project_path=project_path))
        except OSError as exc:
            warnings.append(f"{path}: {exc}")
    requested = {_resolved_path(path) for path in paths}
    candidates = [
        resource
        for resource in candidates
        if _resolved_path(resource.path) in requested
    ]
    report = _filter_new(candidates, existing)
    report.warnings.extend(warnings)
    return report


def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
) -> ImportReport:
    try:
        candidates = scan_resources(root, project_path=project_path)
    except OSError as exc:
        return ImportReport(warnings=[f"{root}: {exc}"])
    return _filter_new(candidates, existing)
```

- [ ] **Step 4: Run service tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_import_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/resources/import_service.py tests/test_data_import_service.py
git commit -m "feat: add data import service"
```

---

### Task 3: Preview Strategy Helpers

**Files:**
- Create: `paleo_workbench/ui/pages/preview_strategy.py`
- Test: `tests/test_preview_strategy.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`.
- Produces: `PreviewState`, `preview_for_resource()`, `preview_for_artifact()`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_preview_strategy.py`:

```python
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.preview_strategy import preview_for_artifact, preview_for_resource


def test_preview_strategy_identifies_image(tmp_path: Path):
    image = tmp_path / "map.png"
    image.write_bytes(b"not-real-png")
    resource = ResourceItem(name="map.png", path=image.as_posix(), type="image_reference", format="png")

    state = preview_for_resource(resource)

    assert state.mode == "image"
    assert state.image_path == image.as_posix()


def test_preview_strategy_returns_table_summary():
    resource = ResourceItem(
        name="table.xlsx",
        path="/tmp/table.xlsx",
        type="spreadsheet",
        format="xlsx",
        parsed_summary={"size_bytes": 2048},
    )

    state = preview_for_resource(resource)

    assert state.mode == "table"
    assert "table.xlsx" in state.title
    assert any("2048" in line for line in state.lines)


def test_preview_strategy_metadata_for_unknown():
    resource = ResourceItem(name="raw.bin", path="/tmp/raw.bin", type="unknown", format="bin")

    state = preview_for_resource(resource)

    assert state.mode == "metadata"
    assert "暂不支持预览" in state.warning


def test_preview_strategy_export_artifact():
    artifact = ExportArtifact(linked_id="map_1", format="GeoTIFF", output_path="/tmp/map.tif")

    state = preview_for_artifact(artifact)

    assert state.mode == "artifact"
    assert "GeoTIFF" in state.title
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement preview strategy**

Create `paleo_workbench/ui/pages/preview_strategy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from paleo_workbench.project.models import ExportArtifact, ResourceItem


@dataclass(frozen=True)
class PreviewState:
    mode: str
    title: str
    lines: list[str]
    image_path: str | None = None
    warning: str = ""


def _summary_lines(name: str, path: str, fmt: str, size: object = None) -> list[str]:
    lines = [f"文件: {name}", f"格式: {fmt}", f"路径: {path}"]
    if size is not None:
        lines.append(f"大小: {size} bytes")
    return lines


def preview_for_resource(resource: ResourceItem, base_path: Path | None = None) -> PreviewState:
    size = resource.parsed_summary.get("size_bytes")
    lines = _summary_lines(resource.name, resource.path, resource.format, size)
    image_types = {"image_reference"}
    image_formats = {"png", "jpg", "jpeg", "tif", "tiff"}
    table_types = {"spreadsheet", "tabular", "time_depth", "horizon", "well_stratification"}

    if resource.type in image_types or resource.format in image_formats:
        return PreviewState("image", resource.name, lines, image_path=resource.path)
    if resource.type in table_types:
        return PreviewState("table", resource.name, lines)
    if resource.type == "well_log":
        return PreviewState("well_log", resource.name, lines + ["预览: 测井摘要"])
    if resource.type == "seismic":
        return PreviewState("seismic", resource.name, lines + ["预览: 地震体元数据"])
    if resource.type in {"document", "reference_map", "well_reference"}:
        return PreviewState("metadata", resource.name, lines, warning="此类型使用外部工具预览")
    return PreviewState("metadata", resource.name, lines, warning="暂不支持预览")


def preview_for_artifact(artifact: ExportArtifact, base_path: Path | None = None) -> PreviewState:
    lines = [
        f"格式: {artifact.format}",
        f"路径: {artifact.output_path}",
        f"关联: {artifact.linked_id}",
    ]
    return PreviewState("artifact", f"成果文件 · {artifact.format}", lines)
```

- [ ] **Step 4: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_preview_strategy.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/preview_strategy.py tests/test_preview_strategy.py
git commit -m "feat: add data preview strategy"
```

---

### Task 4: DataCatalogPanel

**Files:**
- Create: `paleo_workbench/ui/pages/data_catalog_panel.py`
- Test: `tests/test_data_catalog_panel.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`.
- Produces: `DataCatalogPanel(QFrame)`, `category_changed = Signal(str)`, `update_counts(resources, artifacts)`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_catalog_panel.py`:

```python
from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_catalog_panel import DataCatalogPanel


def test_catalog_renders_categories(qtbot):
    panel = DataCatalogPanel()
    qtbot.addWidget(panel)

    assert panel.objectName() == "DataCatalogPanel"
    assert "全部" in panel.category_labels
    assert "测井" in panel.category_labels
    assert "成果" in panel.category_labels


def test_catalog_updates_counts(qtbot):
    panel = DataCatalogPanel()
    qtbot.addWidget(panel)
    resources = [
        ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las"),
        ResourceItem(name="cube.sgy", path="/tmp/cube.sgy", type="seismic", format="sgy"),
    ]
    artifacts = [ExportArtifact(linked_id="map_1", format="PDF", output_path="/tmp/map.pdf")]

    panel.update_counts(resources, artifacts)

    assert panel.category_labels["全部"].text().endswith("3")
    assert panel.category_labels["测井"].text().endswith("1")
    assert panel.category_labels["成果"].text().endswith("1")
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_catalog_panel.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement panel**

Create `paleo_workbench/ui/pages/data_catalog_panel.py` with:

```python
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens


CATEGORIES = {
    "全部": None,
    "输入数据": "input",
    "成果": "artifact",
    "参考资料": "reference",
    "异常": "issue",
    "测井": "well_log",
    "地震": "seismic",
    "层位": "horizon",
    "井分层": "well_stratification",
    "时深": "time_depth",
    "表格": "tabular",
    "文档": "document",
    "影像": "image_reference",
    "参考图": "reference_map",
    "未知": "unknown",
}


class DataCatalogPanel(QFrame):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataCatalogPanel")
        self.setFixedWidth(180)
        self.setStyleSheet(
            f"QFrame#DataCatalogPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER}; border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)
        self.title_label = QLabel("数据目录")
        self.title_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(self.title_label)
        self.category_labels: dict[str, QPushButton] = {}
        for label in CATEGORIES:
            button = QPushButton(f"{label} 0")
            button.setObjectName("SecondaryButton")
            button.clicked.connect(lambda _checked=False, name=label: self.category_changed.emit(name))
            self.category_labels[label] = button
            layout.addWidget(button)
        layout.addStretch()

    def update_counts(self, resources: list, artifacts: list) -> None:
        counts = Counter(resource.type for resource in resources)
        role_counts = Counter(resource.artifact_role or "input" for resource in resources)
        issue_count = sum(1 for resource in resources if resource.status in {"missing", "warning", "failed", "error"})
        values = {
            "全部": len(resources) + len(artifacts),
            "输入数据": role_counts["input"],
            "成果": len(artifacts) + role_counts["derived"] + role_counts["export"],
            "参考资料": sum(counts[key] for key in ("document", "image_reference", "reference_map", "well_reference")),
            "异常": issue_count,
        }
        for label, resource_type in CATEGORIES.items():
            count = values.get(label, counts[resource_type] if resource_type else 0)
            self.category_labels[label].setText(f"{label} {count}")
```

- [ ] **Step 4: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_catalog_panel.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_catalog_panel.py tests/test_data_catalog_panel.py
git commit -m "feat: add data catalog panel"
```

---

### Task 5: DataAssetTable

**Files:**
- Create: `paleo_workbench/ui/pages/data_asset_table.py`
- Test: `tests/test_data_asset_table.py`

**Interfaces:**
- Consumes: `ResourceItem`, `ExportArtifact`, selected category/search strings.
- Produces: `DataAssetTable(QWidget)`, `update_assets()`, `set_category()`, `set_search_text()`, `selected_asset_changed`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_asset_table.py`:

```python
from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_asset_table import DataAssetTable


def test_asset_table_columns(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    headers = [table.table.horizontalHeaderItem(i).text() for i in range(table.table.columnCount())]
    assert headers == ["文件名", "类型", "格式", "状态", "角色", "大小", "来源", "路径"]


def test_asset_table_renders_resources_and_artifacts(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las", parsed_summary={"size_bytes": 10})]
    artifacts = [ExportArtifact(linked_id="map_1", format="PDF", output_path="/tmp/map.pdf")]

    table.update_assets(resources, artifacts)

    assert table.table.rowCount() == 2
    assert table.table.item(0, 0).text() == "well.las"
    assert table.table.item(1, 4).text() == "成果"


def test_asset_table_filters_by_category(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las"),
        ResourceItem(name="cube.sgy", path="/tmp/cube.sgy", type="seismic", format="sgy"),
    ]
    table.update_assets(resources, [])
    table.set_category("测井")

    assert table.table.rowCount() == 1
    assert table.table.item(0, 0).text() == "well.las"


def test_asset_table_filters_by_search(qtbot):
    table = DataAssetTable()
    qtbot.addWidget(table)
    resources = [
        ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las"),
        ResourceItem(name="cube.sgy", path="/tmp/cube.sgy", type="seismic", format="sgy"),
    ]
    table.update_assets(resources, [])
    table.set_search_text("cube")

    assert table.table.rowCount() == 1
    assert table.table.item(0, 0).text() == "cube.sgy"
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_asset_table.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement table**

Create `paleo_workbench/ui/pages/data_asset_table.py`. Use `QTableWidget`, store unfiltered assets in `self._resources` and `self._artifacts`, and render rows through `_matches_category()` and `_matches_search()`. Use `tokens.RESOURCE_LABELS.get(type, type)` for resource type labels. Represent artifacts with role `"成果"`, status `"generated"`, name from `Path(output_path).name`, and path from `output_path`.

- [ ] **Step 4: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_asset_table.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_asset_table.py tests/test_data_asset_table.py
git commit -m "feat: add data asset table"
```

---

### Task 6: DataDetailPanel

**Files:**
- Create: `paleo_workbench/ui/pages/data_detail_panel.py`
- Test: `tests/test_data_detail_panel.py`

**Interfaces:**
- Consumes: `preview_for_resource()`, `preview_for_artifact()`, `PreviewState`.
- Produces: `DataDetailPanel(QFrame)` with `update_asset(asset: object | None)`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_data_detail_panel.py`:

```python
from pathlib import Path

from PySide6.QtWidgets import QLabel

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui.pages.data_detail_panel import DataDetailPanel


def _labels(panel):
    return [label.text() for label in panel.findChildren(QLabel)]


def test_detail_panel_empty_state(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    panel.update_asset(None)
    assert "请选择数据项" in _labels(panel)


def test_detail_panel_resource_metadata(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    resource = ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las", checksum="abc")
    panel.update_asset(resource)
    texts = "\n".join(_labels(panel))
    assert "well.las" in texts
    assert "abc" in texts
    assert "测井" in texts or "well_log" in texts


def test_detail_panel_artifact_metadata(qtbot):
    panel = DataDetailPanel()
    qtbot.addWidget(panel)
    artifact = ExportArtifact(linked_id="map_1", format="PDF", output_path="/tmp/map.pdf")
    panel.update_asset(artifact)
    assert "map.pdf" in "\n".join(_labels(panel))
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_detail_panel.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement panel**

Create `paleo_workbench/ui/pages/data_detail_panel.py`. Build a fixed-width `QFrame` with `title_label`, `metadata_layout`, `preview_title`, and `preview_layout`. `update_asset(None)` clears rows and shows `"请选择数据项"`. For `ResourceItem`, display name/type/format/status/path/checksum and preview state lines. For `ExportArtifact`, display format/path/linked id and preview state lines.

- [ ] **Step 4: Run tests**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_detail_panel.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_detail_panel.py tests/test_data_detail_panel.py
git commit -m "feat: add data detail panel"
```

---

### Task 7: DataPage Assembly And Import Refresh

**Files:**
- Modify: `paleo_workbench/ui/pages/action_panel.py`
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Modify: `paleo_workbench/ui/app_shell.py`
- Modify: `paleo_workbench/app.py`
- Modify: `paleo_workbench/ui/pages/__init__.py`
- Test: `tests/test_data_page.py`
- Test: `tests/test_data_integration.py`

**Interfaces:**
- Consumes: all panels and services from earlier tasks.
- Produces: DataPage with three-zone layout, `update_state(state, resources, artifacts=None)`, `import_paths(paths)`, `import_folder_path(path)`.

- [ ] **Step 1: Write failing DataPage tests**

Update `tests/test_data_page.py`:

```python
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.data_page import DataPage


def test_data_page_assembles_management_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    assert page.catalog_panel is not None
    assert page.asset_table is not None
    assert page.detail_panel is not None
    assert page.action_panel is not None


def test_data_page_import_paths_updates_project_and_table(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)

    report = page.import_paths([well])

    assert report.added_count == 1
    assert len(project.resources) == 1
    assert page.asset_table.table.rowCount() == 1


def test_data_page_import_paths_skips_duplicate(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([well])

    report = page.import_paths([well])

    assert report.added_count == 0
    assert report.skipped_count == 1
    assert len(project.resources) == 1
```

- [ ] **Step 2: Update integration tests**

Update `tests/test_data_integration.py`:

```python
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage


def test_app_shell_page_one_is_data_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert isinstance(page, DataPage)


def test_data_page_receives_resources_and_artifacts(qtbot):
    project = ProjectDocument.new("Test")
    project.resources.append(ResourceItem(name="well.las", path="/tmp/well.las", type="well_log", format="las"))
    project.export_artifacts.append(ExportArtifact(linked_id="map_1", format="PDF", output_path="/tmp/map.pdf"))
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert page.asset_table.table.rowCount() == 2
```

- [ ] **Step 3: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_integration.py -q`

Expected: FAIL because DataPage does not yet accept `project`, does not assemble new panels, and does not import paths.

- [ ] **Step 4: Implement DataPage assembly**

Modify `paleo_workbench/ui/pages/data_page.py`:

```python
class DataPage(QWidget):
    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.project = project or ProjectDocument.new("Untitled Project")
        self._resources = self.project.resources
        self._artifacts = self.project.export_artifacts
        ...
```

Use `QHBoxLayout` for three zones:

```python
self.catalog_panel = DataCatalogPanel()
self.asset_table = DataAssetTable()
self.detail_panel = DataDetailPanel()
self.action_panel = ActionPanel()
```

Wire:

```python
self.catalog_panel.category_changed.connect(self.asset_table.set_category)
self.asset_table.selected_asset_changed.connect(self.detail_panel.update_asset)
self.import_btn = self.action_panel.import_btn
self.import_folder_btn = self.action_panel.import_folder_btn
self.remove_btn = self.action_panel.remove_btn
self.rescan_btn = self.action_panel.rescan_btn
```

Add:

```python
def update_state(self, state: dict, resources: list, artifacts: list | None = None) -> None:
    self._resources = resources
    self._artifacts = artifacts or []
    self.summary_bar.update_state(state)
    self.catalog_panel.update_counts(self._resources, self._artifacts)
    self.asset_table.update_assets(self._resources, self._artifacts)

def import_paths(self, paths: list[Path]) -> ImportReport:
    report = import_files(paths, self.project.resources)
    self.project.resources.extend(report.added)
    self.update_state(dashboard_state(self.project), self.project.resources, self.project.export_artifacts)
    return report

def import_folder_path(self, path: Path) -> ImportReport:
    report = import_folder(path, self.project.resources)
    self.project.resources.extend(report.added)
    self.update_state(dashboard_state(self.project), self.project.resources, self.project.export_artifacts)
    return report
```

- [ ] **Step 5: Implement action panel additions**

Modify `paleo_workbench/ui/pages/action_panel.py` so it exposes:

```python
self.import_btn = QPushButton("导入文件")
self.import_folder_btn = QPushButton("导入目录")
self.rescan_btn = QPushButton("重新扫描")
self.remove_btn = QPushButton("移出项目")
self.open_folder_btn = QPushButton("打开目录")
```

Keep object names consistent: primary import file button uses `PrimaryButton`; others use `SecondaryButton`.

- [ ] **Step 6: Update app shell wiring**

Modify `paleo_workbench/ui/app_shell.py` and `paleo_workbench/app.py` so DataPage is constructed with the project and updated with artifacts:

```python
self.page_stack.addWidget(DataPage(project=self.project))
```

If `AppShell` does not own project, pass project into `AppShell(project=project)` from `PaleoWorkbenchWindow`.

Update `update_data_page` signature:

```python
def update_data_page(self, state: dict, resources: list, artifacts: list | None = None) -> None:
    page = self.page_stack.widget(1)
    if hasattr(page, "update_state"):
        page.update_state(state, resources, artifacts or [])
```

- [ ] **Step 7: Run focused tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_integration.py tests/test_app_shell.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/action_panel.py paleo_workbench/ui/pages/data_page.py paleo_workbench/ui/app_shell.py paleo_workbench/app.py paleo_workbench/ui/pages/__init__.py tests/test_data_page.py tests/test_data_integration.py
git commit -m "feat: assemble data management page"
```

---

### Task 8: File Dialog Hooks And Final Verification

**Files:**
- Modify: `paleo_workbench/ui/pages/data_page.py`
- Test: `tests/test_data_page.py`
- Modify: `task_plan.md`
- Modify: `progress.md`
- Modify: `findings.md` if new discoveries occur

**Interfaces:**
- Consumes: `DataPage.import_paths()`, `DataPage.import_folder_path()`.
- Produces: button-click file dialog hooks and final documented completion.

- [ ] **Step 1: Write failing tests for dialog method seams**

Append to `tests/test_data_page.py`:

```python
from pathlib import Path


def test_data_page_import_files_dialog_uses_selected_paths(qtbot, tmp_path: Path, monkeypatch):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_files", lambda: [well])

    report = page.import_files_from_dialog()

    assert report.added_count == 1
    assert project.resources[0].name == "well.las"


def test_data_page_import_folder_dialog_uses_selected_folder(qtbot, tmp_path: Path, monkeypatch):
    project = ProjectDocument.new("Demo")
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "cube.sgy").write_bytes(b"cube")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_folder", lambda: folder)

    report = page.import_folder_from_dialog()

    assert report.added_count == 1
    assert project.resources[0].name == "cube.sgy"
```

- [ ] **Step 2: Run tests to verify red**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py::test_data_page_import_files_dialog_uses_selected_paths tests/test_data_page.py::test_data_page_import_folder_dialog_uses_selected_folder -q`

Expected: FAIL because dialog seam methods do not exist.

- [ ] **Step 3: Implement dialog hooks**

In `DataPage`:

```python
from PySide6.QtWidgets import QFileDialog

def _choose_import_files(self) -> list[Path]:
    paths, _selected_filter = QFileDialog.getOpenFileNames(self, "导入文件")
    return [Path(path) for path in paths]

def _choose_import_folder(self) -> Path | None:
    path = QFileDialog.getExistingDirectory(self, "导入目录")
    return Path(path) if path else None

def import_files_from_dialog(self) -> ImportReport:
    paths = self._choose_import_files()
    if not paths:
        return ImportReport()
    return self.import_paths(paths)

def import_folder_from_dialog(self) -> ImportReport:
    folder = self._choose_import_folder()
    if folder is None:
        return ImportReport()
    return self.import_folder_path(folder)
```

Connect buttons:

```python
self.import_btn.clicked.connect(self.import_files_from_dialog)
self.import_folder_btn.clicked.connect(self.import_folder_from_dialog)
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_data_page.py tests/test_data_integration.py tests/test_data_import_service.py tests/test_data_asset_table.py tests/test_data_catalog_panel.py tests/test_data_detail_panel.py tests/test_preview_strategy.py -q
```

Expected: PASS.

- [ ] **Step 5: Run full tests**

Run:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

Expected: all tests PASS.

- [ ] **Step 6: Update planning files**

Update:

- `task_plan.md`: Phase 11 status from design review to complete, update test count.
- `progress.md`: record tasks completed, verification commands, commit names.
- `findings.md`: add any import/preview implementation notes discovered during work.

- [ ] **Step 7: Commit**

Run:

```bash
git add paleo_workbench/ui/pages/data_page.py tests/test_data_page.py task_plan.md progress.md findings.md
git commit -m "feat: wire data import dialogs"
```

---

## Final Verification

After all tasks:

```bash
git diff --check
QT_QPA_PLATFORM=offscreen pytest -q
python -m compileall -q paleo_workbench
```

Expected:

- `git diff --check`: no output, exit 0.
- pytest: all tests pass.
- compileall: no output, exit 0.

## Self-Review

Spec coverage:

- Import files/folder: Tasks 2, 7, 8.
- Scanner/classifier confidence: Task 1.
- Deduplication by path/checksum: Task 2.
- Catalog counts/filter: Task 4 and Task 7.
- Extended table/search/filter: Task 5 and Task 7.
- Details/preview: Tasks 3 and 6.
- Existing model reuse: Tasks 2, 3, 7.
- Error handling for unsupported preview: Task 3 and Task 6.
- AppShell integration: Task 7.
- Full verification: Task 8.

Placeholder scan: all tasks include concrete files, commands, expected results, and code-level interfaces. No deferred-marker text is intentionally left in task steps.

Type consistency:

- `ImportReport`, `import_files`, and `import_folder` are introduced in Task 2 and consumed in Tasks 7 and 8.
- `PreviewState`, `preview_for_resource`, and `preview_for_artifact` are introduced in Task 3 and consumed in Task 6.
- Panel method names are defined in Shared Interfaces and used consistently in Tasks 4-7.
