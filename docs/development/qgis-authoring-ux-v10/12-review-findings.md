# 12 — Review Findings（5 轮评审与处置）

评审基线：`9931bd2d`（V10 实现完成点）；修复提交见 git log
（`fix(ui): V10 review round fixes — R1-R5`）。所有 P0/P1 清零。

## R1 — UI 架构

| 级别 | 发现 | 处置 |
|---|---|---|
| P2 | 编辑 chip 在 stage-lock（非 RAW/冻结）时显示「可编辑」——呈现超出事实 | ✅ chip 新增「锁定（原因）」态，消费 edit_gate_reason |
| P3 | `stage_group_visibility` 与 cancel 豁免不对称（陷阱） | ✅ docstring 记录组级映射不覆盖逐工具豁免 |
| P3 | `_recommended_action_text` 死导入 | ✅ 删除 |
| P3 | legacy `update_state` 硬编码 dirty=False | ✅ 保留（mapping_page 兼容入口）+ 注明仅 legacy |
| P3 | 树菜单 repair 双重求值 + 不可达回退 | ✅ facts 探针优先（一次上下文两次投影共享 base） |
| P3 | `_duplicate_vector_layer` 零 re-gate | ✅ 工程级守卫 + 结构性豁免注释 |
| P3 | 状态 chip 判词意译（漂移隐患） | ✅ gate 判词透传 edit_gate_reason；捕捉引擎句保留（呈现行非判词） |
| P3 | RAW 无 metadata.editable 旗标时拿不到草稿入口 | ✅ RAW 块按 facts.raw_protected 编排（不受旗标限制） |
| 结论 | 无第二可用性权威；新增 setEnabled 全部是 Qt 呈现；判词透传链完整 | — |

## R2 — QGIS 工作流

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 菜单项 tooltip 默认不显示——「判词直达菜单」对用户不可见 | ✅ 两处 `setToolTipsVisible(True)` |
| P1 | RAW 复制为草稿产出无角色副本：抢主位防护失效 + 桥侧 badge 仍 RAW | ✅ 副本登记 DERIVED 草稿角色 + 控制器角色覆写（set_layer_role） |
| P2 | 编辑 chip 缺 gate-closed 态（同 R1-P2） | ✅ 同上 |
| P2 | 拓扑 chip 计数=全会话，点击只校验活动层 | ✅ `validate_open_session_topology`（同口径覆盖） |
| P2 | 捕捉 tooltip 报全局容差而非有效容差 | ✅ `_effective_snapping_tolerance`（覆盖优先） |
| P3 | 画布菜单缺 平移/复制坐标 | ✅ 两个入口（复制坐标用最近地图坐标） |
| P3 | 捕捉读数不可点击（QGIS 磁铁惯例） | ✅ `snapping_activated` → 捕捉设置 |
| P3 | 「Edit X」中英混排 | ✅ 「编辑 X ● 未保存」 |
| P3 | 比例尺可渲染 `1:0` | ✅ <1 → `1:—` |
| P3 | dirty+拓扑错误缺「保存受阻」态 | ✅ chip 追加「（保存受阻）」 |
| P3 | 状态块未覆盖 split/merge/reshape/delete_selected | ✅ 扩展 |
| P3 | 「拓扑编辑」tooltip 未提共享节点传播 | ✅ tooltip 补全 |

## R3 — 视觉/设计

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 状态条 1366 溢出：固定省略上限 + 部分 label 不省略 | ✅ 按优先级收敛（渲染器→测距→拓扑→捕捉隐藏；编辑 chip 永存）+ resizeEvent 联动 |
| P2 | `#ffffff` 硬编码 | ✅ `ON_PRIMARY` token |
| P2 | chip 样式非主题响应（深色残留浅色） | ✅ `style.bind` + `style.palette()`（theme_changed 重渲染） |
| P2 | 状态行中英混排 | ✅ Renderer→渲染器 / Edit→编辑 |
| P3 | WARNING 深色对比 ≈3.05:1 | ✅ `_DARK_OVERRIDES["WARNING"]="#d97706"` |
| P3 | 拓扑 chip 仅鼠标可达 | ✅ palette `map:topology_validate` 键盘路径 |
| P3 | 捕捉设置菜单项缺图标 | ✅ `map/snapping.svg` |
| 结论 | preferred QSS 机制/双信号/主题 token 经复核正确 | — |

## R4 — 交互对抗

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 捕获中右键：完成捕获 + 菜单双触发 | ✅ pending 采点时抑制菜单（右键归还工具手势） |
| P1 | B 层开编辑时 A 层会话被静默遗弃；随后「开始编辑」A 实际是保存 | ✅ `_commit_other_open_sessions`（切层先提交/回滚，状态消息说明） |
| P1 | 拓扑 chip 计数/点击口径不一致（同 R2） | ✅ 同上 |
| P2 | `_sync_status_bar` 每次指针移动全量上下文（docstring 承诺的快路径不存在） | ✅ `update_coordinate`/`update_scale` 轻路径；全量投影只在状态同步 |
| P2 | duplicate 直写 active_layer_id 绕过 rebind | ✅ 经宿主登记角色 + 状态同步链收敛（controller 内部行为保留记录） |
| P3 | 菜单 QMenu 泄漏 | ✅ `deleteLater()` |
| P3 | 捕捉设置菜单项绕过 blocking 门禁 | ✅ `_open_snapping_settings_gated` |
| P3 | chip 点击不限左键/按下起点 | ✅ 左键 + press-release 同命中 |
| P3 | 菜单分隔符 exec 期间可孤儿 | 记录（菜单短生命周期；aboutToShow 重算留后续） |
| 结论 | 部分事实 apply_context 无 KeyError；chip 竞态/树菜单目标正确性/重栅格经攻击验证为稳 | — |

## R5 — 性能

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 指针移动逐事件全量上下文（O(N) @1000 层 × 每帧） | ✅ 轻路径（坐标单读数更新） |
| P1 | extent 逐帧全量上下文 + pyproj 每帧解析（回退 R3-P2 成果） | ✅ 轻路径（比例尺单读数）+ `crs_axis_unit_metres` lru_cache |
| P2 | 每次上下文构建两次调度器快照 | ✅ `_scheduler_statuses` 单次共享 |
| P2 | apply_context 逐事件重解析 chip QSS | ✅ 状态迁移才 setStyleSheet/refresh |
| P3 | help 签名含易变字段（zoom 后重拼同文 tooltip） | 记录（成本有界；语义正确） |
| P3 | layer_menu_facts 两次全量上下文 | ✅ base 共享 |
| P3 | `_sync_action_state` 链 @1000 层线性有界（无 O(N²)） | 复核通过 |

## 状态矩阵额外发现（测试驱动）

| 级别 | 发现 | 处置 |
|---|---|---|
| P1 | 未知阶段 fail-closed 把 cancel（Esc 语义）随 snapping 组隐藏 | ✅ `_stage_group_gate` 豁免 cancel（回归钉 `test_cancel_survives_unknown_stage`） |
