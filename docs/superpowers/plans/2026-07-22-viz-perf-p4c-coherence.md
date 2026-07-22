# P4-C coherence 修正 + crossover_fill 删除 + 文档纠偏 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 `compute_coherence_3d`（`sample_window` 生效 + 消除冗余计算）、删除无调用者且算法不正确的 `generate_crossover_fill`、纠偏 `task_plan.md` Phase 9 "C++ 多线程"表述。

**Architecture:** 只动 workbench 仓库（`native/`、`paleo_workbench/viz/`、`tests/`、文档），geo-viz-engine 不涉及。C++ 扩展修改后用 `pip install -e` 原地重建；Python 保底实现与 C++ 保持逐点 parity。

**Tech Stack:** C++17 / pybind11 / NumPy / pytest。

## Global Constraints

- 不引入新第三方依赖。
- `compute_coherence_3d` 保持 GIL 释放（`py::gil_scoped_release`）。
- `compute_coherence_3d` 与 `generate_crossover_fill` 均已确认无生产调用者（全仓库 grep 仅命中 spec、task_plan.md、native 源、`viz/*_api.py`、tests），改动面可控。
- C++ 重建命令（工作目录 `/home/kevin/projects/paleo_project`）：
  - `.venv/bin/python -m pip install -e native/seismic_3d_core --no-build-isolation -q`
  - `.venv/bin/python -m pip install -e native/well_log_core --no-build-isolation -q`
- pytest 一律用 `.venv/bin/python -m pytest`。
- 提交到 workbench 仓库 main 分支；提交前确认 `git status` 干净、HEAD 在 main（本仓库有并行会话活动）。
- 新 coherence 语义（C++ 与 Python 保底必须一致）：
  - 输出体与输入同形状，边缘列（`i < half_i` 等空间边缘）保持 1.0。
  - 对每个输出采样点 `(i, j, k)`：垂直窗 `k0 = max(0, k-half_t)`，`k1 = min(nt-1, k+half_t)`（含端点，`half_t = sample_window/2`）。
  - `num(k) = Σ_{k'=k0..k1} mean_spatial(v[k'])²`；`den(k) = mean_{k'=k0..k1}(Σ_spatial v[k']²) + 1e-12`；`coh = clip(num/den, 0, 1)`。
  - 空间均值/平方和在 `(2·half_i+1)×(2·half_x+1)` 窗口上取。
  - `sample_window=1` 时垂直窗退化为单点，结果沿 t 逐点变化——这是"sample_window 生效"的可测语义。

---

### Task 1: `compute_coherence_3d` 修正（C++ + Python 保底 + 测试）

**Files:**
- Modify: `native/seismic_3d_core/src/seismic_3d_core.cpp:154-207`
- Modify: `paleo_workbench/viz/seismic_3d_api.py:70-101`
- Test: `tests/test_seismic_3d_cpp.py`、`tests/test_seismic_3d_api.py`

**Interfaces:**
- Consumes: 无前置任务。
- Produces: `compute_coherence_3d(volume, inline_window=3, crossline_window=3, sample_window=3) -> np.ndarray`（签名不变，语义按 Global Constraints 更新）。

- [ ] **Step 1: 写失败测试（semantic + parity 扩展）**

在 `tests/test_seismic_3d_api.py` 末尾追加：

```python
def test_compute_coherence_3d_sample_window_takes_effect():
    np.random.seed(7)
    vol = np.random.randn(8, 8, 12).astype(np.float32)

    coh_w1 = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=1)
    coh_w5 = compute_coherence_3d(vol, inline_window=3, crossline_window=3, sample_window=5)

    assert coh_w1.shape == coh_w5.shape == vol.shape
    # sample_window 生效后，不同垂直窗的结果必须不同
    assert not np.allclose(coh_w1, coh_w5)
```

将 `tests/test_seismic_3d_cpp.py` 的 `test_compute_coherence_3d_parity_with_python` 整函数替换为：

```python
@pytest.mark.parametrize("sample_window", [1, 3, 5])
def test_compute_coherence_3d_parity_with_python(sample_window):
    np.random.seed(123)
    vol = np.random.randn(8, 8, 10).astype(np.float32)

    # C++ path
    coh_cpp = compute_coherence_3d(
        vol, inline_window=3, crossline_window=3, sample_window=sample_window
    )

    # Force Python fallback path
    with patch.object(seismic_3d_api, "HAS_CPP_SEISMIC", False):
        coh_py = compute_coherence_3d(
            vol, inline_window=3, crossline_window=3, sample_window=sample_window
        )

    np.testing.assert_allclose(coh_cpp, coh_py, rtol=1e-4, atol=1e-4)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_seismic_3d_api.py::test_compute_coherence_3d_sample_window_takes_effect -x -q`
Expected: FAIL（当前实现忽略 `sample_window`，w1 与 w5 结果完全相同，`np.allclose` 为 True）

- [ ] **Step 3: 改 C++ 实现**

将 `native/seismic_3d_core/src/seismic_3d_core.cpp` 中 `compute_coherence_3d` 整函数（154-207 行）替换为：

```cpp
// 3D Coherence Attribute Calculation
py::array_t<float> compute_coherence_3d(py::array_t<float, py::array::c_style | py::array::forcecast> input, int inline_window, int crossline_window, int sample_window) {
    auto buf = input.request();
    if (buf.ndim != 3) {
        throw std::runtime_error("Input volume must be 3D");
    }

    size_t ni = buf.shape[0];
    size_t nx = buf.shape[1];
    size_t nt = buf.shape[2];
    const float* src = static_cast<const float*>(buf.ptr);

    auto result = py::array_t<float>({ni, nx, nt});
    auto r_buf = result.request();
    float* dst = static_cast<float*>(r_buf.ptr);
    std::fill(dst, dst + ni * nx * nt, 1.0f);

    int half_i = inline_window / 2;
    int half_x = crossline_window / 2;
    int half_t = sample_window / 2;
    double n_spatial = static_cast<double>((2 * half_i + 1) * (2 * half_x + 1));

    std::vector<double> mean_sq(nt);
    std::vector<double> sum_sq(nt);

    {
        py::gil_scoped_release release;
        for (int i = half_i; i < static_cast<int>(ni) - half_i; ++i) {
            for (int j = half_x; j < static_cast<int>(nx) - half_x; ++j) {
                // Per-sample spatial statistics for this trace column (computed once).
                for (size_t k = 0; k < nt; ++k) {
                    double trace_sum = 0.0;
                    double trace_sq_sum = 0.0;
                    for (int di = -half_i; di <= half_i; ++di) {
                        for (int dj = -half_x; dj <= half_x; ++dj) {
                            float v = src[(i + di) * (nx * nt) + (j + dj) * nt + k];
                            trace_sum += v;
                            trace_sq_sum += v * v;
                        }
                    }
                    double mean_val = trace_sum / n_spatial;
                    mean_sq[k] = mean_val * mean_val;
                    sum_sq[k] = trace_sq_sum;
                }

                // Running-sum over the clamped vertical window [k0, k1].
                int k0 = 0;
                int k1 = std::min(static_cast<int>(nt) - 1, half_t);
                double run_num = 0.0;
                double run_den = 0.0;
                for (int k = k0; k <= k1; ++k) {
                    run_num += mean_sq[k];
                    run_den += sum_sq[k];
                }
                for (size_t k = 0; k < nt; ++k) {
                    double den = run_den / static_cast<double>(k1 - k0 + 1) + 1e-12;
                    float coh_val = static_cast<float>(std::min(1.0, std::max(0.0, run_num / den)));
                    dst[i * (nx * nt) + j * nt + k] = coh_val;

                    // Advance window for k+1.
                    if (static_cast<int>(k) + 1 < static_cast<int>(nt)) {
                        int new_lo = std::max(0, static_cast<int>(k) + 1 - half_t);
                        int new_hi = std::min(static_cast<int>(nt) - 1, static_cast<int>(k) + 1 + half_t);
                        while (k1 < new_hi) {
                            ++k1;
                            run_num += mean_sq[k1];
                            run_den += sum_sq[k1];
                        }
                        while (k0 < new_lo) {
                            run_num -= mean_sq[k0];
                            run_den -= sum_sq[k0];
                            ++k0;
                        }
                    }
                }
            }
        }
    }
    return result;
}
```

- [ ] **Step 4: 改 Python 保底实现（与 C++ 同语义）**

将 `paleo_workbench/viz/seismic_3d_api.py` 中 `compute_coherence_3d` 的保底部分（82-101 行，即 `vol = np.asarray(...)` 起到 `return coh`）替换为：

```python
    vol = np.asarray(volume, dtype=np.float32)
    ni, nx, nt = vol.shape
    coh = np.ones_like(vol, dtype=np.float32)

    half_i = inline_window // 2
    half_x = crossline_window // 2
    half_t = sample_window // 2

    ks = np.arange(nt)
    k0 = np.maximum(0, ks - half_t)
    k1 = np.minimum(nt, ks + half_t + 1)  # exclusive upper bound
    win_len = (k1 - k0).astype(np.float64)

    for i in range(half_i, ni - half_i):
        for j in range(half_x, nx - half_x):
            sub = vol[
                i - half_i : i + half_i + 1,
                j - half_x : j + half_x + 1,
                :,
            ].astype(np.float64)
            mean_sq = np.mean(sub, axis=(0, 1)) ** 2  # (nt,)
            sum_sq = np.sum(sub**2, axis=(0, 1))      # (nt,)
            cs_num = np.concatenate([[0.0], np.cumsum(mean_sq)])
            cs_den = np.concatenate([[0.0], np.cumsum(sum_sq)])
            num = cs_num[k1] - cs_num[k0]
            den = (cs_den[k1] - cs_den[k0]) / win_len + 1e-12
            coh[i, j, :] = np.clip(num / den, 0.0, 1.0)

    return coh
```

同时把该函数 docstring 由 `"""Compute 3D seismic coherence/similarity volume."""` 改为：

```python
    """Compute 3D seismic coherence/similarity volume (per-sample vertical window)."""
```

- [ ] **Step 5: 重建 C++ 扩展**

Run: `.venv/bin/python -m pip install -e native/seismic_3d_core --no-build-isolation -q`
Expected: 无错误输出。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_seismic_3d_cpp.py tests/test_seismic_3d_api.py -q`
Expected: 全部 PASS（含 3 个 parametrized parity 用例与 sample_window 语义用例）。

- [ ] **Step 7: Commit**

```bash
git add native/seismic_3d_core/src/seismic_3d_core.cpp paleo_workbench/viz/seismic_3d_api.py tests/test_seismic_3d_cpp.py tests/test_seismic_3d_api.py
git commit -m "fix(seismic): honor sample_window in compute_coherence_3d with running-sum window"
```

---

### Task 2: 删除 `generate_crossover_fill`

**Files:**
- Modify: `native/well_log_core/src/well_log_core.cpp:235-277`（函数）与 `:283`（pybind 绑定）
- Modify: `paleo_workbench/viz/well_log_api.py:16`（`__all__`）与 `:112-138`（wrapper）
- Test: `tests/test_well_log_cpp.py`、`tests/test_well_log_api.py`

**Interfaces:**
- Consumes: 无（与 Task 1 独立）。
- Produces: 无（纯删除）。删除后 `well_log_core` 仅剩 `minmax_downsample`、`fast_las_parse_data`；`well_log_api.py` 的 `__all__` 为 `["HAS_CPP_WELL_LOG", "fast_las_parse_data", "minmax_downsample"]`。

- [ ] **Step 1: 删除测试（先删测试函数与 import）**

- `tests/test_well_log_cpp.py`：删除 `test_generate_crossover_fill_parity_with_python` 整函数（57-70 行）；import 块中删除 `generate_crossover_fill,` 一行。
- `tests/test_well_log_api.py`：删除 `test_generate_crossover_fill_vertices` 整函数（55-64 行）；import 块中删除 `generate_crossover_fill,` 一行。

- [ ] **Step 2: 运行测试确认删除后 import 报错**

Run: `.venv/bin/python -m pytest tests/test_well_log_cpp.py tests/test_well_log_api.py -q`
Expected: 收集阶段 ImportError（`generate_crossover_fill` 仍在生产代码中但测试已不引用——实际应为 PASS；本步骤真实目的：确认无其他测试引用该符号。若出现意外失败说明有遗漏引用，先排查再继续。）

- [ ] **Step 3: 删除生产代码**

- `native/well_log_core/src/well_log_core.cpp`：删除 `// Crossover Fill Vertices Generator` 注释起的整个 `generate_crossover_fill` 函数（235-277 行）；删除 PYBIND11_MODULE 中 `m.def("generate_crossover_fill", ...)` 一行（283 行）。
- `paleo_workbench/viz/well_log_api.py`：删除 `generate_crossover_fill` 整个 wrapper 函数（112-138 行）；`__all__` 中删除 `"generate_crossover_fill",` 一行。

- [ ] **Step 4: 重建 C++ 扩展**

Run: `.venv/bin/python -m pip install -e native/well_log_core --no-build-isolation -q`
Expected: 无错误输出。

- [ ] **Step 5: 运行测试 + 全仓库引用扫描**

Run: `.venv/bin/python -m pytest tests/test_well_log_cpp.py tests/test_well_log_api.py -q`
Expected: 全部 PASS。

Run: `grep -rn "generate_crossover_fill" --include='*.py' --include='*.cpp' --include='*.h' native paleo_workbench tests geo-viz-engine/geoviz 2>/dev/null`
Expected: 无输出（仅 docs/task_plan.md 历史记录保留，属预期）。

- [ ] **Step 6: Commit**

```bash
git add native/well_log_core/src/well_log_core.cpp paleo_workbench/viz/well_log_api.py tests/test_well_log_cpp.py tests/test_well_log_api.py
git commit -m "chore(well-log): drop unused and incorrect generate_crossover_fill"
```

---

### Task 3: 文档纠偏 + 全量回归

**Files:**
- Modify: `task_plan.md:129`
- Modify: `progress.md`（根目录，追加 P4-C 记录）

**Interfaces:**
- Consumes: Task 1、Task 2 的提交（回归需覆盖其改动）。
- Produces: 无代码接口。

- [ ] **Step 1: 纠偏 task_plan.md Phase 9 表述**

`task_plan.md:129` 原文：

```
| 采用 pybind11 构建 `seismic_3d_core` 原生模块 | 在纯 Python / NumPy 算法保底的前提下，通过 C++ 多线程与内存连续性提供高效震相计算与切片提取。 |
```

改为：

```
| 采用 pybind11 构建 `seismic_3d_core` 原生模块 | 在纯 Python / NumPy 算法保底的前提下，通过 C++ 单线程计算（释放 GIL）与内存连续性提供高效震相计算与切片提取。 |
```

- [ ] **Step 2: progress.md 追加 P4-C 记录**

在 `progress.md` 顶部（最新条目处）追加：

```markdown
## P4-C coherence 修正 + crossover_fill 删除（2026-07-22）

- `compute_coherence_3d`：`sample_window` 生效（垂直窗参与相干计算，边缘截断窗）；内层改按列计算 + running-sum，消除逐点重算窗口的冗余；保持 GIL 释放；C++/Python parity 扩展至 sample_window ∈ {1,3,5}。
- `generate_crossover_fill` 删除（无生产调用者且算法不正确）：C++ 函数、pybind 绑定、`well_log_api.py` wrapper 与相关测试一并移除（git 历史可恢复）。
- `task_plan.md` Phase 9 "C++ 多线程"表述纠偏为"单线程（释放 GIL）"。
```

（日期以实际执行日为准。）

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 全绿（已知偶发 flake：`test_project_lifecycle.py` 3 变体与 `test_workflow_controller_api.py` 1 个——若出现，单独重跑确认通过即可）。

- [ ] **Step 4: Commit**

```bash
git add task_plan.md progress.md docs/superpowers/specs/2026-07-21-viz-perf-hardening-design.md docs/superpowers/plans/2026-07-22-viz-perf-p4c-coherence.md
git commit -m "docs: record P4-C coherence fix and correct Phase 9 C++ threading wording"
```

（注：spec 文件 `docs/superpowers/specs/2026-07-21-viz-perf-hardening-design.md` 此前被并行会话误删、已从 git 恢复到工作区，随本提交一并补回。）

---

## Self-Review 结论

- **Spec 覆盖**：阶段 C 三项（coherence 修正 / crossover_fill 删除 / task_plan 纠偏 + progress.md 记录）分别对应 Task 1 / 2 / 3，无遗漏。测试策略中"coherence parity（含非默认 sample_window 用例）"由 Task 1 Step 1 的 parametrize {1,3,5} 覆盖。
- **Placeholder 扫描**：无 TBD/省略，所有代码与命令完整。
- **类型一致性**：`compute_coherence_3d` 签名三处（C++ pybind、Python wrapper、测试调用）一致；删除项无后续引用。
- **明确不动**：`task_plan.md` Phase 7 行 57 对 `generate_crossover_fill` 的历史记录保留（当时属实）；`marching_cubes_3d` 属 P5，不动。
