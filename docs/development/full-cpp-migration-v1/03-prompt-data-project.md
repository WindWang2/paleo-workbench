# Prompt B — C++ 工程、目录、工区和数据事务

将本文件全部内容作为一个独立开发任务的输入。GOAL 模式执行，并使用 `agent/skills/goal-loop/SKILL.md`。

## GOAL

在 `feat/cpp-data-project` 独立 worktree 中交付 C++20 数据与工程首轮实现：兼容读取/回写现有 .paleo 与 V13 catalog.sqlite，保持工程/工区/版本/血缘语义，提供可验证的提交与恢复协议、pwb-inspect/pwb-migrate CLI 和供 A/C 消费的数据接口。以真实 fixture round-trip、事务故障恢复和本轮全部 Oracle 为完成依据。

范围对应总设计 P0/P2、P3 持久化一侧、CPP-20、CPP-309/601/602。数据内核不依赖 Qt Widgets/QGIS，不等候 A 的主窗口就可以完成本轮。

## 启动与隔离

1. 完整阅读共同协议 `01-parallel-development.md`、总设计、goal-loop、`CLAUDE.md` 和适用 AGENTS。
2. 工作目录 `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-data`；分支 `feat/cpp-data-project`；验证 `cpp-migration-plan-v1` 是祖先。
3. 若没有 worktree，确认目录/分支都不存在后，从主仓执行 `git worktree add --no-checkout -b feat/cpp-data-project ../paleo-workbench-cpp-data cpp-migration-plan-v1`，再按共同协议初始化稀疏 checkout 与空索引；已存在则核验复用。
4. 原生 goal API 可用时注册本 GOAL；不覆盖别的 active goal。根账本保留历史并追加 CPP-B；最多 15 轮。
5. 先检查 PR/issues 和现有 V13 模型，避免重做 #1310 已完成工作；目录规范存储按最新代码确认，不能只照抄旧 JSON-canonical 注释。
6. 三任务共享一个重型槽，零子代理，编译/测试最多 2 jobs；使用资源门禁，启动至少 8 GiB 可用内存。B 不构建 QGIS、GDAL、PROJ 或 well-log-engine。

## 唯一写入范围

`libs/domain/`、`libs/project/`、`libs/catalog/`、`libs/workspace/`、`libs/data_suite/`、`tools/pwb-inspect/`、`tools/pwb-migrate/`、`tests/cpp/data/`、`docs/development/cpp-data/`。

顶层 CMake、UI、QGIS、算法/viewer 归 A/C。提供模块独立 CMake 入口和 exported targets，不为构建方便改顶层文件。不得改已有用户工程或原始资产；所有兼容验证在测试副本上运行。

## 必查代码

- `paleo_workbench/project/`
- `paleo_workbench/catalog/` 的 SQLite schema、repositories、models、版本/运行提交、checkpoint
- `paleo_workbench/mapping_workspace/` 的 membership、source binding、stage view、input set
- `paleo_workbench/mapping/` 中 map/document/vector 持久化
- V13 `00-baseline`、`02-domain-model`、`03-data-lineage`、`04-file-lifecycle`、`06-qgis-binding`、`12-migration`、known limitations
- 现有 project/catalog/workspace/manual-edit/source-usage 测试和 fixture

## 交付步骤

### B0：兼容矩阵与接口

建立 `docs/development/cpp-data/`：baseline、contracts、schema-map、test-plan。逐字段列出当前 schema/default/alias/unknown/enum/path/null 语义；选定真实 fixture corpus 并记录来源、版本和校验值。

实现强类型 ID 与 `pwb::data` 接口，输出 `Pwb::Data` target。发布 ProjectSnapshotV1、LayerBindingV1、CommitRequestV1、CommitReceiptV1 的头文件、错误码和最小 fixture。B 的公共接口不携带 QGIS 类型，A 只通过 adapter 连接。

### B1：Project 与 Workspace

- 兼容 .paleo JSON，保持当前 schema 默认值及序列化语义；
- 未知字段在任意可扩展层级 round-trip，未支持 future schema 默认只读并诊断；
- 保留 user_vector_layers、QGIS XML、workspace、stage/input set、资源/实体和域扩展；
- 路径解析相对工程，覆盖 Unicode、Windows drive/UNC、迁移机器、丢失资源；
- workspace source asset/version/kind 绑定和 stage state 与 Python 语义一致；
- 不把全部内容降级成无类型 QJsonObject，也不把领域模型做成 QWidget/QObject；
- 写回采用临时文件 + 原子替换，并保留恢复信息。

### B2：Catalog SQLite

从实际 V13 schema 实现 DataAsset、DataVersion、DataRun 和 typed ports，保留 IDs、stage、lineage、source usage、immutable version 与文件布局。

尊重 schema version、WAL、外键及事务；数据库迁移需明确版本检查。JSON checkpoint 和 SQLite 的关系按最新代码确认。使用临时数据库测试，不连接真实工作工程执行 schema upgrade。

实现 catalog repository 查询与一致性检查：孤儿/重复/失效绑定、缺资源、旧版本使用处、run 失败/取消语义。

### B3：提交与恢复

B 拥有唯一数据 CommitCoordinator，接受 A/C 提供的 staged asset 与 provenance；不直接修改 QGIS edit buffer。

必须实现：
- operation ID 幂等；
- base version 乐观锁，冲突返回诊断；
- 新资产/版本/run/binding 一致；
- 原版本不覆盖；
- SQLite 与工程文件不能宣称单一 ACID，使用 journal 与可恢复步骤；
- staged asset 的路径、hash、文件存在性和相对工程位置验证；
- 启动恢复：未完成 journal 可幂等继续或回滚，不静默丢弃；
- failure/cancel 后无伪成功版本，能明确列出待恢复产物。

通过假的 storage 故障注入验证每个持久化阶段，同时必须有真实 SQLite + 文件系统测试。fake 测试不替代真实存储验收。

### B4：独立 CLI 和兼容测试

建立 `libs/data_suite/CMakeLists.txt` 独立构建入口。提供：
- `pwb-inspect`：只读输出 schema、workspace、binding、lineage 和诊断；稳定机器可读 JSON；
- `pwb-migrate`：默认预检/报告；实际转换须指定输入副本与输出目录，保留备份；不就地损坏原始文件；
- Python oracle runner：读取固定 fixture 得到语义 dump；复用现有解释器只读，不升级主仓环境。

对 JSON 比较不能只比较文本行序；数组业务顺序必须保留，ID/整数/浮点/null/缺省字段差异不得被过度 normalization 掩盖。

## 本轮 Oracle（全部必选）

1. `cmake -S libs/data_suite -B build/cpp-data` 经门禁配置/构建成功；不链接 Qt Widgets/QGIS/Python runtime。
2. 固定 fixture corpus 全部可读；已知字段语义与 Python dump 一致，未知嵌套字段 round-trip 保留。
3. 真实 .paleo + SQLite 保存/重开后 IDs、lineage、membership、stage、QGIS XML 不丢失；只读模式无写入。
4. 提交新版本正确；重复 operation ID 不重复生成版本，base version 冲突被拒绝。
5. 每个 journal 持久化阶段的故障注入有明确恢复结论；真实 SQLite/file 测试通过；原始资产 hash 不变。
6. Unicode、跨平台路径、future schema、缺资源、损坏 JSON/数据库有诊断，不崩溃或静默修复。
7. pwb-inspect/pwb-migrate 实际运行退出码符合文档，拒绝覆盖输入副本以外的真实工程；测试数量非零、非全部 skip。
8. 顺序 review 完成，高优先级发现修复；关键兼容/恢复测试二次复验通过；代码提交到本分支。
9. 输出 Pwb::Data 公共接口、fixture、构建消费说明、测试真实输出和 integration handoff。

## 收尾与资源释放

生成 `docs/development/cpp-data/verification.md`、`handoff.md`、`ledger.md`。明确哪些 schema/功能已验证，哪些旧业务字段目前仅 lossless-pass-through，不能宣称全部业务已迁移。报告本分支 commit、A 的消费方式、剩余 P4/P6 工作。释放自己进程与资源锁，保留 worktree。15 轮仍未通过则记录未完成和具体差距，不降低验收或启动无限 goal。
