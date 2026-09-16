# CPP-B Verification Report

状态：**未完成（资源门禁阻塞构建验证）** —— 详见文末门禁记录。本文件在
构建/测试实际运行后更新为最终结论。

## 1. Oracle 状态矩阵（本轮必选 9 条）

| # | Oracle | 状态 | 证据 |
|---|---|---|---|
| 1 | `cmake -S libs/data_suite -B build/cpp-data` 构建成功；不链 Qt/QGIS/Python | **阻塞**（内存门禁 75） | 源码就绪；`data.build_hygiene` 测试已写 |
| 2 | fixture corpus 可读 + 语义与 Python dump 一致 + 未知字段 round-trip | **阻塞** | oracle 管线已产 8 fixture × 4 dump；C++ 对比测试已写 |
| 3 | 真实 .paleo+SQLite 保存/重开不丢；只读零写入 | **阻塞** | `data.project_roundtrip` 已写（mtime+hash 断言） |
| 4 | 提交正确；重复 op 不重版本；base 冲突拒绝 | **阻塞** | `data.commit_*` 已写 |
| 5 | journal 每阶段故障注入有恢复结论；真实 SQLite/file 测试；原资产 hash 不变 | **阻塞** | `data.commit_recovery`（4 阶段×fault hook）+ `data.commit_kill_window` |
| 6 | Unicode/路径/future/缺资源/损坏 JSON·DB 有诊断不崩溃 | **阻塞** | fixture `unicode_paths`/`future_schema`/`corrupt_*`/`missing_resource` + `data.oracle_compare.diagnostics` |
| 7 | CLI 退出码符合文档；拒绝覆盖；测试非零非全 skip | **阻塞** | `data.cli_*` 已写 |
| 8 | 顺序 review + 高优修复 + 二次复验 + 提交 | 部分（静态自审 2 轮完成，见 §3；运行时 review 待构建） | 账本 B-3/B-4 |
| 9 | Pwb::Data 接口/fixture/消费说明/测试输出/handoff | 文档就绪（handoff.md）；测试输出待运行 | — |

## 2. 已完成且可静态验证的

- fixture corpus：8 个 fixture + manifest（sha256 清单），由真实
  ProjectManager.save + DataCatalogService 产出（含 manual_edit run+typed
  ports、bundle members、working copy、staging lease、blob 去重、trash 布局）。
- Python oracle dump：project/model/catalog/resolve 四类 × 8 fixture。
- C++ 数据内核全量源码（libs/domain|project|workspace|catalog|data_suite +
  tools/pwb-inspect|pwb-migrate + tests/cpp/data 9 文件 18 CTest 条目）。
- 文档：baseline / contracts / schema-map（逐字段含默认值/枚举/null/路径语义）
  / test-plan / handoff / ledger。

## 3. 静态自审发现并已修复（构建前）

1. Windows 窄字符路径转换会以 ACP 损坏中文路径 → 全持久化边界改
   `path_from_u8/path_to_u8`（unicode_paths fixture 的硬前提）。
2. journal 恢复不完整：未记录 format/parent ids/receipt size；ProjectSaved/
   Rebound 阶段误入回滚分支；恢复时 run/rebind 语义未还原 → 全部修复。
3. `load_document` 漏加载 tags/asset_tags/version_tags/working_copies → 补齐。
4. pydantic `__post_init__` 种子语义：stage_states 必有 3 个 STAGE_ORDER
   默认 → C++ from_json 补种子。
5. 临时文件命名与 `cleanup_stale_temps` glob 不匹配 → 统一 `.<name>.*.tmp`。
6. .bak 恢复从 copy 改为 rename（os.replace 语义，备份被消费）。
7. corrupt DB 分类：sqlite_master 探测失败 → Corrupt（不再误报 Legacy）。
8. 测试结构错误（无默认构造的成员、stale catalog 解引用、fixture 被
   恢复路径污染、stage 字符串比较逻辑错）→ 全部修正。

## 4. 资源门禁记录（诚实台账）

| 时间(local) | Probe 结果 | free GiB |
|---|---|---|
| 13:0x | exit 75 | 4.31 |
| 13:2x | exit 75 | 4.29 |
| 13:3x | exit 75 | 4.58 |
| 13:4x | exit 75 | 4.66 |
| 13:5x | exit 75 | 4.55 |
| 14:0x | exit 75 | 4.31 |

可用内存（含 standby 的 AvailableBytes）亦仅 ~4.2 GiB——机器被并行会话真实
占满（top: 多个 ZCode/opencode/ChatGPT/企业应用实例）。按共同协议不绕过
共享门禁、不杀他人进程、不轮询烧资源。

## 5. 解除阻塞后的操作序列

```powershell
cd C:/Users/wangj.KEVIN/projects/paleo-workbench-cpp-data
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Configure `
    -SourceDir ./libs/data_suite -BuildDir ./build/cpp-data `
    -CmakeArguments @('-DBUILD_TESTING=ON','-G','"Visual Studio 17 2022"')
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Build `
    -BuildDir ./build/cpp-data
& ./scripts/cpp-migration/Invoke-ResourceGate.ps1 -Action Test `
    -BuildDir ./build/cpp-data -TestRegex '^data\.'
```

（或经 vcvars64 + VS 自带 cmake/ninja；详见 handoff §1。）预期首轮暴露若干
编译/语义问题，按 goal-loop 迭代修复后把 §1 矩阵改为实际结果并二次复验
关键确定性测试。
