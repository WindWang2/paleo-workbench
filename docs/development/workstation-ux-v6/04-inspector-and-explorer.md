# Workstation UX V6 — 04 检查器与图层树

Date: 2026-09-07

## 1. Inspector（`ui/workstation/inspector.py`）

typed 分发保持（well/horizon/layer/project/seismic/resource/map_component/generic），V6 新增：

- **`curve` kind**（baseline D-P0-1 落地）：测井引擎 `click_pick_info()` 拾取经 `app_shell` 接线直达检查器（此前信号无生产消费者）。字段开放集合：只显示存在的键；**0.0/0 是真实读数不当缺失**（`_first` 显式 None 判定，review round 1）；缺失显示「—」。
- **上下文 seam（`set_context_seam`）**：图层检查的域行（角色/成熟度/可编辑/新鲜度）由宿主注入 `payload → {行: 值}`，检查器不解析 mapping 权威。数据源 = `CompositeDocument.layer_domain_status()`：RAW 角色永远 `▣ RAW 不可编辑` + raw 成熟度（token 可达性，review round 1）；新鲜度经 `layer_freshness`（见下）；未知诚实「未知」。
- 域值统一经 `state_language` 词汇渲染（glyph+文字，§06）。

## 2. 图层树（QGIS 树运行时权威不变）

- **新鲜度聚合真实化**（baseline B-P1-3）：`LayerGroupController.apply_freshness(StaleSummary)` 由 `stale_summary_changed` 推送；`layer_freshness(layer_id)` 经成员资格解析 artifact_key（`factor:{task_id}` / `phase1_draft:{layer_id}` / `integrated:{layer_id}`）；`group_summary` 真实统计 stale（STALE/MISSING_INPUT/SUPERSEDED）与 errors（MISSING_INPUT）——此前硬编码 0/0。**树 UI 尚未渲染该聚合**（见 10-known-limitations）。
- 树本身保持增量 reconcile（desired-tree diff、批量放置、suppress/echo 纪律）；V6 未改树重建路径（镜像发布热点与 fallback 树全量重建为已记录遗留）。
- **属性表差量刷新**（§05）不破坏 RAW 门禁：门禁拒绝对话框整表只读 + 原因行；编辑被拒时单元格恢复为已提交值（无假成功渲染，review round 3）。

## 3. Explorer 大列表

分页目录（>25k SQLite keyset）保持权威；V6 把 well 列表/组合框差量化（§05）。导航树实体分页（500/页）不变。
