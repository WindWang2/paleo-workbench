# 11 — Known Limitations

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6`

## 懒目录
1. 预热窗口内 `search_assets`/`adapter.list_versions` 为 N+1 点查（每 id 一 SELECT）且 `list_all_versions` 全表物化——窗口有界（后台 warm 秒级完成），但超大目录上代理/交付路径反复调用会付每次全量模型重建代价。后续：预热期 SQL JOIN 一次取齐 + 标签批量查询。
2. 预热期对象身份仅由 `_lazy_read_cache` 在窗口内稳定；warm 换文档后身份重置（UI 行源在 warm 后首次刷新会换对象——与 v5 打开路径一致）。
3. lazy+batch_save 空/失败批的 `_reload_document_locked` 做全量 load 但不置 `_warm`（随后首个 warm 重复付费）——纯性能边角。
4. tag 读 API（list_tags/find_by_tag 等）预热期阻塞到 warm（有界诚实加载）；分页浏览不受影响。

## 事务
5. `rebuild_index` 预检与重建事务之间、`apply_changes` schema-absent 回退 `write_all`、`index.sync()`（无生产调用者）不经 CAS——均为显式维护/罕见路径的窄窗口，重构风险大于收益，留待后续把 rebuild 并入单事务。
6. 真双进程写仍以"拒绝 + 重开"为契约（无自动合并/重放）；B 会话在外来提交后仍供旧读直到重开（v5 既有语义）。

## 租约/GC
7. 租约 TTL 1h：单次放置（多 TB 单文件/挂死盘）>1h 无心跳会被过期并失去保护（地震类长计算已有每 band 心跳；普通放置是单遍复制，>1h 罕见）。
8. 租约 best-effort：表损坏/锁超时退化为 v5 无保护行为，且无日志/遥测可见（评审 R3#9 未采纳为代码——可见性工程超出本轮；GC 持锁复查仍兜底 plan→sweep 方向）。
9. blob 根租约是粗粒度（任一 dedup 导入期间保护整个 blobs/ 树——短时）；显式 sweep 期间并发注册的 blob 删除由 chunk 复查兜底，但 chunk 内（64 项）新租约不被重读（评审 R2#2 残余：需要 per-item 重读或 unlink 失败重试，权衡锁持有时长后保守保留现状）。

## 工作副本
10. `recover_working_copies` 的"已提交"证据是 source_uri == 工作路径——若用户曾把工作文件本身另行 import_raw，崩溃提交行会被误判已提交而清行（文件存活、无登记；评审 R2#7 边角）。
11. v6 之前已存在的未登记工作副本：磁盘证据 fail-closed 保护其不被覆盖，但不会出现在 `list_working_copies` 枚举中（无行可枚举）。

## 工程恢复
12. 仅 PermissionError 映射为 `ProjectUnreadableError`；其他读 OSError 原样上抛（fail-safe 但非类型化，与决策表文档略有出入——评审 R3#7 备注）。
13. `last_recovery` 记录在下一次保存落盘——保存前崩溃则事件只存在于会话内存（法证字节仍在隔离文件）。

## 运行时
14. LAS 单文件解析不可中断（lasio 无注入点）：迟到结果被丢弃、槽位 <1s 释放，但线程烧完——诚实语义，文档明示。
15. map_product 崩溃于 begin(running) 与 complete 之间会留下 RUNNING run（可被 stale_running_run 审计发现；repair_ghost_runs 只修 completed 幽灵——设计取舍：running 可能是合法在途）。
16. 调度器 boost/boost_matching 无生产调用者；QProcessFutureBridge 无 ProcessPoolExecutor 使用者（休眠基础设施，未删）。

## 身份/迁移
17. 事实缺失的旧外部版本（迁移时文件已移走、stat 失败）永久 fail-closed：resolve 上报 missing、relink 拒绝——用户须以新版本重导入（#1221 的代价，诚实优于错绑）。
18. 交换打包的溯源摘要仍截断 1000 条、vendored 外部不回绑包内路径（v5 既有，未在本轮范围）。

## 范围外（见 00-baseline）
19. #1213 WellRegistry O(N×W)（井域）；#1214–#1217（井引擎语义）；#1226 地震 footprint 标量；#1227 克里金/样条约束；#1230 CI 门禁结构；100GB 地震体一切支持/基准。
