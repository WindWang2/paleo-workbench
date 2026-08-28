# 百GB级地震体全链路架构规格书

**状态**：定案（Wayfinder 地图 [#1067](https://github.com/WindWang2/paleo-workbench/issues/1067) 终点产出）
**日期**：2026-08-28
**基线硬件**：32 GB RAM 消费机 + NVMe（外置 USB 盘为真实场景之一）+ 消费级 GPU
**目标体积**：100 GB float32 地震体（5000×5000×1000，2500 万道，2 亿 5 千万采样点）

全部决策来自地图九张工单的解决记录，每节标注来源。配套 ADR：0061（存储格式）、0062（导入转码管线）、0063（out-of-core 处理模型）。证据资产：合成体生成器与基准脚本（分支 `bench/synthetic-segy-generator`、`bench/chunked-format-benchmark`）、访问原型（`prototype/chunked-access-api`）、调研报告（`docs/research/chunked-format-survey.md`、`chunked-format-benchmark-results.md`、`chunked-access-api-draft.md`，后两者在基准/原型分支上）。

---

## 1. 存储格式 [#1068](https://github.com/WindWang2/paleo-workbench/issues/1068) [#1070](https://github.com/WindWang2/paleo-workbench/issues/1070)

- **Zarr v3 + sharding** 为主格式（HDF5 降为单文件分发备选；自研 bricklet 不做，重评估触发条件见调研报告）。
- 默认参数：**chunk (64,128,128)**（4 MiB）、**shard (128,512,512)**（128 MiB）、**zstd clevel 5、不启用 bitshuffle**。
- 实测依据（100G 合成体、外置 USB-NTFS 冷）：转换 95 MB/s（18 min）；落盘系数 1.24×；三向切片冷首读 4.4 / 2.8 / 11.8 s；801 个文件（NTFS 友好）。
- **bitshuffle 禁用**是实测结论：读延迟劣化 3-7× 仅换 ~3% 落盘。开放验证项：真实工区数据 shuffle 压缩收益复测——若显著，归档层与浏览层分 codec（归档 zstd5+shuffle、浏览 zstd1-3 无 shuffle）。
- LOD 金字塔：group 级联 `::2`（l1..l4，直到最小维 < 64），**统一 stride 采样 + 停止后精化**（用户定案）；金字塔开销 ~14.8% 落盘（几何级数），**懒构建**（首次浏览时级联建，不导入预支）。
- 道头不入 zarr：结构化元数据（ilines/xlines/dt/坐标）入 `zarr.json` attributes 与 `SeismicSurveyEntity`（ADR 0059）。

## 2. SEG-Y 导入转码管线 [#1071](https://github.com/WindWang2/paleo-workbench/issues/1071)

- **导入即后台转码** + 转换期降级直读 SEG-Y（现状 segyio 路径，零新代码过渡模式）。
- **断点续转零状态文件**：重扫 store shard 完成度；commit 点 = `zarr.json` 写全 + DERIVED DataVersion 入库。
- catalog 挂接：同 DataAsset 的 **DERIVED DataVersion**（parent=RAW，`DataRun(operation="segy-to-zarr")`）；重导入后旧版本 **stale 标记 + 一键重转**，不自动删；资产 trash 级联回收站。
- 产物统一入项目 `*.artifacts/`；导入前预算检查 = 原始 × 0.85 × 1.33（LOD 因子，懒构建时该因子为 1）。
- 调度：**全局单并发** FIFO + 浏览体插队（盘带宽约束）；与属性计算、AI 推理共用同一队列互斥。
- 并行：worker = `min(物理核−2, 8)`，nice 低优先级；验收 100G ≤ 10 min（8 核 NVMe；单线程实测 18-37 min）。

## 3. 分块访问 API [#1072](https://github.com/WindWang2/paleo-workbench/issues/1072)

- `geoviz_seismic/chunked.py` 新模块 + 工厂 `open_volume(path)`（loader.py 不动，消费方改一行 import）。
- `ChunkedVolumeReader`：与 `SeismicLoader` 同名同义（read_inline/read_crossline/read_timeslice/read_trace），全部带 `lod=`；**同一 iline 值在所有 LOD 级有效**（内部 `idx >> lod`）。
- 新增 `read_voxel_window(bounds, lod)`（属性 halo / AI tile 的统一读取原语；实测 64×64×200 = 25 ms 冷）、`read_arbitrary_line(points, interpolate=True)`（任意线，horizon 追踪前提；已知短板：原型 3.3 s/100 点，生产版按 chunk 覆盖盒批量窗口读后内存插值，目标 < 200 ms——实施项）。
- 缓存衔接：`SliceCacheKey.downsample_factor` 承载 LOD，**缓存 schema 零改动**。
- 预读：`DirectionalPrefetcher`（DragTracker 语义），generation token 取消。
- 并行化遗留：zarr-python 3.3 同步 API 8 线程仅 0.9-1.7×——**AsyncArray / 多进程验证列为实施期验证项**（影响转码 worker 内的读取并行度）。

## 4. 属性计算 out-of-core [#1073](https://github.com/WindWang2/paleo-workbench/issues/1073)

- 流式模型：**64-inline 带**（对齐 shard 行）+ **数学等价 halo**（各轴算子半径：C3 半窗 5、RMS 窗 21→半径 10；体边界 reflect）。块间永无可见接缝；带拼接与整内存计算逐位相等（parity 断言）。
- 实测：native C3 78 M sample/s → **全量计算 6 min**（I/O 主导：外置 ~40 min、NVMe ~15 min）；halo +34% 计算可忽略；纯 Python 412 h——仅测试 parity 用。
- 落盘：同配 zarr、**float32**（量化归渲染层）；DERIVED DataVersion + `DataRun("attribute:<name>")`；LOD 懒建。
- native 接口：per-band ndarray 进出、GIL 释放、进度/取消按带（79 带 ≈ 1.3% 步进）。
- 交互：**ROI 秒级**（视野/画框，参数迭代）+ **全量后台**（入统一队列）。

## 5. AI 分块推理 [#1074](https://github.com/WindWang2/paleo-workbench/issues/1074)（仅推理契约；模型为外部黑盒）

- tile：存储对齐 64×128×128；overlap = 模型元数据 `receptive_field`；**中心裁剪融合**（每体素恰一次推理，与属性 halo 数学同构）。
- 双输出：**ClassMap uint8 必落 + ProbMap float16 默认落**（可配置不落并 UI 明示）；同一 DataRun（`inference:<model_id>@<version>`）。
- 调度：统一队列互斥；tile 批完成度重扫断点续跑；GPU OOM 批大小指数退避；CPU 回退标注「CPU 模式」。
- 运行时：**ONNX Runtime 标准**（`model_package` 元数据 `runtime="onnx"`）；现有 ModelProvider/inference_service/DataRun 零改动，分块推理 = 新 provider。
- 可视化消费：ClassMap 离散色图 + ProbMap alpha 调制，走 §6 叠加治理。

## 6. 渲染与显存 [#1075](https://github.com/WindWang2/paleo-workbench/issues/1075)

- **LOD + 视口裁剪**：屏幅像素比选级、视口外裁剪；显存恒定 ≈ 屏幕像素 × 4B × 双缓冲（4K 三正交+叠加 ≈ 150 MB），与体大小无关。
- **VramTextureCache 补课**（L2，现为空缺）：全局 **1 GiB 可配置（512 MB–2 GB）**，全部纹理类型同预算、全局 LRU、超限显式 glDeleteTextures；不设同屏面板硬限。
- 渐进精化：拖动中帧预算选级（16 ms 目标）；预读跟随显示 LOD；停止 **250 ms** 后精化 lod0；colormap 切换只重建 L2 不重读 L1。
- 叠加治理：预测叠加 = 视口分辨率独立小纹理；horizon 矢量渲染不占纹理预算。

---

## 7. 全局资源预算分配表（32 GB 基线）

| 区域 | 预算 | 说明 |
|---|---|---|
| OS + 桌面 + Qt/应用 | 6 GB | 系统与 GUI 基线 |
| Python 堆与业务对象 | 2 GB | 项目文档、目录、UI 状态 |
| **L1 RAM 切片缓存** | 2 GB | 多视图共享全局上限（实例默认 512 MB，现有机制） |
| **流式工作缓冲池** | 5 GB | 转码带缓冲 2.56 GB / 属性带+halo / AI tile 批**互斥共用**（统一队列保证同时只有一类任务） |
| 页缓存余量 | ~17 GB | 留给 OS：zarr shard 复用、SEG-Y 直读都靠它，**不显式占用** |
| **L2 VRAM 纹理缓存** | 1 GiB（可配 512 MB–2 GB） | §6；独立于系统内存预算 |

预算治理规则：L1/L2 超限走各自全局 LRU（现有模式）；流式缓冲池由任务队列准入（超 5 GB 的任务拆带）；任何组件不得绕过预算直接 mmap 大体。

## 8. 工作区存储账本与配额（雾区收编）

- 账本 = DataVersion.size_bytes 汇总（catalog 已有字段，零新概念）：工作区占用 = Σ(所有未 trash 版本)。
- 配额策略：**软告警**——达到用户设定阈值（默认 = 所在盘剩余 20%）时导入对话框显示预估占用与余量（§2 预算检查已有）；**不硬阻断**已有资产的派生计算（用户可清 trash 回收空间）。
- 大体优先级：外置盘场景照常支持（#1069 基线），账本按版本 path 所在盘分桶统计。

## 9. 验收门槛汇总（100G 合成体）

| 项 | 门槛 | 来源 |
|---|---|---|
| 导入转码 | 8 核 NVMe ≤ 10 min；断点续转零重复 | #1071 |
| 首屏（已转码体） | 打开到首张切片可见 ≤ 1 s（LOD1 路径） | 本文（雾区收编） |
| 首屏（降级直读） | ≤ 3 s（inline 顺序读） | 本文（雾区收编） |
| 切片拖动 | 4K 屏三正交+预测叠加 ≥ 30 fps（LOD 路径） | #1075 |
| 精化 | 停止 1 s 内到 lod0；回看已浏览切片 < 16 ms | #1075 |
| VRAM 峰值 | ≤ 配置预算（实测断言） | #1075 |
| 属性 ROI | 64×64×200 邻域端到端 ≤ 2 s | #1073 |
| 属性全量 C3 | 外置盘 ≤ 1 h；NVMe ≤ 20 min；带拼接逐位等价 | #1073 |
| 推理 | 断点零重复；center-crop 与整段推理逐位一致；alpha blend LOD≥1 60 fps | #1074 |
| 落盘系数 | ≥ 1.2×（合成体；真实数据复测项见 §1） | #1070 |

## 10. 实施切分建议

依赖顺序与并行度：

```
W1 存储与访问（关键路径）      W2 任务队列与调度
   zarr 转码器(#1068/1070)       统一队列+断点(#1071)
   → chunked.py reader(#1072) ←—— 共用
W3 渲染显存（可独立起步）      W4 属性 out-of-core（依赖 W1+W2）
   VramTextureCache L2 补课       per-band native 接口
   → LOD 精化 UX（接 W1 LOD）  W5 AI 推理 provider（依赖 W1+W2；模型未到位可先接 demo provider 走通管线）
最后：W1-W5 集成收口 + §9 验收
```

- 各分支资产（生成器/基准/原型/规格）以 PR 合入 main 后作为实施基线。
- 任意线批量优化（§3）与 zarr AsyncArray 并行验证（§3）安排在 W1 尾部，不阻塞 W4/W5。

## 11. 后续演进（不立工单，规格书留档）

- 分块虚拟纹理（2048² tile）——若 LOD+视口裁剪在极端放大场景不够用。
- 真实工区数据 shuffle/codec 复测（§1 开放项）。
- 有损压缩层（ZFP/wavelet 4-10×）——在无损主格式稳定后作为可选 DataVersion 变体。
- 多体同屏（两个 100G 体并存）——存储与预算模型已兼容，渲染叠加待需求。
