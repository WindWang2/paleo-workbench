# 00 — Baseline（V14-COMPILATION-PUBLISH）

- 执行日期：2026-09-21
- Base SHA：`412d8baf22a6a928c860e2e3d6c1108a9c035c78`（执行时 `origin/main`，与 Prompt 快照一致）
- Worktree：`/home/kevin/project/paleo-workbench-v14-compilation-publish`
- Branch：`feat/v14-integrated-compilation-publish`
- Lease：`.git/paleo-v14-parallel/leases/v14-compilation-publish.json`

## 执行时仓库事实（重新侦察结论）

- main = `412d8baf`（#1433 mapping-authoring 的 merge）。`git status` 干净（仅未跟踪 `.zcodeignore`）。
- Open PR（4 个）：
  - **#1434** `fix/open-issues-batch`（#1339–1345/#1357/#1358/#1385/#1388/#1392/#1427–1431）——workflow_graph 语义、curve_expr、polygonization、QGIS mirror/export 性能、表格性能、卫生、CI 环境。其范围全部为本线 forbidden overlap。
  - **#1435** `devin/1789909230-cpp-final-closure`——迁移台账/构建门禁/根 CMake。共享文件仅 additive。
  - **#1436** `feat/cpp-residual-conversion`——**含 `libs/closure_workflow/map_compile.*`（compile_map draft+production 编图管线移植）**、`workflow_runtime/run_orchestration`、`ui_canvas/qt/fallback_map_backend`、`interchange/exporters`、`job_runtime` 治理。map_compile 与本线"综合编图 production wiring"相邻——本线**不重复实现**该管线，聚焦其四周的产品接线（输入集/融合/产品阶梯/版式/导出/发布）；若其先合并则直接消费。
  - **#1437** `feat/v14-qgis-layer-control-plane`（V14-QGIS-CONTROL，Prompt3 线）——`libs/workspace` 层树控制平面 + canonical top-first order。本线消费 main 已有的 `MapSession::layerIdsTopFirst()`（`libs/qgis/include/pwb/qgis/map_session.hpp:58`）；#1437 的扩展为可选增强。
- Open issues 17 个，全部属于 #1434 批（本线不处理）。
- 既有租约：`v14-qgis-control.json`（phase=pr，拥有 `libs/workspace/**`、`libs/mapping_document/**` 的树/持久化语义、`libs/ui_widgets/**/qgis/**`、`native/qgis_render_bridge/**`）、`v14-constraint-factor.json`（phase=audit，拥有 `libs/mapping_kernel/**`、`libs/factor_host/**` 等）。

## Stage3 现状能力矩阵（审计后，main=412d8baf）

| Capability | kernel | production wiring | UI | persistence | tests | gap |
|---|---|---|---|---|---|---|
| integrated compilation（融合） | ✅ `closure_workflow/integrated_compilation.cpp`（§12 全量：freeze gate/pin-current/QC defaults/注册） | ❌ grid seams 无生产实现；无 `decode_grid_artifact`；app 零引用 | ❌ | ✅ catalog seam | ✅ fusion_test | host 装载 + catalog 适配 + UI |
| input freeze（输入集） | ✅ `workflow_interpretation/compilation.*`（create/validate/freeze/persist/evidence_view） | ❌ 无 C++ 动作面 | ❌（freeze_evidence_set 仅 Python） | ✅ document 段 | 部分 | 动作接线 |
| map document（地图文档） | ✅ `mapping_document`（CONV-02+#1412 edit session） | ✅ bank+install | ✅ mapedit | ✅ paleomap_documents | ✅ | — |
| composition document | ✅ `composition.hpp`+`composition_session.hpp`（models+components ≈95%） | ✅ 面板 | ✅ 面板（编辑面全活） | ✅ document_io 原子写 | ✅ oracle | bind_map_documents 活对象路径缺（host seam） |
| template library | ❌（composer `templates.py` 9 模板未移植；cartography/templates 是 geological_pipeline 另一套） | ❌ combo 空 | ⚠️ 空白 A4 起步（`closure_mapping_install.cpp:578`） | ❌ | ❌ 无 oracle | 全缺 |
| composition preview | ❌（`renderer.py` 1341 行未移植） | ❌ `render_svg` seam 未注入 → "预览渲染失败" | 面板就绪 | n/a | ❌ | 全缺 |
| legend | 部分（layout 侧 QGIS legend + filter；canvas chrome legend） | 部分 | 部分 | n/a | 部分 | composer 预览图例 + 顺序契约 |
| layout export | ✅ `layout_export` 内核（spec/预算/报告）+ `layout_spec_exec`（PDF/SVG/PNG，QGIS） | ✅ 平台对话框（硬编码 A4 构图，不走面板文档） | ⚠️ 与面板不互通 | n/a | ✅ oracle+平台 | 面板 export_fn；composer 引擎 |
| QA | 部分（review_qc_core 16 规则+cartographic 3 条+seam） | 部分 | ✅ review 页 | ✅ | ✅ | cartographic QA 12 规则；product_qa 无 UI |
| finalization | ✅ map_product 阶梯（draft→reviewed→frozen→published→superseded）+ versioning 门 | ❌ 零消费者 | ❌（`map_product_requested` 信号悬空） | ✅ map_products 段 | ✅ 库级 | 动作+UI+发布 export |
| artifact provenance | ⚠️ `provenance_registered=false` 硬编码（`review_qc_core.cpp:1245`）；versioning/finalize sink 无生产实现；ExportArtifact 无 hash/catalog 版本 | ❌ | 部分 | 部分 | 部分 | P0 收口 |

## #1433 披露缺口执行时复核（Prompt 要求）

1. "composition preview SVG renderer 未接线"——**仍成立**：`composition_panel.hpp:93-95` seam 存在、`closure_mapping_install.cpp:549-554` 注释明确未接。
2. "export executor 未接线"——**仍成立**：同上（`export_fn` seam 未注入 → "导出引擎不可用"）。
3. "template library 尚未迁移，当前以空白 A4 起步"——**仍成立**：`closure_mapping_install.cpp:576-583` 原文注释 + 空白 A4 `set_document(factory.create_document("未命名组图"))`。
4. "factor grid 上游 gap 归科学线"——归 V14-CONSTRAINT-FACTOR（Prompt4），本线只消费 frozen products。

## 冻结 Python 参考（本线移植源）

- `paleo_workbench/mapping/composer/models.py`（245 行，已移植）
- `paleo_workbench/mapping/composer/components.py`（438 行，已移植 ≈95%）
- `paleo_workbench/mapping/composer/registry.py`（424 行，数据层 D-10 未移植——宿主 install 内嵌 24 spec；本线补 CHART_COLOR_SEQUENCE/PALETTE_ALIASES 等 renderer 所需数据面）
- `paleo_workbench/mapping/composer/renderer.py`（1341 行，**未移植——本线 XL 件**）
- `paleo_workbench/mapping/composer/templates.py`（373 行，9 模板，**未移植**）
- `paleo_workbench/mapping/composer/export.py`（148 行，仅 page_pixels 已移植）
- `paleo_workbench/mapping/renderers.py`（802 行，renderer 的层渲染前置；本线移植 dict-layer 路径所需子集）
- `paleo_workbench/mapping/map_styles.py`（387 行，VectorStyle——cartography 已有权威 from_dict）
- `paleo_workbench/mapping/cartographic_qa.py`（15 规则，**cartographic QA 移植源**）
- `paleo_workbench/workflow/map_product.py` / `integrated_compilation.py` / `interpretation/compilation.py`（内核已在 main，接线参考）
