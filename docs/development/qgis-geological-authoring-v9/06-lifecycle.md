# 06 — Lifecycle（V9）

## 1. V9 新增生命周期面与守卫

| 新面 | 守卫 |
|---|---|
| role lookup 注入（`set_role_lookup`） | 查询异常全捕获（`role_of_layer` 返回 ""）；每次快照/捕获默认派生即时重查（无缓存漂移） |
| 捕捉 profile per-layer 覆盖 | 工程切换层集全替换时 `load_from_project` 清空四通道（lifecycle 压测发现的真 bug，已修）；单层删除路径 V9 前已清 |
| 拓扑计数缓存 | 会话身份入条目（新会话=未校验）；rollback/层删除/工程切换三路径 forget |
| digitize CRS 守卫钩子（shim `_capture_layer_crs_provider`） | bound-method 强引用（与 `_tool_controller` 同形态）；`_on_digitize` 的 weakref + `_shutdown_done` 守卫先行，provider 最坏返回 ""（不比对） |
| `canvas_scale`/`canvas_destination_crs` 探针 | `getattr` 探针 + 异常全捕获 + shutdown 态短路；旧桥返回 0.0/""（诚实未知） |
| 测距工具 Geod | 工程切换时 CRS 变更后显式重建（`measure_distance` 不在 rebind 集合）；`Geod.inv` 异常回退平面 |
| 属性表排序/差量 | 排序期间禁排更新（review-2 P1-1）；新字段出现列缓存失效 |

## 2. QTimer / QObject（复核）

V9 diff 零新增 `QTimer.singleShot` / 裸单射；`#1247` 的 context 绑定模式
未被触碰。conftest 的 timer fence（#951）在最终回归中全程无崩溃。

## 3. 压测矩阵（`tests/test_v9_lifecycle_perf.py`）

- 100× 建层（带角色+会话+计数）→ 删除：层数/缓存/profile 全回收；
- 50× 计数刷新：每层恰一条目（覆写不累积）；
- 30× 工具激活 + 上下文构建：v3 事实稳定不漂移；
- 工程重载：旧层 profile 不复活（修复后的回归钉）；
- blocking 采集：无调度器环境安全返回 ""。

既有 qgis-marked 压测（`test_qgis_lifecycle_stress_v8`：100× 工程切换 /
工具循环 / 树重建 / 指示器共存 / StackEvents 析构竞态）在 0.5.0a0 桥上
全部通过（见 08 验证记录）。
