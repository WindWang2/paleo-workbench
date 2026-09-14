# 00 · 技术决策记录（ADR 摘要）

状态：Accepted ｜ 分支：`feat/geotopo-editor` ｜ 基线：e7214566

每条决策按「决策 → 备选 → 理由（地质/工程双视角）」记录。未决细节按「默认地质最佳实践」自决，均在此留痕。

---

## D1 · DCEL 容差体系（tolerance ladder）

**决策**：统一容差参数 `tolerance`（单位=图层 CRS 线性单位，默认 `1e-6`，即 1 µm），用于：
1. 交点合并（两个交点距离 < tolerance 视为同一节点）；
2. 点在线上判定（vertex-on-segment）；
3. 悬挂枝剪除（长度 < tolerance 的悬挂边不参与构面）；
4. 共边弧匹配（Ticket 3）。

精确重合去重沿用既有 `kSharedNodeEpsilon = 1e-8`（edit_tools.hpp:58）语义，但构面管线内部只用统一 `tolerance`。

**备选**：CGAL 精确谓词 / snap-rounding 完全论。**否决理由**：CGAL 未 vendored；编图坐标域典型 1e3–1e7 m，double 在 1e7 处绝对精度 ~1e-9，1e-6 容差高于数值噪声 3 个量级、低于任何真实地质界线间距（地质图最小图元 ~0.1 mm 图面 ≈ 数十米实地），安全余量充足。

**地质实践依据**：制图规范图面最小可分辨 0.1 mm；1:25万图幅 1 µm 对应图面 4e-6 mm，远低于墨迹宽度——容差不吞真实界线。

---

## D2 · 构面算法 = 打断 → 平面图 → 半边最小回路追踪

**决策**：不引入 GEOS polygonizer 作为 C++ 主路径；自研三段式管线：
1. **Noding**：均匀网格空间索引（uniform grid bucket，格子数 ≈ 2√N）+ 桶内两两精确求交（含共线重叠的端点注入法：互插对方端点参数，把重叠段细化为可去重的全等子段）；T 型交点按参数打断宿主段。
2. **建图**：节点按「容差网格取整 + 邻域合并」字典去重；全等子段去重（保留双亲 line id 集）。
3. **面追踪**：每节点出边按极角排序；从每条有向半边出发、恒取「来向反侧的最逆时针可行出边」（leftmost-turn），每条半边恰好访问一次 → 得到全部最小闭合回路 + 1 个无界面；迭代剪除 degree-1 悬挂边后再追踪；输出 OGC 逆时针外环。

**备选**：`GEOSPolygonize`（QGIS 已链接 geos_c）。**否决理由**：GEOS polygonizer 输出不带父线溯源（source_lines 继承提示需要自管 noding 阶段的 parent 标记）；且 30 ms/5000 段门禁下 GEOS noding + polygonizer 的分配开销不可控。自研核全部 `std::vector` 值语义、零逐段堆分配，可被 standalone_test 独立压测。

**复杂度**：noding O(N·k + I log I)（k=桶内邻居数，I=交点数），面追踪 O(E log E)（角排序）。5000 段网格用例 k≈4，预算内。

---

## D3 · 核心层 QGIS-free（POD 纯净）

**决策**：`geological_topology_core.{hpp,cpp}` **零 QGIS 依赖**（只含 std::），输入 `std::vector<double>` 折线坐标 + 父 id，输出结构化结果；GeoJSON 序列化在核心内用极简 writer 完成（避免拉入 QgsJson 依赖）。bindings.cpp 负责字符串↔核心结构适配，`py::gil_scoped_release` 包裹计算段。

**理由**：恪守桥 ABI/POD 隔离原则（CLAUDE.md）；核心可被 CMake `qgis_render_bridge_selftest` 目标直接单测（standalone_test.cpp 已有先例），绕过 pyd 构建慢回路。

---

## D4 · pybind 面向：新 `geotopo` 子模块 + JSON 信封 + 显式错误码

**决策**：
- 新子模块 `qgis_render_bridge.geotopo`，函数一律返回 JSON 信封：`{"status":"ok", ...}` / `{"status":"error","code":"PWB-GT-xxx","message":"..."}`。不抛异常（与 mapstack 错误字符串约定同哲学，但带结构化码，便于宿主分类拦截）。
- capability_manifest **不改动**（被 test_qgis_capability_manifest 钉住），宿主用 `hasattr(bridge, "geotopo")` 探测。
- mapstack 新增编辑方法（fault_cut_mirror_features / reshape_shared_boundary / set_map_tool 新 kind）沿用「错误字符串返回」既有约定。
- 错误码段 `PWB-GT-001..PWB-GT-0NN` 在 02-interface-contracts.md 全量定义。

**备选**：并入 `geometry` 子模块。**否决**：geometry 子模块语义是「单 QgsGeometry 运算、抛异常」；构面是集合级拓扑运算，混入破坏二者的契约清晰度。

---

## D5 · 断-相截断：复用 splitFeatures + 语义增量

**决策**：C++ 侧 `faultCutMirrorFeatures(doc_id, curve_json, feature_ids_json, options_json)`：
- `feature_ids` 为空 → bbox 预过滤 + GEOS intersects 自动拾取穿越面；
- 属性延续：依赖 `QgsVectorLayerEditUtils::splitFeatures` 固有克隆；随后对两侧新面写 `fault_bounded=true`（字段缺失时在**同一编辑宏内** `addAttribute` + `changeAttributeValues`，保证一次提交原子生效）；
- 可选 `fault_side`（hanging/footwall）按质心对断层折线方向叉积判定；
- 完成后经既有 `edit_gesture` 回执通道发 `fault_cut` 多层手势。
- 交互层：C++ `PwbFaultCutTool`（QgsMapTool 子类，edit_tools.cpp 内实现，kind=`"faultCut"`）——**Python 侧无 QgsMapTool 可继承**（vendored QGIS 未编 Python 绑定），「继承 QgsMapTool」的契约在 C++ 层兑现；宿主 `activate_tool("fault_cut")` 走 `set_map_tool(addr,"faultCut")`。

**理由**：与 PwbVertexTool v2 模式同构（一处 EditBuffer 宏 + 一条手势回执），最小增量、零新回调面。

---

## D6 · 共边重塑：弧替换 + 双侧守恒校验，失败即拒绝

**决策**：`reshapeSharedBoundary`：
1. 宿主提供（或工具拾取）原共享弧 `arc`（容差内匹配两侧要素环）；
2. 两环各自把 `arc` 段替换为新曲线 `curve`（一侧正向、一侧反向）；
3. 校验：两新环各自 `isGeosValid`；GEOS 二者交集面积 ≈ 0（无重叠）、与原并集差面积 ≈ 0（无裂隙）→ **面积和守恒**（相对容差 `1e-9 * extent²`）；
4. 任一校验失败 → 返回 `PWB-GT-201 系列`错误码，不改任何几何（拒绝式而非修复式——地质上"差一点的重塑"宁可重来）；
5. 成功 → 两侧各一个 EditBuffer 宏 + `addTopologicalPoints` 散布对齐点 + 单条多层 `boundary_reshape` 手势回执。

**备选**：直接 QgsMapToolReshape 两次调用。**否决**：无守恒校验、非原子手势、不保证无 sliver。

---

## D7 · 相序邻接矩阵：Walther 相律的秩差编码

**决策**：新资源 `paleo_workbench/resources/facies_adjacency.json`，内含 8 个_builtin_ 相的**岸线距离秩**（rank）：
`冲积扇=0，三角洲=1，滨岸=2，潟湖=2，潮坪=2，碳酸盐台地=3，陆棚=3，深水盆地=4`；
合法相邻 ⇔ `|rank(a)-rank(b)| ≤ 1`（特殊对以 `allowed_pairs` 白名单微调，如 潟湖↔潮坪、三角洲↔陆棚（前缘滑塌浊积））。
`FaciesAdjacency` 类：`builtin()` / `from_project()`（`project.facies_adjacency` 覆盖）/ `may_touch(a,b) -> (bool, reason)`。
校验器纯 Python + shapely（无桥依赖 → 快速 CI 可跑全矩阵）。

**地质依据**：Walther 相律——相邻出露的相必然在环境梯度上连续；深海相直邻冲积扇（缺陆棚/滨岸过渡）即梯度跳变，判非法。秩编码是相律的可判定化，reason 字段给出"缺失过渡相"的语义提示。

**备选**：直接在 facies_taxonomy.json `_meta` 加邻接。**否决**：taxonomy 加载器契约被既有测试钉住，且项目级 taxonomy 覆盖会静默丢邻接；独立资源 + 独立 project 键可外科叠加。

---

## D8 · 守卫接入点：commit_all 第三谓词 + save_edits 同步门

**决策**：`NativeEditSessionController.commit_all(*, gate, topology, geology)` 新增 `geology` 谓词（`GeologyGate(run: Callable[[list[LayerSnapshot]], list[InvariantViolation]])`）；`CompositeEditController.save_edits/_gate_topology_issues` 并联接入。违规 severity=error → 拦截提交（会话保留）；warning → 放行但经 `state_changed` 通道上报语义警告。校验输入 = `readback_features` 镜像真值 + 关联线层记录。

---

## D9 · 原子宏事务：手势级原子（既有）+ 提交级补偿（新增）

**决策**：分两级兑现「原子」：
- **手势级**（一次 Ctrl+Z 跨层同步撤销）：既有 `EditGestureManager.undo_plan()` 已支持；补 `CompoundEditTransaction`（controller.compound_macro(ctx mgr)）把一个手势块内触达的全部层（原生回执 + Python 会话）登记为单手势。
- **提交级**（commit_all 中途失败不留半提交）：提交前快照各层镜像（`mirror_features_json(limit=0)`）；第 k 层 commit 失败 → 对已提交层开补偿编辑（按快照重写几何/属性、删除新增），包成一个 `undo_text="撤销复合提交"` 的宏；补偿后整体返回失败。诚实边界：补偿是"内容等价恢复"，feature id 可能变化（QGIS 内存层新增 fid 重排）——文档 04 记录此限制。

**备选**：QGIS transaction group。**否决**：镜像层是相互独立 QgsVectorLayer（不同 provider 实例），无共享事务上下文可用。

---

## D10 · 构建管线与版本

**决策**：新源文件同时加入 setup.py 源清单与 CMakeLists `qgis_render_bridge_core`/selftest 目标；**不**改 capability_manifest、**不**动版本号（bindings 0.11.0a0 / setup 0.7.0a0 既有漂移不属于本任务修复范围，记录在案）。Windows 迭代编译走 `.scratch/build_bridge.bat`（vendor junction 复用 + `CMAKE_BUILD_PARALLEL_LEVEL=2`）。

---

## 决策时间线

| 日期 | 决策 | 状态 |
|------|------|------|
| 2026-09-14 | D1–D10 全部立项自决 | Accepted |
