# Review package: Task 3 (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated from current Task 3 files. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/resources/__init__.py
paleo_workbench/resources/classifier.py
paleo_workbench/resources/scanner.py
tests/test_resource_scanner.py

## Implementer report
# Task 3 Report: Resource Scanner And Format Classifier

## Scope

Implemented Task 3 in the owned files:

- `paleo_workbench/resources/__init__.py`
- `paleo_workbench/resources/classifier.py`
- `paleo_workbench/resources/scanner.py`
- `tests/test_resource_scanner.py`

## TDD Evidence

### RED

Added `tests/test_resource_scanner.py` first, then ran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Observed expected failure:

- `ModuleNotFoundError: No module named 'paleo_workbench.resources'`

This confirmed the test was exercising missing Task 3 functionality rather than passing against existing behavior.

### GREEN

Implemented the minimal resource package:

- `classify_path(path: Path) -> tuple[str, str, str]`
- `scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]`

Then reran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Result:

- `3 passed`

## Implementation Notes

- Known indexed formats:
  - `las` -> `well_log`
  - `sgy`/`segy` -> `seismic`
  - `dat` -> `tabular`, with path-based special cases for `time_depth`, `horizon`, and `well_stratification`
  - `xlsx`/`xls`/`xml` -> `spreadsheet`
- Unsupported or proprietary/reference-oriented formats are indexed with `status=indexed_reference`
  - `dfb` or filenames containing `相图` -> `reference_map`
  - `wlp` -> `well_reference`
  - `pdf`/`ppt`/`pptx` -> `document`
  - `png`/`jpg`/`jpeg`/`tif`/`tiff` -> `image_reference`
  - unknown extensions -> `unknown`
- Scanner emits `ResourceItem` records compatible with Task 2:
  - `source="scan"`
  - `parsed_summary={"size_bytes": ...}`
  - `checksum=<sha256>`
  - `external` determined through Task 2 path relativization when `project_path` is provided
- Scanner skips macOS sidecar files prefixed with `._`

## Focused Sample Scan

Ran:

```bash
.venv/bin/python -c "from pathlib import Path; from paleo_workbench.resources.scanner import scan_resources; items = scan_resources(Path('data')); print(len(items)); print(sorted({item.format for item in items})[:10])"
```

Observed concise result:

- resource count: `200`
- first formats: `['dat', 'dfb', 'jpg', 'las', 'pdf', 'png', 'pptx', 'sgy', 'wlp', 'xls']`

## Required Verification

Ran:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- `9 passed`

## Checkpoint

Ran:

```bash
git rev-parse --show-toplevel
```

Observed expected repository failure:

- `fatal: not a git repository (or any of the parent directories): .git`

Checkpoint recorded instead of commit:

- `Task 3 complete; root commit pending repository repair`

## Self-Review

- Kept changes scoped to the Task 3 owned files.
- Preserved Task 2 path semantics by delegating project-relative/external handling to `relativize_path`.
- Kept unsupported/proprietary resources indexed as references rather than attempting parsing.
- No commit created because root git is invalid.


## paleo_workbench/resources/__init__.py
     1	from paleo_workbench.resources.scanner import scan_resources
     2	
     3	__all__ = ["scan_resources"]

## paleo_workbench/resources/classifier.py
     1	from __future__ import annotations
     2	
     3	from pathlib import Path
     4	
     5	
     6	def classify_path(path: Path) -> tuple[str, str, str]:
     7	    ext = path.suffix.lower().lstrip(".")
     8	    name = path.name.lower()
     9	    path_parts = tuple(part.lower() for part in path.parts)
    10	
    11	    if ext == "las":
    12	        return "well_log", ext, "indexed"
    13	
    14	    if ext in {"sgy", "segy"}:
    15	        return "seismic", ext, "indexed"
    16	
    17	    if ext == "dat":
    18	        if "td" in path_parts or any("时深" in part for part in path_parts):
    19	            return "time_depth", ext, "indexed"
    20	        if any("层位" in part for part in path_parts):
    21	            return "horizon", ext, "indexed"
    22	        if any("井分层" in part for part in path_parts):
    23	            return "well_stratification", ext, "indexed"
    24	        return "tabular", ext, "indexed"
    25	
    26	    if ext in {"xlsx", "xls", "xml"}:
    27	        return "spreadsheet", ext, "indexed"
    28	
    29	    if ext in {"pdf", "ppt", "pptx"}:
    30	        return "document", ext, "indexed_reference"
    31	
    32	    if ext in {"png", "jpg", "jpeg", "tif", "tiff"}:
    33	        return "image_reference", ext, "indexed_reference"
    34	
    35	    if ext == "dfb" or "相图" in name:
    36	        return "reference_map", ext or "unknown", "indexed_reference"
    37	
    38	    if ext == "wlp":
    39	        return "well_reference", ext, "indexed_reference"
    40	
    41	    return "unknown", ext or "none", "indexed_reference"

## paleo_workbench/resources/scanner.py
     1	from __future__ import annotations
     2	
     3	import hashlib
     4	from pathlib import Path
     5	
     6	from paleo_workbench.project.models import ResourceItem
     7	from paleo_workbench.project.paths import relativize_path
     8	from paleo_workbench.resources.classifier import classify_path
     9	
    10	
    11	def _checksum(path: Path) -> str:
    12	    digest = hashlib.sha256()
    13	    with path.open("rb") as handle:
    14	        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
    15	            digest.update(chunk)
    16	    return digest.hexdigest()
    17	
    18	
    19	def scan_resources(root: Path, project_path: Path | None = None) -> list[ResourceItem]:
    20	    resources: list[ResourceItem] = []
    21	
    22	    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
    23	        if path.name.startswith("._"):
    24	            continue
    25	
    26	        resource_type, resource_format, status = classify_path(path)
    27	        stored_path = path.relative_to(root).as_posix()
    28	        external = False
    29	
    30	        if project_path is not None:
    31	            stored_path, external = relativize_path(str(path), project_path)
    32	
    33	        resources.append(
    34	            ResourceItem(
    35	                name=path.name,
    36	                path=stored_path,
    37	                type=resource_type,
    38	                format=resource_format,
    39	                status=status,
    40	                source="scan",
    41	                parsed_summary={"size_bytes": path.stat().st_size},
    42	                checksum=_checksum(path),
    43	                external=external,
    44	            )
    45	        )
    46	
    47	    return resources

## tests/test_resource_scanner.py
     1	from pathlib import Path
     2	
     3	from paleo_workbench.resources.classifier import classify_path
     4	from paleo_workbench.resources.scanner import scan_resources
     5	
     6	
     7	def test_classify_known_and_reference_formats():
     8	    assert classify_path(Path("A1.Las")) == ("well_log", "las", "indexed")
     9	    assert classify_path(Path("200P_seismic.sgy")) == ("seismic", "sgy", "indexed")
    10	    assert classify_path(Path("C6.dat")) == ("tabular", "dat", "indexed")
    11	    assert classify_path(Path("相图.dfb")) == ("reference_map", "dfb", "indexed_reference")
    12	    assert classify_path(Path("综合柱状图.WLP")) == (
    13	        "well_reference",
    14	        "wlp",
    15	        "indexed_reference",
    16	    )
    17	
    18	
    19	def test_scan_resources_indexes_nested_data(tmp_path: Path):
    20	    (tmp_path / "井曲线").mkdir()
    21	    (tmp_path / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    22	    (tmp_path / "外委资料").mkdir()
    23	    (tmp_path / "外委资料" / "相图.dfb").write_text("binary-like", encoding="utf-8")
    24	
    25	    resources = scan_resources(tmp_path)
    26	
    27	    assert [resource.name for resource in resources] == ["A1.Las", "相图.dfb"]
    28	    assert resources[0].type == "well_log"
    29	    assert resources[1].status == "indexed_reference"
    30	
    31	
    32	def test_scan_resources_relativizes_paths_and_skips_macos_sidecars(tmp_path: Path):
    33	    project_path = tmp_path / "demo.paleo.json"
    34	    data_dir = tmp_path / "data" / "外委资料"
    35	    data_dir.mkdir(parents=True)
    36	    (data_dir / "03-惠西南区域构造图.pptx").write_text("ppt", encoding="utf-8")
    37	    (data_dir / "._03-惠西南区域构造图.pptx").write_text("sidecar", encoding="utf-8")
    38	
    39	    resources = scan_resources(tmp_path / "data", project_path=project_path)
    40	
    41	    assert len(resources) == 1
    42	    assert resources[0].path == "data/外委资料/03-惠西南区域构造图.pptx"
    43	    assert resources[0].external is False
    44	    assert resources[0].status == "indexed_reference"
    45	    assert resources[0].source == "scan"
