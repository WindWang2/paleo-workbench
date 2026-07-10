# Phase 21 Data Page Stress + Hotspot Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a reproducible data-page stress harness (S1–S4 with printed timings) and fix the top measured hotspot (default: import scan checksum skip), without CI wall-clock gates.

**Architecture:** Test-only `tests/perf/` helpers + `test_datapage_stress.py`. Production change primarily in `import_service` → pass `skip_checksum_over_bytes` into `scan_resources`. Optional second fix only if S1/S3 numbers demand it.

**Tech Stack:** pytest, pytest-qt, existing DataPage / FilterIndex / PreviewRequestController / import_service.

**Spec:** `docs/superpowers/specs/2026-07-10-datapage-stress-hotspots-design.md`

---

## File map

| Path | Role |
|------|------|
| `tests/perf/__init__.py` | Package marker |
| `tests/perf/timing.py` | `timed`, `print_stress` |
| `tests/perf/fixtures.py` | `make_mock_resources`, `make_tmp_tree` |
| `tests/test_datapage_stress.py` | S1–S4 scenarios |
| `paleo_workbench/resources/import_service.py` | Pass skip_checksum to scan |
| `tests/test_data_import_service.py` | Checksum skip unit test |
| `task_plan.md` / `progress.md` | Phase 21 notes + sample timings |

---

### Task 1: Timing + fixtures helpers

**Files:**
- Create: `tests/perf/__init__.py`
- Create: `tests/perf/timing.py`
- Create: `tests/perf/fixtures.py`
- Create: `tests/test_perf_helpers.py` (small unit tests for helpers)

- [ ] **Step 1: Failing tests**

```python
# tests/test_perf_helpers.py
from tests.perf.fixtures import make_mock_resources, make_tmp_tree
from tests.perf.timing import timed, format_stress_line


def test_make_mock_resources_count():
    items = make_mock_resources(10)
    assert len(items) == 10
    assert items[0].type == "well_log"
    assert items[5].type in {"well_log", "seismic", "horizon", "document"}


def test_timed_returns_positive_ms():
    t = timed("x", lambda: sum(range(1000)))
    assert t.name == "x"
    assert t.ms >= 0.0
    line = format_stress_line("S1_update", n=2000, ms=12.3)
    assert line.startswith("[datapage-stress]")
    assert "elapsed_ms=12.3" in line or "elapsed_ms=12.30" in line


def test_make_tmp_tree(tmp_path):
    root = make_tmp_tree(tmp_path, n=5)
    assert len(list(root.rglob("*"))) >= 5
```

- [ ] **Step 2: Implement**

`tests/perf/timing.py`:

```python
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Timing:
    name: str
    ms: float


def timed(name: str, fn: Callable[[], T]) -> tuple[Timing, T]:
    start = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - start) * 1000.0
    return Timing(name=name, ms=ms), result


def format_stress_line(scenario: str, *, n: int, ms: float) -> str:
    return f"[datapage-stress] {scenario} n={n} elapsed_ms={ms:.1f}"


def print_stress(scenario: str, *, n: int, ms: float) -> None:
    print(format_stress_line(scenario, n=n, ms=ms), flush=True)
```

`tests/perf/fixtures.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

from paleo_workbench.project.models import ResourceItem

# Types cycle for filter stress
_TYPES = (
    ("well_log", "las"),
    ("seismic", "sgy"),
    ("horizon", "dat"),
    ("document", "pdf"),
)


def stress_n(default: int = 2000) -> int:
    raw = os.environ.get("DATAPAGE_STRESS_N")
    if raw:
        return max(1, int(raw))
    return default


def make_mock_resources(n: int) -> list[ResourceItem]:
    items: list[ResourceItem] = []
    for i in range(n):
        rtype, fmt = _TYPES[i % len(_TYPES)]
        name = f"asset_{i:05d}.{fmt}"
        items.append(
            ResourceItem(
                name=name,
                path=f"/mock/data/{name}",
                type=rtype,
                format=fmt,
                status="indexed",
                checksum=None,
            )
        )
    return items


def make_tmp_tree(base: Path, n: int = 300) -> Path:
    """Create n tiny files under base/stress_import/ for import_folder timing."""
    root = base / "stress_import"
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        # Mix extensions for classifier variety; keep tiny
        ext = "las" if i % 3 == 0 else ("txt" if i % 3 == 1 else "dat")
        p = root / f"f_{i:04d}.{ext}"
        p.write_bytes(b"x")
    return root
```

`tests/perf/__init__.py` can be empty or a docstring.

- [ ] **Step 3:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_perf_helpers.py -q
```

- [ ] **Step 4: Commit**

```bash
git commit -m "test: add datapage stress timing and fixture helpers"
```

---

### Task 2: Stress scenarios S1–S4

**Files:** `tests/test_datapage_stress.py`

- [ ] **Step 1: Implement four tests** (TDD: write tests that fail if helpers missing already done)

```python
# tests/test_datapage_stress.py
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.resources.import_service import import_folder
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.filter_index import FilterIndex
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController
from tests.perf.fixtures import make_mock_resources, make_tmp_tree, stress_n
from tests.perf.timing import print_stress, timed


class InstantProvider(PreviewProvider):
    def preview(self, asset):
        if asset is None:
            return super().preview(asset)
        return PreviewResult(
            mode="message",
            title=asset.name,
            path=asset.path,
            message=f"ok:{asset.name}",
        )


def test_stress_s1_update_state(qtbot):
    n = stress_n(2000)
    page = DataPage(ProjectDocument.new("Stress"))
    qtbot.addWidget(page)
    resources = make_mock_resources(n)

    timing, _ = timed("S1_update", lambda: page.update_state({}, resources))
    print_stress("S1_update", n=n, ms=timing.ms)

    # Prefer public-ish access: asset table model row count
    model = page.asset_table.model()
    assert model is not None
    assert model.rowCount() == n


def test_stress_s2_filter_index():
    n = stress_n(2000)
    resources = make_mock_resources(n)
    idx = FilterIndex()
    idx.rebuild(resources)

    timing_all, rows_all = timed("S2_filter_all", lambda: idx.filter("all", ""))
    print_stress("S2_filter_all", n=n, ms=timing_all.ms)
    assert len(rows_all) == n

    timing_q, rows_q = timed(
        "S2_filter_search",
        lambda: idx.filter("well_log", "asset_0000"),
    )
    print_stress("S2_filter_search", n=n, ms=timing_q.ms)
    assert len(rows_q) >= 1


def test_stress_s3_rapid_select(qtbot):
    n_sel = 30
    resources = make_mock_resources(max(n_sel, 50))
    controller = PreviewRequestController(provider=InstantProvider())
    qtbot.addWidget(controller)  # QObject parent lifecycle; or parent=None + shutdown

    last: list[str] = []
    controller.result_ready.connect(lambda r: last.append(getattr(r, "title", "") or ""))

    def run():
        for i in range(n_sel):
            controller.request(resources[i])
        # Process events so async jobs drain
        app = QApplication.instance()
        for _ in range(50):
            app.processEvents()

    timing, _ = timed("S3_rapid_select", run)
    print_stress("S3_rapid_select", n=n_sel, ms=timing.ms)

    qtbot.waitUntil(
        lambda: controller._active is None and controller._pending is None,
        timeout=10_000,
    )
    controller.shutdown(wait_ms=5_000)
    assert last  # got at least one result
    # Latest-only: final title should be last requested when instant provider
    assert last[-1] == resources[n_sel - 1].name


def test_stress_s4_import_folder(tmp_path):
    n = 300
    root = make_tmp_tree(tmp_path, n=n)
    timing, report = timed("S4_import_folder", lambda: import_folder(root, existing=[]))
    print_stress("S4_import_folder", n=n, ms=timing.ms)
    assert report.added_count == n
```

**Notes for implementer:**

- If `qtbot.addWidget(controller)` is wrong for QObject, use `controller = PreviewRequestController(...);` and always `shutdown` in `try/finally`.
- If InstantProvider is so fast that all hits are sync cache path, still OK—prints time.
- Do **not** assert `timing.ms < X`.

- [ ] **Step 2: Run**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_datapage_stress.py -q -s
```

Expected: 4 passed; stdout shows four `[datapage-stress]` lines.

- [ ] **Step 3: Commit**

```bash
git commit -m "test: datapage stress scenarios S1-S4 with timing logs"
```

---

### Task 3: Import checksum skip (default Top fix)

**Files:** `import_service.py`, `tests/test_data_import_service.py`

- [ ] **Step 1: Failing test**

```python
def test_import_folder_skips_checksum_over_threshold(tmp_path: Path):
    root = tmp_path / "bulk"
    root.mkdir()
    big = root / "big.sgy"
    big.write_bytes(b"x" * 100)
    small = root / "small.las"
    small.write_text("~Version\n", encoding="utf-8")

    report = import_folder(
        root,
        existing=[],
        skip_checksum_over_bytes=50,
    )
    by_name = {r.name: r for r in report.added}
    assert by_name["big.sgy"].checksum is None
    assert by_name["big.sgy"].parsed_summary.get("checksum_skipped") is True
    assert by_name["small.las"].checksum is not None
```

- [ ] **Step 2: Implement `import_service.py`**

```python
DEFAULT_IMPORT_SKIP_CHECKSUM = 50 * 1024 * 1024


def import_files(
    paths: list[Path],
    existing: list[ResourceItem],
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = DEFAULT_IMPORT_SKIP_CHECKSUM,
) -> ImportReport:
    ...
            candidates.extend(
                scan_resources(
                    path.parent,
                    project_path=project_path,
                    skip_checksum_over_bytes=skip_checksum_over_bytes,
                )
            )
    ...


def import_folder(
    root: Path,
    existing: list[ResourceItem],
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = DEFAULT_IMPORT_SKIP_CHECKSUM,
) -> ImportReport:
    try:
        candidates = scan_resources(
            root,
            project_path=project_path,
            skip_checksum_over_bytes=skip_checksum_over_bytes,
        )
    except OSError as exc:
        return ImportReport(warnings=[f"{root}: {exc}"])
    return _filter_new(candidates, existing, project_path)
```

- [ ] **Step 3:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest tests/test_data_import_service.py tests/test_datapage_stress.py -q -s
```

- [ ] **Step 4: Commit**

```bash
git commit -m "perf: skip large-file checksums on data import scan"
```

---

### Task 4: Optional second hotspot (only if needed)

**Do this task only if** local S1 print shows multi-second `update_state` for N=2000, or S3 leaves threads hanging.

**Candidate A — document-only if already fine:** skip code; note in progress.md “S1/S3 acceptable”.

**Candidate B — measure FilterIndex rebuild on DataPage:** if `asset_table.update_assets` rebuilds index twice, collapse to once.

**Candidate C — import_files parent scan:** change `import_files` to scan only the requested file:

```python
# Instead of scan_resources(path.parent) for each file:
candidates.extend(scan_resources(path if path.is_dir() else path.parent, ...))
# Better: if path.is_file(), classify single file without scanning siblings
```

Only if multi-file import is a product path and measured slow.

If no second fix:

```bash
# Skip commit or commit docs note only in Task 5
```

---

### Task 5: Full suite + docs

- [ ] **Step 1:**

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

- [ ] **Step 2:** Update `task_plan.md` Phase 21 complete; link design + plan; test count.  
- [ ] **Step 3:** Update `progress.md` with sample `[datapage-stress]` lines from one local run after import fix.  
- [ ] **Step 4:**

```bash
git commit -m "docs: record Phase 21 datapage stress and import checksum skip"
```

---

## Spec coverage

| Spec item | Task |
|-----------|------|
| timing + fixtures | 1 |
| S1–S4 harness | 2 |
| import skip_checksum | 3 |
| optional #2 fix | 4 |
| docs + full suite | 5 |

**No CI ms asserts** anywhere.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-datapage-stress-hotspots.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)**  
2. **Inline Execution**  

Which approach?
