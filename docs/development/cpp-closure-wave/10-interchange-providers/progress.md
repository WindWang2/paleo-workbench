# 10 线进度记录

## R1（2026-09-20）盘点与骨架

- 候选 SHA: origin/main = 06211541ae1ccce22b0d5ba9258ce722170ca98b（fetch 后确认，与任务书锚点一致）。
- 分支/worktree: codex/cpp-close-10-interchange-providers-20260920 @ /home/kevin/project/worktrees/cpp-close-10-interchange-providers。
- 协调登记: .git/codex-coordination/cpp-close-wave/10-line.json（写明目录/函数/接口声明与资源租约）。
- 平台核实: 本环境技能列表无 /goal、/goal-loop 命令 → 采用文件持久化循环（如实记录，未伪造命令）。
- 盘点子代理（Explore, 1/3 额度）完成 Python interchange/providers 全量能力清单：
  - Python 13 格式注册（flac3d_f3grid/abaqus_inp 为"仅导出+复读校验"半边，无版本协商/单位 CRS——如实记为能力空白）。
  - delivery.py（5 内置 profile + QA 报告）、batch.py（I14 批量）、dependency_audit.py（I13 审计）在 C++ 侧缺失 → 本线净差量。
  - providers registry 现状注释"刻意不做动态加载"；任务书硬性要求动态插件加载+ABI 协商+卸载竞态失败行为 → 做增量边界（不改静态注册语义，11 线消费不受影响）。
  - Python 生产 UI 未接 delivery/batch/model-adapter（库完备、UI 待接）——迁移评估按库契约计，不虚报生产负载。

## R2（2026-09-20）实现

新增文件（全部在本线独占目录）：
- libs/providers: include/pwb/providers/{plugin_abi,plugin_loader,plugin_module}.hpp, src/plugin_loader.cpp。
  - C ABI 边界（6 入口点+桥接函数指针），kPluginAbiVersion=1 协商；PluginLoadError/PluginAbiError/PluginCapabilityError/PluginDescriptorError/PluginUnloadPendingError 全部 typed。
  - 引用计数租约：卸载竞态=运行中任务持有租约→unload 返回 deferred、任务正常完成、新执行 PluginUnloadPendingError 拒绝、最后租约释放时注销 provider 并 dlclose。ModuleState finalized 后记录保留（消除 UAF），查询路径全部视为不存在。
- libs/interchange: include+src dependency_audit.{hpp,cpp}、delivery.{hpp,cpp}、batch.{hpp,cpp}、closure.{hpp,cpp}。
  - dependency_audit：valid/missing/changed/unknown/relink_candidate 分类、4GiB 哈希预算降级、拒绝猜测的 relink 阶梯、apply_relink 人工确认规则；CatalogVersionRef 增 sha256 字段（增量）、ILinkableCatalog=CatalogSource+link_external。
  - delivery：5 内置 profile（键序/消息与 Python 逐字）、get_profile 拒绝消息、QA 报告（JSON 键序+Markdown）、CRS 收集（project+catalog+resources）、报告原子写、zip 容器。
  - batch：有界并发(默认2/上限4)、确定性命名+casefold 冲突后缀 -2/-3、失败隔离、协作取消、预算估算；登记经 IExportRegistration 端口。
  - closure_interchange_*：detect(sniff+preflight)→import_path(包 materialize+verify+登记)→export_as(plan→execute→verify→register)→build_delivery/import_package；插件扫描 load_available_plugins；能力报告 closure_interchange_capability_report。注册经 IRegistrationSink 端口（01/09 消费面）。
- CMake: 两库增量源/测试；closure.cpp 门控 TARGET Pwb::GeoModel AND TARGET Pwb::Providers（集成门禁隐式开 GeoModel，本线自测显式加 -DPWB_BUILD_PROVIDERS=ON，如实记录）。
- 测试: providers_tests/plugin_test.cpp + plugins/test_plugin_module.cpp（4 MODULE 变体：OK/BADABI/BADDESC/MISSING_CAP）；interchange_tests/{dependency_audit,delivery,closure}_test.cpp。

## R3（2026-09-20）验证

- 资源门: invoke-resource-gate.sh Probe 首测 RESOURCE_BUSY(pid 427346) → 按合同排队退避。
- 排错记录: 首次 configure 失败三个原因逐一诊断——(a) 门脚本须在 worktree 内运行（repo_root=git toplevel）；(b) 构建链在非标路径 /home/kevin/pwb-sdks/root/usr/bin（cmake 需 LD_LIBRARY_PATH 指向 SDK 的 usr/lib，librhash）；(c) `-a` 参数表是分号分隔，误用逗号导致 -D 全部失效、默认 PLATFORM=ON 级联拉起 CONV_07 报缺 MAPPING_KERNEL。修正后最小开关集：PLATFORM=OFF/DATA=ON/CONV_22=ON/PROVIDERS=ON/TESTING=ON。
- 独立审查（Explore 子代理 #2，只读）：6 P0 + 5 P1 + 若干 P2，全部确认有效：
  - P0 修复：sweep_pending/finalize_module_now const 一致性；plugin_module.hpp 宏内 `requires` 关键字撞名改 requires_list + 全限定 ABI 类型 + 补 domain/json include；测试插件 using namespace + json 可见性；closure 补 const plugin_loader() 重载；interchange CMake 把 closure.cpp 独立门控在 GeoModel AND Providers 并 PUBLIC 链接 Providers；plugin_test 二次 unload 语义改为幂等 true（实现语义为"已卸载即成功"，比原断言更合理）。
  - P1 修复：插件 glue 拆独立源 plugin_module_glue.cpp + pwb_plugin_glue 静态微库（MODULE 只链 glue+Domain，mapping kernel 非 PIC 归档不再进 .so 链接）；delivery 警告两趟序（先缺失后变化，Python parity）；from_json 空 report_formats 保留为空/未知 external_policy 抛错；重复加载检查跳过 finalized（支持热重载）+ weakly_canonical 归一。
  - P1 文档化：registry.get 借用与 loader sweep/unregister 之间的窗口属 registry.hpp 既有借用合同（与静态 provider 相同），在 plugin_loader.hpp 头注释显式声明，不在本线重造执行器所有权。
  - P2 修复：execute 结果解析错误改 ProviderExecutionError；warnings 非字符串跳过；load() 入口补 sweep；batch convert 起始 cancel.checkpoint()；batch.hpp 补 <algorithm>；markdown dict 渲染改 Python str(dict) 风格（单引号）；audit file_size 失败显式 UNKNOWN。
- 构建实测（资源门下，j2，Release）：两轮排错（门脚本 cwd 约定/SDK 工具链路径/`-a` 分号分隔）后 configure exit 0；首次构建暴露测试插件与命名空间编译错误（外层 namespace 内全限定重开导致的 pwb::providers::pwb::... 相对解析、宏缺分号、Json 别名缺声明、filesystem.path 误用 size()、聚合初始化字段错位、filesystem_error 夹具目录缺失），逐轮修复后 **构建 exit 0、0 error**。
- 测试实测：首轮 13 测试 3 失败（providers.plugins SegFault、interchange.delivery 夹具、interchange.closure 断言+bad_alloc）→ 定位三个真实缺陷：①PluginAbiError 路径 dlclose 后读模块内存（UAF/SIGSEGV）；②测试 RecordingSink 聚合初始化字段错位；③delivery 夹具缺 .artifacts 目录 + write_file 不建父目录；以及 zip 测试误用 directory profile 后解引用空 optional。全部修复。
- 复验：invoke-resource-gate.sh Test -r "providers\.|interchange\." ×2 → 两次 **exit 0，100% tests passed out of 13**（含 providers.plugins 0.46s 全矩阵、interchange.archive oracle 复放）。受影响既有测试零回归。
- 预算消耗：根代理 + 2 个子代理（盘点 ~2.23M、审查 ~2.18M tokens），远低于 360M 上限。

