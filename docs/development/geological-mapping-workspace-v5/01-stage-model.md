# 01 — 阶段模型（Stage ≠ Page）

## 核心裁决

`MappingStage` 是**工作流上下文**（Workflow Context），不是 QWidget 页面：

```
同一个 QGIS Project ─ 同一个地图画布 ─ 同一个图层权威
        └── MappingStage（当前工作上下文）
                ├── 组可见性 profile（增量显隐）
                ├── 活动编辑目标（按角色重指派）
                ├── 工具集合（StageToolProfile）
                ├── dock 推荐（仅首次进入，建议不强制）
                └── 就绪度/过期提示（提示不阻止）
```

三个阶段（`paleo_workbench/mapping_workspace/stages.py`）：

| 值 | 显示名 | 科学语义 |
|---|---|---|
| `facies_calibration` | ① 初始相图校正 | RAW 相图 + 测井/地震预测叠加 + 专家校正 |
| `constraint_factor` | ② 约束与单因素 | typed 地质约束 + 单因素图组织 |
| `integrated_compilation` | ③ 综合编图 | 证据综合 + 相带编辑 + QA + MapProduct |

## 切换纪律（§55/§70）

阶段切换**只做**：组可见性增量（`LayerGroupController.apply_stage_visibility`）、
编辑目标重指派（`_reassign_active_target`）、首次 dock 推荐、面板/工具上下文。

阶段切换**绝不**：重开 QGIS Project、重载源数据、触发科学重计算、销毁未提交
编辑（宿主在切换前 `flush_edit_sessions`；拓扑阻断的会话保持打开并告知）。

## 与 WorkstationLayoutPreset 解耦（§6）

`StageProfile.recommended_docks`（阶段首次进入的建议显隐）≠
`WorkstationLayoutPreset`（用户窗口布局偏好）。二者只经 dock 显隐建议弱耦合，
用户布局完全自由；阶段不写 saveState、不重排停靠几何。

## 成熟度与阶段正交（§33）

`ArtifactMaturity`（draft/reviewed/frozen/published）与阶段独立存储于
`MappingWorkspaceState.artifact_maturity`——「Phase 1 + Published」与
「Phase 3 + Draft」都是合法状态。

## 活动编辑目标（§42/§88，P0 风险）

每个阶段的 `active_editing_roles` 按优先级解析首个有现存图层的角色；全部
缺省 → None（编辑动作禁用并显示原因）。**绝不跨阶段继承**——测试
`test_active_editing_target_not_inherited_across_stages` 专门守护
「画物源线写进相带边界」级业务风险。
