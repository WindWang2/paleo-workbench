# 11 — Known Limitations（V10）

随实现更新；诚实记录，不粉饰。

## 继承自 V7–V9（未翻案）

1. undo 栈无界（V7 08-14，接受）。
2. EditDelta journal 1024 滑窗、非持久化（V7 08-11，by design）。
3. compound 组持强引用至 256 逐出/会话结束（V8 08-5）。
4. `canvas_destination_crs` 在 worktree 配方（vendor 缺 proj.db）返回 ""
   ——digitize CRS 守卫仅在 PROJ 数据可用处生效（V9 09-1）。
5. measure 工具 mirror 降级角落用 project CRS（V9 09-3）。
6. 命令面板不含 split/merge/reshape（context-control-plane 08-1）。
7. grid snapping 仅 Python fallback，不推 QGIS（V7 08-4）。
8. legacy `map_edit_scene.py` 第二编辑面（validator/migration 定位，
   "Phase 3" 移除计划挂起）。
9. 捕获 scratch 层是系统内唯一 `startEditing` 的 QGIS 层（不落盘，
   构造要求 isEditable）。

## V10 新增记录

（随实现填写：vertex insert/delete 不回填 fallback；插入/删除顶点不做
跨层拓扑传播；move 工具无目标 snap；Z/M 系统性 2D；等）
