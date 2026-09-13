# 01 — 基线实测（改造前，BASE = 926f3335）

> 工具：`measure_io.py`（本目录，随仓库入库）。
> 环境：Linux / 主 checkout venv + PYTHONPATH 指向本 worktree（D10），
> payload 7.2 MB，/tmp（tmpfs）。
> 计数口径：源读 = 源文件 'rb' 打开次数；payload 再读 = `<project>.artifacts/`
> 下非源文件 'rb' 打开次数；写 = artifacts 内 payload/blob 临时文件（mkstemp）
> 次数，metadata/（manifest+SQLite）记账写不计入；hashes = `sha256_file()` /
> `_digest_of()` 函数调用次数（拷贝循环的 inline 哈希不是函数调用，每拷贝
> 恰一次，已含在源读数里）。

## 数字（2026-09-13 实测）

| 场景 | 源读 | payload 再读 | 写 | hash 函数调用 |
|---|---|---|---|---|
| S1 `service.import_raw`（新内容，无预哈希） | 1 | **1** | 2 | 0 |
| S2 UI 漏斗（lifecycle→adapter→import_raw，新内容） | **2** | **1** | 2 | 1 |
| S3 UI 漏斗（同内容新路径，dedup 命中） | **2** | 0 | 0 | 2 |
| S4 service API dedup（外部给定 digest） | 1 | 0 | 0 | 1 |
| S6 UI 漏斗（同路径同内容，幂等命中） | 1 | 0 | 0 | 1 |
| S5 `import_folder`（270 文件，tmpfs） | — | — | — | 25.5 ms（串行） |

## 与 §3 静态分析的对应

- **读 3 遍**（S2）：lifecycle `sha256_file_or_none`（源读#1）→
  `place_managed_file` 拷贝循环（源读#2）→ `place_blob → _place_blob_bytes`
  对刚落盘 payload 的再读（payload 再读#1）。✓
- **写 2 遍**（S2）：payload 临时 + blob 临时。✓
- **dedup 命中读 2 遍**（S3）：lifecycle 预哈希（#1）+ dedup 分支
  `_digest_of` 内容复核（#2）。✓
- **S1 的 1 源读**：service 直接调用（无预哈希）时只有拷贝读；blob 注册的
  再读落在 payload 上。说明「读 3 遍」中的 #1 属于 UI 漏斗的预哈希，
  #3 属于 blob 注册。
- **S4 的 1 源读**：service 级 dedup 无预哈希，只有复核读——这是
  `test_same_size_different_content_never_adopts_existing_blob` 钉住的
  契约成本，改造后保持不变。
- mkstemp 追踪确认 metadata/ 下另有 2 次记账临时文件（manifest/store 原子
  写），不计入目标口径。

## 目录导入现状

`_collect_folder` / `import_files` 串行 for 循环（`import_service.py:201-269`）；
同仓 `scanner.py:89` 已用 `ThreadPoolExecutor`。S5 的 25.5ms 是 tmpfs 上的
小文件基线（OS 缓存全部命中），真实机械盘/网络盘上串行 stat+探针的代价
远高于此——并发化的价值在真盘场景，tmpfs 数字仅作回归对照。
