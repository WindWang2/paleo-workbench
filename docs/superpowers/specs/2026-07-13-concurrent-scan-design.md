# Concurrent Resource Scan Design (Phase C)

> **Date:** 2026-07-13
> **Status:** Approved (pending spec review)
> **Scope:** Parallelize `scan_resources` file processing (stat + checksum) via ThreadPoolExecutor; add an N=10000 stress scenario to the Phase 21 harness for validation.
> **Predecessor:** Phase 21 stress harness + checksum skip (`docs/superpowers/specs/2026-07-10-datapage-stress-hotspots-design.md`).

## Goal

Make folder import materially faster by parallelizing the per-file work in `scan_resources`: file `stat()`, `classify_path()`, and `_checksum()` (SHA256). Today this runs serially in a single thread; for a folder of hundreds of files (many requiring full checksum under the 50 MiB threshold), this is the dominant cost.

Validate the improvement with an N=10000 stress scenario (S5) comparing serial vs concurrent scan timing, added to the existing Phase 21 harness.

## Context

Phase 21 already shipped:
- Stress harness S1–S4 (printed `[datapage-stress]` timings; no CI wall-clock gates).
- `scan_resources(..., skip_checksum_over_bytes=50MiB)` — files over 50 MiB skip checksum entirely.

Phase 15 already shipped:
- Virtual `QTableView` + `AssetTableModel` (S1 measured ~4ms at N=2000 — not a hotspot).
- Debounced search (180ms `QTimer`) + `FilterIndex` reuse (no rebuild-on-every-filter; S2 measured ~0.5ms — not a hotspot).

So virtual scrolling, search debounce, and search index are **done and non-hotspots**. The only remaining real gap is **serial scan**.

## Why ThreadPoolExecutor

- `stat()` is a syscall (releases GIL during the kernel call).
- `hashlib.sha256` is a C extension that **releases the GIL** during the hash computation.
- `path.open("rb") / read()` is I/O (releases GIL).
- Therefore a thread pool achieves real parallelism for both the I/O and CPU portions without process overhead.
- `ProcessPoolExecutor` would add serialization cost for the resulting `ResourceItem` objects and process spawn latency — not worth it given GIL is released.
- `asyncio` would complicate the synchronous codebase and the checksum CPU work doesn't benefit from async.

## Design

### `scan_resources` rewrite

Current (serial):
```python
for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
    ... stat, classify, checksum, append ...
```

New (concurrent file processing, serial result assembly to preserve order):
```python
from concurrent.futures import ThreadPoolExecutor
import os

def scan_resources(
    root: Path,
    project_path: Path | None = None,
    *,
    skip_checksum_over_bytes: int | None = None,
    max_workers: int | None = None,
) -> list[ResourceItem]:
    candidates = sorted(c for c in root.rglob("*") if c.is_file() and not c.name.startswith("._"))
    if not candidates:
        return []

    workers = max_workers or min(32, (os.cpu_count() or 1) + 4)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        processed = list(pool.map(
            lambda p: _process_file(p, project_path, skip_checksum_over_bytes),
            candidates,
        ))
    return [r for r in processed if r is not None]
```

`_process_file` (new helper, extracted from the loop body) does: classify + stat + checksum + build `ResourceItem`. Returns `None` on hard failure (e.g., file vanished between rglob and stat — `OSError` on stat → skip gracefully, consistent with current behavior where checksum OSError sets a flag but still appends; the difference: stat OSError means we can't build a ResourceItem at all, so skip).

### Order preservation

`pool.map` returns results in submission order (same as `candidates` sorted order). Result order is identical to the serial version — no behavior change for deterministic tests.

### `max_workers` parameter

- Default: `min(32, cpu_count + 4)` (the `ThreadPoolExecutor` convention from Python 3.8+; bounded to avoid thread explosion on high-core machines for small file sets).
- Exposed as a parameter so tests can force `max_workers=1` to verify serial-equivalence and `max_workers=N` for concurrency.

### Error handling

- `stat()` `OSError` (file vanished): `_process_file` returns `None`; filtered out of results. This is a behavior refinement over today (today a stat OSError would raise uncaught) — but in practice `rglob` files rarely vanish; the graceful skip is safer than crashing the whole scan.
- `_checksum()` `OSError`: unchanged — sets `summary["checksum_error"] = True`, `checksum = None`, still appends the resource (current behavior preserved).
- `classify_path`: pure function, no failure path.

## Stress validation: S5 (N=10000)

Add a new scenario to `tests/test_datapage_stress.py`:

```python
def test_stress_S5_scan_concurrent_large(monkeypatch, tmp_path):
    """N=10000 tiny files: concurrent scan completes; timing printed."""
    n = 10000
    # ... create n tiny tmp files ...
    timing_concurrent = timed("S5_scan_concurrent", lambda: scan_resources(tmp_path))
    print(f"[datapage-stress] S5_scan_concurrent n={n} elapsed_ms={timing_concurrent.ms:.1f}")
    assert len(resources) == n  # correctness
```

Also add a serial-comparison variant (`max_workers=1`) so the printed output shows both numbers side by side:

```python
    timing_serial = timed("S5_scan_serial", lambda: scan_resources(tmp_path, max_workers=1))
    print(f"[datapage-stress] S5_scan_serial n={n} elapsed_ms={timing_serial.ms:.1f}")
```

No CI wall-clock assertion (consistent with Phase 21's "print timings, no hard gates"). The test asserts **correctness** (resource count matches file count; order preserved) and **prints** both timings for human comparison.

`S5` is env-gated (skipped unless `DATAPAGE_STRESS_N` is set, OR a new `DATAPAGE_STRESS_S5=1` opt-in env var) so the 10k-file creation doesn't slow the default CI loop. The existing S1–S4 already run by default with a fixed N=2000; S5's 10k file creation is heavier, so it's opt-in only. When skipped, print a skip reason line for visibility.

## Testing

### Unit tests (`tests/test_resources_scanner.py` or `test_resources_classifier.py` neighbor)

- `test_scan_concurrent_preserves_order`: scan a tmp dir with files a, b, c → results in name-sorted order (same as serial).
- `test_scan_concurrent_results_match_serial`: scan same dir with `max_workers=1` and `max_workers=4` → identical ResourceItem lists (name, path, type, format, checksum, size).
- `test_scan_concurrent_handles_empty_dir`: empty dir → `[]`.
- `test_scan_concurrent_checksums_correct`: file with known content → checksum matches independent SHA256.
- `test_scan_concurrent_vanished_file_skipped`: (harder to test deterministically — mock `_process_file` to return None for one file → result excludes it). Use a monkeypatch or a file that raises on stat.
- `test_scan_max_workers_parameter`: `max_workers=1` runs serially; `max_workers=8` runs concurrently.

### Stress test (S5)

- Correctness: `len(scan_resources(tmp)) == n`.
- Order: first resource name < last resource name (sorted).
- Prints `[datapage-stress] S5_scan_concurrent` + `S5_scan_serial` lines.

### Regression

All existing tests (625) must pass. The `scan_resources` signature is backward-compatible (new `max_workers` param is keyword-only with a default).

## Acceptance Criteria

1. `scan_resources` processes files concurrently via `ThreadPoolExecutor`.
2. Results are identical to serial scan (order + content) — verified by `max_workers=1` vs default comparison test.
3. `skip_checksum_over_bytes` behavior unchanged.
4. `max_workers` parameter exposed for testing/tuning.
5. S5 stress scenario (N=10000) passes correctness + prints concurrent vs serial timings.
6. All 625 existing tests pass.
7. Backward-compatible signature (existing callers unaffected).

## Non-Goals

- Inverted search index (FilterIndex linear scan is fast enough at 0.5ms — YAGNI).
- Virtual scrolling changes (Phase 15 done, non-hotspot).
- ProcessPoolExecutor or asyncio.
- Persistent disk/SQLite index for 10k+ assets (open follow-up from Phase 21).
- CI wall-clock latency gates.

## Risks

- **GIL contention on pure-Python paths**: `classify_path` is pure Python (holds GIL briefly) but trivially fast (string matching); the GIL-releasing work (stat, file read, hashlib) dominates. Net win expected.
- **Thread-safety of `_checksum`/`classify_path`**: both are stateless pure functions (no shared mutable state) — safe under threads.
- **File-handle exhaustion on huge dirs**: 10000 files with `max_workers=32` means ≤32 open handles at a time — well within limits.
- **`pool.map` memory**: holds all results in memory — same as serial (the serial version also builds a full list). No regression.
