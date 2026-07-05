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

