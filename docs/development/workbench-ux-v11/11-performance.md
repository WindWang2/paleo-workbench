# 11 — Performance (V11)

## 结构性指标（优先于裸 wall clock；`tests/test_v11_performance_structural.py` + 两个 modelview 套件）

### Table（goal §21）

| 指标 | 断言 |
|---|---|
| 100k 行零 item-per-cell | QTableWidgetItem 构造计数 == 0（monkeypatch 计数器）；well_table/correlation tops/resource/relink/catalog_health/topology/version/inspector 版本全部模型化 |
| 首屏只取有限页 | ObjectTableModel(100k)+QTableView show 后列-0 取值调用 < 2000（视口有界，非全表） |
| 排序模型侧 | 索引重排，零对象搬运 |
| set_rows 差分 | 同键集合 → beginResetModel 计数 == 0；选择键经 StableSelection 保持 |
| Data 资产表 | 既有分页模式（≥25k SQL 分页 + LRU + epoch，#1269 身份查询）不动 |

### Tree/List

- `reconcile_widget_items` 10k 键二次同步（同键集）→ 新建项计数 == 0（第二次）；
- map_layer_tree 文档切换同键层集 → 项身份 id() 保持、展开态保持；
- explorer/导航树既有差分/分页保持。

### Context

- 选择变化不触发全 UI 重建：TaskPanelBase 同键任务列表项身份保持；Data 页选择仅更新 inspector/摘要（血缘异步）；
- 重复发布守卫：同 (well, source) 二次 `publish_well_selection` → selection_changed 恰 1 次发射；
- UIContextService 差分发射（既有，V11 新槽位同机制）。

### Refresh

- 单资产改动刷新范围：data_lifecycle 各动作走 `_refresh` 的既有作用域（表格模型差分 + 选择按 id 重锚）；井身份/血缘结果缓存避免重复遍历（32 条血缘 LRU；entity_asset_links 索引缓存）。

### GUI 线程契约（goal §9）

`AsyncQuery`（`ui/modelview/async_query.py`）：查询函数永不 GUI 线程执行；submit 递增 epoch，latest-only（新请求协作取消旧查询并即刻释放槽位）；迟到结果 epoch 拒绝；shutdown 后回调全静默。测试：三连发仅末次回调生效；shutdown(0) 后零回调。

结构断言替代裸计时（唯一宽限：100k set_rows < 10s 防退化）。

## 迁移面与量化收益（对应 01-ui-audit D2 排名）

| 表面 | 100k 数据时 V10 | V11 |
|---|---|---|
| 井点表 | 1.1M QTableWidgetItem 全量重建 | 0 项（模型按需取值） |
| 要素选择器 | 100k combo 串 × 每次过滤/排序全量重填 | ≤500 可见窗口 + 搜索 |
| correlation tops | 500k 项全量重建 | 0 项 |
| 版本时间线/检查器版本表 | 每次变更/选择全量重建 | 差分 + 选择保持 |
| 图层树/文档列表 | 每次切换 clear+rebuild | 键差分（身份/展开/滚动保持） |
| 血缘（选择时） | GUI 线程双链同步遍历 | 异步 + 缓存（UI 即时） |
| entity_asset_links | 每次井渲染全扫 | 一次索引缓存 |
| TagManager 搜索 | 每键全量重建 | 200ms 防抖 + 模型 |
