# 06 — Inspector 2.0 (V11)

## 实体覆盖（goal §11）

| 实体 | V10 状态 | V11 |
|---|---|---|
| **DataAsset** | InspectorPanel（Data 页）6 页签全覆盖 | 保持（版本表迁移模型；血缘异步加载见 07） |
| **Well** | 仅 name/X/Y/KB/TD + 联动状态 | + 井 ID（稳定标识）、+ 关联数据角色概要（`well×N` 计数，缓存口径） |
| **Version** | 无独立检查器（活在对话框/血缘树里） | `WorkstationInspector.show_version`：阶段（词表徽章渲染）/版本号/创建时间/SHA-256（截断）/父版本计数/生成 Run/来源/下游/回收站标记；字段缺席=「—」 |
| **MapLayer** | 瘦（类型/作用域/seam 行） | 保持结构；seam 行已按 state_language 词表渲染（V6+）；编辑门禁行由域状态 seam 提供（V10 M11） |
| **Run** | 无 | `WorkstationInspector.show_run`：Run ID/操作/状态（任务词表徽章）/输入输出版本计数/模型/参数/起止耗时 |
| 其它（project/horizon/seismic/resource/curve/feature/factor/map_product） | 各自 show_* | 保持；map_product 过期/就绪行继续由宿主权威注入 |

## 去重

- 资源身份行（name/type/format/path/status）此前 4 处实现（WorkstationInspector/DataDetailPanel/DataReaderPanel/InspectorPanel）——数据资产的主检查器是 InspectorPanel，其余表面维持各自轻量呈现（页面职责不同），**措辞与缺省「—」** 已在同一约定下；完全合并属结构性重构，记入限制。
- 缺失值渲染统一 `_readonly` 的 missing 属性习惯；空选择文案统一为各面板一句（不再多种变体并存——01-ui-audit I 项）。

## 性能（D3 修复）

井的 entity_asset_links 全量扫描此前**每次渲染**执行；V11 按 `(工程对象 id, links 长度)` 缓存轨迹索引与角色计数——追加/移除即失效；就地改写单条 role 的极端情况不覆盖（展示层口径，权威在工程模型）。

## 接线

- explorer/血缘树/任务中心可投递 `{"kind": "version"|"run", "object": ...}` payload 给 `WorkstationInspector.show_payload`（新分发分支）。
- Data 页 InspectorPanel 版本行选择 → 总线 `selected_version_id`（03-ui-context）。

## 测试

- `tests/test_workstation_inspector.py`：井联动状态真实数据（含缓存失效——追加 link 后即见）。
- `tests/test_v11_visual_qa.py`：`inspector_version_payload` / `inspector_run_payload` 场景（结构断言：标题含「版本」/「Run」）。
