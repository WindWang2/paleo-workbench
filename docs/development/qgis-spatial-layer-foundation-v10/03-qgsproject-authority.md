# 03 — QgsProject 权威边界（V10）

## 1. 两个「工程」的分工（D7）

| | Paleo ProjectDocument | QGIS QgsProject |
|---|---|---|
| 角色 | 科学/业务权威 | 运行时 GIS 状态持有者 |
| 内容 | DataVersion、provenance、memberships、maturity | layers、layer tree、CRS、transform context、ellipsoid、snapping config（per-canvas 推送） |
| 生命周期 | 持久化文档（保存/加载/版本化） | 进程内运行时对象 |

`set_project_crs`（composite_document.py:627）只把运行时真值推给
QgsProject——**单向推送，不回写** ProjectDocument：文档的 CRS 字段仍是
科学记录（含 V9 D1 的未声明判词语义），QgsProject 侧是渲染/测量/变换
的消费事实。02-crs-transform.md §3 记录推送顺序（destination 先、
project CRS 后）。

## 2. 工程实例的分布

- **authoring 栈共享 `QgsProject::instance()`**——编辑会话、捕捉配置、
  拓扑编辑状态都落在同一工程实例上（单活 authoring shim 纪律，
  04-layer-registry.md §3）。
- **display 画布各自持有独立 project**（既有架构，V10 不变）。
- edit_tools 的 measure 读取 owning-project 上下文——跨 display 栈触发
  时存在 wrong-context 泄漏（读到 `QgsProject::instance()` 而非所属
  画布工程）：记录为已知限制（12-known-limitations.md 第 1 条），
  修复需 C++ 侧 per-canvas project routing，本批不做。

## 3. snapping 配置持久化（D8）

权威结构不变：画布 `snappingUtils` 投影 + Python `SnappingService`
双层（V8 既有）。V10 新增**持久化通道**：

- 快照写入 `mapping_workspace["snapping"]`——`snapshot_state()` /
  `restore_state()`，`schema_version: 1`（模式版本化，后续演化不读
  旧格式时显式拒载）。
- 重推钩子：stage 切换后 `repush_snapping()`（composite_document.py:1255
  调用点）；工程 `load_from_project` 恢复快照后同样重推——保证 Python
  权威态与 C++ 画布投影一致。
- 回归钉：`tests/test_snapping_persistence_v10.py`。

关闭 00-baseline.md §B.9（工程重载丢 per-layer 覆盖）。
