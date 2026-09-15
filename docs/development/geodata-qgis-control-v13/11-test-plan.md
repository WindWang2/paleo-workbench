# 11 — Test Plan（V13）

## 分层与文件

### Domain（tests/test_v13_domain_contracts.py，19 用例）
manual_edit run（预订/端口/部分提交/簿记失败回退/零提交 failed）；
业务角色→端口映射；membership 绑定字段 roundtrip + 旧工程缺省；
usages_of_version/asset 聚合 + catalog run 有界；stage 状态保留
（显式目标恢复/死图层重算/覆盖层 roundtrip）；intermediate policy
（登记标志/EPHEMERAL 不入库/未知兜底/词汇正交性）；order_key roundtrip。

### Data Manager（tests/test_v13_ingest_plan_ui.py 4；test_v13_impact_and_usage_ui.py 6）
IngestPlanDialog 构建/编辑/执行/幂等重跑（qtbot + 真实 service）；
impact 聚合（血缘+地图用途）/孤立资产静默；remove_assets 门
（拒绝→零变更；无影响→静默过）；Inspector 用途行渲染。

### QGIS（tests/test_order_contract_v13.py 4；test_v13_layer_data_source_ui.py 3）
见 07 的矩阵；图层来源行（绑定显示来源/run/输入/校验和；未绑定不显示；
manual_edit 标注）。

### Harness（tests/test_v13_harness_data_lineage.py 7）
ingest_plan 只读零副作用；ingest 登记+绑定+幂等+decisions 覆盖；
working copy create/commit 带 manual_edit run；map_usage；
recompute_stale dry-run；权限/上下文门（executor 层既有测试覆盖）。

### Cross-domain E2E（tests/test_v13_cross_workspace_e2e.py 1×18 步）
§24 全链：ingest→bind→primary→processing→intermediate→derived→
上图绑定→重排→编辑→manual_edit 提交→血缘回溯→上游升版→
catalog stale + mapping STALE→重算→重绑→usage 反查→save/reopen 不变。

### 修改的既有测试（契约变更，非"改绿"）
test_lifecycle_registration_gaps：operation 断言
working_copy_commit → manual_edit（同一 UI 流程的新统一命名；
零提交幽灵语义由 audit/repair 集合同时覆盖两个旧新名）。

## 运行配方

```bash
# fast 腿（本 worktree）
QT_QPA_PLATFORM=offscreen PYTHONPATH="<wt>/native/qgis_render_bridge" \
  <venv>/python -m pytest tests/test_v13_*.py tests/test_order_contract_v13.py -q
# qgis 腿（追加）
PALEO_QGIS_BUILD_DIR=<main>/native/qgis_render_bridge/build/qgis-vendor
```

## 回归红线

- E2E 是三个生产缺陷（见 13）的回归锚，不得弱化断言；
- ingest 幂等重跑断言（skipped 引用既有资产）防重复导入回归；
- 信封往返组序断言防 #1154 类注册表桥注销回归。
