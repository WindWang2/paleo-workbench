# 00 — Overlap audit（Phase 0）

执行时间：2026-09-09。基线 `origin/main = d5181cb3`。
方法：`git fetch --all --prune` + `gh pr list/issue list` + 逐 PR body/changed-files 阅读 + 两轮独立
source audit（M1/M5 fields & tree 链路；M4 duplicate-GIS 全仓扫描）+ 主 agent 对 M2/M3/M6/M7/M8/M9/M10
的关键文件复核。所有 file:line 引用均相对本 worktree（d5181cb3）。

## A. 运行时状态

- **Open PR：0**；draft 0。与 prompt 编写时一致，无 prompt 之后的新 PR 需要去重。
- **Open issues：2**
  - #1230 [P2] CI 门禁覆盖 + **#951 stale-QTimer/destroyed-QObject 产品侧风险**（Run 2 已定位
    `QTimerInfoList::activateTimers → notifyInternal2`）。M9 相关；CI workflow 修改本 goal 明确不做。
  - #1224 [P2] worker 假取消 —— runtime 侧，非本方向 ownership。
- **并行 worktree**：`../paleo-workbench-v8`（分支 `feat/qgis-context-control-plane-v8`，= d5181cb3，无新提交，
  方向 A 工作区）。文件冲突面：`ui/workstation/**` —— 本方向只做窄 seam，先查该分支。

## B. 已交付基线（禁止重做）

| 来源 | 已交付 | 证据 |
|---|---|---|
| PR #1236 (9e81d6d4) | capability manifest/snapshot、ToolContext、30 工具 evaluator、native identify/select/measure、reshape、endpoint/intersection snap、QGIS-first validate、EditDelta、Windows vendor QGIS 首建 + bridge bootstrap | `mapping/capability_model.py`、`tool_context.py`、`tool_availability.py`、`edit_delta.py`、`native/**/edit_tools.*` |
| PR #1237 (ff721e03) | GeologicalLayerSpec V2(27 roles)、geometry_operations facade、标量栅格镜像+renderer codec、LayerPresentationState、增量发布 ledger/feature-delta、地质符号 V2、因子组产品、约束回同步+指纹、制图 QA、QgsPrintLayout 原生映射+hybrid 边界、fusion 生产入口 | `mapping_workspace/geological_layer_spec.py`、`mapping/geometry_operations.py`、`scalar_*.py`、`qgis_mirror.py`、`geological_symbols.py`、`cartographic_qa.py` |
| main 后续 | `10647f0` submodule 指针复位；`c5a1d322` toolbar/inspector/evaluator sync 修复；`7fcf0bb1` tool_surface 回归+authoring kernel gates；`d5181cb3` polygonization MultiPolygon 面积、seismic grid 重置、测试修复 | git log |

本地 `main` 领先 1 个提交（`836db3df`，空 scratch log，无内容价值）；本 worktree 基于 origin/main。

## C. 审计结论 → 本 Goal 逐项裁定

| Goal 条目 | 审计发现 | 裁定 |
|---|---|---|
| **M1** provider schema | fields_json 在 C++ 端**只写不读**：`map_stack_service.cpp:1673-1676/1722-1725` 仅 `setCustomProperty("pwb/fields_json")`；全 `native/` 零 `QgsFieldConstraints`/`QgsEditorWidgetSetup`/`setAlias`/`addAttributes`。更严重：memory provider 图层**零属性**——`QgsJsonUtils::stringToFeatureList` 以空 QgsFields 解析（:1599/:1626/:1691），GeoJSON properties 在 `qgsogrutils.cpp:788-792` 即被丢弃，QGIS 侧按字段分类渲染无数据可绑。V7 文档 08 §4 已声明此为后续桥工作。 | **NEW（本 goal 最大真实增量，P0）** |
| **M2** 编辑面 | host MapTool 面（pan/zoom/measure/select/rect/add×3/move/vertex/reshape）+ native 工具 + 21 桥几何算子（union/split/difference/buffer/simplify/smooth/densify/reshape/multipart/clip…）已可用且经 30 工具 evaluator 门控；fallback 冻结 | **EXTEND→决策文档**：不加全按钮；逐能力给出做/不做理由（07 决策记录） |
| **M3** snap/topology | host SnappingService 权威 + push QGIS config（V7 已做）；已知限制：`propagate_shared_vertex` 在**其它图层各自 edit_session** 上开命令（`topology.py:153-187`），undo_stack 每层独立（`vector_layer.py:329`）→ origin 层 undo 不撤销传播，非原子 | **NEW（P0）**：host 级 compound transaction（一次地质动作→一次 undo），不可行处显式上报 |
| **M4** 第二套 GIS | 15 处 DUPLICATE-CANDIDATE：4 个幸存 PIP（composite_editing:375、map_interaction:95、project/domain:171、geomodel/builders:576）、8 个 bbox 构建器、2 个平行网格索引、facade host ops 零生产调用者、facade 缺 centroid/bbox-relate | **NEW（P1）**：迁移 F1/F2/F5/F6/F4/F3/F10/F11/F13 + 补 facade 缺口；F7（双索引合并）**延后**（风险>收益，理由见 07） |
| **M5** 树指示器 | native 仅 ✏ 一种（`setEditIndicator` :3505）；host 侧 LayerPresentationState 16 态词汇齐全但只喂 group summary label；fallback 面板有 per-row 装饰（两面板不对齐） | **NEW（P1）**：通用 `set_row_indicators` bridge API + 面板接线 |
| **M6** 增量性能 | 已有 ledger/feature-delta + perf 门（1000 层 no-op 30ms vs 180ms 预算，`tests/perf/test_mirror_publish_scale.py`） | **不人为改码**：跑既有门 + profiling 确认；结果记 06 |
| **M7** 符号/渲染 | 符号 V2 版本化绑定 + role-check + renderer hint 已交付（`geological_symbols.py`）；style/value 分离已立 | **DROP-AS-DUPLICATE**（验证测试存在即可） |
| **M8** layout | legend 无 filter key（V7 文档 08 §1 显式 follow-up：`map_stack_service.cpp:3765-3775` 仅 title/linked/resize/background）；hybrid 边界已文档化 | **EXTEND（P1）**：仅 legend `filter_layers` 窄扩展；其余边界保持 |
| **M9** 生命周期 | 真实风险点：`ui/qgis_stack/events.py:15-23` `QTimer.singleShot(0, lambda: self.<signal>.emit(...))` 无 context 守卫——QObject 销毁后 lambda 悬空（#951 同类根因）；已有 lifecycle 测试（test_qgis_mapstack_lifecycle 等）但无 30×/100× 压测矩阵 | **NEW（P1）**：守卫修复 + 压测矩阵；不做 CI workflow |
| **M10** 能力契约 | manifest/hash/degraded 已有完整测试（test_authoring_contracts 63 项 + test_qgis_v7_authoring） | **DROP-AS-DUPLICATE** |

### 硬排除（沿 goal 约束）

- 100GB seismic：任何形式的新增支持/基准/优化 = 禁止。
- 新 GeologicalLayerSpec V3 / 新 PIP/clip/spatial-index 通用实现 / Python reshape·selection·snapping 复刻 /
  RGBA-only 第二渲染器 / 第二 layer tree authority：禁止（均已存在且审计未发现需要替换的理由）。
- CI workflow 修改：禁止（#1230 的 CI 部分留待 CI 专项）。

## D. Changed-file ownership 与冲突面

| 区域 | 本 goal | 冲突风险（vs 方向 A `ui/workstation/**`） |
|---|---|---|
| `native/qgis_render_bridge/src/map_stack_service.*` + `bindings.cpp` | W1/W4/W5 | 无（方向 A 不碰 C++） |
| `paleo_workbench/mapping/topology.py`、`vector_layer.py`（compound 命令） | W2 | 低；`vector_layer.py` 方向 A 只读 |
| `ui/workstation/composite_editing.py`（identify 迁移 + 传播接线） | W2/W3 | **中**：先查 `feat/qgis-context-control-plane-v8`（当前无提交，安全窗口内尽早合） |
| `ui/qgis_stack/layer_tree_panel.py`、`events.py` | W4/W6 | 低（方向 A 只消费 seam） |
| `mapping/geometry_operations.py`、`geometry_planar.py` + 各迁移点 | W3 | 低 |
| `project/domain.py`、`catalog/domain_binding.py`、`viz/geomodel/builders.py` | W3 | 低（方向 C 不在编辑窗口） |

## E. 执行顺序（编译预算约束）

W1+W4+W5 同文件（map_stack_service.cpp）→ **一次 C++ 批次、一次桥编译**（复用
`PALEO_QGIS_BUILD_DIR=.worktrees/qgis-native-authoring-v7/.../build/qgis-vendor` + `PALEO_QGIS_REUSE_VENDOR=1`，
仅链桥扩展 ~10min，不重建 vendored QGIS）。W2/W3/W6 纯 host 可并行推进后并入。
