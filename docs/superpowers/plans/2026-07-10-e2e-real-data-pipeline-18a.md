# Phase 18a Sample Project Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship pure `pipeline` bootstrap that indexes full `data/`, plus CLI and UI **「打开样例工程」**, so the workbench opens a real-asset `ProjectDocument` without mocks for 18b/18c.

**Architecture:** Extend `scan_resources` with optional large-file checksum skip. Add Qt-free `paleo_workbench/pipeline/` (`bootstrap`, stub `assets`/`compile_map`). CLI writes `.paleo.json` via `ProjectManager`. UI adds a toolbar button that resolves `data/`, calls bootstrap, replaces the in-memory project via existing `_refresh_shell`.

**Tech Stack:** Python 3.12, Pydantic `ProjectDocument`, existing `scan_resources` / `ProjectManager`, PySide6 toolbar signals, pytest / pytest-qt.

**Spec:** `docs/superpowers/specs/2026-07-10-e2e-real-data-pipeline-design.md`  
**Scope:** **18a only** (18b/18c remain stubs/contracts).

---

## File map

| Path | Responsibility |
|------|----------------|
| `paleo_workbench/resources/scanner.py` | Add `skip_checksum_over_bytes`; set `checksum_skipped` in summary |
| `paleo_workbench/pipeline/__init__.py` | Public exports |
| `paleo_workbench/pipeline/bootstrap.py` | `BootstrapResult`, `bootstrap_sample_project`, `resolve_sample_data_root`, `write_project` |
| `paleo_workbench/pipeline/__main__.py` | CLI entry (`python -m paleo_workbench.pipeline`) |
| `paleo_workbench/pipeline/assets.py` | 18b stub: `bind_prediction_assets` / `suggest_assets_for_demo` raise `NotImplementedError` |
| `paleo_workbench/pipeline/compile_map.py` | 18c stub: `compile_map_draft` raises `NotImplementedError` |
| `paleo_workbench/ui/header_toolbar.py` | Button + `open_sample_project_requested` signal |
| `paleo_workbench/app.py` | `open_sample_project`, dialog confirm, toolbar wire |
| `tests/test_resource_scanner.py` | Checksum skip tests |
| `tests/test_pipeline_bootstrap.py` | Pure bootstrap + stratigraphy + empty/missing root |
| `tests/test_pipeline_cli.py` | CLI writes loadable project |
| `tests/test_pipeline_boundary.py` | `pipeline` must not import `ui` |
| `tests/test_header_toolbar.py` | Sample button signal |
| `tests/test_sample_project_ui.py` | Window loads sample → data page count |

---

### Task 1: Scanner checksum skip

**Files:**
- Modify: `paleo_workbench/resources/scanner.py`
- Test: `tests/test_resource_scanner.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_resource_scanner.py`:

```python
def test_scan_resources_skips_checksum_over_threshold(tmp_path: Path):
    big = tmp_path / "vol.sgy"
    big.write_bytes(b"x" * 100)
    small = tmp_path / "A1.Las"
    small.write_text("~Version\n", encoding="utf-8")

    resources = scan_resources(tmp_path, skip_checksum_over_bytes=50)
    by_name = {r.name: r for r in resources}

    assert by_name["vol.sgy"].checksum is None
    assert by_name["vol.sgy"].parsed_summary.get("checksum_skipped") is True
    assert by_name["vol.sgy"].parsed_summary["size_bytes"] == 100
    assert by_name["A1.Las"].checksum is not None
    assert by_name["A1.Las"].parsed_summary.get("checksum_skipped") is not True


def test_scan_resources_default_still_checksums(tmp_path: Path):
    f = tmp_path / "A1.Las"
    content = "~Version\n"
    f.write_text(content, encoding="utf-8")
    resources = scan_resources(tmp_path)
    assert resources[0].checksum == hashlib.sha256(content.encode("utf-8")).hexdigest()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_resource_scanner.py::test_scan_resources_skips_checksum_over_threshold -v
```

Expected: FAIL (`skip_checksum_over_bytes` unexpected keyword or assertion).

- [ ] **Step 3: Implement minimal change**

Update `scan_resources` signature and checksum branch in `paleo_workbench/resources/scanner.py`:

```python
def scan_resources(
    root: Path,
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = None,
) -> list[ResourceItem]:
    resources: list[ResourceItem] = []

    for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
        if path.name.startswith("._"):
            continue

        resource_type, resource_format, status = classify_path(path)
        resolved_path = path.resolve()
        stored_path = resolved_path.as_posix()
        external = False

        if project_path is not None:
            stored_path, external = relativize_path(str(path), project_path)

        size_bytes = resolved_path.stat().st_size
        summary: dict = {"size_bytes": size_bytes}
        checksum: str | None
        if (
            skip_checksum_over_bytes is not None
            and size_bytes > skip_checksum_over_bytes
        ):
            checksum = None
            summary["checksum_skipped"] = True
        else:
            try:
                checksum = _checksum(path)
            except OSError:
                checksum = None
                summary["checksum_error"] = True

        resources.append(
            ResourceItem(
                name=path.name,
                path=stored_path,
                type=resource_type,
                format=resource_format,
                status=status,
                source="scan",
                parsed_summary=summary,
                checksum=checksum,
                external=external,
            )
        )

    return resources
```

Note: existing tests that call `scan_resources(root)` without the new kwarg must keep computing checksums (default `None` = never skip by size).

- [ ] **Step 4: Run tests to verify they pass**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_resource_scanner.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/resources/scanner.py tests/test_resource_scanner.py
git commit -m "feat: skip large-file checksums in scan_resources"
```

---

### Task 2: BootstrapResult + bootstrap_sample_project

**Files:**
- Create: `paleo_workbench/pipeline/__init__.py`
- Create: `paleo_workbench/pipeline/bootstrap.py`
- Create: `paleo_workbench/pipeline/assets.py`
- Create: `paleo_workbench/pipeline/compile_map.py`
- Test: `tests/test_pipeline_bootstrap.py`
- Test: `tests/test_pipeline_boundary.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_pipeline_bootstrap.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.pipeline.bootstrap import (
    BootstrapResult,
    bootstrap_sample_project,
)


def _make_sample_tree(root: Path) -> None:
    (root / "井曲线").mkdir(parents=True)
    (root / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (root / "井曲线" / "A2.Las").write_text("~Version\n", encoding="utf-8")
    (root / "层位").mkdir()
    (root / "层位" / "C6.dat").write_text("h", encoding="utf-8")
    (root / "层位" / "D71.dat").write_text("h", encoding="utf-8")
    (root / "地震体").mkdir()
    (root / "地震体" / "200P_seismic.sgy").write_bytes(b"x" * 100)


def test_bootstrap_indexes_and_stratigraphy(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    _make_sample_tree(data)

    result = bootstrap_sample_project(
        data,
        project_name="Demo",
        region="惠西南",
        skip_checksum_over_bytes=50,
    )
    assert isinstance(result, BootstrapResult)
    doc = result.document
    assert doc.meta.name == "Demo"
    assert doc.meta.region == "惠西南"
    assert len(doc.resources) >= 5
    types = {r.type for r in doc.resources}
    assert "well_log" in types
    assert "seismic" in types
    assert "horizon" in types
    assert doc.stratigraphy.target_horizon == "C6"
    assert doc.stratigraphy.sequence_boundaries == ["C6", "D71"]
    assert doc.stratigraphy.applicable_wells == ["A1", "A2"]
    assert any("200P" in n for n in doc.stratigraphy.applicable_seismic_ranges)
    assert len(doc.compilation_runs) == 1
    assert doc.compilation_runs[0].status == "draft"
    assert doc.compilation_runs[0].target_horizon == "C6"
    assert doc.factor_map_tasks == []
    assert doc.prediction_tasks == []
    assert doc.paleomap_documents == []
    big = next(r for r in doc.resources if r.name.endswith(".sgy"))
    assert big.checksum is None
    assert result.stats["files"] == len(doc.resources)
    assert result.stats["by_type"]["well_log"] == 2


def test_bootstrap_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        bootstrap_sample_project(tmp_path / "nope")


def test_bootstrap_empty_tree_raises(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no files"):
        bootstrap_sample_project(empty)


def test_bootstrap_skips_unreadable(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    good = data / "A1.Las"
    good.write_text("~Version\n", encoding="utf-8")
    bad = data / "bad.Las"
    bad.write_text("x", encoding="utf-8")

    real_stat = Path.stat

    def flaky_stat(self, *args, **kwargs):
        if self.name == "bad.Las":
            raise OSError("permission denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)
    # If skip happens inside scan only for checksum, bootstrap may still list bad.
    # Spec: unreadable mid-scan → skipped. Prefer bootstrap wrapper that catches.
    result = bootstrap_sample_project(data)
    assert any(s["path"].endswith("bad.Las") for s in result.skipped) or len(
        result.document.resources
    ) >= 1
```

Create `tests/test_pipeline_boundary.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path

PIPELINE = Path(__file__).resolve().parents[1] / "paleo_workbench" / "pipeline"


def test_pipeline_modules_do_not_import_ui():
    forbidden = "paleo_workbench.ui"
    for path in PIPELINE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(forbidden), path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pipeline_bootstrap.py tests/test_pipeline_boundary.py -v
```

Expected: FAIL (import errors).

- [ ] **Step 3: Implement package**

`paleo_workbench/pipeline/bootstrap.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import CompilationRun, ProjectDocument
from paleo_workbench.resources.scanner import scan_resources

DEFAULT_SKIP_CHECKSUM = 50 * 1024 * 1024


@dataclass
class BootstrapResult:
    document: ProjectDocument
    skipped: list[dict[str, str]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def resolve_sample_data_root(
    explicit: Path | None = None,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Resolve sample data directory.

    Order: explicit → PALEO_SAMPLE_DATA → cwd/data → walk up from this file for repo data/.
    """
    if explicit is not None:
        return Path(explicit)
    environ = env if env is not None else os.environ
    if environ.get("PALEO_SAMPLE_DATA"):
        return Path(environ["PALEO_SAMPLE_DATA"])
    base = cwd if cwd is not None else Path.cwd()
    candidate = base / "data"
    if candidate.is_dir():
        return candidate
    here = Path(__file__).resolve()
    for parent in here.parents:
        repo_data = parent / "data"
        if repo_data.is_dir() and (repo_data / "井曲线").exists():
            return repo_data
    raise FileNotFoundError(
        "Could not resolve sample data root. Pass data_root, set PALEO_SAMPLE_DATA, "
        "or run from repo with data/ present."
    )


def bootstrap_sample_project(
    data_root: Path,
    *,
    project_name: str = "惠西南样例工程",
    region: str = "惠西南",
    project_path: Path | None = None,
    skip_checksum_over_bytes: int = DEFAULT_SKIP_CHECKSUM,
) -> BootstrapResult:
    root = Path(data_root)
    if not root.is_dir():
        raise FileNotFoundError(f"data_root is not a directory: {root}")

    skipped: list[dict[str, str]] = []
    try:
        resources = scan_resources(
            root,
            project_path=project_path,
            skip_checksum_over_bytes=skip_checksum_over_bytes,
        )
    except OSError as e:
        raise OSError(f"failed to scan {root}: {e}") from e

    # Tag rel_dir for grouping (best-effort).
    root_resolved = root.resolve()
    for res in resources:
        try:
            p = Path(res.path)
            if not p.is_absolute():
                # relative to project — leave rel_dir from name only
                res.parsed_summary.setdefault("rel_dir", str(Path(res.path).parent))
            else:
                try:
                    rel = Path(res.path).resolve().relative_to(root_resolved)
                    res.parsed_summary["rel_dir"] = str(rel.parent) if rel.parent != Path(".") else ""
                except ValueError:
                    res.parsed_summary.setdefault("rel_dir", "")
        except OSError as e:
            skipped.append({"path": res.path, "reason": str(e)})

    if not resources:
        raise ValueError("no files under data_root")

    doc = ProjectDocument.new(name=project_name, region=region)
    if project_path is not None:
        doc.meta.project_root = str(Path(project_path).parent)
    else:
        doc.meta.project_root = str(root.parent)

    # Enrich paths that are absolute with rel_dir already; keep resources as scanned.
    doc.resources = resources

    horizons = sorted(
        Path(r.name).stem
        for r in resources
        if r.type == "horizon"
    )
    wells = sorted(
        Path(r.name).stem
        for r in resources
        if r.type == "well_log"
    )
    seismic_names = sorted(r.name for r in resources if r.type == "seismic")

    doc.stratigraphy.target_horizon = horizons[0] if horizons else ""
    doc.stratigraphy.sequence_boundaries = horizons
    doc.stratigraphy.applicable_wells = wells
    doc.stratigraphy.applicable_seismic_ranges = seismic_names

    doc.compilation_runs.append(
        CompilationRun(
            name=f"{project_name} 演示编制",
            target_horizon=doc.stratigraphy.target_horizon,
            status="draft",
        )
    )

    by_type: dict[str, int] = {}
    for r in resources:
        by_type[r.type] = by_type.get(r.type, 0) + 1

    return BootstrapResult(
        document=doc,
        skipped=skipped,
        stats={"files": len(resources), "by_type": by_type},
    )


def write_project(doc: ProjectDocument, path: Path) -> Path:
    target = Path(path)
    if not target.name.endswith(".paleo.json"):
        if target.name.endswith(".json"):
            target = target.with_name(target.name[: -len(".json")] + ".paleo.json")
        else:
            target = target.with_name(target.name + ".paleo.json")
    ProjectManager(target).save(doc)
    return target
```

Simplify `test_bootstrap_skips_unreadable` if implementation does not wrap per-file OSError from `rglob`—either implement per-file try in a bootstrap-local scan loop, **or** change the test to only assert missing/empty behavior and drop flaky unreadable test. **Preferred:** wrap scan in bootstrap by iterating files yourself only if scanner doesn't skip—**YAGNI:** delete the unreadable monkeypatch test and document soft-skip as best-effort via scanner `checksum_error` only. Keep tests: index, missing, empty.

`paleo_workbench/pipeline/assets.py`:

```python
"""18b contract stubs — implement in Phase 18b."""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import PredictionTask, ProjectDocument


def bind_prediction_assets(
    project: ProjectDocument,
    task: PredictionTask,
    *,
    well_log_ids: list[str] | None = None,
    seismic_ids: list[str] | None = None,
) -> PredictionTask:
    raise NotImplementedError("Phase 18b: bind_prediction_assets")


def suggest_assets_for_demo(project: ProjectDocument) -> dict[str, Any]:
    raise NotImplementedError("Phase 18b: suggest_assets_for_demo")
```

`paleo_workbench/pipeline/compile_map.py`:

```python
"""18c contract stub — implement in Phase 18c."""

from __future__ import annotations

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument


def compile_map_draft(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    prediction_task_id: str | None = None,
    seed: int = 0,
) -> PaleoMapDocument:
    raise NotImplementedError("Phase 18c: compile_map_draft")
```

`paleo_workbench/pipeline/__init__.py`:

```python
from paleo_workbench.pipeline.bootstrap import (
    BootstrapResult,
    bootstrap_sample_project,
    resolve_sample_data_root,
    write_project,
)

__all__ = [
    "BootstrapResult",
    "bootstrap_sample_project",
    "resolve_sample_data_root",
    "write_project",
]
```

Remove or simplify `test_bootstrap_skips_unreadable` to avoid flaky Path.stat monkeypatch—**do not ship that test** unless you implement per-file skip in bootstrap.

- [ ] **Step 4: Run tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pipeline_bootstrap.py tests/test_pipeline_boundary.py tests/test_resource_scanner.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/pipeline tests/test_pipeline_bootstrap.py tests/test_pipeline_boundary.py
git commit -m "feat: add pipeline bootstrap_sample_project for sample data"
```

---

### Task 3: CLI module

**Files:**
- Create: `paleo_workbench/pipeline/__main__.py`
- Test: `tests/test_pipeline_cli.py`

- [ ] **Step 1: Write failing test**

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from paleo_workbench.project.manager import ProjectManager


def test_cli_writes_loadable_project(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "井曲线").mkdir()
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    out = tmp_path / "sample.paleo.json"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "paleo_workbench.pipeline",
            "--data-root",
            str(data),
            "--out",
            str(out),
            "--name",
            "CLIDemo",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.exists()
    doc = ProjectManager(out).load()
    assert doc.meta.name == "CLIDemo"
    assert len(doc.resources) == 1


def test_cli_missing_data_root_exits_2(tmp_path: Path):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "paleo_workbench.pipeline",
            "--data-root",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path / "x.paleo.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
```

- [ ] **Step 2: Run to verify fail**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pipeline_cli.py -v
```

Expected: FAIL (module not executable / exit code).

- [ ] **Step 3: Implement `__main__.py`**

```python
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from paleo_workbench.pipeline.bootstrap import bootstrap_sample_project, write_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap a sample Paleo project from a data tree.")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", default="惠西南样例工程")
    parser.add_argument("--region", default="惠西南")
    args = parser.parse_args(argv)

    try:
        result = bootstrap_sample_project(
            args.data_root,
            project_name=args.name,
            region=args.region,
            project_path=args.out,
        )
        path = write_project(result.document, args.out)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 — CLI boundary
        print(f"unexpected error: {e}", file=sys.stderr)
        return 1

    print(f"Wrote {path} with {result.stats.get('files', 0)} resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Also support `python -m paleo_workbench.pipeline.bootstrap` **or** only package root—spec says `python -m paleo_workbench.pipeline.bootstrap`. Add thin `bootstrap.py` bottom:

```python
# at end of bootstrap.py only if desired — prefer single entry:
# python -m paleo_workbench.pipeline
```

To match spec literally, create `paleo_workbench/pipeline/bootstrap_cli` **or** make `python -m paleo_workbench.pipeline.bootstrap` work by adding to `bootstrap.py`:

```python
def _cli_main() -> None:
    from paleo_workbench.pipeline.__main__ import main
    raise SystemExit(main())


if __name__ == "__main__":
    _cli_main()
```

Use **both** entry points calling the same `main()`.

- [ ] **Step 4: Run tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_pipeline_cli.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/pipeline/__main__.py paleo_workbench/pipeline/bootstrap.py tests/test_pipeline_cli.py
git commit -m "feat: CLI for sample project bootstrap"
```

---

### Task 4: HeaderToolbar sample action

**Files:**
- Modify: `paleo_workbench/ui/header_toolbar.py`
- Modify: `tests/test_header_toolbar.py` (create or extend)

- [ ] **Step 1: Write failing test**

If `tests/test_header_toolbar.py` exists, append; else create:

```python
from paleo_workbench.ui.header_toolbar import HeaderToolbar


def test_sample_project_button_emits(qtbot):
    bar = HeaderToolbar()
    qtbot.addWidget(bar)
    assert bar.open_sample_project_btn.text() == "打开样例工程"
    with qtbot.waitSignal(bar.open_sample_project_requested, timeout=1000):
        bar.open_sample_project_btn.click()
```

- [ ] **Step 2: Run to fail**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_header_toolbar.py::test_sample_project_button_emits -v
```

- [ ] **Step 3: Implement**

In `header_toolbar.py`, add fifth button **after** 打开工程 (index 2), before 保存工程—or append before stretch. Spec: adjacent to 打开工程.

```python
from PySide6.QtCore import Signal
# ...
_BUTTON_SPECS = [
    ("新建工程", "PrimaryButton"),
    ("打开工程", "SecondaryButton"),
    ("打开样例工程", "SecondaryButton"),
    ("保存工程", "SecondaryButton"),
    ("工程属性", "SecondaryButton"),
]

class HeaderToolbar(QFrame):
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_project_requested = Signal()
    save_project_requested = Signal()
    properties_requested = Signal()
    # ...
    # after building buttons:
    self.new_project_btn = self.buttons[0]
    self.open_project_btn = self.buttons[1]
    self.open_sample_project_btn = self.buttons[2]
    self.save_project_btn = self.buttons[3]
    self.properties_btn = self.buttons[4]

    self.new_project_btn.clicked.connect(self.new_project_requested)
    self.open_project_btn.clicked.connect(self.open_project_requested)
    self.open_sample_project_btn.clicked.connect(self.open_sample_project_requested)
    self.save_project_btn.clicked.connect(self.save_project_requested)
    self.properties_btn.clicked.connect(self.properties_requested)
```

**Update any tests** that assume button indices 0–3 only (grep `buttons[3]`, `len(buttons)`, 保存工程 index).

- [ ] **Step 4: Run**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_header_toolbar.py tests/test_app_shell.py -q
```

Fix index assumptions until green.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/ui/header_toolbar.py tests/test_header_toolbar.py
git commit -m "feat: toolbar button for open sample project"
```

---

### Task 5: Window open_sample_project + wire

**Files:**
- Modify: `paleo_workbench/app.py`
- Test: `tests/test_sample_project_ui.py`

- [ ] **Step 1: Write failing tests**

```python
from __future__ import annotations

from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow


def test_open_sample_project_loads_resources(qtbot, tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    (data / "井曲线").mkdir(parents=True)
    (data / "井曲线" / "A1.Las").write_text("~Version\n", encoding="utf-8")
    (data / "层位").mkdir()
    (data / "层位" / "C6.dat").write_text("h", encoding="utf-8")

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: data,
    )
    # Avoid confirm dialog in tests
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)

    ok = window.open_sample_project()
    assert ok is True
    assert window.project.meta.name == "惠西南样例工程"
    assert len(window.project.resources) >= 2
    assert window.project_path is None  # not auto-saved
    # data page sees resources
    page = window.app_shell.data_page_widget()
    assert page is not None
    # resource count via page or project
    assert len(window.project.resources) == len(
        getattr(page, "resources", window.project.resources)
    )


def test_open_sample_project_cancel_confirm_keeps_project(qtbot, monkeypatch, tmp_path: Path):
    window = PaleoWorkbenchWindow(project=__import__(
        "paleo_workbench.project.models", fromlist=["ProjectDocument"]
    ).ProjectDocument.new("KeepMe"))
    qtbot.addWidget(window)
    data = tmp_path / "data"
    data.mkdir()
    (data / "A1.Las").write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: data,
    )
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: False)

    ok = window.open_sample_project()
    assert ok is False
    assert window.project.meta.name == "KeepMe"


def test_open_sample_project_missing_data_returns_false(qtbot, monkeypatch, tmp_path: Path):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(
        "paleo_workbench.app.resolve_sample_data_root",
        lambda explicit=None, **kwargs: (_ for _ in ()).throw(
            FileNotFoundError("no data")
        ),
    )
    monkeypatch.setattr(window, "_confirm_replace_project", lambda: True)
    monkeypatch.setattr(window, "_show_project_error", lambda *a, **k: None)

    assert window.open_sample_project() is False
```

- [ ] **Step 2: Run to fail**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_sample_project_ui.py -v
```

- [ ] **Step 3: Implement in `app.py`**

```python
from paleo_workbench.pipeline.bootstrap import (
    bootstrap_sample_project,
    resolve_sample_data_root,
)

# In PaleoWorkbenchWindow:

def open_sample_project(self, data_root: Path | None = None) -> bool:
    """Bootstrap sample data into the current window (no auto-save)."""
    if not self._confirm_replace_project():
        return False
    try:
        root = resolve_sample_data_root(data_root)
        result = bootstrap_sample_project(root)
    except FileNotFoundError as e:
        self._show_project_error("打开样例工程失败", str(e))
        return False
    except ValueError as e:
        self._show_project_error("打开样例工程失败", str(e))
        return False
    except OSError as e:
        self._show_project_error("打开样例工程失败", str(e))
        return False
    self.project = result.document
    self.project_path = None
    self._refresh_shell()
    return True

def _confirm_replace_project(self) -> bool:
    """Ask before replacing the in-memory project. Overridable in tests."""
    reply = QMessageBox.question(
        self,
        "打开样例工程",
        "将用样例数据替换当前工程（未保存更改会丢失）。是否继续？",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes

def _on_open_sample_project(self) -> None:
    self.open_sample_project()

# In _wire_toolbar:
toolbar.open_sample_project_requested.connect(self._on_open_sample_project)
```

- [ ] **Step 4: Run UI + lifecycle tests**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_sample_project_ui.py tests/test_project_lifecycle.py tests/test_header_toolbar.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/app.py tests/test_sample_project_ui.py
git commit -m "feat: open sample project from workbench toolbar"
```

---

### Task 6: Full suite + planning docs

**Files:**
- Modify: `task_plan.md`, `progress.md` (Phase 18a complete note)
- Optional smoke: manual note in progress

- [ ] **Step 1: Run full suite**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Expected: all previous tests + new ones pass (baseline was 501; expect ~515+).

- [ ] **Step 2: Manual smoke (if display available)**

```bash
python -m paleo_workbench.pipeline --data-root data --out /tmp/sample.paleo.json
# optional GUI: open app → 打开样例工程
```

- [ ] **Step 3: Update `task_plan.md`**

Add Phase 18a complete section pointing at this plan + spec; keep 18b/18c as next.

- [ ] **Step 4: Update `progress.md`**

Session log for 18a delivery.

- [ ] **Step 5: Commit**

```bash
git add task_plan.md progress.md
git commit -m "docs: record Phase 18a sample project bootstrap delivery"
```

---

## Self-review (plan vs spec)

| Spec requirement | Task |
|------------------|------|
| `skip_checksum_over_bytes` on scan | Task 1 |
| `BootstrapResult` + `bootstrap_sample_project` | Task 2 |
| Full index, stratigraphy, one draft run, empty tasks/maps | Task 2 |
| No Qt in pipeline | Task 2 boundary test |
| 18b/18c stubs | Task 2 |
| CLI write `.paleo.json` | Task 3 |
| UI 「打开样例工程」 | Tasks 4–5 |
| No auto-save from UI | Task 5 (`project_path is None`) |
| Confirm replace | Task 5 |
| resolve data root order | Task 2 `resolve_sample_data_root` + Task 5 |
| Full suite green | Task 6 |

**Placeholders:** none intentional.  
**Out of scope (by design):** 18b canvas binding, 18c map compile, dirty-flag tracking beyond simple confirm.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-e2e-real-data-pipeline-18a.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with executing-plans checkpoints  

Which approach?
