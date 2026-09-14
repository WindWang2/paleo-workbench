# 02 — 编图工作台有限状态机（FSM）设计

实现：`paleo_workbench/ui/workstation/mode_state.py`（纯 QObject，投影层，见
00-D12）。工具/画布的既有权威不变；FSM 只观察并广播 `mode_changed(WorkstationMode)`。

## 状态集

| 状态 | 含义 | 进入代表事件 | 画布/提示表现 |
|---|---|---|---|
| `IDLE` | 空闲浏览，无工具 | 启动 / Esc 退出工具 | 提示条：基本导航键 |
| `DIGITIZING` | 数字化采集进行中（面/线/点工具激活） | 工具激活(非顶点编辑) | 提示：Space/Tab/Ctrl+D/Esc |
| `ADJUSTING_BOUNDARY` | 边界调整（顶点编辑/重塑/裁剪） | 顶点/重塑工具激活 | 提示：Tab/Esc；吸色管禁用 |
| `INSPECTING_QC` | 质检向导交互中 | QC hub 激活且选中/定位 issue | 画布差分高亮；↑↓/Enter/F |
| `TIME_TRAVELLING` | 期次时空切换（拖拽/洋葱皮） | 时间轴 scrub 开始 | 洋葱皮/差分切换可视化 |

瞬态（不驻留，仅事件脉冲）：`TRANSIENT_PAN`（Space 按住）、`PREVIEW_PICK`
（吸色管悬停）。实现为 mode 之上的附加标志位（pan_held/preview_pick），避免状态爆炸。

## 事件（输入字母表）

`TOOL_ACTIVATED(tool_id)` · `TOOL_DEACTIVATED` · `GESTURE_CANCELLED` ·
`ESC_PRESSED` · `VERTEX_EDIT_ACTIVATED` · `QC_HUB_ACTIVATED` ·
`QC_ISSUE_FOCUSED` · `QC_HUB_CLOSED` · `TIMELINE_SCRUB_STARTED` ·
`EPOCH_COMMITTED` · `ONION_TOGGLED` · `PAN_HELD/PAN_RELEASED` ·
`FLOATING_PANEL_CLOSED`

## 转移表（完整、确定性；"—"=保持原状态不动作）

| 当前 \ 事件 | TOOL_ACT | TOOL_DEACT | ESC | QC_ACT | QC_CLOSE | SCRUB_START | EPOCH_COMMIT | VERTEX_ACT |
|---|---|---|---|---|---|---|---|---|
| IDLE | DIGITIZING* | — | IDLE（关浮层） | INSPECTING_QC | — | TIME_TRAVELLING | IDLE | ADJUSTING_BOUNDARY |
| DIGITIZING | DIGITIZING* | IDLE | IDLE（先取消手势） | INSPECTING_QC | — | TIME_TRAVELLING | DIGITIZING | ADJUSTING_BOUNDARY |
| ADJUSTING_BOUNDARY | DIGITIZING* | IDLE | IDLE | INSPECTING_QC | — | TIME_TRAVELLING | ADJUSTING_BOUNDARY | ADJUSTING_BOUNDARY |
| INSPECTING_QC | DIGITIZING* | IDLE | IDLE（关 hub） | INSPECTING_QC | IDLE | TIME_TRAVELLING | INSPECTING_QC | ADJUSTING_BOUNDARY |
| TIME_TRAVELLING | 拒绝† | IDLE | IDLE（取消对比） | INSPECTING_QC | — | TIME_TRAVELLING | 回先前模式‡ | 拒绝† |

\* tool_id 含顶点/重塑类时直接进 ADJUSTING_BOUNDARY（与 VERTEX_ACT 合并语义）。
† TIME_TRAVELLING 中途激活工具会打断洋葱皮对比 → 拒绝并提示"先 Esc 结束期次
对比"（Esc 在 TIME_TRAVELLING 首按 = 结束对比回 IDLE）。
‡ EPOCH_COMMITTED 从 TIME_TRAVELLING 落回 **进入前的先前模式**（记录
`_mode_before_travel`），通常 IDLE / DIGITIZING。ONION_TOGGLED 不换状态（自环）。

## 状态图

```
                    TOOL_ACTIVATED(普通工具)
        ┌──────────────────────────────────────────┐
        │                TOOL_ACTIVATED(顶点/重塑) / VERTEX_ACT
        ▼                          ▼               │
     ┌───────┐ ─────────────▶ ┌──────────────────┐ │
     │ IDLE  │                │ ADJUSTING_BOUNDARY│◀┘
     └───────┘ ◀─────────────┴──────────────────┘
        │ ▲   TOOL_DEACT / ESC(含手势取消)    │ ▲
        │ │                                   │ │  (各态经 TOOL_ACT 互转)
 QC_ACT│ │ESC / QC_CLOSE         QC_ACT│      │ │
        ▼ │                                   ▼ │
   ┌──────────────┐
   │ INSPECTING_QC│  QC_CLOSE / ESC → IDLE
   └──────────────┘
        ▲ SCRUB_START（自 IDLE/DIGITIZING/ADJUSTING/INSPECTING_QC）
        │
   ┌────────────────┐  EPOCH_COMMITTED → 回 _mode_before_travel
   │ TIME_TRAVELLING│◀─ ONION_TOGGLED（自环，洋葱皮不换状态）
   └────────────────┘  ESC → IDLE（取消对比）/ TOOL_ACT、VERTEX_ACT → 拒绝+提示
```

## 与既有系统的接线（只读观察点）

| FSM 事件 | 既有信号来源 |
|---|---|
| TOOL_ACTIVATED/DEACTIVATED | `CompositeEditController.activate_tool` / `state_changed`（tools.active_tool 投影） |
| ESC_PRESSED | map 工具 Esc 既有路径（MapActionController cancel）+ shell 快捷键 |
| QC_HUB_ACTIVATED/CLOSED/ISSUE_FOCUSED | InteractiveQCHub 信号（本任务新增） |
| TIMELINE_SCRUB_STARTED / EPOCH_COMMITTED / ONION_TOGGLED | StratigraphicTimelineWidget 信号（本任务新增） |
| PAN_HELD/RELEASED | KeyBindingManager Space 处理 |

## 回环防护契约

FSM 无 setter 链——事件→状态→`mode_changed` 只被 **只读消费者**（提示条、快捷键
域判定、HUD 显隐）订阅；任何消费者不得再向 FSM 发事件形成环。测试 M5-ECHO：
对全部 (状态×事件) 组合注入，断言每组合 dispatch 恰一次、无二次派发、
mode_changed 发射次数 ≤ 状态实际变化次数。
