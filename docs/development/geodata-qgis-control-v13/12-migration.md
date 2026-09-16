# 12 — Migration（V13）

## 原则

additive、幂等、可重入、不伪造。旧工程打开 → 新字段合理默认（空=
UNKNOWN）；不确定信息绝不清洗成猜测值。

## 变更清单

| 载体 | 变更 | 旧行为 |
|---|---|---|
| LayerMembershipRecord | +source_asset_id/binding_kind/bound_at（可选，缺省空） | from_dict 容忍缺键；有 source_version_id 无 kind 的记录按 catalog_version 语义解释（这正是 V13 前唯一写入方的语义） |
| MappingWorkspaceState | schema_version 不变（1）；新键 additive | 旧 to_dict 无新键 → from_dict 默认 |
| DataVersionRef | +version_number（默认 0=未知） | 依赖方对 0 有兜底（注册序末位） |
| run operation 词汇 | 新增 manual_edit | 历史 working_copy_commit run 原样保留（监控集合双名覆盖） |
| port_roles | 新增 manual_edit | 开放词汇，display_for 未知回退 |
| ingest execute | 显式 skip（非重复）记入 report.skipped | 从前静默消失——报告层修正，目录行为不变 |
| dependencies 新鲜度 | 修 3 处字段误读 | 旧工程重开后 freshness 从"恒 CURRENT/UNKNOWN 的假象"变为真实判定——**这是修复不是行为回归**（此前掩盖真实 stale） |

## 无需数据迁移的原因

所有新能力是读取投影或写入路径的增量；不存在需要回填的历史数据
（旧 membership 的空绑定 = UNKNOWN 是诚实状态，回填反而伪造 provenance）。

## 回退兼容

分支不合并则一切为零影响；合并后旧二进制读新工程文件时新增键被
pydantic/dataclass from_dict 忽略（V11 已验证的 lax 读取模式）。
