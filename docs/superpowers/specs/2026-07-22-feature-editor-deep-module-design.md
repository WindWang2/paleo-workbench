# 事务型 FeatureEditor 深层矢量编辑模块设计规范

日期：2026-07-22
状态：已确认 (经 /improve-codebase-architecture 深度访谈闭环)
落点：`paleo_workbench/mapping/feature_editor.py`
关联：`CONTEXT.md`

---

## 1. 背景与目标

在古地理图件绘制中，地相多边形 (FaciesPolygon) 的编辑（包括拾取、顶点拖拽、边界吸附、邻接多边形共享节点联动以及拓扑闭合校验）原先分散在 `map_edit_api.py` 的 10+ 浅层 API 函数以及 UI 控件 `MapCanvasWidget` 鼠标事件响应逻辑中。

这种分散架构导致：
1. **测试困难**：无法在脱离 UI 的情况下独立测试多要素共享节点移动与复杂的拓扑状态。
2. **缺乏拓扑保证**：如果 UI 漏掉某些校验步骤，容易在项目文件中保存自相交或非闭合的非法多边形。

本规范定义了 **事务型 `FeatureEditor` 深层模块**，将图层级选择、顶点拖拽、吸附捕捉、共享节点同步移动、拓扑自动回滚以及 Undo/Redo 事务栈完整收拢在一个深层模块之后。

---

## 2. 核心架构与拓扑约束

### 2.1 图层级状态管理 (Layer-Level Management)
- `FeatureEditor` 绑定整层 `FeatureCollection`。
- 建立 spatial R-Tree / Bounding Box 索引，实现 $O(\log N)$ 级的快速拾取 (Hit Test) 与吸附对齐。
- 自动识别并维护相邻多边形之间坐标完全重合的**共享节点 (Coincident Nodes)**。

### 2.2 强拓扑不变性约束 (Strict Topology Invariants)
- **首尾闭合约束**：多边形外环必须保持 `ring[0] == ring[-1]`。
- **有效顶点防护**：多边形外环有效独立顶点必须 $\ge 3$ 个。
- **非自相交校验与自动回滚**：顶点移动、插入或删除后触发 `validate_ring` 与自交叉检查。若检查失败，抛出 `TopologyError` 异常并自动执行 `rollback()` 还原至变动前的合法拓扑状态。

---

## 3. 组件接口契约

在 `paleo_workbench/mapping/feature_editor.py` 中导出 `FeatureEditor` 与 `TopologyError`：

```python
class TopologyError(Exception):
    """Raised when a geometry edit breaks topology invariants."""
    pass


class FeatureEditor:
    """Stateful, transactional layer-level map geometry editor module."""

    def load_layer(self, feature_collection: dict[str, Any] | list[dict[str, Any]]) -> None:
        """加载图层数据并建立空间索引与共享节点关系."""
        ...

    def select_at(self, x: float, y: float, tolerance: float = 5.0) -> dict[str, Any] | None:
        """点击拾取最近的多边形要素及顶点."""
        ...

    def move_selected_vertex(self, x: float, y: float, snap: bool = True, snap_tolerance: float = 5.0) -> bool:
        """移动选中顶点（同步联动所有重合共享节点，带吸附与 TopologyError 自动回滚）."""
        ...

    def add_vertex(self, feature_id: str, x: float, y: float) -> bool:
        """在多边形环中插入新顶点."""
        ...

    def delete_vertex(self, feature_id: str, vertex_index: int) -> bool:
        """删除多边形顶点（带 >= 3 顶点防护与自动回滚）."""
        ...

    def commit(self) -> None:
        """提交当前事务变动，入栈 Undo/Redo 历史."""
        ...

    def rollback(self) -> None:
        """回滚当前未提交变动."""
        ...
```

---

## 4. 测试与验证策略

1. **共享节点联动测试 (`tests/test_feature_editor.py`)**：
   - 验证移动相邻多边形 A 的重合顶点时，多边形 B 的对应顶点同步移动，无缝无空隙。
2. **拓扑异常回滚测试**：
   - 验证拖拽顶点产生自相交时抛出 `TopologyError`，且坐标自动还原为移动前的合法状态。
   - 验证尝试删除顶点使多边形少于 3 个顶点时拒绝删除。
3. **全库回归验证**：
   - 确保 `pytest` 全量测试套件 100% 保持绿色。
