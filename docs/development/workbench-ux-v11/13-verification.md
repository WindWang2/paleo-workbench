# 13 — Verification (V11)

## 测试矩阵（本地，offscreen；无 CI 等待，goal §2）

| 族 | 文件 | 结果 |
|---|---|---|
| 新 V11 套件 | test_v11_action_surface（22）、test_v11_modelview_data（12）、test_v11_modelview_map（13）、test_v11_performance_structural（8）、test_v11_a11y（15+）、test_v11_visual_qa（15） | **85 全绿** |
| 行为更新测试 | test_data_manager_governance_ui（血缘异步等待）、test_factor/prediction/seismic_task_panel（任务词表）、test_version_workbench_dialog_ui（选择保持）、test_attribute_table_differential（有界选择器）、test_data_manager_tags_ui（防抖）、test_visual_qa_v6（措辞对齐）、test_workstation_context（selected 语义） | 全绿 |
| 视觉 QA 谱系 | v6/v7/v8/v9/v10 + v11 | 全绿 |
| Token 卫生/尺寸棘轮/a11y DPI | test_ui_token_hygiene / test_ui_sizing_ratchet_v9 / test_a11y_dpi_v6 | 全绿（预算按迁移面收缩） |
| 诚实断言门禁 | tests/e2e/test_integrity_guard.py | 3 全绿（新文件合规） |
| 全量 fast 腿 | `pytest tests/ -m "not slow and not welllog_binding and not qgis and not opengl" --ignore=tests/e2e` | 7490 通过；120 失败清单与干净基座 `6576e364` 同命令输出**对称相等**（逐 test-id 差集 = ∅；另加测试顺序 flake 4 项，单跑全过） |

基座对称相等的失败族（预存在，非本 goal）：Windows 临时目录 unlink 权限族（project_package/delivery/dependency_audit 等）、缺失 SVG/桥扩展族（facies_patterns 3、stage toolbar overflow、unified_map*/tiled_onnx/native_factor_map/map_canvas_panel/referencopacity/well_identity_adapter）、schema 约束族（test_v10_schema_constraints ×5）、#1267 词表钉（test_action_registry_flags_match_evaluator_tables 1 项——归 #1267 本分支失败预期）、mapping_page unified_scene 族（×5+1 error，并行 unified-canvas worktree 的改动浸入本环境复现于基座）。

## 评审循环（goal §25）

1. architecture review（总线/AsyncQuery/Registry/reconcile/sort）→ 修 sort 持久索引重映射 + 混合类型键 + 进度刷新合并 + cancel 终态重检查 + registry shell 归属 + publish_asset 去重 + reconcile 键去重。
2. UX consistency review（词表/禁用呈现/inspector/选择器/任务合并/rail）→ 修血缘错误迟到守卫 + version/run 读取口径（包装与扁平双契约）+ warning→degraded 统一 + 状态语言缺省 + 占位行中文化 + 空原因回退 + RAW 前缀。
3. lifecycle review（同 1 轮；K2/残留/关闭）→ shell teardown registry.clear()、Job released 自清。
4. performance review（O(n) 扫描/风暴/内存）→ feature 搜索 200ms 防抖、阶段可用性签名门控、task 列表 O(n²)→O(n)。
5. visual QA（v6–v11 谱系 + 1280×720/1920×1080 亮/暗）。
6. accessibility review（tab 链/a11y 名/Escape 透传/F5-F1/数字守卫）。
7. independent code review（三评审 verdict：needs-fixes→全部 P1 已修，P2 已修/记录；无 P0）。

## DoD 自检（goal 定义）

| 项 | 状态 |
|---|---|
| 统一 UI context（含 selected/active/edit 三层词汇、井身份规范化、死信号替换） | ✓ |
| action availability 基本无平行逻辑（探针达原生树、阶段面板同因、措辞合一、解释接线） | ✓（registry 第二决策除外，见 12-L1） |
| 大数据页面不再依赖 item-per-cell 架构（15 表面迁移 + 结构测试钉住） | ✓ |
| GUI thread scale contract（AsyncQuery + 血缘异步 + 进度接线 + 轨迹缓存） | ✓ |
| Inspector 统一（Version/Run/Well 富化） | ✓ |
| task/progress/error 模型统一（registry+任务中心合并+状态组件） | ✓（登记面逐步扩展，见 12-L3） |
| dark/light 一致（静态快照清零 + tint 路由 + ::item:focus + 密度） | ✓ |
| 主要工作流视觉与交互一致 | ✓（视觉 QA 谱系全绿） |
| 1280/1080p/高 DPI 可用（矩阵场景 + 密度 + focus） | ✓（真机高 DPI 记入 12-L9） |
| QObject 高风险点 review | ✓（三轮独立评审） |
| 无已知 P0/P1 | ✓（剩余 P2 见 12） |
| 本地相关测试通过 | ✓（对称基座 + 85 新断言全绿） |
| PR 已创建 | 见 PR 描述（本文件随 PR 提交） |

## 截图证据

脚本化场景（非人工肉眼）：`tests/test_v11_visual_qa.py` 13 场景 grab() 非空断言 + 结构检查；主题×分辨率矩阵在测试内渲染断言（1280×720 / 1920×1080 × 亮/暗）。基线落问题域：像素 diff 非门禁（D8 政策延续）。
