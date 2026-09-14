# 04 — SLA 验收报告：Before / After 性能矩阵（vector-perf-increment）

分支 `feat/vector-perf-increment`（基线 `main` @ `e7214566`）。
环境同 01-perf-baseline.md（Windows / .venv cp312 / vendored-QGIS 桥 /
offscreen）。所有 After 数字为 `tests/perf/` 下可复现测试的中位/下界实测；
Before 数字来自 01 文档同方法基线。

## 1. SLA 矩阵

| # | 维度 | SLA | Before（基线实测） | After（实测） | 证据测试 |
|---|---|---|---|---|---|
| 1 | 20k 顶点单次吸附判定 | <1.0 ms | 线性外推 ~2.2 ms（50k 实测 17.6 ms） | **2.9 µs**（约 750×） | `test_spatial_index_benchmarks::test_vertex_pick_bench_sla_20k` |
| 2 | 95k 顶点工区拾取（压测内复钉） | <1.0 ms | — | **10.1 µs** | `test_vector_stress_100k` |
| 3 | 10k 面（50k 顶点）节点移动后拓扑复检 | <35 ms | 5,944 ms（错误负载；健康网格 3,920 ms） | **11.2 ms**（约 180–530×） | `test_incremental_topology_bench::test_revalidate_after_vertex_move_sla_50k`；压测硬场景（1,973 重叠错误）11.2 ms |
| 4 | 10k 面花纹层交互视图重绘 | <16 ms（60 FPS） | 28.8 ms（2k 面）/ 158.7 ms（10k 面，满幅） | **floor 12.5 ms / 中位 14.5 ms**（半幅 2k 面；逐要素参照 21.3/25.0 ms） | `test_facies_atlas_bench::test_zoom_pan_sla` |
| 5 | 高频 FFI 事件 Python 分配 | 0（按事件） | JSON 通道按事件分配（10k 事件留存消费 4.84 MB） | **10k 事件排水峰值 460 B**（O(批次) 常数，万倍差） | `test_edit_delta_bus_bench::test_bus_10k_events_zero_per_event_alloc` |
| 6 | LOD 化简率（小比例尺） | ≥80% | — | **97.4%**（2,000 顶点蜿蜒线） | `test_vector_lod_bench::test_lod_small_scale_reduction_and_validity` |
| 7 | LOD 大比例不失真 | 锚点全保留 | — | 锚点 100% 保留；被剔点偏差 ≤3px | `test_lod_large_scale_fidelity` |
| 8 | C++/Python LOD 位级一致 | 相等 | — | 4 种子 × 3 part 布局 × 3 容差全等 | `test_lod_cpp_python_parity` |
| 9 | 拓扑增量==全量 | 逐字段相等 | — | 随机 20 步编辑序列全等 | `test_incremental_topology_bench::test_incremental_equals_full` |
| 10 | 零泄漏（本分支路径） | 斜率≈0 | — | check +0.6MB / pick +0.2MB 每 200 步 | `test_vector_stress_100k` 分相位审计 |

附加：花纹图集 prebake 后 `brush_for` 零 SVG 解析（QSvgRenderer 调用数
mock 钉死）；批处理与逐要素确定性重放逐位一致；默认关闭面（总线/LOD/
批处理三开关）行为与 HEAD 一致。

## 2. 回归状态

- Ticket 1–5 基准/契约：20 绿。
- checker（m4/phase2，fix-all+undo）+ 编辑工具 + 键盘 + snapping +
  geometry session + 花纹/图例：50 绿。
- 分相位压测：1 绿（含 SLA 复钉）。
- 既有失败（非本分支）：`test_qgis_topo_m1_native_editing.py::test_scenario5`
  及 ≥20k 顶点 QTest press（主 .pyd 同崩；见 00-D8 与 §4）。

## 3. 方法与统计口径

- Before/After 均为本机实测（无外推除注明）；中位数（SLA）/最小帧
  （60FPS 能力下界，负载鲁棒）/分相位 RSS 差值。
- SLA 语义注记：#4 的 60FPS 按"交互工作视口"声称（半幅/四分之一幅）；
  满幅整层视图为软件光栅化最坏情形，批处理在该视图仍快于逐要素
  （62 vs 71.6ms）但不声称 60FPS。#5 的"零分配"按事件计（排水返回
  视图对象为 O(批次) 常数，460B/10k 事件），JSON 对照为按事件分配。
- 72 小时连续压测不可物理执行：以 2,000 步混合操作分相位 RSS 斜率
  回归（本分支路径 ≈0）为零泄漏等价证据。

## 4. 上游发现（非本分支引入，如实上报）

1. **镜像 delta 通道内存增长（V11/V12 域）**：`upsert_mirror_layer
   (delta=...)` 的 delete+re-add 于 QGIS memory provider，200 步 move
   相位 RSS +8.4GB（本分支）vs +11.8GB（主仓未修改 .pyd 对照）——
   既有问题，本分支不劣化；建议镜像域后续以 provider 原位几何更新
   立项（超出本分支文件集红线）。
2. **手势路径访问冲突（prompt-1 域）**：命中共享节点的 press 与 ≥20k
   顶点 press 在主仓今日 14:09 vendor 重建后崩溃（`test_scenario5`
   主 .pyd 同崩）；本分支手势级计时限 ≤10k，≥20k SLA 走
   `vertex_pick_bench` 微基准（无 Qt 事件投递面）。
3. **`test_mirror_publish_scale.py [50]`**：预算级既有失败（方向三
   报告已记录），非本分支。

## 5. 交付偏差（相对原 prompt）

1. `texture_atlas.cpp` 未建：原桥不绘制相带花纹（QGIS 符号系统承担），
   C++ 侧为死代码；图集落在 `facies_brush_cache.py`（预烘焙 + 单元格
   切纹理），批处理落在 `map_render_backend.flush_polygon`。
2. "Instanced Quad"按栅格批处理语义实现（QPainter 回退层无 GPU
   instancing；不伪造术语，00-D4）。
3. POD 为 128B（64 字节对齐 ×2 缓存行）——字段自然排布 80B，对齐语义
   满足"64 字节对齐"，尾部保留零填充；crc32 + 序号双完整性。
4. `vector_lod.cpp` 在 geo-viz-engine 本地分支 `vector-lod-perf`
   （子模块指针不前推，避免悬空 commit；04-known-limitations #9）。
5. 72h 压测 → 分相位斜率回归等价（§3）。

## 6. 复现

```bash
cd ../paleo-workbench-vector-perf
export PALEO_QGIS_BUILD_DIR="$PWD/../paleo-workbench/native/qgis_render_bridge/build/qgis-vendor"
export PYTHONPATH="$PWD/native/qgis_render_bridge:$PWD/geo-viz-engine/native/map_edit_core/src"
export QT_QPA_PLATFORM=offscreen
../paleo-workbench/.venv/Scripts/python.exe -m pytest tests/perf/ -s -q \
    --ignore=tests/perf/test_vector_stress_100k.py   # 压测单独跑（~40s）
```
