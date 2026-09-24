# Task Plan — ws0 数据治理闭环（link_well / set_role / tags / impact / trash）

## Goal (Oracle)

在最新 origin/main（c5b95f5e6）上把 ws0 五个 disabled 命令变为真实治理闭环：
资产↔井关联、角色编辑、标签、下游影响分析、软删除回收站——全部走既有持久化权威
（links/role → 项目 JSON via WritableSession；tags/trash → catalog.sqlite via
CatalogClosureAdapter），写后真实刷新、reopen 一致、RAW 不可变、失败可见。

## DoD（全部满足才算完成）

1. 五命令 register_disabled → register_real，applicability 动态（project/selection）。
2. link/unlink/set_role 写入 `.paleo.json` entity_asset_links（单链接删除与角色编辑内核新增）。
3. tags 走 TagStore（正规化复用 catalog::normalize_tag_name），过滤（and/or）接入资产表，标签候选随行集刷新。
4. impact 复用 delete_impact_summary，进 DataLineagePanel 第三页签（两实例/底签同步）。
5. trash 走 trash_asset/restore_asset；软删保留 entity_asset_links；回收站对话框可查看+恢复；破坏性操作显式确认 + impact 预检；decision seam 可注入供测试。
6. 治理状态 reopen 一致（save→close→reopen 测试）；RAW payload 不被治理动作改写（软删只搬目录不改内容）。
7. headless core tests + Qt offscreen tests + 100k scale smoke 全绿（经资源门 -j2）。
8. 两轮独立 review（A：数据一致性；B：UI/性能/错误路径）无新 P0/P1/P2 actionable finding。
9. PR 已创建（base/head SHA、disabled→real 清单、数据模型、RAW 保证、性能证据、本地测试、未执行项、overlap 分析、residual risks）。

## 实施步骤（commit 划分）

1. **commit 1 — domain kernel**：`libs/data_suite` entity_identity 新增
   `remove_entity_asset_link` / `set_link_role`；facade snapshot 增 tags 携带；
   `AssetSelectionBus::republish_current()`。
2. **commit 2 — governance service**：`apps/.../data_governance_service.{hpp,cpp}`
   （links via WritableSession；tags/trash via 短生命周期 adapter；读取函数）。
3. **commit 3 — dialogs/panel**：`data_governance_dialogs.{hpp,cpp}`
   （LinkWellDialog/SetRoleDialog/TagsDialog/TrashDialog + impact 确认）；
   DataLineagePanel 第三页签（影响分析）+ m5 reparent 同步。
4. **commit 4 — workspace wiring**：closure_preview_adapters 填 tags/role 列；
   `data_governance_install.cpp`（tag 过滤/候选/管理、remove→trash 流、多选跟踪、
   filter_fn 扩展 tags/role/trash）；从 closure_preview_install 一行接入。
5. **commit 5 — ribbon wiring**：五命令 disabled → real（最小 diff）。
6. **commit 6 — tests/docs**：tests/cpp/data/governance_ops_test.cpp、
   governance_scale_test.cpp；tests/cpp/platform/test_data_governance.cpp；
   findings/task_plan/progress/acceptance 更新。

## 明确不做

- 不新建平行 metadata DB；不接自动物理 purge；不改 #1492 冻结的表格/工具条外观
  （只接既有信号/候选 seam）；不动旧栈（ui_controllers）行为；不做 100G 地震体专项。
