# 15 — Decisions（每个非显然选择）

分支 `feat/cpp-conv-15-catalog-gc`（BASE = origin/main `35987e13`）。

## D1 路径适配（任务书 vs 本机现实）

任务书给出的仓库根 `/home/kevin/projects/paleo_project/main` 在本机不存在；实际仓库是
`/home/kevin/project/paleo-workbench`（git remote 相同：WindWang2/paleo-workbench）。
worktree 落在 `/home/kevin/project/worktrees/cpp-conv-15-catalog-gc`（仓库外同级，未放入
主工作区）。goal-loop/karpathy skill 路径按仓库内 `agent/skills/` 解析。其余流程（分支名、
BASE、账本、验收）不变。

## D2 「entity view 分页」的落点 = catalog 文档上的稳定分页（Python paged 契约）

Python 的 `EntityViewService` 是 **project 实体视图装配层**（输入含 pydantic
ProjectDocument 的 wells/seismic_surveys/entity_asset_links），而 C++ catalog 库不拥有
project 实体模型（实体绑定投影在 data_suite 快照 + A 线）。任务验收写的是
「entity 列表分页稳定」；v3-verification §7 把「entity view/分页查询/name_search」并列为
一个未迁移面。因此本切片把可对账、可验收的核心落在：**CatalogDocument 上的
`search_assets_page` / `count_assets`（_paged_rows_from_document 与 SQL 页面的并集语义，
20 键行形状、排序白名单、NULLs-first、keyset cursor）**。RoleSlot/well_view 等 UI 装配
不含科学/存储语义且其输入模型在 C++ 侧不存在——不伪造，不在本片实现（诚实边界，
PR 正文如实声明）。

## D3 实现为自由函数，不改 repository.cpp

GC/dedup/分页全部实现为 `pwb::catalog` 命名空间内的**新自由函数**（gc.hpp/dedup.hpp/
entity_view.hpp + 三个新 .cpp），输入 = `project_path + CatalogDocument`（加载自
CatalogRepository 既有读路径）。既有 repository.cpp/sqlite.cpp/models.cpp **一行不改**
（§6「尽量不改」→ 实际零改）。telemetry（Python gc.sweep 事件）不移植：它是旁路日志，
不属于本切片验收的存储契约，C++ 侧也无 telemetry 模块。

## D4 sweep 的并发重校验在 C++ 单写者模型下退化为一次候选校验

Python sweep 64/块、每块锁内重算 referenced+leased（plan→sweep TOCTOU 防护）。C++ 侧
GC 是无服务对象的无锁纯函数，调用方持有一份不可变 document 快照；sweep 前对**每个
候选**重做 referenced/leased 校验（同一次），语义等价于「单线程下无并发窗口」。跨进程
互斥由既有单写者协议承担，不在本片重复造锁。

## D5 staging lease 心跳用 ISO 字符串比较 + fixture 用极值时间戳保证确定性

Python `active_staging_targets` 用 SQL 字符串比较 `heartbeat_at > now−3600s`（ISO 秒精度
字典序=时间序）。C++ 同口径：`document.staging_leases` 行上做同样的字符串比较。
冻结 fixture 不能依赖「生成时刻」的新鲜度，因此生成器写两条租：守卫用
`heartbeat_at="9999-12-31T23:59:59"`（永新鲜）、死租用 `"2000-01-01T00:00:00"`
（永久过期）——与真实时间无关，两侧判定确定一致。TTL 常量 3600.0 与 db.py 对齐。

## D6 name_search / tag 归一化沿用仓库既定的有界 ASCII 折叠边界

Python 是 NFKC+casefold。C++ catalog 写侧已有 `search_fold`（ASCII 大小写折叠，非 ASCII
原样；与 CJK 等无大小写脚本同 Python）。本切片**沿用该口径**并新暴露
`normalize_search_name()` 供分页 text 过滤复用；tag 归一化同函数 + 空白折叠
（Python normalize_tag_name 的 split/join）。fixture 的 text/tag 用例全部落在该有界包络内
（ASCII 名 + CJK 无大小写名），非 ASCII 大小写差异不进 oracle（如实边界，与
data.catalog_write 既有声明一致）。

## D7 行 metadata 字段的对账按解析后 JSON 语义，不按字节

Python 行的 `metadata` 是 `json.dumps(..., ensure_ascii=False)` 文本（默认分隔符含空格）；
nlohmann dump 无空格。该字段的字节级 parity 是 Python 内部契约（index 行=scan 行），
跨语言对账按「parse 后语义比较」执行，冻结 oracle 存解析后的对象。其余 19 键均为
标量/原样字符串，直接字节比较。

## D8 oracle 冻结形态：整棵工程树 + oracle.json，C++ 测试拷贝后对账

生成器 `tools/oracle/generate_catalog_gc_fixtures.py` 用**真实 Python 服务**
（`DataCatalogService.open/import_raw/trash/...` + `catalog.gc` + `catalog.dedup` +
`search_assets_page`）构建 4 个场景工程树（含 catalog.sqlite + payload + 孤儿 + 租行），
把 plan/sweep/dedup/分页结果冻结为 `oracle.json`（路径归一为 project-dir 相对 POSIX，
大小、digest、行集、计数、报错文案含占位替换）。C++ 测试把树拷到临时目录，用
CatalogRepository 读同一 sqlite，跑 C++ 实现，与冻结值对账。凡「会删除」的断言
（sweep 变体）在生成器与测试里各自基于**独立副本**执行，避免顺序耦合。
报告类断言按 (kind, rel_path, size) **集合**比较（Python rglob 顺序非契约）。
fixtures/manifest.json 属旧 fixture 管线，不掺入本片产物（生成器自述）。

## D9 place_managed_file 的错误映射到既有 ErrorCode 词表

- unsafe id → `unsafe_id`，报错文案与 Python 逐字同（含 Python repr 的单引号）；
- 目标已存在（Python FileExistsError）→ `immutable_version`（v3-contracts §2
  「原版本不覆盖（目标路径已存在 → immutable_version）」的既定映射）；
- 校验和不符（Python CatalogError）→ `invalid_argument`，文案逐字
  `"Checksum mismatch for {source}: caller reported {known}, actual {actual}"`（source 绝对
  路径，测试按 `<ROOT>` 归一后比较）。
报错文案进 oracle（§2.5「含报错文案」）。

## D10 CMake 追加方式

无新增子目录，因此不需要新的 add_subdirectory option 门（根 CMakeLists 零改动；
`PWB_BUILD_CONV_15` 传参无害但不被消费——如实在 PR 说明）。两处**纯追加**：
1) `libs/catalog/CMakeLists.txt` 末尾 `BEGIN/END CONV-15` 块内
   `target_sources(pwb_catalog PRIVATE src/gc.cpp src/dedup.cpp src/entity_view.cpp)`；
2) `tests/cpp/data/CMakeLists.txt` 末尾 `BEGIN/END CONV-15` 块内追加
   `pwb_data_test(data_catalog_gc catalog_gc_test.cpp data.catalog_gc)`。
不触碰任何既有 CONV 块/行。

## D11 清扫的只读位重试（Python PermissionError→chmod 分支）在 POSIX 的取舍

POSIX unlink 不受只读位阻拦，Python 该分支是 Windows 语义。C++ 实现保留一次
`chmod(+u+w)` 重试（error_code 路径，行为对 Windows 正确、POSIX 恒短 路），失败按
Python 口径静默跳过（保守：下轮再扫）。

## D12 blob_metrics 的 refs 只数「managed 且 sha256 ∈ 在盘 blobs」的版本

（易错点记录）`bytes_deduped` 的引用计数不是 referenced_digests 的补集运算，而是逐版本
累加且**以在盘 blob 为限**；keep∩blobs / blobs−keep 才是 referenced/unreferenced 计数。
oracle 用 2 版本共享 1 blob + 1 不可达 blob 的场景把四个数全部钉住。

## D13 分页 limit/offset/未知 order 的钳制与回退逐条对齐

`max(0, int(limit/offset))`（负值→0）；未知/空 order_by → name 序；`after` 仅
name/None 序生效；`name_desc` 用两趟稳定排序复刻 `(name DESC, id ASC)`；
stage/size/version 序在无 current 版本（NULL）时排最前（SQLite ASC NULLs first，
catalog-scale-v5 Review1-P2 的对齐教训）。

## D14 safe-id 门禁的 Unicode 包络（R2 对抗审核 P1-2 处置）

Python `is_safe_entity_id` 用 `str.isalnum()`（Unicode 感知），非 ASCII 资产 id
（如迁移产生的 `asset_资产1`）可到达 place_managed_file。C++ domain 层的
`is_safe_storage_segment` 是既有 ASCII 实现（不在本片写入范围，不动）。dedup.cpp
内的门禁按 Python 语义放宽为：非空、无前导点、ASCII 取 `[A-Za-z0-9._-]`、其余
接受**格式合法的非 ASCII UTF-8 序列**（声明的超集：无 Unicode 类别表，ASCII
标点混入非 ASCII id 时 C++ 接受/Python 拒绝，差异已知）。路径安全不变：`/`、
前导 `.` 均为 ASCII，仍被拒绝；多字节 UTF-8 续字节 ≥0x80 不可能含 `/`。
用例：`asset_资产1` 落盘成功 + `资产/../evil` 仍被拒（均入 oracle）。

## D15 其余 R2 审核处置清单（2×P2、5×P3 全修）

- P1-1 空白折叠：`normalize_search_name` 改为纯折叠（空白原样，db.py:287 语义），
  新增 `normalize_tag_name`（折叠+空白收缩，models.py:272 语义）仅供 tag 匹配；
  oracle 新增 `text_whitespace_verbatim`（前导空格 needle → 0 行）。
- P2-3 size 序 NULL 判定按**列值**而非版本存在性（live 版本 size_bytes=NULL 也
  进 NULL 组）；oracle 新增 live-NULL 行（well_005 size=None）钉死顺序。
- P2-4 读流 badbit：place_blob / place_managed_file 拷贝循环后检查 `in.bad()`，
  失败删 temp 并报 io_error（Python 读循环 OSError 语义）。
- P3-5 unsafe-id 报错文案实现 python repr 引号选择（含 `'` 无 `"` → 双引号包裹，
  转义反斜杠与所选引号）；oracle 新增 `ev'il` case。
- P3-6 `type` 改 `std::optional<std::string>`（`""` 也过滤，两侧一致）；
  oracle 新增 `type_empty_string_filters_all`。
- P3-7 asset_ids 不再丢弃空串条目（对齐 Python 文档回退语义；C++ 即回退侧）。
- P3-8 `make_read_only` 只移除写位（保留 exec/setuid，storage.py `mode & ~S_IW*`）。
- P3-9 blob temp 提交失败改为放置失败（io_error，storage.py `_commit_blob_temp`
  re-raise 语义）；temp 命名改 O_EXCL 预留（POSIX；Windows 依赖单写者协议）。
