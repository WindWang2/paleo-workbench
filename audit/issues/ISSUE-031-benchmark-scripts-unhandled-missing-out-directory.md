# ISSUE-031: Unhandled `FileNotFoundError` in Benchmark Scripts on Missing `--out` Directory

- **Severity**: Low
- **Subproject**: `scripts` (`scripts/`)
- **Target File**:
  - `file:///home/kevin/projects/paleo_project/main/scripts/bench_factor_grid_pipeline.py#L211-L213`
  - `file:///home/kevin/projects/paleo_project/main/scripts/bench_interpolation.py#L225-L229`

---

## Defect Description & Root Cause Analysis

In `scripts/bench_factor_grid_pipeline.py` and `scripts/bench_interpolation.py`, benchmark results are saved to disk using:

```python
# bench_factor_grid_pipeline.py:211
if args.out:
    Path(args.out).write_text(text + "\n", encoding="utf-8")

# bench_interpolation.py:225
if args.out:
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.write("\n")
```

Neither script ensures the parent directory of `args.out` exists prior to opening the file.

When a benchmark is run with a path pointing to a non-existent directory (e.g. `--out benchmark_results/run1.json` or `--out /tmp/benchmarks/summary.json`), the script completes all lengthy calculation loops and then crashes with `FileNotFoundError: [Errno 2] No such file or directory`, discarding all computed benchmark metrics.

---

## Impact Analysis

- **Benchmark Workflow Disruption**: Lengthy benchmark runs fail at the final reporting step and discard all performance data.

---

## Reproduction Scenario & Execution Proof

### Code Trace
```bash
python scripts/bench_interpolation.py --out non_existent_dir/output.json
# Calculates all benchmark iterations...
# Crashes with: FileNotFoundError: [Errno 2] No such file or directory: 'non_existent_dir/output.json'
```

---

## Concrete Suggested Fix

Create the parent directory with `parents=True, exist_ok=True` before writing output:

### Patch (`scripts/bench_factor_grid_pipeline.py` & `scripts/bench_interpolation.py`)
```python
if args.out:
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text + "\n", encoding="utf-8")
```
