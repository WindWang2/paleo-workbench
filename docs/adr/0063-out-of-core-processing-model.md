# ADR 0063: 存储对齐的 out-of-core 处理模型（访问 API / 属性 / AI 推理共用）

- Status: Accepted
- Date: 2026-08-28
- Deciders: WindWang2（产品裁决），ZCode wayfinder 会话
- 来源: 地图 [#1067](https://github.com/WindWang2/paleo-workbench/issues/1067) 工单 [#1072](https://github.com/WindWang2/paleo-workbench/issues/1072) [#1073](https://github.com/WindWang2/paleo-workbench/issues/1073) [#1074](https://github.com/WindWang2/paleo-workbench/issues/1074)；规格书 §3-§5

## Context

整内存数组进出（`AttributePipeline(volume: np.ndarray)`）在 100G 体上断裂。属性算子（C3 半窗 5）与 AI 模型（感受野）都是局部算子——分块流式可行，需要统一的几何与融合契约避免三套实现各说各话。

## Decision

**一个模型，三处使用**：

1. 几何：处理单元 = 存储对齐的 **64-inline 带 / 64×128×128 tile**；halo/overlap = 算子半径（属性：各轴算子半窗；推理：模型元数据 `receptive_field`）。
2. 读取：统一原语 `ChunkedVolumeReader.read_voxel_window(bounds, lod)`（实测 64×64×200 = 25 ms 冷）。
3. 融合：**中心裁剪 / 数学等价 halo**——每输出体素恰好一次计算，块间逐位等于整内存结果（parity 断言）；体边界 reflect pad。属性 halo 实测仅 +34% 计算。
4. 写出：同配 zarr、DERIVED DataVersion、LOD 懒建；断点 = 输出完成度重扫（与 ADR 0062 同构）。
5. API：`geoviz_seismic/chunked.py` 新模块 + 工厂 `open_volume(path)`；与 `SeismicLoader` 同名同义 + `lod=`，缓存 schema 零改动。

## Consequences

- native C3 78 M sample/s → 全量计算 6 min，I/O 成为主导（外置 ~40 min）；ROI 秒级 + 全量后台双模式。
- AI 推理实现为一种 ModelProvider（ONNX Runtime 标准），现有 inference_service/DataRun 零改动。
- 逐位等价承诺使「分块结果 vs 整内存结果」成为可测试契约，替代模糊的「近似等价」。
