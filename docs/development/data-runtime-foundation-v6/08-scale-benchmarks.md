# 08 — Scale Benchmarks（§13）

日期：2026-09-07 · branch `feat/data-runtime-foundation-v6` · 运行器 `benchmarks/catalog_scale_v6.py`

## 1. 分层

- **生产路径层**（默认）：真实 `import_raw`（batch_save 单事务/批，微载荷）——用户数据的精确路径。本机 ~52 资产/s（慢盘+Defender；v5 文档在快机上为 ~1850/s）。
- **元数据压力层**（`--direct-seed`）：行直写规范库（同 schema、合成摘要、零载荷 IO），仅测存储/查询层——500k 档专用，诚实标注不是注册路径。
- 100GB 地震体支持/基准**明确排除**（本轮硬边界；地震仅小/中 fixture 生命周期路径）。

## 2. 实测（本机：Windows、NVMe、Defender 实时扫描、fsync 密集；20k 生产层）

| 指标 | 值 | 预算 |
|---|---|---|
| **懒打开** | **13.2 ms** | <500 ms（目标达成，~2500× 急切重开） |
| 首页（500 行） | 7.2 ms | <150 ms |
| 深翻页（offset N/2） | 6.5 ms | <200 ms |
| get-by-id | 0.29 ms | <10 ms |
| 标签变更 | 8.6 ms | <100 ms |
| 版本时间线 / 一跳 lineage | 0.01 ms | — |
| 工作副本 checkout+commit | 33.8 ms | — |
| 清单导出 | 357.9 ms | — |
| **急切重开（对照）** | **33,072 ms** | —（这就是 #1212 移出 GUI 线程的成本） |
| 并发写冲突检测 | 1（检测到） | — |

v5 既有 50k/100k 重档（test_catalog_scale_v5 heavy）继续有效；懒打开与查询不随 N 线性增长（打开只做健康探针）。

## 3. CI 门（tests/test_catalog_scale_v6.py，N=1500）

懒打开 <500ms、首页 <150ms、深页 <200ms、get <10ms、标签 <100ms、**后台 warm 期间查询正确**（不只不阻塞）、规模下 CAS 冲突照常拒绝。

## 4. 10k 井 / 500k / 长 lineage

- 500k 元数据层经 `--direct-seed` 可跑（本机播种耗时超出会话预算，未记录数字——运行器交付，CI 不设门）。
- 10k 井：井域绑定 WellRegistry O(N×W)（#1213）属井域家族，**本轮范围外**（见 11）；数据/运行时核心对井数无额外二次路径。
- 大 lineage 图：BFS 上限 5000 节点 + 双向索引维持；懒路径一跳 SQL。多 GB 载荷模拟 = blob/租约路径按摘要与目录前缀操作，无需物理大文件（测试用微载荷驱动同代码路径）。
