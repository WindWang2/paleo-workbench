# CONV-26 — Decisions（数据/工作区/目录/项目生命周期闭环）

分支 `feat/cpp-data-workspace-catalog-closure`；BASE `origin/main@ff67dcf3`；对照 26-scope.md。

## D1 井名 header 提取冻结在"引擎缺失回退"分支

`_extract_well_name` 依赖 geoviz（LAS/WITSML 预览引擎，PySide6 链）。oracle 生成器阻断
`geoviz` 导入后冻结回退分支（目录提示链）为长期语义——与 CONV-19 对解析引擎的边界
声明一致。真引擎接入后两侧同步升级。后果：井身份匹配 confidence 走 medium/low 档，
永远不出现 header/high 档。

## D2 normalize_well_name 有界折叠（沿用 CONV-15 D6 边界并细化）

ASCII casefold + ASCII 空白 + ASCII 标点 `_ , . ( ) [ ]` + Python 正则点名的 7 个
多字节分隔符（– — · （ ） 【 】）。**未覆盖**：Unicode `\s` 的其余成员（NBSP U+00A0、
ideographic space U+3000 等）与 NFKC 折叠引入的全角变体（U+FF0D 等）。即
`"w－01"`（全角连字符）在 Python 侧与 `"W-01"` 同键、C++ 侧为不同键——井会被提议为
new_entity 而非匹配。ASCII/CJK 无格输入下两侧逐字节一致；全量 Unicode 表待后续
（与 CONV-15 D6 同源决策，非本片回归）。

## D3 execute 的事务粒度：逐项一事务（非 Python 的 64 条批）

Python `batch_save` 以 64 条为一批提交；C++ CatalogRepository 无脏集批机制，每个
导入是自己的 `import_raw_transaction`（all-or-nothing）。粒度更细、部分进度更安全；
中断恢复契约不变（幂等重跑按 (source, sha) 对跳过）。chunk_size 保留为取消/进度
粒度。oracle 对账证明可观察结果一致。

## D4 oracle 的确定性掩码契约

生成器与 C++ 回放应用同一掩码器：`<kind>_<12hex>` id → `kind#首见序号`（全文档共享
计数器，冻结顺序 plan→report→page→sections）；ISO 时间戳 → `<TS>`；场景根 → `<ROOT>`；
树文件列表里的 id → 无计数 `<ID>` 后排序（原始排序键含随机 id 本身不可复现）。
分页行在**同名 tie 内**按内容稳定排序（SQL 的 id 尾序对同名行是随机的，Python 侧
同样不可复现）。metadata TEXT 列按解析后语义比较（CONV-15 D7）。生成器双跑
oracle.json sha256 相等为确定性证明。

## D5 fixture 可移植性：相对标记 source_uri

种入的重复资产 identity 键含绝对路径。fixture 的 catalog.sqlite/catalog.json 中
source_uri 以固定相对标记 `__PWB_INGEST_ROOT__` 存储；生成器执行区与 C++ 回放各自
在计划构建前把标记重写为本方 incoming 根（UPDATE replace）。提交树不含任何绝对
路径，任意 checkout 位置可回放。

## D6 save-as 失败路径的文档恢复

rebase 文档段在目标 JSON 落盘前执行；失败（暂存 catalog 改写失败 / 目标保存失败）
时反向 rebase 回旧位置并回滚暂存（对齐 Python except 分支的 `_rebase_*_artifact_
paths(target, old_path)`）。成功路径下旧 session 视为已终结：**提交迁移前**显式关闭
旧 session 的读写 sqlite 句柄（Windows 不能删除打开文件；Python 同位先 close），
commit() 的布尔结果如实反映到 artifacts_relocated（False = 目标已持久但源残留）。

## D7 rebind_to_version 写时 kind 强制

Python `register_layer` 在写入时把"有 pinned version 无显式 kind"强制为
`catalog_version`；C++ 侧同样在写时存储 `catalog_version`（repair 亦然），使跨语言
读者看到一致 kind。`effective_binding_kind` 的读侧 V13 规则保留为旧文档补偿。
成员时间戳不再虚构：created_at 未知保持 ""（Python `existing or ""` 语义），仅
bound_at 在 pin 变化时盖戳。

## D8 local-build-gate.sh 的门禁偏离

共享 flock 被主 checkout 的 vendored QGIS 长构建（数小时级）占用时，本 worktree 的
小规模构建改走本地封装：保留门禁实质（-j2 上限、worktree 内单一重型构建——
`<build>/.local-gate.lock` flock、MemAvailable ≥ 8GiB 准入、BuildDir 必须在本
worktree/build 下），不取共享锁以免死锁。共享门禁可用时仍优先使用。

## D9 明确不做（如 scope 所列）之外的追加边界

- `rebase_artifact_paths` 对 `model_versions.artifact_uri` 做机械前缀改写（save-as
  迁移的维护性动作，Python 同位语义），**不构成** models/model_versions 读模型的
  移植——注册表读模型仍在 scope 之外。
- staging_leases 写路径未实现；ingest 执行的单写者假设沿用 kernel 既有协议。
- `asset_ids_for_entity` 的主选择扫描逐项线性（与 Python 相同的 O(N×L)，未优化）。
