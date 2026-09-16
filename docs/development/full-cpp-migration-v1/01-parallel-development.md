# 三线并行开发协议

本目录的三个 prompt 可以分别交给三个独立任务。它们从同一 Git 标签出发，各自在独立 worktree 开发。三个任务先交付可验证的第一轮模块成果；完整迁移的 P0–P7 继续按总设计推进，第一轮通过不代表整个 Python 产品已经替换。

## 基线与启动

- 代码起点：`671ee426679156098133847c186fda97722c43ab`（V13 已合并）。
- 计划标签：`cpp-migration-plan-v1`。标签覆盖原始设计、三份 prompt、此协议、goal-loop 技能副本和资源门禁脚本。
- 标签只包含已提交代码与本次计划文件。主工作区未提交的 `composite_document.py` 修改与 scratch 文件不在标签中。
- 用户要求的三个开发 worktree 见下表。已有 worktree 必须核对路径、branch、基线后复用；没有时从此标签创建。禁止覆盖同名目录。
- skill：`agent/skills/goal-loop/SKILL.md`，已从用户本机读取并复制完整正文；不需要在线安装。
- 先阅读本协议、总设计、自己的 prompt、`CLAUDE.md`、适用 AGENTS 和相关 ADR。
- 开始前只读检查最新 PR/issues/远端提交，识别重叠；不要自动把新的 main 合入这三个固定基线。使用 `git fetch --no-recurse-submodules origin` 后逐项记录差异。

| 任务 | 分支 | 本机 worktree | Prompt |
|---|---|---|---|
| A 平台/QGIS | `feat/cpp-platform-qgis` | `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-platform` | `02-prompt-platform-qgis.md` |
| B 数据/工程 | `feat/cpp-data-project` | `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-data` | `03-prompt-data-project.md` |
| C 算法/可视化 | `feat/cpp-science-viz` | `C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-science` | `04-prompt-science-viz.md` |

若以后需要重建缺失的 worktree，使用各 prompt 的 `--no-checkout` 命令；仅针对本次新建、文件目录只有 `.git` 且索引为空的 checkout，依次执行下面两步（`WORKTREE` 替换为表中的明确路径）：

~~~text
git -C WORKTREE sparse-checkout set --cone --skip-checks .github agent docs paleo_workbench native tests scripts libs apps cmake tools geo-viz-engine well-log-engine
git -C WORKTREE read-tree -mu HEAD
~~~

第二步用于填充 `--no-checkout` 的初始空索引，必须先核对是刚创建的空目录，不能对已有用户修改的 worktree 使用。最后验证 `git status --porcelain` 无输出；这一步缺失会把空索引显示成大量待删除文件，而不是真实开发状态。

## GOAL 与 goal-loop 执行协议

每个 prompt 本身是一个完整开发 GOAL。宿主支持原生 goal API 时，先读取当前 goal：无 active goal 才创建；已有同一目标就继续；已有其他目标不能覆盖。只在所有本轮 Oracle 成立时标记 complete，不因 token 少、资源不足或生成了代码就标记完成。没有 goal API 的宿主，使用 GOAL 模式和 goal-loop 账本；不要编造不存在的 `$goal`/`$loop` 命令或 API 调用结果。

启动时按 skill 声明目标、Oracle、15 轮上限。每轮读账本 → 评估差距 → 单一聚焦改动 → 实际验证 → 追加记录 → 判定。独立 worktree 根目录已有历史 `.goal-loop-ledger.md`，保留历史并追加自己的命名区段；最终把本任务区段同步到自己拥有的 `docs/development/cpp-<track>/ledger.md`，不要把三个根账本的分叉互相合并。

执行资源上限来自用户“防止资源占用”的要求，优先于技能中可能被理解为无限循环的措辞：

- 每任务最多 15 轮，无 token 最低消耗量，无“至少跑 N 小时”要求。
- 到上限仍未通过：保存真实状态、失败证据与恢复步骤，报告“未完成/达到上限”；不得自动续开下一组 15 轮、复制 goal 或开后台循环。
- 第 3–4 次同类失败列出三个不同假设；第 5–7 次更换工具/拆分验证；第 8 次重新核对需求。不得原样重跑整套测试。
- skill 要求的最终复验只重跑关键确定性测试两次，不把 QGIS 全量构建或整库 pytest 重跑两次。
- 缺 SDK、权限、可用内存等真实外部条件时，先完成独立源码/契约工作；仍无可推进项则依据 skill 记录 `<loop-abort>` 或 `<loop-pause>`。状态保持未完成，宿主 blocked 的触发必须遵守宿主 API 的规则。
- 不创建定时任务、自动唤醒、无限轮询或后台自重启。

## 资源预算：三任务共用

当前机器约 32 GB RAM，准备阶段实测可用内存约 1.8 GB，因此启动开发不等于立即允许编译。

1. 最多三个顶层开发任务；每个任务不再派生 subagent，也不运行嵌套代理 CLI。审查由当前任务顺序执行。
2. 三个 worktree 共用一个重型任务槽：CMake configure/build、ctest、QGIS/Qt 构建、整组 GUI/性能测试串行。通过 `scripts/cpp-migration/Invoke-ResourceGate.ps1` 取得同一主仓 Git common-dir 下的文件锁。
3. 编译和测试均最多 2 jobs；设置 CMake/CTest 及 OpenMP/BLAS 线程上限，禁止 `-j` 无上限、`pytest -n auto`、并行链接多个大目标。
4. configure/build/test 启动时可用内存至少 8 GiB；QGIS/GDAL/PROJ 全量构建至少 12 GiB。门禁只在开始时检查内存，不是操作系统硬内存配额；运行中内存不足时应在安全边界暂停，记录自身进程，不能杀掉其他工作。
5. 锁繁忙或内存不足返回 75。先做独立轻量工作，不把 75 当测试成功或代码缺陷；连续两次资源拒绝且无独立工作则写账本后等待外部条件，不能轮询烧资源。
6. 每次只启动一个前台构建/测试。跟踪进程 ID；不让工具超时后在后台遗留编译或测试。释放资源锁前确认本次子进程已结束。
7. 不递归初始化所有 submodule。A 是 QGIS SDK 唯一构建者，C 是 well-log-engine SDK 唯一构建者；B 无需编译这些 SDK。
8. 主仓 `third_party/qgis`、已固定的 submodule 可作为只读参考。构建输出只放自己的 worktree；不能写主仓构建目录。发布给其他任务使用的 SDK 必须是已完成的 install 树，带 commit/Qt/compiler/CRT/config manifest，消费方只读，禁止共享可写 build tree。
9. 稀疏 worktree 省去每份完整 QGIS 源码和旧构建产物。需要额外路径时按需扩展 sparse-checkout；不因稀疏缺失而误判源码已删除。子模块需要数据时按主仓 gitlink 的固定 SHA 初始化，不升级远端 main。
10. 不重复复制 `.venv`、数 GB 数据、DLL 树；Python oracle 可使用主仓现有解释器只读运行，禁止向共享环境 pip install/upgrade。

资源门禁示例（PowerShell；工作目录是自己的 worktree）：

~~~powershell
# Probe 只报告锁和内存是否允许，不执行编译。
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Probe

# 模块独立构建：SourceDir 和 BuildDir 替换为本 prompt 的目录。
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Configure -SourceDir ./libs/data_suite -BuildDir ./build/cpp-data -CmakeArguments @('-DBUILD_TESTING=ON')
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Build -BuildDir ./build/cpp-data
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Test -BuildDir ./build/cpp-data -TestRegex '^data\.'
~~~

门禁必须保留所有实际退出码。Configure 不得借 custom target 绕过编译限流；长时测试设置每项 timeout。其他重型命令由 A 扩展统一门禁后使用，不允许 B/C 各造一个互不协调的锁。

## 文件归属

| 归属 | 唯一可写范围 |
|---|---|
| A | 顶层 `CMakeLists.txt` / `CMakePresets.json` / `vcpkg.json`；`cmake/`；`apps/`；`libs/qgis/`；`libs/ui/`；`libs/application/`；`libs/tool_policy/`；`tests/cpp/platform/`；`.github/workflows/cpp-*.yml`；`scripts/cpp-migration/`；`docs/development/cpp-platform/` |
| B | `libs/domain/`；`libs/project/`；`libs/catalog/`；`libs/workspace/`；`libs/data_suite/`；`tools/pwb-inspect/`；`tools/pwb-migrate/`；`tests/cpp/data/`；`docs/development/cpp-data/` |
| C | `libs/algorithms/`；`libs/workflow/`；`libs/visualization/`；`libs/science_suite/`；`tests/cpp/science/`；`docs/development/cpp-science/` |
| 固定参考 | 总设计、本协议、三个 prompt、复制的 goal-loop skill、现有 Python、旧 native bridge、旧 CI、vendor/submodule gitlink |

跨归属变更必须先写清接口变更建议，由文件 owner 实现。不得为了通过编译直接改另一条线的文件。读取另一条线已提交接口/报告是允许的。新 C++ 实现优先新增文件；旧 Python 生产路径、旧桥和已合并 V11–V13 保留到集成验收。

## 接口握手 v1

不在第一轮强推跨 DLL 二进制 ABI；各模块同一编译器/CRT、C++20 编译，初期内部静态链接。以下名称和语义作为冻结契约，具体头文件分别由 owner 实现；依赖模块未出现时，用自己测试目录里的测试替身验证接口，不能在生产库复制另一条线的实体。

| 契约 | Owner / 输出 | 消费者 | 固定语义 |
|---|---|---|---|
| ProjectSnapshotV1 | B：`pwb::data`，`Pwb::Data` | A | 不可变工程快照；现有 project/workspace/member IDs、版本绑定、CRS、图层 URI、原始 QGIS XML；携带诊断与未知字段 |
| CommitRequestV1 / CommitReceiptV1 | B：`Pwb::Data` | A/C | operation ID 幂等；base version 乐观锁；staged asset 路径/hash；原版本不覆盖；result 返回新版本/run/binding/recovery 状态 |
| LayerBindingV1 | B：`Pwb::Data` | A | domain layer ID + asset/version/kind；沿用现有 QGIS custom-property join key；不能以指针/QGIS runtime ID 替代领域 ID |
| EditDeltaV1 | A：`Pwb::Qgis` | A 的 B-adapter | source layer/base revision；新增/删除/属性/几何变化；不每次输出全层 GeoJSON；提交给 B 的是 staged asset，B 不接受 QgsFeature/QgsGeometry |
| AlgorithmRequestV1 / ResultV1 | C：`pwb::science`，`Pwb::Science` | A | 算法 ID/version、typed ports、params/units、input version refs、stop token、progress、产物和 provenance |
| IResultPublisherV1 | C 定义抽象；A 实现到 B 的 adapter | C/A/B | C 不直接改数据库；结果经 B 的版本事务入库；错误/取消不能伪造成功 DataRun |
| SelectionEventV1 | C：`Pwb::Science` | A | domain selection、坐标及 CRS、深度/时间的单位、origin/revision；不得携带 QWidget/Python/QGIS 指针，避免反馈环 |

每条线第一轮先发布 `contracts.md`、公共头文件与最小 contract fixture。C 不依赖 B 的公共头文件完成算法/可视化单测，A 不依赖 B/C 完成平台单测。跨域类型转换集中在 A 的 `libs/application/adapters/`。B 管所有跨文件/SQLite 提交协议，A 管 QGIS edit buffer；禁止两条线各做一个 CommitCoordinator。

所有真实生产装配都必须使用实际模块。测试替身通过仅能证明模块接口通过，不能充当全系统 E2E。

## 独立验证与集成顺序

- A 根构建提供 `PWB_BUILD_DATA` / `PWB_BUILD_SCIENCE` 开关，未合入时明确关闭；选择 ON 而模块缺失必须 configure error，不能 silently skip。
- B 提供 `cmake -S libs/data_suite -B build/cpp-data` 独立入口。
- C 提供 `cmake -S libs/science_suite -B build/cpp-science` 独立入口。
- CTest 命名分别以 `platform.`、`data.`、`science.` 开头；0 tests、全部 skip、stub 输出不能作为通过。
- 每条线完成本轮必选 Oracle、提交本分支代码、给出 commit + CMake target + 测试实际结果 + resource manifest + 已知限制。
- 汇总时在 A 分支顺序集成 B、C 的已完成提交（先检查未提交修改，只在无冲突风险时执行普通 merge；不得操作其他 worktree）。A 拥有主程序跨域接线。
- 合并后运行真实链路：旧工程读取 → 图层绑定 → QGIS 编辑 → B 版本提交 → C 算法结果入库 → 保存重开；这是另一个明确的 integration gate。
- 模块完成不等于集成完成，集成未通过不宣布“全 C++ 迁移完成”。P4/P5 扩展和 P6/P7 切换继续使用总设计中的阶段门禁。

## 标签和 worktree 的含义

此标签是开发计划与源码基线，不是可运行的 C++ release。三个 worktree 此时只完成初始化，尚未启动开发任务或后台构建。标签默认在本地创建；需要跨机器分发时应发布这个确切 tag 和对应提交，禁止移动已分发标签。
