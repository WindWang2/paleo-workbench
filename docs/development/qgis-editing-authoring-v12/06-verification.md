# 06 — 验证与测试计划（Verification）

## 1. 基线实测记录（本集诊断阶段，Windows / MSVC，真桥）

命令统一为 `./.venv/Scripts/python.exe -m pytest <target> -m qgis -q`（`-s` 时打印探针）。

| 目标 | 结果 | 解读 |
|---|---|---|
| `tests/test_qgis_topo_m1_native_editing.py`（全文件） | **崩溃**（access violation，mousePress） | F1：v2 顶点拖动不可用（D-A） |
| `tests/test_qgis_topo_m2_cross_layer.py`（全文件） | **崩溃** | 同上 |
| `tests/test_qgis_v10_edit_tools.py` | 12 passed | 插点/删点/捕捉反馈等路径完好（F7） |
| `tests/test_qgis_vertex_move_tools.py` + `tests/test_qgis_snapping_config.py` | 7 passed | v1 回调 + 捕捉配置下发完好（F7） |
| `tests/test_qgis_topo_phase2.py` | 6 passed | 框选多节点 + 平移拖动完好（该路径不创建共享节点 marker） |
| `tests/test_qgis_topo_m3_geometry_commands.py` / `m4_checker` | 各 6 passed | 切分/合并/检查器完好 |
| 变体矩阵（自建探针） | A 崩 / B 通过 / C 通过 / D 崩 / E 通过 | F3：触发条件是"v2 + 命中顶点" |
| 插桩构建 + 一行修复 | M1 5 passed、M2 5 passed | F4：D-A 修复有效且无副作用 |
| 宿主级探针（`CompositeDocument` + 真桥） | 接受推送数 = 0 | F5：D-B 成立 |
| 无当前层拖动探针 | `events=['vertex_moved']`、几何未变、无提示 | F6：v1 静默失败成立 |

> 说明：诊断用的临时探针文件与插桩构建**已全部还原**（工作区仅剩原有的未提交改动）。因此 **M0-1 必须在正式实施时重跑一次修复验证**，不得直接引用本表作为"已完成"证据。

## 2. 新增用例设计（按不变量）

| 用例 | 类型 | 设计要点 | 钉住 |
|---|---|---|---|
| `test_qgis_edit_chain_v12.py` | 真桥（Windows 腿必跑） | `CompositeDocument(ProjectDocument.new("t"))` → `create_layer("草稿","polygon")` → `start_editing()` → `activate_tool("vertex")` → 断言 `canvas.current_layer_doc_id() == layer.id` → 在顶点上按下+拖动 → 断言镜像几何改变、`edit_gesture` 收到 | I-3、D-A、D-B |
| `test_vertex_receipt_v12.py` | 纯 Python | `dispatch_edit_pick(fake_shim, tool_with_session_None, "vertex_moved", {...})` → 断言 `commit_rejected` 与 `tool_operation(False)` 均发出 | I-5 |
| `test_vertex_tool_ready_v12.py` | 真桥 + 宿主 | 无会话/无当前层时激活 `vertex` → 断言拒绝激活且给出原因；有会话+当前层 → 允许 | I-4 |
| `test_layer_stack_order_parity_v12.py` | 真桥 | 三动作参数化（新建 / 拖拽重排 / 洋葱皮置顶与复原）→ 断言面板行序 == `mirror_tree_order_top_first()` == `canvas.layers()` 序 | I-1、D-C1/C2 |
| `test_label_order_v12.py` | 回退（离屏渲染）+ 原生 | 两层同锚点标注、下层先画 → 断言顶层标注像素覆盖底层（原生：label pass 序；回退：帧末序） | I-2、D-D |
| `test_layer_plan_top_insert_v12.py` | 纯 Python | 新层落点 == 归属组首（置顶） | D9 |
| `test_bridge_origin_v12.py` | 环境 | `find_spec('qgis_render_bridge').origin` 位于 `native/qgis_render_bridge/` | 00 §5 坑 2 |

## 3. 门禁（CI 配置要求）

| 腿 | 内容 | 理由 |
|---|---|---|
| Linux（既有） | 全量 + `-m qgis` | 现状 |
| **Windows（新增）** | `-m qgis` 全部 + 本集 §2 的真桥用例 | D12：D-A 只在 MSVC 复现；无 Windows 腿则该类缺陷必然重演 |
| 双平台 | 上述用例**行为一致**（同一断言、同一期望） | I-7 |

Windows 腿的最小命令：

```
set PALEO_REQUIRE_QGIS=1
python -m pytest -m qgis tests/ -q
```

## 4. 手工验收脚本（发布前人工过一遍）

1. 新建相带草稿 → 点「开始编辑」→ 点「节点编辑」→ 拖一个顶点：**顶点跟着走、松手后几何保留、状态条出现"已移动节点"**。
2. 撤销一次：顶点回到原处（单宏）。
3. 两个相邻面的共享节点：拖动后两面同步变形、无缝隙。
4. 开「捕捉」，把顶点拖到另一层顶点附近：出现捕捉指示器且落点吸附。
5. 开「拓扑编辑」：拖动共享节点后保存编辑 → 无拓扑错误（或错误被明确拦下并提示）。
6. 图层顺序：面板把某层拖到最上 → 画布该层压在最上；洋葱皮时间轴抬高某期次 → 该期次在最上，收起后复原。
7. 标注：两层都有标注且重叠 → 面板上层的标注可见（压住下层）。

## 5. 回归风险清单（改动时重点看）

| 改动 | 可能打破 |
|---|---|
| 幂等重推当前层（R1/R2） | `tests/test_v10_active_layer_chain.py`（假画布按调用次数断言）、`tests/test_edit_targets_v11.py`（假画布 `set_current_layer` 恒成功） |
| 桥侧会话兜底（R3） | `test_qgis_topo_m1/m2`（多会话层时的选择期望） |
| 删 `_push_mirror_order`（R8） | `tests/test_qgis_layer_panel.py:74-92`（断言 `panel._layers` 顺序） |
| 新层置顶（D9） | `tests/test_layer_tree_plan_v11.py:120-138`、`tests/test_layer_tree_reconcile_v11.py` |
| 回退面板行序（D10/R11） | `tests/test_composite_gis.py:750-769`（reorder 持久化） |
| 回退标注帧末化（R12） | `tests/test_map_render_*` 离屏渲染基线（像素期望） |
| TEMP-DIAG 收口（D11） | 现场调试流程（需 `PALEO_EDIT_DIAG=1` 才能复现诊断） |
