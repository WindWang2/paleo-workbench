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

