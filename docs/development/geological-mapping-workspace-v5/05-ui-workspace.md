# 05 — 工作区 UI

## 阶段切换条（§34/§62/§63）

`MappingStageBar`：AppBar 下方的紧凑固定 QToolBar 行
（`[ 初始相图 ] — [ 约束/单因素 ] — [ 综合编图 ]`），可选中分段按钮 +
状态徽标（`✓` 就绪 / `~` 提醒 / `!` 未就绪 / `N↑` 过期计数）。不做整页
彩色主题（§63）——阶段只经 active 指示 + 徽标表达。

## 阶段面板（§35，中央地图永不切换）

`MappingStagePanel`（「编图阶段」dock，左侧与「输入与结果」叠 tab）：
`QStackedWidget` 三页，每页 = 就绪度清单（可点击定位 target）+ 阶段动作 +
说明脚注；Phase 2 页附加 typed 约束创建行（物源线/方向/展布/岸线/相带
边界/断层/掩膜）。

## 阶段动作（`stage_actions.py`）

| 阶段 | 动作 |
|---|---|
| ① | 加载初始相图（RAW 叠加）/ 叠加测井预测 / 叠加地震预测（VECTOR_POLYGONS）/ **创建解释草稿（RAW→DERIVED）** / 保存阶段成果 |
| ② | 单因素工作台（导航既有制备 hub）/ 叠加单因素结果（live 网格→等值线→factor 组）/ 保存 |
| ③ | 选择证据版本 / 创建综合草稿 / 运行 QA（拓扑+过期）/ 生成 MapProduct |

RAW 门禁：`_role_allows_editing` 对 RAW 保护角色拒绝编辑会话并给出原因
（「请创建 DERIVED 草稿后编辑」）。

## Dock 建议（§6/§7/§37）

`StageProfile.recommended_docks` 仅在该阶段**首次进入**时应用（只调显隐，
不动停靠几何）；此后用户布局自由，切走再回不覆盖。用户组显隐/组勾选覆盖
记录在 `StageViewState`（None=未覆盖，用 profile 默认），「Restore Stage
Defaults」清空覆盖层。

## 持久化分工（§45）

- **ProjectDocument.mapping_workspace**（科学状态）：当前阶段、成员资格、
  组结构树、阶段视图覆盖、成熟度、证据集。
- **QSettings**（UI 偏好）：组展开态（`mapping_workspace/expanded/<工程名>
  /<阶段>`，按工程键分域）；dock 几何沿用既有 `layout/window_state`。
