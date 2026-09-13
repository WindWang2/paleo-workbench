# 拓扑编辑二阶段——线约束 / 综合相 / 注记 + 悬挂点（2026-09-13）

> 规格 §8 二阶段。M0–M5 已合 `main`。本阶段打开线层与注记的原生会话，
> 并把 `QgsGeometryDangleCheck` 纳入检查器。

## 落地清单

| 实现件 | 位置 | 说明 |
|---|---|---|
| 原生会话资格 | `composite_editing._native_session_eligible` | `polygon`/`line` 一律；点层仅 `map_annotation` / `interpretation_annotation` |
| 悬挂点规则 | `map_stack_service.cpp` + `TopologyChecker.run` | 默认 rules 含 `dangle`；仅线几何；`fixable=false`，修复=导航 |
| 面板过滤 | `topology_checker_panel._RULE_LABELS` | 「线悬挂点」 |
| 桥版本 | `bindings.cpp` `__version__` | 0.10.0a0 → **0.11.0a0** |

## 验收证据

- `tests/test_topo_phase2.py`：线约束/综合相/注记资格；非注记点层仍走 Python；默认规则含 dangle。
- `tests/test_qgis_topo_phase2.py`（真桥）：开线报悬挂点；闭合环无悬挂；线层 `startEditing`。

## 二阶段补完（框选 / 追踪交点 / 验收钉）

| 实现件 | 位置 |
|---|---|
| 框选多节点 | `PwbVertexTool` 空处拖框 → 蓝框选中；拖其中一点平移同一向量 |
| 选区编辑 | `Delete` 删除选中节点（同位置只删一次）；`Esc` 或重新框选清空；平移后选区随动 |
| 追踪交点插点 | `QgsTracer::setAddPointsOnIntersectionsEnabled` 随追踪开关 |
| 16 场景索引 + 真实工程周期 | `tests/test_topo_acceptance_cycle.py` |

悬挂点仍无几何自动修复（原生 `NoChange`）。

三重门：① M0–M5 验收锚点全绿（16 场景各有自动化钉，索引见
`test_topo_acceptance_cycle.SCENARIO_COVERAGE`）；② 真实工程
建稿→编辑→检查→保存→导出周期已自动化；③ 用户体验签字仍待人工确认。
