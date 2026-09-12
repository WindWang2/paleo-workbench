# 拓扑编辑迁移 M5 退休与评估——实施记录（2026-09-12）

> 规格 §8 → §2。M5 内容：Python 拓扑传播 / 复合撤销组下线。
> 退出标准：无双轨残留；M0–M4 回归绿。悬挂点规则不在本里程碑。

## 落地清单

| 实现件 | 位置 | 说明 |
|---|---|---|
| 停 Python 共享节点传播 | `TopologyService` 删除 `propagate_shared_vertex`；工作站/编图页顶点工具不再挂回调 | 跨层拓扑改由原生顶点「全部层」档 + 拓扑点散布承担 |
| 停复合撤销组 | 删除 `CompoundUndoGroup` / `undo_compound` / `redo_compound` | Python 会话 undo = 单层 `undo_stack`；原生会话仍走手势管理器 |
| 校验保留 | `TopologyService.validate` / `validate_records` + M4 `checker` | 无桥回落 Shapely；有桥走检查器门禁 |
| 错误计数 | `record_validation` / `cached_error_count` 保留 | 工具条 topology_error_count 生产者不变 |

## 验收证据

- `tests/test_topo_m5_retirement.py`：生产模块无 `propagate_shared_vertex` / `CompoundUndoGroup` / `pending_compound`。
- 宿主：M0/M1/M3/M4 + M5 retirement 绿。
- 真桥 `-m qgis` M1–M4：22 passed。

## 二阶段推广评估（三重门）

规格 §8：M0–M5 全绿后须过三重门才开线层/悬挂点。当前结论：**未过**。

1. 16 场景全量人工回归未在本里程碑重跑（本机钉的是 M0–M4 自动化 + 无双轨残留）。
2. 无真实相图工程完整编辑周期验收。
3. 无用户体验确认。

`TopologyService` 类名仍作 validate + M4 checker 持有者（无桥回落）；传播/复合撤销面已删。
