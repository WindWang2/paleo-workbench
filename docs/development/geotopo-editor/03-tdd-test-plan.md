# 03 · TDD 测试计划 — 红绿清单 / 数据集 / 断言

状态：Accepted ｜ 每个 Ticket 严格 Red→Green→Refactor→Atomic Commit。
运行约定：快速腿 `QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -p no:randomly tests/test_X.py`；桥腿同命令（pyd 可用时 `@pytest.mark.qgis` 自动生效）。

---

## Ticket 1 · C++ DCEL 构面算核

文件：`tests/test_geological_topology_core.py`（无桥可跑：host fallback 层 + 契约形状；桥核子集 `@pytest.mark.qgis`）＋ `native/qgis_render_bridge/src/standalone_test.cpp` 追加 C++ 直测。

| # | 用例（先红） | 断言（后绿） |
|---|--------------|--------------|
| 1.1 | 简单十字交叉两线 | 恰 4 面；每面 source_lines 含两线 id；外环 CCW |
| 1.2 | T 型相交（一线端点落另一线内部） | 2 面；宿主线被打断（edge_count 诊断正确） |
| 1.3 | 孤立悬挂线（端点不触任何线） | 面数不受影响；dropped_dangles ≥ 悬挂段数 |
| 1.4 | 自交 8 字环 | 两面（8 字的两个圈）；无退化零面积面 |
| 1.5 | 共线重叠段（两线共用一段路径） | 共线段去重为单边；面正确；无重复边 |
| 1.6 | 网格 50×50（=5000 段）性能门禁（qgis 腿, `capacity`） | `elapsed_ms ≤ 30`；面数 = 2500；面积和 = 网格总面积（解析值） |
| 1.7 | 容差参数：交点间距 < tolerance 的近交 | 合并为单节点（不产生 sliver 面） |
| 1.8 | clip_envelope 剔除 | 越界面被剔除，界内保留 |
| 1.9 | 非法输入（NaN 坐标 / tolerance=0） | `PWB-GT-001/002` 错误信封（fallback 抛 `GeoTopoError` 同码） |
| 1.10 | 多边形几何有效性 | 每个输出面 shapely `is_valid` 且 `polygonize(输出边)` 幂等（重跑得同构面集） |

## Ticket 2 · 断-相协同截断

文件：`tests/test_fault_cutting.py`（FakeNativeStack 纯 Python 编排腿）＋ `@pytest.mark.qgis` 真桥腿。

| # | 用例 | 断言 |
|---|------|------|
| 2.1 | 断层完全穿越单一相带面 | 1 面 → 2 面；两新面 `facies` 属性 = 原；`fault_bounded=True` ×2；单条 `fault_cut` 手势 |
| 2.2 | 断层部分穿越（一端在面内尖灭） | 面被切成 2（GEOS split 语义）或保持 1（未贯穿）——断言与 GEOS 行为一致且属性不变、无崩溃 |
| 2.3 | 多次相交（Z 形断层穿越两相邻面） | 两面均被分割；手势 layers 含全部受影响层 |
| 2.4 | 断层端点正好贴合面边界 | 幂等不崩溃；结果 2 面或 1 面（边界情形显式断言其一，与实现钉死） |
| 2.5 | feature_ids 显式指定 | 仅指定面被切；相邻面不动 |
| 2.6 | 无穿越要素 | 返回 `PWB-GT-102`；层内容零变更 |
| 2.7 | `fault_side` 选项 | 两新面 side 值相反（hanging/footwall） |
| 2.8 | undo（真桥腿） | `undo_mirror_edit` 一次 → 回到切割前 |
| 2.9 | activate_tool("fault_cut") 非原生会话 | 返回 (False, reason)，不 raise |

## Ticket 3 · 共边联动重塑

文件：`tests/test_boundary_reshape.py`。

| # | 用例 | 断言 |
|---|------|------|
| 3.1 | 相邻两面共直边，弧中点外推重塑 | 两面同时更新；`area(a')+area(b') == area(a)+area(b)`（rel 1e-9）；shapely 二者 overlap=0、gap=0 |
| 3.2 | 弧未在容差内匹配 | `PWB-GT-201`；两侧零变更 |
| 3.3 | 新曲线引发自交 | `PWB-GT-202`；零变更 |
| 3.4 | 新曲线越界产生重叠 | `PWB-GT-203`；零变更 |
| 3.5 | 多段共边（飞地）| find_shared_arcs ≥2 弧；重塑指定弧不动其余 |
| 3.6 | 样条平滑模式（options.smooth）| 顶点数增加、面积守恒不变式仍成立 |
| 3.7 | 真桥腿：镜像层 reshape_mirror_shared_boundary + 一次 undo 双层同步恢复 | 双层几何回原 |
| 3.8 | addTopologicalPoints 散布（真桥腿）| 关联层在对齐点处新增顶点 |

## Ticket 4 · 地质拓扑守卫

文件：`tests/test_geological_invariants.py`（纯 Python，无桥依赖）。

| # | 用例 | 断言 |
|---|------|------|
| 4.1 | 相邻矩阵全组合：8 相 × 8 相（含对称） | 与 facies_adjacency.json 期望矩阵完全一致（参数化 64 断言） |
| 4.2 | 深水盆地 直接邻 冲积扇 | `facies_adjacency_gap` error；message 含"陆棚"或"滨岸"过渡提示 |
| 4.3 | 滨岸 邻 陆棚 / 三角洲 邻 滨岸 等合法序 | 无违规 |
| 4.4 | 共享边界 < min_shared_len 的针触 | 不算相邻（不误报） |
| 4.5 | 断层端点悬空于相带面内部 | `dangling_fault_unsealed` error |
| 4.6 | 断层端点抵达面边界 / 触及另一断层 / 出框 | 合法 |
| 4.7 | 等厚线跨越剥蚀边界且无顶点断开 | `isopath_crosses_unconformity` error |
| 4.8 | 等厚线在跨界处已断开（有顶点） | 合法 |
| 4.9 | commit_all 集成（FakeNativeStack）| geology 返回 error 违规 → 全集拦截、无层提交；warning 放行（test_atomic_multilayer_commits.py） |
| 4.10 | save_edits 真实接线集成 | geology_blocked 信号携带违规、零提交（test_atomic_multilayer_commits.py::test_save_edits_real_geology_wiring_blocks_and_emits） |

## Ticket 5 · 原子宏事务

文件：`tests/test_atomic_multilayer_commits.py`。

| # | 用例 | 断言 |
|---|------|------|
| 5.1 | compound_macro 内跨线层+面层编辑 | gestures 登记单手势；undo 一次 → 两层同步回退；redo 同步前滚 |
| 5.2 | 第 2 层 commit 失败（Fake 注入） | 已提交第 1 层被补偿恢复到快照（几何/属性逐字段相等）；返回 (False, 原因)；`compensations` 记录 |
| 5.3 | 补偿后 undo 栈一致性 | 补偿宏可被 Ctrl+Z 撤销（恢复到"半提交"态不出现——补偿后状态=提交前状态，断言快照全等） |
| 5.4 | 并发压力：200 手势 × (undo/redo) 交错随机序列（种子固定） | 每步后 gesture 计划一致性不变式：undo_plan/redo_plan 与层栈深度吻合，无死锁无异常 |
| 5.5 | Python 会话 + 原生会话混合 compound | 单手势跨两种权威；undo 先原生后 Python（逆序） |
| 5.6 | commit_all geology+topology 双门 | 任一门违规 → 全拦截（不出现部分提交） |

## F · 双引擎一致性矩阵

`test_geotopo_parity.py`（qgis 腿）：cross/t/collinear/grid-10 同数据双跑（bridge geotopo ↔ shapely fallback），断言面数/面积多重集一致（容差 1e-4）+ 共边弧长 + 重塑守恒一致。figure-eight（框内真孔洞）为**严格 xfail 钉子**——孔洞近似差异 = 内环面积（04-known-limitations #17）。

## 数据集生成方案

- `tests/data/geotopo/`（新目录，程序化生成 + 少量手写 fixture）：
  - `grid_5000.json`（1.6 用例，50×50 网格控制线 + 解析面积期望值）；
  - `cross_t_fuzz_seed.json`：交叉/T/悬挂混合网络的黄金期望（构面结果人工校验后钉死）；
  - 相带邻接 fixture：8 相两两邻接对（共享边矩形拼接）程序化生成（4.1–4.4）；
  - 模糊语料：`fuzz_corpus(n)` 生成器（种子化）——病态输入五类（见验证阶段）内嵌在 `tests/test_geotopo_fuzz.py`，不落盘大文件。

## 提交切分（atomic commits）

1. `feat(geotopo): C++ DCEL 构面算核与 geotopo 子模块（Ticket 1）` — core + bindings + CMake/setup 同步 + tests 1.x + fallback 服务层
2. `feat(geotopo): 断-相协同截断工具与镜像层原子分割（Ticket 2）` — edit_tools/map_stack + controller 接入 + tests 2.x
3. `feat(geotopo): 相带共边联动平滑重塑（Ticket 3）` — 核心重塑 + 镜像层方法 + tests 3.x
4. `feat(geotopo): 地质拓扑规则形式化守卫（Ticket 4）` — invariants + adjacency 资源 + 门接入 + tests 4.x
5. `feat(geotopo): 多图层原子宏事务与补偿性提交（Ticket 5）` — compound_macro + 补偿 + tests 5.x
6. `test(geotopo): 500+ 病态几何模糊测试与验证报告` — fuzz + verification report
每提交前：红灯证据已入 progress.md（先失败输出，后通过输出）。
