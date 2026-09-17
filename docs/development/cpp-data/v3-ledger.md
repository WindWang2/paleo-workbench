# CPP-B v3 Ledger（codex/cpp-v2-data）

目标与 Oracle 见本目录 `v3-contracts.md` / prompt B（五线安排）。上限 15 轮。
重型操作经共享槽（本机同等契约门禁，见 v3-verification §6）。

| 轮 | 改动 | 验证结果 | 判定 | 下一步 |
|---|---|---|---|---|
| V3-1 | 侦察：账本（CPP-B B-1~B-4、CPP-D R1–R16）、总设计、v1 contracts、现有源码通读（coordinator/repository/manager/workspace/tests/oracle）；建 worktree `codex/cpp-v2-data`@53e22b67（sparse 39 MiB，树干净）；工具链 cmake 4.4.3/GCC 16.2.1/python3.14+pydantic2.13；pwsh 缺失 → 记录并备同等门禁 | worktree/branch/基线核验通过；Python oracle 可用性实测 | 通过 | 公共头+v3 契约先行 |
| V3-2 | 公共契约：run_contracts.hpp / commit_coordinator.hpp 扩展（PublishRequestV1、JournalKind、RunCompleted 相位、run API）/ session.hpp / contracts.hpp kVersion=3；Result<T> 去 default-constructible 约束；ids.hpp `<cstdint>`；v3-contracts.md 冻结；单 TU 语法探针 | 头独立编译通过；提交 **82430eca** 并公布 | 通过 | 实现主体 |
| V3-3 | 实现：repository 增 publish_result_transaction/finish_run_transaction（单事务）；run_coordinator.cpp（登记/发布/终态/恢复/回滚）；session.cpp；共享助手 coordinator_detail.hpp；commit() 增 pending 闸门+幂等键类型守卫+回滚后重试语义（v1 死代码意图转正）；CLI 查询模式+--recover；pwb-data-loop 例子；readback_v3.py；5 个新测试文件 | 对象级编译全绿；门禁内 configure exit 0；build 暴露基线 MSVC 专属代码 → 修 gmtime/windows.h/ldd/cli 引号/路径字面量（V3-4） | 通过（源码级） | 门禁内构建+全量测试 |
| V3-4 | Linux 可移植性修复（§5 of v3-verification）；oracle_resolve.json 本机再生成（catalog/model dump 逐字节不变）；例子双 run 语义修正（manual_edit run 关联编辑、算法 run 单结果——同 run 混用两路径被 publish 正确拒绝） | 门禁内 build exit 0；ctest 首轮 11/19 → 修 journal 漏写 new_version_id（真 bug）、回滚后重试语义、例子 staged 目录、readback immutable 零足迹（-shm 创建根因） | 通过（迭代） | 全量 ctest |
| V3-5 | 全量 `data.*` 19 项门禁内运行 + 关键链路复验 | 发现并修复只读 SQLite 打开创建 `-shm/-wal` 破坏零足迹语义（`Database::open` ReadOnly 改 `immutable=1`，活跃 WAL 时回退保正确性）；一次构建输出被 grep 过滤掩盖门禁拒绝（如实记录）；**ctest 19/19 exit 0（0 失败 0 skip）；关键链路 9 项复验 9/9 exit 0** | 通过 | 交付文档收口 |
| V3-6 | v3-verification/v3-handoff/v3-ledger 定稿；实现提交 **a228bafb**；最终 handoff SHA 公布 | 文档与本文件一致；SHA 公布于 handoff | 通过 | 交付 |

恢复命令（若中断）：

```bash
cd /home/kevin/projects/paleo_project/.worktrees/cpp-v2-data
git status                     # 应干净；分支 codex/cpp-v2-data
cmake --build build/cpp-data --parallel 2
ctest --test-dir build/cpp-data -R "^data\." --output-on-failure
```
