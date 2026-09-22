# 02 — Python→C++ 迁移真值矩阵(重跑核实)

生成:`python3 tools/migration/pwb_final_closure_matrix.py`(main @ 7bfe7585)。

## 总量(678 模块)

| 分类 | 数量 | 说明 |
|---|---|---|
| NATIVE_PRODUCT | 133 | 原生产品接线(#1435 时为 115;V14 系列又接入 18) |
| LEGACY_REFERENCE | 395 | 冻结参考/oracle/开发工具,非产品运行时 |
| PARTIAL_NATIVE | 77 | 部分迁移 |
| NATIVE_LIBRARY_NOT_WIRED | 73 | 库存在、按矩阵口径未标产品接线 |

## 矩阵口径与实测差异(重要)

矩阵的 `product_wired` 来自 inventory 的显式 wiring 证据(直接产品接线),**不含传递消费**。实测抽样:

| 矩阵行(声称 NOT_WIRED) | 实测 | 结论 |
|---|---|---|
| workflow/factor_fusion.py → Pwb::FactorFusion | science_service/src/registry.cpp:846-1301 注册 "Factor evidence fusion" 适配器,经 science_kernels 能力(产品 linked)可达;closure_workflow/grid_seams.cpp、workflow_interpretation/factor_product.cpp 亦消费 | **矩阵保守失真(E 类:实际已接线)**;同时 `--capabilities` 面板的 factor_fusion_kernel "kernel present, not wired into the product" 标签同样失真(P3 诊断准确性) |
| workflow/dependency_graph.py → Pwb::WorkflowGraph | closure_workflow / workflow_interpretation / workflow_runtime 链接并消费(全部在产品闭包内) | 矩阵保守失真(传递接线) |
| workflow/dag/* → Pwb::WorkflowEngine | capability workflow_engine = linked runtime-ok | 同上 |
| mapping/qgis_mirror.py → Pwb::UiWidgetsQgis | mirror_snapshot 被 canvas_shim(产品)使用 | 同上 |

→ 矩阵对"是否死码"采用 fail-closed 口径(宁可低估),用于防"声称迁移完成"是合理工程决策;但**阅读矩阵时必须区分「未接线」与「未直接接线」**。本审计对产品关键行已逐一实测(见 04)。

## LEGACY_REFERENCE 保留正确性(§9 核实)

- 保留角色:oracle 生成器(tools/oracle)、语义冻结参考、迁移参考、开发工具、测试 fixture 生成器、兼容 facade(mapping_bind/cartography_bind,pybind,off-by-default,不链接进产品)。
- `scripts/cpp-migration/audit-python-runtime-deps.sh`(源码面):**PASS** — 产品链接闭包内无 Python C API / PySide / shiboken / python 子进程;pybind11 限于兼容 seam。
- `final-closure-gate.sh static`:**PASS**(矩阵测试 4/4:每模块恰一分类、安装排除 Python 源、根 feature 声明先于解析)。
- Python 入口 `run_app.py`/`app.py` 仍可运行(LEGACY 世界),与原生产品互不依赖。

## PARTIAL_NATIVE 重点行(产品相关)

- `catalog/lifecycle.py`(写路径 15 个 register_*,依赖 service.py 深层)— #1436 声明为独立子史诗未收口;本轮评审确认仍是最大未闭环迁移项(约束登记 commit_constraint_group 无产品调用方,与 F-1 相关)。
- `ui/workstation/*` 家族 — C++ 对应面存在(ui_workstation/ui_composite),编辑核心(CompositeEditController)存在且嵌入 CompositeDocument,但**产品未加入 QGIS 栈**(install_canvas 默认 uses_native_stack=false),阶段面板/图层管理面板的创作类信号无消费者(详见 04 F-1/F-2)。
- `mapping_workspace/controller.py` 等 — #1437 已接 layer control plane(产品可达)。

## 结论

迁移真实状态:**133 模块原生产品直接接线 + 一批传递接线(矩阵保守未计)**;产品运行时无 Python 依赖(源码面验证);遗留 Python 保留为参考/oracle 角色,合规。核心缺口不在"翻译覆盖率"而在**创作侧接线断层**(F-1/F-2)与 catalog 写路径子史诗(已知声明)。
