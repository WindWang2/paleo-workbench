# progress — vector-perf-increment 会话日志

## 2026-09-14（会话 1）

- worktree `../paleo-workbench-vector-perf` @ `feat/vector-perf-increment`
  （自 `main` e7214566）；geo-viz-engine 子模块已 init。
- 桥 .pyd 本地构建成功（vendor 复用，`--parallel 2`，约 5 分钟）。
- 发现并移植主仓未提交 loader 修复（VENDOR 配方 geo/C DLL 预加载），
  否则 worktree 桥 import 即 `ERROR_PROC_NOT_FOUND`。提交 0174451a。
- **既有崩溃（非本分支）**：命中共享节点的 press / ≥20k 顶点 press
  访问冲突；`test_qgis_topo_m1_native_editing.py::test_scenario5` 单测
  亦崩（主 .pyd 同崩）。主仓 vendor 今日 14:09 被并行会话重建，疑似其
  回归；域属 prompt-1。决策见 00-D8。
- Phase 1 基线实测完成（01-perf-baseline.md）：snap 0.13ms@1k /
  1.09ms@10k（手势级，≤10k 因上述崩溃）；topo 7.4ms@1k / 179.5ms@10k /
  **4,029ms@50k**，复检=全量重扫；render 28.8ms@2k面 / 158.7ms@10k面；
  ffi 全 JSON（153ms 单要素发布、344ms delta 应用、265ms 读回）。
- Phase 1 五份文档（00–04）落地并提交。

## 错误台账

| 错误 | 尝试 | 解决 |
|---|---|---|
| worktree 桥 import `ERROR_PROC_NOT_FOUND` | 1: 对比 dumpbin 导入表（两 .pyd 完全一致，qgis_core.dll 导出无缺） | 根因：进程内其他扩展按基名抢占 geo/C DLL；移植主仓 loader 预加载修复 |
| standalone 基准脚本段错误 | 1: bash 直跑 | 既有 Qt/CPython 终结化崩溃域；改走 pytest（pytest-qt 生命周期） |
| QTest press 手势崩溃（v20k 起 + 命中共享节点） | 1: 对齐 M1 测试模式（回调/4326/400px/press-move-release）仍崩；2: 空点 press（不命中）10k 内稳定 | 既有 vendor 回归；SLA 证据改微基准绑定 + 手势测试限 ≤10k（00-D8） |
