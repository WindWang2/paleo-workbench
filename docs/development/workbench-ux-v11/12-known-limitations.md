# 12 — Known Limitations (V11)

## 归属其它 open PR / 并行 goal（本 goal 不修）

1. **#1267**（v10-review-fixes）独占：`action_registry` `native_only`/`write_tools` 词表漂移（#1255，钉测试在本分支红——预存在）、5 个几何工具 SVG 资产缺失（#1256：工具条空白图标按钮）、#1257–#1264 各项。
2. **#1277**（review-convergence，本分支基座）：virtual attribute table / theme lambda / snapping / Data Manager 分页身份查询——已含于基座，不重复实现。
3. **Data Fabric goal**：catalog schema、DataVersion 语义、`get_scheduler()` 进程级生命周期（跨工程计数残留的调度器侧重置）。
4. **QGIS goal**：QGIS 树权威、原生编辑行为、拓扑引擎、#1278 相图编辑迁移；`composite_document/composite_editing` 本 goal 仅动呈现（探针接线 12 行、描边 token 5 行）。

## 本 goal 范围内的已知限制（诚实记录）

| # | 限制 | 原因 | 影响 |
|---|---|---|---|
| L1 | `CommandRegistry` 仍持有第二份阶段白名单**决策**（措辞已同源） | 合并需重构 palette 适用性协议（applicability 契约 v2） | 词表漂移风险已消，决策漂移风险残留（钉测试防护） |
| L2 | 遗留 mapping 页 `edit_gate_open=True` 强开门 | 文档化遗留表面（无阶段上下文）；关闭会改变该页行为 | 同一文档在遗留页与工作站可用性不同 |
| L3 | OperationRegistry 首批仅登记完整性校验；导入/导出/重算/制备仍走各页状态条 | 逐任务迁移需逐个接线取消/进度语义，本轮聚焦机制+样板 | 任务中心可见性渐进改善 |
| L4 | `active_survey_id`/`active_task_id` 总线槽位 API 就绪但地震/预测面板未发布 | 面板重构超本轮范围；UIContext 投影已就绪 | 槽位暂为 None（诚实未知） |
| L5 | `geological_modeling_3d_page` 模型树/QC 列表未模型化（audit ⑫） | 页面体量大、与井列表耦合；风险中（井数级） | 万井工程 3D 页树构建仍偏重 |
| L6 | rail 模式按钮仍只过滤 explorer（不导航） | 设计意图保留（tooltip 已澄清）；双语义会制造「一个功能两个状态」 | IA 期望落差由文案缓解 |
| L7 | 可视化 hub 占用永久键位 `5`（自述临时面） | 功能裁剪超出 UX goal 边界 | 键位预算占用 |
| L8 | whatsThis 层未引入 | palette 详情 + 状态语言已覆盖主要解释面；goal §18 禁大段教学弹窗 | 复杂数值算法的深层文档仍依赖 docs/ |
| L9 | offscreen 无真实高 DPI 屏；视觉 QA 以 DPR 感知路径 + a11y 门禁近似覆盖 | 环境 | 真机高 DPI 建议人工抽检 |
| L10 | inspector 资源身份行 4 处实现未完全合并（措辞/缺省已统一） | 各表面职责不同（主检查器 vs 轻量行） | 维护面重复但行为一致 |
| L11 | 原生栈树菜单门禁经 `contextMenuAboutToShow` 后处理（C++ 菜单构建在桥内） | 桥菜单 API 边界（QGIS goal 域） | 项创建时短暂未门禁（打开前已纠正） |
| L12 | 井身份索引按 bind_project 全量重建；运行期新增井不进索引 | 工程模型无井级变更信号（Data Fabric 域） | 运行期新井的 id 发布回落原值（不吞选择） |
| L13 | `test_dense_diamond_lattice_dag_1000_nodes` 等目录压力测试在 Windows 本机偶发（临时目录 unlink 权限）——与本 goal 无关的既有环境脆弱性 | Windows 文件锁 | CI Linux 腿不受影响 |

## 测试注册表变更说明

`tests/test_ui_token_hygiene.py` / `test_ui_sizing_ratchet_v9.py`：预算/快照按既定快照策略更新（清零项=已完成迁移面）；`test_data_manager_tags_ui.py`（防抖等待）、`test_prediction/seismic_task_panel.py`、`test_factor_task_panel.py`（任务词表）、`test_version_workbench_dialog_ui.py`（选择保持语义）、`test_attribute_table_differential.py`（有界选择器）断言对齐 V11 行为，均在注释中标明。
