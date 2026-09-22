# Ribbon command catalog (native product)

**Baseline**: `470d7500` (`470d7500d9a2…`).
**Sources (code is authority)**:
- Spec table: `libs/ui_ribbon/src/ribbon_spec.cpp` (`build_workspace_specs`, 58 `cmd(...)` rows)
- Install / wiring: `apps/paleo_workbench_platform/ribbon_command_install.cpp` (M4 `register_real` / `register_disabled`, last registration wins)
- Chrome library: `libs/ui_ribbon` (Qt-free core + Qt ribbon bar)
- Design authority: `docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/`

## Rules frozen by the table

1. **Five workspaces, fixed order** — never reorder; tab indices are load-bearing.
2. **Exactly one Primary per workspace** — `data.import` / `predict.run` / `factor.compute` / `map.export` / `verify.run`.
3. **Middle three ARE stage views** — entering 数据管理 / 验证 must not rewrite `ProjectSession::mapping_stage`.
4. **One CommandRegistry** — ribbon / palette / menus / shortcuts share ids; no parallel QAction sets (D4).
5. **Honest disable** — missing backends register disabled with a Chinese reason, never a fake enable.

## Summary

| Metric | Value |
| --- | --- |
| Commands in spec | **58** |
| Wired (`register_real`, effective) | **36** |
| Disabled placeholders (effective) | **22** |
| Spec ↔ install id coverage | **58 / 58** |

> Some ids are briefly registered real and then re-registered disabled in the same install TU (last wins). The **effective** column below reflects final process state after `ribbon_commands::install`.

## 数据管理 (`DataManagement`)

- Workspace id string: see `workspace_id(DataManagement)` in spec
- Primary: `data.import`
- Mapping stage: _none (must not rewrite mapping stage)_
- Commands: 10 (real 6, disabled 4)

| Group | Id | Label | Kind | Overflow | Effective install | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 数据导入 | `data.import` | 导入数据 | Primary |  | **real** | 导入文件并创建项目受管的不可变 RAW 副本 |
| 数据导入 | `data.scan` | 扫描目录 | Secondary |  | **real** | 扫描目录并登记可导入资产 |
| 数据导入 | `data.plan` | 导入计划 | Secondary | yes | **real** | 扫描/分类/查重 → 逐项确认 → 分块执行 |
| 整理 | `data.link_well` | 关联到井 | Secondary |  | _disabled_ | 把数据版本关联到井对象 |
| 整理 | `data.set_role` | 设置角色 | Secondary | yes | _disabled_ | 设置资产角色 |
| 质量检查 | `data.check` | 检查数据 | Secondary |  | **real** | 工程级数据概览（格式/状态/完整性分布） |
| 质量检查 | `data.units` | 单位与坐标 | Secondary | yes | **real** | 元数据覆盖度（目录暴露级） |
| 版本与关联 | `data.history` | 版本历史 | Secondary |  | _disabled_ | 资产的版本来历链 |
| 版本与关联 | `data.lineage` | 来源关系 | Secondary | yes | _disabled_ | 版本的下游影响链 |
| 输出 | `data.export_table` | 导出表格 | Secondary |  | **real** | 导出当前资产表 CSV |

## 1 智能预测 (`IntelligentPrediction`)

- Workspace id string: see `workspace_id(IntelligentPrediction)` in spec
- Primary: `predict.run`
- Mapping stage: `FaciesCalibration`
- Commands: 11 (real 6, disabled 5)

| Group | Id | Label | Kind | Overflow | Effective install | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 输入与模型 | `predict.select_well` | 选择井数据 | Secondary |  | _disabled_ | 选择参与预测的井 |
| 输入与模型 | `predict.select_seismic` | 选择地震 | Secondary |  | _disabled_ | 打开体版本…（工程内 PWBVOL1） |
| 输入与模型 | `predict.model_params` | 模型参数 | Secondary | yes | _disabled_ | 预测模型参数 |
| 预测运行 | `predict.run` | 运行预测 | Primary |  | **real** | 对所选井运行真实 ONNX 相预测 |
| 预测运行 | `predict.cancel` | 取消 | Secondary | yes | **real** | 打开任务中心取消运行中的任务 |
| 预测运行 | `predict.params` | 参数 | Secondary | yes | _disabled_ | 预测运行参数 |
| 叠加对照 | `predict.overlay_seismic` | 地震叠加 | Secondary |  | **real** | 叠加地震相预测成果 |
| 叠加对照 | `predict.overlay_well` | 测井叠加 | Secondary | yes | **real** | 叠加测井相预测成果 |
| 叠加对照 | `predict.link` | 联动 | Toggle |  | _disabled_ | 井震联动开关 |
| 结果 | `predict.save` | 保存结果 | Secondary |  | **real** | 保存当前阶段成果 |
| 结果 | `predict.submit` | 送交验证 | Secondary |  | **real** | 切换到验证工作区 |

## 2 约束与单因素 (`ConstraintFactor`)

- Workspace id string: see `workspace_id(ConstraintFactor)` in spec
- Primary: `factor.compute`
- Mapping stage: `ConstraintFactor`
- Commands: 12 (real 6, disabled 6)

| Group | Id | Label | Kind | Overflow | Effective install | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 约束编辑 | `factor.edit_sourcing` | 编辑物源线 | Secondary |  | _disabled_ | 物源线约束编辑 |
| 约束编辑 | `factor.edit_trend` | 展布线 | Secondary | yes | _disabled_ | 展布线约束编辑 |
| 约束编辑 | `factor.snap` | 捕捉 | Toggle |  | _disabled_ | 约束线捕捉开关 |
| 插值计算 | `factor.compute` | 计算单因素 | Primary |  | **real** | 按所选方法运行真实插值核（idw/kriging/约束 IDW） |
| 插值计算 | `factor.params` | 参数 | Secondary | yes | _disabled_ | 插值计算参数 |
| 插值计算 | `factor.cancel` | 取消 | Secondary | yes | **real** | 打开任务中心取消运行中的计算 |
| 连井分析 | `factor.select_wells` | 选井 | Secondary |  | **real** | 切到约束工作区并聚焦连井剖面 |
| 连井分析 | `factor.crosswell_path` | 连井路径 | Secondary | yes | _disabled_ | 按路径自动排列连井剖面 |
| 连井分析 | `factor.link` | 联动 | Toggle |  | _disabled_ | 剖面联动开关 |
| 等值线 | `factor.contour` | 生成等值线 | Secondary |  | **real** | 从已完成单因素任务提取等值线草稿 |
| 结果 | `factor.save` | 保存版本 | Secondary |  | **real** | 保存当前阶段成果 |
| 结果 | `factor.submit` | 送交验证 | Secondary |  | **real** | 切换到验证工作区 |

## 3 综合编图 (`IntegratedCompilation`)

- Workspace id string: see `workspace_id(IntegratedCompilation)` in spec
- Primary: `map.export`
- Mapping stage: `IntegratedCompilation`
- Commands: 12 (real 6, disabled 6)

| Group | Id | Label | Kind | Overflow | Effective install | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 相界编辑 | `map.select` | 选择 | Secondary |  | **real** | 选择要素（治理动作） |
| 相界编辑 | `map.edit_facies` | 编辑相界 | Secondary |  | **real** | 开始/停止编辑（治理动作） |
| 参考图 | `map.show_reference` | 显示参考图 | Toggle |  | **real** | 编图画布的参考图面板 开/关 |
| 参考图 | `map.opacity` | 透明度 | Secondary | yes | _disabled_ | 参考图透明度 |
| 图件整饰 | `map.annotate` | 标注 | Secondary |  | _disabled_ | 图件标注 |
| 图件整饰 | `map.legend` | 图例 | Secondary | yes | _disabled_ | 图例编辑 |
| 版式 | `map.template` | 模板 | Secondary |  | _disabled_ | 版式模板 |
| 版式 | `map.paper` | 纸张 | Secondary | yes | _disabled_ | 纸张/图框设置 |
| 版式 | `map.preview` | 预览 | Secondary | yes | _disabled_ | 版式预览 |
| 输出 | `map.export` | 导出图件 | Primary |  | **real** | 导出布局（治理动作 Ctrl+Shift+P） |
| 输出 | `map.save_plan` | 保存方案 | Secondary | yes | **real** | 组装并保存编图方案 |
| 输出 | `map.submit` | 送交验证 | Secondary |  | **real** | 切换到验证工作区 |

## 验证 (`Validation`)

- Workspace id string: see `workspace_id(Validation)` in spec
- Primary: `verify.run`
- Mapping stage: _none (must not rewrite mapping stage)_
- Commands: 13 (real 12, disabled 1)

| Group | Id | Label | Kind | Overflow | Effective install | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| 对象与基准 | `verify.select_object` | 选择对象 | Secondary |  | **real** | 固定验证对象（井）并聚焦对比视图 |
| 对象与基准 | `verify.select_baseline` | 选择基准 | Secondary | yes | **real** | 固定基准解释版本 |
| 联动对比 | `verify.link` | 联动 | Toggle |  | **real** | 对照视图深度游标联动（需时深标定） |
| 联动对比 | `verify.side_by_side` | 并排 | Secondary |  | **real** | 解释 \| 预测 \| 差异 三列对照 |
| 联动对比 | `verify.overlay` | 叠加 | Secondary | yes | **real** | 解释与预测半透明叠加对照 |
| 联动对比 | `verify.difference` | 差异 | Secondary |  | **real** | 红=不一致 绿=一致 区间对照 |
| 检查 | `verify.run` | 运行验证 | Primary |  | **real** | 对工程内全部编图文档运行 QC 规则 |
| 检查 | `verify.settings` | 检查设置 | Secondary | yes | **real** | 当前内置 QC 规则一览 |
| 检查 | `verify.cancel` | 取消 | Secondary | yes | _disabled_ | 取消 QC 运行 |
| 复核 | `verify.locate` | 定位问题 | Secondary |  | **real** | 定位当前报告的第一个空间问题 |
| 复核 | `verify.record` | 记录结论 | Secondary |  | **real** | 对选中问题录入人工复核结论 |
| 报告 | `verify.save_record` | 保存记录 | Secondary |  | **real** | 保存当前复核记录 |
| 报告 | `verify.export_report` | 导出报告 | Secondary |  | **real** | 导出 QC 报告 JSON |

## Disabled inventory (effective)

| Id | Label | Reason (as registered) |
| --- | --- | --- |
| `data.link_well` | 关联到井 | 把数据版本关联到井对象 |
| `data.set_role` | 设置角色 | 设置资产角色 |
| `data.history` | 版本历史 | 资产的版本来历链 |
| `data.lineage` | 来源关系 | 版本的下游影响链 |
| `predict.select_well` | 选择井数据 | 选择参与预测的井 |
| `predict.select_seismic` | 选择地震 | 打开体版本…（工程内 PWBVOL1） |
| `predict.model_params` | 模型参数 | 预测模型参数 |
| `predict.params` | 参数 | 预测运行参数 |
| `predict.link` | 联动 | 井震联动开关 |
| `factor.edit_sourcing` | 编辑物源线 | 物源线约束编辑 |
| `factor.edit_trend` | 展布线 | 展布线约束编辑 |
| `factor.snap` | 捕捉 | 约束线捕捉开关 |
| `factor.params` | 参数 | 插值计算参数 |
| `factor.crosswell_path` | 连井路径 | 按路径自动排列连井剖面 |
| `factor.link` | 联动 | 剖面联动开关 |
| `map.opacity` | 透明度 | 参考图透明度 |
| `map.annotate` | 标注 | 图件标注 |
| `map.legend` | 图例 | 图例编辑 |
| `map.template` | 模板 | 版式模板 |
| `map.paper` | 纸张 | 纸张/图框设置 |
| `map.preview` | 预览 | 版式预览 |
| `verify.cancel` | 取消 | 取消 QC 运行 |

## How to re-verify

```bash
git rev-parse --short HEAD  # expect docs branch tip descended from 470d7500
rg -c 'cmd\(' libs/ui_ribbon/src/ribbon_spec.cpp
rg -c 'register_real\(|register_disabled\(' apps/paleo_workbench_platform/ribbon_command_install.cpp
# table integrity is also asserted by ui_ribbon core smoke (unique ids, one primary/workspace)
```
