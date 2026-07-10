# Data Page Stress Harness + Hotspot Fixes Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Phase:** 21  
> **Related:**  
> - `docs/superpowers/specs/2026-07-10-datapage-ui-perf-optimization-design.md` (Phase 15)  
> - `docs/superpowers/specs/2026-07-09-data-management-page-redesign.md`  
> - `paleo_workbench/ui/pages/data_page.py`  
> - `paleo_workbench/ui/pages/preview_worker.py`  
> - `paleo_workbench/resources/import_service.py`  
> - `paleo_workbench/resources/scanner.py`

## Goal

**Phase 21 — Data page stress + evidence-driven hotspots**

1. Ship a **reproducible stress harness** for the data page under **2000+ assets**.  
2. Measure **update_state / filter / selection-preview / folder import** with printed timings.  
3. Fix the **top 1–2** measured hotspots only.

**Success criteria:**

- Harness runs under pytest and prints elapsed ms per scenario.  
- At least one production hotspot is fixed with unit coverage (default candidate: import scan checksum policy).  
- CI does **not** assert wall-clock thresholds.  
- Full suite stays green; Phase 15 contracts preserved.

### Decisions

| Dimension | Decision |
|-----------|----------|
| Scope | Data page only (plus `import_service` / `scanner` as used by data import) |
| Strategy | 方案 A — stress harness + evidence-driven 1–2 fixes |
| Success metric | Timing logs + human judgment; no hard CI latency gate |
| Default N | 2000 assets; import ~300 tiny tmp files |

## Non-Goals

- Hard CI p95 / wall-clock latency gates  
- Rewriting data page layout or floating-panel architecture  
- Unbounded real SEGY/LAS full-file parse in tests  
- Mapping scene or visualization load optimization  
- “Optimize all paths” without measurements  
- Server-side or SQLite project catalog  

## Current Baseline

Phase 15 already delivered:

- Virtual `QTableView` + `AssetTableModel`  
- `FilterIndex` + debounced search  
- Serial `PreviewRequestController` + generation tokens + LRU `PreviewCache`  
- Async import via `QThread` + batch UI refresh  

Known gaps:

- `import_files` / `import_folder` call `scan_resources` **without** `skip_checksum_over_bytes` (full SHA256 per file).  
- Bulk `update_state` may still pay full model + filter rebuild cost.  
- Rapid selection / media preload can still feel heavy under load (measure before changing).  
- No first-class stress scenarios that print timings.

## Architecture

```text
tests/perf/
  timing.py              # timed() / print [datapage-stress] lines
  fixtures.py            # make_mock_resources(n), make_tmp_tree(m)
tests/test_datapage_stress.py
  S1 update_state 2000
  S2 FilterIndex filter
  S3 rapid preview requests (stub provider)
  S4 import_folder ~300 tiny files
        │
        ▼  measurements rank hotspots
        │
production fixes (1–2):
  import_service → scan_resources(skip_checksum_over_bytes=…)
  optional: update_state / preview only if measured #2
```

**Boundary:** `tests/perf/` is test-only; production code stays free of stress harness imports.

## Stress scenarios

| ID | Scenario | Method | Assert (correctness) | Timing |
|----|----------|--------|----------------------|--------|
| **S1** | Bulk fill | `DataPage.update_state` with N mock `ResourceItem`s | Model/visible asset count == N | print ms |
| **S2** | Filter | `FilterIndex.rebuild` + `filter("all","")` and typed search | Stable counts | print ms |
| **S3** | Rapid select | `PreviewRequestController` + instant stub provider; 30 sequential requests | Latest generation wins; controller settles | print ms |
| **S4** | Folder import | tmp tree ~300 tiny files → `import_folder` | `added_count` ≈ file count | print ms |

**Constants:**

```python
STRESS_N = 2000                    # override via env DATAPAGE_STRESS_N optional
STRESS_IMPORT_FILES = 300
```

Optional heavier local runs: `N=5000` via env or `@pytest.mark.slow` (not required in default CI).

**Print format (stable for grepping):**

```text
[datapage-stress] S1_update n=2000 elapsed_ms=41.2
[datapage-stress] S2_filter_all n=2000 elapsed_ms=3.1
[datapage-stress] S3_rapid_select n=30 elapsed_ms=120.0
[datapage-stress] S4_import_folder n=300 elapsed_ms=800.5
```

**Timing helper:**

```python
@dataclass
class Timing:
    name: str
    ms: float

def timed(name: str, fn) -> Timing:
    ...
```

No mandatory baseline file in the repo; implementers may paste one local sample into `progress.md` after the fix.

## Hotspot backlog (fix only if measured)

| Expected rank | Area | Candidate fix |
|---------------|------|----------------|
| 1 | `import_folder` / `scan_resources` always SHA256 | Pass `skip_checksum_over_bytes` (default 50 MiB, same as bootstrap) from `import_service` |
| 2 | `update_state` full rebuild | Single model reset; avoid redundant FilterIndex rebuild if list unchanged |
| 3 | Preview media preload | Ensure generation cancel drops pending media work |
| 4 | Filter haystack | UI already debounced; avoid rebuild-on-every-filter if code path regresses |

### Phase 21 production commitment

1. **Always ship the harness (S1–S4).**  
2. **Always ship at least one production fix.** Default if S4 (or import path) dominates: **import checksum skip alignment**.  
3. **Optional second fix** only when clearly ranked #2 in local runs.

### Import checksum fix (detail)

**Problem:** `import_files` / `import_folder` call `scan_resources(...)` without skip → every file fully hashed.

**Fix:**

```python
DEFAULT_IMPORT_SKIP_CHECKSUM = 50 * 1024 * 1024

# import_folder / import_files scan_resources calls:
scan_resources(
    root_or_parent,
    project_path=project_path,
    skip_checksum_over_bytes=skip_checksum_over_bytes,  # default DEFAULT_IMPORT_SKIP_CHECKSUM
)
```

- Path-based dedupe unchanged.  
- Checksum-based dedupe only when `checksum` is present (existing behavior).  
- Unit test: file larger than threshold → `checksum is None` and `parsed_summary.checksum_skipped`.

**Secondary (only if measured):** `import_files` currently does `scan_resources(path.parent)` per path (may scan siblings). Fix only if S4/multi-file import shows it.

### update_state / preview fixes (conditional)

Do **not** change `DataPage.update_state` signature.

Only after measurement:

- Ensure one model reset per bulk set.  
- Preview: serial latest-only remains; stress proves no thread pile-up after rapid selects.

## Constraints (preserve Phase 15)

- Virtual table + floating catalog/actions layout  
- Serial preview queue + generation tokens + LRU cache  
- `update_state(state, resources, artifacts=None)` contract  
- Import / remove / rescan / open-folder semantics  

## Error handling

| Case | Behavior |
|------|----------|
| Stress tmp IO failure | pytest fails with path context |
| Import `OSError` mid-scan | Existing warnings list / report |
| Hotspot regression | Focused unit test + full suite |

## Testing strategy

| Layer | Rule |
|-------|------|
| Stress tests | Correctness + completion; **print** timings; **no** ms asserts |
| CI | Run default S1–S4 (N=2000 / 300 tiny files) |
| Unit | Production fix covered (e.g. checksum skip on import scan) |
| Regression | Full suite green |

Generous hang timeouts only if needed (e.g. 30–60s); not used as performance SLOs.

## Rollout slices

1. `tests/perf/timing.py` + `fixtures.py`  
2. `test_datapage_stress.py` S1–S4 (print timings)  
3. Local baseline note (optional in progress during implement)  
4. Import `skip_checksum_over_bytes` (or measured #1) + unit tests  
5. Optional second hotspot fix  
6. Docs: `task_plan.md` / `progress.md` Phase 21  

## Acceptance checklist

- [ ] S1–S4 exist and print `[datapage-stress]` lines  
- [ ] Correctness asserts only (counts, latest-only, no hang)  
- [ ] No CI wall-clock threshold asserts  
- [ ] ≥1 production hotspot fix with unit test  
- [ ] Phase 15 data-page contracts preserved  
- [ ] Full pytest green  
- [ ] Planning docs updated  

## Open follow-ups (not Phase 21)

- Mapping / viz performance phases  
- CI latency budgets with calibrated hardware  
- Persistent baseline JSON in repo  
- SQLite or disk index for 10k+ assets  

## Success criteria (program)

1. Anyone can re-run data-page stress and see numbers.  
2. Bulk import (or the measured #1 path) is materially lighter after the fix.  
3. 2000+ mock assets remain correct and stable under the harness.
