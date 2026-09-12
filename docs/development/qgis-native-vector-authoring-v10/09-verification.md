# 09 — Verification（V10）

随实现更新；最终态见文末"执行记录"。

## A. 环境与入口

- venv：本 worktree `.venv`（Python 3.12.13 + PySide6 6.8.3 + pybind11 3.1.0
  + shapely/scipy/pyproj/PyOpenGL）。
- bridge：`PALEO_QGIS_REUSE_VENDOR=1` 复用 v7 vendor build，
  `0.5.0a0 → V10 后 bump`。
- fallback 腿：`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest -q <files>`。
- QGIS 腿：`PALEO_QGIS_BUILD_DIR=<v7 vendor> .venv/Scripts/python.exe
  scripts/run_qgis_env.py -q -m qgis <files>`。

## B. 基线（实现前，2026-09-11）

- fallback 编辑族 13 文件：**325 passed, 1 skipped**。
- QGIS 编辑族 13 文件：**70 passed, 4 deselected**（deselect 为非本族标记）。

## C. V10 新增测试计划

> 表内文件名为**实际仓库文件名**（V10 review follow-up #1261：此前本表列的
> `test_v10_vertex_path_adversarial.py` / `test_qgis_v10_vertex_tools.py` /
> `test_qgis_v10_snap_feedback.py` / `test_v10_tool_surface.py` 四个文件在
> 仓库中并不存在；其内容实际落在下表的合并文件里，已按实况校正）。

| 文件 | 内容 | 腿 |
|---|---|---|
| `tests/test_v10_vertex_ring_invariants.py` | ring 闭环维护（set/insert/delete 首/尾/中间顶点；MultiPolygon 深嵌套；开放线不动；最少顶点守卫；undo 恢复闭合）；`[ring,v]`/`[part,v]`/`[part,ring,v]` 对抗寻址；内环；多点 multipart；越界路径拒绝 | pure |
| `tests/test_v10_session_command_family.py` | duplicate/add_part/delete_part/move_part/explode/collect/add_ring/delete_ring 全 undo/redo/rollback/delta 映射/审计 | pure |
| `tests/test_v10_transaction_invariants.py` | 一个动作=一个 undo 单元矩阵；undo/redo 无 delta；rollback 作废 journal；#1257 定位器失效（全量分支调用 + helper 单一来源源码扫描）；镜像写路径限定 bridge | pure |
| `tests/test_qgis_v10_edit_tools.py` | native 双击插点 / Delete 删点 / hover marker / 最少顶点拒绝 / `vertex_delete_rejected` 回执 / snap_feedback payload / 回调 payload 契约 | qgis |
| `tests/test_qgis_v10_capture_flow.py` | 捕获过程回调（当前坐标/段长/总长）；Backspace 撤销顶点；self-snapping；topological 捕获共享节点 | qgis |
| `tests/test_qgis_v10_geometry_part_ops.py` | bridge add_part/delete_part/collect/add_ring 语义（多类型、错误输入 fail-closed） | qgis |
| `tests/test_v10_edit_paths_callcount.py` | D 节 call-count 契约（选集单趟/memo；native vertex 三操作每手势 1 undo 单元 + 1 bump；拒绝手势零残留） | 两腿 |
| `tests/test_v10_editing_lifecycle.py` | 捕获中切层/切阶段/会话关闭/CRS 变更；新回调在 canvas 重建后不悬挂 | 两腿 |
| `tests/test_authoring_ux_v10.py` | 新工具 id 可用性矩阵 + 禁用原因 + 无第二 evaluator；登记处词表互等；图标资产可解析 | pure |
| `tests/test_v10_review_fixes.py` | 回归钉：#1258 edit-pick 分发层、#1259 多选单 undo 单元、#1264 拓扑计数刷新点 | pure |

## D. 执行记录

（随里程碑更新）
