# 拓扑编辑迁移 M3 几何命令——实施记录（2026-09-12）

> 规格 §8 → §4。M3 内容：无缝分割（画布切线）+ 无缝合并（对话框）+
> 属性继承。退出标准：场景 9、10 通过；M2 回归绿。

## 落地清单

| 实现件 | 位置 | 说明 |
|---|---|---|
| 无缝分割（桥） | `QgisMapStack::splitMirrorFeatures`（`map_stack_service.{hpp,cpp}`） | `splitFeatures(curve, topologyTestPoints, true, topologicalEditing=true)`（命令本身即拓扑分割，不读工程开关）；宿主 id 列表先 `selectByIds`；最大块继承源 fid（桌面 split policy）；新块 Duplicate 继承源属性并分配 `split-<uuid>` 宿主 id。空结果 `destroyEditCommand` 不留痕。 |
| 邻层拓扑点 | 同上 | 画布挂载工程 `project()->mapLayers()`（**禁止读单例**）；同 CRS 可编辑线/面镜像层各一宏 `"Topological points from Features split"`；无插入 `destroyEditCommand`。邻层只插点不分割。 |
| 无缝合并（桥） | `QgisMapStack::mergeMirrorFeatures` | 宿主确认后执行：`union` + `QgsVectorLayerEditUtils::mergeFeatures`（一宏 `"Merged features"`）。`target_id` 缺省 = 面积最大。fid 表在 undo 前保留（commit 时 `committedRemoved` 出表）。 |
| 手势回调 | 分割/合并成功后 `edit_pick` 发 `edit_gesture` | `layers` 有序表（目标层 + 实际插点的邻层）→ 宿主手势管理器逆序撤销。 |
| 切线数字化 | `composite_editing._native_split_begin` / `_commit_native_split` / `cancel_native_capture` | `geometry_command("split")` 在原生会话下切 `addLine`（复用 `PwbDigitizeTool` 线模式，吸附/追踪免费）；`commit_native_capture` 拦截 pending 切线进桥，不落「新线要素」。Esc/空取消清 pending。`attach_canvas` 把原生路由挂到 `tools`（shim 只持有工具栈）。 |
| 合并对话框 | `mapping/merge_attributes.plan_merge_attributes` + `ui/workstation/merge_features_dialog.py` | 预填面积最大要素属性（下拉可换源）；相分类字段冲突高亮可改。桥只执行确认后的 payload。 |
| 原生会话接线 | `composite_editing.geometry_command` | 原生会话走桥；Python 会话保持选中线切割 / shapely-or-bridge 合并。`split_ready`/`merge_ready` 纳入原生会话。 |
| 版本 | `bindings.cpp` `__version__` | 0.8.0a0 → **0.9.0a0**。 |

## 验收证据

- `tests/test_qgis_topo_m3_geometry_commands.py`（6 项，真桥）：场景 9
  （两块继承源属性 + 最大块保留 fid + 一 undo 全撤；邻层插点不分割 +
  逆序 undo；追踪切线沿弯边；空分割不留宏）+ 场景 10（union + 归并
  属性 + 一 undo 全撤；缺省 target = 最大面积）。
- `tests/test_topo_m3_geometry_commands.py`（6 项，宿主）：合并计划预填/
  冲突、对话框改值、原生 `geometry_command` merge/split 走桥、Python
  会话选中线切割仍可用。
- M2/M1/M0 回归：`test_qgis_topo_m2_cross_layer` + `test_qgis_topo_m1_*` +
  `test_topo_m1_*` + `test_topo_m0_foundation` **40 过 / 0 失败**。
- 桥构建：clang-22；`__version__` 0.9.0a0；worktree sitecustomize 预载
  本地 `.so` 并 dlopen 验证。

## 关键约束（继承 M2，未重蹈）

1. 桥侧新代码一律读 **画布挂载工程** `project()`，不读
   `QgsProject::instance()`（单例跨栈毒化）。
2. 测试 teardown 卫生：`set_map_tool(pan)` + `roll_back_mirror_layer`
   （`_cleanup`）。
3. 画布 extent 在 upsert 之后设置。

## 后置（M4+）

- 检查器（场景 12–14、16）；Python 拓扑服务退休（M5）。
- 框选多节点（§4 v2 Shift 批量）仍随工具面收敛。
- 分割/合并的工具栏按钮与切线 rubber-band 提示文案（当前为命令分派 +
  状态消息）。
- 分割邻层拓扑点只作用于**已在会话中的可编辑层**（对齐桌面
  `QgsMapToolSplitFeatures`）；不发 `join_requested`。顶点全部层档的
  按需入集仍是 M2 行为。
