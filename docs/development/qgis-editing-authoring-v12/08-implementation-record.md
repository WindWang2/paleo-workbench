# 08 — 实施记录（Implementation Record）

状态：**M0 全部落地 ｜ M3 主干落地 ｜ M1 部分落地 ｜ PR #1303 已合并并评审 ｜ 渲染预设 + 右键换相已落地**。
本文件记录"实际改了什么、验证到什么程度、还差什么"；设计与决策仍以 00–07 为准。

---

## PR 合并（#1303 vector-perf-increment）

- 本地解决两处构建文件冲突（源清单两边都保留）后合并入 `main` 并推送（GitHub MERGED）；桥按合并后源码重编。
- **评审结论**：
  1. `tests/perf` 在合并+rebase 后 **67 passed / 2 failed**——`test_mirror_publish_scale[50]` 是该 PR 文档自认的本机预算级既有失败；`test_tool_sink_writes_ring` 单跑/连跑均通过（满载时 hover 节拍抖动的时序脆弱项）。
  2. `test_vector_perf_baseline::test_baseline_snap_press_pick` 的段错误**不是** R-Tree 的错：20k 档 `cell≈1.587` 使 (6.25,4.75) 距网格顶点仅 0.10 单位（< 10px 拾取半径）→ 命中顶点 → 触发**主干的 D-A use-after-move**（PR 作者在 04-known-limitations #8 记录过同一崩溃并绕行）。M0 修复 rebase 后该用例通过。
  3. 零拷贝总线是 opt-in（JSON 通道默认不变）、SPSC + 序号/CRC 双完整性、static_assert 钉布局——集成面安全。
  4. 增量拓扑的 gap 规则不做子集化（全局属性），其余规则增量且与全量等价有测试钉住。
  5. LOD 只进绘制管线、永不写回要素几何（拾取/拓扑仍在原始几何上）——与编辑链路无语义冲突。
- wip 分支（M0/M3/M1 + 工作区在制改动）已 rebase 到合并后 main（零文本冲突），逐点核验关键缝合（锚点修复/CRS 可比性/current-layer 钩子/标注帧末绘制）全部完好；rebuild 后编辑链路 23 passed、`-m qgis` 门禁 **912 passed**（3 个既有失败不变）。

## 任务2｜矢量类型渲染预设

- `STYLE_LIBRARY` 核心类型补**标注默认**：井位→井名、断层线→断层名称、相带→相名、成图范围→范围名称（含描边色，制图惯例配色）。模板引用库预设 → 新建图层即得"该有的样子"。
- 分类相样式按其分类字段带标注（相图 facies / 亚相图 sub_facies / 微相图 micro_facies）。
- 一键恢复：控制器 `apply_render_preset`（模板/库预设）+ 图层右键「应用渲染预设」（原生树面板与回退面板同信号契约）；相带层走分类样式重算。

## 任务3｜相带右键换相

- 画布右键策略切 `CustomContextMenu` → shim 换算地图坐标发 `canvas_context_menu((x,y), global_pos)`。
- 宿主：活动相带层 + 光标命中要素 → 相选择列表（词表一级相、当前相勾选、"级联选择（亚相/微相）…"入口）→ `apply_facies_selection` 单命令写入（自动经门禁开会话；RAW/原生会话占用等拒绝原因上浮状态条）→ 分类样式刷新。
- 测试：`tests/test_render_presets_and_facies_menu_v12.py` 7 项（预设标注、模板引用、一键恢复、相带分类重算、菜单列表、换相写入+样式刷新、未命中零写入）。

---

## M0｜编辑链路止血（全部完成）

| 项 | 落地内容 | 代码坐标 |
|---|---|---|
| M0-1 D-A 崩溃 | 顶点拖动锚点先取后用（MSVC 实参从右往左求值 → `shared.front()` 落在 `std::move` 之后 = 空容器解引用） | `native/qgis_render_bridge/src/edit_tools.cpp:1042-1047` |
| M0-2a 当前层读回 | 新增 `QgisMapStack::currentLayerId` + binding `current_layer_id` + manifest `current_layer_query`（0.12.0a0） | `map_stack_service.cpp`、`map_stack_service.hpp`、`bindings.cpp` |
| M0-2a 悬挂清理 | 层被移出工程时清空画布 current layer（挂在 `QgsProject::layerWillBeRemoved`，覆盖全部 erase 出口）；`~Impl` 显式断连 | `map_stack_service.cpp`（Impl 析构 + initialize） |
| M0-2b 幂等重推 | `repush_canvas_current_layer()`；`set_active_layer` 同 id 不再短路；`start_editing` 会话开启后重推；`join_native_layers` 复推；`_sync_composition_now` 发布后兜底 | `composite_editing.py`、`composite_document.py`、`canvas_shim.py` |
| M0-2c 失败上浮 | `vertex_moved` 纳入合成拒绝；`pick_miss` 在"工具已 armed 但无编辑目标"时给一次可读提示（按状态去重、目标就位复位） | `canvas_shim.py`（dispatch_edit_pick / _warn_vertex_without_target） |
| M0-2d 候选 CRS 过滤 | `discoverAllLayers` 不再丢弃未声明 CRS 的层（双方都未声明 = 按原坐标可比；单方声明 = 不可比）——这是工作站默认全层档下"拖不动"的直接原因 | `edit_tools.cpp:430-490`（`coordinatesComparable`） |
| M0-4 诊断收口 | 发布诊断（写盘 + `grab()` + 树 dump）移入 `_trace_publish`，仅 `PALEO_EDIT_DIAG=1` 执行；`snap_feedback` 接状态条（只进捕捉 chip 的 tooltip，避免与权威态互相闪烁） | `canvas_shim.py`、`map_status_bar.py`、`composite_document.py` |
| M0-5 产物来源断言 | QGIS 腿启动即校验 `find_spec('qgis_render_bridge').origin` 位于 `native/qgis_render_bridge/`（防"影子桥"） | `tests/conftest.py` |

**新增用例**

| 文件 | 覆盖 |
|---|---|
| `tests/test_qgis_edit_chain_v12.py`（真桥） | ① 发布后画布当前层 == 编辑目标；② 建草稿 → 开始编辑 → 节点编辑 → 拖动顶点 → **镜像几何改变** |
| `tests/test_vertex_receipt_v12.py`（纯 Python） | 无会话时 `vertex_moved/inserted/deleted` 三族都上浮拒绝；成功路径不污染；无目标提示按状态去重与复位 |

## M3｜栈序与标注序（主干完成）

| 项 | 落地内容 |
|---|---|
| 镜像序反转 | `_push_mirror_order` 改为 `reversed(self._layers)`（组装序自下而上 vs 桥 top-first） |
| 诚实 no-op | `move_layer` 返回 bool；分组模式（root 平铺序非权威）返回 False，洋葱皮据此在状态行说明"当前分组模式不支持跨组置顶"，不再制造"已置顶"假象 |
| 新层落点 | 用户组 / root 的新成员**置顶**并入；系统组 / factor 组保持角色带序尾部并入（带序是不变量） |
| 标注序 | 回退渲染器不再内联画标注：一律收集为 `_LabelSpec`，在**全部几何之后**按图层序统一绘制（顶层标注压在最上），导出路径同为该语义 |
| 用例 | `tests/test_layer_stack_order_v12.py`（面板序==树序==组装序反转、分组模式返回 False、系统组/用户组落点）+ `tests/test_label_order_v12.py`（重叠标注顶层胜出、标注不被上层实心面覆盖） |

**未做（记录在案）**：M3-3 回退面板行序语义对齐（无桥环境的认知陷阱）；洋葱皮"临时置顶"的**会话覆盖**实现（需在 `layer_tree_plan` 引入不落盘的覆盖字段 + 过滤树回声写回，见 04 D8/D10 边界）。

## M1｜工具面（部分完成）

已接线（登记 → 门禁 → 帮助 → 图标 → 工具条/地图右键 → 宿主闭环）：

| 新开关 | 语义 | 门禁 |
|---|---|---|
| `avoid_intersections` 避免重叠 | QGIS avoid overlap（默认开） | 工程 + 活动图层 + 捕捉引擎可用 |
| `tracing` 追踪 | 采点沿既有边（QgsMapCanvasTracer） | 工程 + 图层 + **原生画布** + 捕捉引擎 |
| `vertex_scope` 顶点范围 | 全部层（勾选）/ 当前层 | 工程 + 图层 + **编辑会话** + 原生画布 |

改动面：`tool_availability.py`（工具组 + 三条规则 + checked 映射）、`tool_context.py`（3 个呈现事实字段）、`composite_editing.py`（宿主采集）、`tool_help.py`（标签/帮助）、`action_registry.py`（呈现面）、`map_action_controller.py`（命令 + 可勾选）、三张新图标资产。
用例：`tests/test_snapping_toggles_v12.py`（登记面、图标解析、checked 随事实、门禁给原因、宿主命令闭环）。

**未做**：捕捉模式选择器（所有图层/当前图层/高级配置）与容差单位选择仍是对话框/模型层能力，无工具条控件；`fault_cut` / `boundaryReshape` 工具面（M4-2）；段移动（M2-1）；数字化工具条第一批补全（M5-A）。

## 验证记录（Windows / MSVC / 真桥，冻结源码）

| 范围 | 结果 |
|---|---|
| `-m qgis` 全量 | **893 passed**，3 failed（`test_map_render_backend` 标量格网、`test_qgis_canvas_embed` 背景色、`test_qgis_mapstack_layers` 等待超时）——三者在改动 stash 后同样失败，**均为既有失败**；改动前为 888 passed |
| 编辑链路新用例 | `test_qgis_edit_chain_v12.py` 2 passed（含真实拖动改几何） |
| 栈序/标注序新用例 | `test_layer_stack_order_v12.py` 4 passed、`test_label_order_v12.py` 2 passed |
| 开关新用例 | `test_snapping_toggles_v12.py` 5 passed |
| 受影响的既有套件 | 契约/动作/帮助 144 passed；`tests/ui` + 我改动的模块混合 160 passed（1 既有失败：参考图层导入顺序断言，stash 后同样失败） |
| 泄漏/顺序检查 | 新增三个宿主级用例文件 **先跑**、随后整套 `tests/ui`（含 `test_no_parentless_new_widgets_after_teardown` 泄漏守卫）：**108 passed** —— 编辑会话/开关/栈序改动不残留控件或连接 |
| 全量回退套件 | 首次整进程全量跑的 97 项 `tests/ui` 失败**不可复现**：该运行与我并发改源码重叠（`tests/ui` 单独 97 passed，混合跑亦全绿），且日志被截断无法定位。判定为并发编辑伪影，非代码缺陷。第二次冻结源码的全量跑因机器被其他工作区任务占满（另一个 worktree 的 pytest 同时运行）进度不可接受，已中止；**此项为残余验证缺口**，建议在空闲机器上补一次 |

**踩到并修掉的测试基建坑**：像素级渲染用例必须请求 `qapp` fixture——缺 QGuiApplication 时字体引擎会**硬崩**（进程退出、pytest 无输出），而不是报错。`tests/test_label_order_v12.py` 的注释里钉了这条。
