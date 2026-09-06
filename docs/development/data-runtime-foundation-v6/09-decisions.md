# 09 — Decisions

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

| # | 决策 | 理由 |
|---|---|---|
| D-1 | 懒打开 = "open 轻探测 + 热读 SQL + 后台 warm + 首变更/全量读内联物化"，而非全库 SQL 化 | 89 处文档扫描面全 SQL 化一轮内不可安全完成；内联物化使懒/急切**构造性等价**（单一文档对象、零合并逻辑）。prompt §2 明示允许该形态。 |
| D-2 | warm 守卫用显式方法名清单 + 装饰器循环（`_WARM_REQUIRED_METHODS`），不用 `__getattribute__` 魔法 | 可 grep、导入期对失效名硬失败、急切服务零行为差异。 |
| D-3 | CAS 放 db 层（BEGIN IMMEDIATE + 事务内 revision 比对），服务前置检查保留为快速失败 | 单一权威点；池化连接 + busy_timeout 跨进程串行；异常整体回滚。 |
| D-4 | 载荷保护用**租约**（元数据表）而非把移动塞进事务 | 保持"大 IO 在锁外"的既有正确方向；租约 best-effort 不阻塞注册（表异常退化为 v5 行为，见 11 的降级可见性局限）；GC 分块持锁复查兜底 plan→sweep TOCTOU。 |
| D-5 | 租约目标 = 盘上目录前缀（`STAGE_DIRS`），资产粒度 | 路径确定性（无需预分配版本 id）；评审 R3#1 证明必须用盘上名而非枚举值。 |
| D-6 | 工作副本身份 = 注册 id + 源版本 id；登记降级时**磁盘证据 fail-closed** | #1211 的契约不能因登记表故障而 fail-open（评审 R3#3）。 |
| D-7 | 会话代际 = 目录后端身份（`catalog_is_current`）；缺席后端 ≠ 陈旧 | 一个权威令牌替代散落序号；危害是"错写到新工程"，缺席后端收不到错写；headless/测试不被误伤。 |
| D-8 | 工程恢复按失败类分流，先验 .bak 再隔离 main | 暂时不可读绝不降级（#1229 核心）；双损坏不制造失踪工程悬空态。 |
| D-9 | map_product 预记 completed 改为 begin(running)→register→complete + audit 扩展 + repair_ghost_runs 迁移修复 | 幽灵窗口根除 + 既有幽灵可检测可安全修复（标 failed 留痕）。 |
| D-10 | resolve_path 无证据 fail-closed + 迁移期安全补 stat 指纹 | §12 明令；永不猜测摘要；文件已移走的旧外部版本保持可诚实上报 missing。 |
| D-11 | vendored IDW 不改并行结构，只除 env 改写 + 作用域化 threadpoolctl；池宽继续走注入的预算 | §10 允许的 wrap-with-contract 形态；ComputeSettings.cpu_workers 本就由治理注入。 |
| D-12 | 调度器 QUEUED 同键超越 + 触发 on_cancel | 取消请求不得让下一个请求看似挂起；预记副作用照常舒展。 |
| D-13 | `ensure_catalog_layout` 根解析（resolve） | Windows 8.3 短路径项目目录曾使每次放置崩溃（基准发现的真实缺陷）。 |
| D-14 | #1213/#1214–#1217/#1226/#1227/#1230 不入本轮 | 井域算法/地震 footprint/CI 家族，超出数据/运行时核心边界（00-baseline 映射表）。 |
