# 分块访问 API 草案（#1072 原型产出，供 #1073/#1074/#1075 引用）

**原型**：`prototypes/chunked_access/reader.py`（分支 `prototype/chunked-access-api`，可扔参考实现）
**实测数据**：`demo.py` 输出（quick2g = 内置 NVMe 暖；g100 = 外置 USB-NTFS 冷，#1069 基线）

## 1. API 形态（与 `SeismicLoader` 同名同义 + LOD 扩展）

```python
class ChunkedVolumeReader:
    # 与 SeismicLoader 完全同签名（消费方零改动切换）：
    read_inline(iline) -> np.ndarray          # (nxl, nt) float32
    read_crossline(xline) -> np.ndarray
    read_timeslice(sample_idx) -> np.ndarray
    read_trace(iline, xline) -> np.ndarray

    # 新增：
    read_inline(iline, *, lod=0)              # 所有平面读都带 LOD 级别
    read_voxel_window(il0, il1, xl0, xl1, t0, t1, *, lod=0)
    read_arbitrary_line(points, *, lod=0, interpolate=True)
    attach_cache(RamSliceCache)               # 生产 L1 缓存即插即用
```

- **索引语义**：`iline/xline` 是**值**（非索引），与 loader 一致；**同一 iline 值在所有 LOD 级有效**（内部 `idx >> lod` 映射）——UI 层无感知切换级别。
- **LOD 金字塔**：级联 `::2`，懒构建（首次访问 l_n 时从 l_{n-1} 建），sibling 目录 `<store>_l{n}`，不动基础 store。100G 体 l1 构建预算 ~15-20 min 单线程（建议并入 #1071 导入转码流水线尾部）。
- **缓存衔接**：`SliceCacheKey(volume_id, slice_type, position, downsample_factor=(2**lod,)*3, attribute_id)` —— 现有 key 已携带 `downsample_factor`，**缓存 schema 零改动**。
- **预读**：`DirectionalPrefetcher`（DragTracker 原型等价物）+ generation token 取消。

## 2. 实测（demo.py）

| 场景 | 数值 |
|---|---|
| LOD 懒构建（quick2g 2.1GB） | l1 3.6 s，l2 0.5 s |
| 切片 p50（NVMe 暖）inline / crossline / timeslice | lod0 40/73/152 ms → lod1 9/16/32 → lod2 4/7/10 |
| L1 缓存命中 | 38 ms → 0.02 ms |
| 方向预读拖拽序列（8 inline） | p50 ≈ 0 ms |
| read_trace ×50 | p50 8 ms |
| **read_voxel_window 64×64×200**（g100 冷） | **25 ms** ← #1073 属性 halo / #1074 AI tile 的直接依据 |
| read_inline/crossline/timeslice（g100 冷 lod0） | 4.3 / 3.6 / 12.4 s（与 #1070 一致；UI 必须走 LOD+预读路径） |
| read_arbitrary_line 100 点双线性 | 3258 ms ← **已知短板** |

## 3. 已定案的设计点（原型会话与用户确认）

1. **LOD 采样策略：统一 stride + 停止后精化**——拖动中显示 lod1/2 stride 降采样（振幅真实，可接受混叠），停止后自动精化到 lod0；不引入混合策略的层间语义差异。
2. **落位：geoviz_seismic 新模块 `chunked.py` + 工厂 `open_volume(path)`**——按路径类型自动返回 SEG-Y loader 或 chunked reader，消费方改一行 import；loader.py 不动。

## 4. 已知短板与实施项

1. **任意线慢**（3.3 s/100 点）：原型逐点 4 次 trace 读（Python 循环）。生产版按线的 chunk 覆盖盒批量 `read_voxel_window` 后内存插值——预期 <200 ms，属实施优化而非新决策。
2. g100 的 `read_trace` 9 ms 疑似暖副作用（同 shard 先被 inline 读过）——冷单道仍按 #1070 的 78 ms 规划 well-tie 批量路径。

## 5. 给三张契约工单的输入

- **#1073 属性 out-of-core**：`read_voxel_window` 实测 25 ms（64³ 邻域），brick 流式模型可行；halo 读取直接用窗口读，不要逐道。
- **#1074 AI 分块推理**：tile 组装 = `read_voxel_window`；ProbMap 写回建议同 chunk/shard 配置的 zarr 数组（写入路径与 #1071 转码器对称）。
- **#1075 渲染显存**：LOD2 切片 4-10 ms 足够 60fps 的"先低清后精化"；纹理上传量 = lod 级数据量（lod2 timeslice 1250×1250×4B ≈ 6 MB，远低于 400 MB 全分辨率）。
