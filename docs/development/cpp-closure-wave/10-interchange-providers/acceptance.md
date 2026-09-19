# 10 线验收记录（acceptance）

平台核实：本环境无 /goal、/goal-loop 技能；预算按 360,000,000 tokens 请求（根+子代理累计），完成即停。所有验收项附真实命令与退出码。

## 本线能力四列清单（implemented / merged / wired / verified）

| 能力 | implemented | merged(基线) | wired(组合层) | verified |
| --- | --- | --- | --- | --- |
| FLAC3D/Abaqus 结构化导出+复读校验 | conv-14b | ✔(base 06211541) | closure.export_as | ✔ interchange.closure + interchange.archive |
| 包 builder/verifier/materialize/open | conv-14b | ✔(base) | closure.import_path / build_delivery | ✔ closure + delivery |
| 交付 profile + QA 报告（I15/I16 移植） | 本线 delivery.* | ✗ | closure.build_delivery(_profile) | ✔ interchange.delivery 34 checks ×2 |
| 批量转换（I14 移植） | 本线 batch.* | ✗ | closure.batch | ✔ interchange.closure（确定性命名/冲突后缀/失败隔离/预算） |
| 外部依赖审计+重连（I13 移植） | 本线 dependency_audit.* | ✗ | DeliveryService 内嵌审计 | ✔ interchange.dependency_audit |
| 动态插件加载 + ABI/能力协商 | 本线 plugin_* | ✗ | closure.load_available_plugins | ✔ providers.plugins（8 组检查） |
| 插件卸载竞态安全 | 本线 | ✗ | providers 执行链 | ✔ providers.plugins（运行中任务完成/新执行 typed 拒绝/延迟 finalize/幂等卸载） |
| typed invocation（11 消费面） | base（execution.hpp） | ✔(base) | 不变，插件 provider 走同一 execute_provider 管线 | ✔ providers.execution + plugins |
| 版本/能力协商 | 本线(ABI/能力)+base(包 schema 白名单) | 混合 | 加载时/校验时 | ✔ providers.plugins / interchange.delivery |

## 验收门实测（2026-09-20, build/line10, Release, 资源门 j2）

- 构建：invoke-resource-gate.sh Build -t "pwb_interchange;pwb_providers;pwb_plugin_glue;interchange.preflight;interchange.archive;interchange.dependency_audit;interchange.delivery;interchange.closure;providers.*;providers.plugins;4×pwb_test_plugin_*.so" → exit 0，0 编译错误。
- 测试 pass1: invoke-resource-gate.sh Test -r "providers\.|interchange\." → exit 0，**100% tests passed out of 13**。
- 测试 pass2（green-x2）: 同命令 → exit 0，**100% tests passed out of 13**。
- 受影响既有测试零回归：interchange.preflight / interchange.archive（oracle 复放 fixtures/interchange_oracle.json、interchange_archive_oracle.json）/ providers.oracle（provider_oracle.json）/ providers.contracts/registry/schema/execution/builtins/service 全绿。
- 新增覆盖：providers.plugins（缺文件/重复加载/ABI 999999 拒绝/宿主能力缺失/坏描述符零痕迹/取消桥 TaskCancelled/卸载竞态三段/幂等卸载/typed invocation echo 往返）；interchange.dependency_audit（valid/missing/changed×3/unknown/预算降级/篡改哈希检出/拒绝猜测/重连阶梯/人工确认/lineage 元数据）；interchange.delivery（5 profile/未知配置消息/profile JSON 往返/包构建/报告 JSON+MD/CRS 三来源/依赖审计嵌入/zip 容器+复验/篡改→FAILED→报告/UNVERIFIED 如实/报告子集）；interchange.closure（能力报告/导出闭环+负面自检/批量/包 round-trip/穿越包 fail-closed/missing 结构化）。

## 途中发现并修复的真实缺陷

1. PluginAbiError 路径 dlclose 后再读模块内存拼消息 → SIGSEGV（gdb 定位 `mov (%rbx),%ebx`）；修复：dlclose 前拷贝全部所需字段（abi、requires 列表）。
2. 延迟卸载在最后租约释放时于 execute() 栈内销毁 provider，而 SDK executor 之后还调用 provider.verify() → UAF；修复：惰性清扫（finalize 只在后续 loader 入口执行），token_deleter 只递减。
3. 独立审查（Explore 子代理）6 P0 + 5 P1 全部修复（宏 `requires` 关键字撞名、CMake 门控/链接、警告两趟序、from_json 语义、热重载路径检查、glue 拆分等），见 progress.md R3。

## 尚未执行/明确限制（如实声明）

- 全产品统一矩阵（含 Qt 平台、MALLOC_CHECK_、集成树）由 12 在集成候选 SHA 执行；本线只跑受影响集。
- Windows LoadLibrary 实现未编译（POSIX dlopen；C ABI 两侧已隔离，移植面小）；本环境无 Windows。
- 插件扫描 load_available_plugins 在 closure 测试中未覆盖端到端（模块文件在 providers_tests 构建树内），加载语义由 providers.plugins 全覆盖。
- FLAC3D/Abaqus 无版本协商/单位 CRS 是 Python 冻结源固有能力空白，本线如实保持（未伪造协商），协商点在插件 ABI 与包 schema 白名单。
- Python 参考流程与冻结源未删除；C++ 生产路径无解释器/subprocess 回退。
- 注册/导出治理消费面以 IRegistrationSink/ILinkableCatalog 库端口交付（01/09 实现类接入、12 装配）；本线未改 app 文件。
