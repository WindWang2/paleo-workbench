# CONV-31b decisions — catalog service/db 深核

Branch `feat/cpp-catalog-service`（worktree `../worktrees/cpp-catalog-service`，base main 83eac12e）。
Scope：`31b-findings.md`（A-1~A-8 三列 + A1-A8 文件所有权地图）；行号级侦察：`31b-recon/R1-R10`。
流程：10 并行 recon → 契约冻结（findings §C/§D + 10 新头签名桩 + models DTO 实装）→ 8 并行实现（零交集所有权）→ oracle 冻结 + replay → V1-V4 四镜头审查 + 集中修复 → 独立末验。

## D1 — 移植面（10 个新 TU + 共享面扩展，`# BEGIN CONV-31B` CMake 块并入 pwb_catalog）
- `apply_changes`（DirtySet 8 桶插入序/apply_changes 八表序+事务内 CAS/reconcile 六表逐列/rebuild==apply 等价/sync 自愈/is_fresh 三门/reset）
- `queries_sql`（14 惰性读=急切逐字节 parity + 8 查询；find_managed_raw/find_external_by_path 的 INDEXED BY 逐字）
- `service_core`（CatalogEntityStore unique_ptr 节点/CatalogMaps 8 索引含三处故意不对称/CatalogServiceCore：mutation_serial 先+1、非批 +1→flush→失败 -1 不 reload、#411 pre-check+#1220 事务内 CAS、checkpoint 门；open_catalog 五健康矩阵含 lazy 早退）
- `working_copy`（状态机/recover 四分支判定序/commit 两段式 lease 全窗/#1218 僵尸防护/StagingLeaseGuard）+ gc.hpp 新增 `active_staging_targets_live`（修复 lease 防护被文档快照击穿的 R-leak）
- `resolve`（七梯 + `_fallback_identity_ok` 身份门 #1140/#1221，门失败=降梯）+ `trash_service`（tombstone 四键/锁内两段 save 序/purge 全序载荷含三 tag map 回灌/W1-W2 probe）
- `model_registry` + `asset_metadata`（governance 管线）+ `version_promote`（promote run 形状/#849-1 锁内重分配）
- `v11_bundle`（plan/commit 两阶段、A1-A7 命名池交错、E1-E5 回滚阶梯、C1-C8/M1-M8）+ dedup `place_managed_tree`（T1-T8）
- repository 扩展（load_manifest L1-L5/save 五步+首存种子+unchanged-skip/write_all/reset/WC CRUD+lease 写侧/model 双行一事务）+ models.hpp Model/ModelVersion DTO + row_mapping 四 mapper
- 既有行为纠偏 5 处（对照 db.py 均为回归 Python 真值）：open_read_write 不再 bump revision（三键 DO NOTHING 播种）；WC 三写不 bump + 裸 INSERT（UNIQUE 先判）+ updated_at 刷新；run_ports 分桶 output-else-input（db.py:161）；model_ref 空串归 nullopt（db.py:88）；verify_bundle_integrity 尾聚 null→verified。

## D2 — Oracle 与验证边界
`tools/oracle/generate_catalog_service_fixtures.py` 真实 import 冻结 **97 节**（两遍逐字节一致；随机 id 按首现序 gN 重编号、corrupt 时间戳 __TS、mtime 冻结布尔）。C++ replay `data.catalog_service`：**25+3 cases ×2 全绿**（95/97 节全值 replay；2 节 maps 内部状态无公共观察面=序列驱动+文档级断言，如实标注）+ negative self-check 8 处篡改全检出。**本机无 cmake**：g++ 16.2.1 直连全闭包（93 obj + 3 工具 exe；sqlite3.c C 单编）；CMake 两处挂载（`# BEGIN CONV-31B` 块 + `pwb_data_test(data_catalog_service …)`）供 CI。全仓 **28 项测试 ×2 零回归**（含 Python oracle readback 门、ldd 无 GUI/Python 链接卫生门、data_consumer 全回路两轮）；ASan/UBSan 全闭包零报告。

## D3 — 关键裁决（契约冻结轮 + 审查收敛）
1. SaveHook 家族统一 `std::function<DataError(const DirtySet&)>`（携带式；驳回零参——trash/purge 需告知脏集）。
2. apply_changes 为自由函数族 + repository `writable_database()` 桥接（驳回成员函数形态）。
3. 不新增 ErrorCode：`ConflictBaseVersion` + `detail["stale_write"]` + `is_stale_write()` 谓词；中文 CAS 两变体消息逐字。
4. staging_target 单一来源=working_copy.hpp；WC 注册表真相=sqlite（文档快照仅镜像）；ManifestLoad 类型化 models（Json 透传废止）。
5. v11 虚注册接口裁撤，改用 WorkingCopyContext；锁/save/DirtySet 归 service_core。
6. 修复轮裁决：invalidate_maps 改按 id 复用节点（保 "stable until removed" 契约）；WC 事务后 CAS 基线 resync 以 document==stored 为所有权证明（外来写者仍拒）；find_* 纯读不置脏（mutation-epoch）。

## D4 — 缺陷修复记录（swarm 自查自纠，全部回归 ×2 复验）
- Wave3 replay 揪出 4 处：queries.cpp `search_assets_scan` 迭代器混用 UAF；open_read_write 每次 bump（毒化 CAS 基线）；service_core write_all 后句柄失效；remove_*_bulk detach 过早析构。
- 集成轮 2 处（主代理）：run_ports 分桶方向；model_ref 空串。
- Wave4 四镜头审查（V1 parity/V2 内存并发/V3 约定/V4 消费者）7 处：**invalidate_maps reset_from 销毁节点 UAF（ASan 实锤 P0）**；WC 事务后 flushed_revision 失同步（同会话 save 全拒）；find_* 无条件置脏（直改丢失窗口+O(N) 读放大）；verify 尾聚反转；schema 缺失回退缺两 attempt+reset 自愈；recover 降级读仍发 telemetry；negative 注释措辞。V4 确认 28 项既有测试与全部 repository 消费者（data_suite×5、application、main_window、17 测试 TU）无人依赖旧偏差行为。
- 残余登记：model_registry `Model*` 返回指针作用域契约（结构性修复需动冻结公开面，书面契约落于 TU：同表 append 前用完）。

## D5 — 有界偏离（如实；全表 34 条见 findings §E，本节为审查新登记 + 重点）
- `Transaction::commit()`/`step_done()` 吞返回码：repository 既有基建 23 处写路径在 IO/disk-full 下可能假成功；apply_changes 已自建 Stmt/TxnGuard 规避。**遗留基建项，建议独立小切片统一 sqlite.hpp 错误面**（影响跨切片，不在本轮手术范围）。
- 单写者纪律：WorkingCopyContext/BundleSeams 注入的 `Database&` 与 core flush 共用，仅散文约定（Python 有 ThreadSafeCatalogSession 静态防护）——C++ 库消费者按单写者组合根使用。
- append_parent 未知 id 静默 no-op（冻结 void 签名所限，组合层字节级消息已保留）；v11_bundle Local 降级块（copy/hash/verify 失败降级，Python 让 OSError 传播）；trash move 失败折叠 metadata-only；recover 读失败折叠为 `_safe`（Python 部分路径提前 return）。
- 懒开/warm/`_WARM_REQUIRED_METHODS` 包装退役=直连（Python UI 性能形态）；连接池/线程探活不移植（单连接 RAII + BEGIN IMMEDIATE 跨进程）。
- ASCII fold（沿 15-decisions D6）、`parse_python_int` 不收下划线/Unicode 数字（仅手改 sync_state 可达）等。

## D6 — 不移植/退役（沿 findings §F）
db 连接池全套、service 懒开包装、adapter 协议胶水（其 dedup 三级策略已由「SQL tier1+复验 / maps overlay tier2 / 扫描 heal tier3」双轨承接）、lifecycle.py（CONV-32/33 workflow 域按域重建）、grid_artifact/domain_binding/edit_session（沿 31-decisions D5）。

## D7 — 后续
- **CONV-33（workflow 顶层编排面）的 catalog 依赖已就绪**：open/save/CAS/working-copy/bundle/model registry 的 C++ 面全部可用（service_core + repository 事务族）。
- 建议小切片：sqlite.hpp 事务错误面上报（D5 第一条）；gc.hpp 快照版 `active_staging_targets` 已无库内调用方可收编。
