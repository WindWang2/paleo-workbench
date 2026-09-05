# Target State — Geological Harness 2.0 验收清单

Goal 结束前逐项核实，不允许伪完成项。证据列指向测试/文件/commit。

## H1 ActionSpec V2 / Contract

- [x] ActionSpec 增加 version / deterministic / cacheable / idempotent / verifier /
      domain_tags / typed input/output ref 声明，schema 递归严格校验
- [x] ActionResult 六态：success / degraded / failed / cancelled / rejected /
      unavailable（rejected=校验/权限/上下文拒绝；unavailable=能力缺失），
      迁移 agent_panel 与全部受影响测试
- [x] 旧 25 action 全部迁移到 V2 字段（版本、deterministic、output_schema 抽查补齐）
- [x] 嵌套 provider 执行不再双重准入（已在 b8638b62 修复）

## H2 Workflow DAG Engine

- [x] WorkflowSpec（nodes/edges/params/slots）+ 静态验证：环拒绝、缺失依赖拒绝、
      重复 node id 拒绝、绑定校验（全 fail-closed）
- [x] WorkflowEngine：拓扑就绪集调度、有界并行（governor try_admit + max_concurrency）、
      节点级取消传播、partial rerun（从指定节点重跑）
- [x] 复用 runtime scheduler/governor，不建第二队列权威
- [x] 节点执行经 HarnessExecutor（守卫管线不旁路）

## H3 Checkpoint / Resume / Cache

- [x] 每节点 checkpoint：spec version + normalized params + input version IDs +
      dep output IDs + cache key + 时间 + receipt
- [x] WorkflowRun 持久化（project-managed 存储、原子写），进程/工程重开后 resume
- [x] cache 复用五重门：deterministic+cacheable 声明、输入版本一致、action/provider
      版本一致、参数一致、输出 catalog 可解析+integrity verified
- [x] 崩溃后 running→interrupted 映射；complete 不重跑；incomplete 不冒充 complete

## H4 Recipe

- [x] `*.paleo-workflow.json`：schema version/nodes/actions/parameter templates/
      typed slots/edges/resource hints；与工程序列化策略一致
- [x] 结构性拒绝：secrets、session token、绝对写路径、SQL、代码段
- [x] save from successful run / clone / rerun-with-new-inputs / migrate / diff

## H5 Context Snapshot

- [x] immutable snapshot（frozen dataclass）含 project ref、active asset/version、
      wells、horizon、map document/layer、extent/CRS、selected features、seismic
      cursor、depth interval、workflow/task ref
- [x] 执行中项目切换守卫：节点执行前 identity 校验，切换后 fail-closed，
      绝不写入新工程
- [x] Agent 仍不触碰 widget/SQLite/任意路径

## H6 Scientific Execution Receipt

- [x] 标准 receipt：action id/version、描述、输入及版本、参数、provider 及版本、
      lease、起止/时长、输出版本、verifier 结果、QC metrics、warnings、degraded
      reason、cancel/error、run ID
- [x] 引用 canonical catalog IDs，不复制 lineage
- [x] 可被 Task Center / Agent / project history / reproduction 消费

## H7 Provider Contract V2

- [x] 契约补齐：verifier 钩子、build identity、安全 discovery（opt-in entry-points
      保持）、duplicate/unknown-schema/unsafe-path/no-version 拒绝（已有基础上
      补 verifier 与示例）
- [x] ≥2 个 example provider（纯计算地质类 + render/export 类），走真实接口，
      测试真实执行

## H8 Action Library 扩张（全部映射真实服务，缺失能力→unavailable）

- [x] project.inspect / project.health
- [x] data.search / data.describe_version / data.lineage / data.verify
- [x] well.describe / well.describe_interpretation / well.correlate（或诚实 unavailable）
- [x] seismic.describe / seismic.open_section / seismic.attribute(ROI) /
      seismic.describe_horizon
- [x] map.describe / map.qc / map.contour / layer.describe
- [x] workflow.create / validate / run / resume / cancel / describe /
      describe_reproduction / recipe.save / recipe.load / recipe.clone
- [x] 无 fake success / stub 冒充

## H9 Permissions / Risk

- [x] READ/COMPUTE/WRITE/DESTRUCTIVE 词汇与注册策略（DESTRUCTIVE 仍不可装）
- [x] risk 与副作用一致（WRITE 只写 project-managed storage/validated export/
      Catalog API）
- [x] 本 Goal 无人工确认；permission context 可注入模拟

## H10 Resource / Governor

- [x] 重计算 action 具备 CPU/RAM/IO（含 temp bytes）估算
- [x] DAG 调度经 governor admission，有界并行、无无界队列
- [x] 地震仅 small/medium ROI；不做 100GB

## H11 Plan / Task Center

- [x] UI-independent plan model（节点状态/进度/当前节点/依赖/receipt/cancel/retry）
- [x] agent_panel 行为接线（消费 model 展示 checklist 式进度）；样式不重构

## H12 Determinism / Replay

- [x] normalized params + input version IDs + action/provider version +
      environment identity（合理范围）+ output hashes
- [x] workflow.describe_reproduction 可用；不承诺跨平台 bit-identical

## H13 对抗性测试（全 fail-closed）

- [x] cycle / missing dependency / duplicate action+provider / nested invalid
      schema / invalid output schema
- [x] cancel mid-node / parent 传播 / retry / 非幂等写 / project switch /
      stale input / deleted input / missing output / corrupted cache
- [x] governor rejection / provider ImportError / restart-resume / recipe
      migration / permission refusal / malicious path / fake provider result

## 端到端验收

- [x] Workflow A（单因素图：search→validate→interpolate→contour→compile→QC→export）
      真实 receipt
- [x] Workflow B（测井处理：input→QC→process→derived→verify）真实 receipt
- [x] Workflow C（MapProduct reproduction：provenance→clone→rerun→compare）真实 receipt

## 流程

- [x] 三轮独立 review（Correctness / Architecture / UX-Perf-Adversarial）+ 当场修复
- [x] 全量相关测试本地通过（含既有多域回归抽查）
- [x] 原子 commits；PR 到 main（背景/架构/功能/测试证据/性能/兼容/风险/未做事项）
