# 07 — 已知限制与记录项（Known Limitations）

标记：`[v12]` 本集新识别 ｜ `[inherited]` 承自既往（注明来源） ｜ `[env]` 环境相关。

## 本集新识别

1. `[v12]` **Windows 腿从未真正验证过真桥编辑链路**。截至基线，`-m qgis` 的验收记录全部来自 Linux 腿；D-A（求值顺序）正是因此漏网。M0-3/D12 落地前，任何"顶点/拓扑编辑已交付"的结论都不成立。
2. `[v12]` **回退渲染栈的标注与原生不等价**：不实现 PAL 的避让/优先级求解（D7）。用户在 QGIS 标注对话框里设的 Priority/避让设置**仅在原生渲染路径生效**；回退栈只保证顺序（zIndex + 图层序）与"标注不被几何覆盖"。
3. `[v12]` `topology` 工具条开关是**双重语义**（编辑期拓扑联动 + 保存期 Python 校验门，D6）。文案会写明，但语义仍与 QGIS 原版不同。
4. `[v12]` **网格捕捉仅回退栈**有效（Python 专有，无 QGIS 对应物，不下推）——与 V7 08-4、V10 的记录一致。
5. `[v12]` **逐层捕捉优先级**在原生路径当前无效（对话框有列但不下发）；M4-3 复评，届时要么下推（QGIS 无对应字段则需自研排序）要么在 UI 上标注"仅回退栈生效"。
6. `[v12]` **"影子桥"陷阱**：手工 `setup.py build_ext --inplace` 在仓库根目录执行会把 `.pyd` 落到根目录并遮蔽包内产物（`sys.path` 优先 cwd），导致"改了源码没生效"或"修复误判为生效"。走 `scripts/build-qgis-bridge.ps1` / `pip install -e` 不会踩到；conftest 断言（M0-5）是兜底。
7. `[v12]` **桥增量重编需要 `LIB` 含 `C:\deps\vcpkg\installed\x64-windows\lib`**（gdal/proj 导入库不随 vendor 构建产出）。已有脚本编码了该要求，但 V10 时代的文档没写；M0-5 在脚本注释与文档两侧补齐。

## 承自既往（与本集相关者）

8. `[inherited]` 顶点的插入/删除是 **native-only**，不回填 Python 回退栈（V10 `04-decisions.md` D3、`11-known-limitations.md` #2）。
9. `[inherited]` 连续 Delete 需要重新 hover（抗陈旧镜像守卫，V10 #3）；M2-3 处理。
10. `[inherited]` 插入→hover→Delete 若在 120ms 镜像防抖窗口内完成，可能命中陈旧几何（V10 #5）。会话边界守卫会拒绝越界，属"概率极低"档。
11. `[inherited]` 多顶点选择/段移动在 V10 判 DEFERRED（`05-edit-tool-matrix.md:32`），phase2 已补框选多节点；**段移动**本集 M2-1 立项。
12. `[inherited]` `canvas_destination_crs` 在缺 `proj.db` 的工作区返回 `""`，数字化 CRS 守卫此时降级（V10 #9）。
13. `[inherited]` locator 预热是同步索引构建；超大参考层的首次捕捉配置下推可能卡顿（V10 #10）。
14. `[inherited]` geotopo 交互工具（断层切割、共享弧重塑）的 C++ 与 `geotopo_service` 实现**在 UI 上不可达**（无 action 登记）；本集 M4-2 立项接线。
15. `[inherited]` QC/拓扑错误的画布高亮通道未接线（paleo-ui-workbench `04-known-limitations.md` #64）；M4-1 立项。
16. `[inherited]` 撤销深度受 QGIS undo 栈上限（约 200 步）约束。
17. `[inherited]` 原生 `QgsLayerTreeView` 的右键菜单项无法从 Python 覆写 enablement；既有做法是在 `contextMenuAboutToShow` 上补动作（工作区未提交改动里的「复制为草稿…」即此路径）。
18. `[inherited]` vendored QGIS 带两处 Windows 支持补丁（`third_party/qgis/CMakeLists.txt` 的 ARCHIVE 输出目录、`src/core/CMakeLists.txt` 的内部 spatialindex 静态库），上游同步时需重放。

## 文档维护项（与本集相关）

19. `docs/development/qgis-native-vector-authoring-v10/06-snapping-topology.md:57-60` 仍把 `TopologyService.propagate_shared_vertex` / `CompoundUndoGroup` 描述为提交期通路——二者已于 M5 退役（`docs/development/topological-editing-m5.md:10-13`），需标注。
20. 同一文档集多处写 `PwbSnapIndicator`，实现实际复用公开类 `QgsSnapIndicator`（`edit_tools.hpp:80-99`）；`10-review-findings.md:22` 声称已修正但 01/03/04/05/06 均未改。
21. `docs/development/qgis-authoring-ux-v10/05-toolbar.md:18` 写"45 id 全登记"，当前 `tool_availability.TOOL_GROUPS` 实为 50 个 id（V10 新增 5 个）。

## 硬排除（沿用）

22. 100GB 地震数据零接触；RAW 保护层不可直接编辑；Z/M 不引入；不链接 QGIS app 层类。
