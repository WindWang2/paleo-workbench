# 拓扑编辑迁移 M2 跨层与配置型能力——实施记录（2026-09-12）

> 规格 §8 → §4。M2 内容：全部层档 + 拓扑点散布 + 避免重叠（开关 +
> 数字化免费 + 顶点/移动复刻）+ 追踪。退出标准：场景 6、7、8、11 通过；
> M1 回归绿。

## 落地清单

| 实现件 | 位置 | 说明 |
|---|---|---|
| 全部层档 | `edit_tools.cpp` `discoverAllLayers` + `QgisMapStack::setVertexEditScope` | 跨候选层（全部 pwb 镜像线/面层）**同 CRS 过滤**后取锚 → 1e-8 联合集；未在会话的伙伴层在 press 时同步发 `join_requested`（宿主门禁复查入集，§3 按需生长），release 按当前可编辑层重组落位 |
| 每层一宏（多层手势） | `applyVertexMoves`/`finishSharedDeleteAt` | 每层恰一宏：moveVertex → `avoidIntersectionsV2`（多部件保留最大块；基底无效保原几何；裁空放弃）→ `changeGeometry` → 自层 `addTopologicalPoints`（新旧位置）；`edit_gesture` 回调携带 `layers` 有序层表（手势管理器逆序撤销的输入） |
| 拓扑点散布 | 同上 + `scatterTopologicalPoints` + `addMirrorFeature` | 手势内自层闭合 + 其余同 CRS 会话层各一宏（**bbox 预查**，无插入 `destroyEditCommand` 不留痕）；数字化路由写入时新要素顶点散布进本层既有要素（共享边闭合）。开关 = 画布工程 `topologicalEditing`（随拓扑开关推送） |
| 避免重叠 | `setSnappingConfig` 的 `avoid_intersections` 段 + 顶点/移动复刻 + `PwbMoveTool` 原生模式 | 数字化免费（GUI 基类 `QgsMapToolCaptureLayerGeometry` 内建裁切——桥只推 `QgsProject` 配置）；顶点/移动手势内复刻 `QgsAvoidIntersectionsOperation` 语义；`PwbMoveTool` 获原生会话模式（一宏 "Moved feature" + 平移 + 裁切 + 全顶点散布）；数字化工具目标层**跟随会话当前层**（`setMapTool` 时 `setLayer`，异 CRS/非会话回落 scratch——"当前层"裁切语义成立的前提） |
| 追踪 | `QgisMapStack::setTracingEnabled` | `QgsMapCanvasTracer` 注册进 canvas 全局表（全体捕获工具**免费获得**；图随缩放/层编辑自动重建）；开关 = checkable QAction；端点容差 = 常规吸附容差（无 setSnapTolerance API，规格已注） |
| 宿主 | `composite_editing` 三开关 + `join_native_layers` + 持久化；`canvas_shim` join/gesture 路由 + 两个推面；`composite_document` 三命令分派 + 拒绝提示 | 档位默认当前层；避免重叠默认开（裁切 = 当前编辑层）；追踪默认关；`mapping_workspace["topo_editing"]` 随工程持久化；`native_join_refused` → 状态条（场景 7 提示） |

## 验收证据

- `tests/test_qgis_topo_m2_cross_layer.py`（5 项，真桥）：场景 6（三层
  共享节点同步 + 逆序 undo 整体回退）、场景 7（RAW 邻层不参与不动 + 其余
  正常 + 未入会话）、场景 8（数字化重叠裁净 + 被交面获得拓扑点）、
  场景 11（追踪沿弯边数字化——公共边顶点精确重合，含弯点）、tracer
  开关往返。
- M1/M0 回归全绿；合并批次（17 文件）相对 M0 基线**零新增失败**。

## 关键修复与教训（实施中实测钉死）

1. **单例跨栈毒化（根因）**：`QgsProject::instance()` 在多栈序列里被上一
   栈的 sync/复位时序污染（第二栈手势误散布/误裁）。修复：本类全部读
   **画布挂载工程** `canvas()->project()`；单例仅供 GUI 数字化基类读取，
   由 `setSnappingConfig` 双侧同步、shutdown 条件复位（`touched_`
   守卫）。消融矩阵四变体全净（`/tmp/ablate.py` 语义已入测试）。
2. **QgsMapCanvasTracer 注册表悬垂**：画布先亡 → tracer 的 destroyed
   槽清空 `mCanvas` → 析构 `sTracers->remove(nullptr)` 死键残留 → 地址
   复用返回悬垂 tracer。桥侧不显式删 tracer（canvas 由宿主持有）；
   测试侧 teardown 卫生 = 切回 pan（digitize deactivate 会恢复
   currentLayer——层销毁同息语境下悬垂）+ 回滚会话（`_cleanup`）。
3. **shutdown 顺序**：先 `unsetMapTool`（层/工程完整时干净去激活）再
   摘层摘工程。
4. 拆分脚本教训（M1 分支带病）：`onGeometryChanged` 曾被区间删除吞掉
   ——链接不报缺符号，仅 dlopen 才炸；已恢复并入 M2 修复提交。

## 后置（M3+）

- 分割/合并（场景 9/10）+ 属性继承；检查器（M4）；Python 拓扑服务退休
  （M5）。
- 框选多节点（§4 v2）：共享节点拖动/联合删除已交付，Shift 批量框选
  随 M3 工具面收敛。
- 三开关的 QAction/工具栏按钮注册（当前为命令分派 + 控制器 setter，
  UI 面随工作站工具栏工作）。
- 追踪的 `setAddPointsOnIntersectionsEnabled`（3.40+）评估。
