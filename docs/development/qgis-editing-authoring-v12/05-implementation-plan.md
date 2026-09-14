# 05 — 实施计划（M0–M5）

每项 = 改动点（含文件坐标）+ 验收。M0 是止血，必须单独发布；M1–M5 可按需并行。

---

## M0｜编辑链路止血（P0，本集最高优先级）

### M0-1 D-A 崩溃修复
- 改：`native/qgis_render_bridge/src/edit_tools.cpp:1031` → 先取锚点到局部 `const QgsPointXY`，再 `std::move(shared)`。
- 重生桥（构建命令与两个坑见 00 §5）。
- 验收：`pytest -m qgis tests/test_qgis_topo_m1_native_editing.py tests/test_qgis_topo_m2_cross_layer.py` 在 **Windows 腿全绿**（基线：Windows 腿当前必崩，F1）。
- 顺手巡扫：`git grep -E '\b(front|back)\(\)[^;]*std::move'` 在 native 下应保持为空。

### M0-2 D-B 当前层推送链修复（四层防御）
1. 宿主重推（R2）：
   - `composite_editing.start_editing()`：`native_editing.open(...)` 返回 ok 后补 `self._canvas.set_current_layer(layer.id)`（`composite_editing.py:1388-1394` 一带）。
   - `composite_editing.join_native_layers()`：每个成功入集层同样补推（`:1718-1740`）。
   - `composite_document._sync_composition_now()`：镜像发布完成后统一重推活动层（`:4756-4795` 尾部）。
2. 幂等重推（R1）：`set_active_layer` 的短路加"画布已确认"条件；桥新增 `current_layer_id(canvas_addr)`（`map_stack_service.cpp` + `bindings.cpp` manifest 旗标 `current_layer_query`），旧桥退化"总是重推"。
3. 桥侧会话兜底（R3）：`map_stack_service.cpp:5269-5282` 的 `setEditLayerProvider` 增加唯一可编辑会话层兜底。
4. 失败上浮（R5）：`canvas_shim.dispatch_edit_pick` 给 `vertex_moved` 补合成拒绝（`canvas_shim.py:334-337`）；`pick_miss` 上浮为状态条信息（`:1287-1288`）。
- 验收：新增宿主链路用例（I-3/I-4，见 06）；`tests/test_identify_tool_enablement.py`、`tests/test_v10_active_layer_chain.py` 不回归。

### M0-3 编辑链路回归门
- 新增 `tests/test_qgis_edit_chain_v12.py`（真桥）：新建草稿 → 开始编辑 → 激活节点编辑 → 断言画布当前层 == 该层 → 拖动顶点 → **几何改变** → 保存编辑 → 增量回写。Windows 腿必跑。
- 新增 `tests/test_vertex_receipt_v12.py`（纯 Python）：`dispatch_edit_pick` 在 `session=None` 时对 `vertex_moved/inserted/deleted` 均发 `commit_rejected` + `tool_operation(False)`（I-5）。

### M0-4 诊断脚手架收口（D11）
- `canvas_shim.set_layer_snapshot` 的 TEMP-DIAG 段（含 `.workbuddy/publish_trace.txt` 与 `canvas.grab()`）改为 `PALEO_EDIT_DIAG=1` 控制，默认关闭。
- `snap_feedback` 接到状态条（最小消费方：显示"捕捉：层/类型/距离"，200ms 节流沿用 C++ 侧）。

### M0-5 构建与门禁卫生
- 核对既有 `scripts/build-qgis-bridge.ps1` 已覆盖 00 §5 的两项要求（`LIB` 含 vcpkg 库目录、不得产生根目录影子 `.pyd`）；若脚本走 `uv pip install -e` 则第二项天然满足，只需在脚本头部注释里写明"手工 `build_ext --inplace` 必须在包目录内执行"。
- `tests/conftest.py` 在 QGIS 腿断言 `find_spec('qgis_render_bridge').origin` 位于 `native/qgis_render_bridge/`（防静默加载错产物）。

---

## M1｜工具条对齐（捕捉 + 数字化，UI 面）

| 项 | 改动 | 验收 |
|---|---|---|
| M1-1 捕捉模式选择器 | 工具条加 combo（所有图层/当前图层/高级配置）→ `set_current_layer_only()` + `_push_snapping_config` 的新 `mode` 分支（`composite_editing.py:2304-2396`） | 三态各下一次推，C++ 收到 `AllLayers/ActiveLayer/AdvancedConfiguration` |
| M1-2 避免重叠 | 工具条 checkable「避免重叠」+ 对话框逐层项；应用侧发 `avoid_intersections.layer_doc_ids` | 拖动越层时按层裁切（扩展现有 `test_qgis_topo_m2_cross_layer.py:186`） |
| M1-3 追踪开关 | 工具条 checkable「追踪」→ 既有 `set_tracing_enabled` | 开关往返 + `QgsMapCanvasTracer` 注册断言（已有 C++ 用例） |
| M1-4 顶点档位 | 工具条/对话框「顶点：当前层/全部层」→ `set_vertex_scope` | 档位往返 + 全层档跨层发现 |
| M1-5 捕捉读数 | 状态条消费 `snap_feedback` | 悬停显示层/类型/距离；关捕捉时清空 |
| M1-6 容差单位 | 对话框逐层单位选择 → C++ `setUnits`（去硬编码，`map_stack_service.cpp:4792`） | 像素/地图单位各一次下推 + 命中阈值变化 |
| M1-7 自捕捉指示 | 对话框显示"活动层自身参与捕捉"当前态 | 状态一致（只读面，不改行为） |
| M1-8 激活预检（R6） | `vertex`/`move_feature` 激活前 `vertex_tool_ready` 查询 | 无目标时拒绝激活 + 原因（I-4） |

---

## M2｜顶点工具深交互（V10 遗留项）

- M2-1 段移动（segment move）：C++ 支持"抓段拖段"（顶点对位移），与共享边/拓扑点联动；宿主侧无需新增命令（走同一 `edit_gesture`）。
- M2-2 移动要素的捕捉跟随：`PwbMoveTool` 的 dx/dy 改为 `snapOrRaw` 结果（V10 11-#6 关闭）。
- M2-3 连续 Delete：hover 态在提交后保留（当前 120ms 防陈旧窗口清 hover，需区分"镜像已更新"与"陈旧"）。
- M2-4 零位移点击反馈：单击不移动时给一行状态条"单击不移动节点（拖动以编辑）"，消除"是不是坏了"的疑惑。
- M2-5 插入/删除在回退栈的语义：明确**不**回填 Python 回退（沿用 V10 D3），但工具激活期在无原生会话时禁用并给原因。

## M3｜栈序与标注序一致性（D-C / D-D）

- M3-1 删 `_push_mirror_order` 旁路（D8）；洋葱皮置顶走组控制器**会话覆盖**（R9）。
- M3-2 新层落点置顶（D9）+ 更新 `tests/test_layer_tree_plan_v11.py:120-138`。
- M3-3 回退面板语义对齐（D10）。
- M3-4 回退渲染器标注统一帧末绘制 + 解析 `zIndex`（R12/R13/R14）。
- M3-5 不变量用例：I-1（面板行序 == 画布序 == 树序，参数化三动作）、I-2（双层标注压盖）、I-6。

## M4｜拓扑闭环与"无 UI 面"接线（D13）

- M4-1 拓扑错误 → 画布定位跳转（检查器/QC hub ↔ `highlight_features`）。
- M4-2 `fault_cut` / `boundaryReshape` 进工具面（action 登记 + 门禁 + 帮助文案）。
- M4-3 比例依赖捕捉 + 逐层优先级下推（`layer_priority` → QGIS 无对应字段则明确记录为"仅回退栈生效"）。
- M4-4 合并属性对话框在合并流程中的入口与 `pan_to_selection`。

## M5｜数字化工具条全量（D4）

- M5-A（第一批）：填充环、矩形/正多边形、圆弧、删除环/删除部件/移动部件的画布拾取、捕捉几何到图层、修剪/延伸、偏移曲线、反转线方向、简化、平滑、分割部件。
- M5-B（第二批）：旋转要素、缩放要素、剪切/复制/粘贴要素（粘贴先过 D5 门禁与字段映射）。

**每项统一验收模板**：① 桥侧算子存在（或新增）；② 工具面（工具条/命令面板/快捷键）登记在 `tool_availability.TOOL_GROUPS`；③ 可用性门禁（会话/角色/CRS）与原因；④ 一个真桥行为用例 + 一个可用性用例；⑤ 帮助文案（`tool_help.py`）。

---

## 实施顺序与依赖

```
M0（止血，独立发布）
 ├─► M1（UI 面接线：先把既有能力暴露出来，用户立刻感到"能用了"）
 ├─► M2（深交互）
 └─► M3（栈序/标注序，可与 M1/M2 并行）
M4 依赖 M1（追综/避免重叠表面）与 M0（会话/当前层权威）
M5 依赖 M1（digitizer 门禁与捕捉联动）与 M2（顶点工具稳定性）
```
