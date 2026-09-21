# 03 — Contracts（V14-THREE-STAGE-UX 对外契约）

## C1 StagePresentationSnapshot（Qt-free，`pwb/ui_stageflow/stage_presentation.hpp`）

- 构造：仅经 `StagePresentationController::snapshot()` 或测试直构；消费者**不得回写**
  （值语义 + const 访问器）。
- `stage_value` 词汇 = `tool_policy` 权威字符串（`facies_calibration|constraint_factor|
  integrated_compilation`），宽容解析复用 `stage_from_value`。
- `StageLayoutProfile` 为纯函数 `stage_layout_profile(stage)` 派生，输入不变则输出不变
  （可快照测试）。用户 QSettings 覆盖在应用层叠加，不改变纯函数本体。

## C2 SurfaceKind 词汇（`pwb/ui_stageflow/surface_state.hpp`）

14 值封闭枚举；`state_token_for_surface()` 单向映射到 `ui_workstation::StateToken`
（glyph+label+tone，双信号原则：颜色永远伴随文字）。未知领域输入 → `Unsupported`
（fail-closed，不猜）。Qt 桥 `surface_widget()` 只在一个翻译单元里选 `Pwb*` 组件，
页面代码不得直接 new 状态组件绕过该映射。

## C3 WorkstationFrame::mount_top_bar（ui_shell，additive）

```cpp
// 在 app bar 工具行右端追加宿主提供的全局条（三阶段条）。一次性；二次调用忽略
// 并返回 false。bar 所有权归 WorkstationFrame（reparent）。
bool WorkstationFrame::mount_top_bar(QWidget* bar);
```

## C4 MainWindow 接线缝（apps，具名块 PWB-V14-THREE-STAGE）

- `stageFlowInstall(MainWindow&, AppShell*)`（stage_flow_install.hpp）：
  创建 StageFlowController、挂 bar、注册命令、注入 providers、接 bank/scene 信号、
  实例化 selection bus。幂等（重复调用 no-op）。
- stage 恢复：`MainWindow::restore_mapping_stage_from_project()` 读 workspace codec 值
  → `applyStageValue`。仅在 openProject 成功路径调用。

## C5 命令 ID 约定（command_registry）

`stage.goto.prediction | stage.goto.constraints | stage.goto.compilation`、
`stage.horizon.select`、`nav.hub.<data|wells|seismic|mapping|viz>`、
`panel.toggle.<layers|reference|composer|tasks|agent|inspector>`、
`well.focus.selected`、`seismic.open.linked`、`map.zoom.selected`、`stage.help`。
- 每条必填 `stages` 白名单或留空=全阶段；`requires_write` 仅编辑类；
  `applicability` 给出 disabled reason（中文）。
- 回调必须与对应 UI 按钮/菜单走同一实现函数（禁止旁路双实现）。

## C6 TaskCenter provider 契约（复用 WorkstationTaskCenter 既有缝）

- snapshot provider：返回 `std::vector<TaskRow>`（id/label/state/progress/cancellable），
  数据源 = JobCenter owner 注册表 + workflow run 投影；GUI 线程拉取。
- operation provider：cancel(id)/retry(id)/jump(id)——cancel 走 JobOwner::cancel；
  retry/jump 在目标未注册时返回 false（诚实）。

## C7 Selection bus 契约（复用 ui_controllers 既有实现）

- 实例：每 MainWindow 一个 `ViewCoordinationController`（非进程单例）。
- source token：发布必须带 SOURCE_* 标签；回显抑制沿用 `was_published_by`。
- project token：`bind_project` 在 openProject/closeProject 重绑；迟到结果由各部件
  generation guard 丢弃（不新增机制）。
- 项目切换清空 selection；面板隐藏不销毁 selection；多窗口各自 controller 不串扰。

## C8 bank→page 数据链（apps 装配层信号接线）

`MapDocumentBank::active_changed/document_saved/dirty_changed` →
`MappingPage::update_state(documents_json)`；`MapEditScene::selection_ids_changed/
document_dirty_changed/topology_issues_changed/command_stack_changed` →
底部工作台三 tab + MapEditToolbar undo/redo enablement。全部 queued connection，
发送者销毁自动断线（Qt 父子链保证）。

## C9 持久化键（QSettings `PaleoWorkbench/Workstation`）

- `stage_presentation/version` = 1（版本栅栏，restore 仅精确匹配）。
- `stage_presentation/<stage>/dock_overrides`（dock_id:visible 逗号表）。
- `stage_presentation/<stage>/split`（分号分隔整数）。缺省=用 StageLayoutProfile 默认。
- 科学状态不入此组（stage 归工程，horizon 归工程）。

## C10 兼容性

- 旧工程无 `mapping_workspace` → 恢复 stage1（既有 lenient fallback），无迁移需求。
- 旧 QSettings 无 `stage_presentation/` 组 → 全默认，无迁移。
- 能力 OFF（无 seismic viewer/无 viz_b/无 composition）时命令注册跳过对应条目
  （不注册不可用命令，palette 不显示空承诺）。
