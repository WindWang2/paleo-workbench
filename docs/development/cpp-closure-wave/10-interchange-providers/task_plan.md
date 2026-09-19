# 10 线任务计划 — 交换格式、插件与工具运行时接入

- 分支: `codex/cpp-close-10-interchange-providers-20260920`（基于 origin/main 06211541ae1ccce22b0d5ba9258ce722170ca98b）
- worktree: `/home/kevin/project/worktrees/cpp-close-10-interchange-providers`
- 预算: 平台无 /goal /goal-loop 命令（已核实本环境技能列表），按任务书要求采用文件持久化循环；预算上限 360,000,000 tokens（根+子代理累计，子代理已耗 ~2.23M）。
- 独占范围: libs/interchange、libs/providers 的缺失生产适配 + closure_interchange_*；不拥有 agent/harness 调度、部署安装脚本、MainWindow/AppShell 组合（12）。

## 基线盘点结论（2026-09-20, base=06211541）

已实现（复用，不重写）：
- libs/interchange conv-14b 内核：contracts/preflight/manifest/model_adapters(FLAC3D+Abaqus 写出+复读校验)/package_runtime(builder+verifier+materialize+open)/path_safety/atomic_file/zip_archive/unicode/service。
- libs/providers：contracts/registry(静态注册+隔离区)/execution(guarded execute_provider)/schema(JSON-schema 子集)/refs(typed)/context/errors/builtin(factor_stats+map_thumbnail)。

净差量（本线交付）：
1. 交付层 C++ 缺口：delivery.py（DeliveryProfile×5+DeliveryService+报告）、batch.py（BatchConversionService）、dependency_audit.py（ExternalDependencyAuditor）→ `libs/interchange` 新文件。
2. 动态插件加载：libs/providers 新增 versioned C-ABI 插件边界 + dlopen 加载器 + 引用计数延迟卸载；缺插件/ABI 不兼容/卸载竞态失败行为可重复（任务书硬性验收）。
3. closure_interchange_* 组合层：导入探测→配置校验→native 执行→输出登记→可移植包导入导出，供 01 登记/09 导出治理以库 API 消费。
4. 版本/能力协商：插件 ABI+capability 协商；包 schema 版本白名单已在内核（复用）。

## 轮次计划

- R1: 盘点+worktree+登记+ledger（本轮）。
- R2: 实现 delivery/batch/dependency_audit 移植 + 测试。
- R3: 实现 plugin ABI/loader/生命周期 + 测试（含失败行为矩阵）。
- R4: closure_interchange_* 组合 API + 测试。
- R5: 资源门构建+ctest（j2，×2 关键回归）+ oracle 对账。
- R6: 独立审查 subagent → 修复 → 复验 → PR。

## 资源与协作

- 构建一律经 scripts/cpp-migration/invoke-resource-gate.sh（flock 于 .git/common-dir），j2 默认/j4 上限；2026-09-20T16:30 Probe: RESOURCE_BUSY(pid 427346)，排队退避中。
- 协调登记: .git/codex-coordination/cpp-close-wave/10-line.json。
- 11 线消费 pwb::providers 静态 SDK（base 已合并）：插件接口做增量，不改静态契约。
