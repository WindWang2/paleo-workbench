# Concurrent Resource Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize `scan_resources` file processing (stat + checksum) via `ThreadPoolExecutor` and validate with an N=10000 stress scenario.

**Architecture:** Extract the per-file loop body into `_process_file(path, project_path, skip_checksum_over_bytes) -> ResourceItem | None`, then run it through `ThreadPoolExecutor.map` (preserves submission order). Default `max_workers = min(32, cpu_count + 4)`. Expose `max_workers` as a keyword-only param for test control.

**Tech Stack:** Python stdlib `concurrent.futures.ThreadPoolExecutor`, `os.cpu_count`.

**Spec:** `docs/superpowers/specs/2026-07-13-concurrent-scan-design.md`

## Global Constraints

- `scan_resources(root, project_path=None, *, skip_checksum_over_bytes=None, max_workers=None)` — `max_workers` is keyword-only with default `None` (resolved to `min(32, cpu_count+4)` internally). Backward-compatible: existing callers pass no `max_workers`.
- `ThreadPoolExecutor.map` preserves submission order → result order identical to serial `sorted(rglob)`.
- `_process_file` is a module-level helper (not a method) — stateless, pure, thread-safe (classify_path + stat + hashlib are all thread-safe; no shared mutable state).
- stat `OSError` (file vanished between rglob and processing) → `_process_file` returns `None` → filtered from results. This is a behavior refinement (graceful skip vs. today's uncaught raise); acceptable and safer.
- checksum `OSError` → unchanged: sets `summary["checksum_error"] = True`, `checksum = None`, resource still included (current behavior preserved).
- `skip_checksum_over_bytes` behavior unchanged (files over threshold skip checksum).
- Empty dir → `[]` (early return, no thread pool spawned).
- S5 stress scenario is env-gated: skipped unless `DATAPAGE_STRESS_S5=1` is set. Prints a skip line when skipped.
- Stay on `main`. TDD. Frequent commits. All 625 existing tests must pass.

---

## File Structure

| File | Change |
|------|--------|
| `paleo_workbench/resources/scanner.py` | Extract `_process_file`; rewrite `scan_resources` to use ThreadPoolExecutor |
| `tests/test_resource_scanner.py` | +6 concurrent-scan unit tests |
| `tests/test_datapage_stress.py` | +S5 scenario (env-gated) |

---

## Task 1: Concurrent scan_resources + unit tests

**Files:**
- Modify: `paleo_workbench/resources/scanner.py`
- Test: `tests/test_resource_scanner.py`

**Interfaces:**
- Produces: `scan_resources(root, project_path=None, *, skip_checksum_over_bytes=None, max_workers=None) -> list[ResourceItem]` and module-level `_process_file(path, project_path, skip_checksum_over_bytes) -> ResourceItem | None`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_resource_scanner.py`:
```python
def test_scan_concurrent_preserves_order(tmp_path: Path):
    (tmp_path / "c.las").write_bytes(b"x")
    (tmp_path / "a.las").write_bytes(b"x")
    (tmp_path / "b.las").write_bytes(b"x")
    results = scan_resources(tmp_path)
    names = [r.name for r in results]
    assert names == ["a.las", "b.las", "c.las"]


def test_scan_concurrent_matches_serial(tmp_path: Path):
    for i in range(20):
        (tmp_path / f"f{i:02d}.las").write_bytes(f"content{i}".encode())
    serial = scan_resources(tmp_path, max_workers=1)
    concurrent = scan_resources(tmp_path, max_workers=4)
    assert len(serial) == len(concurrent) == 20
    for s, c in zip(serial, concurrent):
        assert s.name == c.name
        assert s.path == c.path
        assert s.type == c.type
        assert s.format == c.format
        assert s.checksum == c.checksum


def test_scan_concurrent_empty_dir(tmp_path: Path):
    assert scan_resources(tmp_path) == []


def test_scan_concurrent_checksum_correct(tmp_path: Path):
    import hashlib
    (tmp_path / "data.dat").write_bytes(b"hello world")
    results = scan_resources(tmp_path)
    assert len(results) == 1
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert results[0].checksum == expected


def test_scan_concurrent_max_workers_param(tmp_path: Path):
    (tmp_path / "a.las").write_bytes(b"x")
    # Both should work without error; max_workers=1 forces serial
    r1 = scan_resources(tmp_path, max_workers=1)
    r8 = scan_resources(tmp_path, max_workers=8)
    assert len(r1) == len(r8) == 1


def test_scan_concurrent_vanished_file_skipped(tmp_path: Path, monkeypatch):
    (tmp_path / "a.las").write_bytes(b"x")
    (tmp_path / "b.las").write_bytes(b"x")
    # Make _process_file return None for one file (simulating vanished file)
    from paleo_workbench.resources import scanner
    original = scanner._process_file
    call_count = [0]

    def patched(path, project_path, skip):
        call_count[0] += 1
        if call_count[0] == 1:
            return None  # simulate vanished
        return original(path, project_path, skip)

    monkeypatch.setattr(scanner, "_process_file", patched)
    results = scan_resources(tmp_path)
    assert len(results) == 1  # one skipped, one kept
```

- [ ] **Step 2: Run — expect FAIL (scan_resources has no max_workers; _process_file doesn't exist)**

```bash
source .venv/bin/activate && python -m pytest tests/test_resource_scanner.py -v
```

- [ ] **Step 3: Rewrite scan_resources**

In `paleo_workbench/resources/scanner.py`, replace the entire file:
```python
from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.project.paths import relativize_path
from paleo_workbench.resources.classifier import classify_path


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _process_file(
    path: Path,
    project_path: Path | None,
    skip_checksum_over_bytes: int | None,
) -> ResourceItem | None:
    """Process a single file: classify, stat, checksum, build ResourceItem.

    Returns None if the file vanished (stat OSError) — caller filters it.
    Thread-safe: uses only local state and stateless helpers.
    """
    resource_type, resource_format, status = classify_path(path)
    resolved_path = path.resolve()
    try:
        size_bytes = resolved_path.stat().st_size
    except OSError:
        return None
    stored_path = resolved_path.as_posix()
    external = False
    if project_path is not None:
        stored_path, external = relativize_path(str(path), project_path)
    summary: dict = {"size_bytes": size_bytes}
    if skip_checksum_over_bytes is not None and size_bytes > skip_checksum_over_bytes:
        checksum: str | None = None
        summary["checksum_skipped"] = True
    else:
        try:
            checksum = _checksum(path)
        except OSError:
            checksum = None
            summary["checksum_error"] = True
    return ResourceItem(
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


def scan_resources(
    root: Path,
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = None,
    max_workers: int | None = None,
) -> list[ResourceItem]:
    candidates = sorted(
        c for c in root.rglob("*") if c.is_file() and not c.name.startswith("._")
    )
    if not candidates:
        return []
    workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(
            pool.map(
                lambda p: _process_file(p, project_path, skip_checksum_over_bytes),
                candidates,
            )
        )
    return [r for r in processed if r is not None]
```

- [ ] **Step 4: Run — expect PASS**

```bash
python -m pytest tests/test_resource_scanner.py -v
```

- [ ] **Step 5: Run full suite — expect PASS (backward compatible)**

```bash
python -m pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add paleo_workbench/resources/scanner.py tests/test_resource_scanner.py
git commit -m "feat: parallelize scan_resources file processing via ThreadPoolExecutor"
```

---

## Task 2: S5 stress scenario (N=10000, env-gated)

**Files:**
- Modify: `tests/test_datapage_stress.py`

**Interfaces:**
- Produces: `test_stress_s5_scan_concurrent_large` — env-gated by `DATAPAGE_STRESS_S5=1`; creates 10000 tiny tmp files; scans with concurrent + serial (max_workers=1); prints both timings; asserts correctness.

- [ ] **Step 1: Write the S5 test**

Append to `tests/test_datapage_stress.py`:
```python
import os
from paleo_workbench.resources.scanner import scan_resources
from tests.perf.timing import timed, print_stress


def test_stress_s5_scan_concurrent_large(tmp_path):
    """N=10000 tiny files: concurrent vs serial scan timing (env-gated).

    Skipped unless DATAPAGE_STRESS_S5=1 to avoid slowing the default loop.
    """
    n = int(os.getenv("DATAPAGE_STRESS_S5_N", "10000"))
    if os.getenv("DATAPAGE_STRESS_S5") != "1":
        print(f"[datapage-stress] S5 SKIPPED (set DATAPAGE_STRESS_S5=1 to enable, N={n})", flush=True)
        return

    for i in range(n):
        (tmp_path / f"f{i:05d}.dat").write_bytes(b"x")

    timing_serial, serial_results = timed(
        "S5_scan_serial", lambda: scan_resources(tmp_path, max_workers=1)
    )
    print_stress("S5_scan_serial", n=n, ms=timing_serial.ms)

    timing_concurrent, concurrent_results = timed(
        "S5_scan_concurrent", lambda: scan_resources(tmp_path)
    )
    print_stress("S5_scan_concurrent", n=n, ms=timing_concurrent.ms)

    # Correctness: both scans return all files in sorted order
    assert len(serial_results) == n
    assert len(concurrent_results) == n
    assert serial_results[0].name == concurrent_results[0].name
    assert serial_results[-1].name == concurrent_results[-1].name
```

- [ ] **Step 2: Run default (S5 skips, prints skip line)**

```bash
python -m pytest tests/test_datapage_stress.py -v -s
```
Expected: S5 prints `S5 SKIPPED` and returns (pass).

- [ ] **Step 3: Run with S5 enabled (local validation)**

```bash
DATAPAGE_STRESS_S5=1 DATAPAGE_STRESS_S5_N=100 python -m pytest tests/test_datapage_stress.py::test_stress_s5_scan_concurrent_large -v -s
```
(N=100 for a quick local check; full N=10000 optional.) Expected: prints both timings; passes correctness.

- [ ] **Step 4: Run full suite (S5 skips by default)**

```bash
python -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_datapage_stress.py
git commit -m "test: add S5 concurrent scan stress scenario (N=10000, env-gated)"
```

---

## Task 3: Final review + ledger sync

**Actions:**
- Whole-branch review: scan correctness (concurrent == serial results), thread safety of `_process_file` (no shared state), order preservation, graceful vanished-file skip, backward-compatible signature, S5 gating.
- Run full suite, confirm count.
- Update `task_plan.md` / `progress.md` / `findings.md` with Phase C.

**Commit:** `chore: sync SDD progress ledger (Concurrent Scan Phase C complete)`

## Self-Review (completed during authoring)

- **Spec coverage:** concurrent scan_resources (Task 1), S5 validation (Task 2). All 7 acceptance criteria map to tasks. ✓
- **Placeholder scan:** Every code step has actual code. No TBD. ✓
- **Type consistency:** `_process_file(path, project_path, skip_checksum_over_bytes) -> ResourceItem | None` — consistent across scanner rewrite + test monkeypatch. `scan_resources(..., max_workers=None)` keyword-only — consistent. ✓
- **Thread safety:** `_process_file` is module-level, uses only local variables + stateless helpers (classify_path, _checksum, relativize_path). No shared mutable state. ✓
- **Backward compat:** new `max_workers` param is keyword-only with `None` default; existing callers (`import_service`, bootstrap, tests) unaffected. ✓
