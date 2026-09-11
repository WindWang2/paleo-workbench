# 02 — CRS 链与提交守卫（V10）

## 1. `mapping/crs_chain.py` 判定表（D4）

`evaluate_commit_guard`（crs_chain.py:43，判定词 `GuardVerdict`）
是数字化提交的单一守卫真源。判定按「存储侧声明 × 画布侧声明」展开：

| storage CRS | canvas CRS | 判定 |
|---|---|---|
| 已声明 | 已声明，相等 | **allow**（同帧直写） |
| 已声明 | 已声明，不同 | **reject**（跨帧提交拒绝） |
| 已声明 | 未知 | 运行时 CRS-capable：**fail-closed**（拒收）；运行时不 capable：V9 诚实 no-compare（降级放行，带判词） |
| 未声明 | 已声明 | **allow**（raw frame——层本就无 CRS 语义） |
| 未声明 | 未声明 | **allow**（双 raw frame） |

「未知不比对」是 V9 守卫的既有语义（docs/development/qgis-geological-authoring-v9/09-known-limitations.md
第 1 条）；V10 的变化是：运行时 capable 的环境下不再降级——proj.db
供给到位（01-qgis-runtime.md §4）后，未知即拒绝。

## 2. `runtime_crs_capable()`（crs_chain.py:132）

能力事实来自 `qgis_runtime.health`（`probe_qgis_runtime` 的 CRS 探针
面，01-qgis-runtime.md §3），**进程缓存**——首次探测后不再重复构造
探针栈（12-known-limitations.md 第 8 条记录一次性代价）。

## 3. qgis_mirror 侧：destination 恒推送 + project CRS（D5）

- `set_destination_crs` 现在**恒被调用**（qgis_mirror.py:445）——空串
  同样推送：切工程后清除上一工程残留的目标 CRS，QGIS 进入 no-OTF
  raw rendering，杜绝陈旧 CRS 下的静默变形。
- destination 之后推送 `set_project_crs`（桥 0.6.0a0
  `project_crs_push`；宿主入口 composite_document.py:627 /
  layer_tree_panel.py:269）：C++ 侧
  `QgsProject::setCrs(crs, adjustEllipsoid=true)`——椭球测量分支
  （`PwbMeasureTool` 的 QgsDistanceArea 椭球链）第一次真正激活，
  关闭 V9 限制 #3（测量椭球依赖 QgsProject ellipsoid 而工程从不配置）。

## 4. 数字化 scratch 层去 quiet-4326（D6）

无效画布 CRS 时，scratch 层创建**不带 `crs` 参数**（raw frame），
绝不再回填 EPSG:4326（桥 `digitize_scratch_honest_crs` flag）。
`_capture_layer_crs` 解析 `layer.crs`，缺失时回退 `project_crs`
（§3 推送后该值有了真源）。

## 5. quiet-4326 盘点变更（存量消费点）

| 位点 | V10 行为 |
|---|---|
| geological_pipeline models + `extract_factors` | 默认值改 ""（不再 4326）；服务边界 `resolve_crs` 带**记录在案的 fallback**（empty→4326 由 `tests/test_mapping_crs_idw.py` 钉住——服务边界外的回填是显式契约，不是静默猜测） |
| `well_location_xml._crs_from` | 不再依 lon/lat 形状猜 4326；返回 "" → `CoordinateStatus.UNTRANSMED` 透传（未变换状态可见） |
| `MapDocument.crs` | wire 默认值保留（持久化兼容面，V9 D1 边界裁定维持），本文档记录在案 |

## 6. 测试

`tests/test_mapping_crs_idw.py` 的 descriptive-alias 用例更新为
canonical authid——main 上该用例曾红（散文式 CRS 别名形态在守卫处
假拒绝的镜像问题）；`crs_contract` 归一化是比对真源链
（docs/development/qgis-geological-authoring-v9/03-decisions.md D1），
用例钉 canonical 形态而非别名形态。
