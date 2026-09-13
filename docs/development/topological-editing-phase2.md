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

## 仍不在本阶段

- 线悬挂点无几何自动修复（原生 `NoChange`）。
- 规格三重门的人工全周期回归 / 用户体验签字。
