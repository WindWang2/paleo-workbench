# 01 线 acceptance — 验收门核对

任务书验收条款 → 证据映射。全部成立后才可宣告本线完成。

| # | 验收条款 | 证据（命令/文件/退出码） | 状态 |
|---|---|---|---|
| A1 | 正常提交与重开一致 | closure_chain_query_import_commit_reopen：WC 提交→提升→close→reopen，revision/版本数/身份一致（data_catalog_closure） | ✔ |
| A2 | 失败事务不产生半成品 | closure_conflict_rollback_no_half_product：CAS 拒绝后内存回滚 + raw/ 载荷零残留 + store 修订不变（同上） | ✔ |
| A3 | 只读数据库可重复验证 | closure_corrupt_shortwrite_readonly(3)：全树只读 → 诚实拒绝非假成功；root 下环境不可能 → 显式 SKIP | ✔（root SKIP 如实标注） |
| A4 | 损坏数据库恢复 | 同用例(1)(2)：sqlite 头损坏 → isolate+manifest 重建；检查点短写 → .bak 梯恢复 | ✔ |
| A5 | 并发 revision 冲突 | closure_conflict_rollback_no_half_product：双 adapter 同库，is_stale_write 检出、B 陈旧会话被拒、重开见 A 数据 | ✔ |
| A6 | 工程切换 | closure_production_controller_chain：open A→B→A，generation 递增、身份/数据保持 | ✔ |
| A7 | 资产增删改通知真实可消费 | closure_change_feed_subscription + 生产链 feed：增/删/恢复三类事件、失败零发布、cancel 生效、身份+revision 携带 | ✔ |
| A8 | 生产调用链真实（非 fake） | closure_production_controller_chain：ProjectControllerCore × InstalledCatalogClosure 真实 runtime bag × ManagerProjectSaveApi（Qt-free，无 fake） | ✔ |
| A9 | Transaction::commit 错误传播 | sqlite.hpp/cpp 签名修复；closure_transaction_error_channel：嵌套 BEGIN 失败不再错误提交外层事务（#1398 遗留回归）；data_catalog_service oracle 28/28 零回归 | ✔ |
| A10 | 中断恢复与冲突的用户说明 | docs/specs/catalog-recovery-and-conflicts.md + CatalogRecoveryReport + closure_interrupt_recovery_report（missing_dropped 判定序验证） | ✔ |
| A11 | 关键确定性回归 ≥2 遍 | 第二轮 7/7+6/6+28/28；第三轮 7/7+6/6+28/28（同一代码状态两遍，exit 全 0） | ✔ |
| A12 | ON/OFF 闭包 | 本机无 cmake：块为纯增量（option+TARGET 双守卫）；直连构建证明 TU 独立可编译；CMake configure ON/OFF 留 CI 复放 | ✘ 未执行（如实标注） |
| A13 | 独立审查 | general-purpose 子代理独立审查（/tmp 实机编译运行），FIX_REQUIRED → 11 项全部修复复验 | ✔ |
| A14 | PR 创建、指向最新 main | base = 06211541（开工时 origin/main，PR 前重查） | ⏳ |
| A15 | Python 参考保留 | 未删除/未修改 paleo_workbench/** 任何 Python 文件 | ✔ |

## 未执行/受限项（如实声明）
- A12：本机无 cmake/ctest（与 #1398 披露一致）；验证通道为 g++ 直连 + 资源门
  Exec。CMake 级 configure/CTest ON/OFF 由 CI 复放（测试注册随 PR 提交）。
- A3 部分：root 身份下 chmod 不生效，该子场景显式 SKIP（测试内打印），非断言放宽。
- 磁盘满（ENOSPC）真实注入未做；以 短写（截断文件）+ 权限失败 + CAS 冲突三类
  真实故障注入覆盖同族回滚路径。
- 性能：本线不做（14 线职责）。
