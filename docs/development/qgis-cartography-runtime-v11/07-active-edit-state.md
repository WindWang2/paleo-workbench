# 07 — Active / Edit State (V11)

## 1. 五目标模型

`EditTargetSnapshot`（`edit_targets()` 唯一查询入口）：

| 目标 | 含义 | 来源 |
|---|---|---|
| selected_tree_node | 树选中节点（信息性） | 面板回写（note_tree_selection） |
| active_map_layer | 画布当前图层 | set_active_layer（原生 select/identify 目标） |
| edit_target_layer | 唯一编辑目标 | 会话层（有手势）/ 活动图层（无手势） |
| tool_target_layer | 工具实际写入层 | 持有会话的工具 → 会话层 |
| selection_layer | 选择集上下文 | 活动图层 |

## 2. #1268 收敛

V10 review #1 钉死语义保持：armed 捕获工具跨目标切换保持会话（同步链
瞬时切层不劫持数字化；切割线跨层工作流依赖会话跨切换存活）。V11 的收敛
是**建模并呈现**分歧，而非改变保持语义：

* 手势进行中：tool/edit 锁定会话层，`divergent=True`；
* 状态块显示「数字化目标 A（树选中 B）」——绝不把树选中呈现成编辑目标
  （D2-ui 关闭）；
* `last_switch_block_reason` 记录信息性说明；
* 无工具持有旧会话 → 切换零副作用。

## 3. 不变式（测试钉死）

无手势：四目标一致（divergent=False）。手势中：tool/edit=会话层，
active=新选中，分歧诚实。会话跨切换存活（切回可用）。
