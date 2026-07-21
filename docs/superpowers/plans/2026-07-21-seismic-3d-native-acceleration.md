# 3D 地震核心算法 C++ 原生加速 (seismic_3d_core) 实施计划与 TDD 指南

> **开发范式**：严格遵守 TDD（测试驱动开发）——先编写针对契约与算法的失败测试（RED），再编写 Python/C++ 功能代码通过测试（GREEN），最后重构与回归全量测试（REFACTOR）。

---

## 一、 设计目标与架构设计

在 `paleo_workbench/viz/` 下建立 `seismic_3d_api.py` 纯 Python 门面，结合 `native/seismic_3d_core`（pybind11 + C++17）双路径机制：

1. **`fast_slice_extract`**：从 3D 震旦数据体 (`shape=(inline, crossline, sample)`) 中提取任意平面的 2D 切片，C++ 路径提供零拷贝 Stride 切片与极速内存复用。
2. **`compute_coherence_3d`**：三维震相相干/相似性属性计算（C3 算法），多线程 (OpenMP) 并行计算窗口归一化互相关。
3. **`marching_cubes_3d`**：三维地层/相面等值面网格提取算法，输出顶点 `vertices` 与三角面片 `faces`。

---

## 二、 任务拆解与 TDD 开发步骤

### Task 1: 编写纯 Python 门面 `seismic_3d_api.py` 与 TDD 测试 (RED ➔ GREEN)

- **测试先行 (RED)**：编写 `tests/test_seismic_3d_api.py`，测试切片提取、相干计算、Marching Cubes 算法输出格式及 `HAS_CPP_SEISMIC` 状态标志。
- **实现代码 (GREEN)**：创建 `paleo_workbench/viz/seismic_3d_api.py`，实现全套 NumPy 纯 Python 回退（Fallback）算法逻辑。

### Task 2: 搭建 C++ 扩展目录与 pybind11 绑定结构

- 新建 `native/seismic_3d_core/pyproject.toml`
- 新建 `native/seismic_3d_core/setup.py`
- 新建 `native/seismic_3d_core/src/seismic_3d_core.cpp`

### Task 3: 编写 C++ 算法实现与数值等价性 TDD 测试 (RED ➔ GREEN)

- **测试先行 (RED)**：编写 `tests/test_seismic_3d_cpp.py`，断言当 C++ 扩展载入时，`seismic_3d_api` 自动路由至 C++ 原生引擎，且输出数值与 Python 路径完全一致。
- **实现代码 (GREEN)**：在 `seismic_3d_core.cpp` 中实现 C++ 核心加速算法并完成本地构建 (`python setup.py build_ext --inplace`)。

### Task 4: 地震预览集成与可视化挂载

- 将 `seismic_3d_api` 接入 `seismic_parsers.py` 与 `seismic_slice_preview_widget.py`。

### Task 5: 全量回归与性能验证

- 运行 `pytest` 确保 100% 全绿（包含新的 3D 地震算法测试与全量项目测试）。
