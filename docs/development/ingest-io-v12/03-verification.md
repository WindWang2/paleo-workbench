# 03 — 验证证据（ingest-io-v12）

> BASE `926f3335` → HEAD（本 Goal 的实现提交 `de9f1f38` + `ef1108e8`）。
> 测试环境见 D10（主 venv + PYTHONPATH 指向本 worktree，包解析已核实指向
> 本 worktree）。全部命令带 `-p no:randomly -m "not qgis and not slow and not opengl"`。

## 1. before / after 实测（`measure_io.py`，7.2 MB payload，同一脚本同一口径）

| 场景 | 源读（前→后） | payload 再读（前→后） | 写（前→后） | 结论 |
|---|---|---|---|---|
| S1 `service.import_raw`（新内容） | 1→1 | **1→0** | 2→2 | 读 3 遍中的「再读刚落盘 payload」已消除 |
| S2 UI 漏斗（新内容） | 2→2 | **1→0** | 2→2 | 全路径完整读 3→2 遍 |
| S3 UI 漏斗（dedup 命中） | **2→1** | 0→0 | 0→0 | 新鲜哈希即内容证明 |
| S4 service dedup（未经证实 digest） | 1→1 | 0→0 | 0→0 | 复核契约原样保留（必须如此） |
| S6 UI 漏斗（幂等命中） | 1→1 | 0→0 | 0→0 | 不变 |

「写 2 遍」保持 2 遍：payload 与 blob 是两个必须完整落地的文件（D5 证明了
在落盘结构不变 + dedup 语义不变 + 不硬链接的约束下这是下界）；变化是第二次
写不再伴随第三次读（净全量读次数 3→2，字节读流量 -1/3）。

`import_folder`（270 文件，tmpfs，best-of-3）：25.5ms → 60.5ms。tmpfs +
页缓存全命中时线程池启动开销大于收益（见 04-known-limitations #3）；
并发能力与确定性由测试钉死，真盘/网络盘场景为受益面。

## 2. 目标达成核对（§4.1）

1. **单次受管 RAW 导入**：可达下界 2R+2W（D5 证明 1R+1W 不可达），
   payload 再读 = 0。✅（按修正口径达成；偏离如实声明）
2. **去重命中路径**：UI 漏斗 1R/0W（新鲜哈希免复核）；service API 任意
   caller 的未知来源 digest 仍复核（护栏要求）。✅
3. **目录导入并发**：`ThreadPoolExecutor.map` 保序；`_collect_resource`
   注入随机延迟下 added/warnings/filtered 与串行版逐字节一致；线程 rendezvous
   证明 ≥2 工作线程。✅
4. **语义零变化**：
   - temp+fsync+os.replace：拷贝路径两目标各自保持全套原子写
     （`test_catalog_crash_safety.py` 全绿）
   - 只读标记：payload 与 blob 均照旧（`test_catalog_dedup.py` 断言只读位）
   - `known_sha256` 不符 → `CatalogError`：
     `test_wrong_known_checksum_is_rejected_honestly` 绿；blob 命中但内容
     不符 → 拒绝：`test_same_size_different_content_never_adopts_existing_blob` 绿
   - `catalog.json` manifest：`test_catalog_service.py`、
     `test_catalog_lifecycle_acceptance.py`、`test_e2e_dataflow_contract.py` 绿
5. **回归钉 + 反向对照**：`tests/test_ingest_io_v12.py` 7 项；反向对照
   （注入双哈希 → 计数器读 2≠1）证明主断言非空断言；仓库
   tautological 守卫（`tests/e2e/test_integrity_guard.py`）3 passed。✅

## 3. 测试证据（全部本地，无 CI）

新增：`tests/test_ingest_io_v12.py` — 7 passed。

相关套件全绿合计 **342 passed**（24 个文件）：
test_ingest_io_v12 / test_catalog_dedup / test_catalog_service /
test_catalog_crash_safety / test_catalog_adapter_e2e / test_catalog_seam /
test_data_import_service / test_import_registration_flow /
test_issue379_import_threading / test_resources_scanner / test_resource_scanner /
test_issue849_catalog_batch / test_f19_f20_adversarial /
test_catalog_resolve_path_safety / test_audit_catalog /
test_catalog_hotpath_scale / test_catalog_gc / test_import_preflight /
test_catalog_lifecycle_acceptance / test_data_lifecycle_e2e /
test_e2e_dataflow_contract / test_geojson_facies_layers / test_data_toolbar /
test_data_project_path_io。

追加：test_project_manager / test_tooltips / test_export_service /
tests/e2e/test_integrity_guard（tautological 守卫）— 33 passed，0 failed。

修复过程中暴露并处理的既有钉子冲突：`test_integrity_unknown_when_no_checksum`
（port 层不伪造 checksum）与 `test_import_without_checksum_computes_it`
（lifecycle 层必须补哈希）→ D6 修正：lifecycle 保持哈希点，新鲜度经
`_checksum_fresh` 下传，替身接受但忽略。

## 4. 双轴 code-review 与修复轮

两位评审 subagent（串行执行，遵守 ≤2 并发预算）：

- **Spec 轴**：FAIL (0 P0, 1 P1) → 修复后全清。
  - P1（已修）：blob 临时文件 fsync 失败被吞——非耐久 blob 可能静默提交；
    现在 fsync 失败使整个放置失败（与 payload 侧同契约），并有故障注入钉
    （`test_blob_fsync_failure_fails_the_import`）。
  - P2×5：相对路径新鲜度漏洞（已修，只对绝对路径标记 + 边界钉）；
    `_commit_blob_temp` 异常泄漏临时文件（已修）；source 消失时 fd 泄漏
    （已修）；显式路径变体测试缺口（已补钉）；无 digest 重复导入多付一次
    临时写（接受，见 04 #3）。
- **Standards 轴**：FAIL (0 P0, 2 P1) → 修复后全清。
  - 两个 P1 均为 docstring 与代码不符（`_collect_entry` 元组语义、
    lifecycle 新鲜度条件），已改写。
  - P2×7：注释措辞、"the adapter hashed" 不精确（lifecycle 也会哈希）、
    死计数器、Recorder 可变类属性、决策文档先例引用错误、measure_io 清理、
    tickets 拆分——全部处理（除下述）。
  - 接受项：`_checksum_fresh` 是端口协议上首个下划线参数（文档已如实
    标注为 deliberate）。

修复轮后全量复跑：主 venv 345 passed；独立 worktree venv 348 passed
（含 `tests/e2e/test_integrity_guard.py` tautological/integrity 守卫）。

## 5. 最终测量（评审修复后，独立 venv）

| 场景 | 源读 | payload 再读 | 写 |
|---|---|---|---|
| S1 service.import_raw（新内容） | 1 | 0 | 2 |
| S2 UI 漏斗（新内容） | 2 | 0 | 2 |
| S3 UI 漏斗（dedup 命中） | 1 | 0 | 0 |
| S4 service dedup（未经证实 digest） | 1 | 0 | 0 |
| S6 UI 漏斗（幂等命中） | 1 | 0 | 0 |

注：`hashes` 列在清理后只计 `_digest_of`（S4=1，其余 0），与 01-baseline
的旧口径（含 sha256_file）不可直接对比；源读/payload 再读/写三列口径未变。
`import_folder` 墙钟在共享机器上噪声大（60~101ms，tmpfs 小文件，见
04 #4），不作为验收指标；确定性与并发由测试钉死。

## 6. TDD 过程记录

`tests/test_ingest_io_v12.py` 在实现前运行：4 failed（payload 再读、dedup
双读、串行采集三类钉）+ 3 passed（守卫钉与反向对照）；实现后 7 passed。
红→绿证据齐全。
