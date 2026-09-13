# 02 — 目标设计（ingest-io-v12）

> 输入：01-baseline 的实测数字 + 00-decisions D5-D8 的边界结论。
> 原则：Karpathy guidelines——最小改动、只动任务要求的线、每步可验证。

## 1. 现状数据流（改造前）

单次受管 RAW 导入（UI 漏斗：`data_page` worker →
`data_lifecycle_controller.register_imported_resources` →
`lifecycle.register_resource_input` → `adapter.register_input` →
`service.import_raw` → `storage.place_managed_file`）：

```
源文件 ──读1──> lifecycle sha256_file_or_none        (dedup/幂等键)
       ──读2──> place_managed_file 拷贝循环           (payload 临时 + inline hash)
                     │ os.replace → {stage}/…/file   写1
       ──读3──> place_blob → _place_blob_bytes(target)  ← 再读刚落盘的 payload
                     │ os.replace → blobs/xx/<digest> 写2
```

dedup 命中时（blob 已存在）：读1（lifecycle）+ 读4（dedup 分支 `_digest_of`
内容复核），0 次写。

## 2. 目标数据流（改造后）

```
源文件 ──读1──> adapter sha256_file_or_none          (dedup/幂等键；新鲜哈希)
       │
       ├─ blob 命中 + size 相等 + _sha256_verified ──> 直接引用共享 blob（0 写）
       │    （service API 的未经证实 digest 仍走 _digest_of 复核，契约不变）
       │
       └─ 未命中 ──读2──> place_managed_file 拷贝循环（inline hash = 诚实校验）
                     ├─ os.replace → {stage}/…/file   写1（payload）
                     └─ 同一次读的分发写出（tee）
                        os.replace → blobs/xx/<digest> 写2（blob）
```

- 读 3 遍 → **2 遍**（新内容）/ 2 遍 → **1 遍**（dedup 命中）
- 写 2 遍不变（两个完整文件是语义约束的最小值，见 D5 证明），但第二次写
  不再伴随第三次读。
- 幂等命中（同路径同内容）保持 1 遍读。

## 3. 改动点（全部为外科手术式修改）

### 3.1 `catalog/storage.py::place_managed_file`

1. 签名增加 `_sha256_verified: bool = False`。
2. dedup 分支：`known_sha256` 命中已有 blob 且 size 相等时，若
   `_sha256_verified` 为真则跳过 `_digest_of(source)` 复核（新鲜度契约写入
   docstring：digest 必须来自本进程对同一 source 的即时哈希）；否则照旧复核。
   OSError 回退到拷贝路径的行为不变。
3. 拷贝分支：读循环同时写 payload 临时与 blob 临时（仅当 `register_blob`），
   两者各自 flush+fsync；digest 出来后：
   - `os.replace(payload_tmp → target)` + dir fsync（顺序不变）
   - 诚实校验（inline hash vs `known_sha256`）不变，失败时清理两个临时文件
     并抛 `CatalogError`
   - `_make_readonly(target)` 不变
   - blob 侧：`has_blob(digest)` 命中 → 丢弃 blob 临时（绝不覆盖既有 blob）；
     未命中 → mkdir shard 目录、若目标已被并发放置则丢弃临时、否则
     `os.replace(blob_tmp → blobs/xx/<digest>)` + dir fsync + `_make_readonly`
4. blob 临时文件放在 `blobs/` 根目录（digest 在流式过程中未知，进不了 shard
   目录；`scan_blobs` 跳过顶层非目录条目，孤儿临时不污染 digest 表）。
5. `_place_blob_bytes` / `place_blob` 公共 API 原样保留。

### 3.2 `catalog/service.py`

`import_raw` / `register_version` 增加 `_sha256_verified: bool = False` 私有
参数（命名沿 `_register_blob` 惯例），透传至 `_build_version` →
`place_managed_file`。事务、staging lease、`_save`、回滚一概不动。

### 3.3 `catalog/adapter.py::register_input`

managed 分支调用 `import_raw` 时，若 checksum 来自本调用内
`sha256_file_or_none(resolved_path)` 的新鲜计算，则传
`_sha256_verified=True`；来自调用方传入的 checksum 一律不标记。
幂等/桥接/external 分支不动。

### 3.4 `catalog/lifecycle.py::register_resource_input`

不再在 checksum 缺失时自行补哈希；直接透传 `resource.checksum`（可为 None）。
adapter 的既有 `checksum is None and not external → 自己哈希` 逻辑接管，
哈希总数不变、计算点后移到知道新鲜度的地方。external 资源不再被无效哈希
（`link_external` 与 adapter external 分支从不消费该值，已核实）。

### 3.5 `resources/import_service.py` + `resources/scanner.py`

- `scanner.py`：把 governor 预算块提取为模块级 `default_workers()`（行为不变）。
- `import_service.py`：`_collect_folder` / `import_files` 的逐文件采集改
  `ThreadPoolExecutor.map`（保序）；每文件工作函数内部保持原有 try/except
  OSError 语义与 warning 文案；结果列表按输入顺序重组，与串行版逐字节一致。

## 4. 明确不变的东西（验收时逐条核对）

| 语义 | 验证手段 |
|---|---|
| payload temp+fsync+os.replace 原子性 | 代码走查 + `test_catalog_crash_safety.py` |
| 落盘只读标记（payload 与 blob） | `test_catalog_dedup.py` 既有断言 |
| `known_sha256` 与实际不符 → `CatalogError` | `test_wrong_known_checksum_is_rejected_honestly` 等既有测试 |
| dedup 命中 O(1) 免拷贝、版本指向 blob | `test_import_of_present_digest_is_copy_free` |
| 未知来源 digest 的内容复核 | `test_same_size_different_content_never_adopts_existing_blob` |
| `catalog.json` manifest 行为 | 既有 service/lifecycle 测试 |
| 目录导入结果顺序 | 新增确定性测试 + 既有 `test_data_import_service.py` |
| catalog 事务/SQLite 串行提交域 | 不触碰（diff 审查） |

## 5. 回归钉设计（`tests/test_ingest_io_v12.py`）

1. **读/写遍数钉**（T5）：以 `Path.open`（'rb'、按路径过滤）计源读与
   payload 再读、以 `tempfile.mkstemp`（artifacts 目录内）计写遍数。
   - UI 漏斗新内容导入：src reads == 2，payload re-reads == 0，writes == 2。
   - UI 漏斗 dedup 命中：src reads == 1，writes == 0。
   - service API dedup（未经证实 digest）：src reads == 2（复核保留）。
2. **反向对照**：注入人为回归（把 dedup 命中路径强制再哈希一次 / 把 blob
   落盘改回再读 target 的旧实现等价物），断言计数器读到不同数字——证明
   主断言对回归敏感，不是空断言。实现方式：monkeypatch
   `storage._digest_of` 使其在 dedup 场景额外执行一次真实哈希，计数应从
   1 变 2。
3. **并发确定性钉**：monkeypatch `_probe_summary` 注入随机延迟，断言
   `import_folder` 的 added/warnings/filtered 顺序与无延迟串行结果一致。
4. 全部断言通过仓库 tautological 守卫（无 `or True` / 恒真式）。
