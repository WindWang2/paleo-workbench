# Workstation UX V6 — 08 决策记录

Date: 2026-09-07（实现期决策，全部可追溯到提交）

| # | 决策 | 理由 |
|---|------|------|
| D1 | 跳过 brainstorming 用户问答 | /goal 规范完全给定 + 明确自主模式（用户指令优先级最高） |
| D2 | 复用主 checkout 的 `.venv`（uv/3.12）跑 worktree 测试 | cwd 优先导入使 `paleo_workbench` 解析到 worktree；geo-viz-engine/native 未改动 → 复用主树构建产物正是 prompt 的「reuse built native artifacts」要求 |
| D3 | 不在 worktree 初始化 submodule | gdal/proj 重建被 prompt 明令禁止；venv 从主树解析 |
| D4 | RAW 门禁以 `set_edit_gate` 注入 `CompositeEditController`（单点） | 会话起点（start/ensure/repair/flush）与属性表全部过门；宿主仍由 `CompositeDocument._role_allows_editing` 定义规则——权威不搬家 |
| D5 | 可信导入通道 `import_layer_features` 显式绕过用户门禁 | 语义对齐 catalog `import_raw`：RAW 保护约束**用户编辑**，不约束领域建稿落盘；源码扫描测试钉死调用方只有 stage_actions（review round 1/2） |
| D6 | 工具条阶段过滤 = 隐藏（QGIS 惯例）；palette = 禁用+原因（可发现性） | 同一命令两种呈现语义按媒介惯例分工 |
| D7 | `governed_edit_actions()` = 各阶段 edit_actions 并集 | profile 只约束它显式声明的动作；add_point 不受治理（无 profile 声明它） |
| D8 | 具名预设不 `dock_all_panels()`；仅「恢复默认布局」重置几何 | 用户浮动/分屏是显式偏好；预设 = 可见性矩阵（audit A-P0-3） |
| D9 | 状态语言 = 纯呈现词汇表（无领域逻辑） | review round 2 验证：不成为第二权威；tone 只供样式层 |
| D10 | 快照字段最小集（消费者驱动） | Karpathy 纪律；新增字段必须有消费者 |
| D11 | 阶段白名单 fail-closed（mapping_stage 未知 → 禁用） | provider 故障时放行阶段限定命令比误伤更危险（review round 1） |
| D12 | `running_task_count` = QUEUED+RUNNING | 与任务中心/触发器/徽标同口径；消除晋升竞态（review round 3） |
| D13 | 曲线拾取落检查器（curve kind）而非新面板 | D-P0-1 的最小正确落点；字段开放集合诚实渲染 |
| D14 | UIContextService.refresh 容忍拆壳期 RuntimeError | 与 shell 既有死壳纪律一致（迟到的轮询定时器不刷屏） |
| D15 | 并行子代理分工按**文件族**切分（TDD + 不提交，主会话验证后提交） | 避免同文件冲突；架构真源保留在主会话 |
| D16 | 视觉 QA 扩展而非替换；v5 基线不动 | /goal §13 明令；新状态全部无桥可构造（诚实回退态） |
| D17 | 接受的遗留显式文档化（10-known-limitations） | 诚实汇报优于假完成 |
