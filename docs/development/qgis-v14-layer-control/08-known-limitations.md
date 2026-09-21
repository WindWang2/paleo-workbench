# 08 — Known Limitations

每条给依据与后续路径；P2 级未修项在此登记（07 处置记录互引）。

## 1. `map_qgis_project_xml` envelope 的原生 apply 未实现

原生 `MainWindow::openProject` 不消费 envelope（样式经 sidecar 恢复；
顺序/组/可见性由 `state.tree` reconcile 恢复——Python 侧「领域树覆盖
envelope 平铺序」的既有权威顺序一致）。桥的
`applyProjectXml/writeProjectXml` 继续服务遗留 GUI。
后续：平台侧 envelope 写入可在 save 时经 stack 序列化补齐（本线
`QgsLayerTreeStack` 已具备树结构面）。

## 2. 实时树模型信号写回（observe）仅 save 时采纳

用户拖拽在保存时经快照写回（含角色校验与最小 diff re-reconcile，
E2E 探针证实 reopen 保序）；**编辑会话中的实时**结构回声（拖拽即刻
落期望树）需要 QgsLayerTreeModel 信号接线——Qt 侧代码，本机无 QGIS
SDK 不可编译验证，留作 Prompt-2 图层面板集成点。glue 头注释已声明。

## 3. QGIS/平台侧 TU 本机未编译（环境无 vendored SDK）

`layer_tree_stack.cpp`、main_window glue、canvas_shim 修改、panel 状态
块按桥已验证模式编写并经两轮独立 review（Round 2 对照 vendored SDK
源码逐行核对 takeChild/removeChildrenPrivate 语义与信号签名），
但**未经编译器验证**——与 #1434/#1435 PR 同一环境限制。首次有 SDK 的
CI/开发机需跑 `05-test-plan §3` 清单。

## 4. 与 Python 的有意分歧（记录，不改）

- `bound_at`：写侧在 pin/重钉时盖 `now_iso8601`（conv-26 既有
  `mutations.cpp` 行为，锁定于既有 data 测试）；Python 保留 caller
  原值。C++ 侧时间戳语义更严（绑定事件必有发生时间）。
- diff/planner 的 map 迭代为键序（Python 插入序）：applier 对同父
  创建顺序不敏感；未来做 byte 级 fixture 对比时需排序后比。
- `key_of` 无键回退 node id（Python 在 children 排序处同样回退 id；
  其 root by_key 处回退 ""——两侧实际路径均先经 assign_keys 赋键，
  回退不触发）。

## 5. 组 id 词汇：QGIS 侧铸造 `user_<uuid>`

`ensureGroupNodeId` 为 QGIS 内建组铸造 `user_<uuid>`（桥继承）；契约
§9 的 `user.` 前缀指领域侧铸造（`create_user_group` 用的就是
`user.<hex>`）。两词汇并存与桥现状一致；统一需要桥协同（跨线）。

## 6. diff 的宿主义务：实际树不得残留 desired 外的图层节点

keyed-LCS diff 只发 move，不发 layer 移除（Python 同源设计：图层删除
由宿主经 mirror `remove_mirror_layers_except` 完成）。若实际树残留
陈旧节点，兄弟序可能错乱（Round 2 穷举场景 C）。原生路径 openProject
只添加绑定层 + save 前 observe，当前无残留路径；将来新增树写入口时
必须维持「先物理移除、后 reconcile」义务（代码注释已声明）。

## 7. root 级 O(R²) 去重与杂项热点（有界）

`build_plan` root_mixed 去重、`place_copy_adjacent`、
`remove_user_group`、`ensure_memberships` 陈旧扫描为线性扫（Python 同
源）；规模上界受 root 松散层数/组数约束（1000 层预算下层在组内）。
contract §8 的主断言（单窗口/单清扫/单批量放置/无 per-move）不受影响。

## 8. `tests/cpp/data` 平台目标链接的既有配置问题

`PWB_BUILD_PLATFORM=OFF + BUILD_TESTING=ON` 时 `data.catalog_closure`
无条件链接平台目标 → configure 失败（A/B 验证为 main 既有，#1435 租约
范围）。本线测试挂 `libs/workspace/workspace_tests`，data 闭包库构建
（BUILD_TESTING=OFF）不受影响。

## 9. 编辑会话 dirty fail/close 的宿主策略

`LayerTargets::revalidate` 报告 dropped_dirty_editing（宿主须 fail/close
会话）；平台 glue 在打开路径调用（新开工程不可能有 dirty 会话）。
运行中删除图层的接线属编辑面（Prompt-2/编辑线）。

## 10. expand 态的阶段化（QSettings）未接

展开态经树持久化跨重开保留（Round 2 R2-4 修复）；Python 的按阶段展开
偏好（QSettings 分域）未移植——原生无 QSettings 宿主，留待面板集成。
