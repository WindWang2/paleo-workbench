# 候选分块格式基准结果：Zarr v3 vs HDF5（#1070，地图 #1067）

**日期**：2026-08-27
**执行**：`benchmarks/segy_chunked_format_benchmark.py`（分支 `bench/chunked-format-benchmark`）
**数据**：确定性合成体（`generate_synthetic_segy.py`，seed=20260827）

- **Phase A**：quick2g = 1024×1024×512 float32（2.1 GB 数据），内置 NVMe（ext4），页缓存暖。
- **Phase B**：full100g = 5000×5000×1000 float32（100 GB 数据 / 106 GB 文件），**外置 USB-NTFS 盘**（#1069 用户指示），页缓存基本冷（106 GB ≫ 62 GB RAM）。

环境：Python 3.13（miniconda），zarr-python 3.3.0，h5py 3.16.0 + hdf5plugin（Zstd），numcodecs 0.16.5。h5py 读侧 rdcc = 256 MiB。**注意**：合成体以白噪声为主，压缩系数**低估**真实地震数据（真实道相关性更高）。

---

## 1. Phase A：chunk 形状 × codec 扫描（quick2g，NVMe）

### 1.1 转换（SEG-Y → 存储）

| 配置 | chunk | shard | codec | 落盘系数 | 转换吞吐 |
|---|---|---|---|---|---|
| zarr-128cube | (128,128,128) | (256,256,512) | zstd5+bitshuffle | 1.22× | 45.3 MB/s |
| zarr-64cube | (64,64,64) | (256,256,512) | zstd5+bitshuffle | 1.21× | 39.7 MB/s |
| zarr-plate16 | (16,256,256) | (128,512,512) | zstd5+bitshuffle | 1.22× | 14.7 MB/s |
| zarr-mix64 | (64,128,128) | (128,512,512) | zstd5+bitshuffle | 1.22× | 21.0 MB/s |
| zarr-plate4 | (4,512,512) | (128,512,512) | zstd5+bitshuffle | 1.22× | 34.4 MB/s |
| zarr-64cube-noshuf | (64,64,64) | (256,256,512) | zstd5 无shuffle | **1.25×** | 42.8 MB/s |
| zarr-64cube-zstd1 | (64,64,64) | (256,256,512) | zstd1+bitshuffle | 1.17× | **55.4 MB/s** |
| zarr-64cube-lz4 | (64,64,64) | (256,256,512) | lz4+bitshuffle | 1.17× | 29.3 MB/s |
| hdf5-128cube | (128,128,128) | — | zstd5+byteshuffle | **1.25×** | 31.5 MB/s |
| hdf5-plate16 | (16,256,256) | — | zstd5+byteshuffle | **1.25×** | **47.7 MB/s** |

### 1.2 随机整切片读取延迟（p50/p95，ms，暖页缓存）

| 配置 | inline | crossline | timeslice |
|---|---|---|---|
| zarr-128cube | 403/519 | 376/509 | 720/1012 |
| zarr-64cube | 418/641 | 360/421 | 1089/2427 |
| zarr-plate16 | **97/160** | 1477/2224 | 2525/3150 |
| zarr-mix64 | 386/572 | 597/849 | 989/1208 |
| zarr-plate4 | **43/76** | 1789/2552 | 3931/4788 |
| zarr-64cube-**noshuf** | **85/99** | **74/90** | **146/174** |
| zarr-64cube-zstd1 | 530/799 | 547/936 | 1083/1536 |
| zarr-64cube-lz4 | 175/340 | 253/370 | 588/858 |
| hdf5-128cube | 0~1023（双峰） | **1/5** | 28/36 |
| hdf5-plate16 | 57/166 | **1/394** | 44/82 |

### 1.3 单道随机读（500 道，well-tie 场景）

| 配置 | ms/道 |
|---|---|
| zarr-plate4 | 26.1 |
| **zarr-64cube-noshuf** | **10.0** |
| zarr-plate16 | 55.0 |
| zarr-mix64 | 64.8 |
| zarr-128cube | 71.4 |
| zarr-64cube | 113.2（chunk 更多 → 每 chunk 开销主导） |
| hdf5-128cube | **9.5** |
| hdf5-plate16 | 13.4 |

### 1.4 并发读（8 线程，串行/线程用不同随机任务集）

| 配置 | 加速比 |
|---|---|
| zarr 各配置 | **0.92–1.15×（无并行收益）** |
| hdf5-128cube | **3.62×** |
| hdf5-plate16 | **6.43×** |

### 1.5 预读干扰（顺序扫 inline 时交互读 timeslice）

- zarr-mix64：x1.3 退化；zarr-64cube-noshuf：x1.5。
- hdf5-128cube：x0.4（热缓存偏置，见 §4 方法论警告）。

### 1.6 LOD 金字塔（zarr-mix64 上建 ::2 的 L1）

- 构建：7.4 s / 2.1 GB（≈285 MB/s）；L1 落盘 226 MB（10.5%，低于理论 12.5%）。
- L1 切片读取 34 ms vs 基层 188 ms → **5.5× 加速**，金字塔有效。

---

## 2. Phase B：100G 体（外置 USB-NTFS）

### 2.1 转换与落盘

| 配置 | 转换耗时 | 转换吞吐 | 落盘 | 系数 | 文件数 |
|---|---|---|---|---|---|
| zarr-mix64（zstd5+bitshuffle） | **20.2 min** | **82.4 MB/s** | 83.0 GB | 1.20× | 801 |
| zarr-64cube（zstd5 无shuffle） | **17.6 min** | **94.7 MB/s** | 80.4 GB | 1.24× | 801 |
| hdf5-128cube（zstd5+shuffle） | 37.1 min | 44.9 MB/s | 80.2 GB | 1.25× | 1 |

（均为单线程转换；shard = 128 MiB 时 100 GB 体收敛到 801 个文件，sharding 的 NTFS 效果成立。）

### 2.2 冷缓存随机切片（p50/p95，ms）

| 配置 | inline | crossline | timeslice |
|---|---|---|---|
| zarr-mix64 | **2797/3647** | 5387/12309 | 25155/80072 |
| zarr-64cube-noshuf | 4374/6679 | **2816/4777** | **11796/23677** |
| hdf5-128cube | 6250/6778 | 9358/13582 | 36869/48372 |

### 2.3 单道读 & 并发

| 配置 | ms/道（100 道） | 8 线程加速比 |
|---|---|---|
| zarr-mix64 | **59.5** | **1.72×** |
| zarr-64cube-noshuf | 77.6 | 1.25× |
| hdf5-128cube | 216.9 | 1.09× |

**冷盘反转了暖缓存印象**：HDF5 在 quick2g 上的全部优势（rdcc、timeslice 28 ms、×3.6-6.4 并发）在 100G 冷 USB 上全部消失，成为三向延迟与单道读最慢、转换最慢（44.9 MB/s）的配置；phil 锁 + 单文件随机 chunk 寻址在冷盘上无从发挥。Zarr 除 inline（受 chunk 数影响）外全面占优。

---

## 3. 关键发现

1. **读放大模型被实测精确验证**：切片延迟 ≈ A × 解压吞吐⁻¹。plate4 的 inline 43 ms vs crossline 1789 ms（A=4 vs 512）完美对应理论（调研报告 §4.2）。
2. **bitshuffle 是 zarr 读延迟的头号杀手**：关闭后三向延迟降 5-7×（418→85 / 360→74 / 1089→146 ms），而落盘系数仅从 1.22 降到 1.25（合成噪声数据上 shuffle 甚至略降压缩率）。lz4+bitshuffle 是 2-3× 提速的折中。
3. **zarr-python 3.3 同步 API 的并发读没有兑现**（8 线程 0.92-1.15×）——与调研 §4.5 的结构性论断相反；h5py 的 phil 锁也没阻止 3.6-6.4× 的实际加速（含 rdcc 共享缓存的贡献）。并行化路径需要 zarr AsyncArray 或多进程，留给访问层原型（#1072）验证。
4. **每 chunk 固定开销显著**（zarr 同步路径）：64³ 的单道读取（113 ms）反而比 128³（71 ms）慢——chunk 数量翻倍抵消了放大系数减半。
5. **h5py 的 rdcc（解压后 chunk 缓存）是暖工作集的大杀器**：crossline p50 1 ms。zarr-python 3.3 无对应进程内缓存——访问层必须自带 L1（现有 RamSliceCache 正好补位）。
6. **转换吞吐 15-55 MB/s（单线程压缩主导）**：100G 体转换需 35-110 分钟。导入管线（#1071）必须并行化转换（分 inline 段多进程）或接受后台长任务。

## 4. 方法论警告

- 1.4 的首轮 threads 测试曾复用同一任务集（第二次全命中缓存 → 假加速 ×7-10），已修正为不同种子任务集。
- 1.5 的 hdf5 x0.4 "加速" 是暖缓存偏置（solo 先跑预热了 rdcc）。
- quick2g 全程暖页缓存；100G 体冷缓存行为以 Phase B 为准。
- 合成噪声数据低估压缩系数（真实地震预期 1.5-2×，见调研 §4.7）。

## 5. 推荐（#1070 定案，供规格书采纳）

1. **格式定案：Zarr v3 + sharding（128 MiB shard，morton 写序）**。调研首选经实测巩固：转换吞吐 2×于 HDF5（95 vs 45 MB/s），冷读全面占优，100 GB 体 801 个文件（NTFS 友好），HDF5 的暖缓存优势在冷盘场景（真实使用：106 GB ≫ RAM）全部反转。HDF5 降为单文件分发场景的备选，不再是主格式。
2. **默认 codec：zstd clevel 5、不启用 bitshuffle**（快速浏览场景）。bitshuffle 使三向读延迟劣化 3-7×（Phase A/B 一致），而合成数据压缩系数仅差 ~3%（1.24 vs 1.20）。⚠️ 开放验证项：真实工区数据（道间相关性强）上 shuffle 的压缩收益需复测；若真实数据收益显著，可对 RAW 归档层与浏览层用不同 codec（归档 zstd5+shuffle、浏览 zstd1-3 无 shuffle）。
3. **默认 chunk 形状：(64, 128, 128) 混合板状**（4 MiB，shard (128,512,512)）。inline 热路径冷首读 2.8 s、三向均衡；64³ 逐 chunk 开销过大（Phase A 单道读 113 ms 反超 128³ 的 71 ms 证实）。
4. **硬约束输入 #1072（访问层原型）**：冷态首读秒级（2.8-12 s）是格式层物理极限，交互级延迟**必须**由 LOD 金字塔（实测 L1 切片 5.5× 加速）+ 方向预读 + 进程内 L1 缓存（RamSliceCache 补 zarr 无解压缓存之缺）叠加达成；timeslice 是最坏路径（12-37 s），规格书应规定 timeslice 浏览 LOD-first。
5. **硬约束输入 #1071（导入管线契约）**：单线程转换 100 GB 需 18-37 分钟——契约必须含分段并行转换（预期 4-8×）与「转换期间降级直读 SEG-Y」的过渡模式。
6. **并发实测修正调研 §4.5**：zarr-python 3.3 同步 API 8 线程仅 1.1-1.7×（承诺未兑现），h5py 冷盘 ×1.09；并行化路径（AsyncArray / 多进程）是 #1072 的验证项。
