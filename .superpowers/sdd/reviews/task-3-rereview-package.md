# Review package: Task 3 re-review (no git root)

## Environment
Root git is invalid; no BASE/HEAD SHA is available. Package generated after Task 3 review fixes. Python baseline: .venv CPython 3.12.13.

## Files changed
paleo_workbench/resources/__init__.py
paleo_workbench/resources/classifier.py
paleo_workbench/resources/scanner.py
tests/test_resource_scanner.py

## Implementer and fix report
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

---

## Task 3 Review Fixes

### Findings Addressed

- Fixed `scan_resources(..., project_path=None)` so scanned resources now retain their canonical absolute source path instead of being rewritten relative to the scan root.
- Preserved existing Task 2 semantics when `project_path` is provided by continuing to route stored path and `external` handling through `relativize_path`.
- Added checksum coverage that fails if the scanner emits `checksum=None` or an incorrect SHA-256 digest for a known file payload.
- Tightened scanner assertions for `format`, `parsed_summary["size_bytes"]`, and `indexed_reference` behavior across representative well-log, document, image, and reference cases.

### RED Evidence

Ran before the production fix:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Observed the expected regression failure:

- `test_scan_resources_without_project_path_preserves_canonical_source_path`
- actual path: `logs/A1.Las`
- expected path: absolute canonical file path under the temp directory

This isolated the root cause to the scanner's default `path.relative_to(root)` behavior.

### GREEN Verification

Focused scanner suite:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py -v
```

Result:

- `5 passed`

Required verification suite:

```bash
.venv/bin/python -m pytest tests/test_resource_scanner.py tests/test_project_models.py tests/test_project_manager.py -v
```

Result:

- `11 passed`

Repository root check:

```bash
git rev-parse --show-toplevel
```

Observed expected failure:

- `fatal: not a git repository (or any of the parent directories): .git`


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
    27	        resolved_path = path.resolve()
    28	        stored_path = resolved_path.as_posix()
    29	        external = False
    30	
    31	        if project_path is not None:
    32	            stored_path, external = relativize_path(str(path), project_path)
    33	
    34	        resources.append(
    35	            ResourceItem(
    36	                name=path.name,
    37	                path=stored_path,
    38	                type=resource_type,
    39	                format=resource_format,
    40	                status=status,
    41	                source="scan",
    42	                parsed_summary={"size_bytes": resolved_path.stat().st_size},
    43	                checksum=_checksum(path),
    44	                external=external,
    45	            )
    46	        )
    47	
    48	    return resources

## tests/test_resource_scanner.py
     1	import hashlib
     2	from pathlib import Path
     3	
     4	from paleo_workbench.resources.classifier import classify_path
     5	from paleo_workbench.resources.scanner import scan_resources
     6	
     7	
     8	def test_classify_known_and_reference_formats():
     9	    assert classify_path(Path("A1.Las")) == ("well_log", "las", "indexed")
    10	    assert classify_path(Path("200P_seismic.sgy")) == ("seismic", "sgy", "indexed")
    11	    assert classify_path(Path("C6.dat")) == ("tabular", "dat", "indexed")
    12	    assert classify_path(Path("相图.dfb")) == ("reference_map", "dfb", "indexed_reference")
    13	    assert classify_path(Path("综合柱状图.WLP")) == (
    14	        "well_reference",
    15	        "wlp",
    16	        "indexed_reference",
    17	    )
    18	
    19	
    20	def test_scan_resources_indexes_nested_data(tmp_path: Path):
    21	    (tmp_path / "井曲线").mkdir()
    22	    (tmp_path / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    23	    (tmp_path / "外委资料").mkdir()
    24	    (tmp_path / "外委资料" / "相图.dfb").write_text("binary-like", encoding="utf-8")
    25	
    26	    resources = scan_resources(tmp_path)
    27	
    28	    assert [resource.name for resource in resources] == ["A1.Las", "相图.dfb"]
    29	    assert resources[0].type == "well_log"
    30	    assert resources[0].format == "las"
    31	    assert resources[0].parsed_summary["size_bytes"] == len("~Version\n".encode("utf-8"))
    32	    assert resources[1].status == "indexed_reference"
    33	    assert resources[1].format == "dfb"
    34	    assert resources[1].parsed_summary["size_bytes"] == len("binary-like".encode("utf-8"))
    35	
    36	
    37	def test_scan_resources_without_project_path_preserves_canonical_source_path(tmp_path: Path):
    38	    source_file = tmp_path / "external" / "logs" / "A1.Las"
    39	    source_file.parent.mkdir(parents=True)
    40	    content = "~Version\n"
    41	    source_file.write_text(content, encoding="utf-8")
    42	
    43	    resources = scan_resources(tmp_path / "external")
    44	
    45	    assert len(resources) == 1
    46	    assert resources[0].path == source_file.resolve().as_posix()
    47	    assert resources[0].external is False
    48	    assert resources[0].checksum == hashlib.sha256(content.encode("utf-8")).hexdigest()
    49	
    50	
    51	def test_scan_resources_relativizes_paths_and_skips_macos_sidecars(tmp_path: Path):
    52	    project_path = tmp_path / "demo.paleo.json"
    53	    data_dir = tmp_path / "data" / "外委资料"
    54	    data_dir.mkdir(parents=True)
    55	    (data_dir / "03-惠西南区域构造图.pptx").write_text("ppt", encoding="utf-8")
    56	    (data_dir / "._03-惠西南区域构造图.pptx").write_text("sidecar", encoding="utf-8")
    57	
    58	    resources = scan_resources(tmp_path / "data", project_path=project_path)
    59	
    60	    assert len(resources) == 1
    61	    assert resources[0].path == "data/外委资料/03-惠西南区域构造图.pptx"
    62	    assert resources[0].external is False
    63	    assert resources[0].status == "indexed_reference"
    64	    assert resources[0].format == "pptx"
    65	    assert resources[0].source == "scan"
    66	    assert resources[0].parsed_summary["size_bytes"] == len("ppt".encode("utf-8"))
    67	
    68	
    69	def test_scan_resources_computes_checksum_for_reference_image(tmp_path: Path):
    70	    project_path = tmp_path / "demo.paleo.json"
    71	    image_file = tmp_path / "data" / "图件" / "剖面图.png"
    72	    image_file.parent.mkdir(parents=True)
    73	    payload = b"fake-png-bytes"
    74	    image_file.write_bytes(payload)
    75	
    76	    resources = scan_resources(tmp_path / "data", project_path=project_path)
    77	
    78	    assert len(resources) == 1
    79	    assert resources[0].status == "indexed_reference"
    80	    assert resources[0].format == "png"
    81	    assert resources[0].checksum == hashlib.sha256(payload).hexdigest()
