# 03 — 目标架构与不变量（Target Architecture）

## 1. 编辑目标权威链（本集的核心修复对象）

当前"谁是编辑目标"散落在五个地方，各自可有各自的答案——这正是 D-B 的结构性成因：

```
领域层  edit_controller.active_layer_id（权威 1）
画布层  QgsMapCanvas::currentLayer（原生选择/identify/顶点工具的目标，权威 2）
会话层  NativeEditSessionController._sessions / SESSION_SET（权威 3）
工具层  PwbVertexTool.edit_layer_provider_()（读权威 2 ∩ 权威 3）
面板层  QgsLayerTreeView current / LayerManagerPanel 选中行（权威 4）
```

**目标态**：一条单向派生链，链路各级**只能由链上游写**，且上游每次变更都必须把变更**传播到链尾**（幂等重推，不允许"同值即跳过"）。

```
active_layer_id  ──(set/repush)──►  canvas.currentLayer  ──(∩ 会话集合)──►  tool edit layer
       │                                   ▲
       └──(会话开启/关闭/入集)──────────────┘
面板选中行 ◄──(呈现，不写权威)
```

落地规则：

- **R1** `CompositeEditController.set_active_layer` 的短路条件从"id 未变"改为"id 未变 **且** 画布已确认"——需要新增画布查询面 `QgisCanvasShim.current_layer_doc_id()`（桥侧加 `current_layer_id(canvas_addr)`，从 `canvas->currentLayer()->customProperty("pwb/doc_id")` 读；旧桥返回 `""` 时退化为"总是重推"）。
- **R2** 三个必须重推的时刻：① 原生会话 `open()` 成功（`native_edit_session.py:104` 之后由宿主推）；② 会话入集 `join_native_layers`（`composite_editing.py:1718-1740`）为每个新入集层；③ 每次 `set_layer_snapshot()` 完成后（镜像重建/新增都可能让"上一个被拒绝的 id"变得有效）——③ 是兜底，代价是一次 Python→C++ 调用，可接受。
- **R3** 桥侧 `editLayerProvider` 增加**会话兜底**：`canvas->currentLayer()` 不在 `mirror_edit_connections` 时，若该画布的会话集合恰有一个可编辑层，则用之；多于一个时按树序取最上者，并把"兜底生效"经 `edit_gesture` 的 payload 记一个 `via` 字段（可诊断，不改语义）。
- **R4** 面板选中是**呈现**：它读 `active_layer_id`，用户点击经 `active_layer_changed` 回到 `set_active_layer`；面板不得直写画布（现状已如此，保持）。

## 2. 失败可见性通道（不许无声死键）

三条强制规则：

- **R5** 任何 `tool_operation(False)` 必须伴随一条可读原因（`commit_rejected` 或状态条）。当前缺口：`dispatch_edit_pick` 对 `vertex_moved` 失败不发拒绝（`canvas_shim.py:334-337`）；`pick_miss` 被丢弃（`:1287-1288`）。两者都要补。
- **R6** 工具激活即校验前置：激活 `vertex`/`move_feature` 前做一次"可用性预检"——原生会话已开但 `editLayer()` 建立不起来（无当前层/层不在会话）时，**拒绝激活并给原因**，而不是激活后静默。实现：宿主在 `_rebind_active_tool` 后调用新增桥查询 `vertex_tool_ready(canvas_addr) -> bool`；旧桥无此面 → 保守放行（保持现状语义，但补 R5 的上浮）。
- **R7** 诊断可开关：现场调试脚手架（现为 `canvas_shim` 里的 TEMP-DIAG 落盘 + `canvas.grab()`）改为 `PALEO_EDIT_DIAG=1` 环境变量控制，默认关闭；保留的信号面（`snap_feedback`）必须有消费方（状态条）。

## 3. 栈序单一来源（图层顺序）

**不变量 I-1**：`mirror_tree_order_top_first()`（桥，树的 DFS top-first 序）是**唯一**顺序权威；领域层自下而上列表、面板行序都是它的投影。

```
QgsLayerTree (权威)
   ├─► 面板行序          = 树遍历序（行 0 = 顶层）          原生树构造上成立
   ├─► 画布绘制序        = 反向遍历（先画顶层？否——从栈底画）  构造上成立
   └─► 布局/图例序       = 同一 DFS（V11 11-layout-legend §3-21 已修）
领域 _layers（自下而上）  ◄── 只能由树回声（reversed）更新，不得反推画布
```

落地规则：

- **R8** 删除 `QgisLayerTreePanel._push_mirror_order` 这条**旁路**：用户/程序化重排一律写 `LayerGroupController` 的 placement（组模式已是权威；平铺模式下 controller 也在场），由 reconcile diff 落到树；确实需要平铺快速路径时，**必须与 `qgis_mirror.py:1124` 同式反转**，并由不变量用例钉住。
- **R9** 洋葱皮置顶/复原走同一通道：`stratigraphic_timeline_slider._raise_layer_to_top` 现在循环 `move_layer(..., -1)`，在组模式下是 no-op；改为调用组控制器的"临时置顶"placement（会话覆盖，不持久化——与 V11 04-ordering §3 "临时会话覆盖不落盘"一致）。
- **R10** 新增层落点统一为"归属组内**置顶**"（QGIS 约定）：`layer_tree_plan._merge_container_order` 的尾部追加改为头部插入，并同步 `tests/test_layer_tree_plan_v11.py:120-138`（当前钉死 `ids[-1] == "l_new"` 的断言随语义更新）。
- **R11** 回退面板对齐语义：`LayerManagerPanel` 行 0 = 顶层（构建行时反向遍历 `_layers`，`_move_up/_move_down` 方向同步）；若决定废弃回退面板，则把依赖它的用例迁到原生树，并在 07 记录。

## 4. 标注顺序（Labeling）

**不变量 I-2**：标注在**几何之后**单独一个 pass 绘制；同 `zIndex` 时按图层序（**顶层最后画**）。原生栈已满足。

- **R12** 回退渲染器：删掉点层内联标注分支（`map_render_backend.py:1558-1571`），统一走"收集 `_LabelSpec` → 帧末按**自下而上**的图层序绘制"（即现在的 worker 路径 `:940-970` + `_finalize_frame`），保证两条路径同序、且标注永不被上层几何覆盖。
- **R13** 回退渲染器解析 `labeling_xml` 的 `zIndex`（有则参与排序）；`priority`/避让属于 PAL 引擎能力，回退栈无法等价 → 在标注对话框旁给一行提示"高级避让仅在 QGIS 渲染路径生效"，并记入 07。
- **R14** 栈序变化（重排/显隐/新增）必须触发标注序重算——回退栈的帧缓存键需包含图层序（`_frame_key()` 检查；原生栈由 QGIS 负责）。

## 5. 一条顶点拖动的目标端到端流（修复后）

```
用户按下顶点
  Qt → QgsMapCanvas::mousePressEvent
      → PwbVertexTool::canvasPressEvent
           ├ editLayer() != nullptr ?  ←─ R1/R2/R3 保证
           │    ├ verticesNear(layer, pt, tol)          # 命中=拖动集合
           │    ├ [全层档] discoverAllLayers(...) + join_requested（门禁复查入集）
           │    └ beginSharedDrag(anchor, shared)       # D-A 修复：先取锚点
           │         ├ 共享节点 marker + rubber band（拖动预览）
           │         └ 捕捉指示器（QgsSnapIndicator）
           └ 拖动中：snapOrRaw 跟随捕捉；拓扑点即时传播（addTopologicalPoints）
用户松手
  → finishSharedDrag(target)
       ├ 零位移抑制（<10px 不算拖动）
       ├ 按"释放时"可编辑层重组 → 逐层 beginEditCommand("Moved vertex")
       ├ avoidIntersectionsV2（越层裁切）
       └ scatterTopologicalPoints（跨层拓扑点）
  → callback_("edit_gesture", {layer_doc_id, layers[], gesture, undo_text, features[]})
  → canvas_shim._on_edit_pick → record_native_gesture（宿主台账 + 撤销计划）
  → 保存编辑：commit_all（角色门 → 拓扑零错误门 → 地质不变量门 → 逐层 commit + 增量回写）
```

每一步的失败都必须落到 R5/R6 的可见通道。

## 6. 不变量清单（测试可直接引用）

| 编号 | 不变量 | 钉法（见 06） |
|---|---|---|
| I-1 | 面板行序 == 画布图层序 == `mirror_tree_order_top_first()` | 三动作参数化用例（新建/拖拽/洋葱皮） |
| I-2 | 标注晚于几何；同 zIndex 时顶层标注在上 | 双层面重叠锚点用例（原生 + 回退各一） |
| I-3 | 会话开启后，画布当前层 == 会话层 | 宿主链路用例 |
| I-4 | 编辑工具激活 ⇒ 画布侧确有可写目标（否则拒绝激活并给原因） | 宿主用例 + 桥查询 |
| I-5 | 任何 `tool_operation(False)` 都有可读原因 | 纯 Python 用例（`dispatch_edit_pick` 直打） |
| I-6 | 领域 `_layers` 序 == reversed(树序) | 已有 `test_layer_order_parity_v11.py` 扩展 |
| I-7 | MSVC/GCC 双平台下同一条编辑链路行为一致 | 双平台 CI 腿（Windows 腿必须含真桥用例） |
