# Paleogeography Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable desktop MVP for paleogeographic map compilation with project recovery, data scanning, deterministic mock factor/prediction outputs, a workflow dashboard, and a clean `geo-viz-engine` adapter boundary.

**Architecture:** Create a new root-level `paleo_workbench` PySide6 application that owns business workflow state and `.paleo.json` project files. Keep `geo-viz-engine` independent; expose typed adapter schemas and small viewer adapters so the workbench never depends on `geo-viz-engine/src/app.py` or old page navigation. Persist generated outputs under `project-name.artifacts/` and store only metadata and paths in the project file.

**Tech Stack:** Python 3.12, PySide6, Pydantic v2-compatible models, pytest, pytest-qt, existing `geo-viz-engine` workspace packages (`geoviz_paleo_map`, `geoviz_plots`, `geoviz_seismic`, `geoviz_well_log`, `geoviz_cross_well`).

## Global Constraints

- UI must strictly follow `/home/kevin/projects/paleo_project/古地理图编制系统 (standalone).html`.
- Before UI implementation, extract a screen inventory from the standalone prototype; do not parse or depend on the bundle at runtime.
- Main application owns project format, resource catalog, workflow state, prediction task state, QC state, export artifact tracking, and UI shell.
- `geo-viz-engine` owns visualization, rendering, interpolation, projection, styling, and high-fidelity export utilities.
- Default project CRS is `EPSG:4326 / WGS84`.
- First MVP manages target horizons plus sequence scheme metadata; it does not implement full stratigraphic calibration tools.
- Project format is `.paleo.json`; generated arrays, thumbnails, predictions, QC reports, and exports live under `project-name.artifacts/`.
- All paths in `.paleo.json` are relative when possible; external resources are marked `external=true`.
- Unsupported or proprietary resource formats are indexed as `status=indexed_reference`.
- Mock factor maps and mock predictions must be deterministic and record `seed`, `generator_version`, and `input_snapshot_hash`.
- Main app depends on typed adapter contracts, not on old `geo-viz-engine` page state, shell navigation, `PAGE_CONFIGS`, or `.gvz`.
- Root directory currently is not a valid git repository. Do not delete or replace `.git` without explicit user approval. If a task changes only root files before the repo is repaired, record the checkpoint in this plan instead of committing.

---

## File Structure

Create root application package:

```text
pyproject.toml
paleo_workbench/
  __init__.py
  main.py
  app.py
  project/
    __init__.py
    models.py
    manager.py
    paths.py
  resources/
    __init__.py
    scanner.py
    classifier.py
  workflow/
    __init__.py
    service.py
    factors.py
    qc.py
    export.py
  prediction/
    __init__.py
    adapters.py
  adapters/
    __init__.py
    schemas.py
    base.py
    paleo_map.py
  ui/
    __init__.py
    screen_inventory.py
    dashboard.py
tests/
  test_project_models.py
  test_project_manager.py
  test_resource_scanner.py
  test_workflow_service.py
  test_mock_outputs.py
  test_adapter_schemas.py
  test_integration_smoke.py
```

Modify `geo-viz-engine` only if adapter wrappers require package-side access. First attempt should keep adapter code in `paleo_workbench/adapters/` and import existing `geo-viz-engine` packages.

---

### Task 1: Root Package And Development Entry Point

**Files:**
- Create: `pyproject.toml`
- Create: `paleo_workbench/__init__.py`
- Create: `paleo_workbench/main.py`
- Create: `tests/test_project_models.py`

**Interfaces:**
- Produces: importable package `paleo_workbench`
- Produces: runnable command `python -m paleo_workbench.main`
- Consumes: none

- [ ] **Step 1: Write the failing package import test**

Create `tests/test_project_models.py` with:

```python
def test_package_imports():
    import paleo_workbench

    assert paleo_workbench.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'paleo_workbench'`.

- [ ] **Step 3: Add root packaging**

Create `pyproject.toml`:

```toml
[project]
name = "paleo-workbench"
version = "0.1.0"
description = "Paleogeographic map compilation desktop workbench"
requires-python = ">=3.12,<3.13"
dependencies = [
    "pyside6>=6.6",
    "pydantic>=2.0",
    "numpy>=1.26",
    "pandas>=2.0",
    "openpyxl>=3.1",
    "lasio>=0.14",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-qt>=4.5.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
qt_api = "pyside6"
timeout = 60
pythonpath = [
    ".",
    "geo-viz-engine",
    "geo-viz-engine/packages/geoviz_paleo_map",
    "geo-viz-engine/packages/geoviz_plots",
    "geo-viz-engine/packages/geoviz_seismic",
    "geo-viz-engine/packages/geoviz_well_log",
    "geo-viz-engine/packages/geoviz_cross_well",
]
```

Create `paleo_workbench/__init__.py`:

```python
"""Paleogeography map compilation workbench."""

__version__ = "0.1.0"
```

Create `paleo_workbench/main.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QLabel


def main() -> int:
    app = QApplication(sys.argv)
    label = QLabel("Paleogeography Workbench")
    label.setMinimumSize(480, 240)
    label.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run package import test**

Run:

```bash
python -m pytest tests/test_project_models.py::test_package_imports -v
```

Expected: PASS.

- [ ] **Step 5: Verify app entry point imports without launching GUI**

Run:

```bash
python -c "from paleo_workbench.main import main; print(callable(main))"
```

Expected output:

```text
True
```

- [ ] **Step 6: Checkpoint**

Run:

```bash
git rev-parse --show-toplevel
```

Expected in current workspace: FAIL because root git is invalid. Record checkpoint in this plan under the task status section. If the root repository has been repaired with user approval, run:

```bash
git add pyproject.toml paleo_workbench/__init__.py paleo_workbench/main.py tests/test_project_models.py
git commit -m "chore: scaffold paleogeography workbench package"
```

---

### Task 2: Project Schema, Artifact Paths, And Round Trip

**Files:**
- Create: `paleo_workbench/project/__init__.py`
- Create: `paleo_workbench/project/models.py`
- Create: `paleo_workbench/project/paths.py`
- Create: `paleo_workbench/project/manager.py`
- Modify: `tests/test_project_models.py`
- Create: `tests/test_project_manager.py`

**Interfaces:**
- Consumes: package from Task 1
- Produces: `ProjectDocument`, `ResourceItem`, `CompilationRun`, `WorkflowStep`
- Produces: `ProjectManager.save(project: ProjectDocument) -> None`
- Produces: `ProjectManager.load() -> ProjectDocument`
- Produces: `artifact_dir_for(project_path: Path) -> Path`

- [ ] **Step 1: Write failing schema defaults test**

Append to `tests/test_project_models.py`:

```python
from paleo_workbench.project.models import ProjectDocument


def test_project_defaults_include_crs_and_empty_workflow():
    project = ProjectDocument.new(name="HZ26 Demo", region="惠州26区")

    assert project.meta.name == "HZ26 Demo"
    assert project.meta.region == "惠州26区"
    assert project.coordinate.project_crs == "EPSG:4326"
    assert project.resources == []
    assert project.compilation_runs == []
```

- [ ] **Step 2: Run schema test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_models.py::test_project_defaults_include_crs_and_empty_workflow -v
```

Expected: FAIL with `ModuleNotFoundError` for `paleo_workbench.project`.

- [ ] **Step 3: Implement project models**

Create `paleo_workbench/project/__init__.py`:

```python
from paleo_workbench.project.models import (
    CompilationRun,
    CoordinateReference,
    ExportArtifact,
    FactorMapTask,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ProjectMeta,
    QualityReport,
    ResourceItem,
    StratigraphicFramework,
    WorkflowStep,
)

__all__ = [
    "CompilationRun",
    "CoordinateReference",
    "ExportArtifact",
    "FactorMapTask",
    "PaleoMapDocument",
    "PredictionTask",
    "ProjectDocument",
    "ProjectMeta",
    "QualityReport",
    "ResourceItem",
    "StratigraphicFramework",
    "WorkflowStep",
]
```

Create `paleo_workbench/project/models.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ProjectMeta(BaseModel):
    name: str
    region: str = ""
    version: str = "0.1.0"
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    project_root: str = "."


class CoordinateReference(BaseModel):
    project_crs: str = "EPSG:4326"
    target_crs: str | None = None
    display_crs: str = "EPSG:4326"
    transform_history: list[dict[str, Any]] = Field(default_factory=list)


class StratigraphicFramework(BaseModel):
    target_horizon: str = ""
    sequence_boundaries: list[str] = Field(default_factory=list)
    systems_tract_scheme: str = "LST/TST/HST"
    interpretation_version: str = "v1"
    applicable_wells: list[str] = Field(default_factory=list)
    applicable_seismic_ranges: list[str] = Field(default_factory=list)


class ResourceItem(BaseModel):
    id: str = Field(default_factory=lambda: _id("res"))
    name: str
    path: str
    type: str
    format: str
    crs: str | None = None
    status: str = "indexed"
    tags: list[str] = Field(default_factory=list)
    source: str = "local"
    parsed_summary: dict[str, Any] = Field(default_factory=dict)
    checksum: str | None = None
    external: bool = False
    artifact_role: str | None = None


class WorkflowStep(BaseModel):
    id: str = Field(default_factory=lambda: _id("step"))
    step_type: Literal["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]
    status: Literal["pending", "ready", "running", "complete", "warning", "failed", "skipped", "mock"] = "pending"
    required_input_resource_ids: list[str] = Field(default_factory=list)
    produced_ids: list[str] = Field(default_factory=list)
    blocking_issue_summary: str = ""
    provenance_summary: str = ""


class CompilationRun(BaseModel):
    id: str = Field(default_factory=lambda: _id("run"))
    name: str
    target_horizon: str
    sequence_scheme_ref: str = ""
    status: Literal["draft", "running", "blocked", "review_required", "export_ready", "exported", "failed"] = "draft"
    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
    active_factor_map_task_ids: list[str] = Field(default_factory=list)
    active_prediction_task_id: str | None = None
    active_paleomap_document_id: str | None = None
    active_quality_report_id: str | None = None
    export_artifact_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)


class FactorMapTask(BaseModel):
    id: str = Field(default_factory=lambda: _id("factor"))
    name: str
    target_horizon: str
    factor_type: str
    input_resource_ids: list[str] = Field(default_factory=list)
    method: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    output_resource_ids: list[str] = Field(default_factory=list)
    quality_metrics: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    source_kind: Literal["real", "imported", "mock", "mixed"] = "mock"
    input_snapshot_hash: str = ""
    generator_version: str | None = None
    seed: int | None = None


class PredictionTask(BaseModel):
    id: str = Field(default_factory=lambda: _id("pred"))
    name: str
    adapter_kind: Literal["mock", "http", "local"] = "mock"
    input_factor_map_ids: list[str] = Field(default_factory=list)
    input_refs: dict[str, list[str]] = Field(default_factory=dict)
    model_metadata: dict[str, Any] = Field(default_factory=dict)
    result_summary: dict[str, Any] = Field(default_factory=dict)
    probability_summary: dict[str, Any] = Field(default_factory=dict)
    evidence_contribution: list[dict[str, Any]] = Field(default_factory=list)
    review_areas: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    adapter_schema_version: str = "1.0"
    input_snapshot_hash: str = ""
    generator_version: str | None = None
    seed: int | None = None


class PaleoMapDocument(BaseModel):
    id: str = Field(default_factory=lambda: _id("map"))
    name: str
    linked_target_horizon: str
    linked_prediction_task_id: str | None = None
    facies_polygons: list[dict[str, Any]] = Field(default_factory=list)
    facies_style: dict[str, Any] = Field(default_factory=dict)
    well_overlays: list[dict[str, Any]] = Field(default_factory=list)
    map_chrome: dict[str, Any] = Field(default_factory=dict)
    view_state: dict[str, Any] = Field(default_factory=dict)
    edit_history: list[dict[str, Any]] = Field(default_factory=list)


class QualityReport(BaseModel):
    id: str = Field(default_factory=lambda: _id("qc"))
    linked_map_document_id: str
    rules: list[str] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "pending"
    generated_at: str = Field(default_factory=_now_iso)


class ExportArtifact(BaseModel):
    id: str = Field(default_factory=lambda: _id("artifact"))
    linked_id: str
    format: str
    output_path: str
    options: dict[str, Any] = Field(default_factory=dict)
    included_map_elements: list[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_now_iso)
    source_task_ids: list[str] = Field(default_factory=list)


class ProjectDocument(BaseModel):
    meta: ProjectMeta
    coordinate: CoordinateReference = Field(default_factory=CoordinateReference)
    stratigraphy: StratigraphicFramework = Field(default_factory=StratigraphicFramework)
    resources: list[ResourceItem] = Field(default_factory=list)
    compilation_runs: list[CompilationRun] = Field(default_factory=list)
    factor_map_tasks: list[FactorMapTask] = Field(default_factory=list)
    prediction_tasks: list[PredictionTask] = Field(default_factory=list)
    paleomap_documents: list[PaleoMapDocument] = Field(default_factory=list)
    quality_reports: list[QualityReport] = Field(default_factory=list)
    export_artifacts: list[ExportArtifact] = Field(default_factory=list)

    @classmethod
    def new(cls, name: str, region: str = "") -> "ProjectDocument":
        return cls(meta=ProjectMeta(name=name, region=region))
```

- [ ] **Step 4: Run schema tests**

Run:

```bash
python -m pytest tests/test_project_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Write failing project manager round-trip test**

Create `tests/test_project_manager.py`:

```python
from pathlib import Path

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.project.paths import artifact_dir_for


def test_project_round_trip_uses_relative_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_file = tmp_path / "data" / "well.las"
    data_file.parent.mkdir()
    data_file.write_text("~Version\n", encoding="utf-8")

    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(
            name="well.las",
            path=str(data_file),
            type="well_log",
            format="las",
            status="indexed",
        )
    )

    manager = ProjectManager(project_path)
    manager.save(project)
    loaded = manager.load()

    assert loaded.resources[0].path == "data/well.las"
    assert loaded.resources[0].external is False
    assert artifact_dir_for(project_path) == tmp_path / "demo.artifacts"
```

- [ ] **Step 6: Run project manager test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_manager.py::test_project_round_trip_uses_relative_paths -v
```

Expected: FAIL with `ModuleNotFoundError` for `paleo_workbench.project.manager`.

- [ ] **Step 7: Implement path helpers and manager**

Create `paleo_workbench/project/paths.py`:

```python
from __future__ import annotations

from pathlib import Path


def artifact_dir_for(project_path: Path) -> Path:
    return project_path.with_suffix("").with_name(f"{project_path.stem}.artifacts")


def ensure_artifact_layout(project_path: Path) -> Path:
    root = artifact_dir_for(project_path)
    for name in ["cache", "factor_maps", "predictions", "paleomaps", "qc", "exports", "thumbnails"]:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def relativize_path(path: str, project_path: Path) -> tuple[str, bool]:
    resolved = Path(path).resolve()
    project_dir = project_path.parent.resolve()
    try:
        return resolved.relative_to(project_dir).as_posix(), False
    except ValueError:
        return resolved.as_posix(), True
```

Create `paleo_workbench/project/manager.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.paths import ensure_artifact_layout, relativize_path


class ProjectManager:
    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path)

    def save(self, project: ProjectDocument) -> None:
        data = project.model_dump()
        for resource in data["resources"]:
            path, external = relativize_path(resource["path"], self.project_path)
            resource["path"] = path
            resource["external"] = external
        self.project_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_artifact_layout(self.project_path)
        self.project_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> ProjectDocument:
        data = json.loads(self.project_path.read_text(encoding="utf-8"))
        return ProjectDocument.model_validate(data)
```

- [ ] **Step 8: Run project manager tests**

Run:

```bash
python -m pytest tests/test_project_manager.py -v
```

Expected: PASS.

- [ ] **Step 9: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/project tests/test_project_models.py tests/test_project_manager.py
git commit -m "feat: add paleo project document model"
```

If root git is still invalid, record checkpoint: `Task 2 complete; root commit pending repository repair`.

---

### Task 3: Resource Scanner And Format Classifier

**Files:**
- Create: `paleo_workbench/resources/__init__.py`
- Create: `paleo_workbench/resources/classifier.py`
- Create: `paleo_workbench/resources/scanner.py`
- Create: `tests/test_resource_scanner.py`

**Interfaces:**
- Consumes: `ResourceItem`
- Produces: `classify_path(path: Path) -> tuple[str, str, str]`
- Produces: `scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]`

- [ ] **Step 1: Write failing classifier/scanner test**

Create `tests/test_resource_scanner.py`:

```python
from pathlib import Path

from paleo_workbench.resources.classifier import classify_path
from paleo_workbench.resources.scanner import scan_resources


def test_classify_known_and_reference_formats():
    assert classify_path(Path("A1.Las")) == ("well_log", "las", "indexed")
    assert classify_path(Path("200P_seismic.sgy")) == ("seismic", "sgy", "indexed")
    assert classify_path(Path("C6.dat")) == ("tabular", "dat", "indexed")
    assert classify_path(Path("相图.dfb")) == ("reference_map", "dfb", "indexed_reference")
    assert classify_path(Path("综合柱状图.WLP")) == ("well_reference", "wlp", "indexed_reference")


def test_scan_resources_indexes_nested_data(tmp_path: Path):
    (tmp_path / "井曲线").mkdir()
    (tmp_path / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (tmp_path / "外委资料").mkdir()
    (tmp_path / "外委资料" / "相图.dfb").write_text("binary-like", encoding="utf-8")

    resources = scan_resources(tmp_path)

    assert [r.name for r in resources] == ["A1.Las", "相图.dfb"]
    assert resources[0].type == "well_log"
    assert resources[1].status == "indexed_reference"
```

- [ ] **Step 2: Run scanner tests to verify they fail**

Run:

```bash
python -m pytest tests/test_resource_scanner.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `paleo_workbench.resources`.

- [ ] **Step 3: Implement classifier**

Create `paleo_workbench/resources/__init__.py`:

```python
from paleo_workbench.resources.scanner import scan_resources

__all__ = ["scan_resources"]
```

Create `paleo_workbench/resources/classifier.py`:

```python
from __future__ import annotations

from pathlib import Path


def classify_path(path: Path) -> tuple[str, str, str]:
    ext = path.suffix.lower().lstrip(".")
    name = path.name.lower()
    if ext in {"las"}:
        return "well_log", ext, "indexed"
    if ext in {"sgy", "segy"}:
        return "seismic", ext, "indexed"
    if ext == "dat":
        if "td" in path.parts or "时深" in path.parts:
            return "time_depth", ext, "indexed"
        if "层位" in path.parts:
            return "horizon", ext, "indexed"
        if "井分层" in path.parts:
            return "well_stratification", ext, "indexed"
        return "tabular", ext, "indexed"
    if ext in {"xlsx", "xls", "xml"}:
        return "spreadsheet", ext, "indexed"
    if ext in {"pdf", "ppt", "pptx"}:
        return "document", ext, "indexed_reference"
    if ext in {"png", "jpg", "jpeg", "tif", "tiff"}:
        return "image_reference", ext, "indexed_reference"
    if ext == "dfb" or "相图" in name:
        return "reference_map", ext or "unknown", "indexed_reference"
    if ext == "wlp":
        return "well_reference", ext, "indexed_reference"
    return "unknown", ext or "none", "indexed_reference"
```

- [ ] **Step 4: Implement scanner**

Create `paleo_workbench/resources/scanner.py`:

```python
from __future__ import annotations

import hashlib
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]:
    resources: list[ResourceItem] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if path.name.startswith("._"):
            continue
        resource_type, fmt, status = classify_path(path)
        stored_path, external = (path.as_posix(), False)
        if project_path is not None:
            stored_path, external = relativize_path(str(path), project_path)
        resources.append(
            ResourceItem(
                name=path.name,
                path=stored_path,
                type=resource_type,
                format=fmt,
                status=status,
                source="scan",
                parsed_summary={"size_bytes": path.stat().st_size},
                checksum=_checksum(path),
                external=external,
            )
        )
    return resources
```

- [ ] **Step 5: Run scanner tests**

Run:

```bash
python -m pytest tests/test_resource_scanner.py -v
```

Expected: PASS.

- [ ] **Step 6: Run scanner against sample data**

Run:

```bash
python -c "from pathlib import Path; from paleo_workbench.resources.scanner import scan_resources; items=scan_resources(Path('data')); print(len(items)); print(sorted({i.format for i in items})[:10])"
```

Expected: prints a positive count and a list containing formats such as `dat`, `dfb`, `jpg`, `las`, `pdf`, `sgy`.

- [ ] **Step 7: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/resources tests/test_resource_scanner.py
git commit -m "feat: add resource scanner"
```

If root git is still invalid, record checkpoint: `Task 3 complete; root commit pending repository repair`.

---

### Task 4: Workflow Service And Dashboard State

**Files:**
- Create: `paleo_workbench/workflow/__init__.py`
- Create: `paleo_workbench/workflow/service.py`
- Create: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `CompilationRun`, `WorkflowStep`
- Produces: `create_compilation_run(project, name, target_horizon, sequence_scheme) -> CompilationRun`
- Produces: `dashboard_state(project) -> dict[str, object]`

- [ ] **Step 1: Write failing workflow tests**

Create `tests/test_workflow_service.py`:

```python
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_create_compilation_run_adds_ordered_steps():
    project = ProjectDocument.new(name="Demo")

    run = create_compilation_run(
        project,
        name="ZJ2 编图",
        target_horizon="ZJ2",
        sequence_scheme="三级层序格架",
    )

    assert project.compilation_runs == [run]
    assert [s.step_type for s in run.workflow_steps] == [
        "data_check",
        "factor_map",
        "prediction",
        "map_compile",
        "qc",
        "export",
    ]


def test_dashboard_state_reports_missing_and_available_resources():
    project = ProjectDocument.new(name="Demo")
    project.resources.append(
        ResourceItem(name="A1.Las", path="data/A1.Las", type="well_log", format="las")
    )
    create_compilation_run(project, "Run", "ZJ2", "三级层序格架")

    state = dashboard_state(project)

    assert state["active_target_horizon"] == "ZJ2"
    assert state["resource_counts"]["well_log"] == 1
    assert state["workflow_status"] == "draft"
```

- [ ] **Step 2: Run workflow tests to verify they fail**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: FAIL with `ModuleNotFoundError` for `paleo_workbench.workflow`.

- [ ] **Step 3: Implement workflow service**

Create `paleo_workbench/workflow/__init__.py`:

```python
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state

__all__ = ["create_compilation_run", "dashboard_state"]
```

Create `paleo_workbench/workflow/service.py`:

```python
from __future__ import annotations

from collections import Counter

from paleo_workbench.project.models import CompilationRun, ProjectDocument, WorkflowStep


STEP_ORDER = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]


def create_compilation_run(
    project: ProjectDocument,
    name: str,
    target_horizon: str,
    sequence_scheme: str,
) -> CompilationRun:
    project.stratigraphy.target_horizon = target_horizon
    project.stratigraphy.systems_tract_scheme = sequence_scheme
    run = CompilationRun(
        name=name,
        target_horizon=target_horizon,
        sequence_scheme_ref=sequence_scheme,
        workflow_steps=[WorkflowStep(step_type=step) for step in STEP_ORDER],
    )
    project.compilation_runs.append(run)
    return run


def dashboard_state(project: ProjectDocument) -> dict[str, object]:
    active_run = project.compilation_runs[-1] if project.compilation_runs else None
    counts = Counter(resource.type for resource in project.resources)
    return {
        "project_name": project.meta.name,
        "active_target_horizon": active_run.target_horizon if active_run else project.stratigraphy.target_horizon,
        "sequence_scheme": active_run.sequence_scheme_ref if active_run else project.stratigraphy.systems_tract_scheme,
        "workflow_status": active_run.status if active_run else "draft",
        "resource_counts": dict(counts),
        "factor_map_count": len(project.factor_map_tasks),
        "prediction_count": len(project.prediction_tasks),
        "qc_issue_count": sum(len(report.issues) for report in project.quality_reports),
        "export_count": len(project.export_artifacts),
    }
```

- [ ] **Step 4: Run workflow tests**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow tests/test_workflow_service.py
git commit -m "feat: add compilation workflow service"
```

If root git is still invalid, record checkpoint: `Task 4 complete; root commit pending repository repair`.

---

### Task 5: Deterministic Factor Map And Prediction Mock Services

**Files:**
- Create: `paleo_workbench/workflow/factors.py`
- Create: `paleo_workbench/prediction/__init__.py`
- Create: `paleo_workbench/prediction/adapters.py`
- Create: `tests/test_mock_outputs.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `FactorMapTask`, `PredictionTask`
- Produces: `create_mock_factor_map(project, target_horizon, factor_type, seed) -> FactorMapTask`
- Produces: `MockPredictionAdapter.run(project, factor_map_ids, seed) -> PredictionTask`

- [ ] **Step 1: Write failing deterministic mock tests**

Create `tests/test_mock_outputs.py`:

```python
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_mock_factor_map_is_deterministic():
    project_a = ProjectDocument.new("A")
    project_b = ProjectDocument.new("B")

    task_a = create_mock_factor_map(project_a, "ZJ2", "sand_thickness", seed=42)
    task_b = create_mock_factor_map(project_b, "ZJ2", "sand_thickness", seed=42)

    assert task_a.parameters["sample_points"] == task_b.parameters["sample_points"]
    assert task_a.input_snapshot_hash == task_b.input_snapshot_hash
    assert task_a.source_kind == "mock"


def test_mock_prediction_is_deterministic():
    project = ProjectDocument.new("Demo")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    adapter = MockPredictionAdapter()

    first = adapter.run(project, [factor.id], seed=7)
    second = adapter.run(project, [factor.id], seed=7)

    assert first.result_summary == second.result_summary
    assert first.probability_summary == second.probability_summary
    assert first.adapter_schema_version == "1.0"
```

- [ ] **Step 2: Run mock tests to verify they fail**

Run:

```bash
python -m pytest tests/test_mock_outputs.py -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement deterministic factor map service**

Create `paleo_workbench/workflow/factors.py`:

```python
from __future__ import annotations

import hashlib
import json
import random

from paleo_workbench.project.models import FactorMapTask, ProjectDocument


GENERATOR_VERSION = "mock-factor-v1"


def _snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_mock_factor_map(
    project: ProjectDocument,
    target_horizon: str,
    factor_type: str,
    seed: int,
) -> FactorMapTask:
    rng = random.Random(seed)
    sample_points = [
        {
            "well": f"A{i + 1}",
            "x": round(114.0 + rng.random() * 0.3, 6),
            "y": round(22.5 + rng.random() * 0.3, 6),
            "value": round(10.0 + rng.random() * 40.0, 3),
        }
        for i in range(8)
    ]
    snapshot = {
        "target_horizon": target_horizon,
        "factor_type": factor_type,
        "seed": seed,
        "generator_version": GENERATOR_VERSION,
        "sample_points": sample_points,
    }
    task = FactorMapTask(
        name=f"{target_horizon} {factor_type}",
        target_horizon=target_horizon,
        factor_type=factor_type,
        method="mock",
        parameters={"sample_points": sample_points},
        status="complete",
        source_kind="mock",
        input_snapshot_hash=_snapshot_hash(snapshot),
        generator_version=GENERATOR_VERSION,
        seed=seed,
    )
    project.factor_map_tasks.append(task)
    return task
```

- [ ] **Step 4: Implement mock prediction adapter**

Create `paleo_workbench/prediction/__init__.py`:

```python
from paleo_workbench.prediction.adapters import MockPredictionAdapter

__all__ = ["MockPredictionAdapter"]
```

Create `paleo_workbench/prediction/adapters.py`:

```python
from __future__ import annotations

import hashlib
import json
import random

from paleo_workbench.project.models import PredictionTask, ProjectDocument


GENERATOR_VERSION = "mock-prediction-v1"


def _snapshot_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class MockPredictionAdapter:
    adapter_kind = "mock"
    schema_version = "1.0"

    def run(self, project: ProjectDocument, factor_map_ids: list[str], seed: int) -> PredictionTask:
        rng = random.Random(seed)
        facies = ["三角洲前缘砂体", "水下分流河道砂体", "分流间湾泥", "滨岸砂体"]
        predicted = [
            {
                "region_id": f"mock_region_{i + 1}",
                "facies": facies[i % len(facies)],
                "probability": round(0.55 + rng.random() * 0.35, 3),
            }
            for i in range(4)
        ]
        snapshot = {
            "factor_map_ids": factor_map_ids,
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "schema_version": self.schema_version,
        }
        task = PredictionTask(
            name="Mock sedimentary facies prediction",
            adapter_kind="mock",
            input_factor_map_ids=factor_map_ids,
            result_summary={"predicted_regions": predicted},
            probability_summary={"mean_probability": round(sum(p["probability"] for p in predicted) / len(predicted), 3)},
            evidence_contribution=[
                {"name": "sand_thickness", "weight": 0.45},
                {"name": "target_horizon", "weight": 0.30},
                {"name": "neighbor_wells", "weight": 0.25},
            ],
            review_areas=[p for p in predicted if p["probability"] < 0.7],
            status="complete",
            adapter_schema_version=self.schema_version,
            input_snapshot_hash=_snapshot_hash(snapshot),
            generator_version=GENERATOR_VERSION,
            seed=seed,
        )
        project.prediction_tasks.append(task)
        return task
```

- [ ] **Step 5: Run mock output tests**

Run:

```bash
python -m pytest tests/test_mock_outputs.py -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow/factors.py paleo_workbench/prediction tests/test_mock_outputs.py
git commit -m "feat: add deterministic mock factor and prediction services"
```

If root git is still invalid, record checkpoint: `Task 5 complete; root commit pending repository repair`.

---

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

### Task 8: UI Screen Inventory Artifact

**Files:**
- Create: `paleo_workbench/ui/__init__.py`
- Create: `paleo_workbench/ui/screen_inventory.py`
- Create: `docs/paleo_workbench_screen_inventory.md`
- Create: `tests/test_project_models.py` update for inventory import

**Interfaces:**
- Produces: `SCREEN_INVENTORY`
- Produces: human-readable inventory document used by UI implementation

- [ ] **Step 1: Write failing inventory import test**

Append to `tests/test_project_models.py`:

```python
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY


def test_screen_inventory_includes_required_pages():
    page_ids = {page["id"] for page in SCREEN_INVENTORY["pages"]}

    assert {"dashboard", "data", "visualization", "preparation", "prediction", "paleomap", "qc_export"} <= page_ids
```

- [ ] **Step 2: Run inventory test to verify it fails**

Run:

```bash
python -m pytest tests/test_project_models.py::test_screen_inventory_includes_required_pages -v
```

Expected: FAIL with missing `paleo_workbench.ui`.

- [ ] **Step 3: Implement inventory module**

Create `paleo_workbench/ui/__init__.py`:

```python
from paleo_workbench.ui.screen_inventory import SCREEN_INVENTORY

__all__ = ["SCREEN_INVENTORY"]
```

Create `paleo_workbench/ui/screen_inventory.py`:

```python
SCREEN_INVENTORY = {
    "source": "古地理图编制系统 (standalone).html",
    "tokens": {
        "primary": "#1f6fe0",
        "accent": "#6f47cf",
        "success": "#1f9d57",
        "warning": "#c47e12",
        "surface": "#ffffff",
        "background": "#eef2f7",
    },
    "pages": [
        {"id": "dashboard", "title": "工程工作台", "purpose": "编图任务总览与运行入口"},
        {"id": "data", "title": "多源数据管理与转换", "purpose": "资源扫描、导入、分类、状态管理"},
        {"id": "visualization", "title": "数据可视化", "purpose": "测井、地震、连井、参考资料回溯"},
        {"id": "preparation", "title": "制图数据制备", "purpose": "单因素图任务管理与预览"},
        {"id": "prediction", "title": "沉积相预测", "purpose": "预测任务、证据贡献、待复核区"},
        {"id": "paleomap", "title": "古地理图编制", "purpose": "相带草图、人工编辑、图例样式"},
        {"id": "qc_export", "title": "质控与导出", "purpose": "规则检查、问题处理、成果导出"},
    ],
}
```

- [ ] **Step 4: Create inventory document**

Create `docs/paleo_workbench_screen_inventory.md`:

```markdown
# Paleogeography Workbench Screen Inventory

Source: `古地理图编制系统 (standalone).html`

## Pages

- 工程工作台: target horizon, sequence scheme, resource completeness, factor map status, prediction status, QC blockers, export artifacts.
- 多源数据管理与转换: resource categories, format/status table, conversion options, queue.
- 数据可视化: well log, seismic, cross-well, well-tie, reference document previews.
- 制图数据制备: factor map task cards, map preview, interpolation/method metadata.
- 沉积相预测: input selectors, mock/service adapter status, probability/evidence panels, review areas.
- 古地理图编制: facies polygons, well overlay, legend, north arrow, scale bar, coordinate/grid display.
- 质控与导出: QC rules, issue table, export formats, artifact summary.

## Design Tokens

- Primary: `#1f6fe0`
- Accent: `#6f47cf`
- Success: `#1f9d57`
- Warning: `#c47e12`
- Surface: `#ffffff`
- Background: `#eef2f7`
```

- [ ] **Step 5: Run inventory tests**

Run:

```bash
python -m pytest tests/test_project_models.py::test_screen_inventory_includes_required_pages -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/ui docs/paleo_workbench_screen_inventory.md tests/test_project_models.py
git commit -m "docs: add paleogeography workbench screen inventory"
```

If root git is still invalid, record checkpoint: `Task 8 complete; root commit pending repository repair`.

---

### Task 9: Workflow Dashboard Widget

**Files:**
- Create: `paleo_workbench/ui/dashboard.py`
- Modify: `paleo_workbench/app.py`
- Modify: `paleo_workbench/main.py`
- Create: `tests/test_integration_smoke.py`

**Interfaces:**
- Consumes: `dashboard_state(project) -> dict[str, object]`
- Produces: `WorkflowDashboard(QWidget)`
- Produces: `PaleoWorkbenchWindow(QWidget)`

- [ ] **Step 1: Write failing dashboard smoke test**

Create `tests/test_integration_smoke.py`:

```python
from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument


def test_dashboard_window_shows_project_name(qtbot):
    project = ProjectDocument.new(name="HZ26 Demo")
    window = PaleoWorkbenchWindow(project)
    qtbot.addWidget(window)

    assert "HZ26 Demo" in window.windowTitle()
    assert window.dashboard.project_name_label.text() == "HZ26 Demo"
```

- [ ] **Step 2: Run dashboard test to verify it fails**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_dashboard_window_shows_project_name -v
```

Expected: FAIL with missing `paleo_workbench.app`.

- [ ] **Step 3: Implement dashboard widget**

Create `paleo_workbench/ui/dashboard.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class WorkflowDashboard(QWidget):
    def __init__(self, state: dict[str, object], parent=None):
        super().__init__(parent)
        self.project_name_label = QLabel(str(state.get("project_name", "")))
        self.target_label = QLabel(f"目标层位: {state.get('active_target_horizon') or '未设置'}")
        self.status_label = QLabel(f"流程状态: {state.get('workflow_status', 'draft')}")
        self.summary = QLabel(
            f"资源 {sum(state.get('resource_counts', {}).values())} · "
            f"单因素图 {state.get('factor_map_count', 0)} · "
            f"预测 {state.get('prediction_count', 0)} · "
            f"QC问题 {state.get('qc_issue_count', 0)} · "
            f"导出 {state.get('export_count', 0)}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        title_card = QFrame()
        title_card.setStyleSheet("QFrame { background: #ffffff; border: 1px solid #d8dee6; border-radius: 12px; }")
        card_layout = QVBoxLayout(title_card)
        for widget in [self.project_name_label, self.target_label, self.status_label, self.summary]:
            card_layout.addWidget(widget)
        layout.addWidget(title_card)
        layout.addStretch()
```

- [ ] **Step 4: Implement main window**

Create `paleo_workbench/app.py`:

```python
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.dashboard import WorkflowDashboard
from paleo_workbench.workflow.service import dashboard_state


class PaleoWorkbenchWindow(QWidget):
    def __init__(self, project: ProjectDocument | None = None):
        super().__init__()
        self.project = project or ProjectDocument.new("Untitled Project")
        self.setWindowTitle(f"{self.project.meta.name} - Paleogeography Workbench")
        self.resize(1280, 820)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.dashboard = WorkflowDashboard(dashboard_state(self.project))
        layout.addWidget(self.dashboard)
```

Modify `paleo_workbench/main.py`:

```python
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from paleo_workbench.app import PaleoWorkbenchWindow


def main() -> int:
    app = QApplication(sys.argv)
    window = PaleoWorkbenchWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run dashboard smoke test**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_dashboard_window_shows_project_name -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/app.py paleo_workbench/main.py paleo_workbench/ui/dashboard.py tests/test_integration_smoke.py
git commit -m "feat: add workflow dashboard shell"
```

If root git is still invalid, record checkpoint: `Task 9 complete; root commit pending repository repair`.

---

### Task 10: QC And Export Artifact Records

**Files:**
- Create: `paleo_workbench/workflow/qc.py`
- Create: `paleo_workbench/workflow/export.py`
- Modify: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: `ProjectDocument`, `PaleoMapDocument`, `QualityReport`, `ExportArtifact`
- Produces: `run_basic_qc(project, map_document_id) -> QualityReport`
- Produces: `record_export(project, linked_id, output_path, fmt, source_task_ids) -> ExportArtifact`

- [ ] **Step 1: Write failing QC/export tests**

Append to `tests/test_workflow_service.py`:

```python
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.qc import run_basic_qc


def test_qc_warns_when_map_has_no_polygons():
    project = ProjectDocument.new("Demo")
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2")
    project.paleomap_documents.append(doc)

    report = run_basic_qc(project, doc.id)

    assert report.status == "warning"
    assert report.issues[0]["rule"] == "facies_polygons_present"


def test_record_export_adds_artifact():
    project = ProjectDocument.new("Demo")

    artifact = record_export(project, "map_1", "exports/map.geojson", "geojson", ["pred_1"])

    assert project.export_artifacts == [artifact]
    assert artifact.format == "geojson"
    assert artifact.source_task_ids == ["pred_1"]
```

- [ ] **Step 2: Run QC/export tests to verify they fail**

Run:

```bash
python -m pytest tests/test_workflow_service.py::test_qc_warns_when_map_has_no_polygons tests/test_workflow_service.py::test_record_export_adds_artifact -v
```

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement QC service**

Create `paleo_workbench/workflow/qc.py`:

```python
from __future__ import annotations

from paleo_workbench.project.models import ProjectDocument, QualityReport


def run_basic_qc(project: ProjectDocument, map_document_id: str) -> QualityReport:
    document = next(doc for doc in project.paleomap_documents if doc.id == map_document_id)
    issues: list[dict] = []
    if not document.facies_polygons:
        issues.append(
            {
                "rule": "facies_polygons_present",
                "severity": "warning",
                "message": "古地理图尚无相带多边形",
            }
        )
    if not document.linked_target_horizon:
        issues.append(
            {
                "rule": "target_horizon_present",
                "severity": "error",
                "message": "古地理图未关联目标层位",
            }
        )
    report = QualityReport(
        linked_map_document_id=map_document_id,
        rules=["facies_polygons_present", "target_horizon_present"],
        issues=issues,
        status="pass" if not issues else "warning",
    )
    project.quality_reports.append(report)
    return report
```

- [ ] **Step 4: Implement export record service**

Create `paleo_workbench/workflow/export.py`:

```python
from __future__ import annotations

from paleo_workbench.project.models import ExportArtifact, ProjectDocument


def record_export(
    project: ProjectDocument,
    linked_id: str,
    output_path: str,
    fmt: str,
    source_task_ids: list[str],
) -> ExportArtifact:
    artifact = ExportArtifact(
        linked_id=linked_id,
        format=fmt,
        output_path=output_path,
        included_map_elements=["legend", "north_arrow", "scale_bar"],
        source_task_ids=source_task_ids,
    )
    project.export_artifacts.append(artifact)
    return artifact
```

- [ ] **Step 5: Run QC/export tests**

Run:

```bash
python -m pytest tests/test_workflow_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Checkpoint or commit**

If root git is repaired, run:

```bash
git add paleo_workbench/workflow/qc.py paleo_workbench/workflow/export.py tests/test_workflow_service.py
git commit -m "feat: add qc and export artifact records"
```

If root git is still invalid, record checkpoint: `Task 10 complete; root commit pending repository repair`.

---

### Task 11: End-To-End MVP Smoke Path

**Files:**
- Modify: `tests/test_integration_smoke.py`

**Interfaces:**
- Consumes all services from Tasks 2-10
- Produces executable proof of MVP success criteria

- [ ] **Step 1: Add failing full-loop smoke test**

Append to `tests/test_integration_smoke.py`:

```python
from pathlib import Path

from paleo_workbench.adapters.paleo_map import PaleoMapAdapter
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.factors import create_mock_factor_map
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_full_mvp_loop_recovers_dashboard_state(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "A1.Las").write_text("~Version\n", encoding="utf-8")
    project_path = tmp_path / "demo.paleo.json"

    project = ProjectDocument.new("Demo")
    project.resources = scan_resources(data_root, project_path=project_path)
    run = create_compilation_run(project, "ZJ2 Run", "ZJ2", "三级层序格架")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    pred = MockPredictionAdapter().run(project, [factor.id], seed=7)
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2", linked_prediction_task_id=pred.id)
    project.paleomap_documents.append(doc)
    qc = run_basic_qc(project, doc.id)

    adapter = PaleoMapAdapter()
    adapter.set_data({"viewer_type": "paleo_map", "schema_version": "1.0", "resources": [], "layers": []})
    export_path = tmp_path / "demo.artifacts" / "exports" / "map.geojson"
    result = adapter.export({"path": str(export_path), "format": "geojson"})
    artifact = record_export(project, doc.id, result.output_path, result.format, [pred.id, qc.id])
    run.active_factor_map_task_ids = [factor.id]
    run.active_prediction_task_id = pred.id
    run.active_paleomap_document_id = doc.id
    run.active_quality_report_id = qc.id
    run.export_artifact_ids = [artifact.id]

    ProjectManager(project_path).save(project)
    loaded = ProjectManager(project_path).load()
    state = dashboard_state(loaded)

    assert state["project_name"] == "Demo"
    assert state["active_target_horizon"] == "ZJ2"
    assert state["factor_map_count"] == 1
    assert state["prediction_count"] == 1
    assert state["export_count"] == 1
```

- [ ] **Step 2: Run full-loop test to verify it passes or exposes integration defects**

Run:

```bash
python -m pytest tests/test_integration_smoke.py::test_full_mvp_loop_recovers_dashboard_state -v
```

Expected: PASS. If it fails, fix only the integration defect exposed by the assertion or traceback, then rerun the same test.

- [ ] **Step 3: Run full MVP test suite**

Run:

```bash
python -m pytest tests -v
```

Expected: PASS for all root `tests/`.

- [ ] **Step 4: Checkpoint or commit**

If root git is repaired, run:

```bash
git add tests/test_integration_smoke.py
git commit -m "test: add paleogeography workbench mvp smoke path"
```

If root git is still invalid, record checkpoint: `Task 11 complete; root commit pending repository repair`.

---

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
