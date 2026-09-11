# 02 — Action Surface Inventory（M1 矩阵）

## 动作 × 表面矩阵（V10 后状态）

| Action（组） | Toolbar | Palette | Layer Menu | Canvas Menu | Shortcut | Stage | Inspector |
|---|---|---|---|---|---|---|---|
| navigate（7） | ✓ | map:* | — | ✓ | — | — | — |
| selection（5） | ✓ | map:*（部分） | — | ✓ | — | — | — |
| inspection（2） | ✓ | map:identify/measure | — | ✓ | — | — | — |
| edit_session（3） | ✓ | map:* | 开始/停止编辑 | ✓ | Ctrl+S(save) | — | 推荐动作行 |
| capture（3） | ✓+preferred | —（快照不可判 kind 会话细节；执行面覆盖） | — | — | — | — | 推荐动作行 |
| geometry（9） | ✓ | map:split/merge/reshape（V10 新增） | 修复几何 | — | Delete/Ctrl+Z | — | — |
| snapping（3） | ✓ | map:snapping/topology | 参与捕捉(引用) | ✓+捕捉设置… | Esc(cancel) | — | — |
| layer（6） | ✓ | map:* | 属性表/属性/符号/标注/导出/缩放 | ✓(部分) | — | — | 样式编辑钮 |
| symbology（2） | ✓ | map:* | 符号系统… | — | — | — | — |
| factor（2） | 阶段② | map:* | — | — | — | ✓ | — |
| qa（2） | ✓ | map:* | — | — | — | ✓ | — |
| layout_export（1） | 阶段③ | map:map_export | — | — | — | ✓ | — |

## 门禁一致性（V10 后）

* **Toolbar / Overflow / Palette / Shortcut / Canvas Menu**：同一批
  `MapActionController` QAction——enable/visible/判词零漂移（画布菜单直接
  挂同一 action 实例；palette applicability 经同一 evaluator + 判词透传）。
* **Layer Menu（回退树）**：`layer_menu_facts` 探针（evaluator 投影）；
  RAW/冻结/组锁/阻塞判词直达菜单 tooltip；执行 re-gate 同源。
* **Layer Menu（原生树）**：C++ 侧组合按 `pwb/editable` 身份旗标（菜单项
  enable 无法从 Python 覆写，无桥 API）——执行 re-gate（完整 evaluator）
  是权威，拒绝以状态条判词可见（已知限制，见 13）。
* **Stage Panel**：无 per-item 门禁（执行统一 re-gate + 判词状态条）。
* **Inspector**：推荐动作行 = evaluator 结论（`_recommended_action_text`）。

## 残余独立判断（记录在案，非业务门禁）

* 树缩放 `has_extent` 有效性判据（呈现层有效性，执行侧同判据）。
* `remove_button` 的 `metadata.editable` 身份判断（结构性删除≠数据编辑）。
* 面板菜单/视图开关（UI 状态动作，无业务语义）。
* Agent 面板 WRITE 授权（harness 权限体系，与 evaluator 正交）。
