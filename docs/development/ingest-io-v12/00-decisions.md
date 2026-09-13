# 00 — 决策记录（ingest-io-v12）

> 本文件记录本 Goal 期间的全部自主决策与理由。按时间顺序追加；重大决策编号 D1…Dn。

## D1 — 环境适配：Linux worktree 布局，非 Windows/GitBash

Prompt 假设 Windows/GitBash（`/c/Users/wangj.KEVIN/...`、`.venv/Scripts/python.exe`）。
实际执行环境是 Linux：

- 仓库本体是 bare + worktree 布局：`/home/kevin/projects/paleo_project/.bare`（bare repo），
  主 checkout 在 `/home/kevin/projects/paleo_project/main`（branch `main`）。
- 适配：worktree 按 prompt 的字面约定放在仓库外同级
  `/home/kevin/projects/paleo-workbench-ingest-io-v12`，分支 `feat/ingest-io-v12`。
- venv 用 `.venv/bin/python`（Linux 布局），由 `uv 0.12.3` 创建（本仓 main 的 `.venv`
  即 uv 建的，pyvenv.cfg 记录 uv = 0.11.6；用 uv 是沿用本机现状而非引入新工具链）。
- PyPI 直连不稳定（超时），最终以 main `.venv` 的 `uv pip freeze` 作为约束集安装成功。

## D2 — BASE SHA

`git fetch origin main` 后 `origin/main` 与本地 `main` 一致：
**BASE = `926f33354d17bb481cddc52c4f221160482e191a`**（与 prompt §3 所述基线相同，
侦察结论的行号已逐一复核，见 01-baseline）。

## D3 — geo-viz-engine / well-log-engine submodule 不重新 clone

`geo-viz-engine` 在主 checkout 有 1.1G 的工作区，且其 HEAD（`08851951`）与
BASE 记录的 submodule 指针完全一致。为省 1.1G 网络与磁盘，geoviz 子包以
editable 方式安装指向主 checkout 的 engine 目录（`/tmp/req-geoviz-main.txt` 重写
`requirements-geoviz.txt` 的路径前缀）。本 Goal 不改 engine 代码，共享安全。
仓库自身的 `run_env*.sh` 亦是同样的「geoviz 从 main 共享」约定。
well-log-engine 不在本 Goal 测试范围内，未安装。

## D4 — wayfinder / to-tickets 产物保留在本地，不发 GitHub Issues

Prompt 要求按 wayfinder→to-spec→to-tickets 流程走，但同时声明「本 Goal 不依赖
任何 CI、所有验证在本地完成」。本 Goal 的未知项已在侦察阶段通过直接读码全部
消解（见 D5-D8），不存在需要多人协同决策的开放问题；向共享 issue tracker
发布 5 张一次性 ticket 只增加外部表面积。决策：ticket 以本地文件形式保存在
`docs/development/ingest-io-v12/tickets/`，to-tickets 的本地文件模式是其一等公民
用法。此偏离会在 PR 与最终回报中明示。

## D5 — 「读 1 遍 + 写 1 遍」的可达边界（本 Goal 最重要的决策）

Prompt §0/§4.1 的目标「单次受管 RAW 导入 读1遍 + 写1遍」在 §4.1.4 的
「语义零变化」约束下**信息论上不可达**，证明如下：

1. **去重判定先于拷贝**：dedup 快路径要求在拷贝前知道 digest（`has_blob(digest)`），
   而 digest 只能来自对源文件的一次完整读。⇒ 拷贝路径至少有一次「拷贝前读」。
2. **诚实校验要求拷贝中哈希**：`known_sha256` 与实际字节一致必须在拷贝路径上
   验证（#1175 honest checksum；`test_wrong_known_checksum_is_rejected_honestly`
   钉死）。拷贝循环顺带计算哈希是零额外读的，但这次哈希发生在**第二次读**上。
   ⇒ 拷贝路径 = 拷贝前读（digest）+ 拷贝读（验证）= **至少 2 次读**。
   （若省掉拷贝前读、拷贝后再判 dedup，dedup 命中时已付出完整拷贝，且版本
   path 会落在 `raw/` 而非 `blobs/` —— 落盘结构与 manifest 双重语义变化，禁止。）
3. **两个完整文件 ⇒ 两次完整写**：非去重导入必须同时落地
   `{stage}/{asset}/{version}/{filename}` 与 `blobs/xx/<digest>`（`import_raw`
   文档语义「Every managed RAW import also registers its payload in the content
   store」）。硬链接被 `test_no_writable_hardlink_is_created` 与不可变性文档语义
   排除（st_nlink 会暴露结构差异，且共享 inode 扩大误写事故半径）；reflink
   不可移植到本仓主平台 Windows。⇒ **至少 2 次写**。

**可达最优**（本次实现目标）：

| 路径 | 现状 | 目标 | 手段 |
|---|---|---|---|
| 新内容导入（UI 漏斗） | 3R + 2W | **2R + 2W** | 消灭 `_place_blob_bytes` 对刚落盘 payload 的再读（读3），blob 与 payload 从同一次读分发写出 |
| 去重命中（UI 漏斗） | 2R + 0W | **1R + 0W** | 摘要新鲜度标记：同进程内新鲜哈希可免 dedup 分支的内容复核 |
| 去重命中（service API 任意 caller） | 2R + 0W | 2R + 0W（不变） | `test_same_size_different_content_never_adopts_existing_blob` 钉死未知来源 digest 必须内容复核 |
| 幂等命中（同路径同内容重导入） | 1R + 0W | 1R + 0W（不变） | — |

「写 1 遍」按同理不可达；二次写不再伴随额外读。此结论在 02-design 与
04-known-limitations 中展开，PR 中如实声明。

## D6 — dedup 信任边界：私有参数 `_sha256_verified`，沿 `_register_blob` 惯例

`place_managed_file` dedup 分支的 `_digest_of(source)` 复核是
`test_same_size_different_content_never_adopts_existing_blob` 明确钉住的
service 层契约（防 stale digest 静默链错 blob），**不能全局移除**。但 UI 漏斗的
digest 是同进程刚刚对同一文件算出的新鲜哈希，复核即重复读。方案：

- `place_managed_file` / `register_version` / `import_raw` 增加私有参数
  `_sha256_verified: bool = False`（命名沿 `register_version` 既有私有参数
  `_register_blob` / `_restore_payload_to` 的下划线惯例）。
- 为 True 时 dedup 分支跳过 `_digest_of` 复核（保留 size 相等检查与 OSError
  回退），拷贝分支照旧在拷贝中哈希并与 `known_sha256` 比对（TOCTOU 仍然闭合，
  且该哈希零额外代价）。
- 唯一置 True 的位置：`adapter.register_input` 在**本调用内**自己哈希出
  checksum 时（adapter.py `sha256_file_or_none(resolved_path)` 一处）。
  scanner/存量 metadata 来源的 digest 一律 False（行为与今天完全一致）。
- 为让 adapter 成为新鲜哈希的计算点，`lifecycle.register_resource_input` 不再
  在 checksum 缺失时自行补哈希，直接透传 `resource.checksum`（可能为 None）；
  adapter 的既有逻辑（`checksum is None and not external` → 自己哈希）接管。
  哈希总数不变（只是计算点从 lifecycle 移到 adapter），但外部链接（external）
  不再被 lifecycle 白白哈希一次——`link_external` 与 adapter external 分支
  从不消费该 checksum（已核实），纯浪费消除，无可见行为变化。

## D7 — blob 落盘改为「同读分发」（tee），临时文件放 blob 根目录

`register_blob=True` 的拷贝路径：单次读循环同时写 payload 临时文件与 blob
临时文件（各自 fsync），digest 出来后按现有顺序
`os.replace(payload_tmp → target)` → 诚实校验 → `os.replace(blob_tmp → blobs/xx/<digest>)`，
任一既有 blob 存在时丢弃 blob 临时文件（绝不覆盖，幂等语义与
`_place_blob_bytes` 一致）。blob 临时文件放在 `blobs/` 根目录（digest 未知
不能进 shard 目录；`scan_blobs` 跳过顶层非目录条目，孤儿临时文件不污染
digest 表；崩溃孤儿与今天 shard 内 `.blob-*` 同类）。两个目标各自保持
temp + fsync + rename + dir fsync + read-only 的全部原子性与只读标记。

## D8 — 目录导入并发：ThreadPoolExecutor + pool.map（保序），worker 预算沿用 scanner 的 governor 逻辑

`_collect_folder` / `import_files` 的逐文件元数据收集（stat + 轻量探针）改
线程池并发；`pool.map` 保序 ⇒ added/warnings/filtered 的顺序与串行版完全一致
（现有测试依赖 `sorted(paths)` 确定性）。每文件 try/except OSError 语义原样
移入工作函数。worker 数与 `scanner.py` 共用一个辅助函数（governor io_slots + 2，
[2,32]，回退 cpu_count+4）——提为共享函数而非复制，与 ADR 0056「哈希统一
实现防止行为分叉」同一理由。不引入新依赖（标准库 concurrent.futures）。
SQLite store 事务域不碰：并发只发生在纯文件系统元数据收集，catalog 提交仍
串行（register_imported_resources 的 chunked batch 语义不变）。

## D10 — 测试环境：主 checkout venv + PYTHONPATH 指向本 worktree（仓库既有约定）

PyPI 直连长时间挂起（另一会话的安装同样卡住），worktree 独立 venv 装不完。
改用本仓 `run_env*.sh` 的既有 worktree 测试约定：

```
env QT_QPA_PLATFORM=offscreen \
    PYTHONPATH=/home/kevin/projects/paleo-workbench-ingest-io-v12 \
    <main>/.venv/bin/python -m pytest -p no:randomly …
```

PYTHONPATH 先于 site-packages，`import paleo_workbench` 实测解析到本 worktree
（已验证：`paleo_workbench.__file__` 指向本 worktree；`test_catalog_dedup.py`
16 passed）。依赖来自主 venv（pinned 集与 BASE 一致）。受约束的独立 venv
安装在后台继续，若最终成功则在 PR 前用独立 venv 复跑关键测试双保险。

## D9 — 范围排除

- derived/result 注册路径（`register_result_asset`、run 产物）的 pre-hash 不动：
  那些摘要进入 run/artifact 记录，语义不同，不在本 Goal 声明范围内。
- `catalog/service.py` 缓存/事务框架、schema 版本、`_vendored/`、native、
  QGIS 桥：一律不碰。
- `scanner.py` 本体行为不变（仅提取 worker 预算辅助函数）。
