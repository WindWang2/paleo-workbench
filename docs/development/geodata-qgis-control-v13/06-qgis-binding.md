# 06 — QGIS Binding（W-I，V13）

## 1. 绑定模型

见 02 §2。核心判据复述：**唯一 join key 是 `pwb/doc_id`**；
catalog 身份只活在 Python 域（membership + 发布快照），QGS 对象上
不建立第二身份（防 QGS 文件被外部编辑后出现两个"权威"）。

## 2. 双向查询

- **图层→数据**：`layer_domain_status(layer_id)`（composite seam）→
  membership.source_version_id → get_version/get_run →
  「数据来源（资产 vN（stage））/生成方式（run op；manual_edit 标注
  人工修改）/上游输入 N 个/校验和前缀」。无绑定不显示（不编造）。
- **数据→图层**：`usages_of_version/asset`（source_usage）→
  DataPage Inspector 行 + harness `data.map_usage` action +
  impact 预览的地图用途段。三处同源。

## 3. 生产写入覆盖（V13 补齐后）

| 路径 | pin 值 |
|---|---|
| phase1 建稿 | RAW 记录的 source_version_id（既有） |
| factor grid/contour/classification/uncertainty/QC 子层 | task.grid_artifact_version_id（V13） |
| factor 井点输入层 | 不 pin（源是井数据，不伪造） |
| 融合 likelihood/confidence/variance 子层 | descriptor.artifact_version_id ∥ summary.catalog_version_id（V13） |
| 融合初稿 | summary.catalog_version_id（V13） |
| 重算后重绑 | register_layer 覆盖（E2E §16 步） |

## 4. 边界诚实

- 约束线图层走 content fingerprint（constraints_sync），
  `binding_kind="content_fingerprint"`，不冒充 catalog_version；
- QC/分析辅助/用户通用层创建时无版本可 pin → 留空（UNKNOWN）；
- 版本被回收后的图层 → 「版本缺失（可能已被回收）」。
