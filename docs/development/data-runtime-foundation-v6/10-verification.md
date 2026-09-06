# 10 — Verification

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6` · 测试环境：Windows + 主 checkout .venv（Python 3.12.13 / pytest 9.1.1 / PySide6 offscreen）

## 1. 新增测试（7 个文件，44 例）

| 文件 | 覆盖 |
|---|---|
| test_catalog_lazy_open.py (11) | 懒/急切等价、身份稳定、页/聚合/一跳 lineage 预热即用、未知 id 不触发物化、变更内联物化、warm 竞态、零变更关闭不写清单、打开预算门 |
| test_catalog_transaction_cas.py (5) | TOCTOU 窗口模拟拦截、无范围 reconcile 拒删外来行、rebuild 守卫、**真·子进程提交**被拒且存活、批原子性 |
| test_catalog_gc_registration_race.py (5) | 对抗性 register‖sweep（放置后提交前确定性驻留；**经临时还原 bug 验证具备杀伤力**）、陈旧 plan 报告 sweep、租约 TTL 过期、blob 存活、#1218 锁释放证据 |
| test_catalog_working_copy_lifecycle.py (7) | 复用保编辑、重名身份、copy 后崩溃枚举、提交中崩溃两分支证据裁决、显式丢弃、并发收敛、save-as 孤儿行 |
| test_project_recovery_v6.py (6) | 暂时不可读绝不回退、隔离+记录往返落盘、中断保存恢复、双损坏诚实失败、良性 touch、真实外来写入拒绝 |
| test_runtime_session_and_cancel.py (6) | 会话令牌语义、属性回调守卫、chunk 取消时机、verify_integrity cancelled、调度器超越、导出检查点 |
| test_catalog_scale_v6.py (3) + test_resource_governance_convergence.py (5) + test_provenance_and_identity_v6.py (5) | 规模门/热身期查询正确性/规模下冲突；env 零变化/作用域恢复/池宽收敛；幽灵检测+幂等修复/basename 拒绝/尺寸证据绑定/迁移 stat 回填 |

## 2. 回归

本轮触面全量回归 **223 passed, 1 skipped**（catalog service/db/gc/crash/lazy/CAS/工作副本/恢复/会话/治理/溯源 + adapter e2e + batch dedup + seismic + scheduler + controller + scale v6）。

## 3. 评审轮（§16，独立 agent，全 diff 295fabc3..5078bfec）

- R1 数据正确性/崩溃一致性：0 P0；2 P2 已修（预热漂移空回退、恢复先隔离后验备份 + 证据残留）+ rowid 序。
- R2 并发/架构/事务边界：1 P1 已修（mapping_page 守卫读不存在属性）；4 P2 已修（转码守卫对称、超越 on_cancel、zombie 占位遮蔽、漂移空回退）；死锁矩阵/锁序/warm 竞态/CAS 边界/"第二权威"五项验证通过。
- R3 性能/对抗/恢复：3 P1 已修（OUTPUT 租约前缀、import_raw 无租约、fail-open 工作副本）+ 测试空转重写并证明杀伤力；暖卫/CAS 开销/批量租约成本/隔离碰撞等验证通过。
- 未采纳为代码修复的 P2/P3 见 11（均有理由与边界说明）。

## 4. main 既有失败（与本分支无关，pristine main 复现）

e01cc3cb 引入的 `_scan_managed_raw/_scan_external_by_path` 悬挂引用（adapter_e2e ×3、batch_dedup ×2——**本分支已顺手修复**）；`test_mapping_crs_idw::kriging_dispatch`（#1227 克里金家族，范围外）；`test_interchange_crash_consistency::package_crash_mid_build`（范围外）。

## 5. 显式排除

100GB 地震体支持/基准/优化（硬边界）；#1213–#1217、#1226、#1227、#1230（井域/算法/CI 家族，00-baseline 映射）。
