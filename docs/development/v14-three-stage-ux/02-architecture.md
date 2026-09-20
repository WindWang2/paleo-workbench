# 02 — Architecture（V14-THREE-STAGE-UX）

## 设计原则（从审计推导）

**机制已备、接线缺失** 是基线的核心事实。因此本线架构 = 「接线 + 少量新装配组件」，
不是重写：

1. **不建第二权威**：stage 唯一运行时权威仍是 `ProjectSession::mapping_stage_`
   （写入口 `MainWindow::applyStageValue`）；本线新增的全部是**投影（projection）层**。
2. **占位→换真件的 adopt 模式**是本仓既定扩展协议（AppShell::adopt_preparation_page、
   MappingPage::adopt_*、HubPage::adopt_submodule），新装配沿此模式。
3. **诚实降级**：跨线能力（factor 内核、组图导出、QGIS 深层）未就绪时呈现真实状态，
   不假成功。

## 新组件：`libs/ui_stageflow`（本线独占库）

三层（仓库 UI 库标准模式：Qt-free core + Qt shell + tests）：

### 1) Qt-free core — `stage_presentation.hpp/.cpp`

`StagePresentationState`：**派生视图模型**（无自有权威字段，全部由 provider 注入或从权威读出）：

```cpp
struct StagePresentationSnapshot {
    std::string stage_value;                 // 权威: ProjectSession.mapping_stage()
    std::string stage_label;                 // 派生: tool_policy 中文标签
    std::optional<std::string> horizon;      // 权威: project.stratigraphy.target_horizon
    bool project_open = false;
    std::optional<std::string> write_granted_reason;  // nullopt=已授权
    int running_tasks = 0;                   // JobCenter 投影
    int stale_factors = 0;                   // readiness 投影
    StageReadinessKind readiness = Unknown;  // 派生
};

struct StageLayoutProfile {                  // 每阶段的“舞台布置”（纯数据）
    std::map<std::string, bool> workstation_dock_visibility;  // 14 dock 键
    std::map<std::string, bool> mapping_page_panels;          // MappingPage dock 键
    std::string lower_pane_mode;             // "none"|"seismic"|"well"|"crosswell"|"factors"
};
StageLayoutProfile stage_layout_profile(const std::string& stage_value);  // 从
// kStageGroupVisibility 派生: stage1 隐 factor/layout_export 相关面板、stage2 显
// factor、stage3 显 composer 隐 factor——与工具门控同源，永不漂移。
```

**持久偏好与瞬态分界**（V5 §45 分工）：
- 持久（QSettings 组 `stage_presentation/`，经注入的 KV sink，Qt-free）：
  用户对每阶段的 dock 可见性覆盖、split ratios、底部面板用户偏好。
- 瞬态（不落盘）：当前 focus、selection、preview_mode、canvas_priority。
- 科学状态（stage/horizon）**不经过**本模型持久化——分别由 ProjectSession 与工程文档拥有。

### 2) Qt-free core — `surface_state.hpp/.cpp`

统一 busy/empty/error/stale/degraded 呈现模型（填 `Pwb*` 组件与 `StateToken` 之间的空档）：

```cpp
enum class SurfaceKind { Ready, Loading, Busy, Queued, Cancelled, Stale,
                         Degraded, MissingSource, Unsupported, Error,
                         NoProject, NoLayer, NoSelection, Empty };
struct SurfaceState { SurfaceKind kind; std::string title; std::string hint;
                      std::optional<std::string> retry_action_id; };
SurfaceState surface_state_for(...);  // 按领域输入派生（fail-closed: 未知→Unsupported）
// Qt 侧桥接: surface_to_widget() 把 SurfaceState 映射到 PwbLoadingState/
// PwbErrorState/PwbEmptyState/StateToken —— 单一映射点，页面不各自选型。
```

### 3) Qt shell — `stage_flow_controller.hpp/.cpp`（QObject）

产品装配的粘合控制器（在 apps 层实例化，一处集中）：
- 订阅 ProjectSession/工程变化 → 更新 StagePresentationSnapshot → 驱动
  MappingStageBar/StageDock/StatusBar 同步（单一写入口扇出）；
- 应用 `StageLayoutProfile` 到 WorkstationFrame（dock 可见性矩阵）+ MappingPage
  （MapDockManager 面板）+ MainWindow 侧 dock；
- 提供 `lower_pane_mode()` 给底部联动区的显隐控制；
- 持久化通道绑定 QSettings（`stage_presentation/` 组）。

## 产品装配（apps/paleo_workbench_platform，具名块 `BEGIN/END PWB-V14-THREE-STAGE`）

新增 `stage_flow_install.cpp/.hpp`（本线独占文件）：
1. **挂载孤儿 MappingStageBar**：`WorkstationFrame::mount_top_bar(QWidget*)`（ui_shell
   新增具名 API，插入 app bar 工具行）← `composite->stage_bar`（reparent）。
2. **接线**：`stage_bar::stage_requested` → `MainWindow::applyStageValue`（既有权威写入口）；
   `horizon_requested` → 工程 `stratigraphy.target_horizon` 写 + 会话通知（走既有
   `notify_project_changed` 型通道）。
3. **stage 恢复**：openProject 后从 `mapping_workspace.current_stage`（workspace codec 读）
   恢复 ProjectSession 映射阶段，StageDock/Bar 同步。
4. **命令注册**：向 `command_registry()` 注册生产命令（约 25 条）：切阶段 ×3、切层位、
   导航 5 hub + 子页、开/关面板（图层/参考/组图/任务中心/Agent）、聚焦井、打开地震剖面、
   zoom-to-selected、stage help。回调与按钮同源（同一 slot/函数）。
5. **TaskCenter providers**：把 JobCenter 的 owner 注册表投影为
   `WorkstationTaskCenter` 的 snapshot/operation provider（jobs 表 + 取消）。
6. **hub3 数据链接线**：MapDocumentBank `active_changed/document_saved/dirty_changed` →
   `MappingPage::update_state`；`MapEditScene` 选择/脏/拓扑/命令栈信号 → 底部工作台三 tab
   + `MapEditToolbar` 安装到 `MapAuthoringToolbars` 挂点。
7. **Selection bus 实例化**：`QtSelectionContext + ViewCoordinationController`
   （链接 `Pwb::UiControllers` 进平台——root CMake 一行守卫）；绑定 sinks：地图井高亮、
   测井 dock、地震定位、Geo3D 高亮、状态栏 horizon 段。

## 明确不做（边界）

- 不改 QGIS layer order/identity（Prompt 3）；不改 factor 数值核（Prompt 4）；
  不做 layout/export 引擎（Prompt 5）；不改 catalog（Prompt 1）；不重复 #1434 的 perf 面。
- 不新增第二个 stage 枚举、第二个命令注册表、第二个 selection bus、第二个任务中心。
- Python 生产路径零新增。

## 线程/异步模型

- StageFlowController 全部在 GUI 线程；无自有 worker。
- 任务状态经 JobCenter→TaskCenter 的 400ms 轮询（既有）+ 事件即时刷新。
- late-result 防护沿用各部件 generation token（不新增机制）。

## 失败语义

- stage 恢复读到未知 stage 值 → lenient fallback stage1（与 workspace codec 一致）。
- LayoutProfile 应用时 dock 不存在（能力 OFF 降级）→ 跳过并记录，不 FATAL。
- 命令回调目标不可用 → 命令以 disabled+reason 呈现（registry 既有 fail-closed）。

## Scale 预算

- stage 切换：纯可见性矩阵应用，O(dock 数)，无图层重建、无工程重载（stages.py 契约）。
- 命令面板：≤50 条注册，子序列匹配已有性能设计。
- TaskCenter 轮询 400ms，job 表有界（JobCenter max_workers=1+1）。
