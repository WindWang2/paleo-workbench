# 03 — TDD / 基准计划（红绿循环 + 回归钉）

总纪律（本仓惯例）：基准先行——测试先红（断言当前基线超预算/能力缺失），
实现后转绿；每个 ticket 一个原子提交；反空断言——每个 SLA 断言配反向
对照（人为退回慢路径必须变红）；跑不过就修，禁止调预算迁就实现。

预算为本机（01-perf-baseline.md 同环境）测量设定；CI 无桥环境全部自跳过
（`pytest.mark.qgis`），性能门禁只在本地/有桥腿生效——与 `tests/perf/`
既有约定一致。

---

## Ticket 1 — SpatialIndexCore

**测试**：`tests/perf/test_spatial_index_benchmarks.py`（`slow`+`qgis`）

| 用例 | 断言 | 红→绿 |
|---|---|---|
| `test_vertex_pick_bench_sla` | 20k 顶点：`vertex_pick_bench` 中位 <1.0 ms；hits>0 于命中点 | 红：现线性 ~2.2 ms；绿：索引后 <1 ms |
| `test_vertex_pick_equivalence` | 50k 顶点随机 200 查询点：索引 hits == 线性参照（集合相等，含坐标） | 绑定新增即红（无索引） |
| `test_vertex_index_disabled_falls_back` | `PWB_DISABLE_VERTEX_INDEX=1` 时行为等价（慢路径仍正确） | 绿后钉住（防降级路径腐坏） |
| `test_index_invalidation_after_edit` | 移动顶点后拾取到新坐标（缓存不陈旧——#1257 同类风险对照） | 红：无索引期间以线性行为为参照 |
| 反向对照 | 禁用索引 + 50k 规模断言 >1 ms（防 SLA 断言空转） | 绿后仍须红（在禁用分支上） |

**提交**：`perf(edit-tools): 顶点拾取 C++ 动态 R-Tree 索引核（<1ms SLA）`

## Ticket 2 — DirtyBoxTopologicalCore

**测试**：`tests/perf/test_incremental_topology_bench.py`

| 用例 | 断言 |
|---|---|
| `test_revalidate_after_vertex_move_sla` | 50k 顶点（10k 面）：移动 1 顶点后 `run_geometry_checks` 中位 <35 ms（基线 3,920 ms） |
| `test_incremental_equals_full` | 随机 20 步编辑序列（增/删/移/撤），每步增量错误列表 == 缓存关闭时全量列表（排序逐字段相等）——**数学等价性契约** |
| `test_gap_cache_fastpath` | 图层无变化时第二次 run() <1 ms（缓存直返）；有变化时不劣于基线 |
| `test_cache_reset_on_full_reship` | 镜像 revision 回退/重发后缓存失效（防陈旧错误） |
| 反向对照 | 注入伪造缓存（指纹不变、几何已变）必须被等价性用例抓红 |

**提交**：`perf(topology): 脏区增量拓扑校验（<35ms SLA，全量等价）`

## Ticket 3 — AdaptiveVectorLOD

**测试**：`tests/perf/test_vector_lod_bench.py`（纯 Python 部分 + 桥扩展部分）

| 用例 | 断言 |
|---|---|
| `test_lod_simplify_shape_fidelity` | 大比例尺（小 tolerance）：化简结果 == 原折线（0 剔除）或仅剔除共线点；极值/拐点全部保留 |
| `test_lod_small_scale_reduction` | 小比例尺：蜿蜒岸线顶点数下降 ≥80%，且首尾/拐点保留、无自交（shapely is_valid） |
| `test_lod_cpp_python_parity` | map_edit_core `vector_lod` 与 Python 参照逐位相等（同运算序） |
| `test_render_with_lod_budget` | 50k 顶点花纹层 + LOD 开启：缩放扫中位 <16 ms（与 Ticket 4 联合达成） |
| 反向对照 | tolerance=0 时输出必须与输入逐点相等 |

**提交**：`perf(render): Visvalingam 自适应矢量 LOD（大比例不失真/小比例 -80%）`

## Ticket 4 — FaciesTextureAtlas

**测试**：`tests/perf/test_facies_atlas_bench.py`

| 用例 | 断言 |
|---|---|
| `test_atlas_bake_once` | init 烘焙计数 == 1（跨帧/缩放不重复烘焙）；图集 QImage 尺寸/槽位正确 |
| `test_zoom_pan_sla_2k` | 2k 面：zoom+pan 各 12 帧中位 <16 ms |
| `test_zoom_pan_sla_10k` | 10k 面：同上 <16 ms（基线 158.7/89.6 ms） |
| `test_pattern_visual_parity` | 图集笔刷填充 vs 旧逐张笔刷：渲染输出逐像素一致（同 pattern/同几何） |
| 反向对照 | 逐要素 drawPath 旧路径计时作为参照行打印（不达标即证批处理必要） |

**提交**：`perf(render): 相带花纹图集预烘焙与按花纹批处理填充（60FPS SLA）`

## Ticket 5 — ZeroCopyDeltaBus

**测试**：`tests/perf/test_edit_delta_bus_bench.py`

| 用例 | 断言 |
|---|---|
| `test_pod_layout_pinned` | `sizeof(PwbEditEventPod)==64`、`alignas==64`、crc32 覆盖（C++ 静态断言 + Python 侧结构体尺寸钉） |
| `test_bus_10k_events_zero_alloc` | 10,000 事件 @ ~10 kHz 排水：tracemalloc 追踪分配 == 0；环无穿越（sequence 连续） |
| `test_json_channel_alloc_contrast` | 同负载 JSON 参照通道分配数 >0（反向对照） |
| `test_bus_event_fidelity` | 环内事件字段 == JSON 通道同事件字段（x/y/kind/feature/序号） |
| `test_bus_disabled_by_default` | 未启用总线时回调行为与 HEAD 完全一致（API 兼容钉） |
| GC | 排水循环 gc collections == 0 |

**提交**：`perf(ffi): 零拷贝 POD EditDelta 总线（10kHz 0 分配）`

---

## Phase 3 — 压测与验收

- `tests/perf/test_vector_stress_100k.py`：100k 顶点 / 2k 相带面 / 500 断裂
  线极端工区；2,000 次（移动/框选/吸附/撤销重做）混合操作循环；
  - 进程 RSS / 桥侧内存计数器每 200 步采样，断言斜率 ~0（无线性增长）；
  - gc 停顿回调累计 == 0（编辑事件经总线时）；
  - 循环时长与 SLA 记入 `04-sla-verification-report.md`。
- Review（≤2 subagents）：C++ 内存布局/SIMD 兼容（MSVC x64，无显式
  intrinsics，跨平台编译位）/`std::shared_mutex` 争用面/环越界与对齐
  边界——发现项修复后复跑全部 ticket 测试。
