# 07 — Task / Progress / Feedback UX (V11)

## 统一操作模型（goal §12）

`ui/operations.py` — `OperationRegistry`（随 shell 生命周期）：

```
QUEUED → RUNNING → CANCELLING → COMPLETED | WARNING | FAILED | CANCELLED
```

`OperationRecord` 携带：标题、对象上下文、进度（done/total 或阶段文本）、耗时、取消入口（协作式）、**结果跳转**（label + callable）、错误。终态记录 FIFO 保留 40 条；`clear()`（shell 销毁）不留悬挂回调。

## 任务中心合并（单一出口）

`TaskCenter`（增量模型 + delegate 绘制，架构不变）`attach_registry` 后把 registry 记录经 `_OperationHandleAdapter`（状态映射 warning→降级完成 等）与调度器任务**同表呈现**：同一状态词表、同一取消交互（registry 记录走 `request_cancel`）、右键/双击终态记录执行**结果跳转**（迟到跳转吞 RuntimeError）。空表空态在每次 refresh 时同步（修复常空表不显示空态的缺口）。

## 已登记操作（V11 首批）

| 操作 | 进度 | 取消 | 结果跳转 |
|---|---|---|---|
| 完整性校验（单/批量） | IntegrityWorker.progress（done/total/名称）——**信号此前存在但从未接线**（D4），现已进 registry | ✓（worker.cancel） | 汇总文本 |

校验经 `data_lifecycle_controller.verify_assets` 登记；其余长任务（导入/导出/重算/制备）逐步迁移——见 12-known-limitations。

## 任务面板统一（G3）

- `TaskPanelBase`（测井/地震预测共用）：状态值 = PwbBadge（tone 经 state_language 任务词表桥 `tone_to_badge`）；任务列表行 `名称 · 状态`（中文词表，不再泄漏 pending/running 英文裸串）；列表按任务 id `reconcile`（同键行身份保持）。
- `FactorTaskPanel`：私有 `_STATUS_TONES` 映射退役，统一经 `state_token("task", …)+tone_to_badge`。

## GUI 线程契约（goal §9，配合 11-performance）

| 禁止（GUI 线程） | V11 状态 |
|---|---|
| hydrate 100k 对象 / 全量 SQL | Data 资产表分页模式（既有）+ 本 goal 的模型迁移面 |
| 全量 lineage traversal | **已移出**：Data 页选择 → 血缘双链经 `AsyncQuery`（epoch/latest-only/迟到拒绝）+ 32 条有界缓存；血缘 tab 先显加载占位（`show_lineage`）再回填（`update_lineage`） |
| 大量 QWidget creation | 模型迁移面（04）零建项 |
| 同步 hash 大文件 | 校验/导入/交付既有 worker（保持） |

## 状态组件采用（G2）

`PwbEmptyState`（TaskCenter/home 既有）扩展到：well_table、resource_table、relink、catalog_health、map_topology_issue 面板；`PwbLoadingState` 用于 relink 扫描与 catalog 深检（替代无进度的模态等待）；`PwbBadge` 状态行进入任务面板。空文案统一语汇（「未发现缺失源」「未发现目录健康问题」等）。

## 结果跳转

既有最佳实践（血缘节点双击 → 资产行定位）保持；registry 终态记录的右键/双击跳转是统一机制的推广面。

## 测试

- `tests/test_v11_visual_qa.py::task_center_operations`：registry running@42% + 终态带结果标签。
- `tests/test_v11_performance_structural.py`：AsyncQuery latest-only/迟到拒绝/shutdown 静默；registry FIFO 淘汰。
- `tests/test_factor_task_panel.py` / `test_prediction_task_panel.py` / `test_seismic_task_panel.py`：词表渲染钉住。
- `tests/test_data_manager_governance_ui.py`：血缘异步等待协议（`_await_async_lineage`）。
