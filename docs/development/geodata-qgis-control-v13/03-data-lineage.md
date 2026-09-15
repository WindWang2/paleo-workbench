# 03 — Geological Data Lineage（V13）

## 1. 用户可回答的问题（Goal §4 → 实现）

| 问题 | 回答路径（生产代码） |
|---|---|
| 这个文件为什么存在/谁生成/什么时候 | ExplainService.explain_version（run/generator/时间）+ manual_edit run（V13 前为黑洞） |
| 输入是什么 | run.input_version_ids + typed ports（含 manual_edit 输入端口） |
| 现在仍有效吗 | ImpactService.is_stale/downstream_stale + mapping freshness（V13 修复真实 adapter 路径） |
| 能否重算 | explain 的 regenerable（manual_edit 现在也 regenerable=False——人工修改按定义不可由算法重放，但 provenance 完整） |
| 能否删除 | delete_impact + cleanup_eligibility + **V13 impact 预览门**（remove 前 UI 强制过目） |
| 删除影响什么 | TrashImpactSummary（血缘 + 地图用途聚合） |
| 有没有地图在用 | **usages_of_version/asset（V13）**：图层/输入集/成图产品/run |
| 最终成果是否依赖 | usages 里的 map_product_output/compilation_input |

## 2. 正反向闭环（§2 Goal 闭环图 → 代码）

正向（文件→地图）：ingest(plan)→DataVersion→run 链→factor task→
register_layer(pin)→LayerTreeSnapshot→QGS mirror→composition/map product
（OUTPUT version）。每跳都有 id 引用，无 filename/tag 猜测。

反向（地图→文件）：QGS 树选中→doc_id→membership.source_version_id→
get_version/get_run→Inspector「数据来源/生成方式/上游输入/校验和」行
（`layer_domain_status` seam）；成图→map_products→run inputs→RAW。

## 3. 节点/关系词汇（投影层，非新表）

节点：Entity / DataAsset / DataVersion / DataRun / WorkingCopy /
Mapping Layer / Compilation Input Set / Map Product / Export Artifact。
关系实现载体：
- belongs_to/role_of → entity_asset_links；
- version_of → DataVersion.asset_id；supersedes → current pointer + parent ids；
- derived_from → parent_version_ids；generated_by → version.run_id；
- input_of/output_of → run io lists + ports；
- working_copy_of → working_copies 表；
- used_by_layer → membership.source_version_id（V13 完整化）；
- referenced_by_map → compilation input set entries + factor task 指针；
- exported_as → export run + OUTPUT version。

## 4. 有界性

- 血统链：build_lineage_chain（max_nodes 5000，truncated 标志）；
- 影响面：downstream_stale（MAX 20k/2k）+ usages（run 级 100 截断）；
- UI：LineageExplorerDialog 懒展开（25/1000）；本 Goal 未新增全量绘制路径。

## 5. E2E 保证

`tests/test_v13_cross_workspace_e2e.py` pin 了 §24 十八步闭环（含
stale 传播→重算→重绑→save/reopen 不变性）。该测试同时是三个生产
缺陷的回归锚（见 13-review-findings）。
