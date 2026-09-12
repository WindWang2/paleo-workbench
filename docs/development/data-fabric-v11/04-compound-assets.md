# 04 — Compound / Multi-file Assets

## 1. 语义

一个**逻辑资产**的某个**版本**由多个**物理成员文件**组成：

- shapefile family（.shp+.shx+.dbf+.prj+.cpg）
- 地震 geometry sidecar（体积 + 几何描述对）
- 多段导入（multi-part import）
- 模型工件 bundle（weights + schema + preprocessing）

与"一口井多个业务资产"严格区分（后者见 03）。

## 2. 模型（`catalog/models.py`）

```python
class VersionMember(BaseModel):
    name: str                # 成员显示名/键（版本内唯一）
    rel_path: str            # 相对版本 payload 目录的 POSIX 路径（禁止 .. 逃逸）
    member_role: str = ""    # data | index | attributes | projection | sidecar | part | manifest ...
    ordinal: int = 0
    required: bool = True
    sha256: str | None = None
    size_bytes: int | None = None

class DataVersion(BaseModel):
    ...
    members: list[VersionMember] = []   # 空 = 传统单文件版本
```

- `DataVersion.path` 语义扩展：members 非空时指向**成员目录**（managed）。
- `aggregate_sha256(version)`：`sha256("\n".join(f"{m.name}:{m.sha256}" for m in sorted members))`
  —— 版本级聚合完整性凭据，写入 `version.sha256`。
- `DataVersion.size_bytes` = 成员 size 之和。

## 3. 存储（`catalog/db.py`）

新表（幂等 DDL，见 02/D3）：

```sql
CREATE TABLE IF NOT EXISTS version_members (
    version_id TEXT NOT NULL,
    name TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    member_role TEXT NOT NULL DEFAULT '',
    ordinal INTEGER NOT NULL DEFAULT 0,
    required INTEGER NOT NULL DEFAULT 1,
    sha256 TEXT,
    size_bytes INTEGER,
    PRIMARY KEY (version_id, name)
);
```

接入点：`apply_changes` versions 循环（重写该版本成员行）、`_rebuild_once`、
`_load_document_once`/`list_version_models_for_asset`（二次读挂载）、
`reconcile`（成员漂移检测 → 标记 version dirty）、`_DELETE_ORDER`。

## 4. 服务 API（`catalog/service.py`）

- `register_bundle_version(asset_id, member_dir, members, stage, ...)`：
  校验成员存在/唯一名/无逃逸 → 目录落位 → 逐成员 sha → 聚合 sha →
  单事务提交（复用 `register_version` 内部路径扩展 move-directory 语义）。
- `verify_bundle_integrity(version_id)`：逐成员重算 + 聚合比对 →
  按成员报告 missing/modified，聚合进 IntegrityStatus。
- 工作副本：`create_working_copy` 对 bundle 版本拷贝整个成员目录；
  commit 时按目录 move。
- trash/purge：整目录进 trash/（复用现有目录搬移路径）。
- `detect_file_family(paths)`：静态启发（shp 族、同名多扩展），供 ingest
  分组建议 —— 只建议，不自动合并。

## 5. shapefile family 专项

导入 .shp 时扫描同 stem 的 .shx/.dbf/.prj/.cpg/.qix；用户确认后作为
bundle 注册（required: shp/shx/dbf=True，prj/cpg/qix=False）。
外部引用（workstation_reference_layers）保持不复制语义不变 —— bundle
只针对**入库**数据。

## 6. 避免过度 schema 化

- 不为成员间依赖建表（shapefile 内部依赖由 required 标记表达）。
- 不做成员级 lineage —— lineage 粒度保持版本级。
- 成员 role 是受控词表（member_role_vocabulary），但允许自由扩展值
  （未知值原样保留，UI 归入 other）。
