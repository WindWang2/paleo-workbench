# 03 — QGIS 树权威与桥扩展

## 权威边界（§9）

**运行时**显示/排序/组结构权威 = QGIS Layer Tree（`QgsProject::instance()
->layerTreeRoot()`）。领域侧（`mapping_workspace`）只保存稳定元数据（角色/
成员资格/组 id/阶段视图状态），经增量 reconcile 驱动 QGIS；用户树操作经
typed 事件回写领域——两侧永不对抗：

- 程序化变更：C++ `SuppressGuard` 抑制回声（既有机制）；
- 用户变更：schema 2 事件 → 领域更新 → 下次 reconcile 以领域为准。

`LayerTreeSnapshot` 只是可序列化领域表示（期望树/观察投影/持久化载体），
绝不能发展成第二棵运行时可变树。

## C++ 桥新增 API（`map_stack_service.*`）

| API | 语义 |
|---|---|
| `upsert_group(gid, name, parent)` | 幂等建组/改名/重挂（子树保护） |
| `remove_groups_except(gids)` | 删未列组；**子节点先上提，绝不注销图层** |
| `rename_group` / `set_group_visibility` | 组改名/勾选（程序化，建立影子基线） |
| `move_layer_to_group(doc, gid, i)` | 图层放置（registry bridge detach） |
| `move_group(gid, parent, i)` | 组重挂（禁止移入自身后代；子树保护） |
| `apply_tree_placements(json)` | **批量放置**：一次遍历建索引 + 一次画布同步（O(N)） |
| `tree_snapshot_json()` | 全层级观察快照（深度优先，渲染序） |
| `set_group_expanded(tree, node, on)` | 组展开态恢复（节点级 `setExpanded`） |
| `set_tree_expand_callback` | 节点级 `expandedChanged` 接线（仅组节点） |

### 上游陷阱与防护（实现记录）

1. **`takeChild` 隐藏语义**：`removeChildrenPrivate` 先递归卸下被移动节点
   的全部后代（`makeOrphan`）——对带子组的组直接调用会摧毁子树。防护：
   `detachGroupSubtree`（后序卸载）→ 搬空组 → `restoreGroupSubtree`。
2. **registry bridge 计数不受 `setEnabled` 控制**（#1154）：组删除/移动
   期间必须整体 detach root 的两个槽（`RegistryBridgeDetach` RAII）。
3. **性能**：逐个 `move_*` 是 O(N²)（每次全树 find + 全画布 sync）——
   `apply_tree_placements` 批量路径一次建索引、一次同步。

## 树事件 schema 2（§47）

legacy 键保持不变（`visibility`/`order`/`renames`，平铺图层语义），追加：

```json
{"schema": 2,
 "events": [{"type": "visibility"|"rename",
             "node_type": "layer"|"group", "node_id": "...", "value": ...}],
 "tree": [{"type": "group", "id": "gid", "name": "...", "visible": true,
            "children": [...]}, ...]}
```

`tree` 只在结构变化（拖拽/建组/删组）时携带，一次性覆盖 move/group-create/
group-delete——Python 侧对结构化节点数组 diff（`parse_tree_events`），
无字符串拼接解析。组事件依赖影子表基线（`upsert_group` 同步建立可见性
基线，否则首次勾选被当「首次见面」吞掉）。

## XML 信封（§49）

`writeProjectXml` 天然包含组结构（custom property 随 QgsProject 序列化）；
`applyProjectXml` donor 层级遍历：先样式/可见性，再按 donor 出现序恢复组
（父先于子，嵌套父级保留），最后恢复图层放置。要素仍在 Python
（user_vector_layers）——XML 只是呈现态信封（既有契约不变）。
