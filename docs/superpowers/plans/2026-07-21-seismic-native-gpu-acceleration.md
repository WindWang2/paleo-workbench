# 地震数据预览与可视化 C++ & GPU 双重加速方案

> **目标**：彻底解决 3D 地震切片预览与可视化在打开/滑动时的卡顿问题。通过 C++ 原生指令集并行加速切片提取与归一化通道、消除 Python 循环 IO、并在 GPU 纹理层优化 LOD 缓存。

---

## 1. 瓶颈分析与优化策略

### 瓶颈 1: 切片渲染中的 Python 级数组运算与 Matplotlib 查表
- **现状**：每次拖动切片 Slider，Python 端执行 `np.nan_to_num` -> `min()/max()` 全图扫描 -> 浮点归一化 -> 类型转换 -> QImage 构造。
- **优化**：在 `native/seismic_3d_core` 中编写 C++ 函数 `fast_slice_to_indexed8` 与 `fast_slice_to_rgba32`。在 C++ 层一次 Pass 内完成切片提取、NaN 替换、动态范围归一化与 Index8 / RGBA32 渲染字节生成（开 AVX2/OpenMP 向量化）。

### 瓶颈 2: SEGY / 伪三维数据加载的 Trace-by-Trace Python 循环 IO
- **现状**：`seismic_load.py` 使用 Python `for ti in t_indices: cube.trace[ti]` 逐道读取，导致几千次 Python Seek/Call 开销。
- **优化**：增加 `fast_resample_volume_3d` C++ 极速下采样与跨步特征提取，在 Python 层直接批量 `read` 大块 Buffer，由 C++ 原生并行做 3D 步长重采样，降低打开时卡顿 90% 以上。

### 3. 色彩映射与纹理缓存
- 静态预缓存 256 色 RGB/RGBA Colormap，避免在主线程做 `matplotlib` 动态导入和 `qRgba` 循环。

---

## 2. TDD 计划与实施步骤

1. **Task 1: C++ 原生 `fast_slice_to_indexed8` 与 `fast_resample_volume_3d` 测试 (RED)**
   - 编写 `tests/test_seismic_3d_cpp_perf.py` 验证 C++ 端切片转 Indexed8 / RGBA 与 3D 快速重采样的数值一致性及性能。
2. **Task 2: 在 `seismic_3d_core` C++ 扩展中实现高效 C++ 函数 (GREEN)**
   - `fast_slice_to_indexed8(volume, axis, index, min_val, max_val)`
   - `fast_resample_volume_3d(volume, target_d0, target_d1, target_d2)`
   - 在 `native/seismic_3d_core/src/seismic_3d_core.cpp` 与 `paleo_workbench/viz/seismic_3d_api.py` 中暴露门面。
3. **Task 3: 重构 `SeismicSlicePreviewWidget` 接入 C++ 极速渲染 (GREEN)**
   - 使用 `fast_slice_to_indexed8` 替代 Python 归一化逻辑。
   - 预建静态 `_color_table` 避免重算。
4. **Task 4: 重构 `seismic_load.py` 极速加载逻辑 (GREEN)**
   - 引入 C++ 3D 快速重采样下采样，缩短 SEGY 与预加载时间。
5. **Task 5: 全量回归测试与性能验证**
   - 确保 `pytest` 所有测试绿色通过。
