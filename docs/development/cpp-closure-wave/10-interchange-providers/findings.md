# 10 线发现记录（findings）

## 基线事实（base=06211541）

1. **C++ interchange 内核比任务书假设的更完整**：conv-14/14b 已移植 path-safety/manifest/preflight/contracts/zip/atomic/package_runtime(builder+verifier+materialize+open)/model_adapters(FLAC3D+Abaqus 写出+严格复读)/service。净差量不在这些内核，而在 delivery/batch/dependency_audit 三层与闭环组合。
2. **providers registry 的"不做动态加载"是当时的显式决策**（registry.hpp 头注释引用 ADR 0055 track P.REG："No directory scanning, ever"）。任务书（更晚）硬性要求动态插件加载与 ABI 协商验收。处理：**增量边界**而非重写——静态注册语义原样保留（11 线已声明消费它），插件经同一 register_provider 入口注册为普通 IProvider，失败走既有 quarantine 语义；加载器级拒绝（ABI/能力/描述符）在注册前完成，被拒模块零痕迹。
3. **FLAC3D/Abaqus 无版本协商、无单位/CRS 处理是 Python 侧就有的能力空白**（registry 只认本仓库写出器语法；adapter 不读不写单位/CRS）。如实按"能力空白"记录，不伪造协商；包 schema 版本白名单（SUPPORTED_SCHEMA_VERSIONS=2）与插件 ABI/capability 协商是本线新增的真实协商点。
4. **Python 生产 UI 未接 delivery/batch/model-adapter**（3D 建模页直调 geomodel exporters；交付 UI 走 catalog 自带 copy）。C++ 组合层做成库 API（IRegistrationSink / ILinkableCatalog 两个端口），01/09 以实现类接入，12 装配——不需要抢 app 文件。
5. **集成门禁（run-integrated-gate.sh）不显式开 PWB_BUILD_PROVIDERS**，但 PLATFORM+DATA 隐式开 CONV_22(GeoModel)。因此 closure.cpp 按 `TARGET Pwb::GeoModel AND TARGET Pwb::Providers` 门控；本线自测命令显式加 -DPWB_BUILD_PROVIDERS=ON。delivery/dependency_audit/batch 不需要 providers。
6. 构建工具链在非标路径：/home/kevin/pwb-sdks/root/usr/bin/{cmake,ninja}，SDK cmake 需 LD_LIBRARY_PATH=/home/kevin/pwb-sdks/root/usr/lib（librhash）。资源门脚本要求 cwd 在 worktree 内（repo_root=git toplevel），BuildDir 必须位于 <worktree>/build 下。

## 设计决策（无 Python oracle 的面，如实声明）

- 插件 C ABI：6 入口点（describe/provider_count/provider_descriptor/execute/last_error/shutdown），跨边界只传 UTF-8 JSON + 函数指针桥（progress/cancel）；宿主能力词表 "pwb.plugin-host/1"，模块声明 requires/provides，加载时协商。
- 卸载语义：unload 请求即从注册表视角"即将消失"——运行中执行靠租约完成；新执行收到 typed PluginUnloadPendingError；最后租约释放才 dlclose（先 unregister 后 dlclose，避免代码消失时对象仍存活）。finalized ModuleState 记录永久保留，消除所有 raw 指针 UAF 路径。
- 错误包络 kind ∈ {cancelled, rejected, invalid_parameters, execution, internal}，宿主分别映射 TaskCancelled（原样传播）/ProviderRejectedInputError/InvalidParametersError/ProviderExecutionError。

## 风险与回险

- MODULE 测试插件链接静态 SDK（仅取 glue），每模块一份 thread_local 错误缓冲——语义仍正确（last_error 与 execute 同模块同线程）。
- unload() 与 load() 的模块表查询在 loader mutex 外解析 raw 指针，靠"finalized 记录永不销毁"保证安全。
- batch 多线程路径的结果收集按提交序（池内偷索引），与 Python completion-order-then-sort 的可观察结果一致（最终 stable_sort by source）。
