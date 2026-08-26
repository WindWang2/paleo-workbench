# ISSUE-006: Uncaught `ImportError` on Missing cuBLAS in `compute_coherence_c3`

- **Severity**: High
- **Subproject**: `geo-viz-engine` (`geo-viz-engine/packages/geoviz_seismic`)
- **Target File**: `file:///home/kevin/projects/paleo_project/main/geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/attributes.py#L149-L156,L208-L212`

---

## Defect Description & Root Cause Analysis

In `geoviz_seismic/attributes.py`, GPU acceleration detection for seismic attribute extraction is initialized at module load time:

```python
try:
    import cupy as cp
    _has_cupy = True
except Exception:
    _has_cupy = False
```

When CuPy is installed in the Python environment but the system lacks the underlying CUDA Toolkit runtime libraries (specifically `libcublas.so.12` / `cublas64_12.dll`), `import cupy` succeeds.

However, during execution of `compute_coherence_c3()` with `gpu=True` (or `gpu=None` when `_has_cupy` is True), `_power_iteration_c3(traces_gpu, n_power_iter)` invokes `cp.matmul()`. CuPy attempts to dynamically lazy-load `cupy_backends.cuda.libs.cublas`, which fails with:
`ImportError: libcublas.so.12: cannot open shared object file: No such file or directory`

Because the GPU execution branch in `compute_coherence_c3` lacks exception handling and fallback to NumPy, the unhandled `ImportError` propagates up and crashes the calling application.

---

## Impact Analysis

- **Application Crash**: Seismic 3D coherence volume calculations terminate with an unhandled exception on systems where CuPy wheels are present without complete CUDA runtime shared libraries.
- **CI Test Failures**: Automated GPU consistency tests crash under headless CI runners.

---

## Reproduction Scenario & Execution Proof

### Pytest Execution Trace
```bash
pytest geo-viz-engine/tests/test_coherence.py::TestCoherenceC3GpuConsistency::test_gpu_matches_cpu
```

### Traceback Output:
```
cupy_backends/cuda/libs/cublas.pyx:1: in init cupy_backends.cuda.libs.cublas
    ???
E   ImportError: libcublas.so.12: cannot open shared object file: No such file or directory
```

---

## Concrete Suggested Fix

Wrap the GPU computation path in a `try...except Exception:` block to gracefully fall back to CPU NumPy calculations upon runtime CUDA/cuBLAS library errors.

### Patch (`geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/attributes.py`)
```python
# In compute_coherence_c3():
if gpu_active:
    try:
        traces_gpu = cp.asarray(traces)
        coh = _power_iteration_c3(traces_gpu, n_power_iter)
        coh = cp.asnumpy(coh).astype(np.float32)
    except Exception:
        coh = _power_iteration_c3(traces, n_power_iter).astype(np.float32)
else:
    coh = _power_iteration_c3(traces, n_power_iter).astype(np.float32)
```
