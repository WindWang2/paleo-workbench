# CPP-B v3 Handoff（A/C/D/E 消费指南）

分支 `codex/cpp-v2-data`；基线 `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf`。
契约：`v3-contracts.md`（SHA 见 §5）。验证状态：`v3-verification.md`。

## 1. 交付物与 SHA

| 交付 | SHA |
|---|---|
| v1 基线（data 14/14 合入） | `53e22b679ea3181d4e2c2bca8d42ca272c00dfbf` |
| v3 公共契约头 + v3-contracts.md | `82430eca8f64c37adfbb7414662a68e4423d869d` |
| v3 实现 + 测试 + CLI + 例子 + oracle 脚本 | `a228bafbccd2a41393d319e7f18c24abf960b9cc` |
| 最终收口（含本文档与验证报告定稿） | 见 §5（交付时公布） |

## 2. A 如何消费（v3 全链）

```cpp
#include "pwb/data/contracts.hpp"   // kVersion == 3 钉版本

// 只读打开（零写入：工程文件与 SQLite 目录均不落任何文件）
pwb::data::DataFacade facade(project_file);
auto snapshot = facade.open_snapshot();   // Result<ProjectSnapshotV1>
// → layer_bindings / workspace / resources / catalog_assets|versions|runs /
//   catalog_findings / diagnostics / read_only

// 可写会话（显式；future-schema 工程在此即被拒绝）
auto session = pwb::data::WritableSession::open(project_file);
if (!session) { /* session.error() */ }
auto& coordinator = session.value().coordinator();
auto& document   = session.value().document();

// ① 编辑提交（staged 文件 + 乐观锁 + 可选 rebind + 可选 manual_edit run）
pwb::data::CommitRequestV1 edit;          // 见 v1 contracts §4
auto receipt = coordinator.commit(edit, document);

// ② 注册算法 run（ durable "running"；幂等于 run_id）
pwb::data::RunRegistrationV1 reg;
reg.run_id = pwb::domain::RunId(pwb::domain::make_id("run_"));
reg.operation = "seismic.coherence_c3";
reg.generator = "coherence-c3@0.7.0+build123";
reg.parameters = {{"window_ms",12},{"units","ms"}};   // JSON/POD 原样
reg.input_version_ids = {base_version};
auto run = coordinator.register_run(reg);

// ③ 发布单结果（新建资产无需预造；run 完成于一切 durable 之后）
pwb::data::PublishRequestV1 pub;
pub.operation_id = pwb::domain::OperationId(pwb::domain::make_id("op_"));
pub.run_id = reg.run_id;
pub.new_asset_name = "coherence result";  // 或 target_asset_id 追加版本
pub.products.push_back(staged);           // 恰好 1 个，否则写入前拒绝
pub.result_metadata = {{"units","ms"},{"approximate",false}};
auto published = coordinator.publish_run_result(pub, document);

// ④ 算法失败 / 用户取消（终态；不可改写；已有输出则拒绝）
coordinator.finish_run(reg.run_id,
                       pwb::data::RunTerminalStatus::Failed,
                       {{"error", "kernel timeout"}});

// ⑤ 恢复（唯一入口；pending 阻塞冲突写入，journal 不自动删除）
pwb::data::RecoveryReportV1 report = session.value().recover();
```

参考实现（可直接运行的消费样例）：`libs/data_suite/examples/data_consumer_example.cpp`
（目标 `pwb-data-loop <project.paleo.json>`，完成 打开→基线→编辑→双 run→发布→
关闭重开→验证，打印 JSON 摘要；`data.consumer_loop` 对真实 fixture 副本连跑两轮）。

fixture：`tests/cpp/data/fixtures/typical/`（有效资源路径 + 版本绑定 + 真实
catalog.sqlite；其 membership 含故意未知的 asset id——审计路径数据，消费侧应像例子
一样校验绑定可解析后再选目标）。

## 3. 结果消费（A/D：字节 + 元数据边界）

```text
pwb-inspect --project <f> --provenance <version_id>
→ { version:{...含 result_metadata 原样...}, file:{path,resolved,exists,
   sha256_measured,size_bytes_measured}, run:{operation,generator,parameters,...},
   lineage:{parents:[...]} }
```

B 拥有字节与事务（payload 不可变、hash/size 入库、目录 `{stage}/{asset}/{version}/`）；
数值编码/解码归 A（`result_metadata.units/approximate/encoding` 由调用方写入、B 原样
往返）。查询模式全部只读（`immutable` SQLite 打开，零足迹）。

## 4. 运维：恢复与诊断命令

```bash
# 只读诊断（任何模式都不写盘）
pwb-inspect --project P.paleo.json                 # 快照 + 审计 + 诊断
pwb-inspect --project P.paleo.json --asset asset_x # 资产 + 版本列表
pwb-inspect --project P.paleo.json --run run_x     # run 行 + ports + 参数
pwb-inspect --project P.paleo.json --version ver_x # 版本行
pwb-inspect --project P.paleo.json --provenance ver_x

# 显式可写恢复（唯一恢复入口；退出码 6 = 仍有 pending，见 JSON 报告）
pwb-inspect --project P.paleo.json --recover

# 全量测试（共享重型槽内，≤2 jobs）
cmake -S libs/data_suite -B build/cpp-data -DBUILD_TESTING=ON
cmake --build build/cpp-data --parallel 2
ctest --test-dir build/cpp-data -R "^data\." --output-on-failure
```

journal 位置：`<project>.artifacts/metadata/commit_journal/<operation_id>.json`
（`kind` 区分 `edit_commit`/`run_publish`；相位含 v3 新增 `run_completed`）。

## 5. 交接状态与边界

- 已交付：上表 SHA；19 项 `data.*` 全绿（v3-verification §4）。
- 未迁移（勿当已具备）：GC/dedup 全套、entity view/分页、Unicode 检索归一化、
  models/model_versions 注册表、staging_leases 写路径、通用多产物原子发布、
  catalog.json checkpoint 写出（兼容性由 oracle readback 证明，见 v3-verification §7）。
- 平台：本轮 Linux/GCC 门禁内验证；MSVC 分支保留 `#if` 守卫，未在 Windows 重跑。
- B 不链接算法库；C/E 对象到 `RunRegistrationV1/PublishRequestV1` 的转换在 A 的
  `libs/application`（跨域转换只放 A）。
