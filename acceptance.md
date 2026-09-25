# Acceptance — ws0 数据治理闭环

## 核心验收（headless，tests/cpp/data/governance_ops_test.cpp）

- [ ] link 创建后 `.paleo.json` 持久（重开读取断言）；重复 upsert 幂等
- [ ] 单链接删除只删目标行；角色编辑保留 is_primary/ordinal/note；未知井拒绝；空角色拒绝
- [ ] link 到 trashed 资产拒绝；trash 后 links 保留；restore 后 links 可解析
- [ ] tags add/remove/bulk 正规化（fold+空白折叠）持久；重开一致
- [ ] impact：直接下游计数 ≥1（派生子版本）；无下游为 0；cycle 输入不挂（seen 守卫）
- [ ] trash unknown id / restore unknown id 报错不崩
- [ ] save→close→reopen 三方一致（JSON links + sqlite tags/trash）

## 规模（tests/cpp/data/governance_scale_test.cpp）

- [ ] 10 万资产 + 标签 SQL 查询/过滤预算内；链接扫描 10k→40k 增长近似线性（无 O(N²)）

## UI（tests/cpp/platform/test_data_governance.cpp，offscreen）

- [ ] snapshot 行携带 tags/role；filter_fn：tag and/or、role 等值、trash node_type 空集
- [ ] LinkWellDialog 选中井→应用→文档落盘；解除→行消失
- [ ] SetRoleDialog 修改角色→文档落盘
- [ ] TagsDialog 添加/移除→sqlite 落盘（重开可见）
- [ ] TrashDialog 列表反映 trash；恢复→live 回表
- [ ] DataLineagePanel 第三页签在有下游时非空
- [ ] bus republish_current 重发 current_asset_changed
- [ ] 移除流程 impact 预检 seam：无依赖直删 / 有依赖要求确认（注入 decision）

## 命令（registry evaluate）

- [ ] 无工程：五命令不可用（"需要先打开工程"）
- [ ] 有工程无选择：link_well/set_role/tags/impact 不可用；trash 可用（工程级视图）
- [ ] 有选择：全部可用且执行真实路径

## Review 收敛

- [ ] Round A（数据一致性/事务/血缘/删除恢复）无新 P0-P2 actionable
- [ ] Round B（UI 状态/规模/生命周期/错误路径）无新 P0-P2 actionable

## PR

- [ ] base/head SHA、disabled→real 清单、模型/RAW 保证、性能证据、本地测试清单、未执行项、overlap、residual risks
