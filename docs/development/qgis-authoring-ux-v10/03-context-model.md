# 03 — ToolContext v4（上下文模型）

contract_version=4（V9 v3 的**附加式**扩展；缺省安全——不生产的表面保持
v3 行为）。

## 新事实

| 字段 | 语义 | 生产者 |
|---|---|---|
| `snapping_tolerance_px` | 全局捕捉容差（0=服务默认/未知） | `tool_context_inputs`（SnappingService） |
| `snapping_modes` | 当前全局模式集（()=默认） | 同上 |
| `snapping_reference_count` | 参与捕捉的引用层数 | CompositeDocument（metadata.snap） |
| `snapping_role_recommended` | 活动层配置=角色推荐（None=角色无推荐） | `_snapping_role_recommended`（覆盖通道 vs profile） |
| `canvas_destination_crs` | 桥画布目标 CRS（""=未暴露） | `_canvas_destination_crs`（shim destination_crs） |
| `crs_mismatch` | 工程/图层 CRS 可证不一致（None=不可判定） | `_project_layer_crs_mismatch`（normalize 后比对） |
| `reference_failed_count` | 失败/错误引用层数（呈现计数） | `_reference_failed_count` |
| `running_task_count` | 运行+排队任务总数（呈现计数） | `_running_task_count` |

## 设计约束

* 全部 O(1) 派生（字典/计数器读取），挂在既有刷新链上无新增扫描。
* 呈现事实 ≠ 门禁事实：`blocking_task` 仍是唯一全局阻断判定；
  `crs_mismatch` 是警示呈现（门禁在 `crs_valid` + 捕获 commit 守卫）。
* palette 快照（UIContextSnapshot）新增 `split_ready/merge_ready/
  reshape_ready/native_canvas_available/native_capability_flags`（provider
  缺席 → 保守 False，执行侧 re-gate 兜底）。

## 消费者

状态条（`MapStatusBar.apply_context`）、工具条 tooltip 状态块
（`_action_status_blocks`）、Inspector（几何/CRS/会话/选择行）、
palette applicability（三个几何命令）。
