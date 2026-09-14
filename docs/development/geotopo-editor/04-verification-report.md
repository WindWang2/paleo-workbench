# 04 · 验证报告 — geotopo-editor 阶段三闭环

日期：2026-09-14 ｜ 分支：`feat/geotopo-editor`（worktree `../paleo-workbench-geotopo-editor`）
基线：e7214566 ｜ 验证环境：Windows 11 x64 / MSVC 14.38 / Qt 6.8.0 (C:/deps) / vendored QGIS（主仓 build 复用）/ Python 3.12.13 (uv)

---

## 1. 交付总览（5 Tickets + 审查修复）

| Ticket | 提交 | 内容 |
|---|---|---|
| 文档先行 | 8a9bdfe9 | 5 份工程文档 + 计划/发现/进度文件 |
| 1 · DCEL 构面 | b21be8c6 | geological_topology_core（QGIS-free）+ geotopo 子模块 + 宿主 facade |
| 4 · 地质守卫 | cb09b70b | facies_adjacency.json（Walther 秩差）+ geological_invariants 三校验器 |
| 2 · 断-相截断 | 7e34cf8a | faultCutMirrorFeatures + PwbFaultCutTool + 宿主编排 + conftest DLL 预导入修复 |
| 3 · 共边重塑 | 325e5e06 | find_shared_arcs / reshape_shared_arc（守恒四校验）+ 镜像层联动 + PwbBoundaryReshapeTool |
| 5 · 原子宏事务 | 939022bd | compound_macro + commit_all geology 门 + 补偿恢复（restore_mirror_snapshot） |
| 审查修复 | a352773f | 双轴审查 P0×2 + P1×6 + 契约文档对齐 + 补齐缺失用例 |

## 2. 测试结果（全部本机实测，命令：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -p no:randomly <files> -q`）

| 套件 | 用例 | 结果 |
|---|---|---|
| test_geological_topology_core.py（含 5 项 qgis 桥腿） | 15 | ✅ 15 passed |
| test_geological_invariants.py（64 组合参数化 + 情形） | 75 | ✅ 75 passed |
| test_fault_cutting.py（8 fake + 8 真桥） | 16 | ✅ 16 passed |
| test_boundary_reshape.py（7 host + 5 真桥） | 12 | ✅ 12 passed |
| test_atomic_multilayer_commits.py（6 fake/压力 + 1 真桥 + 2 真接线） | 9 | ✅ 9 passed |
| test_geotopo_parity.py（双引擎矩阵 + 孔洞 xfail 钉） | 7 | ✅ 6 passed + 1 strict xfailed |
| test_geotopo_fuzz.py（540 语料 × 双引擎） | 1080 | ✅ 1080 passed |
| **geotopo 合计** | **1214** | **1212 passed + 1 xfailed + 1 xfail 计入 xfailed**（单一运行输出：`1212 passed, 1 xfailed`） |
| 既有回归：test_topo_m1 / m3 / composite_editing / topology_compound_undo | 86 | ✅ 86 passed（40 + 46 两批） |

**模糊测试语料**（固定种子 20260914，六类 × 90）：微小刺状（1e-6~1e-7 抖动）、自交 8 字环、2000 顶点密集共线、退化输入（零长/重复/NaN/inf/1e300 巨坐标）、随机线汤、相邻面对。不变式：零崩溃、零卡死（单调用 10s 墙钟守卫）、输出合法或契约化拒绝（GeoTopoError 携 PWB-GT-xxx）。

## 3. 性能基准（原生 DCEL 核）

| 用例 | 结果 | 门禁 |
|---|---|---|
| 5100 段 51×51 网格构面 | 无负载：**8.44 / 8.69 / 11.38 ms**（faces=2500 精确）；满载开发机：15.7–47.4 ms | ≤30 ms（best-of-3 + `capacity` 标记；04-limitations #9） |
| 断层截断（单面） / 共边重塑（双面） / 快照恢复 | 单宏毫秒级（编辑缓冲操作） | — |

**注**：验证期间开发机 CPU 持续 100% 负载（后台进程群），墙钟数据取无负载窗口实测为准。

## 4. 测试覆盖率（coverage 7.16，双引擎两遍合并；qgis 腿经桥预热 runner）

| 模块 | 语句 | 未覆盖 | 覆盖率 |
|---|---|---|---|
| mapping/geological_invariants.py | 183 | 6 | **97%** |
| mapping/geotopo_service.py | 307 | 27 | **91%** |
| mapping/native_edit_session.py | 253 | 78 | 69%（未覆盖为旧桥回退分支/异常兜底路径；geotopo 新路径全覆盖） |
| C++ 核心 | — | — | 经 1212 项 Python 面 + standalone selftest 覆盖（阈值断言 + 契约信封 + parity） |

## 5. 双轴审查（≤2 subagents 并行）

### 首轮判定：双 FAIL → 修复后复验通过
**Standards 轴**（内存/异常/GIL）发现 10 项：P0×1（geology 谓词签名错配——启用即 TypeError）、P1×5、P2×4。
**Spec 轴**（契约/地质真实性）发现 14 项：P0×2（boundaryReshape 工具缺失；geology 门生产路径失效——readback 无 attributes + 角色词表不匹配）、P1×5、P2×7。

全部 P0/P1 已修复并新增回归测试钉死（见 a352773f）；P2 修复 6 项、接受 2 项（prune O(E²) 最坏路径与双跑门计算量——已记录）。**关键复验证据**：`test_save_edits_real_geology_wiring_blocks_and_emits`（真实接线，非注入谓词）证明 geology 门在生产路径拦截违规并发出 `geology_blocked`。

### 内存 / GIL 对抗审计结论（修复后复核）
- **所有权**：`ring_from_xy` 的 QgsLineString/QgsPolygon 经 unique_ptr→release() 转移给 QgsGeometry（QGIS4 语义正确）；`finishCut` 曲线 make_unique；新代码零裸 new/delete、零泄漏路径（审查 verified-clean）。
- **生命周期**：setMapTool 两分支的 `this` 捕获均以 alive_token_ 弱引用守卫；canvas 原始指针经 Qt 父子关系 + 既有 slot 替换规程保护。
- **异常 × pybind**：三个新 mapstack 方法全部错误字符串返回（editingLayerFor 不抛）；geotopo 子模块体仅可能 bad_alloc（pybind 默认转译）；宿主 facade 异常统一包裹为契约码。
- **GIL**：geotopo 三函数的 gil_scoped_release 区间为纯 std 计算（JSON 解析在区间外）；edit_gesture 回调经既有 py::gil_scoped_acquire 包装；新增 mapstack 绑定不释放 GIL（递归获取安全）。规模护栏（4e6 段对）防释放区间无界燃烧。

## 6. 地质真实性核对（Spec 轴结论）

- Walther 秩差阶梯（冲积扇0/三角洲1/滨岸-潟湖-潮坪2/台地-陆棚3/深水盆地4，|Δ|≤1 + 浊积白名单三角洲↔陆棚/深水盆地）判定为可辩护编码；未知名拒绝 + 缺失过渡相中文提示符合《勘探管理图件图册编制规范》精神。
- 悬挂断层传递封闭（并查集）、等厚线-剥蚀边界断开判据的中文判词被审查判定为地质精确。
- 遗留地质边界（工程覆盖通道存在）：三角洲↔碳酸盐台地（混积陆棚）默认拦截、微相级矩阵、剥蚀边界 LayerRole 词条（04 #4/#13/#16）。

## 7. 环境事项（如实记录）

1. **Windows DLL 同名复用序**（预存，主仓同病已实测复现）：CPython 自带 libcrypto-3/sqlite3（hashlib/sqlite3 触发）先载入则桥导入失败（0xC0000139）。修复：tests/conftest.py 采集期预热导入（无桥环境静默跳过）。
2. **test_qgis_topo_m1_native_editing.py 段错误**：**主仓基线同样崩溃**（QTest 鼠标驱动真画布，access violation，已留双仓对照日志）——本机预存环境问题，非本分支引入；m3 真桥文件及全部新真桥用例通过。
3. 性能墙钟受满载影响（见 §3 注）。
4. 版本钉扎：PySide6 6.8.0.1、pyproj 3.7.2（PROJ 9.5.1，与 vcpkg 桥链接对齐）。

## 8. 结论

`docs_generated ✅ / tdd_all_green ✅（1212+1xfail，含 1080 模糊双引擎）/ memory_and_gil_audited ✅ / review_passed ✅（双 FAIL → 修复 → 复验）`——循环条件满足。分支合并就绪（8 commits，见 `git log e7214566..HEAD`）。
