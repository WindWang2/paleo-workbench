# Review package: Task 2 (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated from current Task 2 files. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/project/__init__.py
paleo_workbench/project/models.py
paleo_workbench/project/paths.py
paleo_workbench/project/manager.py
tests/test_project_models.py
tests/test_project_manager.py

## Implementer report
# Task 2 Report

## Scope

Implemented Task 2 only in the owned files:

- `paleo_workbench/project/__init__.py`
- `paleo_workbench/project/models.py`
- `paleo_workbench/project/paths.py`
- `paleo_workbench/project/manager.py`
- `tests/test_project_models.py`
- `tests/test_project_manager.py`

## TDD Evidence

### RED 1

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py::test_project_defaults_include_crs_and_empty_workflow -v
```

Result:

- Exit code `4`
- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.project'`

### GREEN 1

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py -v
```

Result:

- Exit code `0`
- `2 passed`

### RED 2

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py::test_project_round_trip_uses_relative_paths -v
```

Result:

- Exit code `4`
- Failed during collection with `ModuleNotFoundError: No module named 'paleo_workbench.project.manager'`

### GREEN 2

Command:

```bash
.venv/bin/python -m pytest tests/test_project_manager.py -v
```

Result:

- First run exposed a real implementation bug:
  - Exit code `1`
  - `artifact_dir_for()` produced `demo.paleo.artifacts` instead of required `demo.artifacts`
- After fixing artifact path derivation:
  - Exit code `0`
  - `1 passed`

## Final Verification

Command:

```bash
.venv/bin/python -m pytest tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- Exit code `0`
- `3 passed in 0.09s`

## Checkpoint

Command:

```bash
git rev-parse --show-toplevel
```

Result:

- Exit code `128`
- Expected failure: `fatal: not a git repository (or any of the parent directories): .git`
- Checkpoint recorded instead of commit: `Task 2 complete; root commit pending repository repair`

## Self-Review

- Verified `.paleo.json` artifact root resolves to `project-name.artifacts/`
- Verified in-project resource paths persist as relative POSIX paths
- Verified external flag remains `False` for project-local resources
- No commit created because root git is invalid


## paleo_workbench/project/__init__.py
     1	from paleo_workbench.project.models import (
     2	    CompilationRun,
     3	    CoordinateReference,
     4	    ExportArtifact,
     5	    FactorMapTask,
     6	    PaleoMapDocument,
     7	    PredictionTask,
     8	    ProjectDocument,
     9	    ProjectMeta,
    10	    QualityReport,
    11	    ResourceItem,
    12	    StratigraphicFramework,
    13	    WorkflowStep,
    14	)
    15	
    16	__all__ = [
    17	    "CompilationRun",
    18	    "CoordinateReference",
    19	    "ExportArtifact",
    20	    "FactorMapTask",
    21	    "PaleoMapDocument",
    22	    "PredictionTask",
    23	    "ProjectDocument",
    24	    "ProjectMeta",
    25	    "QualityReport",
    26	    "ResourceItem",
    27	    "StratigraphicFramework",
    28	    "WorkflowStep",
    29	]

## paleo_workbench/project/models.py
     1	from __future__ import annotations
     2	
     3	from datetime import datetime, timezone
     4	from typing import Any, Literal
     5	from uuid import uuid4
     6	
     7	from pydantic import BaseModel, Field
     8	
     9	
    10	def _now_iso() -> str:
    11	    return datetime.now(timezone.utc).isoformat()
    12	
    13	
    14	def _id(prefix: str) -> str:
    15	    return f"{prefix}_{uuid4().hex[:12]}"
    16	
    17	
    18	class ProjectMeta(BaseModel):
    19	    name: str
    20	    region: str = ""
    21	    version: str = "0.1.0"
    22	    created_at: str = Field(default_factory=_now_iso)
    23	    updated_at: str = Field(default_factory=_now_iso)
    24	    project_root: str = "."
    25	
    26	
    27	class CoordinateReference(BaseModel):
    28	    project_crs: str = "EPSG:4326"
    29	    target_crs: str | None = None
    30	    display_crs: str = "EPSG:4326"
    31	    transform_history: list[dict[str, Any]] = Field(default_factory=list)
    32	
    33	
    34	class StratigraphicFramework(BaseModel):
    35	    target_horizon: str = ""
    36	    sequence_boundaries: list[str] = Field(default_factory=list)
    37	    systems_tract_scheme: str = "LST/TST/HST"
    38	    interpretation_version: str = "v1"
    39	    applicable_wells: list[str] = Field(default_factory=list)
    40	    applicable_seismic_ranges: list[str] = Field(default_factory=list)
    41	
    42	
    43	class ResourceItem(BaseModel):
    44	    id: str = Field(default_factory=lambda: _id("res"))
    45	    name: str
    46	    path: str
    47	    type: str
    48	    format: str
    49	    crs: str | None = None
    50	    status: str = "indexed"
    51	    tags: list[str] = Field(default_factory=list)
    52	    source: str = "local"
    53	    parsed_summary: dict[str, Any] = Field(default_factory=dict)
    54	    checksum: str | None = None
    55	    external: bool = False
    56	    artifact_role: str | None = None
    57	
    58	
    59	class WorkflowStep(BaseModel):
    60	    id: str = Field(default_factory=lambda: _id("step"))
    61	    step_type: Literal[
    62	        "data_check",
    63	        "factor_map",
    64	        "prediction",
    65	        "map_compile",
    66	        "qc",
    67	        "export",
    68	    ]
    69	    status: Literal[
    70	        "pending",
    71	        "ready",
    72	        "running",
    73	        "complete",
    74	        "warning",
    75	        "failed",
    76	        "skipped",
    77	        "mock",
    78	    ] = "pending"
    79	    required_input_resource_ids: list[str] = Field(default_factory=list)
    80	    produced_ids: list[str] = Field(default_factory=list)
    81	    blocking_issue_summary: str = ""
    82	    provenance_summary: str = ""
    83	
    84	
    85	class CompilationRun(BaseModel):
    86	    id: str = Field(default_factory=lambda: _id("run"))
    87	    name: str
    88	    target_horizon: str
    89	    sequence_scheme_ref: str = ""
    90	    status: Literal[
    91	        "draft",
    92	        "running",
    93	        "blocked",
    94	        "review_required",
    95	        "export_ready",
    96	        "exported",
    97	        "failed",
    98	    ] = "draft"
    99	    workflow_steps: list[WorkflowStep] = Field(default_factory=list)
   100	    active_factor_map_task_ids: list[str] = Field(default_factory=list)
   101	    active_prediction_task_id: str | None = None
   102	    active_paleomap_document_id: str | None = None
   103	    active_quality_report_id: str | None = None
   104	    export_artifact_ids: list[str] = Field(default_factory=list)
   105	    created_at: str = Field(default_factory=_now_iso)
   106	    updated_at: str = Field(default_factory=_now_iso)
   107	
   108	
   109	class FactorMapTask(BaseModel):
   110	    id: str = Field(default_factory=lambda: _id("factor"))
   111	    name: str
   112	    target_horizon: str
   113	    factor_type: str
   114	    input_resource_ids: list[str] = Field(default_factory=list)
   115	    method: str
   116	    parameters: dict[str, Any] = Field(default_factory=dict)
   117	    output_resource_ids: list[str] = Field(default_factory=list)
   118	    quality_metrics: dict[str, Any] = Field(default_factory=dict)
   119	    status: str = "pending"
   120	    source_kind: Literal["real", "imported", "mock", "mixed"] = "mock"
   121	    input_snapshot_hash: str = ""
   122	    generator_version: str | None = None
   123	    seed: int | None = None
   124	
   125	
   126	class PredictionTask(BaseModel):
   127	    id: str = Field(default_factory=lambda: _id("pred"))
   128	    name: str
   129	    adapter_kind: Literal["mock", "http", "local"] = "mock"
   130	    input_factor_map_ids: list[str] = Field(default_factory=list)
   131	    input_refs: dict[str, list[str]] = Field(default_factory=dict)
   132	    model_metadata: dict[str, Any] = Field(default_factory=dict)
   133	    result_summary: dict[str, Any] = Field(default_factory=dict)
   134	    probability_summary: dict[str, Any] = Field(default_factory=dict)
   135	    evidence_contribution: list[dict[str, Any]] = Field(default_factory=list)
   136	    review_areas: list[dict[str, Any]] = Field(default_factory=list)
   137	    status: str = "pending"
   138	    adapter_schema_version: str = "1.0"
   139	    input_snapshot_hash: str = ""
   140	    generator_version: str | None = None
   141	    seed: int | None = None
   142	
   143	
   144	class PaleoMapDocument(BaseModel):
   145	    id: str = Field(default_factory=lambda: _id("map"))
   146	    name: str
   147	    linked_target_horizon: str
   148	    linked_prediction_task_id: str | None = None
   149	    facies_polygons: list[dict[str, Any]] = Field(default_factory=list)
   150	    facies_style: dict[str, Any] = Field(default_factory=dict)
   151	    well_overlays: list[dict[str, Any]] = Field(default_factory=list)
   152	    map_chrome: dict[str, Any] = Field(default_factory=dict)
   153	    view_state: dict[str, Any] = Field(default_factory=dict)
   154	    edit_history: list[dict[str, Any]] = Field(default_factory=list)
   155	
   156	
   157	class QualityReport(BaseModel):
   158	    id: str = Field(default_factory=lambda: _id("qc"))
   159	    linked_map_document_id: str
   160	    rules: list[str] = Field(default_factory=list)
   161	    issues: list[dict[str, Any]] = Field(default_factory=list)
   162	    status: str = "pending"
   163	    generated_at: str = Field(default_factory=_now_iso)
   164	
   165	
   166	class ExportArtifact(BaseModel):
   167	    id: str = Field(default_factory=lambda: _id("artifact"))
   168	    linked_id: str
   169	    format: str
   170	    output_path: str
   171	    options: dict[str, Any] = Field(default_factory=dict)
   172	    included_map_elements: list[str] = Field(default_factory=list)
   173	    generated_at: str = Field(default_factory=_now_iso)
   174	    source_task_ids: list[str] = Field(default_factory=list)
   175	
   176	
   177	class ProjectDocument(BaseModel):
   178	    meta: ProjectMeta
   179	    coordinate: CoordinateReference = Field(default_factory=CoordinateReference)
   180	    stratigraphy: StratigraphicFramework = Field(default_factory=StratigraphicFramework)
   181	    resources: list[ResourceItem] = Field(default_factory=list)
   182	    compilation_runs: list[CompilationRun] = Field(default_factory=list)
   183	    factor_map_tasks: list[FactorMapTask] = Field(default_factory=list)
   184	    prediction_tasks: list[PredictionTask] = Field(default_factory=list)
   185	    paleomap_documents: list[PaleoMapDocument] = Field(default_factory=list)
   186	    quality_reports: list[QualityReport] = Field(default_factory=list)
   187	    export_artifacts: list[ExportArtifact] = Field(default_factory=list)
   188	
   189	    @classmethod
   190	    def new(cls, name: str, region: str = "") -> "ProjectDocument":
   191	        return cls(meta=ProjectMeta(name=name, region=region))

## paleo_workbench/project/paths.py
     1	from __future__ import annotations
     2	
     3	from pathlib import Path
     4	
     5	
     6	def artifact_dir_for(project_path: Path) -> Path:
     7	    project_name = project_path.name.removesuffix(".paleo.json")
     8	    return project_path.with_name(f"{project_name}.artifacts")
     9	
    10	
    11	def ensure_artifact_layout(project_path: Path) -> Path:
    12	    root = artifact_dir_for(project_path)
    13	    for name in [
    14	        "cache",
    15	        "factor_maps",
    16	        "predictions",
    17	        "paleomaps",
    18	        "qc",
    19	        "exports",
    20	        "thumbnails",
    21	    ]:
    22	        (root / name).mkdir(parents=True, exist_ok=True)
    23	    return root
    24	
    25	
    26	def relativize_path(path: str, project_path: Path) -> tuple[str, bool]:
    27	    resolved = Path(path).resolve()
    28	    project_dir = project_path.parent.resolve()
    29	    try:
    30	        return resolved.relative_to(project_dir).as_posix(), False
    31	    except ValueError:
    32	        return resolved.as_posix(), True

## paleo_workbench/project/manager.py
     1	from __future__ import annotations
     2	
     3	import json
     4	from pathlib import Path
     5	
     6	from paleo_workbench.project.models import ProjectDocument
     7	from paleo_workbench.project.paths import ensure_artifact_layout, relativize_path
     8	
     9	
    10	class ProjectManager:
    11	    def __init__(self, project_path: str | Path):
    12	        self.project_path = Path(project_path)
    13	
    14	    def save(self, project: ProjectDocument) -> None:
    15	        data = project.model_dump()
    16	        for resource in data["resources"]:
    17	            path, external = relativize_path(resource["path"], self.project_path)
    18	            resource["path"] = path
    19	            resource["external"] = external
    20	        self.project_path.parent.mkdir(parents=True, exist_ok=True)
    21	        ensure_artifact_layout(self.project_path)
    22	        self.project_path.write_text(
    23	            json.dumps(data, ensure_ascii=False, indent=2),
    24	            encoding="utf-8",
    25	        )
    26	
    27	    def load(self) -> ProjectDocument:
    28	        data = json.loads(self.project_path.read_text(encoding="utf-8"))
    29	        return ProjectDocument.model_validate(data)

## tests/test_project_models.py
     1	from paleo_workbench.project.models import ProjectDocument
     2	
     3	
     4	def test_package_imports():
     5	    import paleo_workbench
     6	
     7	    assert paleo_workbench.__version__ == "0.1.0"
     8	
     9	
    10	def test_project_defaults_include_crs_and_empty_workflow():
    11	    project = ProjectDocument.new(name="HZ26 Demo", region="惠州26区")
    12	
    13	    assert project.meta.name == "HZ26 Demo"
    14	    assert project.meta.region == "惠州26区"
    15	    assert project.coordinate.project_crs == "EPSG:4326"
    16	    assert project.resources == []
    17	    assert project.compilation_runs == []

## tests/test_project_manager.py
     1	from pathlib import Path
     2	
     3	from paleo_workbench.project.manager import ProjectManager
     4	from paleo_workbench.project.models import ProjectDocument, ResourceItem
     5	from paleo_workbench.project.paths import artifact_dir_for
     6	
     7	
     8	def test_project_round_trip_uses_relative_paths(tmp_path: Path):
     9	    project_path = tmp_path / "demo.paleo.json"
    10	    data_file = tmp_path / "data" / "well.las"
    11	    data_file.parent.mkdir()
    12	    data_file.write_text("~Version\n", encoding="utf-8")
    13	
    14	    project = ProjectDocument.new(name="Demo")
    15	    project.resources.append(
    16	        ResourceItem(
    17	            name="well.las",
    18	            path=str(data_file),
    19	            type="well_log",
    20	            format="las",
    21	            status="indexed",
    22	        )
    23	    )
    24	
    25	    manager = ProjectManager(project_path)
    26	    manager.save(project)
    27	    loaded = manager.load()
    28	
    29	    assert loaded.resources[0].path == "data/well.las"
    30	    assert loaded.resources[0].external is False
    31	    assert artifact_dir_for(project_path) == tmp_path / "demo.artifacts"
