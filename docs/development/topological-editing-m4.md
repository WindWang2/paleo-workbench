# 拓扑编辑迁移 M4 检查器——实施记录（2026-09-12）

> 规格 §8 → §5。M4 内容：四规则 + 面板 + 保存门禁合并 + 双豁免 + 修复交互。
> 退出标准：场景 12、13、14、16 通过；M3 回归绿。

## 落地清单

| 实现件 | 位置 | 说明 |
|---|---|---|
| 桥 run/fix | `QgisMapStack::runGeometryChecks` / `fixGeometryError(s)` / `highlightCheckerErrors` | analysis：`QgsGeometryOverlapCheck` / `QgsGeometryGapCheck` / `QgsGeometryIsValidCheck`；工区余量 = `工区面.difference(union(相带))`（建议性导航，不改几何）。池用 `QgsVectorLayerFeaturePool` 子类（索引 + 写编辑缓冲）。**禁止** `QgsProject::instance()`。 |
| 有效性修复 | 同上 `applyCheckerFix` | `QgsGeometryIsValidCheck` 无 resolutionMethods；桥侧 `makeValid`。 |
| 批量修复 | `fixGeometryErrors` | 一层一宏 `"Fix geometry errors"` 包多轮裁切；一次 undo 整体回退。 |
| 宿主检查器 | `mapping/topology_checker.py` | 上次结果、忽略键（规则+层+要素+对方）、缝隙白名单、`run_for_commit`。 |
| 门禁合并 | `native_edit_session.commit_all` + `composite_editing.save_edits` | 桥 `run_geometry_checks` 优先；旧桥回落 `validate_records`。零**未忽略**错误放行。 |
| 双豁免持久化 | `mapping_workspace["topo_checker"]` | 忽略列表 + allowed_gaps GeoJSON，随 `sync_to_project`。 |
| 面板 | `ui/workstation/topology_checker_panel.py` | 错误列表、规则过滤、灰显忽略、点击缩放/高亮。挂综合编修画布下方（默藏；拓扑 chip 打开），不嵌 `QgsGeometryCheckerDialog`。 |
| 场景 16 | `VectorLayer.apply_committed_delta(..., gestures=)` | 提交审计含手势溯源；台账对齐仍走 M0 `align_publish_ledger`。 |
| 版本 | `bindings.cpp` `__version__` | 0.9.0a0 → **0.10.0a0**。`setup.py` 增加 vendor `src/analysis` include（`qgis_analysis.h`）。 |

## 验收证据

- `tests/test_qgis_topo_m4_checker.py`（4 项，真桥）：场景 12（余量高亮 + 导航不改几何）、重叠检测、is_valid + makeValid、场景 14（全部修复清空重叠 + 一次 undo 回退）。
- `tests/test_topo_m4_checker.py`（5 项，宿主）：场景 13（忽略放行 / 恢复再阻断）、双豁免持久化、面板灰显+缩放信号、场景 16（台账 authoritative + 审计手势）、检查器门禁 API。
- M3/M2/M1 真桥回归：`test_qgis_topo_m{1,2,3,4}_*` **20 过 / 0 失败**。
- 宿主回归：M0/M1/M3 + inspector/dock/shell/composite_editing 绿。

## 关键约束（继承 M2/M3）

1. 桥侧读画布挂载工程 `project()`，不读单例。
2. shutdown：先 `unsetMapTool` → **无条件**释放检查器会话（池持层指针；authoring 走 `QgsProject::instance()` 时同样必须先 reset）→ 摘层摘工程。
3. 测试 teardown：`try/finally` 里 `set_map_tool(pan)` + `roll_back_mirror_layer`。
4. 线悬挂点（`QgsGeometryDangleCheck`）二阶段，M4 不做。
5. 不移植 `src/plugins/geometry_checker/`（UI 壳，依赖 `QgisInterface`）。
6. 工区余量：宿主把 `project.workarea.boundary` 写入 checker.workspace；缺则桥用画布范围兜底。
7. 面板徽章 = 未忽略条数 + `last_run_at`；单条右键出 check 声明的方法列表。

## 后置（M5）

- Python 拓扑服务下线（`propagate_shared_vertex` / `CompoundUndoGroup` / `TopologyService` 传播面）。
- 二阶段线层悬挂点规则。
